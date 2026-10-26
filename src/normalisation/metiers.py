"""Reconnaissance de la famille de métier à partir du titre (conception § 5.1)."""
from __future__ import annotations

from src.config import Famille, Metiers
from src.normalisation.texte import contient, normaliser


def reconnaitre(titre: str, metiers: Metiers, code_rome: str = "") -> tuple[Famille | None, str]:
    """Rend la famille de plus haute priorité dont un motif figure dans le titre, et ce motif.

    Le code ROME ne sert PAS à classer : l'essai du 26/10 a montré que France Travail range
    sous M1889 (ingénieur IA) des offres d'infirmier coordinateur ou de mécanicien. Les codes
    ROME servent seulement à interroger l'API ; seul le titre décide. `code_rome` est gardé
    dans la signature pour la traçabilité.
    """
    t = normaliser(titre)
    meilleure: tuple[Famille, str] | None = None
    for famille in metiers.familles:
        for motif in famille.motifs:
            if contient(t, motif):
                if meilleure is None or famille.priorite < meilleure[0].priorite:
                    meilleure = (famille, motif)
                break
    return meilleure if meilleure else (None, "")
