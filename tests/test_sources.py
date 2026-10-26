"""Sources, sur des réponses réelles capturées au sondage du 25 octobre 2026 (branche `sondes`)."""
from datetime import datetime

import pytest
import requests

from src.filtres import normaliser_offre
from src.models import Contrat, Fil
from src.sources import Contexte, SourceIndisponible, adzuna, france_travail, hellowork
from tests.conftest import FausseSession, Reponse, fixture_json, fixture_texte

MAINTENANT = datetime(2026, 10, 26, 9, 0)


def ctx(config, repondre):
    return Contexte(config=config, session=FausseSession(repondre), maintenant_utc=MAINTENANT)


@pytest.fixture(autouse=True)
def sans_pause(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture
def identifiants(monkeypatch):
    for nom in ("FT_CLIENT_ID", "FT_CLIENT_SECRET", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.setenv(nom, "x")


# --------------------------------------------------------------------------- France Travail

def test_ft_conversion_reelle(config):
    items = fixture_json("france_travail/emploi_data_engineer.json")["resultats"]
    offres = [france_travail.convertir(i, Fil.EMPLOI) for i in items]
    assert len(offres) == 40 and all(o.titre and o.url for o in offres)
    assert any(o.experience_annees is not None for o in offres)
    assert any(o.diffuseur for o in offres)          # reprises de partenaires
    assert {o.code_rome for o in offres} >= {"M1811"}


def test_ft_alternance_reelle(config):
    items = fixture_json("france_travail/alternance.json")["resultats"]
    offres = [normaliser_offre(france_travail.convertir(i, Fil.ALTERNANCE), config) for i in items]
    assert offres and all(o.contrat == Contrat.ALTERNANCE for o in offres)
    assert all(o.fil == Fil.ALTERNANCE for o in offres)


def _repondeur_ft(pages_totales=1, statut=200):
    items = fixture_json("france_travail/emploi_ia.json")["resultats"]

    def repondre(methode, url, kw):
        if "access_token" in url:
            return Reponse(200, {"access_token": "jeton"})
        debut = int(kw["params"]["range"].split("-")[0])
        total = 150 * pages_totales
        return Reponse(statut, {"resultats": items}, headers={"Content-Range": f"offres {debut}-{debut + 149}/{total}"})
    return repondre


def test_ft_pagination_et_dates(config, identifiants):
    c = ctx(config, _repondeur_ft(pages_totales=3))
    offres = france_travail.fetch(c)
    appels = [a for a in c.session.appels if "search" in a[1]]
    cfg = config.sources.france_travail
    attendus = len(cfg.emploi.romes) * cfg.max_pages + len(cfg.emploi.mots_cles) + len(cfg.alternance.romes) \
        + len(cfg.alternance.mots_cles)
    assert len(appels) == attendus
    assert all("minCreationDate" in a[2]["params"] and "maxCreationDate" in a[2]["params"] for a in appels)
    assert c.requetes == attendus + 1      # + le jeton
    assert {o.fil_demande for o in offres} == {Fil.EMPLOI, Fil.ALTERNANCE}


def test_ft_sans_identifiants(config, monkeypatch):
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, lambda *a: Reponse()))


def test_ft_jeton_refuse(config, identifiants):
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, lambda m, u, k: Reponse(401, {})))


def test_ft_toutes_requetes_en_echec(config, identifiants):
    def repondre(m, u, k):
        return Reponse(200, {"access_token": "j"}) if "access_token" in u else Reponse(500, {})
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, repondre))


def test_ft_aucun_resultat(config, identifiants):
    def repondre(m, u, k):
        return Reponse(200, {"access_token": "j"}) if "access_token" in u else Reponse(204)
    assert france_travail.fetch(ctx(config, repondre)) == []


def test_ft_erreur_reseau_isolee(config, identifiants):
    items = fixture_json("france_travail/emploi_ia.json")["resultats"]
    n = {"i": 0}

    def repondre(m, u, k):
        if "access_token" in u:
            return Reponse(200, {"access_token": "j"})
        n["i"] += 1
        return requests.ConnectionError() if n["i"] == 1 else Reponse(200, {"resultats": items}, headers={})
    c = ctx(config, repondre)
    assert france_travail.fetch(c) and len(c.erreurs) == 1


# --------------------------------------------------------------------------- Adzuna

def test_adzuna_reel_et_pages(config, identifiants):
    donnees = fixture_json("adzuna/titre_data.json")
    c = ctx(config, lambda m, u, k: Reponse(200, donnees))
    offres = adzuna.fetch(c)
    pages = sum(r.pages for r in config.sources.adzuna.requetes)
    assert c.requetes == pages and len(offres) == 50 * pages
    params = c.session.appels[0][2]["params"]
    assert params["title_only"] == "data" and params["sort_by"] == "date" and "what_exclude" not in params


def test_adzuna_derniere_page_courte(config, identifiants):
    donnees = fixture_json("adzuna/titre_data.json")
    donnees = {**donnees, "results": donnees["results"][:10]}
    c = ctx(config, lambda m, u, k: Reponse(200, donnees))
    assert len(adzuna.fetch(c)) == 10 and c.requetes == 1


def test_adzuna_sans_identifiants(config, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    with pytest.raises(SourceIndisponible):
        adzuna.fetch(ctx(config, lambda *a: Reponse()))


# --------------------------------------------------------------------------- HelloWork

def test_hellowork_lecture_reelle():
    offres = hellowork.lire_page(fixture_texte("hellowork/data_scientist.html"), Fil.EMPLOI)
    assert len(offres) == 30
    assert all(o.titre and o.entreprise and o.lieu and o.url.startswith("https://www.hellowork.com/") for o in offres)


def test_hellowork_titre_avec_a():
    offres = hellowork.lire_page(fixture_texte("hellowork/alternance_data.html"), Fil.ALTERNANCE)
    o = next(o for o in offres if "Bac+4 à Bac+5" in o.titre)
    assert "," not in o.lieu and o.entreprise == "NEXA Digital School"


def test_hellowork_refus_coupe_la_source(config, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(SourceIndisponible):
        hellowork.fetch(ctx(config, lambda m, u, k: Reponse(403, text="Access denied")))


def test_hellowork_parcourt_les_recherches(config, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    page = fixture_texte("hellowork/data_scientist.html")
    c = ctx(config, lambda m, u, k: Reponse(200, text=page if k["params"]["p"] == 1 else "<html></html>"))
    offres = hellowork.fetch(c)
    cfg = config.sources.hellowork
    assert len(offres) == 30 * (len(cfg.emploi) + len(cfg.alternance))
    assert {o.fil_demande for o in offres} == {Fil.EMPLOI, Fil.ALTERNANCE}


def test_session_honnete():
    from src.utils.http import build_session
    s = build_session()
    assert "veille-emploi-data" in s.headers["User-Agent"] and "Mozilla" not in s.headers["User-Agent"]
