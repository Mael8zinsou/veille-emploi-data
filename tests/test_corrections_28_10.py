"""Corrections du 28/10, chacune tirée d'un cas réel des alertes des 26, 27 et 28 octobre."""
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from src import main, stockage
from src.dedoublonnage import fusionner
from src.filtres import motif_de_rejet, normaliser_offre
from src.models import Motif, TypeEmployeur, titre_souple
from src.sorties.telegram import message_alerte
from src.sources import adzuna
from tests.conftest import fixture_json, offre

JOUR = date(2026, 10, 28)
DESCRIPTION_TRANSAVIA = ("L'équipe transverse Data & Analytics (D&A) contribue au pilotage de la performance de "
                         "l'entreprise en concevant des outils décisionnels et des solutions pilotées par l'IA pour "
                         "les décideurs métier. Dans un contexte de forte croissance, l'équipe D&A recrute un(e) "
                         "Data Scientist ML/RO (H/F) pour résoudre des problèmes complexes.")


def rejet(config, **kw):
    o = normaliser_offre(offre(**kw), config)
    r = motif_de_rejet(o, config, JOUR)
    return r[0] if r else None


# --------------------------------------------------------------------------- 1. stages déguisés

@pytest.mark.parametrize("description", [
    "L'offre est à pourvoir à partir de janvier pour un stage de 6 mois.",          # Cdiscount
    "Vos connaissances de SQL Server sont des atouts pour la réussite de ce stage.",  # ESSCA
    "Stage de 4 à 6 mois, gratification selon profil.",
    "Offre de stage en data engineering.",
])
def test_stage_dans_la_description_d_un_cdi(config, description):
    assert rejet(config, contrat_brut="CDI", description=description) == Motif.STAGE_CONVENTIONNE


@pytest.mark.parametrize("description", [
    "Vous avez réalisé un stage ou une alternance en data.",
    "Nos stagiaires sont encadrés par l'équipe.",
    "",
])
def test_cdi_qui_parle_de_stage_garde(config, description):
    assert rejet(config, contrat_brut="CDI", description=description) is None


def test_alternance_non_concernee(config):
    o = normaliser_offre(offre(titre="Alternance Data Analyst", contrat_brut="Apprentissage",
                               description="Pendant ce stage puis cette alternance..."), config)
    assert motif_de_rejet(o, config, JOUR) is None


def test_detail_du_rejet(config):
    o = normaliser_offre(offre(description="pour un stage de 6 mois"), config)
    assert motif_de_rejet(o, config, JOUR) == (Motif.STAGE_CONVENTIONNE, "description : stage de 6 mois")


# --------------------------------------------------------------------------- 2 et 3. métiers écartés

@pytest.mark.parametrize("titre", [
    "Business analyste informatique IA / Data Science – Full Remote (IT)",              # Net technologie
    "Business analyste informatique & Data Engineer Big Data (Spark / Hadoop) - H/F",   # Storm Group
    "Enseignant-Chercheur en Intelligence Artificielle (H/F)",                           # CESI
    "Doctorant en machine learning",
    "Post-doctorant data science",
])
def test_metiers_ecartes(config, titre):
    assert rejet(config, titre=titre) == Motif.METIER_HORS_CIBLE


def test_ingenieur_de_recherche_garde(config):
    assert rejet(config, titre="Ingénieur de recherche en intelligence artificielle") is None


# --------------------------------------------------------------------------- 4. ESN sous leur nom complet

@pytest.mark.parametrize("nom", ["SOCIETE POUR L'INFORMATIQUE INDUSTRIELLE", "Groupe LR Technologies", "Ekkiden",
                                 "Aubay", "Davidson Consulting", "SII"])
def test_esn_reconnues(config, nom):
    assert normaliser_offre(offre(entreprise=nom), config).type_employeur == TypeEmployeur.ESN


# --------------------------------------------------------------------------- 5 et 6. doublons

@pytest.mark.parametrize("a, b", [
    ("Data Scientist (H/F) AEROMIN", "Data Scientist (H/F)"),                              # Transavia
    ("Data Engineer Python / PySpark F/H (CDI)", "Data Engineer Python / PySpark F/H"),    # LR Technologies
    ("Data Engineer (x/f/m)", "Data Engineer"),
])
def test_titres_souples_identiques(a, b):
    assert titre_souple(a) == titre_souple(b)


def test_titre_en_capitales_intact():
    assert titre_souple("INGENIEUR BIG DATA - DATA ENGINEER") == "ingenieur big data data engineer"


def test_fusion_dans_un_meme_passage(config):
    a = normaliser_offre(offre(titre="Data Scientist (H/F) AEROMIN", entreprise="Transavia"), config)
    b = normaliser_offre(offre(titre="Data Scientist (H/F)", entreprise="Transavia", source="adzuna"), config)
    assert len(fusionner([a, b])) == 1


def test_empreinte(config):
    a = normaliser_offre(offre(entreprise="Transavia", description=DESCRIPTION_TRANSAVIA), config)
    b = normaliser_offre(offre(entreprise="Transavia", titre="Analyste ML", description=DESCRIPTION_TRANSAVIA), config)
    c = normaliser_offre(offre(entreprise="Air France", description=DESCRIPTION_TRANSAVIA), config)
    assert a.empreinte == b.empreinte != c.empreinte
    assert normaliser_offre(offre(description="Courte description."), config).empreinte is None


def _sources(lot):
    return {"france_travail": lambda ctx: [offre(**kw) for kw in lot], "adzuna": lambda ctx: [],
            "hellowork": lambda ctx: [], "service_public": lambda ctx: [], "la_bonne_alternance": lambda ctx: []}


@pytest.mark.parametrize("second", [
    {"titre": "Data Scientist (H/F) AEROMIN", "entreprise": "Transavia"},                       # clé souple
    {"titre": "Data Scientist ML/RO", "entreprise": "Transavia", "description": DESCRIPTION_TRANSAVIA},  # empreinte
])
def test_doublon_d_un_passage_a_l_autre(tmp_path, config, second):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    premier = {"titre": "Data Scientist (H/F)", "entreprise": "Transavia", "description": DESCRIPTION_TRANSAVIA}
    r1 = main.passage(config, base, datetime(2026, 10, 27, 9, 0), sources_imposees=["france_travail"],
                      session=object(), sources=_sources([premier]))
    r2 = main.passage(config, base, datetime(2026, 10, 28, 9, 0), sources_imposees=["france_travail"],
                      session=object(), sources=_sources([second]))
    assert r1.nouvelles == 1 and r2.nouvelles == 0 and r2.doublons_ecartes == 1
    with sqlite3.connect(base.chemin) as c:
        assert c.execute("SELECT COUNT(*) FROM offres").fetchone()[0] == 1


def test_doublon_trop_ancien_redevient_nouveau(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    o = normaliser_offre(offre(titre="Data Scientist (H/F)", entreprise="Transavia"), config)
    stockage.enregistrer_offres(base, [o], datetime(2026, 9, 1))
    v = normaliser_offre(offre(titre="Data Scientist (H/F) AEROMIN", entreprise="Transavia"), config)
    assert stockage.doublons(base, [v], datetime(2026, 10, 28) - timedelta(days=30)) == {}


def test_migration_vers_la_version_3(tmp_path, config):
    chemin = tmp_path / "b.sqlite"
    stockage.ouvrir(chemin)
    o = normaliser_offre(offre(titre="Data Scientist (H/F)", entreprise="Transavia"), config)
    stockage.enregistrer_offres(stockage.Base(chemin), [o], datetime(2026, 10, 27))
    with sqlite3.connect(chemin) as c:   # base en version 2 : colonnes et index absents
        c.execute("DROP INDEX idx_offres_cle_souple")
        c.execute("DROP INDEX idx_offres_empreinte")
        for col in ("cle_souple", "empreinte", "signaux"):
            c.execute(f"ALTER TABLE offres DROP COLUMN {col}")
        c.execute("UPDATE version_schema SET version = 2")
    base = stockage.ouvrir(chemin)
    with sqlite3.connect(chemin) as c:
        assert c.execute("SELECT cle_souple FROM offres").fetchone()[0] == o.cle_souple
        assert c.execute("SELECT version FROM version_schema").fetchone()[0] == 3
    v = normaliser_offre(offre(titre="Data Scientist (H/F) AEROMIN", entreprise="Transavia"), config)
    assert stockage.doublons(base, [v], datetime(2026, 10, 1)) == {v.cle: o.cle}


# --------------------------------------------------------------------------- 7, 8, 9. signaux

@pytest.mark.parametrize("texte, attendu", [
    ("Permis B exigé.", True),                                       # GIP Innovation e-Santé Sud
    ("Déplacements réguliers, permis B requis.", True),
    ("Permis de conduire obligatoire.", True),
    ("Le permis B est un plus.", False),
    ("Titulaire du permis B apprécié.", False),
])
def test_permis(config, texte, attendu):
    assert normaliser_offre(offre(description=texte), config).permis_exige is attendu


def test_cabinet_signale_sans_penalite(config):
    o = normaliser_offre(offre(entreprise="SILKHOM SAS"), config)
    assert o.via_cabinet and o.type_employeur == TypeEmployeur.FINAL


def test_adzuna_description_partielle():
    item = fixture_json("adzuna/titre_data.json")["results"][0]
    assert adzuna.convertir(item).description_partielle


def test_signaux_dans_l_alerte_et_le_journal(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    lot = [{"titre": "Data Engineer junior", "entreprise": "SILKHOM SAS", "url": "https://exemple.fr/silkhom",
            "description": "Python, SQL, Airflow, dbt. Permis B exigé."}]
    r = main.passage(config, base, datetime(2026, 10, 28, 9, 0), sources_imposees=["france_travail"],
                     session=object(), sources=_sources(lot))
    assert "https://exemple.fr/silkhom" in r.exemples_nouvelles[0]
    assert "permis B exigé" in r.exemples_nouvelles[0] and "via cabinet" in r.exemples_nouvelles[0]
    ligne = stockage.a_resumer(base, "emploi")[0] if r.par_niveau.get("resume") else stockage.alertes_a_envoyer(base)[0]
    assert {"permis B exigé", "via cabinet"} <= set(ligne["signaux"])
    assert "permis B exigé" in message_alerte(ligne)
