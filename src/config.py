"""
Chargement de config/profil.yaml en objets Python.
SimpleNamespace permet d'accéder aux champs avec la syntaxe `config.telegram.top_n_par_jour`.
"""
from pathlib import Path
from types import SimpleNamespace

import yaml


def _to_namespace(data):
    """Convertit récursivement dict -> SimpleNamespace, listes inchangées."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_to_namespace(x) for x in data]
    return data


def load_config(path: str | Path) -> SimpleNamespace:
    """Charge un YAML et retourne un namespace navigable."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return _to_namespace(raw)


def load_slugs(path: str | Path) -> list[tuple[str, str]]:
    """
    Lit config/slugs_ats.txt.
    Format par ligne : `<ats>:<slug>` (ex. `greenhouse:doctolib`).
    Lignes vides et commentaires (#) ignorés.
    Retourne [(ats, slug), ...].
    """
    out: list[tuple[str, str]] = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        ats, slug = line.split(":", 1)
        ats, slug = ats.strip().lower(), slug.strip()
        if ats and slug:
            out.append((ats, slug))
    return out
