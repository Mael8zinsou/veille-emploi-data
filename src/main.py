"""
Point d'entrée du pipeline de veille.

Orchestration :
    sources actives → filtrage profil → dédoublonnage/fusion → scoring (saturation)
    → filtre "déjà vu" (SQLite) → marquage → notification Telegram (top N) → prune.

Aucune source défaillante ne doit casser le pipeline (critère d'acceptation #5) :
chaque fetch est isolé dans un try/except.

Lancement : `python -m src.main`
Env : ADZUNA_*, FT_*, TELEGRAM_* (+ DRY_RUN=1 pour ne pas envoyer, VERBOSE=1 pour DEBUG).
"""
import locale
import logging
import os
from datetime import datetime
from pathlib import Path

from src import storage
from src.config import load_config
from src.notif_telegram import (
    construire_messages,
    envoyer_messages,
    message_jour_vide,
)
from src.scoring import dedoublonne_et_fusionne, filtre_par_profil, score_toutes
from src.sources import (
    adzuna,
    ashby,
    choose,
    france_travail,
    greenhouse,
    hellowork,
    lever,
)
from src.utils.http import build_session

CONFIG_PATH = "config/profil.yaml"
DB_PATH = "data/offres.sqlite"
LOG_PATH = "data/pipeline.log"

logger = logging.getLogger("veille")

# Nom du module source -> fonction fetch. L'ordre n'a pas d'importance fonctionnelle.
SOURCES = {
    "adzuna": adzuna.fetch,
    "france_travail": france_travail.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "hellowork": hellowork.fetch,
    "choose": choose.fetch,
}


def _setup_logging() -> None:
    """Logs vers stdout ET data/pipeline.log, ISO timestamps. DEBUG si VERBOSE=1."""
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    niveau = logging.DEBUG if os.getenv("VERBOSE") == "1" else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    handlers = [logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    logging.basicConfig(level=niveau, format=fmt, datefmt="%Y-%m-%dT%H:%M:%S", handlers=handlers)


def _date_fr() -> str:
    """Date du jour façon '10 juin'. Locale FR si dispo, sinon fallback anglais."""
    for loc in ("fr_FR.UTF-8", "fr_FR", "French_France"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            break
        except locale.Error:
            continue
    try:
        return datetime.now().strftime("%-d %B")
    except ValueError:
        # %-d non supporté sous Windows : on retombe sur %d.
        return datetime.now().strftime("%d %B").lstrip("0")


def _sources_actives(config) -> list[tuple[str, callable]]:
    """Liste (nom, fetch) des sources activées dans profil.yaml."""
    actives = vars(config.sources_actives)
    return [(nom, fn) for nom, fn in SOURCES.items() if actives.get(nom, False)]


def run() -> int:
    """Exécute le pipeline complet. Retourne le nombre d'offres notifiées."""
    config = load_config(CONFIG_PATH)
    storage.init_db(DB_PATH)
    session = build_session()

    # 1. Collecte multi-source, chaque source isolée.
    toutes = []
    for nom, fetch_fn in _sources_actives(config):
        try:
            offres = fetch_fn(config, session)
            logger.info("Source %s : %d offres", nom, len(offres))
            toutes.extend(offres)
        except Exception as e:
            logger.error("Source %s a échoué (ignorée) : %s", nom, e)
            continue
    logger.info("Total brut : %d offres", len(toutes))

    # 2. Filtrage profil.
    filtrees = filtre_par_profil(toutes, config)
    logger.info("Après filtres profil : %d", len(filtrees))

    # 3. Dédoublonnage + fusion cross-source.
    fusionnees = dedoublonne_et_fusionne(filtrees)
    logger.info("Après dédoublonnage : %d", len(fusionnees))

    # 4. Scoring (saturation incluse).
    scorees = score_toutes(fusionnees, config)

    # 5. Filtre "déjà vues" AVANT de marquer.
    nouvelles = [o for o in scorees if not storage.is_already_seen(o.cle_unique)]
    logger.info("Nouvelles offres : %d", len(nouvelles))

    # 6. Marque toutes les offres vues (nouvelles ET revues -> rafraîchit date_derniere_vue).
    for o in scorees:
        storage.mark_seen(o)

    # 7. Sélection à notifier : score >= seuil, top N.
    seuil = config.telegram.score_minimum
    top_n = config.telegram.top_n_par_jour
    a_notifier = sorted(
        (o for o in nouvelles if o.score >= seuil),
        key=lambda o: o.score, reverse=True,
    )[:top_n]
    logger.info("À notifier (score>=%d, top %d) : %d", seuil, top_n, len(a_notifier))

    # 8. Notification.
    date_str = _date_fr()
    if a_notifier:
        messages = construire_messages(a_notifier, total_scanne=len(toutes), date_str=date_str)
        if envoyer_messages(messages, session):
            for o in a_notifier:
                storage.mark_notified(o.cle_unique)
            logger.info("Notification envoyée (%d offres).", len(a_notifier))
        else:
            logger.error("Échec de notification : offres non marquées notifiées.")
    else:
        envoyer_messages([message_jour_vide(total_scanne=len(toutes), date_str=date_str)], session)
        logger.info("Aucune offre à notifier aujourd'hui.")

    # 9. Entretien : purge des entrées trop anciennes.
    supprimees = storage.prune_old(days=90)
    if supprimees:
        logger.info("Prune : %d entrées anciennes supprimées.", supprimees)

    logger.info("Pipeline terminé.")
    return len(a_notifier)


def main() -> None:
    # Charge un éventuel .env local (no-op sur GitHub Actions où il n'existe pas ;
    # les variables déjà présentes dans l'environnement ne sont pas écrasées).
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    _setup_logging()
    try:
        run()
    except Exception as e:
        logger.exception("Pipeline interrompu par une erreur fatale : %s", e)
        raise


if __name__ == "__main__":
    main()
