"""Reconnaissance de la famille de métier à partir du titre (conception § 5.1)."""
from __future__ import annotations

from src.config import Famille, Metiers
from src.normalisation.texte import contient, normaliser


def reconnaitre(titre: str, metiers: Metiers, code_rome: str = "") -> tuple[Famille | None, str]:
    """Rend la famille de plus haute priorité dont un motif figure dans le titre, et ce motif.

    À défaut de motif, un code ROME rattaché à une famille suffit (titre flou, code explicite).
    """
    t = normaliser(titre)
    meilleure: tuple[Famille, str] | None = None
    for famille in metiers.familles:
        for motif in famille.motifs:
            if contient(t, motif):
                if meilleure is None or famille.priorite < meilleure[0].priorite:
                    meilleure = (famille, motif)
                break
    if meilleure:
        return meilleure
    if code_rome:
        for famille in metiers.familles:
            if code_rome in famille.romes:
                return famille, f"rome {code_rome}"
    return None, ""
