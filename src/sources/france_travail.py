"""
Source France Travail (API officielle, https://francetravail.io/).
OAuth2 client_credentials -> token 24h, puis recherche d'offres.

Migré depuis veille_emploi.py V2. Correctif V2 conservé : l'API exige
minCreationDate ET maxCreationDate ensemble (ISO 8601), sinon 400.

Signature standardisée : fetch(config, session) -> list[Offre].
Credentials lus dans l'environnement (FT_CLIENT_ID, FT_CLIENT_SECRET).
"""
import logging
import os
from datetime import datetime, timedelta

import requests

from src.models import Offre
from src.utils.http import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# Requêtes envoyées (motsCles). FT plafonne à 150 résultats par requête.
REQUETES = [
    "data engineer",
    "ingénieur données",
    "data",
]
MAX_RESULTATS = 150
TYPE_CONTRAT = "CDI,CDD,MIS,LIB"  # tous types pertinents, intérim seul exclu


def _get_token(session: requests.Session, client_id: str, client_secret: str) -> str | None:
    """Récupère un token OAuth2 (valable 24h). None en cas d'échec."""
    params = {"realm": "/partenaire"}
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "api_offresdemploiv2 o2dsoffre",
    }
    try:
        r = session.post(TOKEN_URL, params=params, data=data, timeout=DEFAULT_TIMEOUT)
        if r.status_code >= 400:
            logger.warning("France Travail token : HTTP %s", r.status_code)
            return None
        return r.json().get("access_token")
    except (requests.RequestException, ValueError) as e:
        logger.warning("France Travail token : %s", e)
        return None


def _fetch_une_requete(
    session: requests.Session,
    token: str,
    mots_cles: str,
    max_days_old: int,
) -> list[Offre]:
    """Une requête FT -> liste d'Offre. Erreur isolée : log + []."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    # Correctif V2 : minCreationDate ET maxCreationDate obligatoires ensemble.
    now = datetime.now()
    min_date = (now - timedelta(days=max_days_old)).strftime("%Y-%m-%dT00:00:00Z")
    max_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "motsCles": mots_cles,
        "range": f"0-{MAX_RESULTATS - 1}",
        "minCreationDate": min_date,
        "maxCreationDate": max_date,
        "typeContrat": TYPE_CONTRAT,
    }
    try:
        r = session.get(SEARCH_URL, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 204:
            logger.info("France Travail '%s' : aucun résultat", mots_cles)
            return []
        if r.status_code not in (200, 206):
            logger.warning("France Travail '%s' : HTTP %s", mots_cles, r.status_code)
            return []
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("France Travail '%s' : %s", mots_cles, e)
        return []

    offres = []
    for item in data.get("resultats", []):
        lieu = item.get("lieuTravail") or {}
        entreprise = item.get("entreprise") or {}
        origine = item.get("origineOffre") or {}
        url = origine.get("urlOrigine") or (
            f"https://candidat.francetravail.fr/offres/recherche/detail/{item.get('id', '')}"
        )
        offres.append(
            Offre(
                source="France Travail",
                titre=item.get("intitule", "") or "",
                entreprise=entreprise.get("nom", "") or "—",
                localisation=lieu.get("libelle", "") or "—",
                contrat=item.get("typeContratLibelle", "") or "",
                description=(item.get("description", "") or "")[:500],
                url=url,
                date_publication=(item.get("dateCreation", "") or "")[:10],
            )
        )
    logger.info("France Travail '%s' : %d offres", mots_cles, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """
    Interroge France Travail sur plusieurs requêtes et agrège les offres.
    Retourne [] si les credentials manquent ou si le token échoue.
    """
    client_id = os.getenv("FT_CLIENT_ID")
    client_secret = os.getenv("FT_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.warning("France Travail : FT_CLIENT_ID / FT_CLIENT_SECRET absents, source ignorée.")
        return []

    token = _get_token(session, client_id, client_secret)
    if not token:
        return []

    max_days_old = int(getattr(config, "fraicheur_max_jours", 14))

    offres: list[Offre] = []
    for query in REQUETES:
        offres.extend(_fetch_une_requete(session, token, query, max_days_old))
    return offres
