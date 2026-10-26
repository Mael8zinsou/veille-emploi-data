"""Évaluation du tri : métriques, seuils et incontournables sur des avis simulés."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluer_tri as ev

from tests.conftest import offre

JOUR = date(2026, 10, 26)


def jeu():
    return [(1, offre(titre="Data Engineer junior", description="Python SQL Airflow dbt", date_publication="2026-10-26")),
            (2, offre(titre="Data Analyst", entreprise="ALTEN")),
            (3, offre(titre="Senior Data Engineer")),
            (4, offre(titre="Comptable")),
            (5, offre(titre="Chef de projet data confirmé", entreprise="ALTEN", date_publication="2026-10-20"))]


def test_metriques(config):
    avis = {1: ev.POSTULE, 2: ev.PEUT_ETRE, 3: ev.POSTULE, 4: ev.HORS_CIBLE, 5: ev.HORS_CIBLE}
    res = ev.rejouer(jeu(), avis, config, JOUR)
    m = ev.metriques(res)
    assert m["annotees"] == 5
    assert m["rappel_filtres"] == 0.5               # la 3 (senior) est rejetée alors que « je postule »
    assert m["alertes"] == 1 and m["precision_alertes"] == 1.0
    assert m["hors_cible_ecartees"] == 1.0          # 4 rejetée, 5 en archive


def test_offres_sans_avis_ignorees(config):
    assert [r.numero for r in ev.rejouer(jeu(), {2: ev.PEUT_ETRE}, config, JOUR)] == [2]


def test_balayage_des_seuils(config):
    res = ev.rejouer(jeu(), {n: ev.POSTULE for n, _ in jeu()}, config, JOUR)
    lignes = ev.balayer_seuils(res, config, JOUR)
    assert all(b["resume"] <= b["alerte"] for b in lignes)
    bas = next(b for b in lignes if b["alerte"] == 6 and b["resume"] == 0)
    haut = next(b for b in lignes if b["alerte"] == 20 and b["resume"] == 10)
    assert bas["presentees"] >= haut["presentees"]


def test_lecture_des_avis():
    lignes = [["1", "t", "e", "l", "c", "s", "u", "je postule", ""], ["2", "t"], ["x", "", "", "", "", "", "", "je postule"],
              ["3", "t", "e", "l", "c", "s", "u", "autre chose"]]
    assert ev.avis_depuis_lignes(lignes) == {1: "je postule"}


def test_offre_brute_rejouable(config):
    from dataclasses import asdict

    from src.filtres import normaliser_offre
    o = normaliser_offre(offre(titre="Alternance Data Analyst"), config)
    brute = ev.offre_brute(asdict(o))
    assert brute.famille == "" and brute.titre == o.titre      # la normalisation sera rejouée


def test_incontournables_actuels(config):
    assert all(x["ok"] for x in ev.incontournables(config, JOUR))
