"""Outils partagés par les scripts du lot 0 (vérification des accès et sondages).

Les résultats sont émis en annotations GitHub Actions (`::notice::`), lisibles par l'API
des check-runs, car les journaux et artefacts ne sont pas accessibles depuis l'espace de
travail de Claude. Aucune valeur secrète n'est jamais écrite.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SECRETS_A_MASQUER = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "FT_CLIENT_SECRET", "LBA_API_KEY",
                     "TELEGRAM_BOT_TOKEN", "GOOGLE_TOKEN_JSON")


def masquer(texte: str) -> str:
    """Retire de `texte` toute valeur de secret présente dans l'environnement."""
    for nom in SECRETS_A_MASQUER:
        valeur = os.getenv(nom)
        if valeur and len(valeur) >= 6:
            texte = texte.replace(valeur, f"<{nom}>")
    return re.sub(r"(app_id|app_key|token|key)=[^&\s]+", r"\1=<masqué>", texte)


def _echapper_annotation(texte: str) -> str:
    return texte.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def notice(titre: str, lignes: list[str] | str) -> None:
    """Émet une annotation GitHub. Plusieurs lignes tiennent dans une seule annotation."""
    corps = lignes if isinstance(lignes, str) else "\n".join(lignes)
    corps = masquer(corps)[:6000]
    print(f"::notice title={_echapper_annotation(titre)}::{_echapper_annotation(corps)}", flush=True)


def ecrire(dossier: Path, nom: str, contenu: str | bytes | dict | list) -> Path:
    """Écrit une réponse brute dans le dossier de sondage, secrets masqués."""
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / nom
    if isinstance(contenu, (dict, list)):
        chemin.write_text(masquer(json.dumps(contenu, ensure_ascii=False, indent=1)), encoding="utf-8")
    elif isinstance(contenu, bytes):
        chemin.write_text(masquer(contenu.decode("utf-8", errors="replace")), encoding="utf-8")
    else:
        chemin.write_text(masquer(contenu), encoding="utf-8")
    return chemin
