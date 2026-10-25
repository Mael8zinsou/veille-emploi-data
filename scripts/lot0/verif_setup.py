"""Lot 0 : vérifie les accès dont la v2 a besoin, en lecture seule.

1. Google Sheets : le jeton ouvre-t-il le fichier de suivi ? Onglets, en-têtes, formules.
2. Telegram : identifiant du groupe à sujets et des sujets, statut du bot. Un message de
   test est posté dans chaque sujet détecté, pour confirmation visuelle.
3. La bonne alternance : la clé est-elle acceptée ?

Chaque vérification est isolée : un échec n'empêche pas les suivantes. Les résultats sont
émis en annotations (cf. commun.py). Rien n'est écrit dans le fichier de suivi.

Variables : GOOGLE_TOKEN_JSON, SUIVI_SHEET_ID, TELEGRAM_BOT_TOKEN, LBA_API_KEY.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).parent))
from commun import ecrire, notice

SORTIE = Path(os.getenv("SONDE_DIR", "sondes_out")) / "verif"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
TG = "https://api.telegram.org/bot{token}/{methode}"
LBA_BASE = "https://api.apprentissage.beta.gouv.fr"


# --------------------------------------------------------------------------- Google Sheets

def _session_google():
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials

    info = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
    creds = Credentials.from_authorized_user_info(info)
    creds.refresh(Request())
    portees = sorted(creds.granted_scopes or info.get("scopes") or [])
    return AuthorizedSession(creds), portees


def verif_sheets() -> bool:
    sheet_id = os.environ.get("SUIVI_SHEET_ID", "").strip()
    if not sheet_id or not os.getenv("GOOGLE_TOKEN_JSON"):
        notice("Sheets : secrets absents", "GOOGLE_TOKEN_JSON ou SUIVI_SHEET_ID manquant.")
        return False
    s, portees = _session_google()
    lignes = [f"Portées du jeton : {', '.join(portees) or 'inconnues'}"]

    meta = s.get(f"{SHEETS}/{sheet_id}", params={"fields": "properties(title,locale,timeZone),"
                                                 "sheets.properties(title,gridProperties)"})
    lignes.append(f"Lecture du fichier : HTTP {meta.status_code}")
    if meta.status_code != 200:
        lignes.append(meta.text[:400])
        notice("Sheets : ÉCHEC", lignes)
        return False
    m = meta.json()
    p = m.get("properties", {})
    lignes.append(f"Paramètres régionaux : {p.get('locale')}, fuseau {p.get('timeZone')}")
    for feuille in m.get("sheets", []):
        fp = feuille["properties"]
        g = fp.get("gridProperties", {})
        lignes.append(f"Onglet « {fp['title']} » : {g.get('rowCount')} lignes x {g.get('columnCount')} colonnes")

    def lire(plage: str, rendu: str) -> list:
        r = s.get(f"{SHEETS}/{sheet_id}/values/{quote(plage)}", params={"valueRenderOption": rendu})
        return r.json().get("values", []) if r.status_code == 200 else [[f"HTTP {r.status_code}"]]

    # En-têtes (ligne 4) et premières formules, sans lire de données personnelles.
    for onglet, plage in (("Candidatures", "A4:N4"), ("Entreprises", "A4:I4"), ("Contacts", "A4:P4")):
        entetes = lire(f"'{onglet}'!{plage}", "FORMATTED_VALUE")
        lignes.append(f"En-têtes {onglet} : {' | '.join(entetes[0]) if entetes else 'vide'}")
    formules = lire("'Candidatures'!K5:L5", "FORMULA")
    valeurs = lire("'Candidatures'!K5:L5", "FORMATTED_VALUE")
    lignes.append(f"Candidatures K5:L5, formules présentes : {bool(formules and str(formules[0][0]).startswith('='))}")
    lignes.append(f"Candidatures K5:L5, valeurs calculées : {valeurs[0] if valeurs else 'vide'}")
    colonne_a = lire("'Candidatures'!A5:A300", "FORMATTED_VALUE")
    remplies = sum(1 for ligne in colonne_a if ligne and str(ligne[0]).strip())
    lignes.append(f"Candidatures : {remplies} lignes saisies dans le bloc A5:A300")
    verdicts = lire("'Entreprises'!C5:C400", "FORMATTED_VALUE")
    compte: dict[str, int] = {}
    for ligne in verdicts:
        if ligne and ligne[0]:
            compte[ligne[0]] = compte.get(ligne[0], 0) + 1
    lignes.append("Verdicts Entreprises : " + ", ".join(f"{k} ({v})" for k, v in sorted(compte.items())))
    notice("Sheets : OK", lignes)
    return True


# --------------------------------------------------------------------------- Telegram

def _tg(methode: str, **params):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(TG.format(token=token, methode=methode), json=params, timeout=20)
    return r.json()


def verif_telegram() -> bool:
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        notice("Telegram : secret absent", "TELEGRAM_BOT_TOKEN manquant.")
        return False
    moi = _tg("getMe")
    bot = moi.get("result", {})
    lignes = [(f"Bot : @{bot.get('username')} (id {bot.get('id')}), "
               f"lit tous les messages de groupe : {bot.get('can_read_all_group_messages')}")]
    maj = _tg("getUpdates", limit=100, allowed_updates=["message", "my_chat_member", "chat_member"])
    if not maj.get("ok"):
        lignes.append(f"getUpdates refusé : {maj.get('description')}")
        notice("Telegram : ÉCHEC", lignes)
        return False
    updates = maj.get("result", [])
    ecrire(SORTIE, "telegram_updates.json", {"nb": len(updates)})
    lignes.append(f"{len(updates)} mises à jour récentes reçues")

    groupes: dict[int, dict] = {}
    sujets: dict[tuple[int, int], str] = {}
    for u in updates:
        msg = u.get("message") or {}
        chat = msg.get("chat") or (u.get("my_chat_member") or {}).get("chat") or {}
        if not chat or chat.get("type") not in ("group", "supergroup"):
            continue
        groupes[chat["id"]] = {"titre": chat.get("title"), "forum": chat.get("is_forum", False)}
        fil = msg.get("message_thread_id")
        if fil and msg.get("is_topic_message"):
            nom = ((msg.get("reply_to_message") or {}).get("forum_topic_created") or {}).get("name")
            nom = nom or (msg.get("forum_topic_created") or {}).get("name") or "?"
            sujets[(chat["id"], fil)] = nom

    if not groupes:
        lignes.append("Aucun groupe vu. Écris un message dans chaque sujet du groupe, puis relance.")
        notice("Telegram : groupe introuvable", lignes)
        return False
    for gid, g in groupes.items():
        membre = _tg("getChatMember", chat_id=gid, user_id=bot.get("id")).get("result", {})
        lignes.append(f"Groupe « {g['titre']} » : chat_id {gid}, sujets activés {g['forum']}, "
                      f"bot {membre.get('status')}")
    for (gid, fil), nom in sorted(sujets.items()):
        lignes.append(f"Sujet « {nom} » : message_thread_id {fil}")
        r = _tg("sendMessage", chat_id=gid, message_thread_id=fil,
                text=f"Test de la refonte v2 : sujet « {nom} » détecté (identifiant {fil}).")
        lignes.append(f"  message de test : {'envoyé' if r.get('ok') else r.get('description')}")
    if not sujets:
        lignes.append("Aucun message de sujet vu : écris un message dans chaque sujet, puis relance.")
    notice("Telegram : OK" if sujets else "Telegram : sujets introuvables", lignes)
    return bool(sujets)


# --------------------------------------------------------------------------- La bonne alternance

def verif_lba() -> bool:
    cle = os.getenv("LBA_API_KEY", "").strip()
    if not cle:
        notice("La bonne alternance : secret absent", "LBA_API_KEY manquant.")
        return False
    lignes = []
    # Découverte de la documentation OpenAPI (sans authentification).
    for chemin in ("/api/documentation/json", "/api/docs/json", "/api/openapi.json", "/api/swagger.json"):
        try:
            r = requests.get(LBA_BASE + chemin, timeout=20)
        except requests.RequestException as e:
            lignes.append(f"{chemin} : {e.__class__.__name__}")
            continue
        lignes.append(f"{chemin} : HTTP {r.status_code}")
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
            doc = r.json()
            ecrire(SORTIE, "lba_openapi.json", doc)
            chemins = [p for p in doc.get("paths", {}) if "job" in p.lower()]
            lignes.append("Chemins « job » : " + ", ".join(chemins[:15]))
            break
    # Essai de recherche (chemin le plus probable, confirmé ou non par la documentation).
    params = {"romes": "M1811,M1405,M1419", "latitude": 48.8566, "longitude": 2.3522, "radius": 50}
    r = requests.get(f"{LBA_BASE}/api/job/v1/search", params=params,
                     headers={"Authorization": f"Bearer {cle}"}, timeout=30)
    lignes.append(f"/api/job/v1/search : HTTP {r.status_code}")
    ok = r.status_code == 200
    if ok:
        data = r.json()
        ecrire(SORTIE, "lba_search.json", data)
        for k, v in (data.items() if isinstance(data, dict) else []):
            lignes.append(f"  {k} : {len(v) if isinstance(v, list) else type(v).__name__}")
    else:
        lignes.append(r.text[:300])
    notice("La bonne alternance : OK" if ok else "La bonne alternance : à revoir", lignes)
    return ok


def main() -> int:
    resultats = {}
    for nom, fn in (("sheets", verif_sheets), ("telegram", verif_telegram), ("lba", verif_lba)):
        try:
            resultats[nom] = fn()
        except Exception as e:  # noqa: BLE001 (une vérification ne doit pas masquer les autres)
            notice(f"{nom} : erreur", traceback.format_exc()[-1500:] or str(e))
            resultats[nom] = False
    notice("Synthèse des vérifications", [f"{k} : {'OK' if v else 'à revoir'}" for k, v in resultats.items()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
