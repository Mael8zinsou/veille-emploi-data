"""
Persistance SQLite des offres déjà vues.
La base est sauvegardée entre runs GitHub Actions via actions/cache (cf. veille.yml).
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.models import Offre

SCHEMA = """
CREATE TABLE IF NOT EXISTS offres_vues (
    cle_unique TEXT PRIMARY KEY,
    titre TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    url TEXT NOT NULL,
    score INTEGER NOT NULL,
    date_premiere_vue TEXT NOT NULL,
    date_derniere_vue TEXT NOT NULL,
    sources TEXT NOT NULL,
    notifiee INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_date_premiere_vue
    ON offres_vues(date_premiere_vue);
"""

_DB_PATH: str | None = None


def init_db(path: str | Path) -> None:
    """Crée la base et le schéma si nécessaire. Mémorise le chemin pour les appels suivants."""
    global _DB_PATH
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p) as conn:
        conn.executescript(SCHEMA)
    _DB_PATH = str(p)


def _conn() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("init_db() doit être appelé avant toute autre opération.")
    return sqlite3.connect(_DB_PATH)


def is_already_seen(cle_unique: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM offres_vues WHERE cle_unique = ? LIMIT 1",
            (cle_unique,),
        ).fetchone()
    return row is not None


def mark_seen(offre: Offre) -> None:
    """
    Enregistre l'offre ou met à jour son `date_derniere_vue` et son score.
    Conserve `date_premiere_vue` et `notifiee` à leur valeur existante.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sources_csv = ",".join(offre.sources_list or [offre.source])
    with _conn() as conn:
        # UPSERT en deux passes : INSERT OR IGNORE puis UPDATE.
        # Pas d'ON CONFLICT pour rester compatible SQLite < 3.24.
        conn.execute(
            """
            INSERT OR IGNORE INTO offres_vues
                (cle_unique, titre, entreprise, url, score,
                 date_premiere_vue, date_derniere_vue, sources, notifiee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                offre.cle_unique, offre.titre, offre.entreprise, offre.url,
                offre.score, now, now, sources_csv,
            ),
        )
        conn.execute(
            """
            UPDATE offres_vues
            SET date_derniere_vue = ?, score = ?, sources = ?
            WHERE cle_unique = ?
            """,
            (now, offre.score, sources_csv, offre.cle_unique),
        )


def mark_notified(cle_unique: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE offres_vues SET notifiee = 1 WHERE cle_unique = ?",
            (cle_unique,),
        )


def get_recent_unseen(days: int) -> list[str]:
    """Pour debug : liste les `cle_unique` vus mais jamais notifiés sur la fenêtre `days`."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT cle_unique FROM offres_vues
            WHERE notifiee = 0 AND date_premiere_vue >= ?
            ORDER BY date_premiere_vue DESC
            """,
            (cutoff,),
        ).fetchall()
    return [r[0] for r in rows]


def prune_old(days: int = 90) -> int:
    """Supprime les offres jamais revues depuis plus de `days` jours. Retourne le nb supprimé."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM offres_vues WHERE date_derniere_vue < ?",
            (cutoff,),
        )
        return cur.rowcount
