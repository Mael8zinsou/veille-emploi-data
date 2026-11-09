"""Offre encore en ligne ? Vérifié juste avant la liste du matin.

Première liste du 9/11 : 4 offres sur 10 avaient été clôturées entre leur détection et leur
traitement (offres de partenaires France Travail surtout). Une offre fermée lue dans Chrome
coûte cher pour rien : la veille la vérifie elle-même, gratuitement, sur GitHub Actions.

* France Travail : API Offres d'emploi, `GET /offres/{id}` (200 en ligne ; 204, 404 ou 410 fermée).
* HelloWork, Choisir le service public : page de l'offre (404 ou 410 fermée).
* Autres sources, ou réponse ambiguë : inconnu, l'offre reste dans la liste.
"""
from __future__ import annotations

import logging
import re

from src.sources import Contexte, france_travail

logger = logging.getLogger(__name__)

URL_API_FT = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/{id}"
_FT = re.compile(r"francetravail\.fr/offres/recherche/detail/([A-Za-z0-9]+)")
_PAGES = ("hellowork.com/fr-fr/emplois/", "choisirleservicepublic.gouv.fr/offre-emploi/")


class Verificateur:
    def __init__(self, ctx: Contexte) -> None:
        self.ctx = ctx
        self._jeton: str | None = None
        self._ft_indisponible = False

    def _jeton_ft(self) -> str | None:
        if self._jeton is None and not self._ft_indisponible:
            try:
                self._jeton = france_travail._jeton(self.ctx)
            except Exception as ex:  # accès absent ou refusé : vérification FT impossible, pas bloquante
                logger.warning("Disponibilité France Travail non vérifiable : %s", ex)
                self._ft_indisponible = True
        return self._jeton

    def _statut(self, url: str, **kwargs) -> bool | None:
        try:
            r = self.ctx.session.get(url, timeout=20, allow_redirects=False, **kwargs)
        except Exception as ex:  # réseau : on ne conclut rien
            logger.warning("Disponibilité de %s non vérifiable : %s", url.split("?")[0], ex.__class__.__name__)
            return None
        if r.status_code in (204, 404, 410):
            return False
        if r.status_code == 200:
            return True
        return None

    def en_ligne(self, url: str) -> bool | None:
        """True en ligne, False fermée, None inconnu (source non vérifiable, réponse ambiguë)."""
        m = _FT.search(url or "")
        if m:
            jeton = self._jeton_ft()
            if not jeton:
                return None
            return self._statut(URL_API_FT.format(id=m.group(1)),
                                headers={"Authorization": f"Bearer {jeton}", "Accept": "application/json"})
        if any(p in (url or "") for p in _PAGES):
            return self._statut(url)
        return None
