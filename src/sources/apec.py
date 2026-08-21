"""
Source APEC (apec.fr) — le board des cadres. Un Data Engineer junior est un cadre,
c'est donc une source à fort volume de vrais postes (≈630 résultats "data engineer").

Endpoint interne (utilisé par la SPA) : POST https://www.apec.fr/cms/webservices/rechercheOffre
Renvoie du JSON, sans authentification ni anti-bot (vérifié le 2026-08-21).

Particularités exploitées :
- Filtrage CDI/CDD côté serveur via `typesContrat` (codes APEC : CDI=101888, CDD=101887).
- `indicateurFaibleCandidature` : APEC signale les offres peu candidatées -> on porte
  ce signal dans Offre.faible_concurrence pour un bonus de scoring (anti-saturation).
- Filtrage fraîcheur ici même (datePublication), comme Adzuna/France Travail.

Signature standardisée : fetch(config, session) -> list[Offre].
"""
import logging
from datetime import datetime, timedelta

import requests

from src.models import Offre
from src.utils.http import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"
DETAIL_URL = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{num}"

# Codes contrat APEC (déterminés en live le 2026-08-21).
CODE_CDI = 101888
CODE_CDD = 101887
CONTRAT_LABEL = {CODE_CDI: "CDI", CODE_CDD: "CDD"}

REQUETES = [
    "data engineer",
    "ingénieur données",
    "analytics engineer",
    "mlops",
]
RESULTATS_PAR_PAGE = 50
MAX_PAGES = 2  # 2 pages * 50 = 100 offres max par requête, triées par date


def _parse_date(iso: str) -> datetime | None:
    """Parse une date APEC (ex. '2026-08-21T12:02:21.000+0000'). None si illisible."""
    if not iso:
        return None
    txt = iso.replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _parse_offre(item: dict) -> Offre:
    """Mappe un résultat APEC vers Offre."""
    num = item.get("numeroOffre") or item.get("id") or ""
    contrat = CONTRAT_LABEL.get(item.get("typeContrat"), "")
    return Offre(
        source="APEC",
        titre=item.get("intitule", "") or "",
        entreprise=item.get("nomCommercial", "") or "—",
        localisation=item.get("lieuTexte", "") or "—",
        contrat=contrat,
        description=(item.get("texteOffre", "") or "")[:500],
        url=DETAIL_URL.format(num=num),
        date_publication=(item.get("datePublication", "") or "")[:10],
        faible_concurrence=bool(item.get("indicateurFaibleCandidature")),
    )


def _fetch_une_requete(
    session: requests.Session, mots_cles: str, seuil_date: datetime | None
) -> list[Offre]:
    """Une requête APEC (paginée) -> liste d'Offre récentes. Erreur isolée : log + []."""
    offres: list[Offre] = []
    for page in range(MAX_PAGES):
        body = {
            "motsCles": mots_cles,
            "typesContrat": [CODE_CDI, CODE_CDD],
            "pagination": {"range": RESULTATS_PAR_PAGE, "startIndex": page * RESULTATS_PAR_PAGE},
            "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
        }
        try:
            r = session.post(SEARCH_URL, json=body, timeout=DEFAULT_TIMEOUT)
            if r.status_code >= 400:
                logger.warning("APEC '%s' p%d : HTTP %s", mots_cles, page, r.status_code)
                break
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("APEC '%s' p%d : %s", mots_cles, page, e)
            break

        resultats = data.get("resultats", [])
        if not resultats:
            break

        stop = False
        for item in resultats:
            # Filtrage fraîcheur (tri par date décroissante : dès qu'on passe le seuil,
            # les suivantes sont plus vieilles -> on arrête).
            if seuil_date is not None:
                dpub = _parse_date(item.get("datePublication", ""))
                if dpub is not None and dpub < seuil_date:
                    stop = True
                    break
            offres.append(_parse_offre(item))
        if stop or len(resultats) < RESULTATS_PAR_PAGE:
            break
    logger.info("APEC '%s' : %d offres", mots_cles, len(offres))
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """Interroge APEC sur plusieurs requêtes (CDI/CDD, récentes) et agrège."""
    max_days = int(getattr(config, "fraicheur_max_jours", 14))
    # tz-aware pour comparer aux dates APEC (qui portent un offset).
    seuil = datetime.now().astimezone() - timedelta(days=max_days)

    offres: list[Offre] = []
    for mots_cles in REQUETES:
        offres.extend(_fetch_une_requete(session, mots_cles, seuil))
    logger.info("APEC : %d offres au total", len(offres))
    return offres
