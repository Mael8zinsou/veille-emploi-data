"""
Initialise la base SQLite (crée data/offres.sqlite et son schéma).

Le pipeline appelle déjà storage.init_db() au démarrage, donc ce script est surtout
utile pour préparer la base manuellement (debug, inspection, premier setup local).

Usage :
    python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import storage  # noqa: E402

DB_PATH = "data/offres.sqlite"


def main() -> None:
    storage.init_db(DB_PATH)
    print(f"[OK] Base initialisee : {DB_PATH}")


if __name__ == "__main__":
    main()
