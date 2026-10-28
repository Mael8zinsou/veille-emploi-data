"""Type d'employeur à partir du nom (conception § 5.3)."""
from __future__ import annotations

from src.config import Employeurs
from src.models import TypeEmployeur
from src.normalisation.texte import normaliser, premier_motif

_VIDES = {"", "-", "—", "n c", "nc", "non communique", "confidentiel", "entreprise confidentielle"}


def classer(nom: str, employeurs: Employeurs, delegue_par_ecole: bool = False) -> TypeEmployeur:
    """Plateforme, intermédiaire, école, ESN, puis employeur final. Nom vide : inconnu.

    L'ordre compte : « Hellowork » est un intermédiaire avant d'être autre chose, et une
    école qui publie pour une entreprise (`delegue_par_ecole`, signal de La bonne
    alternance) reste une école.
    """
    n = normaliser(nom)
    if n in _VIDES:
        return TypeEmployeur.INCONNU
    if premier_motif(n, employeurs.plateformes_missions):
        return TypeEmployeur.PLATEFORME
    if premier_motif(n, employeurs.intermediaires):
        return TypeEmployeur.INTERMEDIAIRE
    if delegue_par_ecole or premier_motif(n, employeurs.ecoles):
        return TypeEmployeur.ECOLE
    if premier_motif(n, employeurs.esn):
        return TypeEmployeur.ESN
    return TypeEmployeur.FINAL


def est_cabinet(nom: str, employeurs: Employeurs) -> bool:
    """Cabinet de recrutement qui publie pour un client (signalé, sans pénalité)."""
    return bool(premier_motif(normaliser(nom), employeurs.cabinets))
