"""
Audit lecture seule de la base de prod (data/offres.sqlite).

Ne modifie RIEN, n'envoie AUCUNE notification : ouvre la base en lecture, calcule
des statistiques sur l'historique des offres vues/notifiées, et écrit :
  - data/audit_report.md   (rapport lisible)
  - data/notified_offers.csv (offres notifiées, triées par score décroissant)

Lancé par le workflow .github/workflows/audit.yml (manuel), après restauration du
cache SQLite. Peut aussi tourner en local si data/offres.sqlite existe.

Limite importante : la table `offres_vues` ne stocke QUE les offres ayant passé les
filtres (une ligne par offre unique). On mesure donc ce qui est PASSÉ, pas ce qui a
été rejeté — impossible d'évaluer la précision du filtrage à partir de cette base.
"""
import csv
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

DB_PATH = "data/offres.sqlite"
REPORT_PATH = "data/audit_report.md"
CSV_PATH = "data/notified_offers.csv"


def _rows(conn):
    cur = conn.execute(
        "SELECT cle_unique, titre, entreprise, url, score, "
        "date_premiere_vue, date_derniere_vue, sources, notifiee "
        "FROM offres_vues"
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _score_buckets(scores):
    buckets = Counter()
    for s in scores:
        if s < 0:
            buckets["< 0"] += 1
        elif s < 5:
            buckets["0-4"] += 1
        elif s < 10:
            buckets["5-9"] += 1
        elif s < 15:
            buckets["10-14"] += 1
        elif s < 20:
            buckets["15-19"] += 1
        else:
            buckets["20+"] += 1
    order = ["< 0", "0-4", "5-9", "10-14", "15-19", "20+"]
    return [(k, buckets.get(k, 0)) for k in order if buckets.get(k, 0)]


def _sources_of(row):
    return [s.strip() for s in (row["sources"] or "").split(",") if s.strip()]


def _fmt_counter(counter, total=None, top=None):
    items = counter.most_common(top)
    lines = []
    for k, v in items:
        pct = f" ({100 * v / total:.0f}%)" if total else ""
        lines.append(f"| {k} | {v}{pct} |")
    return "\n".join(lines)


def build_report(rows) -> str:
    total = len(rows)
    notified = [r for r in rows if r["notifiee"]]
    n_notif = len(notified)

    dates = sorted(r["date_premiere_vue"][:10] for r in rows if r["date_premiere_vue"])
    date_min = dates[0] if dates else "—"
    date_max = (
        max(r["date_derniere_vue"][:10] for r in rows if r["date_derniere_vue"])
        if rows else "—"
    )

    # Mix de sources sur les offres NOTIFIÉES (une offre peut cumuler des sources).
    src_notif = Counter()
    sat_notif = Counter()  # distribution nb_sources observée (saturation réelle)
    for r in notified:
        srcs = _sources_of(r)
        for s in srcs:
            src_notif[s] += 1
        n = len(srcs) or 1
        sat_notif["1 (exclusif)" if n == 1 else ("2-3" if n <= 3 else "4+")] += 1

    # Mix de sources sur TOUT l'historique.
    src_all = Counter()
    for r in rows:
        for s in _sources_of(r):
            src_all[s] += 1

    scores_all = [r["score"] for r in rows]
    scores_notif = [r["score"] for r in notified]

    # Hygiène : fuites de titres hors cible parmi les NOTIFIÉES.
    def _contains(rows_, needle):
        return sum(1 for r in rows_ if needle in (r["titre"] or "").lower())
    leaks = {
        "alternance": _contains(notified, "alternance") + _contains(notified, "alternant"),
        "apprenti": _contains(notified, "apprenti"),
        "stage/stagiaire": _contains(notified, "stage") + _contains(notified, "stagiaire"),
        "senior": _contains(notified, "senior"),
    }

    # Top entreprises parmi les notifiées.
    ent_notif = Counter(r["entreprise"] for r in notified)

    # Offres notifiées par mois (date_premiere_vue).
    par_mois = Counter(r["date_premiere_vue"][:7] for r in notified if r["date_premiere_vue"])

    def stat_line(scores):
        if not scores:
            return "aucune donnée"
        return (f"min {min(scores)}, médiane {statistics.median(scores):.0f}, "
                f"moyenne {statistics.mean(scores):.1f}, max {max(scores)}")

    L = []
    L.append("# Audit chiffré — base de prod\n")
    L.append(f"Période couverte : **{date_min} → {date_max}**\n")
    L.append("## 1. Volumétrie\n")
    L.append("| Mesure | Valeur |")
    L.append("|---|---|")
    L.append(f"| Offres uniques vues (total historique) | {total} |")
    L.append(f"| Offres notifiées (envoyées sur Telegram) | {n_notif} |")
    ratio = f"{100 * n_notif / total:.1f}%" if total else "—"
    L.append(f"| Taux de notification | {ratio} |")
    L.append("")

    L.append("## 2. Mix des sources — offres NOTIFIÉES\n")
    L.append("_Une offre peut cumuler plusieurs sources (dédoublonnage cross-source)._\n")
    L.append("| Source | Offres notifiées où présente |")
    L.append("|---|---|")
    L.append(_fmt_counter(src_notif, total=n_notif))
    L.append("")

    L.append("## 3. Saturation réellement observée (offres notifiées)\n")
    L.append("| Nb de sources | Offres |")
    L.append("|---|---|")
    for k in ("1 (exclusif)", "2-3", "4+"):
        if sat_notif.get(k):
            L.append(f"| {k} | {sat_notif[k]} |")
    L.append("")

    L.append("## 4. Distribution des scores\n")
    L.append(f"- **Toutes offres vues** : {stat_line(scores_all)}")
    L.append(f"- **Offres notifiées** : {stat_line(scores_notif)}\n")
    L.append("| Tranche de score | Notifiées |")
    L.append("|---|---|")
    for k, v in _score_buckets(scores_notif):
        L.append(f"| {k} | {v} |")
    L.append("")

    L.append("## 5. Hygiène du ciblage — titres hors cible parmi les NOTIFIÉES\n")
    L.append("_Détecte d'éventuelles fuites (dont l'historique d'avant les correctifs)._\n")
    L.append("| Motif | Occurrences |")
    L.append("|---|---|")
    for k, v in leaks.items():
        L.append(f"| {k} | {v} |")
    L.append("")

    L.append("## 6. Top entreprises (offres notifiées)\n")
    L.append("_Rappel : les sources ATS utilisent le slug comme nom d'entreprise._\n")
    L.append("| Entreprise | Offres notifiées |")
    L.append("|---|---|")
    L.append(_fmt_counter(ent_notif, top=20))
    L.append("")

    L.append("## 7. Offres notifiées par mois\n")
    L.append("| Mois | Notifiées |")
    L.append("|---|---|")
    for mois in sorted(par_mois):
        L.append(f"| {mois} | {par_mois[mois]} |")
    L.append("")

    L.append("## 8. Mix des sources — tout l'historique vu\n")
    L.append("| Source | Offres où présente |")
    L.append("|---|---|")
    L.append(_fmt_counter(src_all, total=total))
    L.append("")

    return "\n".join(L)


def write_csv(rows):
    notified = sorted(
        (r for r in rows if r["notifiee"]),
        key=lambda r: r["score"], reverse=True,
    )
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["score", "entreprise", "titre", "sources",
                    "date_premiere_vue", "url"])
        for r in notified:
            w.writerow([r["score"], r["entreprise"], r["titre"], r["sources"],
                        r["date_premiere_vue"], r["url"]])
    return len(notified)


def main() -> int:
    if not Path(DB_PATH).exists():
        print(f"[!] Base introuvable : {DB_PATH} (cache non restauré ?)")
        # On écrit quand même un rapport vide pour que l'artefact existe.
        Path(REPORT_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(REPORT_PATH).write_text(
            "# Audit\n\nAucune base trouvee (cache absent ou vide).\n", encoding="utf-8"
        )
        return 0

    with sqlite3.connect(DB_PATH) as conn:
        rows = _rows(conn)

    report = build_report(rows)
    Path(REPORT_PATH).write_text(report, encoding="utf-8")
    n_csv = write_csv(rows)

    print(f"[OK] {len(rows)} offres analysees, {n_csv} notifiees.")
    print(f"[OK] Rapport : {REPORT_PATH}")
    print(f"[OK] CSV     : {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
