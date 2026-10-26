"""Outils communs des tests : configuration réelle, fabrique d'offres, faux client HTTP."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.config import charger
from src.models import Offre

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def config():
    return charger()


def offre(**kw) -> Offre:
    valeurs = {"source": "test", "titre": "Data Engineer H/F", "entreprise": "Doctolib", "lieu": "Paris",
               "url": "https://exemple.fr/1", "contrat_brut": "CDI", "date_publication": "2026-10-25"}
    valeurs.update(kw)
    return Offre(**valeurs)


def fixture_json(chemin: str):
    return json.loads((FIXTURES / chemin).read_text(encoding="utf-8"))


def fixture_texte(chemin: str) -> str:
    return (FIXTURES / chemin).read_text(encoding="utf-8")


@dataclass
class Reponse:
    status_code: int = 200
    donnees: object = None
    text: str = ""
    headers: dict = field(default_factory=dict)

    def json(self):
        if self.donnees is None:
            raise ValueError("pas de JSON")
        return self.donnees


@dataclass
class FausseSession:
    """Rejoue des réponses selon une fonction (méthode, url, kwargs) -> Reponse ou exception."""
    repondre: object
    appels: list = field(default_factory=list)

    def request(self, methode, url, **kwargs):
        self.appels.append((methode, url, kwargs))
        r = self.repondre(methode, url, kwargs)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)
