"""Exigence d'expérience, en années (cahier des charges § 3.5).

Ordre de confiance : la donnée structurée de la source (France Travail), puis le titre
(« Data Engineer 5 ans d'exp »), puis la description. Dans la description, seules les
formulations qui parlent d'expérience comptent : « une société de plus de 10 ans » ne doit
pas éliminer l'offre. Pour une fourchette (« 2 à 4 ans »), on retient la borne basse.
"""
from __future__ import annotations

import re

_NOMBRE = r"(\d{1,2})"
_ANS = r"(?:ans?|annees?|years?)"
_FOURCHETTE = rf"{_NOMBRE}\s*(?:\+\s*)?(?:(?:a|-|à|to)\s*\d{{1,2}}\s*)?{_ANS}"

_MOTIFS_DESCRIPTION = [
    # « 3 ans d'expérience », « 2 à 4 ans minimum d'expérience », « 5+ years of experience »
    re.compile(rf"{_FOURCHETTE}\s*(?:minimum\s*|au moins\s*|ou plus\s*|et plus\s*)?"
               rf"(?:d['’ ]\s*|de\s+|of\s+)?(?:exp[ée]rience|experience)", re.IGNORECASE),
    # « expérience de 3 ans », « expérience minimum de 5 ans », « expérience d'au moins 4 ans »
    re.compile(rf"exp[ée]rience\s*(?:professionnelle\s*)?(?:significative\s*)?(?:minimum\s*|requise\s*)?"
               rf"(?:de\s*|d['’ ]\s*)?(?:au moins\s*|minimum\s*|plus de\s*)?{_FOURCHETTE}", re.IGNORECASE),
    # « minimum 5 ans », « au moins 3 ans dans un poste similaire »
    re.compile(rf"(?:minimum|au moins|at least)\s*(?:de\s*)?{_FOURCHETTE}", re.IGNORECASE),
]
_MOTIF_TITRE = re.compile(rf"\b{_FOURCHETTE}\b", re.IGNORECASE)


def _plus_petit(motifs: list[re.Pattern], texte: str) -> int | None:
    valeurs = [int(m.group(1)) for p in motifs for m in p.finditer(texte or "")]
    valeurs = [v for v in valeurs if v <= 30]
    return min(valeurs) if valeurs else None


def annees_requises(titre: str, description: str, structure: int | None = None) -> int | None:
    if structure is not None:
        return structure
    du_titre = _plus_petit([_MOTIF_TITRE], titre)
    if du_titre is not None:
        return du_titre
    return _plus_petit(_MOTIFS_DESCRIPTION, description)


_FT_LIBELLE = re.compile(r"(\d{1,2})\s*An", re.IGNORECASE)
_FT_MOIS = re.compile(r"(\d{1,3})\s*Mois", re.IGNORECASE)


def depuis_france_travail(experience_exige: str | None, libelle: str | None) -> tuple[int | None, bool | None]:
    """« E », « 5 An(s) » -> (5, False). « D », « Débutant accepté » -> (0, True)."""
    if experience_exige == "D":
        return 0, True
    lib = libelle or ""
    m = _FT_LIBELLE.search(lib)
    if m:
        return int(m.group(1)), False
    m = _FT_MOIS.search(lib)
    if m:
        return int(m.group(1)) // 12, False
    return None, None
