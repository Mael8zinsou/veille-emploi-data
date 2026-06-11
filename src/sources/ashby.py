"""
Source Ashby (discovery par slugs).

Endpoint : https://api.ashbyhq.com/posting-api/job-board/{slug}
Endpoint public non documenté officiellement mais stable. Réponse : {"jobs": [...]}.
Localisation dans le champ `locationName`.
Résilient : un slug obsolète ou en erreur log + continue.
Pas de fallback HTML (cf. brief §4.6) : on log et on passe au slug suivant.

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
ATS = "ashby"
BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _parse_job(item: dict, slug: str) -> Offre | None:
    """
    Mappe un job Ashby vers Offre. None si localisation hors cible.

    Schéma réel observé sur l'endpoint public : champ `location` (string),
    `publishedAt`, et flag booléen `isRemote`. Un poste remote est gardé même
    si la chaîne `location` ne mentionne pas la France (souvent "Remote").
    """
    location = item.get("location", "") or item.get("locationName", "") or ""
    is_remote = bool(item.get("isRemote"))
    if not is_remote and not localisation_pertinente(location):
        return None
    return Offre(
        source="Ashby",
        titre=item.get("title", "") or "",
        entreprise=slug,
        localisation=location or ("Remote" if is_remote else "—"),
        contrat=item.get("employmentType", "") or "",
        description=(item.get("descriptionPlain", "") or "")[:500],
        url=item.get("jobUrl", "") or item.get("applyUrl", "") or "",
        date_publication=(item.get("publishedAt", "") or item.get("publishedDate", "") or "")[:10],
    )


def _fetch_un_slug(session: requests.Session, slug: str) -> list[Offre]:
    """Un slug -> liste d'Offre filtrées FR. Erreur isolée : log + []."""
    url = BOARD_URL.format(slug=slug)
    data = get_json(session, url, timeout=DEFAULT_TIMEOUT)
    if not isinstance(data, dict):
        logger.debug("Ashby '%s' : pas de réponse exploitable (slug obsolète ?)", slug)
        return []

    offres = []
    for item in data.get("jobs", []):
        try:
            offre = _parse_job(item, slug)
        except Exception as e:
            logger.debug("Ashby '%s' : job ignoré (%s)", slug, e)
            continue
        if offre is not None:
            offres.append(offre)
    if offres:
        logger.info("Ashby '%s' : %d offres FR", slug, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """Itère sur les slugs Ashby connus, agrège les offres FR/remote."""
    slugs = slugs_pour(ATS, load_slugs(SLUGS_PATH))
    if not slugs:
        logger.warning("Ashby : aucun slug dans %s, source ignorée.", SLUGS_PATH)
        return []

    offres: list[Offre] = []
    for slug in slugs:
        offres.extend(_fetch_un_slug(session, slug))
        pause_polie()
    logger.info("Ashby : %d offres FR sur %d slugs", len(offres), len(slugs))
    return offres
