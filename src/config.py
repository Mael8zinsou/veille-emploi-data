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


class Seniorite(_Strict):
    titre: MotifsRequis
    exceptions: Motifs = []
    annees_max: int = Field(ge=0, le=20)


class Employeurs(_Strict):
    plateformes_missions: Motifs
    intermediaires: Motifs
    esn: Motifs
    ecoles: Motifs


class Filtres(_Strict):
    fraicheur_max_jours: int = Field(ge=1, le=60)
    duree_min_mois: int = Field(ge=0, le=36)
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


class Envois(_Strict):
    resume_quotidien_heure: int = Field(ge=0, le=23)
    bilan_hebdomadaire: Bilan


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
    emploi: list[RechercheHelloWork]
    alternance: list[RechercheHelloWork] = []


class Sources(_Strict):
    actives: dict[str, bool]
    france_travail: FranceTravail
    adzuna: Adzuna
    hellowork: HelloWork


# --------------------------------------------------------------------------- ensemble

class Config(_Strict):
    metiers: Metiers
    filtres: Filtres
    planning: Planning
    sources: Sources


def _lire(chemin: Path) -> dict:
    with chemin.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def charger(dossier: Path | str = DOSSIER_CONFIG) -> Config:
    """Charge et valide les quatre fichiers. Lève pydantic.ValidationError si invalide."""
    d = Path(dossier)
    return Config(metiers=_lire(d / "metiers.yaml"), filtres=_lire(d / "filtres.yaml"),
                  planning=_lire(d / "planning.yaml"), sources=_lire(d / "sources.yaml"))
