"""Dédoublonnage entre sources (conception § 4.1).

Les offres de même clé souple (même employeur, titre débarrassé de ses suffixes) sont
fusionnées : on garde la plus détaillée (description la plus longue), on cumule les sources,
et les signaux portés par une seule source sont conservés.
"""
from __future__ import annotations

from src.models import Offre


def fusionner(offres: list[Offre]) -> list[Offre]:
    par_cle: dict[str, Offre] = {}
    sources: dict[str, list[str]] = {}
    for o in offres:
        cle = o.cle_souple
        liste = sources.setdefault(cle, [])
        if o.source not in liste:
            liste.append(o.source)
        gardee = par_cle.get(cle)
        if gardee is None:
            par_cle[cle] = o
            continue
        principale, autre = (o, gardee) if len(o.description) > len(gardee.description) else (gardee, o)
        principale.faible_concurrence = principale.faible_concurrence or autre.faible_concurrence
        principale.debutant_accepte = principale.debutant_accepte or autre.debutant_accepte
        if principale.duree_mois is None:
            principale.duree_mois = autre.duree_mois
        if principale.annees_requises is None:
            principale.annees_requises = autre.annees_requises
        principale.via_cabinet = principale.via_cabinet or autre.via_cabinet
        principale.permis_exige = principale.permis_exige or autre.permis_exige
        par_cle[cle] = principale
    sortie = []
    for cle, o in par_cle.items():
        o.sources = sources[cle]
        sortie.append(o)
    return sortie
