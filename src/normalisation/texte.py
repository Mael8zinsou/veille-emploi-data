"""Normalisation commune du texte et recherche de motifs mot à mot.

Toutes les comparaisons de l'outil passent par ici : minuscules, accents retirés,
ponctuation remplacée par des espaces, espaces réduits. Un motif est cherché entouré
d'espaces, ce qui garantit les frontières de mots : « ia » ne trouve pas « media ».
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def normaliser(texte: str | None) -> str:
    """« Ingénieur·e Data (H/F) – CDI » -> « ingenieur e data h f cdi »."""
    if not texte:
        return ""
    t = sans_accents(texte).lower().replace("œ", "oe").replace("æ", "ae")
    return _NON_ALNUM.sub(" ", t).strip()


def contient(texte_normalise: str, motif_normalise: str) -> bool:
    """Vrai si le motif apparaît comme suite de mots entiers dans le texte."""
    if not motif_normalise:
        return False
    return f" {motif_normalise} " in f" {texte_normalise} "


def premier_motif(texte_normalise: str, motifs: Iterable[str]) -> str | None:
    """Premier motif (dans l'ordre donné) présent dans le texte, ou None."""
    for m in motifs:
        if contient(texte_normalise, m):
            return m
    return None


def retirer(texte_normalise: str, motifs: Iterable[str]) -> str:
    """Retire les motifs du texte (mots entiers), pour des contrôles qui doivent les ignorer."""
    t = f" {texte_normalise} "
    for m in motifs:
        if m:
            t = t.replace(f" {m} ", " ")
    return " ".join(t.split())
