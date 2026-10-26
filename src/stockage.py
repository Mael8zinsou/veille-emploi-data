"""Base SQLite v2 (conception § 4.3).

Le chemin est passé explicitement (plus de singleton de module comme en v1) : chaque test
travaille sur sa propre base. Le schéma est versionné ; `ouvrir` crée ou migre la base, y
compris depuis la base v1 (`offres_vues`), dont les clés sont importées comme déjà vues
pour que le premier passage v2 ne renvoie pas tout l'historique.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.models import Offre, Rejet

VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS version_schema (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS offres (
    cle TEXT PRIMARY KEY,
    fil TEXT,
    famille TEXT,
    priorite INTEGER,
    titre TEXT NOT NULL,
    entreprise TEXT,
    type_employeur TEXT,
    lieu TEXT,
    contrat TEXT,
    duree_mois INTEGER,
    url TEXT,
    sources TEXT,
    date_publication TEXT,
    premiere_vue TEXT NOT NULL,
    derniere_vue TEXT NOT NULL,
    note INTEGER,
    raisons TEXT,
    niveau TEXT,
    etat_envoi TEXT NOT NULL DEFAULT 'aucun',
    envoyee_le TEXT,
    ajoutee_veille_le TEXT,
    importee_v1 INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_offres_premiere_vue ON offres(premiere_vue);
CREATE INDEX IF NOT EXISTS idx_offres_etat ON offres(etat_envoi);

CREATE TABLE IF NOT EXISTS rejets (
    cle TEXT NOT NULL,
    source TEXT,
    titre TEXT,
    entreprise TEXT,
    type_employeur TEXT,
    lieu TEXT,
    motif TEXT NOT NULL,
    detail TEXT,
    url TEXT,
    vu_le TEXT NOT NULL,
    PRIMARY KEY (cle, motif)
);
CREATE INDEX IF NOT EXISTS idx_rejets_vu_le ON rejets(vu_le);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tache TEXT NOT NULL,
    debut TEXT NOT NULL,
    fin TEXT,
    succes INTEGER NOT NULL DEFAULT 0,
    nb_offres INTEGER,
    requetes INTEGER NOT NULL DEFAULT 0,
    erreur TEXT
);
CREATE INDEX IF NOT EXISTS idx_executions_tache ON executions(tache, debut);

CREATE TABLE IF NOT EXISTS envois (
    type TEXT NOT NULL,
    fil TEXT,
    le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_b (
    entreprise_normalisee TEXT PRIMARY KEY,
    ajoutee_le TEXT NOT NULL
);
"""


FORMAT = "%Y-%m-%d %H:%M:%S"


def maintenant_utc() -> datetime:
    """Heure UTC sans fuseau : toutes les dates de la base sont en UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def _maintenant(le: datetime | None = None) -> str:
    return (le or maintenant_utc()).strftime(FORMAT)


@dataclass
class Base:
    chemin: Path

    def connexion(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.chemin)
        c.row_factory = sqlite3.Row
        return c


def ouvrir(chemin: str | Path) -> Base:
    """Crée la base si besoin, applique le schéma, importe la v1 si elle est présente."""
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    base = Base(p)
    with closing(base.connexion()) as c, c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM version_schema").fetchone()[0] == 0:
            c.execute("INSERT INTO version_schema(version) VALUES (?)", (VERSION,))
            _importer_v1(c)
    return base


def _importer_v1(c: sqlite3.Connection) -> int:
    existe = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='offres_vues'").fetchone()
    if not existe:
        return 0
    cur = c.execute(
        """INSERT OR IGNORE INTO offres (cle, titre, entreprise, url, sources, premiere_vue, derniere_vue,
                                         note, etat_envoi, importee_v1)
           SELECT cle_unique, titre, entreprise, url, sources, date_premiere_vue, date_derniere_vue, score,
                  CASE WHEN notifiee = 1 THEN 'envoyee' ELSE 'aucun' END, 1
           FROM offres_vues""")
    return cur.rowcount


# --------------------------------------------------------------------------- offres

def cles_connues(base: Base, cles: list[str]) -> set[str]:
    if not cles:
        return set()
    with closing(base.connexion()) as c:
        connues: set[str] = set()
        for i in range(0, len(cles), 500):
            lot = cles[i:i + 500]
            rows = c.execute(f"SELECT cle FROM offres WHERE cle IN ({','.join('?' * len(lot))})", lot)
            connues.update(r[0] for r in rows)
    return connues


def enregistrer_offres(base: Base, offres: list[Offre], le: datetime | None = None) -> None:
    """Ajoute les nouvelles offres, rafraîchit la dernière détection des offres connues."""
    maintenant = _maintenant(le)
    with closing(base.connexion()) as c, c:
        for o in offres:
            c.execute(
                """INSERT OR IGNORE INTO offres (cle, fil, famille, priorite, titre, entreprise, type_employeur,
                       lieu, contrat, duree_mois, url, sources, date_publication, premiere_vue, derniere_vue)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (o.cle, o.fil, o.famille, o.priorite, o.titre, o.entreprise, o.type_employeur, o.lieu,
                 o.contrat, o.duree_mois, o.url, ",".join(o.sources or [o.source]), o.date_publication,
                 maintenant, maintenant))
            c.execute("UPDATE offres SET derniere_vue = ? WHERE cle = ?", (maintenant, o.cle))


def dernieres_vues(base: Base, cles: list[str]) -> dict[str, datetime]:
    """Dernière détection (UTC) des offres déjà connues parmi `cles`."""
    sortie: dict[str, datetime] = {}
    with closing(base.connexion()) as c:
        for i in range(0, len(cles), 500):
            lot = cles[i:i + 500]
            for cle, d in c.execute(f"SELECT cle, derniere_vue FROM offres WHERE cle IN ({','.join('?' * len(lot))})", lot):
                sortie[cle] = datetime.strptime(d, FORMAT)
    return sortie


def noter(base: Base, cle: str, note: int, raisons: list[tuple[str, int]], niveau: str) -> None:
    with closing(base.connexion()) as c, c:
        c.execute("UPDATE offres SET note = ?, raisons = ?, niveau = ? WHERE cle = ?",
                  (note, json.dumps(raisons, ensure_ascii=False), niveau, cle))


# --------------------------------------------------------------------------- rejets

def enregistrer_rejets(base: Base, rejets: list[Rejet], le: datetime | None = None) -> None:
    maintenant = _maintenant(le)
    with closing(base.connexion()) as c, c:
        for r in rejets:
            o = r.offre
            c.execute(
                """INSERT INTO rejets (cle, source, titre, entreprise, type_employeur, lieu, motif, detail, url, vu_le)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(cle, motif) DO UPDATE SET vu_le = excluded.vu_le""",
                (o.cle, o.source, o.titre, o.entreprise, o.type_employeur, o.lieu, r.motif, r.detail, o.url,
                 maintenant))


# --------------------------------------------------------------------------- exécutions

def debut_execution(base: Base, tache: str, le: datetime | None = None) -> int:
    with closing(base.connexion()) as c, c:
        return c.execute("INSERT INTO executions (tache, debut) VALUES (?, ?)", (tache, _maintenant(le))).lastrowid


def fin_execution(base: Base, ident: int, succes: bool, nb_offres: int | None = None,
                  requetes: int = 0, erreur: str | None = None) -> None:
    """La fin est datée de l'horloge réelle : elle sert au diagnostic, pas au planning."""
    with closing(base.connexion()) as c, c:
        c.execute("UPDATE executions SET fin = ?, succes = ?, nb_offres = ?, requetes = ?, erreur = ? WHERE id = ?",
                  (_maintenant(), int(succes), nb_offres, requetes, (erreur or "")[:500] or None, ident))


def dernier_succes(base: Base) -> dict[str, datetime]:
    """Date (UTC) du dernier succès de chaque tâche."""
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT tache, MAX(debut) FROM executions WHERE succes = 1 GROUP BY tache").fetchall()
    return {t: datetime.strptime(d, FORMAT) for t, d in rows if d}


def echecs_consecutifs(base: Base, tache: str) -> int:
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT succes FROM executions WHERE tache = ? AND fin IS NOT NULL ORDER BY id DESC LIMIT 10",
                         (tache,)).fetchall()
    n = 0
    for (succes,) in rows:
        if succes:
            break
        n += 1
    return n


def requetes_du_mois(base: Base, tache: str, maintenant: datetime) -> int:
    debut_mois = maintenant.strftime("%Y-%m-01 00:00:00")
    with closing(base.connexion()) as c:
        r = c.execute("SELECT COALESCE(SUM(requetes), 0) FROM executions WHERE tache = ? AND debut >= ?",
                      (tache, debut_mois)).fetchone()
    return int(r[0])


# --------------------------------------------------------------------------- envois et entretien

def enregistrer_envoi(base: Base, type_envoi: str, fil: str | None, le: datetime) -> None:
    with closing(base.connexion()) as c, c:
        c.execute("INSERT INTO envois (type, fil, le) VALUES (?, ?, ?)", (type_envoi, fil, le.strftime(FORMAT)))


def derniers_envois(base: Base) -> dict[tuple[str, str | None], datetime]:
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT type, fil, MAX(le) FROM envois GROUP BY type, fil").fetchall()
    return {(t, f): datetime.strptime(d, FORMAT) for t, f, d in rows}


def purger(base: Base, jours_offres: int = 180, jours_rejets: int = 90) -> tuple[int, int]:
    limite_o = (maintenant_utc() - timedelta(days=jours_offres)).strftime(FORMAT)
    limite_r = (maintenant_utc() - timedelta(days=jours_rejets)).strftime(FORMAT)
    with closing(base.connexion()) as c, c:
        n_o = c.execute("DELETE FROM offres WHERE derniere_vue < ?", (limite_o,)).rowcount
        n_r = c.execute("DELETE FROM rejets WHERE vu_le < ?", (limite_r,)).rowcount
    return n_o, n_r
