"""
Helpers partagés par les sources ATS (Greenhouse, Lever, Ashby).

Les trois suivent le même schéma :
- liste de slugs (config/slugs_ats.txt) filtrée par préfixe ATS
- une requête JSON par slug, avec délai poli entre slugs
- filtrage localisation côté code (les ATS ne filtrent pas par pays)
- résilience : un slug en erreur log + continue, ne casse jamais la boucle
"""
import logging
import time

from src.models import _normalize

logger = logging.getLogger(__name__)

DELAI_ENTRE_SLUGS = 0.2  # 200ms, pour rester poli (cf. brief §7)

# Mots indiquant un poste accessible depuis la France / en remote.
# Comparés sur une chaîne localisation déjà normalisée (sans accents, minuscule).
LOC_FR_HINTS = (
    "paris", "france", "ile-de-france", "idf", "nanterre", "defense",
    "boulogne", "issy", "saint-denis", "nantes", "rennes", "bordeaux",
    "lille", "lyon", "toulouse", "marseille", "strasbourg", "grenoble",
    "montpellier", "nice", "bruxelles", "brussels", "belgi",
    "remote", "teletravail", "anywhere",
)


def localisation_pertinente(localisation: str) -> bool:
    """
    True si la localisation évoque la France, la Belgique ou un poste remote.
    Tolérant : une localisation vide est rejetée (les ATS donnent toujours un lieu).
    """
    loc = _normalize(localisation)
    if not loc:
        return False
    return any(hint in loc for hint in LOC_FR_HINTS)


def slugs_pour(ats: str, slugs: list[tuple[str, str]]) -> list[str]:
    """Extrait les slugs d'un ATS donné depuis la liste (ats, slug) chargée du fichier."""
    return [slug for a, slug in slugs if a == ats]


def pause_polie() -> None:
    time.sleep(DELAI_ENTRE_SLUGS)
