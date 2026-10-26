"""Un passage du pipeline v2 (conception § 1).

Lot 1 : planification, collecte, normalisation, filtres, dédoublonnage, enregistrement et
rapport. La note, les envois Telegram et les écritures Google Sheets arrivent aux lots 2 à 4.

Lancement : `python -m src.main`
Variables : FT_CLIENT_ID, FT_CLIENT_SECRET, ADZUNA_APP_ID, ADZUNA_APP_KEY.
Options : VEILLE_BASE (chemin de la base), VEILLE_SOURCES (liste imposée, ignore le planning),
VEILLE_SOURCES_EXCLUES, VEILLE_ENVOI (telegram pour un envoi réel, simulation sinon),
VEILLE_MAINTENANT (essais : heure UTC imposée), VEILLE_SUIVI (reel, essai ou aucun ; requiert
GOOGLE_TOKEN_JSON et SUIVI_SHEET_ID), VEILLE_RAPPORT (rapport JSON), VERBOSE=1.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src import dedoublonnage, filtres, notation, planning, stockage
from src.config import Config, charger
from src.models import Offre, Rejet
from src.planning import Plan
from src.sorties import telegram as tgm
from src.sorties.sheets import ClientSheets, ErreurSheets
from src.sorties.suivi import ROUTE_B_PAR_JOUR, Suivi
from src.sorties.telegram import Telegram
from src.sources import Contexte, SourceIndisponible, adzuna, france_travail, hellowork, service_public
from src.utils.http import build_session

logger = logging.getLogger("veille")

SOURCES = {m.NOM: m.fetch for m in (france_travail, adzuna, hellowork, service_public)}


@dataclass
class Rapport:
    debut: str
    plan: dict
    sources: dict[str, dict] = field(default_factory=dict)
    brutes: int = 0
    gardees: int = 0
    nouvelles: int = 0
    rejets_par_motif: dict[str, int] = field(default_factory=dict)
    par_fil: dict[str, int] = field(default_factory=dict)
    par_famille: dict[str, int] = field(default_factory=dict)
    par_type_employeur: dict[str, int] = field(default_factory=dict)
    par_niveau: dict[str, int] = field(default_factory=dict)
    exemples_nouvelles: list[str] = field(default_factory=list)
    envois: dict[str, int] = field(default_factory=lambda: {"alertes": 0, "alertes_en_attente": 0, "resumes": 0,
                                                            "bilans": 0, "pannes": 0})
    suivi: dict[str, object] = field(default_factory=dict)

    def resume(self) -> list[str]:
        lignes = [f"Plan : {', '.join(self.plan['sources']) or 'aucune source due'}"]
        for nom, s in self.sources.items():
            ligne = f"{nom} : {s['etat']}, {s.get('offres', 0)} offres, {s.get('requetes', 0)} requêtes"
            if s.get("erreur"):
                ligne += f" ({s['erreur']})"
            elif s.get("erreurs_partielles"):
                ligne += f", {s['erreurs_partielles']} en échec ({'; '.join(s['erreurs'][:2])})"
            lignes.append(ligne)
        lignes.append(f"Brutes {self.brutes}, gardées {self.gardees}, nouvelles {self.nouvelles}")
        lignes.append("Rejets : " + ", ".join(f"{k} {v}" for k, v in sorted(self.rejets_par_motif.items())))
        lignes.append("Fils : " + ", ".join(f"{k} {v}" for k, v in sorted(self.par_fil.items())))
        lignes.append("Familles : " + ", ".join(f"{k} {v}" for k, v in sorted(self.par_famille.items())))
        lignes.append("Employeurs : " + ", ".join(f"{k} {v}" for k, v in sorted(self.par_type_employeur.items())))
        lignes.append("Niveaux (nouvelles) : " + ", ".join(f"{k} {v}" for k, v in sorted(self.par_niveau.items())))
        lignes.append("Envois : " + ", ".join(f"{k} {v}" for k, v in self.envois.items()))
        if self.suivi:
            lignes.append("Suivi : " + ", ".join(f"{k} {v}" for k, v in self.suivi.items()))
        return lignes


def collecter(noms: list[str], config: Config, base: stockage.Base, session, maintenant_utc: datetime,
              rapport: Rapport, sources: dict = SOURCES) -> list[Offre]:
    """Interroge chaque source isolément. Une source en échec n'arrête pas le passage."""
    toutes: list[Offre] = []
    for nom in noms:
        fetch = sources.get(nom)
        if fetch is None:
            rapport.sources[nom] = {"etat": "inconnue"}
            continue
        ctx = Contexte(config=config, session=session, maintenant_utc=maintenant_utc,
                       memoire=stockage.lire_memoire(base, nom))
        ident = stockage.debut_execution(base, nom, maintenant_utc)
        try:
            offres = fetch(ctx)
        except SourceIndisponible as e:
            stockage.fin_execution(base, ident, False, 0, ctx.requetes, str(e))
            rapport.sources[nom] = {"etat": "indisponible", "requetes": ctx.requetes, "erreur": str(e)}
            logger.warning("%s", e)
            continue
        except Exception as e:  # dernière ligne de défense : une source ne casse pas le passage
            stockage.fin_execution(base, ident, False, 0, ctx.requetes, f"{e.__class__.__name__}: {e}")
            rapport.sources[nom] = {"etat": "erreur", "requetes": ctx.requetes, "erreur": e.__class__.__name__}
            logger.exception("Source %s en erreur", nom)
            continue
        stockage.fin_execution(base, ident, True, len(offres), ctx.requetes,
                               "; ".join(ctx.erreurs[:3]) if ctx.erreurs else None)
        if ctx.memoire:
            stockage.ecrire_memoire(base, nom, ctx.memoire, maintenant_utc)
        rapport.sources[nom] = {"etat": "ok", "offres": len(offres), "requetes": ctx.requetes,
                                "erreurs_partielles": len(ctx.erreurs), "erreurs": ctx.erreurs[:5]}
        toutes.extend(offres)
    return toutes


REPUBLICATION_JOURS = 30
REPRISE_JOURS = 2   # mise en service : offres de la période de test reprises dans les vrais envois


def passage(config: Config, base: stockage.Base, maintenant_utc: datetime | None = None,
            sources_imposees: list[str] | None = None, session=None, sources: dict = SOURCES,
            verdicts: dict[str, str] | None = None, telegram: Telegram | None = None,
            sources_exclues: list[str] | None = None, suivi: Suivi | None = None) -> Rapport:
    """Un passage : collecte des sources dues, tri, note, enregistrement, puis envois dus.

    `sources_imposees` ignore le planning (essais). `sources_exclues` retire des sources après
    planification (mode ombre : Adzuna, dont le quota est partagé avec la v1).
    """
    maintenant_utc = maintenant_utc or stockage.maintenant_utc()
    plan = planning.taches_dues(maintenant_utc, stockage.dernier_succes(base), stockage.derniers_envois(base),
                                stockage.requetes_du_mois(base, "adzuna", maintenant_utc), config)
    noms = sources_imposees if sources_imposees is not None else plan.sources
    noms = [n for n in noms if n not in (sources_exclues or [])]
    rapport = Rapport(debut=maintenant_utc.isoformat(), plan={"sources": noms, "raisons": plan.raisons,
                                                               "hors_plage": plan.hors_plage})
    if suivi is not None and verdicts is None and not plan.hors_plage:
        try:
            verdicts = suivi.verdicts()
            rapport.suivi["verdicts_lus"] = len(verdicts)
        except ErreurSheets as ex:
            rapport.suivi["erreur_verdicts"] = str(ex)[:200]
            logger.warning("Verdicts du suivi illisibles, note calculée sans eux : %s", ex)
    if noms:
        _collecter_et_noter(noms, config, base, session, maintenant_utc, rapport, sources, verdicts)
    else:
        logger.info("Aucune source due : %s", plan.raisons)
    if telegram is not None and not plan.hors_plage:
        envoyer(base, config, plan, telegram, maintenant_utc, rapport)
    if suivi is not None and not plan.hors_plage:
        synchroniser_suivi(base, config, suivi, verdicts or {}, maintenant_utc, rapport)
    return rapport


def synchroniser_suivi(base: stockage.Base, config: Config, suivi: Suivi, verdicts: dict[str, str],
                       maintenant_utc: datetime, rapport: Rapport) -> None:
    """Transfert des offres retenues, ajout des nouvelles à l'onglet Veille, cibles Route B.

    Chaque étape est isolée : un échec Google Sheets n'empêche ni les autres étapes ni le
    passage suivant, qui reprend ce qui n'a pas été écrit (l'état est en base).
    """
    local = maintenant_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(config.planning.fuseau))
    try:
        rapport.suivi.update(suivi.transferer_retenues(local))
    except ErreurSheets as ex:
        rapport.suivi["erreur_transfert"] = str(ex)[:200]
    try:
        # Mise en service : le vrai onglet reprend les offres des deux derniers jours de test.
        depuis = maintenant_utc - timedelta(days=REPRISE_JOURS) if suivi.mode == "reel" else None
        offres = stockage.a_ajouter_veille(base, suivi.mode, depuis)
        n = suivi.ajouter_a_veille(offres, local)
        stockage.marquer_veille(base, [o["cle"] for o in offres], maintenant_utc, suivi.mode)
        rapport.suivi["ajoutees_veille"] = n
    except ErreurSheets as ex:
        rapport.suivi["erreur_veille"] = str(ex)[:200]
    try:
        debut_jour = (local.replace(hour=0, minute=0, second=0, microsecond=0)).astimezone(UTC).replace(tzinfo=None)
        restant = ROUTE_B_PAR_JOUR - stockage.route_b_ajoutees_depuis(base, debut_jour)
        if restant > 0:
            choisies = suivi.cibles_route_b(stockage.candidats_route_b(base, maintenant_utc - timedelta(hours=2)),
                                            stockage.route_b_connues(base), verdicts, restant)
            suivi.ajouter_route_b([ligne for _, ligne in choisies])
            for nom, _ in choisies:
                stockage.ajouter_route_b(base, nom, maintenant_utc)
            rapport.suivi["cibles_route_b"] = len(choisies)
    except ErreurSheets as ex:
        rapport.suivi["erreur_route_b"] = str(ex)[:200]


def _collecter_et_noter(noms, config, base, session, maintenant_utc, rapport, sources, verdicts) -> None:
    brutes = collecter(noms, config, base, session or build_session(), maintenant_utc, rapport, sources)
    aujourdhui = maintenant_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(config.planning.fuseau)).date()
    gardees, rejets = filtres.trier(brutes, config, aujourdhui)
    fusionnees = dedoublonnage.fusionner(gardees)
    vues = stockage.dernieres_vues(base, [o.cle for o in fusionnees])
    nouvelles, notes = [], {}
    for o in fusionnees:
        derniere = vues.get(o.cle)
        republiee = derniere is not None and (maintenant_utc - derniere).days >= REPUBLICATION_JOURS
        if derniere is None or republiee:
            nouvelles.append(o)
        note = notation.noter(o, config, aujourdhui, verdicts, republiee=republiee)
        notes[o.cle] = (note, notation.niveau(o, note, config))

    stockage.enregistrer_offres(base, fusionnees, maintenant_utc)
    for o in nouvelles:
        note, niv = notes[o.cle]
        stockage.noter(base, o.cle, note.total, note.composantes, niv.value)
    stockage.enregistrer_rejets(base, _rejets_uniques(rejets), maintenant_utc)

    rapport.brutes, rapport.gardees, rapport.nouvelles = len(brutes), len(fusionnees), len(nouvelles)
    rapport.rejets_par_motif = dict(collections.Counter(r.motif.value for r in rejets))
    rapport.par_fil = dict(collections.Counter(str(o.fil) for o in fusionnees))
    rapport.par_famille = dict(collections.Counter(o.famille for o in fusionnees))
    rapport.par_type_employeur = dict(collections.Counter(str(o.type_employeur) for o in fusionnees))
    rapport.par_niveau = dict(collections.Counter(notes[o.cle][1].value for o in nouvelles))
    meilleures = sorted(nouvelles, key=lambda o: notes[o.cle][0].total, reverse=True)[:25]
    rapport.exemples_nouvelles = [f"{notes[o.cle][1].value} {notes[o.cle][0].total:+d} [{o.fil}/{o.famille}] {o.titre} · "
                                  f"{o.entreprise} · {o.lieu} ({', '.join(notes[o.cle][0].raisons(2))})" for o in meilleures]
    stockage.purger(base)


def envoyer(base: stockage.Base, config: Config, plan: Plan, tg: Telegram, maintenant_utc: datetime,
            rapport: Rapport) -> None:
    """Alertes (dès détection, rejouées si l'envoi a échoué), pannes, résumés, bilan."""
    fait = "envoyee" if tg.mode == "telegram" else "simulee"
    if tg.mode == "telegram":
        # Mise en service : ce qui n'a été que simulé pendant le test récent est envoyé pour de vrai.
        rapport.envois["reprises"] = stockage.reprendre_simulations(base, maintenant_utc - timedelta(days=REPRISE_JOURS))
    for o in stockage.alertes_a_envoyer(base):
        ok = tg.envoyer(tgm.message_alerte(o), o["fil"])
        stockage.marquer(base, [o["cle"]], fait if ok else "en_attente", maintenant_utc)
        rapport.envois["alertes" if ok else "alertes_en_attente"] += 1

    seuil = config.telegram.pannes_avant_avertissement
    for nom, s in rapport.sources.items():
        if s.get("etat") != "ok" and stockage.echecs_consecutifs(base, nom) == seuil:
            tg.envoyer(tgm.message_panne(nom, seuil, stockage.derniere_erreur(base, nom)))
            rapport.envois["pannes"] += 1

    jour = maintenant_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(config.planning.fuseau)).date()
    if plan.resume_quotidien:
        for fil in ("emploi", "alternance"):
            offres = stockage.a_resumer(base, fil)
            messages = tgm.messages_resume(fil, offres, jour, config.telegram.resume_max_offres)
            if all(tg.envoyer(m, fil) for m in messages):
                stockage.marquer(base, [o["cle"] for o in offres], fait, maintenant_utc)
                stockage.enregistrer_envoi(base, "resume", fil, maintenant_utc)
                rapport.envois["resumes"] += 1

    if plan.bilan_hebdomadaire:
        debut = maintenant_utc - timedelta(days=7)
        stats = stockage.stats_periode(base, debut, maintenant_utc)
        stats.update(du=tgm.date_fr(debut.date()), au=tgm.date_fr(jour),
                     adzuna_mois=stockage.requetes_du_mois(base, "adzuna", maintenant_utc),
                     adzuna_plafond=config.planning.quotas.adzuna_mensuel)
        if tg.envoyer(tgm.message_bilan(stats)):
            stockage.enregistrer_envoi(base, "bilan", None, maintenant_utc)
            rapport.envois["bilans"] += 1


def _rejets_uniques(rejets: list[Rejet]) -> list[Rejet]:
    vus: dict[tuple[str, str], Rejet] = {}
    for r in rejets:
        vus.setdefault((r.offre.cle, r.motif.value), r)
    return list(vus.values())


def _annotation(titre: str, lignes: list[str]) -> None:
    corps = "\n".join(lignes)[:6000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::notice title={titre}::{corps}", flush=True)


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.DEBUG if os.getenv("VERBOSE") == "1" else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)
    config = charger()
    base = stockage.ouvrir(os.getenv("VEILLE_BASE", "data/veille_v2.sqlite"))
    imposees = [s.strip() for s in os.getenv("VEILLE_SOURCES", "").split(",") if s.strip()] or None
    exclues = [s.strip() for s in os.getenv("VEILLE_SOURCES_EXCLUES", "").split(",") if s.strip()]
    # Par sécurité, rien n'est envoyé sauf demande explicite (VEILLE_ENVOI=telegram).
    mode = "telegram" if os.getenv("VEILLE_ENVOI") == "telegram" else "simulation"
    tg = Telegram(build_session(), os.getenv("TELEGRAM_BOT_TOKEN"), config.telegram.groupe_id,
                  config.telegram.sujets, mode=mode)
    # Essais seulement : rejouer un passage à une heure donnée (UTC, ISO 8601), pour vérifier
    # résumés et bilans hors des heures où ils sont dus.
    force = os.getenv("VEILLE_MAINTENANT")
    quand = datetime.fromisoformat(force) if force else None
    # Fichier de suivi : « reel », « essai » (onglets séparés, rien de modifié) ou rien.
    mode_suivi = os.getenv("VEILLE_SUIVI", "aucun")
    suivi = None
    if mode_suivi in ("reel", "essai"):
        try:
            suivi = Suivi(ClientSheets.depuis_env(), mode=mode_suivi)
        except Exception as ex:  # jeton expiré ou absent : la veille continue sans le fichier de suivi
            logger.error("Fichier de suivi inaccessible (%s) : passage sans lui", ex.__class__.__name__)
    rapport = passage(config, base, maintenant_utc=quand, sources_imposees=imposees, telegram=tg,
                      sources_exclues=exclues, suivi=suivi)
    chemin = Path(os.getenv("VEILLE_RAPPORT", "data/rapport_passage.json"))
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
    for ligne in rapport.resume():
        logger.info(ligne)
    if os.getenv("GITHUB_ACTIONS") == "true":
        _annotation("Passage v2", rapport.resume())
        _annotation("Nouvelles offres (extrait)", rapport.exemples_nouvelles or ["aucune"])
        if mode == "simulation" and tg.envoyes:
            _annotation("Messages simulés (extrait)", [f"[{fil or 'général'}] {texte[:300]}" for fil, texte in tg.envoyes[:12]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
