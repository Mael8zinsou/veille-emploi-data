from pathlib import Path

from src.config import load_config, load_slugs


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_config_lit_profil_yaml():
    cfg = load_config(REPO_ROOT / "config" / "profil.yaml")
    assert cfg.profil.poste_cible == "Data Engineer Junior"
    assert "data engineer" in cfg.mots_cles_must_match
    assert cfg.telegram.top_n_par_jour == 30
    assert cfg.fraicheur_max_jours == 3
    assert cfg.sources_actives.adzuna is True


def test_load_slugs_ignore_commentaires_et_vides(tmp_path):
    p = tmp_path / "slugs.txt"
    p.write_text(
        "# commentaire\n"
        "\n"
        "greenhouse:doctolib\n"
        " lever:alan \n"
        "ligne sans deux-points\n"
        "ashby:foo\n",
        encoding="utf-8",
    )
    slugs = load_slugs(p)
    assert slugs == [
        ("greenhouse", "doctolib"),
        ("lever", "alan"),
        ("ashby", "foo"),
    ]


def test_load_slugs_fichier_absent_retourne_vide(tmp_path):
    assert load_slugs(tmp_path / "absent.txt") == []
