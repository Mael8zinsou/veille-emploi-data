"""
Tests des sources Phase 2.
Aucun appel réseau réel : on mocke les réponses HTTP (session/get_json).
On vérifie : parsing -> Offre, filtrage localisation FR, résilience (slug en erreur),
et le délai poli entre slugs (mocké pour ne pas ralentir les tests).
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.sources import (
    _ats_common,
    adzuna,
    apec,
    ashby,
    france_travail,
    greenhouse,
    lever,
    teamtailor,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    """Neutralise la pause polie entre slugs pour que les tests restent instantanés."""
    with patch.object(_ats_common.time, "sleep", lambda *_: None):
        yield


@pytest.fixture
def config():
    return SimpleNamespace(fraicheur_max_jours=14)


# --------------------------------------------------------------------------
# _ats_common.localisation_pertinente
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "loc,attendu",
    [
        ("Paris, France", True),
        ("Île-de-France", True),
        ("Remote - Europe", True),
        ("Bruxelles", True),
        ("Télétravail", True),
        ("Lyon", True),
        ("Berlin, Germany", False),
        ("New York", False),
        ("", False),
        ("London, UK", False),
    ],
)
def test_localisation_pertinente(loc, attendu):
    assert _ats_common.localisation_pertinente(loc) is attendu


def test_slugs_pour_filtre_par_ats():
    slugs = [("greenhouse", "a"), ("lever", "b"), ("greenhouse", "c")]
    assert _ats_common.slugs_pour("greenhouse", slugs) == ["a", "c"]
    assert _ats_common.slugs_pour("ashby", slugs) == []


# --------------------------------------------------------------------------
# Helpers de mock
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class FakeSession:
    """Session dont .get retourne une réponse par URL (ou par défaut)."""
    def __init__(self, default=None, by_substring=None):
        self.default = default or FakeResponse(404, {})
        self.by_substring = by_substring or {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for sub, resp in self.by_substring.items():
            if sub in url:
                return resp
        return self.default


# --------------------------------------------------------------------------
# Adzuna
# --------------------------------------------------------------------------

def test_adzuna_sans_credentials(monkeypatch, config):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    assert adzuna.fetch(config, FakeSession()) == []


def test_adzuna_parse(monkeypatch, config):
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    payload = {
        "results": [
            {
                "title": "Data Engineer Junior",
                "company": {"display_name": "Spendesk"},
                "location": {"display_name": "Paris"},
                "contract_type": "permanent",
                "description": "Python SQL Airflow",
                "redirect_url": "https://adzuna/x",
                "created": "2026-06-10T08:00:00Z",
            }
        ]
    }
    session = FakeSession(default=FakeResponse(200, payload))
    offres = adzuna.fetch(config, session)
    # 4 requêtes -> chaque requête renvoie la même offre (le dédoublonnage est fait en aval)
    assert len(offres) == len(adzuna.REQUETES)
    o = offres[0]
    assert o.source == "Adzuna"
    assert o.titre == "Data Engineer Junior"
    assert o.entreprise == "Spendesk"
    assert o.date_publication == "2026-06-10"


def test_adzuna_http_error_renvoie_vide(monkeypatch, config):
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    session = FakeSession(default=FakeResponse(500, {}))
    assert adzuna.fetch(config, session) == []


# --------------------------------------------------------------------------
# France Travail
# --------------------------------------------------------------------------

def test_france_travail_sans_credentials(monkeypatch, config):
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    monkeypatch.delenv("FT_CLIENT_SECRET", raising=False)
    assert france_travail.fetch(config, FakeSession()) == []


def test_france_travail_parse(monkeypatch, config):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "secret")

    search_payload = {
        "resultats": [
            {
                "id": "123ABC",
                "intitule": "Data Engineer",
                "entreprise": {"nom": "ACME"},
                "lieuTravail": {"libelle": "Paris (75)"},
                "typeContratLibelle": "Contrat à durée indéterminée",
                "description": "dbt snowflake",
                "origineOffre": {"urlOrigine": "https://ft/123"},
                "dateCreation": "2026-06-09T10:00:00.000Z",
            }
        ]
    }

    class FTSession(FakeSession):
        def post(self, url, **kwargs):
            return FakeResponse(200, {"access_token": "tok"})

    session = FTSession(default=FakeResponse(200, search_payload))
    offres = france_travail.fetch(config, session)
    assert len(offres) == len(france_travail.REQUETES)
    o = offres[0]
    assert o.source == "France Travail"
    assert o.entreprise == "ACME"
    assert o.url == "https://ft/123"
    assert o.date_publication == "2026-06-09"


def test_france_travail_token_echoue(monkeypatch, config):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "secret")

    class FTSession(FakeSession):
        def post(self, url, **kwargs):
            return FakeResponse(401, {})

    assert france_travail.fetch(config, FTSession()) == []


# --------------------------------------------------------------------------
# Greenhouse / Lever / Ashby
# --------------------------------------------------------------------------

def test_greenhouse_filtre_localisation(monkeypatch, config):
    payload = {
        "jobs": [
            {"title": "Data Engineer", "location": {"name": "Paris, France"},
             "content": "x", "absolute_url": "https://gh/1", "updated_at": "2026-06-10T00:00:00Z"},
            {"title": "Data Engineer", "location": {"name": "Berlin, Germany"},
             "content": "x", "absolute_url": "https://gh/2", "updated_at": "2026-06-10T00:00:00Z"},
        ]
    }
    session = FakeSession(default=FakeResponse(200, payload))
    monkeypatch.setattr(greenhouse, "load_slugs", lambda _: [("greenhouse", "spendesk")])
    offres = greenhouse.fetch(config, session)
    assert len(offres) == 1
    assert offres[0].localisation == "Paris, France"
    assert offres[0].source == "Greenhouse"
    assert offres[0].entreprise == "spendesk"


def test_greenhouse_slug_404_ne_casse_pas(monkeypatch, config):
    ok_payload = {"jobs": [
        {"title": "DE", "location": {"name": "Paris"}, "content": "x",
         "absolute_url": "https://gh/ok", "updated_at": "2026-06-10T00:00:00Z"}
    ]}
    session = FakeSession(
        default=FakeResponse(404, {}),
        by_substring={"/boards/ok/": FakeResponse(200, ok_payload)},
    )
    monkeypatch.setattr(
        greenhouse, "load_slugs",
        lambda _: [("greenhouse", "mort"), ("greenhouse", "ok")],
    )
    offres = greenhouse.fetch(config, session)
    assert len(offres) == 1
    assert offres[0].url == "https://gh/ok"


def test_greenhouse_aucun_slug(monkeypatch, config):
    monkeypatch.setattr(greenhouse, "load_slugs", lambda _: [])
    assert greenhouse.fetch(config, FakeSession()) == []


def test_lever_parse_et_filtre(monkeypatch, config):
    payload = [
        {"text": "Data Engineer", "categories": {"location": "Remote (France)", "commitment": "Full-time"},
         "descriptionPlain": "python", "hostedUrl": "https://lever/1"},
        {"text": "Data Engineer", "categories": {"location": "Tokyo"},
         "descriptionPlain": "python", "hostedUrl": "https://lever/2"},
    ]
    session = FakeSession(default=FakeResponse(200, payload))
    monkeypatch.setattr(lever, "load_slugs", lambda _: [("lever", "alan")])
    offres = lever.fetch(config, session)
    assert len(offres) == 1
    assert offres[0].source == "Lever"
    assert offres[0].contrat == "Full-time"


def test_ashby_parse_et_filtre(monkeypatch, config):
    payload = {"jobs": [
        {"title": "Analytics Engineer", "locationName": "Paris", "descriptionPlain": "dbt",
         "jobUrl": "https://ashby/1", "employmentType": "FullTime", "publishedDate": "2026-06-08T00:00:00Z"},
        {"title": "Analytics Engineer", "locationName": "San Francisco", "descriptionPlain": "dbt",
         "jobUrl": "https://ashby/2"},
    ]}
    session = FakeSession(default=FakeResponse(200, payload))
    monkeypatch.setattr(ashby, "load_slugs", lambda _: [("ashby", "pigment")])
    offres = ashby.fetch(config, session)
    assert len(offres) == 1
    assert offres[0].source == "Ashby"
    assert offres[0].date_publication == "2026-06-08"


def test_ashby_remote_garde_meme_si_location_hors_fr(monkeypatch, config):
    # Schéma réel : champ `location` (pas locationName) + flag isRemote.
    payload = {"jobs": [
        {"title": "Data Engineer", "location": "United States", "isRemote": True,
         "descriptionPlain": "x", "jobUrl": "https://ashby/r", "publishedAt": "2026-06-08T00:00:00Z"},
        {"title": "Data Engineer", "location": "United States", "isRemote": False,
         "descriptionPlain": "x", "jobUrl": "https://ashby/n"},
    ]}
    session = FakeSession(default=FakeResponse(200, payload))
    monkeypatch.setattr(ashby, "load_slugs", lambda _: [("ashby", "dust")])
    offres = ashby.fetch(config, session)
    # Le remote est gardé, le US non-remote est filtré.
    assert len(offres) == 1
    assert offres[0].url == "https://ashby/r"
    assert offres[0].date_publication == "2026-06-08"


def _tt_item(titre, ville, pays, org="Deezer", url="https://x.teamtailor.com/jobs/1"):
    return {
        "title": titre,
        "url": url,
        "date_published": "2026-08-10T09:00:00+02:00",
        "content_html": "<p>python sql</p>",
        "_jobposting": {
            "@type": "JobPosting",
            "title": titre,
            "description": "<p>python sql airflow</p>",
            "datePosted": "2026-08-10T09:00:00+02:00",
            "hiringOrganization": {"@type": "Organization", "name": org},
            "jobLocation": [
                {"@type": "Place",
                 "address": {"@type": "PostalAddress",
                             "addressLocality": ville, "addressCountry": pays}}
            ],
        },
    }


def test_teamtailor_parse_fr_et_nom_reel(monkeypatch, config):
    payload = {"items": [
        _tt_item("Data Engineer", "Paris", "FR", org="Deezer"),
        _tt_item("Data Engineer", "Amsterdam", "NL", org="Tibber"),
    ]}
    session = FakeSession(default=FakeResponse(200, payload))
    monkeypatch.setattr(teamtailor, "load_slugs", lambda _: [("teamtailor", "deezer")])
    offres = teamtailor.fetch(config, session)
    assert len(offres) == 1
    o = offres[0]
    assert o.source == "Teamtailor"
    assert o.entreprise == "Deezer"          # vrai nom, pas le slug
    assert "France" in o.localisation
    assert "python" in o.description.lower() and "<p>" not in o.description  # HTML retiré
    assert o.date_publication == "2026-08-10"


def test_teamtailor_remote_sans_lieu(monkeypatch, config):
    item = {
        "title": "Data Engineer",
        "url": "https://x.teamtailor.com/jobs/2",
        "_jobposting": {
            "hiringOrganization": {"name": "Skello"},
            "jobLocationType": "TELECOMMUTE",
            "description": "data engineer",
        },
    }
    session = FakeSession(default=FakeResponse(200, {"items": [item]}))
    monkeypatch.setattr(teamtailor, "load_slugs", lambda _: [("teamtailor", "skello")])
    offres = teamtailor.fetch(config, session)
    assert len(offres) == 1
    assert offres[0].localisation == "Remote"


def test_teamtailor_slug_obsolete_ne_casse_pas(monkeypatch, config):
    session = FakeSession(default=FakeResponse(404, {}))
    monkeypatch.setattr(teamtailor, "load_slugs", lambda _: [("teamtailor", "mort")])
    assert teamtailor.fetch(config, session) == []


class ApecSession:
    """Session dont chaque .post renvoie la même page APEC.
    La pagination s'arrête d'elle-même car la page (< 50 résultats) est non pleine."""
    def __init__(self, resultats):
        self._resultats = resultats

    def post(self, url, **kwargs):
        return FakeResponse(200, {"resultats": self._resultats})


def _apec_item(intitule="Data Engineer F/H", code=101888, faible=False, jours=1):
    from datetime import datetime, timedelta
    d = (datetime.now().astimezone() - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%S.000%z")
    return {
        "numeroOffre": "123456W", "id": 123456,
        "intitule": intitule, "nomCommercial": "ACME",
        "lieuTexte": "Paris - 75", "typeContrat": code,
        "texteOffre": "python sql airflow", "datePublication": d,
        "indicateurFaibleCandidature": faible,
    }


def test_apec_parse_cdi_et_url(config):
    session = ApecSession([_apec_item(code=101888)])
    offres = apec.fetch(config, session)
    assert len(offres) == len(apec.REQUETES)  # une page par requête
    o = offres[0]
    assert o.source == "APEC"
    assert o.contrat == "CDI"
    assert o.entreprise == "ACME"
    assert o.url.endswith("/detail-offre/123456W")
    assert o.faible_concurrence is False


def test_apec_mappe_cdd(config):
    session = ApecSession([_apec_item(code=101887)])
    offres = apec.fetch(config, session)
    assert offres[0].contrat == "CDD"


def test_apec_signal_faible_candidature(config):
    session = ApecSession([_apec_item(faible=True)])
    offres = apec.fetch(config, session)
    assert offres[0].faible_concurrence is True


def test_apec_filtre_fraicheur(config):
    # config.fraicheur_max_jours = 14 ; une offre publiée il y a 30 jours est écartée.
    session = ApecSession([_apec_item(jours=30)])
    assert apec.fetch(config, session) == []


def test_apec_http_error_ne_casse_pas(config):
    class BadSession:
        def post(self, url, **kwargs):
            return FakeResponse(500, {})
    assert apec.fetch(config, BadSession()) == []


def test_ats_reponse_inattendue_ne_casse_pas(monkeypatch, config):
    # Greenhouse attend un dict, Lever une liste : on inverse pour vérifier la robustesse.
    monkeypatch.setattr(greenhouse, "load_slugs", lambda _: [("greenhouse", "x")])
    monkeypatch.setattr(lever, "load_slugs", lambda _: [("lever", "x")])
    session_list = FakeSession(default=FakeResponse(200, []))      # liste là où GH veut un dict
    session_dict = FakeSession(default=FakeResponse(200, {}))      # dict là où Lever veut une liste
    assert greenhouse.fetch(config, session_list) == []
    assert lever.fetch(config, session_dict) == []
