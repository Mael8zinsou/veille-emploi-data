"""
Source Choose (choose.app) — NO-OP volontaire. Source niche, désactivable.

Statut au 2026-06-11 : désactivée. Choose est une SPA dont les offres ne sont
rendues qu'après exécution JavaScript. Sondage effectué :
  - `api.choose.app` : n'existe pas (DNS ne résout pas).
  - `choose.app` / `www.choose.app` : HTML servi mais aucune donnée d'offre
    statique (pas de __NEXT_DATA__, pas d'Algolia exposé, routes /jobs en 404).
  - L'extraction nécessiterait un navigateur headless (Playwright), hors périmètre
    du brief (§2.3 : pas de scraping lourd) et trop fragile pour un cron quotidien.

Conformément au brief §4.8, on livre un module no-op propre plutôt qu'un scraper
qui casse. Choose reste nice-to-have, non critique.

# TODO: Choose désactivé. Réactiver si une API JSON stable est identifiée
#       (inspecter les Network calls de https://www.choose.app après login,
#       ou évaluer un fetch headless dédié hors pipeline cron).

Signature standardisée : fetch(config, session) -> list[Offre].
"""
import logging

import requests

from src.models import Offre

logger = logging.getLogger(__name__)


def fetch(config, session: requests.Session) -> list[Offre]:
    """No-op : Choose nécessite un rendu JS, aucune API JSON stable identifiée."""
    logger.info("Choose : source désactivée (SPA sans API stable), 0 offre.")
    return []
