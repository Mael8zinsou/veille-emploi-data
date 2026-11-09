"""Diagnostic du vivier (lecture seule) : d'où viennent les offres présentées, ce qu'il reste
pour la liste du matin, et ce que les filtres écartent. Lancé par audit.yml sur une copie de
la base de production ; n'écrit que data/vivier.md."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src import filtres, liste_matin
from src.config import charger
from src.stockage import _ligne

BASE = "data/offres.sqlite"
PARIS = ZoneInfo("Europe/Paris")


def _sources(v: str | None) -> list[str]:
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else [str(x)]
    except ValueError:
        return [s.strip() for s in (v or "").split(",") if s.strip()]


def main() -> None:
    config = charger()
    c = sqlite3.connect(BASE)
    c.row_factory = sqlite3.Row
    maintenant = datetime.now(UTC)
    il_y_a = lambda j: (maintenant - timedelta(days=j)).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
    out: list[str] = []
    p = out.append

    p("## 1. Offres présentées (alerte ou résumé), par jour de première vue\n")
    p("| Jour | Alertes | Résumés | Emploi | Alternance | Sources |\n|---|---|---|---|---|---|")
    rows = c.execute("SELECT * FROM offres WHERE niveau IN ('alerte','resume') AND premiere_vue >= ?",
                     (il_y_a(10),)).fetchall()
    par_jour: dict[str, list] = {}
    for r in rows:
        jour = datetime.fromisoformat(r["premiere_vue"]).replace(tzinfo=UTC).astimezone(PARIS).date().isoformat()
        par_jour.setdefault(jour, []).append(r)
    for jour in sorted(par_jour):
        rs = par_jour[jour]
        src = Counter(s for r in rs for s in _sources(r["sources"]))
        p(f"| {jour} | {sum(r['niveau'] == 'alerte' for r in rs)} | {sum(r['niveau'] == 'resume' for r in rs)} "
          f"| {sum(r['fil'] == 'emploi' for r in rs)} | {sum(r['fil'] == 'alternance' for r in rs)} | {dict(src)} |")

    lm = config.planning.envois.liste_matin
    cands = [_ligne(r) for r in c.execute(
        "SELECT * FROM offres WHERE niveau IN ('alerte','resume') AND premiere_vue >= ? AND liste_le IS NULL "
        "ORDER BY note DESC", (il_y_a(lm.fenetre_jours),)).fetchall()]
    choix = liste_matin.choisir(cands, set(), maintenant.astimezone(PARIS).date(), 999, lm.fils,
                                exclure_titre=lambda t: filtres.titre_senior(t, config) is not None)
    p(f"\n## 2. Vivier de la prochaine liste ({lm.fenetre_jours} jours, jamais listées)\n")
    p(f"Candidates en base : {len(cands)} ; après règles et une par employeur : {len(choix)}.\n")
    p(f"Verdicts : {dict(Counter(ch.verdict for ch in choix))}")
    p(f"Modes : {dict(Counter(ch.candidature.get('mode', 'inconnu') for ch in choix))}")
    p(f"Notes : {dict(sorted(Counter(min(ch.offre.get('note') or 0, 20) // 3 * 3 for ch in choix).items()))} "
      "(tranches de 3)\n")
    p("| Rang | Note | Verdict | Fil | Source | Entreprise | Poste | Lieu | Écarts |\n|---|---|---|---|---|---|---|---|---|")
    for i, ch in enumerate(choix[:40], 1):
        o = ch.offre
        p(f"| {i} | {o.get('note')} | {ch.verdict} | {o.get('fil')} | {o.get('sources')} | {o.get('entreprise') or ''} "
          f"| {o.get('titre')} | {o.get('lieu') or ''} | {', '.join(ch.ecarts)} |")

    p("\n## 3. Rejets des 7 derniers jours\n")
    for motif, n in c.execute("SELECT motif, COUNT(*) FROM rejets WHERE vu_le >= ? GROUP BY motif ORDER BY 2 DESC",
                              (il_y_a(7),)):
        p(f"* {motif} : {n}")
    for motif, filtre in (("seniorite", ""), ("metier_hors_cible", "AND (lower(titre) LIKE '%data%' OR "
                                                                    "lower(titre) LIKE '%donn%')")):
        p(f"\n### Échantillon « {motif} » {('(titres data)' if filtre else '')}\n")
        for r in c.execute(f"SELECT DISTINCT titre, entreprise, detail FROM rejets WHERE motif = ? AND vu_le >= ? {filtre} "
                           "ORDER BY vu_le DESC LIMIT 40", (motif, il_y_a(7))):
            p(f"* {r['titre']} · {r['entreprise'] or ''} · {r['detail'] or ''}")

    texte = "\n".join(out)
    print(texte)
    with open("data/vivier.md", "w", encoding="utf-8") as f:
        f.write(texte)


if __name__ == "__main__":
    main()
