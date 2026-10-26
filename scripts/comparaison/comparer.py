"""Compare la v1 et la v2 sur les mêmes offres (aucun envoi, aucune écriture en production).

Entrées : le fichier produit par v1_a_blanc.py, et un passage v2 sur les vraies sources.
Questions posées :
1. Parmi les offres que la v1 juge notifiables (note >= seuil), lesquelles la v2 écarte-t-elle,
   et pour quel motif ? (régression de filtrage)
2. Les requêtes de la v2 retrouvent-elles ces offres ? (régression de collecte)
3. Qu'apporte la v2 que la v1 ne voit pas ?

Sortie : annotations GitHub et un CSV détaillé dans COMPARAISON_DIR.
"""
from __future__ import annotations

import collections
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import dedoublonnage, filtres, main, stockage  # noqa: E402
from src.config import charger  # noqa: E402
from src.models import Offre  # noqa: E402

SOURCES_V1 = {"Adzuna": "adzuna", "France Travail": "france_travail", "HelloWork": "hellowork", "APEC": "apec"}


def annotation(titre: str, lignes: list[str]) -> None:
    corps = "\n".join(lignes)[:6000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::notice title={titre}::{corps}", flush=True)


def depuis_v1(d: dict) -> Offre:
    return Offre(source=SOURCES_V1.get(d["source"], d["source"].lower()), titre=d["titre"], entreprise=d["entreprise"],
                 lieu=d["localisation"], url=d["url"], description=d["description"], contrat_brut=d["contrat"],
                 date_publication=d["date_publication"], faible_concurrence=d.get("faible_concurrence", False))


def main_comparaison(fichier_v1: str, dossier: str) -> int:
    config = charger()
    sortie = Path(dossier)
    sortie.mkdir(parents=True, exist_ok=True)
    v1 = json.loads(Path(fichier_v1).read_text(encoding="utf-8"))
    maintenant = stockage.maintenant_utc()
    aujourdhui = maintenant.replace(tzinfo=UTC).astimezone(ZoneInfo(config.planning.fuseau)).date()

    # 1. Filtrage v2 appliqué aux offres de la v1.
    notifiables = [d for d in v1["offres"] if d["notifiable"]]
    lignes_csv, motifs = [], collections.Counter()
    offres_v1 = []
    for d in notifiables:
        o = filtres.normaliser_offre(depuis_v1(d), config)
        r = filtres.motif_de_rejet(o, config, aujourdhui)
        motif = r[0].value if r else "gardee"
        motifs[motif] += 1
        offres_v1.append((d, o, r))

    # 2. Passage v2 réel, base jetable : quelles offres la v2 collecte-t-elle elle-même ?
    base = stockage.ouvrir(sortie / "v2_jetable.sqlite")
    brutes: list[Offre] = []
    rapport = main.Rapport(debut=maintenant.isoformat(), plan={})
    brutes = main.collecter(["france_travail", "adzuna", "hellowork"], config, base, main.build_session(),
                            maintenant, rapport)
    gardees_v2, rejets_v2 = filtres.trier(brutes, config, aujourdhui)
    gardees_v2 = dedoublonnage.fusionner(gardees_v2)
    cles_collectees = {o.cle for o in gardees_v2} | {r.offre.cle for r in rejets_v2}

    collecte = collections.Counter()
    for d, o, r in offres_v1:
        trouvee = o.cle in cles_collectees
        collecte["retrouvee" if trouvee else "absente"] += 1
        lignes_csv.append({"verdict_v2": r[0].value if r else "gardee", "detail": r[1] if r else "",
                           "retrouvee_par_v2": trouvee, "note_v1": d["score"], "source_v1": d["source"],
                           "titre": d["titre"], "entreprise": d["entreprise"], "lieu": d["localisation"],
                           "famille_v2": o.famille, "fil_v2": o.fil, "url": d["url"]})

    # 3. Apport de la v2 : offres gardées par la v2 que la v1 ne voit pas du tout.
    cles_v1 = {filtres.normaliser_offre(depuis_v1(d), config).cle for d in v1["offres"]}
    apport = [o for o in gardees_v2 if o.cle not in cles_v1]
    familles_apport = collections.Counter(o.famille for o in apport)

    with (sortie / "v1_notifiables_vues_par_v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes_csv[0]) if lignes_csv else ["vide"])
        w.writeheader()
        w.writerows(lignes_csv)
    with (sortie / "apport_v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fil", "famille", "titre", "entreprise", "lieu", "source", "url"])
        for o in sorted(apport, key=lambda o: (o.priorite, o.famille)):
            w.writerow([o.fil, o.famille, o.titre, o.entreprise, o.lieu, ",".join(o.sources), o.url])
    (sortie / "synthese.json").write_text(json.dumps({
        "date": datetime.now(UTC).isoformat(), "v1_par_source": v1["par_source"], "v1_brutes": v1["brutes"],
        "v1_gardees": len(v1["offres"]), "v1_notifiables": len(notifiables),
        "v1_notifiees_ce_passage": sum(d["serait_notifiee_ce_passage"] for d in v1["offres"]),
        "v2_sur_offres_v1": dict(motifs), "v2_collecte_des_offres_v1": dict(collecte),
        "v2_sources": rapport.sources, "v2_brutes": len(brutes), "v2_gardees": len(gardees_v2),
        "v2_apport": len(apport), "v2_apport_par_famille": dict(familles_apport),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    annotation("Comparaison : volumes", [
        f"v1 : {v1['brutes']} brutes, {len(v1['offres'])} gardées, {len(notifiables)} notifiables (note >= seuil), "
        f"{sum(d['serait_notifiee_ce_passage'] for d in v1['offres'])} seraient envoyées à ce passage",
        "v1 par source : " + ", ".join(f"{k} {v}" for k, v in v1["par_source"].items()),
        f"v2 : {len(brutes)} brutes, {len(gardees_v2)} gardées, dont {len(apport)} que la v1 ne voit pas",
        "Apport v2 par famille : " + ", ".join(f"{k} {v}" for k, v in familles_apport.most_common()),
    ])
    annotation("Comparaison : verdict v2 sur les offres notifiables v1",
               [f"{k} : {v}" for k, v in motifs.most_common()]
               + [f"Retrouvées par les requêtes v2 : {collecte['retrouvee']} / {len(notifiables)}"])
    ecartees = [ligne for ligne in lignes_csv if ligne["verdict_v2"] != "gardee"]
    annotation("Comparaison : notifiables v1 écartées par la v2",
               [f"{ligne['verdict_v2']} ({ligne['detail']}) | {ligne['titre'][:70]} | {ligne['entreprise'][:30]}"
                for ligne in ecartees[:45]] or ["aucune"])
    absentes = [ligne for ligne in lignes_csv if not ligne["retrouvee_par_v2"] and ligne["verdict_v2"] == "gardee"]
    annotation("Comparaison : gardées par la v2 mais non collectées par ses requêtes",
               [f"{ligne['source_v1']} | {ligne['titre'][:70]} | {ligne['entreprise'][:30]}" for ligne in absentes[:45]]
               or ["aucune"])
    return 0


if __name__ == "__main__":
    sys.exit(main_comparaison(sys.argv[1], os.getenv("COMPARAISON_DIR", "comparaison_out")))
