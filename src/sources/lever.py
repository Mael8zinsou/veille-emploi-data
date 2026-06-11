"""
Source Lever (discovery par slugs).

Endpoint : https://api.lever.co/v0/postings/{slug}?mode=json
Réponse : liste de postings. Localisation dans categories.location.
Résilient : un slug obsolète ou en erreur log + continue.

Signature standardisée : fetch(config, session) -> list[Offre].
"""
import logging

import requests

from src.config import load_slugs
from src.models import Offre
from src.sources._ats_common import (
    localisation_pertinente,
    pause_polie,
    slugs_pour,
)
from src.utils.http import DEFAULT_TIMEOUT, get_json

logger = logging.getLogger(__name__)

SLUGS_PATH = "config/slugs_ats.txt"
ATS = "lever"
POSTINGS_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def _parse_posting(item: dict, slug: str) -> Offre | None:
    """Mappe un posting Lever vers Offre. None si localisation hors cible."""
    categories = item.get("categories") or {}
    location = categories.get("location", "") or ""
    if not localisation_pertinente(location):
        return None
    description = item.get("descriptionPlain", "") or item.get("description", "") or ""
    return Offre(
        source="Lever",
        titre=item.get("text", "") or "",
        entreprise=slug,
        localisation=location or "—",
        contrat=categories.get("commitment", "") or "",
        description=description[:500],
        url=item.get("hostedUrl", "") or item.get("applyUrl", "") or "",
        date_publication="",  # Lever renvoie createdAt en ms epoch, peu fiable pour l'affichage
    )


def _fetch_un_slug(session: requests.Session, slug: str) -> list[Offre]:
    """Un slug -> liste d'Offre filtrées FR. Erreur isolée : log + []."""
    url = POSTINGS_URL.format(slug=slug)
    data = get_json(session, url, timeout=DEFAULT_TIMEOUT)
    if not isinstance(data, list):
        logger.debug("Lever '%s' : pas de réponse exploitable (slug obsolète ?)", slug)
        return []

    offres = []
    for item in data:
        try:
            offre = _parse_posting(item, slug)
        except Exception as e:
            logger.debug("Lever '%s' : posting ignoré (%s)", slug, e)
            continue
        if offre is not None:
            offres.append(offre)
    if offres:
        logger.info("Lever '%s' : %d offres FR", slug, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """Itère sur les slugs Lever connus, agrège les offres FR/remote."""
    slugs = slugs_pour(ATS, load_slugs(SLUGS_PATH))
    if not slugs:
        logger.warning("Lever : aucun slug dans %s, source ignorée.", SLUGS_PATH)
        return []

    offres: list[Offre] = []
    for slug in slugs:
        offres.extend(_fetch_un_slug(session, slug))
        pause_polie()
    logger.info("Lever : %d offres FR sur %d slugs", len(offres), len(slugs))
    return offres
