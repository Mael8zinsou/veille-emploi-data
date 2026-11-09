"""Vérification des offres (9/11) : page de l'offre, expérience réelle, mode de candidature."""
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime

import pytest

from src import stockage
from src.dedoublonnage import fusionner, meilleure_candidature
from src.filtres import motif_de_rejet, normaliser_offre
from src.models import Candidature, ModeCandidature, Motif
from src.normalisation import candidature as cand
from src.sources import Contexte, adzuna, hellowork, service_public
from src.sources.france_travail import convertir as convertir_ft
from tests.conftest import FausseSession, Reponse, fixture_texte, offre

MAINTENANT = datetime(2026, 11, 9, 9, 0)
JOUR = date(2026, 10, 26)   # date des offres de test (conftest)
F, C, M, S = ModeCandidature.FORMULAIRE, ModeCandidature.COMPTE, ModeCandidature.MAIL, ModeCandidature.SITE


@pytest.fixture(autouse=True)
def sans_pause(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def ctx(config, repondre, memoire=None):
    return Contexte(config=config, session=FausseSession(repondre), maintenant_utc=MAINTENANT, memoire=memoire or {})


# --------------------------------------------------------------------------- HelloWork

@pytest.mark.parametrize("fixture, annees, debut", [
    ("detail_5_ans", 5, "Les missions du poste"),
    ("detail_1_an", 1, "Détail du poste"),
    ("detail_alternance", None, "Les missions du poste"),
])
def test_hellowork_page_reelle(fixture, annees, debut):
    d = hellowork.lire_detail(fixture_texte(f"hellowork/{fixture}.html"))
    assert d["experience"] == annees
    assert d["description"].startswith(debut) and 500 < len(d["description"]) <= 3000
    assert "Créer mon alerte" not in d["description"] and "Voir plus" not in d["description"]


def test_hellowork_cinq_ans_rejetee_apres_lecture(config):
    o = offre(source="hellowork", titre="Ingénieur Data Analytics H/F", entreprise="Segula Technologies")
    assert motif_de_rejet(normaliser_offre(offre(source="hellowork", titre=o.titre), config), config, JOUR) is None
    hellowork.completer(o, hellowork.lire_detail(fixture_texte("hellowork/detail_5_ans.html")))
    assert motif_de_rejet(normaliser_offre(o, config), config, JOUR)[0] == Motif.SENIORITE
    assert o.candidature.mode == C and o.candidature.plateforme == "HelloWork"


def test_hellowork_lecture_unique_et_plafonnee(config):
    page = fixture_texte("hellowork/detail_1_an.html")
    deja = offre(source="hellowork", id_source="1", titre="Data Analyst", url="https://hw/1")
    nouvelles = [offre(source="hellowork", id_source=str(i), titre="Data Engineer", url=f"https://hw/{i}") for i in range(2, 60)]
    hors_cible = offre(source="hellowork", id_source="99", titre="Comptable", url="https://hw/99")
    c = ctx(config, lambda m, u, k: Reponse(200, text=page), memoire={"1": {"experience": 4, "description": "x"}})
    lues = hellowork.completer_toutes([deja, hors_cible, *nouvelles], c)
    assert lues == config.sources.hellowork.max_details
    assert deja.experience_annees == 4 and "https://hw/1" not in [a[1] for a in c.session.appels]
    assert "https://hw/99" not in [a[1] for a in c.session.appels]       # titre hors cible : page non lue
    assert all(o.candidature is not None for o in [deja, hors_cible, *nouvelles])
    assert nouvelles[0].experience_annees == 1 and "2" in c.memoire
    assert nouvelles[-1].experience_annees is None                       # au-delà du plafond : au prochain passage


def test_hellowork_page_refusee_ignoree(config):
    o = offre(source="hellowork", id_source="5", titre="Data Engineer", url="https://hw/5")
    c = ctx(config, lambda m, u, k: Reponse(403, text="Just a moment"))
    hellowork.completer_toutes([o], c)
    assert o.experience_annees is None and "5" not in c.memoire and o.candidature.mode == C


def test_hellowork_fetch_lit_les_pages_une_fois(config):
    liste = fixture_texte("hellowork/data_scientist.html")
    detail = fixture_texte("hellowork/detail_5_ans.html")
    c = ctx(config, lambda m, u, k: Reponse(200, text=liste if k.get("params", {}).get("p") == 1
                                            else detail if "/emplois/" in u else "<html></html>"))
    offres = hellowork.fetch(c)
    pages = [a[1] for a in c.session.appels if "/emplois/" in a[1]]
    assert len(pages) == len(set(pages)) <= config.sources.hellowork.max_details
    lues = [o for o in offres if o.experience_annees == 5]
    assert lues and all(o.description for o in lues)


# --------------------------------------------------------------------------- Choisir le service public

def test_service_public_par_mail():
    d = service_public.lire_detail(fixture_texte("service_public/detail_mail.html"))
    o = offre(entreprise="")
    service_public.completer(o, d)
    assert o.entreprise == "Secrétariat Général"
    assert o.candidature.mode == M and o.candidature.date_limite == "2026-11-20"
    assert o.candidature.lien.startswith("mailto:")
    assert o.candidature.libelle() == "candidature : par mail, avant le 20/11"


def test_service_public_site_employeur_et_confirme():
    d = service_public.lire_detail(fixture_texte("service_public/detail_site_employeur.html"))
    o = offre(entreprise="")
    service_public.completer(o, d)
    assert o.experience_annees == 3                                      # « Confirmé »
    assert o.candidature.mode == C and o.candidature.plateforme == "Talentsoft"
    assert "talent-soft.com" in o.candidature.lien and "&#038;" not in o.candidature.lien
    assert o.candidature.date_limite == "2026-12-31"


def test_service_public_memoire_garde_la_candidature():
    d = service_public.lire_detail(fixture_texte("service_public/detail_mail.html"))
    garde = {k: d[k] for k in service_public._CHAMPS_GARDES if k in d}
    o = offre(entreprise="")
    service_public.completer(o, garde)
    assert o.candidature.mode == M


def test_service_public_page_sans_bouton():
    assert service_public.lire_candidature("<html>rien</html>") == {}


# --------------------------------------------------------------------------- classement des liens

@pytest.mark.parametrize("lien, mode, plateforme", [
    ("https://boards.greenhouse.io/doctolib/jobs/1", F, "Greenhouse"),
    ("https://jobs.lever.co/qonto/abc", F, "Lever"),
    ("https://acme.wd3.myworkdayjobs.com/fr/job/1", C, "Workday"),
    ("https://emploi.cnrs.fr/Offres/CDD/X/Default.aspx", C, "CNRS"),
    ("https://www.welcometothejungle.com/fr/companies/x/jobs/y", F, "Welcome to the Jungle"),
    ("https://carrieres.exemple.fr/offre/12", S, "carrieres.exemple.fr"),
    ("mailto:rh@exemple.fr", M, ""),
    ("", ModeCandidature.INCONNU, ""),
])
def test_depuis_lien(lien, mode, plateforme):
    c = cand.depuis_lien(lien)
    assert c.mode == mode and c.plateforme == plateforme


@pytest.mark.parametrize("item, mode, plateforme", [
    ({"contact": {"urlPostulation": "https://jobs.lever.co/x/1"}}, F, "Lever"),
    ({"contact": {"courriel": "rh@exemple.fr"}}, M, ""),
    ({"origineOffre": {"partenaires": [{"nom": "BEETWEEN", "url": "https://x.beetween.com/1"}]}}, F, "Beetween"),
    ({"origineOffre": {"partenaires": [{"nom": "PMEJOB", "url": "https://www.jobposting.pro/emploi-1"}]}}, C, "Pmejob"),
    ({"origineOffre": {"partenaires": [{"nom": "METEOJOB", "url": "https://www.meteojob.com/x"}]}}, C, "Meteojob"),
    ({}, C, "France Travail"),
])
def test_depuis_france_travail(item, mode, plateforme):
    c = cand.depuis_france_travail(item)
    assert c.mode == mode and c.plateforme == plateforme


def test_france_travail_convertit_la_candidature():
    o = convertir_ft({"id": "X", "intitule": "Data Engineer", "contact": {"courriel": "rh@exemple.fr"}}, None)
    assert o.candidature.mode == M


def test_libelles_sans_adresse():
    assert "@" not in Candidature(M, "", "mailto:rh@exemple.fr").libelle()
    assert Candidature(F, "Lever").libelle() == "candidature : formulaire sans compte (Lever)"
    assert Candidature(C).libelle() == "candidature : compte requis"
    assert Candidature(S).libelle() == "candidature : site de l'employeur"
    assert Candidature(F).libelle() == "candidature : formulaire sans compte"


def test_date_limite_et_dict():
    assert cand.date_limite_fr("Date limite : 31/02/2026") == "" and cand.date_limite_fr("") == ""
    c = Candidature(F, "Lever", "https://jobs.lever.co/x", "2026-11-20")
    assert cand.depuis_dict(c.en_dict()) == c
    assert cand.depuis_dict({"mode": "nimporte"}) is None


def test_adzuna_a_verifier_sans_doublon_de_signal():
    o = adzuna.convertir({"id": 1, "title": "Data Engineer", "redirect_url": "https://www.adzuna.fr/details/1"})
    assert o.candidature.mode == ModeCandidature.A_VERIFIER
    signaux = stockage.signaux_offre(o)
    assert not any(s.startswith("candidature") for s in signaux)


# --------------------------------------------------------------------------- fusion et base

def test_fusion_garde_le_mode_le_plus_simple():
    a = offre(source="adzuna", candidature=Candidature(ModeCandidature.A_VERIFIER, "Adzuna"))
    b = offre(source="hellowork", candidature=Candidature(C, "HelloWork"), description="x" * 10)
    (o,) = fusionner([a, b])
    assert o.candidature.plateforme == "HelloWork" and set(o.sources) == {"adzuna", "hellowork"}
    assert meilleure_candidature(None, b.candidature) is b.candidature
    assert meilleure_candidature(Candidature(F), Candidature(M)).mode == F


def test_base_enregistre_la_candidature(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "v.sqlite")
    o = normaliser_offre(offre(candidature=Candidature(M, "", "mailto:rh@exemple.fr", "2026-11-20")), config)
    stockage.enregistrer_offres(base, [o], MAINTENANT)
    stockage.noter(base, o.cle, 8, [("priorité 1", 6)], "resume")
    (ligne,) = stockage.a_resumer(base, str(o.fil))
    assert ligne["candidature"]["mode"] == "mail" and ligne["candidature"]["date_limite"] == "2026-11-20"
    assert "candidature : par mail, avant le 20/11" in ligne["signaux"]


def test_migration_vers_la_version_4(tmp_path):
    chemin = tmp_path / "v.sqlite"
    stockage.ouvrir(chemin)
    with closing(sqlite3.connect(chemin)) as c, c:
        c.execute("ALTER TABLE offres DROP COLUMN candidature")
        c.execute("UPDATE version_schema SET version = 3")
    stockage.ouvrir(chemin)
    with closing(sqlite3.connect(chemin)) as c:
        assert "candidature" in {r[1] for r in c.execute("PRAGMA table_info(offres)")}
        assert c.execute("SELECT version FROM version_schema").fetchone()[0] == 4


def test_maintenant_utc_naif():
    assert MAINTENANT.replace(tzinfo=UTC).tzinfo is UTC
