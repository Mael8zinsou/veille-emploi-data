"""
Tests des sources niches Phase 3.
HelloWork : parsing sur fixture HTML (pas de réseau), détection blocage, filtrage loc.
Choose : no-op.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.sources import choose, hellowork


@pytest.fixture(autouse=True)
def _no_sleep():
    """Neutralise le délai entre pages pour des tests instantanés."""
    with patch.object(hellowork.time, "sleep", lambda *_: None):
        yield


@pytest.fixture
def config():
    return SimpleNamespace(fraicheur_max_jours=14)


# Fixture : 3 ancres telles que rendues par HelloWork (href + aria-label structuré).
# 2 en localisation cible (Paris, Lyon), 1 hors cible (Berlin) pour tester le filtre.
HTML_OK = """
<html><body>
<a href="/fr-fr/emplois/111.html"
   aria-label="Voir offre de Data Engineer H/F &#xE0; Paris 17e - 75, chez Team.is, super recruteur, pour un CDI, en temps plein">lien</a>
<a href="/fr-fr/emplois/222.html"
   aria-label="Voir offre de Analytics Engineer &#xE0; Lyon - 69, chez Acme, pour un CDI, avec un salaire de 45 000 &#x20AC; / an, en temps plein, T&#xE9;l&#xE9;travail partiel">lien</a>
<a href="/fr-fr/emplois/333.html"
   aria-label="Voir offre de Data Engineer &#xE0; Berlin, chez GmbH, pour un CDI, en temps plein">lien</a>
</body></html>
"""


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        return self._response


def test_hellowork_parse_et_filtre_localisation():
    offres = hellowork._parse_page(HTML_OK)
    # Berlin filtré -> 2 offres FR
    assert len(offres) == 2
    o = offres[0]
    assert o.source == "HelloWork"
    assert o.titre == "Data Engineer H/F"
    assert o.entreprise == "Team.is"
    assert o.localisation == "Paris 17e - 75"
    assert o.contrat == "CDI"
    assert o.url == "https://www.hellowork.com/fr-fr/emplois/111.html"


def test_hellowork_contrat_sans_salaire():
    # La 2e offre a un salaire dans le label : on ne garde que le type de contrat.
    offres = hellowork._parse_page(HTML_OK)
    lyon = [o for o in offres if "Lyon" in o.localisation][0]
    assert lyon.contrat == "CDI"
    assert "salaire" not in lyon.contrat.lower()


def test_hellowork_page_vide_arrete_pagination(config):
    session = FakeSession(FakeResponse(200, "<html><body>aucune offre</body></html>"))
    offres = hellowork._fetch_recherche(session, "data engineer", "Paris")
    assert offres == []
    # Une seule requête (page 1 vide -> stop), pas 3.
    assert len(session.calls) == 1


def test_hellowork_blocage_cloudflare_ne_casse_pas(config):
    session = FakeSession(FakeResponse(403, "Just a moment... cf-challenge"))
    offres = hellowork._fetch_recherche(session, "data engineer", "Paris")
    assert offres == []
    assert len(session.calls) == 1  # blocage détecté dès la page 1


def test_hellowork_fetch_complet_resilient(config):
    # fetch() itère sur REQUETES ; chaque recherche pagine jusqu'à MAX_PAGES tant
    # que les pages ne sont pas vides. Avec une session qui renvoie toujours la
    # même page non vide : nb_recherches * MAX_PAGES * 2 offres FR.
    session = FakeSession(FakeResponse(200, HTML_OK))
    offres = hellowork.fetch(config, session)
    assert len(offres) == len(hellowork.REQUETES) * hellowork.MAX_PAGES * 2
    assert all(o.source == "HelloWork" for o in offres)


def test_choose_est_noop(config):
    assert choose.fetch(config, FakeSession(FakeResponse())) == []
