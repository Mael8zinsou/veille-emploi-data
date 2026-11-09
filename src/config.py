"""Chargement et validation de la configuration (config/*.yaml).

Une erreur de saisie dans un fichier arrête le passage avec un message clair, au lieu d'un
comportement silencieusement faux. Les motifs sont normalisés au chargement : on peut les
écrire avec ou sans accents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.normalisation.texte import normaliser

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_CONFIG = RACINE / "config"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normaliser_liste(valeurs: list[str]) -> list[str]:
    vus, sortie = set(), []
    for v in valeurs:
        n = normaliser(str(v))
        if n and n not in vus:
            vus.add(n)
            sortie.append(n)
    return sortie


def _non_vide(valeurs: list[str]) -> list[str]:
    if not valeurs:
        raise ValueError("la liste ne peut pas être vide")
    return valeurs


# Liste de motifs : normalisés (sans accents, minuscules) et dédoublonnés au chargement.
Motifs = Annotated[list[str], AfterValidator(_normaliser_liste)]
MotifsRequis = Annotated[list[str], AfterValidator(_normaliser_liste), AfterValidator(_non_vide)]


# --------------------------------------------------------------------------- métiers

class Famille(_Strict):
    nom: str
    libelle: str
    priorite: int = Field(ge=1, le=3)
    romes: list[str] = []
    motifs: MotifsRequis


class Metiers(_Strict):
    exclusions: Motifs = []
    familles: list[Famille]

    @model_validator(mode="after")
    def _noms_uniques(self) -> Metiers:
        noms = [f.nom for f in self.familles]
        if len(noms) != len(set(noms)):
            raise ValueError("deux familles portent le même nom")
        return self


# --------------------------------------------------------------------------- filtres

class Lieux(_Strict):
    etrangers: Motifs
    teletravail_complet: Motifs
    preferees: Motifs


class IndicesContrat(_Strict):
    alternance: Motifs
    immersion: Motifs
    stage: Motifs
    freelance: Motifs
    cdi: Motifs
    cdd: Motifs
    interim: Motifs


class Contrats(_Strict):
    indices_titre: IndicesContrat
    stage_description: Motifs = []


class Seniorite(_Strict):
    titre: MotifsRequis
    exceptions: Motifs = []
    annees_max: int = Field(ge=0, le=20)


class Employeurs(_Strict):
    plateformes_missions: Motifs
    intermediaires: Motifs
    esn: Motifs
    ecoles: Motifs
    cabinets: Motifs = []


class CertificationExigee(_Strict):
    fenetre: int = Field(ge=0, le=10)
    mots: MotifsRequis


class Filtres(_Strict):
    fraicheur_max_jours: int = Field(ge=1, le=60)
    duree_min_mois: int = Field(ge=0, le=36)
    certification_exigee: CertificationExigee
    lieux: Lieux
    contrats: Contrats
    seniorite: Seniorite
    employeurs: Employeurs


# --------------------------------------------------------------------------- planning

class Plage(_Strict):
    debut: int = Field(ge=0, le=23)
    fin: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _ordre(self) -> Plage:
        if self.debut >= self.fin:
            raise ValueError("plage : debut doit précéder fin")
        return self


class Tache(_Strict):
    intervalle_minutes: int = Field(ge=1)


class Bilan(_Strict):
    jour: int = Field(ge=0, le=6)
    heure: int = Field(ge=0, le=23)


class ListeMatin(_Strict):
    heure: int = Field(ge=0, le=23)              # heure de Paris à partir de laquelle la liste est due
    max_offres: int = Field(default=10, ge=1, le=20)
    fenetre_jours: int = Field(default=3, ge=1, le=14)
    fils: list[str] = ["emploi", "alternance"]


class Envois(_Strict):
    resume_quotidien_heure: int = Field(ge=0, le=23)
    bilan_hebdomadaire: Bilan
    liste_matin: ListeMatin | None = None


class Quotas(_Strict):
    adzuna_mensuel: int = Field(ge=0, le=250)


class Planning(_Strict):
    fuseau: str
    plage: Plage
    taches: dict[str, Tache]
    envois: Envois
    quotas: Quotas


# --------------------------------------------------------------------------- sources

class FTEmploi(_Strict):
    types_contrat: str
    romes: list[str] = []
    mots_cles: list[str] = []


class FTAlternance(_Strict):
    nature_contrat: str
    romes: list[str] = []
    mots_cles: list[str] = []


class FranceTravail(_Strict):
    fenetre_jours: int = Field(ge=1, le=31)
    max_pages: int = Field(ge=1, le=7)
    emploi: FTEmploi
    alternance: FTAlternance


class RequeteAdzuna(_Strict):
    nom: str
    title_only: str | None = None
    what: str | None = None
    pages: int = Field(default=1, ge=1, le=5)


class Adzuna(_Strict):
    max_jours: int = Field(ge=1, le=30)
    par_page: int = Field(ge=1, le=50)
    requetes: list[RequeteAdzuna]


class RechercheHelloWork(_Strict):
    k: str
    l: str | None = None  # noqa: E741 (nom du paramètre de l'URL HelloWork)


class HelloWork(_Strict):
    max_pages: int = Field(ge=1, le=5)
    delai_secondes: float = Field(ge=1.0)
    max_details: int = Field(default=0, ge=0, le=100)   # pages d'offre lues au plus par passage
    emploi: list[RechercheHelloWork]
    alternance: list[RechercheHelloWork] = []


class FluxTalentsoft(_Strict):
    nom: str
    profil: int | None = None     # métier du répertoire (Rss_Profile)
    famille: int | None = None    # domaine (Rss_JobFamily)


class ServicePublic(_Strict):
    flux: list[FluxTalentsoft]
    max_details: int = Field(ge=0, le=100)
    delai_secondes: float = Field(ge=0.5)


class RechercheLBA(_Strict):
    nom: str
    latitude: float | None = None
    longitude: float | None = None
    rayon_km: int = Field(default=60, ge=1, le=200)


class LaBonneAlternance(_Strict):
    romes: list[str]
    recherches: list[RechercheLBA]
    partenaires_exclus: list[str] = []


class Sources(_Strict):
    actives: dict[str, bool]
    france_travail: FranceTravail
    adzuna: Adzuna
    hellowork: HelloWork
    service_public: ServicePublic
    la_bonne_alternance: LaBonneAlternance


# --------------------------------------------------------------------------- notation

class Competences(_Strict):
    points: int
    plafond: int = Field(ge=0)
    liste: MotifsRequis


class NiveauExperience(_Strict):
    signaux_junior: Motifs
    junior: int
    debutant_accepte: int
    confirme_titre: int
    mots_confirme: Motifs
    annees: dict[int, int]


class PointsEmployeur(_Strict):
    esn: int
    intermediaire: int
    inconnu: int
    ecole: int


class PointsSuivi(_Strict):
    cible_prioritaire: int
    cible: int
    derniere_priorite: int
    ecarter: int
    ecarter_definitif: Motifs


class Signaux(_Strict):
    publiee_depuis_un_jour: int
    publiee_depuis_5_jours: int
    republiee: int
    peu_candidatee: int
    zone_preferee: int
    teletravail_complet: int


class SeuilAlerte(_Strict):
    note_min: int
    fils: list[str]
    exige_priorite_1_ou_cible: bool = True
    exclut_seconde_main: bool = True


class SeuilResume(_Strict):
    note_min: int = Field(ge=-100)


class Niveaux(_Strict):
    alerte: SeuilAlerte
    resume: SeuilResume

    @model_validator(mode="after")
    def _ordre(self) -> Niveaux:
        if self.alerte.note_min < self.resume.note_min:
            raise ValueError("le seuil d'alerte doit être au moins égal à celui du résumé")
        return self


class Affinite(_Strict):
    """Bonus quand l'offre ressemble à l'expérience de Maël (repositionnement du 9/11)."""
    points: int
    employeurs: Motifs = []    # mots cherchés dans le nom de l'employeur
    sources: list[str] = []    # sources dont toutes les offres relèvent de l'affinité
    mots: Motifs = []          # mots cherchés dans le titre et la description


class Affinites(_Strict):
    secteur_public: Affinite | None = None
    donnees_sensibles: Affinite | None = None


class Notation(_Strict):
    priorite_famille: dict[int, int]
    competences: Competences
    niveau_experience: NiveauExperience
    employeur: PointsEmployeur
    suivi: PointsSuivi
    signaux: Signaux
    niveaux: Niveaux
    affinites: Affinites = Affinites()


# --------------------------------------------------------------------------- telegram

class RequeteLinkedIn(_Strict):
    libelle: str
    mots_cles: str


class RappelLinkedIn(_Strict):
    actif: bool = True
    intervalle_minutes: int = Field(ge=30)
    plage: Plage
    requetes: list[RequeteLinkedIn] = Field(min_length=1)


class Telegram(_Strict):
    groupe_id: int
    sujets: dict[str, int]
    resume_max_offres: int = Field(ge=1, le=100)
    pannes_avant_avertissement: int = Field(ge=1, le=20)
    rappel_linkedin: RappelLinkedIn | None = None


# --------------------------------------------------------------------------- ensemble

class Config(_Strict):
    metiers: Metiers
    filtres: Filtres
    planning: Planning
    sources: Sources
    notation: Notation
    telegram: Telegram


def _lire(chemin: Path) -> dict:
    with chemin.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def charger(dossier: Path | str = DOSSIER_CONFIG) -> Config:
    """Charge et valide les fichiers de configuration. Lève pydantic.ValidationError si invalide."""
    d = Path(dossier)
    return Config(metiers=_lire(d / "metiers.yaml"), filtres=_lire(d / "filtres.yaml"),
                  planning=_lire(d / "planning.yaml"), sources=_lire(d / "sources.yaml"),
                  notation=_lire(d / "notation.yaml"), telegram=_lire(d / "telegram.yaml"))
