"""Liens avec le fichier de suivi Google Sheets (cahier des charges § 7.2 à 7.4, conception § 8).

* Lecture des verdicts de l'onglet Entreprises : ils entrent dans la note (« Cible
  prioritaire » +6, « Écarter : nationalité » archive l'offre…). Lecture seule.
* Onglet Veille : chaque offre présentée (alerte ou résumé) y est ajoutée, avec une case
  « Retenir ».
* Transfert : une offre cochée « Retenir » est copiée dans la première ligne libre du bloc de
  l'onglet Candidatures (lignes 5 à 300), sans doublon, puis datée dans « Transférée le ».
* Route B : un employeur final dont une offre a été rejetée pour séniorité ou ancienneté, et
  absent de l'onglet Entreprises, y est ajouté en « À vérifier » (5 au plus par jour).

Mode « essai » (période de test) : le vrai fichier n'est modifié nulle part. Les offres vont
dans l'onglet « Veille (essai) », les cibles Route B dans « Route B (essai) », et aucun
transfert n'a lieu. Les verdicts sont lus dans les deux modes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.normalisation.texte import contient, normaliser
from src.notation import table_verdicts
from src.sorties.sheets import ClientSheets, ErreurSheets

logger = logging.getLogger(__name__)

ENTETE_VEILLE = ["Ajoutée le", "Fil", "Niveau", "Note", "Entreprise", "Poste", "Lieu", "Contrat", "Source", "Raisons",
                 "Signaux", "Lien", "Retenir", "Transférée le", "Clé"]
COL_RETENIR, COL_TRANSFEREE, COL_CLE = 12, 13, 14          # M, N, O
LARGEURS_VEILLE = {0: 120, 1: 85, 2: 75, 3: 50, 4: 180, 5: 340, 6: 160, 7: 80, 8: 100, 9: 300, 10: 150, 11: 90,
                   12: 70, 13: 120}
ENTETE_ROUTE_B = ["Entreprise", "Catégorie", "Verdict Route B", "Secteur / implantation", "Pourquoi ce verdict",
                  "Format d'adresse mail", "Vérifiée", "Date d'ouverture", "Source"]
LIBELLES_SOURCE = {"france_travail": "France Travail", "adzuna": "Adzuna", "hellowork": "HelloWork",
                   "service_public": "Choisir le service public",
                   "la_bonne_alternance": "La bonne alternance"}
LIBELLES_NIVEAU = {"alerte": "alerte", "resume": "résumé"}
LIBELLES_MOTIF = {"seniorite": "trop senior", "trop_ancienne": "offre ancienne"}
BLOC_CANDIDATURES = (5, 300)
ROUTE_B_PAR_JOUR = 5


def _source(sources: str | None) -> str:
    return ", ".join(LIBELLES_SOURCE.get(s, s) for s in (sources or "").split(",") if s)


@dataclass
class Suivi:
    client: ClientSheets
    mode: str = "essai"        # « reel » ou « essai »

    @property
    def onglet_veille(self) -> str:
        return "Veille" if self.mode == "reel" else "Veille (essai)"

    @property
    def onglet_route_b(self) -> str:
        return "Entreprises" if self.mode == "reel" else "Route B (essai)"

    # ------------------------------------------------------------------ lecture

    def verdicts(self) -> dict[str, str]:
        lignes = self.client.lire("'Entreprises'!A5:C600")
        return table_verdicts([(lg[0], lg[2]) for lg in lignes if len(lg) >= 3])

    # ------------------------------------------------------------------ onglet Veille

    def _assurer(self, onglet: str, entete: list[str], **options) -> None:
        if onglet not in self.client.onglets():
            self.client.ajouter_onglet(onglet, [entete], **options)

    def ajouter_a_veille(self, offres: list[dict], quand: datetime) -> int:
        if not offres:
            return 0
        self._assurer(self.onglet_veille, ENTETE_VEILLE, colonnes_masquees=(COL_CLE,), largeurs=LARGEURS_VEILLE)
        date = f"{quand:%d/%m/%Y %H:%M}"
        lignes = [[date, str(o.get("fil") or "").capitalize(), LIBELLES_NIVEAU.get(o.get("niveau"), o.get("niveau")),
                   o.get("note"), o.get("entreprise") or "(non indiqué)", o.get("titre"), o.get("lieu"),
                   o.get("contrat") or "", _source(o.get("sources")), " ; ".join(o.get("raisons") or []),
                   ", ".join(o.get("signaux") or []), o.get("url"), False, "", o.get("cle")] for o in offres]
        self.client.ajouter_lignes(self.onglet_veille, lignes, cases_a_cocher=COL_RETENIR)
        return len(lignes)

    # ------------------------------------------------------------------ transfert vers Candidatures

    def transferer_retenues(self, quand: datetime) -> dict[str, int]:
        """Copie les offres cochées dans Candidatures. Rend {transferees, deja_presentes, bloc_plein}."""
        bilan = {"transferees": 0, "deja_presentes": 0, "bloc_plein": 0}
        if self.mode != "reel" or self.onglet_veille not in self.client.onglets():
            return bilan
        veille = self.client.lire(f"'{self.onglet_veille}'!A2:O", "UNFORMATTED_VALUE")
        a_faire = [(i + 2, lg) for i, lg in enumerate(veille)
                   if len(lg) > COL_RETENIR and lg[COL_RETENIR] is True
                   and (len(lg) <= COL_TRANSFEREE or not str(lg[COL_TRANSFEREE]).strip())]
        if not a_faire:
            return bilan
        d, f = BLOC_CANDIDATURES
        bloc = self.client.lire(f"'Candidatures'!A{d}:C{f}", "FORMULA")
        bloc += [[]] * (f - d + 1 - len(bloc))
        liens = {str(lg[2]).strip() for lg in bloc if len(lg) > 2 and str(lg[2]).strip()}
        libres = [d + i for i, lg in enumerate(bloc) if not any(str(v).strip() for v in lg[:2])]
        for ligne_veille, lg in a_faire:
            entreprise, poste, lien, source = lg[4], lg[5], lg[11], lg[8]
            if str(lien).strip() in liens:
                bilan["deja_presentes"] += 1
            elif not libres:
                bilan["bloc_plein"] += 1
                continue
            else:
                n = libres.pop(0)
                note = f"Ajoutée par la veille le {quand:%d/%m}, note {lg[3]} : {lg[9]}"
                self.client.ecrire_cellules_vides("Candidatures", {
                    f"A{n}": entreprise, f"B{n}": poste, f"C{n}": lien, f"D{n}": f"Veille : {source}", f"N{n}": note})
                liens.add(str(lien).strip())
                bilan["transferees"] += 1
            self.client.ecrire_cellules_vides(self.onglet_veille, {f"N{ligne_veille}": f"{quand:%d/%m/%Y %H:%M}"})
        return bilan

    # ------------------------------------------------------------------ cibles Route B

    def cibles_route_b(self, candidats: list[dict], deja: set[str], verdicts: dict[str, str],
                       restant: int) -> list[tuple[str, list]]:
        """Choisit les nouvelles cibles : absentes de l'onglet Entreprises et des ajouts passés."""
        choisies, vues = [], set(deja)
        for r in candidats:
            nom = normaliser(r["entreprise"])
            if len(choisies) >= restant or not nom or nom in vues:
                continue
            connue = any(contient(nom, v) or contient(v, nom) for v in verdicts if len(v) >= 3)
            vues.add(nom)
            if connue:
                continue
            pourquoi = (f"Recrute en data : offre « {r['titre']} » repérée le {r['vu_le'][8:10]}/{r['vu_le'][5:7]}, "
                        f"rejetée ({LIBELLES_MOTIF.get(r['motif'], r['motif'])}). À vérifier avant toute prise de contact.")
            choisies.append((nom, [r["entreprise"], "Employeur final", "À vérifier", r.get("lieu") or "", pourquoi,
                                   "", "", "", "Veille auto"]))
        return choisies

    def ajouter_route_b(self, lignes: list[list]) -> int:
        if not lignes:
            return 0
        if self.mode == "reel":
            self.client.ajouter_lignes("Entreprises", lignes, premiere=5)
        else:
            self._assurer(self.onglet_route_b, ENTETE_ROUTE_B)
            self.client.ajouter_lignes(self.onglet_route_b, lignes)
        return len(lignes)


__all__ = ["ErreurSheets", "Suivi"]
