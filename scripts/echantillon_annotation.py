"""Prépare le jeu d'annotation du lot 2 (conception § 10).

1. Un passage v2 réel collecte les offres (aucun envoi).
2. Un échantillon d'environ 150 offres est tiré : des offres gardées, stratifiées par famille de
   métier et par fil, et une vingtaine d'offres rejetées (pour mesurer ce que les filtres font
   perdre).
3. L'échantillon complet (description comprise) est conservé en JSON : l'évaluation rejouera
   la note sur ces offres exactes.
4. Un onglet « Annotation » est créé dans le fichier de suivi. L'avis de la v2 n'y figure pas,
   pour ne pas influencer le jugement. L'onglet n'est jamais écrasé s'il existe déjà.
"""
from __future__ import annotations

import collections
import json
import os
import random
import sys
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import dedoublonnage, filtres, main, stockage  # noqa: E402
from src.config import charger  # noqa: E402
from src.sorties.sheets import ClientSheets  # noqa: E402

GRAINE = 20261026
CIBLE_GARDEES = 130
MINIMUM_PAR_FAMILLE = 8
CIBLE_REJETS = {"seniorite": 8, "metier_hors_cible": 6, "duree_trop_courte": 3, "trop_ancienne": 2, "lieu_etranger": 1}
AVIS = ["je postule", "peut-être", "hors cible"]
ONGLET = "Annotation"


def tirer(gardees, rejets, alea: random.Random) -> list[tuple[object, str]]:
    par_famille = collections.defaultdict(list)
    for o in gardees:
        par_famille[o.famille].append(o)
    total = len(gardees)
    choisies = []
    for _famille, offres in sorted(par_famille.items()):
        offres = sorted(offres, key=lambda o: o.cle)
        alea.shuffle(offres)
        part = max(MINIMUM_PAR_FAMILLE, round(CIBLE_GARDEES * len(offres) / total))
        choisies += [(o, "gardee") for o in offres[:part]]
    par_motif = collections.defaultdict(list)
    for r in rejets:
        par_motif[r.motif.value].append(r)
    for motif, n in CIBLE_REJETS.items():
        lot = sorted(par_motif.get(motif, []), key=lambda r: r.offre.cle)
        alea.shuffle(lot)
        choisies += [(r.offre, f"rejet:{motif}:{r.detail}") for r in lot[:n]]
    alea.shuffle(choisies)
    return choisies


def main_echantillon(dossier: str) -> int:
    config = charger()
    sortie = Path(dossier)
    sortie.mkdir(parents=True, exist_ok=True)
    maintenant = stockage.maintenant_utc()
    aujourdhui = maintenant.replace(tzinfo=UTC).astimezone(ZoneInfo(config.planning.fuseau)).date()
    base = stockage.ouvrir(sortie / "jetable.sqlite")
    rapport = main.Rapport(debut=maintenant.isoformat(), plan={})
    noms = [n.strip() for n in os.getenv("VEILLE_SOURCES", "france_travail,adzuna,hellowork").split(",") if n.strip()]
    brutes = main.collecter(noms, config, base, main.build_session(), maintenant, rapport)
    gardees, rejets = filtres.trier(brutes, config, aujourdhui)
    gardees = dedoublonnage.fusionner(gardees)
    rejets = list({(r.offre.cle, r.motif): r for r in rejets}.values())

    echantillon = tirer(gardees, rejets, random.Random(GRAINE))
    lignes = [["N°", "Titre", "Entreprise", "Lieu", "Contrat", "Source", "Lien", "Ton avis", "Commentaire", "Clé"]]
    enregistrement = []
    for i, (o, verdict) in enumerate(echantillon, start=1):
        lignes.append([i, o.titre, o.entreprise or "(non indiqué)", o.lieu, o.contrat_brut or "", o.source, o.url, "", "", o.cle])
        enregistrement.append({"numero": i, "verdict_v2": verdict, "offre": asdict(o)})
    (sortie / "echantillon_annotation.json").write_text(
        json.dumps({"date": maintenant.isoformat(), "graine": GRAINE, "sources": rapport.sources,
                    "offres": enregistrement}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    composition = collections.Counter(v.split(":")[0] if v.startswith("rejet") else "gardee" for _, v in echantillon)
    familles = collections.Counter(o.famille for o, v in echantillon if v == "gardee")
    volumes = ", ".join(f"{k} {v.get('offres', 0)}" for k, v in rapport.sources.items())
    print(f"::notice title=Échantillon::{len(echantillon)} offres : {dict(composition)} ; familles {dict(familles)} ; "
          f"sources {volumes}", flush=True)

    client = ClientSheets.depuis_env()
    client.ajouter_onglet(ONGLET, lignes, colonnes_masquees=(9,), liste_deroulante=(7, AVIS),
                          largeurs={0: 45, 1: 380, 2: 200, 3: 170, 4: 110, 5: 100, 6: 120, 7: 120, 8: 260})
    print(f"::notice title=Onglet Annotation::{len(echantillon)} offres écrites dans l'onglet « {ONGLET} »", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main_echantillon(os.getenv("SONDE_DIR", "annotation_out")))
