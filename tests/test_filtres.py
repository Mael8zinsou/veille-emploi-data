from datetime import date

import pytest

from src.dedoublonnage import fusionner
from src.filtres import motif_de_rejet, normaliser_offre, trier
from src.models import Fil, Motif, TypeEmployeur, calculer_cle
from tests.conftest import offre

JOUR = date(2026, 10, 26)


def motif(config, **kw):
    o = normaliser_offre(offre(**kw), config)
    r = motif_de_rejet(o, config, JOUR)
    return r[0] if r else None


def test_offre_ordinaire_gardee(config):
    assert motif(config) is None


@pytest.mark.parametrize("kw, attendu", [
    ({"titre": "Comptable"}, Motif.METIER_HORS_CIBLE),
    ({"lieu": "Bruxelles"}, Motif.LIEU_ETRANGER),
    ({"entreprise": "Collective.work"}, Motif.PLATEFORME_MISSIONS),
    ({"titre": "Data Engineer Freelance"}, Motif.FREELANCE),
    ({"titre": "Stage Data Engineer"}, Motif.STAGE_CONVENTIONNE),
    ({"contrat_brut": "SAI Saisonnier"}, Motif.CONTRAT_HORS_CIBLE),
    ({"titre": "Senior Data Engineer"}, Motif.SENIORITE),
    ({"titre": "Lead Data Scientist"}, Motif.SENIORITE),
    ({"description": "Vous avez 5 ans d'expérience en data."}, Motif.SENIORITE),
    ({"contrat_brut": "CDD - 3 Mois"}, Motif.DUREE_TROP_COURTE),
    ({"contrat_brut": "MIS Intérim - 1 Mois"}, Motif.DUREE_TROP_COURTE),
    ({"date_publication": "2026-10-01"}, Motif.TROP_ANCIENNE),
])
def test_motifs(config, kw, attendu):
    assert motif(config, **kw) == attendu


@pytest.mark.parametrize("kw", [
    {"titre": "Data Engineer confirmé"},                          # déclassé plus tard, pas éliminé
    {"description": "3 ans d'expérience souhaités."},             # 3 ans : accepté
    {"description": "2 à 5 ans d'expérience."},                   # borne basse
    {"titre": "Data Manager (études cliniques)"},                 # métier, pas grade
    {"lieu": "Londres", "titre": "Data Engineer - Full remote"},  # télétravail complet
    {"contrat_brut": "CDD - 6 Mois"},
    {"contrat_brut": "CDD"},                                      # durée inconnue : gardée
    {"date_publication": ""},                                     # date inconnue : gardée
    {"entreprise": "Conseil Régional d'Île-de-France"},
])
def test_gardees(config, kw):
    assert motif(config, **kw) is None


def test_ordre_seniorite_avant_anciennete(config):
    # Senior ET ancienne : le motif retenu est la séniorité (utile à la Route B).
    assert motif(config, titre="Senior Data Engineer", date_publication="2026-09-01") == Motif.SENIORITE


def test_alternance_va_dans_son_fil(config):
    o = normaliser_offre(offre(titre="Alternance Data Analyst", contrat_brut="CDD"), config)
    assert o.fil == Fil.ALTERNANCE and motif_de_rejet(o, config, JOUR) is None


def test_trier_separe_et_motive(config):
    gardees, rejets = trier([offre(), offre(titre="Senior Data Engineer"), offre(titre="Comptable")], config, JOUR)
    assert len(gardees) == 1
    assert {r.motif for r in rejets} == {Motif.SENIORITE, Motif.METIER_HORS_CIBLE}
    assert all(r.detail is not None for r in rejets)


# --------------------------------------------------------------------------- clé et dédoublonnage

def test_cle_compatible_v1():
    import hashlib
    assert calculer_cle("Doctolib", "Data Engineer F/H") == hashlib.sha256(b"doctolib|data engineer f/h").hexdigest()[:16]


def test_cle_sans_employeur_utilise_le_lieu():
    a = calculer_cle("", "Data Engineer", "Paris")
    b = calculer_cle("", "Data Engineer", "Lyon")
    assert a != b
    assert calculer_cle("Handicap Job", "Data Engineer", "Paris", TypeEmployeur.INTERMEDIAIRE) == a


def test_fusion(config):
    a = normaliser_offre(offre(source="adzuna", description="court"), config)
    b = normaliser_offre(offre(source="france_travail", description="beaucoup plus long", faible_concurrence=True,
                               contrat_brut="CDD - 12 Mois"), config)
    c = normaliser_offre(offre(titre="Data Scientist"), config)
    sortie = fusionner([a, b, c])
    assert len(sortie) == 2
    fusion = next(o for o in sortie if o.titre == "Data Engineer H/F")
    assert fusion.sources == ["adzuna", "france_travail"]
    assert fusion.description == "beaucoup plus long" and fusion.faible_concurrence
