"""Contrat, durée et fil (conception § 5.2).

La source déclare un contrat ; le titre peut le contredire (« Alternance - Data Analyst »
publié en CDD). Les indices du titre l'emportent, dans l'ordre : alternance, immersion,
stage, freelance, puis cdi, cdd, intérim.
"""
from __future__ import annotations

import re

from src.config import Filtres
from src.models import Contrat, Fil
from src.normalisation.texte import normaliser, premier_motif

_DUREE = re.compile(r"(\d{1,3})\s*(mois|jours?|semaines?|ans?)\b", re.IGNORECASE)

# Libellés bruts des sources -> contrat. Clés normalisées, comparées en début de libellé
# puis mot à mot.
_CORRESPONDANCES: list[tuple[str, Contrat]] = [
    ("contrat apprentissage", Contrat.ALTERNANCE),
    ("apprentissage", Contrat.ALTERNANCE),
    ("cont professionnalisation", Contrat.ALTERNANCE),
    ("professionnalisation", Contrat.ALTERNANCE),
    ("alternance", Contrat.ALTERNANCE),
    ("stage", Contrat.STAGE),
    ("freelance", Contrat.FREELANCE),
    ("independant", Contrat.FREELANCE),
    ("lib", Contrat.FREELANCE),            # France Travail : profession libérale
    ("cdi", Contrat.CDI),
    ("permanent", Contrat.CDI),            # Adzuna
    ("cdd", Contrat.CDD),
    ("contract", Contrat.CDD),             # Adzuna
    ("mis", Contrat.INTERIM),              # France Travail
    ("interim", Contrat.INTERIM),
    ("sai", Contrat.AUTRE),                # saisonnier
    ("saisonnier", Contrat.AUTRE),
    ("fra", Contrat.AUTRE),                # franchise
    ("cce", Contrat.AUTRE),
    ("reserve aux fonctionnaires", Contrat.AUTRE),   # Choisir le service public
]


def contrat_declare(brut: str) -> Contrat:
    n = normaliser(brut)
    if not n:
        return Contrat.INCONNU
    for cle, contrat in _CORRESPONDANCES:
        if n == cle or n.startswith(cle + " ") or f" {cle} " in f" {n} ":
            return contrat
    return Contrat.INCONNU


def contrat_du_titre(titre: str, filtres: Filtres) -> Contrat | None:
    t = normaliser(titre)
    i = filtres.contrats.indices_titre
    for liste, contrat in ((i.alternance, Contrat.ALTERNANCE), (i.immersion, Contrat.IMMERSION),
                           (i.stage, Contrat.STAGE), (i.freelance, Contrat.FREELANCE),
                           (i.cdi, Contrat.CDI), (i.cdd, Contrat.CDD), (i.interim, Contrat.INTERIM)):
        if premier_motif(t, liste):
            return contrat
    return None


def duree_en_mois(brut: str) -> int | None:
    """« CDD - 12 Mois » -> 12, « Intérim - 15 Jour(s) » -> 0, « 2 ans » -> 24."""
    m = _DUREE.search(brut or "")
    if not m:
        return None
    n, unite = int(m.group(1)), m.group(2).lower()
    if unite.startswith("mois"):
        return n
    if unite.startswith("an"):
        return n * 12
    if unite.startswith("semaine"):
        return n // 4
    return n // 30


def determiner(titre: str, contrat_brut: str, filtres: Filtres,
               fil_demande: Fil | None = None) -> Contrat:
    """Contrat final : indice du titre, sinon contrat déclaré, sinon le fil interrogé."""
    du_titre = contrat_du_titre(titre, filtres)
    declare = contrat_declare(contrat_brut)
    # Un titre « CDI » ne contredit pas une source qui dit alternance : l'alternance gagne.
    if du_titre in (Contrat.CDI, Contrat.CDD, Contrat.INTERIM) and declare == Contrat.ALTERNANCE:
        return declare
    if du_titre is not None:
        return du_titre
    if declare != Contrat.INCONNU:
        return declare
    if fil_demande == Fil.ALTERNANCE:
        return Contrat.ALTERNANCE
    return Contrat.INCONNU


def fil_du_contrat(contrat: Contrat) -> Fil | None:
    """Fil d'un contrat retenu. None : le contrat est hors cible (rejet en aval)."""
    if contrat in (Contrat.CDI, Contrat.CDD, Contrat.INTERIM, Contrat.INCONNU):
        return Fil.EMPLOI
    if contrat == Contrat.ALTERNANCE:
        return Fil.ALTERNANCE
    if contrat == Contrat.IMMERSION:
        return Fil.IMMERSION
    return None
