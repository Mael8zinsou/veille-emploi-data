"""Évaluation du tri sur le jeu annoté (conception § 10, critères du cahier des charges § 10).

Entrées :
* `eval/echantillon_*.json` : les offres exactes présentées à l'annotation (données brutes) ;
* les avis de Maël, lus dans l'onglet « Annotation » du fichier de suivi (ou un CSV local) ;
* `eval/incontournables.yaml` : offres qui doivent passer.

Les règles actuelles (config/) sont rejouées sur les données brutes : chaque modification des
règles se mesure sur les mêmes offres. Les métriques agrégées sont publiques (annotations) ; le
détail offre par offre, qui révèle les avis de Maël, part dans un onglet privé du fichier.
"""
from __future__ import annotations

import collections
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from src import filtres  # noqa: E402
from src.config import Config, charger  # noqa: E402
from src.models import Fil, Niveau, Offre  # noqa: E402
from src.notation import niveau, noter  # noqa: E402

POSTULE, PEUT_ETRE, HORS_CIBLE = "je postule", "peut-être", "hors cible"
CHAMPS_BRUTS = {"source", "titre", "entreprise", "lieu", "url", "description", "contrat_brut", "date_publication",
                "id_source", "duree_mois", "experience_annees", "debutant_accepte", "faible_concurrence", "code_rome",
                "diffuseur", "fil_demande"}


def offre_brute(d: dict) -> Offre:
    """Reconstruit l'offre telle que la source l'a rendue : la normalisation sera rejouée."""
    valeurs = {k: v for k, v in d.items() if k in CHAMPS_BRUTS}
    if valeurs.get("fil_demande"):
        valeurs["fil_demande"] = Fil(valeurs["fil_demande"])
    return Offre(**valeurs)


@dataclass
class Resultat:
    numero: int
    avis: str
    offre: Offre
    motif_rejet: str | None
    note: int | None
    niveau: str | None
    raisons: list[str] = field(default_factory=list)


def rejouer(offres: list[tuple[int, Offre]], avis: dict[int, str], config: Config, jour: date) -> list[Resultat]:
    sortie = []
    for numero, o in offres:
        if numero not in avis:
            continue
        o = filtres.normaliser_offre(o, config)
        r = filtres.motif_de_rejet(o, config, jour)
        if r:
            sortie.append(Resultat(numero, avis[numero], o, r[0].value, None, None))
            continue
        n = noter(o, config, jour)
        sortie.append(Resultat(numero, avis[numero], o, None, n.total, niveau(o, n, config).value, n.raisons(3)))
    return sortie


def _part(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def metriques(resultats: list[Resultat]) -> dict:
    postule = [r for r in resultats if r.avis == POSTULE]
    hors = [r for r in resultats if r.avis == HORS_CIBLE]
    alertes = [r for r in resultats if r.niveau == Niveau.ALERTE]
    presentees = [r for r in resultats if r.niveau in (Niveau.ALERTE, Niveau.RESUME)]
    return {
        "annotees": len(resultats),
        "avis": dict(collections.Counter(r.avis for r in resultats)),
        "rappel_filtres": _part(sum(r.motif_rejet is None for r in postule), len(postule)),
        "postule_presentees": _part(sum(r.niveau in (Niveau.ALERTE, Niveau.RESUME) for r in postule), len(postule)),
        "precision_alertes": _part(sum(r.avis == POSTULE for r in alertes), len(alertes)),
        "alertes": len(alertes),
        "presentees": len(presentees),
        "bruit_presente": _part(sum(r.avis == HORS_CIBLE for r in presentees), len(presentees)),
        "hors_cible_ecartees": _part(sum(r.motif_rejet is not None or r.niveau == Niveau.ARCHIVE for r in hors), len(hors)),
    }


def balayer_seuils(resultats: list[Resultat], config: Config, jour: date) -> list[dict]:
    """Mesure chaque couple (seuil d'alerte, seuil de résumé) sur les offres gardées."""
    gardees = [r for r in resultats if r.motif_rejet is None]
    lignes = []
    for s_alerte in range(6, 21):
        for s_resume in range(-5, 11):
            if s_resume > s_alerte:
                continue
            niv = config.notation.niveaux.model_copy(update={
                "alerte": config.notation.niveaux.alerte.model_copy(update={"note_min": s_alerte}),
                "resume": config.notation.niveaux.resume.model_copy(update={"note_min": s_resume})})
            cfg = config.model_copy(update={"notation": config.notation.model_copy(update={"niveaux": niv})})
            essai = [Resultat(r.numero, r.avis, r.offre, None, r.note,
                              niveau(r.offre, noter(r.offre, cfg, jour), cfg).value) for r in gardees]
            m = metriques(essai + [r for r in resultats if r.motif_rejet])
            lignes.append({"alerte": s_alerte, "resume": s_resume, **m})
    return lignes


def incontournables(config: Config, jour: date, chemin: Path = RACINE / "eval" / "incontournables.yaml") -> list[dict]:
    ordre = {Niveau.ARCHIVE: 0, Niveau.RESUME: 1, Niveau.ALERTE: 2}
    sortie = []
    for d in yaml.safe_load(chemin.read_text(encoding="utf-8"))["offres"]:
        o = filtres.normaliser_offre(Offre(source="reference", titre=d["titre"], entreprise=d["entreprise"],
                                           lieu=d["lieu"], url="", contrat_brut=d["contrat_brut"],
                                           description=d.get("competences", "")), config)
        r = filtres.motif_de_rejet(o, config, jour)
        niv = None if r else niveau(o, noter(o, config, jour), config)
        attendu = Niveau.ALERTE if d["attendu"] == "alerte" else Niveau.RESUME
        ok = niv is not None and ordre[niv] >= ordre[attendu]
        sortie.append({"titre": d["titre"], "entreprise": d["entreprise"], "attendu": attendu.value,
                       "obtenu": r[0].value if r else niv.value, "ok": ok})
    return sortie


def _quantiles(valeurs: list[int]) -> str:
    if not valeurs:
        return "aucune"
    v = sorted(valeurs)
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]  # noqa: E731
    return f"n={len(v)}, min {v[0]}, q1 {q(0.25)}, médiane {q(0.5)}, q3 {q(0.75)}, max {v[-1]}"


def diagnostic(resultats: list[Resultat], balayage: list[dict]) -> list[str]:
    """Agrégats seulement (pas de titres) : distribution des notes par avis, motifs de rejet des
    « je postule », composantes les plus fréquentes par avis, et tableau des seuils."""
    lignes = []
    for avis in (POSTULE, PEUT_ETRE, HORS_CIBLE):
        lignes.append(f"Notes « {avis} » : " + _quantiles([r.note for r in resultats if r.avis == avis and r.note is not None]))
    rejets = collections.Counter(r.motif_rejet for r in resultats if r.avis == POSTULE and r.motif_rejet)
    lignes.append("« je postule » rejetées par les filtres : " + (", ".join(f"{k} {v}" for k, v in rejets.items()) or "aucune"))
    for avis in (POSTULE, HORS_CIBLE):
        familles = collections.Counter(r.offre.famille or "?" for r in resultats if r.avis == avis)
        employeurs = collections.Counter(str(r.offre.type_employeur) for r in resultats if r.avis == avis)
        fils = collections.Counter(str(r.offre.fil) for r in resultats if r.avis == avis)
        lignes.append(f"« {avis} » par famille : {dict(familles)} ; employeur : {dict(employeurs)} ; fil : {dict(fils)}")
    lignes.append("Seuils (alerte, résumé) : alertes, précision, « je postule » présentées, présentées, bruit")
    for b in balayage:
        if b["alerte"] in (6, 8, 9, 10, 12) and b["resume"] in (-5, 0, 1, 2, 3, 4):
            lignes.append(f"  {b['alerte']:>2}, {b['resume']:>2} : {b['alertes']}, {b['precision_alertes']}, "
                          f"{b['postule_presentees']}, {b['presentees']}, {b['bruit_presente']}")
    return lignes


def charger_echantillon(chemin: Path) -> tuple[list[tuple[int, Offre]], date]:
    d = json.loads(chemin.read_text(encoding="utf-8"))
    jour = datetime.fromisoformat(d["date"]).date()
    return [(x["numero"], offre_brute(x["offre"])) for x in d["offres"]], jour


def avis_depuis_lignes(lignes: list[list]) -> dict[int, str]:
    """Lignes de l'onglet (en-tête exclu) : N° en colonne A, avis en colonne H."""
    sortie = {}
    for ligne in lignes:
        if len(ligne) > 7 and str(ligne[0]).strip().isdigit() and str(ligne[7]).strip() in (POSTULE, PEUT_ETRE, HORS_CIBLE):
            sortie[int(ligne[0])] = str(ligne[7]).strip()
    return sortie


def _annotation(titre: str, lignes: list[str]) -> None:
    corps = "\n".join(lignes)[:6000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::notice title={titre}::{corps}", flush=True)


def main() -> int:
    config = charger()
    chemin = sorted((RACINE / "eval").glob("echantillon_*.json"))[-1]
    offres, jour = charger_echantillon(chemin)
    client = None
    if os.getenv("AVIS_CSV"):
        with open(os.environ["AVIS_CSV"], encoding="utf-8") as f:
            avis = avis_depuis_lignes(list(csv.reader(f))[1:])
    else:
        from src.sorties.sheets import ClientSheets
        client = ClientSheets.depuis_env()
        avis = avis_depuis_lignes(client.lire("'Annotation'!A2:I400"))
    if not avis:
        _annotation("Évaluation du tri", ["Aucun avis saisi dans l'onglet Annotation pour l'instant : rien à mesurer."])
        return 0
    resultats = rejouer(offres, avis, config, jour)
    m = metriques(resultats)
    balayage = balayer_seuils(resultats, config, jour)
    inc = incontournables(config, jour)

    _annotation("Évaluation du tri", [f"{k} : {v}" for k, v in m.items()])
    _annotation("Incontournables", [f"{'OK' if x['ok'] else 'ÉCHEC'} {x['titre']} ({x['entreprise']}) : "
                                    f"attendu {x['attendu']}, obtenu {x['obtenu']}" for x in inc])
    _annotation("Diagnostic (agrégats, sans titres)", diagnostic(resultats, balayage))
    candidats = [b for b in balayage if (b["precision_alertes"] or 0) >= 0.7 and (b["postule_presentees"] or 0) >= 0.9]
    meilleurs = sorted(candidats, key=lambda b: (-(b["alertes"]), b["bruit_presente"] or 1))[:8]
    _annotation("Seuils qui respectent les critères (précision des alertes >= 70 %, « je postule » présentées >= 90 %)",
                [f"alerte {b['alerte']}, résumé {b['resume']} : {b['alertes']} alertes, précision {b['precision_alertes']}, "
                 f"présentées {b['presentees']}, bruit {b['bruit_presente']}" for b in meilleurs] or ["aucun couple"])
    rapport = RACINE / "eval" / "REPORT.md"
    rapport.write_text("# Évaluation du tri\n\n" + f"Échantillon : `{chemin.name}`, {m['annotees']} offres annotées.\n\n"
                       + "\n".join(f"* {k} : {v}" for k, v in m.items())
                       + "\n\n## Incontournables\n\n" + "\n".join(
                           f"* {'OK' if x['ok'] else 'ÉCHEC'} : {x['titre']} ({x['entreprise']}), attendu {x['attendu']}, "
                           f"obtenu {x['obtenu']}" for x in inc) + "\n", encoding="utf-8")

    if client is not None:
        detail = [["N°", "Ton avis", "Verdict v2", "Note", "Raisons", "Titre", "Entreprise", "Famille", "Fil", "Lien"]]
        for r in sorted(resultats, key=lambda r: r.numero):
            detail.append([r.numero, r.avis, r.motif_rejet or r.niveau, r.note if r.note is not None else "",
                           " ; ".join(r.raisons), r.offre.titre, r.offre.entreprise, r.offre.famille, str(r.offre.fil or ""),
                           r.offre.url])
        titre = f"Évaluation {datetime.now():%d-%m %Hh%M}"
        client.ajouter_onglet(titre, detail, largeurs={4: 300, 5: 340, 6: 180})
        _annotation("Détail", [f"Détail offre par offre dans l'onglet privé « {titre} »"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
