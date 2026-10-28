"""Modèle de données v2 : offre, rejet, et leurs énumérations (conception § 4)."""
from __future__ import annotations

import hashlib
import re
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


class Niveau(StrEnum):
    ALERTE = "alerte"
    RESUME = "resume"
    ARCHIVE = "archive"


class Motif(StrEnum):
    """Motifs de rejet, dans l'ordre d'application des filtres (conception § 5.4)."""
    METIER_HORS_CIBLE = "metier_hors_cible"
    LIEU_ETRANGER = "lieu_etranger"
    PLATEFORME_MISSIONS = "plateforme_missions"
    FREELANCE = "freelance"
    STAGE_CONVENTIONNE = "stage_conventionne"
    CONTRAT_HORS_CIBLE = "contrat_hors_cible"
    SENIORITE = "seniorite"
    CERTIFICATION_EXIGEE = "certification_exigee"
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
    diffuseur: str = ""                  # partenaire qui a republié l'offre (France Travail, La bonne alternance)
    delegue_par_ecole: bool = False      # offre déposée par une école pour une entreprise (La bonne alternance)
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
    via_cabinet: bool = False            # publiée par un cabinet de recrutement pour un client
    permis_exige: bool = False           # « permis B exigé » dans le texte
    description_partielle: bool = False  # la source ne donne qu'un extrait (Adzuna)

    # Rempli par le dédoublonnage
    sources: list[str] = field(default_factory=list)

    @property
    def cle(self) -> str:
        return calculer_cle(self.entreprise, self.titre, self.lieu, self.type_employeur)

    @property
    def cle_souple(self) -> str:
        """Comme `cle`, mais sur un titre débarrassé de ses suffixes (« (CDI) », « H/F », code en
        majuscules) : reconnaît une même offre republiée sous un titre à peine différent."""
        return calculer_cle(self.entreprise, titre_souple(self.titre), self.lieu, self.type_employeur)

    @property
    def empreinte(self) -> str | None:
        """Empreinte de la description, liée à l'employeur (ou au lieu s'il est masqué). Rien si la
        description est trop courte pour distinguer deux offres."""
        texte = normaliser(self.description)
        if len(texte) < EMPREINTE_MIN:
            return None
        ent = "" if self.type_employeur == TypeEmployeur.INTERMEDIAIRE else normaliser(self.entreprise)
        base = f"{ent or normaliser(self.lieu)}|{texte[:EMPREINTE_LONGUEUR]}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


EMPREINTE_MIN = 200
EMPREINTE_LONGUEUR = 500
_SUFFIXES_TITRE = re.compile(
    r"\b(?:h\s*f(?:\s*n|\s*x)?|f\s*h(?:\s*n|\s*x)?|x\s*f\s*m|f\s*m\s*x|m\s*f|f\s*m|hf|fh|cdi|cdd)\b")
_CODE_FINAL = re.compile(r"\s+[A-Z0-9]{4,}\s*$")


def titre_souple(titre: str) -> str:
    """« Data Scientist (H/F) AEROMIN » et « Data Scientist (H/F) » -> « data scientist ».
    Un mot final tout en majuscules n'est retiré que si le titre contient des minuscules : un
    titre entièrement en capitales (« INGENIEUR BIG DATA ») reste intact."""
    t = titre or ""
    if any(c.islower() for c in t):
        t = _CODE_FINAL.sub("", t)
    t = _SUFFIXES_TITRE.sub(" ", normaliser(t))
    return " ".join(t.split())


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
