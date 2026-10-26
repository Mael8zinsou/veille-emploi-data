"""Client Google Sheets minimal, aux écritures sûres (conception § 8.2).

Le fichier de suivi est l'outil de travail quotidien de Maël. Règles appliquées ici, pas
seulement documentées :

* toute valeur est écrite en `RAW` : un titre d'offre qui commence par « = » reste du texte,
  jamais une formule (pas d'injection de formule par une annonce) ;
* `ajouter_onglet` refuse un onglet qui existe déjà : rien n'est écrasé ;
* `ecrire_cellules_vides` relit avant d'écrire et refuse toute cellule déjà remplie ;
* pas de suppression, pas d'effacement de plage.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import quote

API = "https://sheets.googleapis.com/v4/spreadsheets"


class ErreurSheets(Exception):
    pass


def session_depuis_env():
    """Session autorisée à partir du jeton OAuth (GOOGLE_TOKEN_JSON), rafraîchi à la volée."""
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    info = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
    creds = Credentials.from_authorized_user_info(info)
    creds.refresh(Request())
    return AuthorizedSession(creds)


@dataclass
class ClientSheets:
    session: object
    sheet_id: str

    @classmethod
    def depuis_env(cls) -> ClientSheets:
        sheet_id = os.environ.get("SUIVI_SHEET_ID", "").strip()
        if not sheet_id:
            raise ErreurSheets("SUIVI_SHEET_ID absent")
        return cls(session_depuis_env(), sheet_id)

    # ------------------------------------------------------------------ bas niveau

    def _verifier(self, r, action: str):
        if r.status_code >= 400:
            raise ErreurSheets(f"{action} : HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.text else {}

    def onglets_detail(self) -> dict[str, dict]:
        r = self.session.get(f"{API}/{self.sheet_id}",
                             params={"fields": "sheets.properties(title,sheetId,gridProperties.rowCount)"})
        donnees = self._verifier(r, "lecture des onglets")
        return {s["properties"]["title"]: {"id": s["properties"]["sheetId"],
                                           "lignes": s["properties"].get("gridProperties", {}).get("rowCount", 0)}
                for s in donnees.get("sheets", [])}

    def onglets(self) -> dict[str, int]:
        return {t: d["id"] for t, d in self.onglets_detail().items()}

    def lire(self, plage: str, rendu: str = "FORMATTED_VALUE") -> list[list]:
        r = self.session.get(f"{API}/{self.sheet_id}/values/{quote(plage)}", params={"valueRenderOption": rendu})
        return self._verifier(r, f"lecture de {plage}").get("values", [])

    def _ecrire(self, plage: str, valeurs: list[list]) -> None:
        r = self.session.put(f"{API}/{self.sheet_id}/values/{quote(plage)}", params={"valueInputOption": "RAW"},
                             json={"range": plage, "majorDimension": "ROWS", "values": valeurs})
        self._verifier(r, f"écriture de {plage}")

    def _lot(self, requetes: list[dict]) -> dict:
        r = self.session.post(f"{API}/{self.sheet_id}:batchUpdate", json={"requests": requetes})
        return self._verifier(r, "mise à jour")

    # ------------------------------------------------------------------ opérations sûres

    def ajouter_onglet(self, titre: str, lignes: list[list], colonnes_masquees: tuple[int, ...] = (),
                       liste_deroulante: tuple[int, list[str]] | None = None, largeurs: dict[int, int] | None = None) -> int:
        """Crée un onglet neuf et y écrit `lignes` (la première est l'en-tête). Refuse s'il existe."""
        if titre in self.onglets():
            raise ErreurSheets(f"l'onglet « {titre} » existe déjà : rien n'est écrit")
        nb_col = max(len(lg) for lg in lignes)
        rep = self._lot([{"addSheet": {"properties": {"title": titre, "gridProperties": {
            "rowCount": max(len(lignes) + 20, 100), "columnCount": nb_col, "frozenRowCount": 1}}}}])
        sheet = rep["replies"][0]["addSheet"]["properties"]["sheetId"]
        self._ecrire(f"'{titre}'!A1", lignes)
        requetes: list[dict] = [{"repeatCell": {
            "range": {"sheetId": sheet, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}}]
        for col in colonnes_masquees:
            requetes.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
        for col, px in (largeurs or {}).items():
            requetes.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})
        if liste_deroulante:
            col, options = liste_deroulante
            requetes.append({"setDataValidation": {
                "range": {"sheetId": sheet, "startRowIndex": 1, "endRowIndex": len(lignes),
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in options]},
                         "showCustomUi": True, "strict": True}}})
        self._lot(requetes)
        return sheet

    def ajouter_lignes(self, onglet: str, lignes: list[list], premiere: int = 2,
                       cases_a_cocher: int | None = None) -> int:
        """Ajoute `lignes` après la dernière ligne remplie (colonne A), sans rien écraser.

        Rend le numéro de la première ligne écrite. `cases_a_cocher` : index de colonne qui
        reçoit une case à cocher sur les lignes ajoutées. Agrandit l'onglet si besoin.
        """
        if not lignes:
            return 0
        colonne_a = self.lire(f"'{onglet}'!A{premiere}:A")
        debut = premiere + len(colonne_a)
        fin = debut + len(lignes) - 1
        largeur = max(len(lg) for lg in lignes)
        derniere_col = chr(ord("A") + largeur - 1)
        if any(any(str(v).strip() for v in lg) for lg in self.lire(f"'{onglet}'!A{debut}:{derniere_col}{fin}", "FORMULA")):
            raise ErreurSheets(f"{onglet} : les lignes {debut} à {fin} ne sont pas vides, rien n'est écrit")
        detail = self.onglets_detail()[onglet]
        requetes: list[dict] = []
        if fin > detail["lignes"]:
            requetes.append({"appendDimension": {"sheetId": detail["id"], "dimension": "ROWS",
                                                 "length": fin - detail["lignes"] + 500}})
        if requetes:
            self._lot(requetes)
        self._ecrire(f"'{onglet}'!A{debut}", lignes)
        if cases_a_cocher is not None:
            self._lot([{"setDataValidation": {
                "range": {"sheetId": detail["id"], "startRowIndex": debut - 1, "endRowIndex": fin,
                          "startColumnIndex": cases_a_cocher, "endColumnIndex": cases_a_cocher + 1},
                "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}}])
        return debut

    def ecrire_cellules_vides(self, onglet: str, cellules: dict[str, object]) -> None:
        """Écrit chaque cellule (« B7 » -> valeur) seulement si elle est vide à la relecture."""
        for adresse, valeur in cellules.items():
            plage = f"'{onglet}'!{adresse}"
            actuel = self.lire(plage, "FORMULA")
            if actuel and actuel[0] and str(actuel[0][0]).strip():
                raise ErreurSheets(f"{plage} n'est pas vide : rien n'est écrit")
            self._ecrire(plage, [[valeur]])
