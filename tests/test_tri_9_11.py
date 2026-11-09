"""Repositionnement du 9/11 : familles, rejets et bonus tirés du bilan des candidatures."""
from datetime import date

import pytest

from src.filtres import motif_de_rejet, normaliser_offre
from src.models import Motif, TypeEmployeur
from src.normalisation import employeurs, metiers
from src.notation import noter
from tests.conftest import offre

JOUR = date(2026, 10, 26)


def preparer(config, **kw):
    return normaliser_offre(offre(**kw), config)


def raisons(config, **kw):
    return dict(noter(preparer(config, **kw), config, JOUR).composantes)


@pytest.mark.parametrize("titre, priorite", [
    ("Data Analyst H/F", 1), ("Consultant BI Power BI", 1), ("Analytics Engineer", 1),
    ("Data Engineer", 1), ("Data Scientist", 2),
])
def test_priorites_repositionnees(config, titre, priorite):
    f, _ = metiers.reconnaitre(titre, config.metiers)
    assert f is not None and f.priorite == priorite


def test_nouvelles_ecoles_malus_sans_rejet(config):
    # Sur le jeu du 26/10, six offres d'écoles étaient annotées « je postule » : malus, pas de rejet.
    o = preparer(config, entreprise="Aivancity School", titre="Alternance Data Analyst")
    assert o.type_employeur == TypeEmployeur.ECOLE and motif_de_rejet(o, config, JOUR) is None
    assert dict(noter(o, config, JOUR).composantes)["école"] == -3


@pytest.mark.parametrize("titre", ["Data Scientist docteur", "PhD Data Scientist"])
def test_postes_de_docteur_rejetes(config, titre):
    assert motif_de_rejet(preparer(config, titre=titre), config, JOUR)[0] == Motif.SENIORITE


def test_experimente_et_trois_ans_penalises_sans_rejet(config):
    o = preparer(config, titre="Data Analyst expérimenté", description="3 ans d'expérience souhaités.")
    assert motif_de_rejet(o, config, JOUR) is None
    r = dict(noter(o, config, JOUR).composantes)
    assert r["« confirmé » dans le titre"] == -4 and r["3 an(s) d'expérience demandé(s)"] == -4


@pytest.mark.parametrize("nom", ["Keoni", "CRIT Intérim", "LinkedIn Job Wrapping", "Lynx RH", "Jobposting"])
def test_nouveaux_intermediaires(config, nom):
    assert employeurs.classer(nom, config.filtres.employeurs) == TypeEmployeur.INTERMEDIAIRE


@pytest.mark.parametrize("kw", [
    {"entreprise": "Ministère de l'Économie et des Finances"},
    {"entreprise": "Direction générale des Finances publiques"},
    {"entreprise": "Inserm"},
    {"entreprise": "Ministères de la Santé, des Solidarités et du Travail"},   # pluriel, passage du 9/11
    {"entreprise": "Recruteur", "source": "service_public"},
])
def test_bonus_secteur_public(config, kw):
    assert raisons(config, **kw)["secteur public"] == 3


def test_pas_de_bonus_public_pour_une_entreprise(config):
    assert "secteur public" not in raisons(config, entreprise="Doctolib")


def test_bonus_donnees_sensibles(config):
    r = raisons(config, description="Vous fiabilisez les données de lutte contre la fraude.")
    assert r["données sensibles (fraude)"] == 2
    assert not any(k.startswith("données sensibles") for k in raisons(config, description="Tableaux de bord."))


def test_affinites_facultatives(config):
    sans = config.notation.model_copy(update={"affinites": type(config.notation.affinites)()})
    c = config.model_copy(update={"notation": sans})
    r = dict(noter(preparer(c, entreprise="Inserm"), c, JOUR).composantes)
    assert "secteur public" not in r


def test_resume_limite_a_15(config):
    assert config.telegram.resume_max_offres == 15
