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

from src.models import Offre, Rejet, TypeEmployeur, calculer_cle, titre_souple

VERSION = 3

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
    ajoutee_essai_le TEXT,
    importee_v1 INTEGER NOT NULL DEFAULT 0,
    cle_souple TEXT,
    empreinte TEXT,
    signaux TEXT
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

-- Ce qu'une source garde d'un passage à l'autre (Choisir le service public : la page de
-- chaque offre n'est lue qu'une fois).
CREATE TABLE IF NOT EXISTS memoire_sources (
    source TEXT NOT NULL,
    cle TEXT NOT NULL,
    valeur TEXT NOT NULL,
    maj_le TEXT NOT NULL,
    PRIMARY KEY (source, cle)
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
        _migrer(c)
    return base


def _migrer(c: sqlite3.Connection) -> None:
    """Version 1 -> 2 : l'onglet d'essai a sa propre date d'ajout (le vrai onglet Veille doit
    recevoir, à la mise en service, les offres déjà vues pendant la période de test).
    Version 2 -> 3 : clé souple, empreinte de description et signaux, pour reconnaître une même
    offre republiée sous un titre à peine différent. La clé souple des offres déjà en base est
    recalculée ; leur empreinte reste vide (la description n'est pas conservée)."""
    colonnes = {r[1] for r in c.execute("PRAGMA table_info(offres)")}
    for nouvelle in ("cle_souple", "empreinte", "signaux"):
        if nouvelle not in colonnes:
            c.execute(f"ALTER TABLE offres ADD COLUMN {nouvelle} TEXT")
    a_calculer = c.execute("SELECT cle, titre, entreprise, lieu, type_employeur FROM offres "
                           "WHERE cle_souple IS NULL").fetchall()
    if a_calculer:
        c.executemany("UPDATE offres SET cle_souple = ? WHERE cle = ?",
                      [(calculer_cle(e or "", titre_souple(t or ""), li or "", _type(ty)), cle)
                       for cle, t, e, li, ty in a_calculer])
    c.execute("CREATE INDEX IF NOT EXISTS idx_offres_cle_souple ON offres(cle_souple)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_offres_empreinte ON offres(empreinte)")
    if "ajoutee_essai_le" not in colonnes:
        c.execute("ALTER TABLE offres ADD COLUMN ajoutee_essai_le TEXT")
        # En version 1, seul le mode essai a existé : ses ajouts deviennent des ajouts d'essai.
        c.execute("UPDATE offres SET ajoutee_essai_le = ajoutee_veille_le, ajoutee_veille_le = NULL "
                  "WHERE ajoutee_veille_le IS NOT NULL")
    c.execute("UPDATE version_schema SET version = ?", (VERSION,))


def _type(valeur: str | None) -> TypeEmployeur:
    try:
        return TypeEmployeur(valeur)
    except ValueError:
        return TypeEmployeur.INCONNU


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


# --------------------------------------------------------------------------- mémoire des sources

MEMOIRE_JOURS = 60


def lire_memoire(base: Base, source: str) -> dict[str, dict]:
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT cle, valeur FROM memoire_sources WHERE source = ?", (source,)).fetchall()
    return {r["cle"]: json.loads(r["valeur"]) for r in rows}


def ecrire_memoire(base: Base, source: str, memoire: dict[str, dict], le: datetime | None = None) -> None:
    """Ajoute les entrées nouvelles (les connues gardent leur date) et oublie celles de plus de
    MEMOIRE_JOURS jours."""
    maintenant = le or maintenant_utc()
    with closing(base.connexion()) as c, c:
        c.executemany("INSERT OR IGNORE INTO memoire_sources (source, cle, valeur, maj_le) VALUES (?,?,?,?)",
                      [(source, cle, json.dumps(v, ensure_ascii=False), _maintenant(maintenant))
                       for cle, v in memoire.items()])
        c.execute("DELETE FROM memoire_sources WHERE source = ? AND maj_le < ?",
                  (source, _maintenant(maintenant - timedelta(days=MEMOIRE_JOURS))))


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
                       lieu, contrat, duree_mois, url, sources, date_publication, premiere_vue, derniere_vue,
                       cle_souple, empreinte, signaux)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (o.cle, o.fil, o.famille, o.priorite, o.titre, o.entreprise, o.type_employeur, o.lieu,
                 o.contrat, o.duree_mois, o.url, ",".join(o.sources or [o.source]), o.date_publication,
                 maintenant, maintenant, o.cle_souple, o.empreinte,
                 json.dumps(signaux_offre(o), ensure_ascii=False)))
            c.execute("UPDATE offres SET derniere_vue = ? WHERE cle = ?", (maintenant, o.cle))


def signaux_offre(o: Offre) -> list[str]:
    """Signaux sans effet sur la note, affichés avec l'offre (Telegram, onglet Veille)."""
    signaux = []
    if o.permis_exige:
        signaux.append("permis B exigé")
    if o.via_cabinet:
        signaux.append("via cabinet")
    if o.description_partielle:
        signaux.append("description partielle (Adzuna) : expérience à vérifier")
    return signaux


def doublons(base: Base, offres: list[Offre], depuis: datetime) -> dict[str, str]:
    """Offres nouvelles par leur clé mais déjà connues sous une autre : même clé souple ou même
    empreinte de description, vues depuis `depuis`. Rend {clé de l'offre : clé déjà en base}."""
    trouves: dict[str, str] = {}
    with closing(base.connexion()) as c:
        for o in offres:
            empreinte = o.empreinte
            r = c.execute("SELECT cle FROM offres WHERE cle != ? AND derniere_vue >= ? AND "
                          "(cle_souple = ? OR (? IS NOT NULL AND empreinte = ?)) LIMIT 1",
                          (o.cle, _maintenant(depuis), o.cle_souple, empreinte, empreinte)).fetchone()
            if r:
                trouves[o.cle] = r[0]
    return trouves


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


# --------------------------------------------------------------------------- envois (lot 3)

def _ligne(r: sqlite3.Row) -> dict:
    d = dict(r)
    stockes = json.loads(d.get("signaux") or "[]")
    d["composantes"] = json.loads(d.get("raisons") or "[]")
    tri = sorted(d["composantes"], key=lambda c: abs(c[1]), reverse=True)
    d["raisons"] = [f"{n} {p:+d}" for n, p in tri[:3]]
    d["signaux"] = [n for n, _ in d["composantes"] if n in ("seconde main", "employeur non indiqué", "republiée",
                                                             "peu candidatée", "école")]
    d["signaux"] += stockes
    return d


def alertes_a_envoyer(base: Base) -> list[dict]:
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT * FROM offres WHERE niveau = 'alerte' AND etat_envoi IN ('aucun', 'en_attente') "
                         "ORDER BY note DESC").fetchall()
    return [_ligne(r) for r in rows]


def a_resumer(base: Base, fil: str) -> list[dict]:
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT * FROM offres WHERE niveau = 'resume' AND etat_envoi = 'aucun' AND fil = ? "
                         "ORDER BY note DESC", (fil,)).fetchall()
    return [_ligne(r) for r in rows]


def marquer(base: Base, cles: list[str], etat: str, le: datetime | None = None) -> None:
    with closing(base.connexion()) as c, c:
        c.executemany("UPDATE offres SET etat_envoi = ?, envoyee_le = ? WHERE cle = ?",
                      [(etat, _maintenant(le), cle) for cle in cles])


def stats_periode(base: Base, debut: datetime, fin: datetime) -> dict:
    d, f = debut.strftime(FORMAT), fin.strftime(FORMAT)
    with closing(base.connexion()) as c:
        par_fil = dict(c.execute("SELECT fil, COUNT(*) FROM offres WHERE envoyee_le BETWEEN ? AND ? "
                                 "AND etat_envoi IN ('envoyee', 'simulee') AND niveau IN ('alerte', 'resume') "
                                 "GROUP BY fil", (d, f)).fetchall())
        alertes = c.execute("SELECT COUNT(*) FROM offres WHERE envoyee_le BETWEEN ? AND ? AND niveau = 'alerte' "
                            "AND etat_envoi IN ('envoyee', 'simulee')", (d, f)).fetchone()[0]
        sources = [dict(r) for r in c.execute(
            "SELECT tache, COUNT(*) AS passages, SUM(succes) AS succes, COALESCE(SUM(nb_offres), 0) AS offres "
            "FROM executions WHERE debut BETWEEN ? AND ? GROUP BY tache ORDER BY tache", (d, f)).fetchall()]
    for s in sources:
        s["echecs_consecutifs"] = echecs_consecutifs(base, s["tache"])
    return {"par_fil": par_fil, "alertes": alertes, "sources": sources}


def derniere_erreur(base: Base, tache: str) -> str:
    with closing(base.connexion()) as c:
        r = c.execute("SELECT erreur FROM executions WHERE tache = ? AND succes = 0 ORDER BY id DESC LIMIT 1",
                      (tache,)).fetchone()
    return (r[0] or "") if r else ""


# --------------------------------------------------------------------------- fichier de suivi (lot 4)

_COLONNE_VEILLE = {"reel": "ajoutee_veille_le", "essai": "ajoutee_essai_le"}


def a_ajouter_veille(base: Base, mode: str = "reel", depuis: datetime | None = None) -> list[dict]:
    """Offres présentées (alerte ou résumé) pas encore ajoutées à l'onglet Veille du mode.

    `depuis` : seulement les offres détectées depuis cette date (reprise à la mise en service).
    """
    colonne = _COLONNE_VEILLE[mode]
    borne = (depuis or datetime(2000, 1, 1)).strftime(FORMAT)
    with closing(base.connexion()) as c:
        rows = c.execute(f"SELECT * FROM offres WHERE niveau IN ('alerte', 'resume') AND {colonne} IS NULL "
                         "AND importee_v1 = 0 AND premiere_vue >= ? ORDER BY premiere_vue, note DESC", (borne,)).fetchall()
    return [_ligne(r) for r in rows]


def marquer_veille(base: Base, cles: list[str], le: datetime | None = None, mode: str = "reel") -> None:
    colonne = _COLONNE_VEILLE[mode]
    with closing(base.connexion()) as c, c:
        c.executemany(f"UPDATE offres SET {colonne} = ? WHERE cle = ?", [(_maintenant(le), k) for k in cles])


def reprendre_simulations(base: Base, depuis: datetime) -> int:
    """Mise en service : les envois simulés récents redeviennent « à envoyer » (une seule fois,
    car un envoi réel les marque ensuite « envoyee »). Les plus anciens restent simulés."""
    with closing(base.connexion()) as c, c:
        return c.execute("UPDATE offres SET etat_envoi = 'aucun', envoyee_le = NULL WHERE etat_envoi = 'simulee' "
                         "AND premiere_vue >= ?", (depuis.strftime(FORMAT),)).rowcount


def candidats_route_b(base: Base, depuis: datetime) -> list[dict]:
    """Employeurs finaux identifiés dont une offre a été rejetée pour séniorité ou ancienneté."""
    with closing(base.connexion()) as c:
        rows = c.execute("SELECT * FROM rejets WHERE motif IN ('seniorite', 'trop_ancienne') AND type_employeur = 'final' "
                         "AND entreprise <> '' AND vu_le >= ? ORDER BY vu_le", (depuis.strftime(FORMAT),)).fetchall()
    return [dict(r) for r in rows]


def route_b_connues(base: Base) -> set[str]:
    with closing(base.connexion()) as c:
        return {r[0] for r in c.execute("SELECT entreprise_normalisee FROM route_b")}


def route_b_ajoutees_depuis(base: Base, depuis: datetime) -> int:
    with closing(base.connexion()) as c:
        return c.execute("SELECT COUNT(*) FROM route_b WHERE ajoutee_le >= ?", (depuis.strftime(FORMAT),)).fetchone()[0]


def ajouter_route_b(base: Base, nom_normalise: str, le: datetime | None = None) -> None:
    with closing(base.connexion()) as c, c:
        c.execute("INSERT OR IGNORE INTO route_b (entreprise_normalisee, ajoutee_le) VALUES (?, ?)",
                  (nom_normalise, _maintenant(le)))
