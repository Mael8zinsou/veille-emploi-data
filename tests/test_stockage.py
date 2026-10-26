import sqlite3
from datetime import datetime

from src import stockage
from src.filtres import normaliser_offre
from src.models import Motif, Rejet
from tests.conftest import offre


def test_creation_et_idempotence(tmp_path):
    chemin = tmp_path / "b.sqlite"
    stockage.ouvrir(chemin)
    stockage.ouvrir(chemin)
    with sqlite3.connect(chemin) as c:
        assert c.execute("SELECT COUNT(*) FROM version_schema").fetchone()[0] == 1


def test_import_v1(tmp_path):
    chemin = tmp_path / "prod.sqlite"
    with sqlite3.connect(chemin) as c:
        c.executescript("""CREATE TABLE offres_vues (cle_unique TEXT PRIMARY KEY, titre TEXT NOT NULL,
            entreprise TEXT NOT NULL, url TEXT NOT NULL, score INTEGER NOT NULL, date_premiere_vue TEXT NOT NULL,
            date_derniere_vue TEXT NOT NULL, sources TEXT NOT NULL, notifiee INTEGER NOT NULL DEFAULT 0);
            INSERT INTO offres_vues VALUES ('abc', 'Data Engineer', 'Doctolib', 'u', 6, '2026-09-01 07:00:00',
                                            '2026-09-02 07:00:00', 'APEC', 1);""")
    base = stockage.ouvrir(chemin)
    assert stockage.cles_connues(base, ["abc", "zzz"]) == {"abc"}
    stockage.ouvrir(chemin)   # second appel : pas de double import
    with sqlite3.connect(chemin) as c:
        assert c.execute("SELECT COUNT(*), MAX(etat_envoi), MAX(importee_v1) FROM offres").fetchone() == (1, "envoyee", 1)


def test_offres_enregistrees_puis_revues(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    o = normaliser_offre(offre(), config)
    stockage.enregistrer_offres(base, [o])
    stockage.enregistrer_offres(base, [o])
    assert stockage.cles_connues(base, [o.cle]) == {o.cle}
    with sqlite3.connect(base.chemin) as c:
        assert c.execute("SELECT COUNT(*), fil, famille FROM offres").fetchone() == (1, "emploi", "data_engineering")


def test_rejets_dedoublonnes_par_motif(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    o = normaliser_offre(offre(titre="Senior Data Engineer"), config)
    stockage.enregistrer_rejets(base, [Rejet(o, Motif.SENIORITE, "titre : senior")] * 2)
    with sqlite3.connect(base.chemin) as c:
        assert c.execute("SELECT COUNT(*), motif FROM rejets").fetchone() == (1, "seniorite")


def test_executions_quota_et_echecs(tmp_path):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    i = stockage.debut_execution(base, "adzuna")
    stockage.fin_execution(base, i, True, 50, requetes=2)
    for _ in range(3):
        j = stockage.debut_execution(base, "france_travail")
        stockage.fin_execution(base, j, False, 0, 1, "HTTP 500")
    maintenant = stockage.maintenant_utc()
    assert stockage.requetes_du_mois(base, "adzuna", maintenant) == 2
    assert stockage.echecs_consecutifs(base, "france_travail") == 3
    assert stockage.echecs_consecutifs(base, "adzuna") == 0
    assert set(stockage.dernier_succes(base)) == {"adzuna"}


def test_envois(tmp_path):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    stockage.enregistrer_envoi(base, "resume", "emploi", datetime(2026, 10, 26, 17, 5))
    assert stockage.derniers_envois(base) == {("resume", "emploi"): datetime(2026, 10, 26, 17, 5)}


def test_purge(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    stockage.enregistrer_offres(base, [normaliser_offre(offre(), config)])
    with sqlite3.connect(base.chemin) as c:
        c.execute("UPDATE offres SET derniere_vue = '2025-01-01 00:00:00'")
    assert stockage.purger(base) == (1, 0)


def test_memoire_des_sources(tmp_path):
    from datetime import datetime, timedelta
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    t0 = datetime(2026, 10, 26, 10, 0)
    stockage.ecrire_memoire(base, "service_public", {"A": {"x": "é"}}, t0)
    stockage.ecrire_memoire(base, "service_public", {"A": {"x": "autre"}, "B": {}}, t0 + timedelta(days=59))
    assert stockage.lire_memoire(base, "service_public") == {"A": {"x": "é"}, "B": {}}   # A garde sa valeur
    assert stockage.lire_memoire(base, "autre") == {}
    stockage.ecrire_memoire(base, "service_public", {}, t0 + timedelta(days=61))
    assert stockage.lire_memoire(base, "service_public") == {"B": {}}                    # A oubliée
