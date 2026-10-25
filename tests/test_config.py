import shutil

import pytest
import yaml
from pydantic import ValidationError

from src.config import DOSSIER_CONFIG, charger


def test_configuration_reelle_valide(config):
    assert {f.nom for f in config.metiers.familles} >= {"data_engineering", "data_science", "ia_ml", "analyse"}
    assert config.planning.quotas.adzuna_mensuel <= 250


def test_motifs_normalises_au_chargement(config):
    de = next(f for f in config.metiers.familles if f.nom == "data_engineering")
    assert "ingenieur donnees" in de.motifs
    assert all(m == m.lower() and "é" not in m for f in config.metiers.familles for m in f.motifs)
    assert "belgique" in config.filtres.lieux.etrangers


def _copie(tmp_path, fichier, modifier):
    d = tmp_path / "config"
    shutil.copytree(DOSSIER_CONFIG, d)
    donnees = yaml.safe_load((d / fichier).read_text(encoding="utf-8"))
    modifier(donnees)
    (d / fichier).write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return d


def test_cle_inconnue_refusee(tmp_path):
    d = _copie(tmp_path, "filtres.yaml", lambda c: c.update({"fraicheur_maxi_jours": 3}))
    with pytest.raises(ValidationError):
        charger(d)


def test_priorite_hors_bornes_refusee(tmp_path):
    d = _copie(tmp_path, "metiers.yaml", lambda c: c["familles"][0].update({"priorite": 4}))
    with pytest.raises(ValidationError):
        charger(d)


def test_famille_sans_motif_refusee(tmp_path):
    d = _copie(tmp_path, "metiers.yaml", lambda c: c["familles"][0].update({"motifs": []}))
    with pytest.raises(ValidationError):
        charger(d)


def test_quota_adzuna_au_dela_du_gratuit_refuse(tmp_path):
    d = _copie(tmp_path, "planning.yaml", lambda c: c["quotas"].update({"adzuna_mensuel": 400}))
    with pytest.raises(ValidationError):
        charger(d)


def test_plage_inversee_refusee(tmp_path):
    d = _copie(tmp_path, "planning.yaml", lambda c: c.update({"plage": {"debut": 22, "fin": 7}}))
    with pytest.raises(ValidationError):
        charger(d)
