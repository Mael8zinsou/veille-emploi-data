"""Passage de la v1 (code de main) à blanc : collecte, filtres, note, AUCUN envoi.

À lancer depuis le dossier de la v1 (cwd), avec sa base copiée. Écrit la liste des offres
que la v1 aurait notifiées (et les autres offres gardées) dans le fichier passé en argument.
La base n'est lue que pour savoir si une offre est « déjà vue » : rien n'y est écrit.
"""
import json
import logging
import sys
from dataclasses import asdict

from src import storage
from src.config import load_config
from src.main import _sources_actives
from src.scoring import dedoublonne_et_fusionne, filtre_par_profil, score_toutes
from src.utils.http import build_session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", stream=sys.stderr)


def main(sortie: str) -> int:
    config = load_config("config/profil.yaml")
    storage.init_db("data/offres.sqlite")
    session = build_session()
    brutes, par_source = [], {}
    for nom, fetch in _sources_actives(config):
        try:
            offres = fetch(config, session)
        except Exception as e:  # noqa: BLE001
            offres = []
            logging.error("v1 %s : %s", nom, e)
        par_source[nom] = len(offres)
        brutes.extend(offres)
    filtrees = filtre_par_profil(brutes, config)
    scorees = score_toutes(dedoublonne_et_fusionne(filtrees), config)
    seuil, top_n = config.telegram.score_minimum, config.telegram.top_n_par_jour
    lignes = []
    nouvelles = [o for o in scorees if not storage.is_already_seen(o.cle_unique)]
    notifiees = {o.cle_unique for o in sorted((o for o in nouvelles if o.score >= seuil),
                                              key=lambda o: o.score, reverse=True)[:top_n]}
    for o in scorees:
        d = asdict(o)
        d["notifiable"] = o.score >= seuil
        d["deja_vue_v1"] = storage.is_already_seen(o.cle_unique)
        d["serait_notifiee_ce_passage"] = o.cle_unique in notifiees
        lignes.append(d)
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump({"par_source": par_source, "brutes": len(brutes), "filtrees": len(filtrees), "offres": lignes},
                  f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
# relance 2026-10-26T00:17:24
