"""
Notification Telegram (Markdown V2).

Variables d'environnement requises (sauf en DRY_RUN) :
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Mode DRY_RUN : si la variable d'env DRY_RUN vaut "1", on n'envoie rien à Telegram,
on affiche le(s) message(s) en console. Pratique pour tester sans bot.

Particularités Markdown V2 :
- Tout caractère réservé dans du texte dynamique doit être échappé (cf. _escape).
- Une limite de 4096 caractères par message : on découpe en plusieurs envois numérotés.
"""
import logging
import os
import sys

import requests

from src.models import Offre

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
LIMITE_TELEGRAM = 4096
MARGE = 200  # marge de sécurité sous la limite dure (en-têtes de découpage, etc.)

# Caractères réservés en MarkdownV2 (doc officielle Telegram).
_RESERVES = r"_*[]()~`>#+-=|{}.!"


def _escape(texte: str) -> str:
    """Échappe les caractères réservés MarkdownV2 dans du texte dynamique."""
    if not texte:
        return ""
    out = []
    for ch in texte:
        if ch in _RESERVES:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _format_offre(index: int, offre: Offre) -> str:
    """Met en forme une offre en bloc MarkdownV2."""
    if offre.nb_sources == 1:
        sources_txt = "1 source — exclusif"
    else:
        sources_txt = f"{offre.nb_sources} sources"

    lieu = _escape(offre.localisation or "—")
    contrat = _escape(offre.contrat or "—")
    tags = _escape(", ".join(offre.tags[:6])) if offre.tags else ""

    lignes = [
        f"*\\[{index}\\]* ⭐ score {offre.score} \\({_escape(sources_txt)}\\)",
        f"*{_escape(offre.titre)}* chez *{_escape(offre.entreprise)}*",
        f"📍 {lieu} · {contrat}",
    ]
    if tags:
        lignes.append(f"🏷 {tags}")
    # Le libellé du lien est échappé, l'URL ne l'est pas (entre parenthèses).
    lignes.append(f"🔗 [Voir l'offre]({offre.url})")
    return "\n".join(lignes)


def construire_messages(
    offres: list[Offre], total_scanne: int, date_str: str, heure_str: str = "07:00"
) -> list[str]:
    """
    Construit la liste des messages MarkdownV2 (découpés sous la limite Telegram).
    `date_str` est déjà formaté (ex. "10 juin") par l'appelant.
    """
    entete = (
        f"🌅 *Veille du {_escape(date_str)}* — "
        f"{len(offres)} nouvelle\\(s\\) offre\\(s\\)"
    )
    pied = (
        f"_Pipeline lancé à {_escape(heure_str)} — "
        f"{total_scanne} offres scannées, {len(offres)} nouvelles_"
    )

    blocs = [_format_offre(i, o) for i, o in enumerate(offres, 1)]

    messages: list[str] = []
    courant = entete
    for bloc in blocs:
        candidat = f"{courant}\n\n{bloc}"
        if len(candidat) > LIMITE_TELEGRAM - MARGE:
            messages.append(courant)
            courant = bloc  # nouveau message démarre par le bloc courant
        else:
            courant = candidat
    # Pied de message sur le dernier.
    if len(f"{courant}\n\n{pied}") <= LIMITE_TELEGRAM - MARGE:
        courant = f"{courant}\n\n{pied}"
        messages.append(courant)
    else:
        messages.append(courant)
        messages.append(pied)

    # Numérotation si plusieurs messages.
    if len(messages) > 1:
        total = len(messages)
        messages = [f"{m}\n\n_\\({i}/{total}\\)_" for i, m in enumerate(messages, 1)]
    return messages


def message_jour_vide(total_scanne: int, date_str: str) -> str:
    """Message quand aucune nouvelle offre n'a passé le seuil."""
    return (
        f"🌅 *Veille du {_escape(date_str)}*\n\n"
        f"Aucune nouvelle offre au\\-dessus du seuil aujourd'hui\\.\n"
        f"_{total_scanne} offres scannées\\._"
    )


def _envoyer(token: str, chat_id: str, texte: str, session: requests.Session | None = None) -> bool:
    """Envoie un message via l'API Telegram. True si OK."""
    payload = {
        "chat_id": chat_id,
        "text": texte,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    url = API_URL.format(token=token)
    try:
        if session is not None:
            r = session.post(url, json=payload, timeout=15)
        else:
            r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            logger.error("Telegram : HTTP %s — %s", r.status_code, r.text[:300])
            return False
        return True
    except requests.RequestException as e:
        logger.error("Telegram : échec d'envoi — %s", e)
        return False


def _dry_run() -> bool:
    return os.getenv("DRY_RUN") == "1"


def _print_console(texte: str) -> None:
    """
    print() tolérant à l'encodage console. Sous Windows, la console est souvent en
    cp1252 et ne sait pas afficher les emojis : on retombe alors sur un rendu ASCII
    plutôt que de planter. N'affecte que l'affichage DRY_RUN, jamais l'envoi réel.
    """
    try:
        print(texte)
    except UnicodeEncodeError:
        enc = (sys.stdout.encoding or "ascii")
        print(texte.encode(enc, errors="replace").decode(enc, errors="replace"))


def envoyer_messages(messages: list[str], session: requests.Session | None = None) -> bool:
    """
    Envoie chaque message. En DRY_RUN, les affiche en console sans appel réseau.
    Retourne True si tout est parti (ou en DRY_RUN).
    """
    if _dry_run():
        _print_console("\n===== DRY_RUN : messages Telegram (non envoyés) =====")
        for i, m in enumerate(messages, 1):
            _print_console(f"\n----- message {i}/{len(messages)} -----\n{m}")
        _print_console("\n===== fin DRY_RUN =====\n")
        return True

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Telegram : TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID absents.")
        return False

    ok = True
    for m in messages:
        if not _envoyer(token, chat_id, m, session):
            ok = False
    return ok
