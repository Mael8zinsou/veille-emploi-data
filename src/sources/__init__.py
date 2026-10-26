"""Sources d'offres. Contrat commun (conception § 3) :

    NOM: str                       # identifiant, aussi utilisé par le planning et la base
    def fetch(ctx: Contexte) -> list[Offre]

Une source interroge elle-même tous les fils qu'elle sert (Emploi, Alternance) et renseigne
`Offre.fil_demande`. Elle passe par `ctx.get` / `ctx.post`, qui comptent les requêtes et
gardent les erreurs : une requête en échec est journalisée et la source continue. Si toutes
ses requêtes échouent, ou si un accès manque, elle lève `SourceIndisponible` : le passage
continue avec les autres sources, et l'échec est enregistré pour le bilan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import requests

from src.config import Config

logger = logging.getLogger(__name__)

DELAI_DEFAUT = 20  # secondes


class SourceIndisponible(Exception):
    """La source ne peut rien rendre lors de ce passage (accès manquant, refus, panne)."""


@dataclass
class Contexte:
    config: Config
    session: requests.Session
    maintenant_utc: datetime
    requetes: int = 0
    erreurs: list[str] = field(default_factory=list)

    def _appel(self, methode: str, url: str, **kwargs) -> requests.Response | None:
        kwargs.setdefault("timeout", DELAI_DEFAUT)
        self.requetes += 1
        try:
            r = self.session.request(methode, url, **kwargs)
        except requests.RequestException as e:
            self.erreurs.append(f"{url.split('?')[0]} : {e.__class__.__name__}")
            logger.warning("%s %s : %s", methode, url.split("?")[0], e.__class__.__name__)
            return None
        if r.status_code >= 400:
            self.erreurs.append(f"{url.split('?')[0]} : HTTP {r.status_code}")
            logger.warning("%s %s : HTTP %s", methode, url.split("?")[0], r.status_code)
            return None
        return r

    def get(self, url: str, **kwargs) -> requests.Response | None:
        return self._appel("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response | None:
        return self._appel("POST", url, **kwargs)

    def verifier(self, nom: str, preliminaires: int = 0) -> None:
        """À appeler en fin de collecte : toutes les requêtes de recherche en échec = source indisponible.

        `preliminaires` : requêtes réussies qui ne rapportent pas d'offres (jeton d'accès),
        exclues du compte.
        """
        utiles = self.requetes - preliminaires
        if utiles > 0 and len(self.erreurs) >= utiles:
            raise SourceIndisponible(f"{nom} : {utiles} requêtes, toutes en échec ({self.erreurs[0]})")
