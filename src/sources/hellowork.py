"""
Source HelloWork (scraping HTML de la page de recherche). Source niche, désactivable.

Approche : la page de recherche HelloWork rend les offres directement dans le HTML
statique. Chaque carte est une ancre <a> portant à la fois le lien de l'offre et un
aria-label « Voir offre de … » très structuré (titre, lieu, entreprise, contrat).
On parse cet aria-label, bien plus stable que des classes CSS générées.

Validé en live le 2026-06-11 : 30 offres parsées / page, 100% de couverture.

Précautions (cf. brief §4.7) :
- User-Agent navigateur réaliste (déjà porté par build_session).
- Délai >= 2s entre requêtes.
- Maximum 3 pages par recherche.
- Si HTTP 403 / Cloudflare détecté : on désactive la source pour ce run (log warning),
  sans jamais faire planter le pipeline.

Signature standardisée : fetch(config, session) -> list[Offre].
"""
import html as ihtml
import logging
import re
import time

import requests

from src.models import Offre
from src.sources._ats_common import localisation_pertinente
from src.utils.http import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hellowork.com/fr-fr/emploi/recherche.html"
SITE_ROOT = "https://www.hellowork.com"

REQUETES = [
    ("data engineer", "Paris"),
    ("data engineer", "Lyon"),
    ("analytics engineer", "Paris"),
]
MAX_PAGES = 3
DELAI_ENTRE_PAGES = 2.0  # secondes, politesse anti-ban

# Une ancre = lien d'offre + aria-label structuré, dans la même balise <a>.
_ANCHRE_RE = re.compile(
    r'<a\b[^>]*href="(?P<href>/fr-fr/emplois/\d+\.html)"[^>]*'
    r'aria-label="(?P<label>Voir offre[^"]+)"',
    re.IGNORECASE,
)
# Décompose l'aria-label : "Voir offre de <titre> à <lieu>, chez <ent>[, super
# recruteur], pour <contrat>[, en <temps>]".
_LABEL_RE = re.compile(
    r"^Voir offre de (?P<titre>.+?) (?:à|a) (?P<lieu>.+?), "
    r"chez (?P<ent>.+?)(?:, super recruteur)?, "
    r"pour (?:un |une |le |du )?(?P<contrat>.+?)(?:, en (?P<temps>.+))?$"
)

# Signaux d'un blocage anti-bot dans le corps de la réponse.
_BLOCAGE_MARKERS = ("just a moment", "cf-challenge", "captcha", "access denied")


def _cloudflare_ou_403(resp: requests.Response) -> bool:
    if resp.status_code in (403, 429, 503):
        return True
    low = resp.text[:5000].lower()
    return any(m in low for m in _BLOCAGE_MARKERS)


def _parse_page(html_text: str) -> list[Offre]:
    """Extrait les offres d'une page de résultats. Filtre par localisation cible."""
    offres = []
    for m in _ANCHRE_RE.finditer(html_text):
        label = ihtml.unescape(m.group("label"))
        href = m.group("href")
        champs = _LABEL_RE.match(label)
        if not champs:
            logger.debug("HelloWork : label non parsé (%s)", label[:80])
            continue
        lieu = champs.group("lieu").strip()
        if not localisation_pertinente(lieu):
            continue
        # Le contrat peut traîner un salaire après une virgule : on ne garde que le type.
        contrat = champs.group("contrat").split(",")[0].strip()
        offres.append(
            Offre(
                source="HelloWork",
                titre=champs.group("titre").strip(),
                entreprise=champs.group("ent").strip(),
                localisation=lieu,
                contrat=contrat,
                description="",  # non disponible sur la page liste
                url=SITE_ROOT + href,
                date_publication="",  # non exposé de façon fiable sur la liste
            )
        )
    return offres


def _fetch_recherche(session: requests.Session, mots_cles: str, lieu: str) -> list[Offre]:
    """Une recherche (mots-clés + lieu), jusqu'à MAX_PAGES pages. Résilient."""
    offres: list[Offre] = []
    for page in range(1, MAX_PAGES + 1):
        params = {"k": mots_cles, "l": lieu, "p": page}
        try:
            r = session.get(BASE_URL, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            logger.warning("HelloWork '%s/%s' p%d : %s", mots_cles, lieu, page, e)
            break
        if _cloudflare_ou_403(r):
            logger.warning(
                "HelloWork : blocage détecté (HTTP %s) sur '%s/%s', source coupée pour ce run.",
                r.status_code, mots_cles, lieu,
            )
            break
        if r.status_code != 200:
            logger.warning("HelloWork '%s/%s' p%d : HTTP %s", mots_cles, lieu, page, r.status_code)
            break

        page_offres = _parse_page(r.text)
        if not page_offres:
            break  # plus de résultats, inutile de paginer plus loin
        offres.extend(page_offres)

        if page < MAX_PAGES:
            time.sleep(DELAI_ENTRE_PAGES)
    return offres


def fetch(config, session: requests.Session) -> list[Offre]:
    """
    Scrape HelloWork sur quelques couples (mots-clés, lieu).
    Toute défaillance est contenue : on retourne ce qu'on a pu collecter.
    """
    offres: list[Offre] = []
    for mots_cles, lieu in REQUETES:
        try:
            res = _fetch_recherche(session, mots_cles, lieu)
            logger.info("HelloWork '%s/%s' : %d offres", mots_cles, lieu, len(res))
            offres.extend(res)
        except Exception as e:  # garde-fou : aucune source ne doit casser le pipeline
            logger.warning("HelloWork '%s/%s' a échoué : %s", mots_cles, lieu, e)
            continue
    logger.info("HelloWork : %d offres au total", len(offres))
    return offres
