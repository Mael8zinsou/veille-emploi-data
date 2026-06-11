"""
Source Adzuna (https://developer.adzuna.com/).
Free tier : 250 requêtes/mois — on reste donc économe (quelques requêtes par run).

Migré depuis veille_emploi.py V2. Signature standardisée : fetch(config, session) -> list[Offre].
Credentials lus dans l'environnement (ADZUNA_APP_ID, ADZUNA_APP_KEY).
"""
import logging
import os

import requests

from src.models import Offre
from src.utils.http import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"

# Requêtes envoyées à Adzuna. Volontairement limité pour économiser le quota mensuel.
REQUETES = [
    "data engineer",
    "ingénieur données",
    "analytics engineer",
    "mlops",
]

RESULTS_PER_PAGE = 50  # max autorisé par Adzuna sur le free tier


def _fetch_une_requete(
    session: requests.Session,
    app_id: str,
    app_key: str,
    query: str,
    max_days_old: int,
) -> list[Offre]:
    """Une requête Adzuna -> liste d'Offre. Erreur isolée : log + [] (ne casse pas la boucle)."""
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "results_per_page": RESULTS_PER_PAGE,
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    try:
        r = session.get(BASE_URL, params=params, timeout=DEFAULT_TIMEOUT)
        if r.status_code >= 400:
            logger.warning("Adzuna '%s' : HTTP %s", query, r.status_code)
            return []
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Adzuna '%s' : %s", query, e)
        return []

    offres = []
    for item in data.get("results", []):
        offres.append(
            Offre(
                source="Adzuna",
                titre=item.get("title", "") or "",
                entreprise=(item.get("company") or {}).get("display_name", "") or "—",
                localisation=(item.get("location") or {}).get("display_name", "") or "—",
                contrat=item.get("contract_type", "") or item.get("contract_time", "") or "",
                description=(item.get("description", "") or "")[:500],
                url=item.get("redirect_url", "") or "",
                date_publication=(item.get("created", "") or "")[:10],
            )
        )
    logger.info("Adzuna '%s' : %d offres", query, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """
    Interroge Adzuna sur plusieurs requêtes et agrège les offres.
    Retourne [] si les credentials manquent (la source est alors simplement ignorée).
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logger.warning("Adzuna : ADZUNA_APP_ID / ADZUNA_APP_KEY absents, source ignorée.")
        return []

    max_days_old = int(getattr(config, "fraicheur_max_jours", 14))

    offres: list[Offre] = []
    for query in REQUETES:
        offres.extend(_fetch_une_requete(session, app_id, app_key, query, max_days_old))
    return offres
