"""Messages Telegram (conception § 7) : alertes, résumés quotidiens, bilan, avertissements.

Format HTML : seuls `<`, `>` et `&` sont à échapper, ce qui supprime la principale cause de
messages refusés de la v1 (MarkdownV2). Chaque message tient sous la limite de 4 096
caractères ; un résumé trop long est découpé.

Deux modes d'envoi :
* `telegram` : envoi réel dans le sujet du fil (groupe à sujets) ;
* `simulation` : rien n'est envoyé, les messages sont gardés et journalisés (mode ombre,
  tests). Un message simulé compte comme « traité » : il n'est pas rejoué au passage suivant.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMITE = 4096
MARGE = 96
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
LIBELLES_FIL = {"emploi": "Emploi", "alternance": "Alternance", "immersion": "Immersion"}


def e(texte: object) -> str:
    return html.escape(str(texte or ""), quote=False)


def date_fr(d) -> str:
    return f"{d.day} {MOIS[d.month - 1]}"


def _lien(url: str, libelle: str = "Voir l'offre") -> str:
    return f'<a href="{html.escape(url or "", quote=True)}">{e(libelle)}</a>' if url else ""


def message_alerte(o: dict) -> str:
    """`o` : ligne de la table offres (titre, entreprise, lieu, contrat, note, raisons, url, signaux)."""
    lignes = [f"🔔 <b>{e(o['titre'])}</b>",
              " · ".join(p for p in (e(o.get("entreprise") or "Employeur non indiqué"), e(o.get("lieu")),
                                      e(o.get("contrat"))) if p),
              f"Note {o['note']} : {e(', '.join(o.get('raisons') or []))}"]
    if o.get("signaux"):
        lignes.append("⚠️ " + e(", ".join(o["signaux"])))
    lignes.append(_lien(o.get("url", "")))
    return "\n".join(lignes)


def _ligne_resume(i: int, o: dict) -> str:
    detail = " · ".join(p for p in (e(o.get("entreprise") or "?"), e(o.get("lieu"))) if p)
    lien = _lien(o.get("url", ""), "offre")
    return f"{i}. <b>{o['note']}</b> {e(o['titre'])} · {detail} · {lien}"


def messages_resume(fil: str, offres: list[dict], jour, maximum: int) -> list[str]:
    """Résumé d'un fil : offres classées par note, `maximum` au plus, découpé sous la limite."""
    tri = sorted(offres, key=lambda o: o["note"], reverse=True)
    montrees, reste = tri[:maximum], len(tri) - maximum
    entete = f"🗞 <b>Résumé du {date_fr(jour)}</b> · {LIBELLES_FIL.get(fil, fil)} · {len(tri)} offre(s)"
    if not tri:
        return [f"{entete}\nAucune nouvelle offre aujourd'hui."]
    messages, courant = [], entete
    for i, o in enumerate(montrees, start=1):
        ligne = _ligne_resume(i, o)
        if len(courant) + len(ligne) + 1 > LIMITE - MARGE:
            messages.append(courant)
            courant = f"{entete} (suite)"
        courant += "\n" + ligne
    if reste > 0:
        courant += f"\n… et {reste} autre(s), notées plus bas, dans l'onglet Veille."
    messages.append(courant)
    return messages


def message_bilan(stats: dict) -> str:
    lignes = [f"📊 <b>Bilan de la semaine</b> (du {e(stats['du'])} au {e(stats['au'])})"]
    lignes.append("Offres présentées : " + ", ".join(f"{LIBELLES_FIL.get(f, f)} {n}" for f, n in stats["par_fil"].items())
                  if stats["par_fil"] else "Offres présentées : aucune")
    lignes.append(f"Alertes envoyées : {stats['alertes']}")
    for s in stats["sources"]:
        etat = "✅" if s["echecs_consecutifs"] == 0 else "⚠️"
        lignes.append(f"{etat} {e(s['tache'])} : {s['succes']}/{s['passages']} passages réussis, {s['offres']} offres"
                      + (f", {s['echecs_consecutifs']} échec(s) d'affilée" if s["echecs_consecutifs"] else ""))
    lignes.append(f"Adzuna : {stats['adzuna_mois']} requêtes ce mois-ci sur {stats['adzuna_plafond']}")
    return "\n".join(lignes)


def message_panne(tache: str, echecs: int, erreur: str) -> str:
    return (f"⚠️ <b>Source en panne : {e(tache)}</b>\n{echecs} passages en échec d'affilée.\n"
            f"Dernière erreur : {e(erreur)[:300]}\nLes autres sources continuent.")


@dataclass
class Telegram:
    session: object
    token: str | None
    groupe_id: int
    sujets: dict[str, int]
    mode: str = "simulation"
    envoyes: list[tuple[str | None, str]] = field(default_factory=list)

    def envoyer(self, texte: str, fil: str | None = None) -> bool:
        """Envoie dans le sujet du fil (ou le sujet général si `fil` est None)."""
        self.envoyes.append((fil, texte))
        if self.mode != "telegram":
            logger.info("[simulation] %s : %s", fil or "général", texte.splitlines()[0][:120])
            return True
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN absent : envoi impossible")
            return False
        corps = {"chat_id": self.groupe_id, "text": texte[:LIMITE], "parse_mode": "HTML",
                 "disable_web_page_preview": True}
        if fil and fil in self.sujets:
            corps["message_thread_id"] = self.sujets[fil]
        try:
            r = self.session.post(API.format(token=self.token), json=corps, timeout=20)
            ok = r.status_code == 200 and r.json().get("ok", False)
        except Exception as ex:  # un envoi raté est rejoué au passage suivant
            logger.warning("Telegram : %s", ex.__class__.__name__)
            return False
        if not ok:
            logger.warning("Telegram : HTTP %s %s", r.status_code, r.text[:200])
        return ok
