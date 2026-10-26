"""Modèle de données v2 : offre, rejet, et leurs énumérations (conception § 4)."""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from src.normalisation.texte import normaliser


class Fil(StrEnum):
    EMPLOI = "emploi"
    ALTERNANCE = "alternance"
    IMMERSION = "immersion"


class Contrat(StrEnum):
    CDI = "cdi"
    CDD = "cdd"
    INTERIM = "interim"
    ALTERNANCE = "alternance"
    IMMERSION = "immersion"
    STAGE = "stage"
    FREELANCE = "freelance"
    AUTRE = "autre"          # saisonnier, franchise, libéral…
    INCONNU = "inconnu"


class TypeEmployeur(StrEnum):
    FINAL = "final"
    ESN = "esn"
    INTERMEDIAIRE = "intermediaire"
    PLATEFORME = "plateforme"
    ECOLE = "ecole"
    INCONNU = "inconnu"


class Motif(StrEnum):
    """Motifs de rejet, dans l'ordre d'application des filtres (conception § 5.4)."""
    METIER_HORS_CIBLE = "metier_hors_cible"
    LIEU_ETRANGER = "lieu_etranger"
    PLATEFORME_MISSIONS = "plateforme_missions"
    FREELANCE = "freelance"
    STAGE_CONVENTIONNE = "stage_conventionne"
    CONTRAT_HORS_CIBLE = "contrat_hors_cible"
    SENIORITE = "seniorite"
    DUREE_TROP_COURTE = "duree_trop_courte"
    TROP_ANCIENNE = "trop_ancienne"


@dataclass
class Offre:
    """Une offre telle que rendue par une source, puis enrichie par la normalisation."""

    # Rempli par la source
    source: str
    titre: str
    entreprise: str
    lieu: str
    url: str
    description: str = ""
    contrat_brut: str = ""
    date_publication: str = ""          # AAAA-MM-JJ, vide si inconnue
    id_source: str = ""
    duree_mois: int | None = None        # durée du CDD ou de la mission, si la source la donne
    experience_annees: int | None = None  # exigence d'expérience structurée (France Travail)
    debutant_accepte: bool | None = None
    faible_concurrence: bool = False
    code_rome: str = ""
    diffuseur: str = ""                  # partenaire qui a republié l'offre (France Travail)
    fil_demande: Fil | None = None       # fil pour lequel la source a été interrogée

    # Rempli par la normalisation
    contrat: Contrat = Contrat.INCONNU
    fil: Fil | None = None
    famille: str = ""
    priorite: int = 0
    type_employeur: TypeEmployeur = TypeEmployeur.INCONNU
    zone_preferee: bool = False
    teletravail_complet: bool = False
    annees_requises: int | None = None

    # Rempli par le dédoublonnage
    sources: list[str] = field(default_factory=list)

    @property
    def cle(self) -> str:
        return calculer_cle(self.entreprise, self.titre, self.lieu, self.type_employeur)


def calculer_cle(entreprise: str, titre: str, lieu: str = "",
                 type_employeur: TypeEmployeur = TypeEmployeur.INCONNU) -> str:
    """Clé de dédoublonnage (conception § 4.1).

    Celle de la v1 (entreprise normalisée et 50 premiers caractères du titre), compatible
    avec les clés déjà en base. Quand l'employeur est absent ou masqué par un intermédiaire,
    le lieu remplace l'entreprise, pour ne pas fusionner des offres distinctes.
    """
    ent = normaliser(entreprise) if entreprise not in ("", "—", "-") else ""
    if not ent or type_employeur == TypeEmployeur.INTERMEDIAIRE:
        base = f"|{_v1(titre)}|{normaliser(lieu)}"
    else:
        base = f"{_v1_entreprise(entreprise)}|{_v1(titre)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _v1_entreprise(texte: str) -> str:
    """Normalisation de la v1 (accents retirés, minuscules), gardée pour la compatibilité des clés."""
    t = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def _v1(titre: str) -> str:
    return _v1_entreprise(titre)[:50]


@dataclass(frozen=True)
class Rejet:
    offre: Offre
    motif: Motif
    detail: str = ""
