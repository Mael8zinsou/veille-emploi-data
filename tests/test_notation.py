import sqlite3
from datetime import date, datetime

from src import main, stockage
from src.filtres import normaliser_offre
from src.models import Niveau
from src.notation import niveau, noter, table_verdicts, verdict_de
from tests.conftest import offre

JOUR = date(2026, 10, 26)


def note_de(config, verdicts=None, **kw):
    o = normaliser_offre(offre(**kw), config)
    n = noter(o, config, JOUR, table_verdicts(verdicts or []))
    return o, n


def raisons(n):
    return dict(n.composantes)


def test_composantes_lisibles(config):
    _, n = note_de(config, titre="Data Engineer junior", entreprise="Doctolib", lieu="Paris 75",
                   description="Python, SQL, Airflow, dbt, Docker.", date_publication="2026-10-26")
    r = raisons(n)
    assert r["priorité 1"] == 6 and r["signal junior"] == 3 and r["zone préférée"] == 1
    assert r["publiée depuis un jour au plus"] == 2
    assert any(k.startswith("compétences") for k in r)
    assert n.total == sum(r.values())
    assert n.raisons(1) == ["priorité 1 +6"]


def test_plafond_des_competences(config):
    _, n = note_de(config, description=" ".join(config.notation.competences.liste))
    assert max(p for r, p in n.composantes if r.startswith("compétences")) == config.notation.competences.plafond


def test_malus(config):
    _, esn = note_de(config, entreprise="ALTEN")
    _, inconnu = note_de(config, entreprise="")
    _, confirme = note_de(config, titre="Data Engineer confirmé")
    assert raisons(esn)["ESN"] < 0 and raisons(inconnu)["employeur non indiqué"] < 0
    assert raisons(confirme)["« confirmé » dans le titre"] < 0


def test_verdicts_du_suivi(config):
    v = table_verdicts([("SOCOTEC", "Cible prioritaire"), ("EY", "Dernière priorité : filtre grande école"),
                        ("Mondial Relay", "Écarter : ingénierie hors de France"), ("Akuo", "Cible")])
    assert verdict_de("SOCOTEC Group", v) == "cible prioritaire"
    assert verdict_de("EY Consulting", v) is None          # nom trop court : ignoré
    assert verdict_de("Doctolib", v) is None
    _, n = note_de(config, verdicts=[("SOCOTEC", "Cible prioritaire")], entreprise="SOCOTEC Group")
    assert raisons(n)["cible prioritaire du suivi"] == 6 and n.cible
    _, n = note_de(config, verdicts=[("Mondial Relay", "Écarter : ingénierie hors de France")], entreprise="Mondial Relay")
    assert n.archivee


def test_niveaux(config):
    o, n = note_de(config, titre="Data Engineer junior", lieu="Paris", description="Python SQL Airflow dbt",
                   date_publication="2026-10-26")
    assert n.total >= config.notation.niveaux.alerte.note_min and niveau(o, n, config) == Niveau.ALERTE
    # Même offre en alternance : jamais d'alerte (résumé seulement).
    o, n = note_de(config, titre="Alternance Data Engineer junior", lieu="Paris", description="Python SQL Airflow dbt",
                   date_publication="2026-10-26")
    assert niveau(o, n, config) == Niveau.RESUME
    # Seconde main : pas d'alerte, même bien notée.
    o, n = note_de(config, titre="Data Engineer junior", entreprise="", lieu="Paris", description="Python SQL Airflow dbt",
                   date_publication="2026-10-26")
    assert niveau(o, n, config) != Niveau.ALERTE
    # Calibrage du 26/10 : toute offre gardée par les filtres entre au moins dans le résumé.
    o, n = note_de(config, titre="Chef de projet data", entreprise="ALTEN", date_publication="2026-10-20")
    assert n.total < 0 and niveau(o, n, config) == Niveau.RESUME
    # Verdict définitif du suivi : archive d'office.
    o, n = note_de(config, verdicts=[("Mondial Relay", "Écarter : ingénierie hors de France")],
                   entreprise="Mondial Relay", titre="Data Engineer junior", description="Python SQL Airflow dbt")
    assert niveau(o, n, config) == Niveau.ARCHIVE


def test_republication_dans_le_passage(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    sources = {"france_travail": lambda ctx: [offre()], "adzuna": lambda ctx: [], "hellowork": lambda ctx: []}
    main.passage(config, base, datetime(2026, 9, 1, 9, 0), sources_imposees=["france_travail"], session=object(),
                 sources=sources)
    r = main.passage(config, base, datetime(2026, 9, 2, 9, 0), sources_imposees=["france_travail"], session=object(),
                     sources=sources)
    assert r.nouvelles == 0
    # Revue 40 jours plus tard : republiée, donc de nouveau présentée, avec un malus.
    r = main.passage(config, base, datetime(2026, 10, 12, 9, 0), sources_imposees=["france_travail"], session=object(),
                     sources=sources)
    assert r.nouvelles == 1
    with sqlite3.connect(base.chemin) as c:
        assert "republiée" in c.execute("SELECT raisons FROM offres").fetchone()[0]
