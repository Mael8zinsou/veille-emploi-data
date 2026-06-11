"""
Découverte de nouveaux slugs ATS (bonus, lancé manuellement — PAS dans le cron).

Idée : interroger un moteur de recherche avec des requêtes ciblant les boards ATS
(ex. `site:boards.greenhouse.io "France" "data"`), extraire les slugs des URLs
trouvées, et les ajouter à config/slugs_ats.txt en dédoublonnant.

⚠️ Le scraping Google direct est fragile et facilement bloqué (captcha). Ce script
utilise donc DuckDuckGo HTML (https://html.duckduckgo.com/html/), plus tolérant, mais
reste best-effort : il peut ne rien remonter selon les protections du moment. C'est
pour ça qu'il est manuel et hors pipeline (cf. brief §4.12).

Usage :
    python scripts/decouvrir_slugs.py            # affiche les nouveaux slugs trouvés
    python scripts/decouvrir_slugs.py --write     # les ajoute à config/slugs_ats.txt
"""
import argparse
import re
import sys
import time
from pathlib import Path

# Permet `python scripts/decouvrir_slugs.py` depuis la racine.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_slugs  # noqa: E402
from src.utils.http import build_session  # noqa: E402

SLUGS_PATH = "config/slugs_ats.txt"
SEARCH_URL = "https://html.duckduckgo.com/html/"

# Patterns d'extraction de slug par ATS, sur les URLs de boards publics.
PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/([a-z0-9][a-z0-9-]+)", re.I),
    "lever": re.compile(r"jobs\.lever\.co/([a-z0-9][a-z0-9-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9-]+)", re.I),
}

# Requêtes envoyées au moteur. Ciblent les boards FR orientés data.
REQUETES = [
    'site:boards.greenhouse.io "France" data engineer',
    'site:boards.greenhouse.io "Paris" data',
    'site:jobs.lever.co "France" data',
    'site:jobs.lever.co "Paris" data engineer',
    'site:jobs.ashbyhq.com "France" data',
    'site:jobs.ashbyhq.com "Paris" data',
]

DELAI = 2.0  # politesse entre requêtes


def _chercher(session, query: str) -> str:
    """Une recherche -> HTML brut (ou '' en cas d'échec)."""
    try:
        r = session.post(SEARCH_URL, data={"q": query}, timeout=20)
        if r.status_code != 200:
            print(f"  [warn] '{query}' : HTTP {r.status_code}")
            return ""
        return r.text
    except Exception as e:
        print(f"  [warn] '{query}' : {e}")
        return ""


def _extraire_slugs(html: str) -> set[tuple[str, str]]:
    """Extrait les couples (ats, slug) trouvés dans une page de résultats."""
    trouves = set()
    for ats, pattern in PATTERNS.items():
        for slug in pattern.findall(html):
            slug = slug.lower().strip("-")
            # Filtre les faux positifs courants (segments d'URL non-slug).
            if slug and slug not in ("embed", "api", "v1", "jobs", "boards"):
                trouves.add((ats, slug))
    return trouves


def decouvrir() -> set[tuple[str, str]]:
    """Lance toutes les requêtes et agrège les slugs découverts."""
    session = build_session()
    tous = set()
    for query in REQUETES:
        print(f"> {query}")
        html = _chercher(session, query)
        nouveaux = _extraire_slugs(html)
        print(f"  {len(nouveaux)} slugs dans cette page")
        tous |= nouveaux
        time.sleep(DELAI)
    return tous


def _ajouter_au_fichier(nouveaux: list[tuple[str, str]]) -> None:
    """Ajoute les nouveaux slugs à la fin du fichier, sous une section datée."""
    from datetime import date

    lignes = [f"\n# --- découverts automatiquement le {date.today().isoformat()} ---\n"]
    lignes += [f"{ats}:{slug}\n" for ats, slug in sorted(nouveaux)]
    with open(SLUGS_PATH, "a", encoding="utf-8") as f:
        f.writelines(lignes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Découvre de nouveaux slugs ATS.")
    parser.add_argument("--write", action="store_true",
                        help="ajoute les slugs trouvés à config/slugs_ats.txt")
    args = parser.parse_args()

    connus = set(load_slugs(SLUGS_PATH))
    trouves = decouvrir()
    nouveaux = sorted(trouves - connus)

    print(f"\n{len(trouves)} slugs trouvés, dont {len(nouveaux)} nouveaux :")
    for ats, slug in nouveaux:
        print(f"  {ats}:{slug}")

    if not nouveaux:
        print("Rien de nouveau.")
        return

    if args.write:
        _ajouter_au_fichier(nouveaux)
        print(f"\n[OK] {len(nouveaux)} slugs ajoutes a {SLUGS_PATH}")
    else:
        print("\n(relance avec --write pour les ajouter au fichier)")


if __name__ == "__main__":
    main()
