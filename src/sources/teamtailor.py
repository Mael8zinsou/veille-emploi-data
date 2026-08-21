"""
Source Teamtailor (discovery par slugs).

Endpoint : https://{slug}.teamtailor.com/jobs.json — flux public JSON Feed 1.1,
sans authentification (l'API officielle api.teamtailor.com, elle, exige une clé).
Chaque item porte un objet `_jobposting` (schema.org JobPosting) avec le VRAI nom
d'entreprise (hiringOrganization.name) et une localisation structurée (ville + pays).

Beaucoup de scale-ups FR ayant quitté Greenhouse/Lever/Ashby ont migré ici
(PayFit, Akeneo, Deezer, Skello, Ornikar, Yousign…). C'est un gisement d'employeurs
finaux FR que les autres ATS ne captaient plus.

Résilient : un slug obsolète ou en erreur log + continue.
Signature standardisée : fetch(config, session) -> list[Offre].
"""
import logging
import re

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
ATS = "teamtailor"
FEED_URL = "https://{slug}.teamtailor.com/jobs.json"

# Codes pays -> libellé, injecté dans la localisation pour que le filtre FR
# (localisation_pertinente, basé sur des mots comme "france"/"belgi") matche même
# une petite commune non listée.
COUNTRY_NAMES = {"FR": "France", "BE": "Belgique"}

_HTML_TAG = re.compile(r"<[^>]+>")


def _localisation(jobposting: dict) -> str:
    """Construit une chaîne de localisation lisible depuis _jobposting.jobLocation."""
    locs = jobposting.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for lieu in locs:
        addr = (lieu or {}).get("address") or {}
        ville = addr.get("addressLocality") or ""
        pays = addr.get("addressCountry") or ""
        pays = COUNTRY_NAMES.get(pays, pays)
        seg = ", ".join(x for x in (ville, pays) if x)
        if seg:
            parts.append(seg)
    if not parts:
        # Pas de lieu structuré : souvent un poste remote.
        if jobposting.get("jobLocationType") == "TELECOMMUTE":
            return "Remote"
        return ""
    return " / ".join(dict.fromkeys(parts))  # dédoublonne en gardant l'ordre


def _parse_item(item: dict, slug: str) -> Offre | None:
    """Mappe un item du flux vers Offre. None si localisation hors cible."""
    jp = item.get("_jobposting") or {}
    localisation = _localisation(jp)
    if not localisation_pertinente(localisation):
        return None

    org = (jp.get("hiringOrganization") or {}).get("name") or slug
    description = jp.get("description") or item.get("content_html") or ""
    description = _HTML_TAG.sub(" ", description)  # retire les balises HTML
    return Offre(
        source="Teamtailor",
        titre=item.get("title", "") or jp.get("title", "") or "",
        entreprise=org,
        localisation=localisation or "—",
        contrat=jp.get("employmentType", "") or "",
        description=description[:500],
        url=item.get("url", "") or "",
        date_publication=(item.get("date_published", "") or jp.get("datePosted", "") or "")[:10],
    )


def _fetch_un_slug(session: requests.Session, slug: str) -> list[Offre]:
    """Un slug -> liste d'Offre filtrées FR. Erreur isolée : log + []."""
    url = FEED_URL.format(slug=slug)
    data = get_json(session, url, timeout=DEFAULT_TIMEOUT)
    if not isinstance(data, dict):
        logger.debug("Teamtailor '%s' : pas de réponse exploitable (slug obsolète ?)", slug)
        return []

    offres = []
    for item in data.get("items", []):
        try:
            offre = _parse_item(item, slug)
        except Exception as e:  # parsing défensif
            logger.debug("Teamtailor '%s' : item ignoré (%s)", slug, e)
            continue
        if offre is not None:
            offres.append(offre)
    if offres:
        logger.info("Teamtailor '%s' : %d offres FR", slug, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """Itère sur les slugs Teamtailor connus, agrège les offres FR/remote."""
    slugs = slugs_pour(ATS, load_slugs(SLUGS_PATH))
    if not slugs:
        logger.warning("Teamtailor : aucun slug dans %s, source ignorée.", SLUGS_PATH)
        return []

    offres: list[Offre] = []
    for slug in slugs:
        offres.extend(_fetch_un_slug(session, slug))
        pause_polie()
    logger.info("Teamtailor : %d offres FR sur %d slugs", len(offres), len(slugs))
    return offres
