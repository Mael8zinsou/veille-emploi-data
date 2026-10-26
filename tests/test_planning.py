"""Planification : toutes les heures sont données en UTC, comme dans la base.

Rappel : Paris = UTC+1 en hiver (après le 25 octobre 2026), UTC+2 en été.
"""
from datetime import datetime, timedelta

from src.planning import taches_dues

LUNDI_HIVER_10H = datetime(2026, 10, 26, 9, 0)    # lundi 26/10, 10h à Paris
MARDI_HIVER_10H = datetime(2026, 10, 27, 9, 0)


def plan(config, maintenant, succes=None, envois=None, adzuna=0):
    return taches_dues(maintenant, succes or {}, envois or {}, adzuna, config)


def test_hors_plage_de_nuit(config):
    p = plan(config, datetime(2026, 10, 27, 22, 30))   # 23h30 à Paris
    assert p.hors_plage and p.sources == []
    assert plan(config, datetime(2026, 10, 27, 5, 30)).hors_plage    # 6h30 à Paris


def test_changement_d_heure(config):
    # 5h30 UTC = 7h30 à Paris en été, 6h30 en hiver.
    assert not plan(config, datetime(2026, 7, 1, 5, 30)).hors_plage
    assert plan(config, datetime(2026, 11, 2, 5, 30)).hors_plage


def test_premier_passage_tout_est_du(config):
    p = plan(config, MARDI_HIVER_10H)
    assert set(p.sources) == {"france_travail", "adzuna", "hellowork"}
    assert p.alertes_en_attente


def test_intervalles(config):
    t = config.planning.taches
    succes = {"france_travail": MARDI_HIVER_10H - timedelta(minutes=t["france_travail"].intervalle_minutes - 5),
              "hellowork": MARDI_HIVER_10H - timedelta(minutes=t["hellowork"].intervalle_minutes + 5),
              "adzuna": MARDI_HIVER_10H - timedelta(minutes=t["adzuna"].intervalle_minutes - 60)}
    p = plan(config, MARDI_HIVER_10H, succes)
    assert p.sources == ["hellowork"]
    assert "france_travail" in p.raisons and "adzuna" in p.raisons


def test_passage_en_retard_ne_perd_rien(config):
    # Plus d'une journée sans passage réussi : tout est dû, une seule fois.
    succes = {n: MARDI_HIVER_10H - timedelta(hours=25) for n in ("france_travail", "hellowork", "adzuna")}
    assert set(plan(config, MARDI_HIVER_10H, succes).sources) == {"france_travail", "adzuna", "hellowork"}


def test_quota_adzuna(config):
    p = plan(config, MARDI_HIVER_10H, adzuna=config.planning.quotas.adzuna_mensuel)
    assert "adzuna" not in p.sources and "quota" in p.raisons["adzuna"]


def test_resume_quotidien(config):
    assert not plan(config, datetime(2026, 10, 27, 16, 0)).resume_quotidien      # 17h
    assert plan(config, datetime(2026, 10, 27, 17, 20)).resume_quotidien         # 18h20
    deja = {("resume", "emploi"): datetime(2026, 10, 27, 17, 25)}
    assert not plan(config, datetime(2026, 10, 27, 19, 20), envois=deja).resume_quotidien
    hier = {("resume", "emploi"): datetime(2026, 10, 26, 17, 25)}
    assert plan(config, datetime(2026, 10, 27, 17, 20), envois=hier).resume_quotidien


def test_bilan_du_lundi_meme_en_retard(config):
    assert not plan(config, datetime(2026, 10, 26, 6, 30)).bilan_hebdomadaire     # lundi 7h30
    assert plan(config, LUNDI_HIVER_10H).bilan_hebdomadaire
    # Lundi raté (aucun passage) : le bilan part mardi.
    assert plan(config, MARDI_HIVER_10H).bilan_hebdomadaire
    fait = {("bilan", None): datetime(2026, 10, 26, 9, 5)}
    assert not plan(config, MARDI_HIVER_10H, envois=fait).bilan_hebdomadaire


def test_alertes_du_matin_une_seule_fois(config):
    fait = {("matin", None): datetime(2026, 10, 27, 6, 20)}
    assert not plan(config, MARDI_HIVER_10H, envois=fait).alertes_en_attente
