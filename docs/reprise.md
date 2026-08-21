# Reprise de l'outil — état, audit, roadmap

> Point d'entrée pour reprendre le projet après une pause. Lis ce fichier en premier,
> puis [`doc.md`](doc.md) pour la technique et [`CLAUDE.md`](../CLAUDE.md) pour l'historique
> phase par phase. Dernière mise à jour : **2026-08-21**.

---

## 1. En un coup d'œil

- **Statut** : livré, **en production**. Le cron GitHub Actions tourne **chaque matin (6h UTC)
  depuis le 2026-06-12**, notifie sur Telegram, sans intervention.
- **Repo** : `Mael8zinsou/veille-emploi-data` (branche `main`).
- **Secrets configurés** (6) : `ADZUNA_APP_ID/KEY`, `FT_CLIENT_ID/SECRET`, `TELEGRAM_BOT_TOKEN/CHAT_ID`.
- **Tests** : 70 (`pytest -q`).
- **Chantier en cours** : **nettoyage qualité** du flux (voir §4). **Ensuite** : Teamtailor + APEC (§5).

---

## 2. Ce qui a été fait (rappel condensé)

- **Phases 1→6** : fondations, sources core (Adzuna, France Travail, Greenhouse, Lever, Ashby),
  niches (HelloWork scraping, Choose no-op), pipeline (scoring + saturation + notif Telegram),
  automatisation (workflow + cache SQLite), livraison prod. Détail : [`CLAUDE.md`](../CLAUDE.md).
- **Affinage ciblage** (commit `7bbc57d`, 2026-08-21) :
  - `fraicheur_max_jours` 14 → **3** (n'affecte qu'Adzuna/FT, seules à filtrer par date).
  - **Couverture France entière** : `filtre_par_profil` inversé — plus de liste blanche de villes,
    mais une liste d'exclusion de lieux étrangers (`exclusions_localisation`).
  - **Alternance/apprentissage exclus** (ajoutés à `exclusions_titre`, retirés du bonus junior).
  - `top_n_par_jour` 15 → **30**.
- **Outillage d'audit** (commit `4b74459`) : `scripts/audit_stats.py` (lecture seule) +
  `.github/workflows/audit.yml` (manuel). Régénère le rapport quand on veut.

---

## 3. L'audit chiffré (2 mois de prod : 2026-06-12 → 2026-08-21)

Source : run manuel de `audit.yml` sur la base réelle (1303 offres vues, 1069 notifiées).
**C'est le fait le plus important à connaître pour reprendre : le réel contredit la promesse.**

### Constats durs

| Constat | Chiffre | Implication |
|---|---|---|
| **Mix des sources notifiées** | Adzuna **73 %**, FT **18 %**, HelloWork **9 %**, ATS **0,3 %** | L'outil est de fait un **client Adzuna + FT**. |
| **Couche ATS (marché caché)** | **3 offres / 1069** en 2 mois | La premise « marché caché » est **absente**, pas juste faible. |
| **Bruit ESN/conseil/freelance** | **~29 %** des notifs (315), dont **Collective.work = 136** | Un tiers du flux = déchet pour la cible. |
| **Stages notifiés** | **33** | `"stage"`/`"stagiaire"` pas dans `exclusions_titre` → fuite. |
| **Anti-saturation** | **1067/1069 exclusives** | La feature ne se déclenche jamais (sources sans recoupement) → **code mort en pratique**. |
| **Scores** | 916/1069 dans la tranche 5-9, 11 seulement ≥15 | Seuil `score_minimum=5` ne filtre presque rien. |
| **Cap quotidien** | 1069 / ~70 j ≈ **15,3/j** | L'ancien `top_n=15` était atteint **tous les jours** → l'outil envoyait le **max**, pas le meilleur. |

### Ce que l'audit NE peut PAS voir
La table `offres_vues` ne stocke que ce qui a **passé** les filtres. On ne mesure donc **pas**
ce qui a été rejeté → impossible d'évaluer la précision du filtrage (faux négatifs) depuis la base.

### Conséquence directe à garder en tête
Passer `top_n` à 30 **sans** traiter le bruit va ~**doubler** le déchet reçu (assez de volume à
score 5-6 pour remplir 30 slots). Le nettoyage qualité doit précéder ou accompagner ce changement.

---

## 4. Chantier EN COURS — nettoyage qualité (priorité 1)

Objectif : faire remonter de vrais CDI/CDD junior propres, écarter le bruit. Pistes décidées :

1. **Exclure les stages** : ajouter `stage`, `stagiaire` à `exclusions_titre` (config seule).
2. **Liste noire d'entreprises ESN/freelance/agrégateurs** : le malus actuel ne cible que
   `"esn "`, `"société de conseil"`, `"consultant"` (mots), il rate **ALTEN, Sopra, CGI,
   Collective.work, Free-Work, Jobgether, Klanik, Externatic…** (noms propres). Créer un
   mécanisme d'exclusion/malus fort **par nom d'entreprise**. Candidats issus du CSV d'audit.
3. **Reconsidérer `top_n=30`** ou **relever `score_minimum`** une fois le bruit filtré, pour que
   le tri redevienne sélectif (aujourd'hui il ne l'est pas).
4. (Optionnel) **Filtrer positivement le contrat** côté Adzuna/HelloWork (FT le fait déjà via
   `typeContrat`), pour ne garder que CDI/CDD.

> Après chaque changement : `pytest -q`, un `DRY_RUN=1 python -m src.main` pour observer le flux,
> puis relancer `audit.yml` quelques jours plus tard pour mesurer l'effet sur le réel.

---

## 5. Chantier SUIVANT — réanimer le marché caché (priorité 2)

L'audit prouve que c'est nécessaire, pas cosmétique :

1. **Teamtailor** : là où les scale-ups FR ont migré (API publique `{slug}.teamtailor.com/api/v1/...`).
   Nouvel adaptateur `src/sources/teamtailor.py` sur le même contrat `fetch(config, session)`.
2. **Curation de slugs FR** : `slugs_ats.txt` est US/international-skewed. Passer
   `decouvrir_slugs.py` + tri manuel. Ajouter une section Teamtailor au fichier de slugs.
3. **APEC** : board des cadres (un data engineer junior EST cadre). Leake déjà un peu via Adzuna
   (7 offres). Évaluer une source dédiée.
4. **Anti-saturation** : ne redeviendra utile que quand plusieurs sources couvriront les **mêmes**
   offres. Dépend donc de l'élargissement ci-dessus.

---

## 6. Comment reprendre concrètement

```bash
# Sanity
pytest -q                                   # doit passer (70)

# Tester le pipeline sans envoyer (charge .env local si présent)
DRY_RUN=1 python -m src.main

# Relancer l'audit sur la prod (lecture seule, ne touche à rien)
gh workflow run audit.yml --repo Mael8zinsou/veille-emploi-data
gh run download <run_id> --repo Mael8zinsou/veille-emploi-data --dir _audit_dl
#   -> _audit_dl/audit-prod/audit_report.md  + notified_offers.csv

# Rafraîchir les slugs ATS (manuel, hors cron)
python scripts/decouvrir_slugs.py --write
```

- **Config à éditer** (sans toucher au code) : `config/profil.yaml`, `config/slugs_ats.txt`.
- **Réglages via YAML** : voir [`annexe_C_scoring.md`](annexe_C_scoring.md) §C.6.

---

## 7. Points de vigilance opérationnels

- **Cron auto-désactivé** : GitHub désactive un workflow planifié après **~60 jours sans activité**
  sur le repo (commit/push). Un commit périodique suffit à réarmer. (Le dernier push d'août a
  remis le compteur à zéro.)
- **Éviction du cache** : GitHub évince un cache après **~7 jours** sans accès. Le run quotidien
  le maintient chaud ; une longue pause du cron = perte possible de la mémoire « déjà vu » →
  un afflux au redémarrage (non bloquant, se stabilise en 1 jour).
- **Quota Adzuna** : free tier 250 req/mois. Usage actuel ~120/mois (4 requêtes/j). Toute
  pagination Adzuna augmentera ce compteur.
- **Logs non persistés** : `data/pipeline.log` n'est uploadé qu'en cas d'échec. Pour l'historique
  des offres envoyées, la source de vérité est la base (via `audit.yml`) ou le fil Telegram.
- **Encodage Windows** : scripts en sortie ASCII (`[OK]`) ; pipeline en UTF-8 via `PYTHONIOENCODING`.

---

## 8. Fichiers clés

| Fichier | Rôle |
|---|---|
| `src/main.py` | Orchestration du pipeline. |
| `src/scoring.py` | Filtrage profil, dédoublonnage/fusion, scoring + saturation. |
| `src/sources/*.py` | Une source = `fetch(config, session) -> list[Offre]`. |
| `config/profil.yaml` | **Tout le ciblage** (mots-clés, exclusions, scoring, top_n…). |
| `config/slugs_ats.txt` | Slugs ATS interrogés. |
| `scripts/audit_stats.py` | Audit lecture seule de la base. |
| `.github/workflows/veille.yml` | Cron quotidien. |
| `.github/workflows/audit.yml` | Audit manuel. |
| [`doc.md`](doc.md) + annexes A–D | Documentation technique. |
