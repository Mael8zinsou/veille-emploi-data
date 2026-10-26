"""Lieu : étranger, télétravail complet, zone préférée (cahier des charges § 3.4)."""
from __future__ import annotations

from dataclasses import dataclass

from src.config import Lieux
from src.normalisation.texte import normaliser, premier_motif


@dataclass(frozen=True)
class AnalyseLieu:
    etranger: str | None        # motif étranger reconnu, ou None
    teletravail_complet: bool
    zone_preferee: bool


def analyser(lieu: str, titre: str, lieux: Lieux) -> AnalyseLieu:
    n = normaliser(lieu)
    # Le télétravail complet peut être annoncé dans le titre (« Data Engineer - Full remote »).
    tele = bool(premier_motif(n, lieux.teletravail_complet) or premier_motif(normaliser(titre),
                                                                             lieux.teletravail_complet))
    return AnalyseLieu(etranger=premier_motif(n, lieux.etrangers), teletravail_complet=tele,
                       zone_preferee=bool(premier_motif(n, lieux.preferees)))
