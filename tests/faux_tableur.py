"""Faux Google Sheets en mémoire, fidèle aux comportements qui comptent ici.

* Les plages suivent la notation A1 (« 'Onglet'!A5:A300 », « 'Onglet'!B7 », « 'Onglet'!A2:O »).
* Comme l'API réelle, la lecture rogne les cellules et lignes vides en fin de plage.
* Les écritures `RAW` sont conservées telles quelles (une chaîne « =1+1 » reste une chaîne).
* `batchUpdate` gère addSheet, appendDimension, setDataValidation et les mises en forme.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

from tests.conftest import Reponse

_A1 = re.compile(r"^'?(?P<onglet>.+?)'?!(?P<c1>[A-Z]+)(?P<l1>\d+)?(?::(?P<c2>[A-Z]+)(?P<l2>\d+)?)?$")


def col_index(lettres: str) -> int:
    n = 0
    for ch in lettres:
        n = n * 26 + ord(ch) - 64
    return n - 1


class FauxTableur:
    def __init__(self):
        self.onglets: dict[str, dict] = {}       # titre -> {"id", "lignes": {i: {j: v}}, "nb_lignes", "validations"}
        self.journal: list[tuple[str, str]] = []

    # ---------------------------------------------------------------- préparation des tests
    def creer(self, titre: str, lignes: list[list], nb_lignes: int = 1000):
        grille = {i: {j: v for j, v in enumerate(lg) if v not in (None, "")} for i, lg in enumerate(lignes)}
        self.onglets[titre] = {"id": len(self.onglets) + 1, "lignes": grille, "nb_lignes": nb_lignes, "validations": []}

    def cellule(self, titre: str, ligne: int, colonne: str):
        """Lecture directe, ligne numérotée comme dans le tableur (1 = première ligne)."""
        return self.onglets[titre]["lignes"].get(ligne - 1, {}).get(col_index(colonne))

    def ligne(self, titre: str, ligne: int) -> dict:
        return self.onglets[titre]["lignes"].get(ligne - 1, {})

    # ---------------------------------------------------------------- API simulée
    def _plage(self, plage: str):
        m = _A1.match(unquote(plage))
        if not m:
            raise AssertionError(f"plage illisible : {plage}")
        o = self.onglets[m["onglet"]]
        c1, c2 = col_index(m["c1"]), col_index(m["c2"] or m["c1"])
        l1 = int(m["l1"] or 1) - 1
        l2 = int(m["l2"]) - 1 if m["l2"] else (l1 if not m["c2"] else o["nb_lignes"] - 1)
        return o, l1, l2, c1, c2

    def get(self, url, params=None):
        if "/values/" in url:
            o, l1, l2, c1, c2 = self._plage(url.split("/values/")[-1])
            valeurs = []
            for i in range(l1, l2 + 1):
                ligne = [o["lignes"].get(i, {}).get(j, "") for j in range(c1, c2 + 1)]
                while ligne and ligne[-1] in ("", None):
                    ligne.pop()
                valeurs.append(ligne)
            while valeurs and not valeurs[-1]:
                valeurs.pop()
            return Reponse(200, {"values": valeurs} if valeurs else {}, text="x")
        return Reponse(200, {"sheets": [{"properties": {"title": t, "sheetId": o["id"],
                                                        "gridProperties": {"rowCount": o["nb_lignes"]}}}
                                        for t, o in self.onglets.items()]}, text="x")

    def put(self, url, params=None, json=None):
        assert params["valueInputOption"] == "RAW"
        o, l1, _, c1, _ = self._plage(url.split("/values/")[-1])
        for di, ligne in enumerate(json["values"]):
            for dj, v in enumerate(ligne):
                o["lignes"].setdefault(l1 + di, {})[c1 + dj] = v
        self.journal.append(("ecriture", json["range"]))
        return Reponse(200, {}, text="")

    def post(self, url, json=None):
        reponses = []
        par_id = {o["id"]: o for o in self.onglets.values()}
        for req in json["requests"]:
            if "addSheet" in req:
                p = req["addSheet"]["properties"]
                self.creer(p["title"], [], p.get("gridProperties", {}).get("rowCount", 1000))
                reponses.append({"addSheet": {"properties": {"sheetId": self.onglets[p["title"]]["id"]}}})
            elif "appendDimension" in req:
                par_id[req["appendDimension"]["sheetId"]]["nb_lignes"] += req["appendDimension"]["length"]
                reponses.append({})
            elif "setDataValidation" in req:
                r = req["setDataValidation"]["range"]
                par_id[r["sheetId"]]["validations"].append(req["setDataValidation"])
                reponses.append({})
            else:
                reponses.append({})
            self.journal.append(("lot", next(iter(req))))
        return Reponse(200, {"replies": reponses}, text="x")
