"""
Source Greenhouse (discovery par slugs).

Endpoint : https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Le filtrage localisation FR se fait côté code (l'API ne filtre pas par pays).
Résilient : un slug obsolète (404) ou en erreur log + continue.

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
ATS = "greenhouse"
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def _parse_job(item: dict, slug: str) -> Offre | None:
    """Mappe un job Greenhouse vers Offre. None si la localisation n'est pas pertinente."""
    location = (item.get("location") or {}).get("name", "") or ""
    if not localisation_pertinente(location):
        return None
    return Offre(
        source="Greenhouse",
        titre=item.get("title", "") or "",
        entreprise=slug,  # Greenhouse n'expose pas le nom légal, le slug fait office
        localisation=location or "—",
        contrat="",  # non fourni par l'API jobs board
        description=(item.get("content", "") or "")[:500],
        url=item.get("absolute_url", "") or "",
        date_publication=(item.get("updated_at", "") or "")[:10],
    )


def _fetch_un_slug(session: requests.Session, slug: str) -> list[Offre]:
    """Un slug -> liste d'Offre filtrées FR. Erreur isolée : log + []."""
    url = BOARD_URL.format(slug=slug)
    data = get_json(session, url, timeout=DEFAULT_TIMEOUT)
    if not isinstance(data, dict):
        logger.debug("Greenhouse '%s' : pas de réponse exploitable (slug obsolète ?)", slug)
        return []

    offres = []
    for item in data.get("jobs", []):
        try:
            offre = _parse_job(item, slug)
        except Exception as e:  # parsing défensif, un job malformé ne casse rien
            logger.debug("Greenhouse '%s' : job ignoré (%s)", slug, e)
            continue
        if offre is not None:
            offres.append(offre)
    if offres:
        logger.info("Greenhouse '%s' : %d offres FR", slug, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """Itère sur les slugs Greenhouse connus, agrège les offres FR/remote."""
    slugs = slugs_pour(ATS, load_slugs(SLUGS_PATH))
    if not slugs:
        logger.warning("Greenhouse : aucun slug dans %s, source ignorée.", SLUGS_PATH)
        return []

    offres: list[Offre] = []
    for slug in slugs:
        offres.extend(_fetch_un_slug(session, slug))
        pause_polie()
    logger.info("Greenhouse : %d offres FR sur %d slugs", len(offres), len(slugs))
    return offres
