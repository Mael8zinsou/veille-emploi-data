# CLAUDE.md — Veille emploi Data Engineer (Vague 3)

> Fichier de suivi pour les futures sessions Claude. Lis-le en premier avant de toucher au code.

---

## Contexte du projet

Pipeline autonome de veille d'offres Data Engineer junior, déclenché chaque matin sur GitHub Actions, qui agrège plusieurs sources (Adzuna, France Travail, ATS Greenhouse/Lever/Ashby, plateformes FR niches) et notifie l'utilisateur via Telegram.

**Brief complet :** `../Mail_track_AI/brief_vague3.md` (côté repo Mail_track_AI, gardé en archive de référence). Toutes les décisions de design y sont consignées — ne pas redécider seul.

**Utilisateur :** Maël Mike ZINSOU, étudiant Mastère Data Engineer YNOV, alternant DIRCOFI IDF jusqu'en septembre 2026. Cherche premier CDI ou alternance septembre 2026, profil junior.

**Vague 3 = ce dépôt.** Les vagues 1 et 2 sont livrées :
- Vague 1 : `lance_recherches.py` (côté Mail_track_AI) — packs de requêtes Google ciblant les ATS.
- Vague 2 : `veille_emploi.py` (côté Mail_track_AI) — script Adzuna + France Travail validé en live.

---

## Architecture cible (rappel)

```
GitHub Actions cron 7h Paris
  └─▶ main.py
        ├─▶ Sources core : Adzuna, France Travail, Greenhouse, Lever, Ashby
        ├─▶ Sources niches désactivables : HelloWork, Choose
        ├─▶ Agrégation + dédoublonnage cross-source + fusion + scoring (saturation)
        ├─▶ SQLite : filtre "déjà vu" + marque les nouveaux
        └─▶ Telegram : top N (par défaut 15) avec score ≥ 5
```

**Décisions clés** :
- Une dataclass `Offre` partagée par toutes les sources.
- `cle_unique` = SHA256(entreprise normalisée + 50 premiers caractères du titre normalisé), 16 chars. Volontairement tolérant aux variations mineures (accents, casse).
- SQLite locale `data/offres.sqlite` persistée entre runs via **GitHub Actions Cache** (pas via commit auto sur branche `data`).
- Pas de scraping de LinkedIn / Indeed / WTTJ (anti-bot + alertes natives déjà configurées par l'utilisateur).
- Pas de génération de lettre, pas d'auto-apply : on alimente, l'utilisateur candidate à la main.

---

## État actuel : PHASE 1 TERMINÉE ET COMMITTÉE (commit `028c9b4`)

### Ce qui est fait

| Fichier | État | Note |
|---|---|---|
| Structure de dossiers complète | ✅ | Conforme au brief §3.1 |
| `requirements.txt` | ✅ | requests, pyyaml, python-dotenv, pytest (pas encore versions figées pour Telegram/etc.) |
| `.gitignore` + `.env.example` | ✅ | `.env` exclu, `.env.example` versionné |
| `config/profil.yaml` | ✅ | Toutes les sections du brief §4.1 |
| `config/slugs_ats.txt` | ⚠️ vide | À peupler en Phase 2 (~100-200 slugs FR) |
| `src/models.py` | ✅ | Dataclass `Offre` + `compute_cle_unique` |
| `src/config.py` | ✅ | `load_config` (YAML → SimpleNamespace) + `load_slugs` |
| `src/storage.py` | ✅ | SQLite : init_db, is_already_seen, mark_seen (UPSERT 2 passes), mark_notified, get_recent_unseen, prune_old |
| `src/utils/http.py` | ✅ | `build_session` (retry exponentiel 3 tentatives, backoff 0.5) + `get_json` |
| `tests/` | ✅ | 15 tests passent (models, config, storage) — vérifié via `pytest -q` |
| `pyproject.toml` | ✅ | Config pytest avec `pythonpath = ["."]` |

### Ce qui reste à faire (par phase du brief §6)

- **Phase 2 — Sources core** : `src/sources/adzuna.py`, `france_travail.py`, `greenhouse.py`, `lever.py`, `ashby.py`. Migrer Adzuna + FT depuis `../Mail_track_AI/veille_emploi.py`. Peupler `config/slugs_ats.txt`.
- **Phase 3 — Sources niches** : `hellowork.py`, `choose.py`. Brief autorise le no-op + TODO si scraping trop fragile.
- **Phase 4 — Pipeline** : `src/scoring.py` (filtres + dédoublonnage cross-source avec fusion + scoring saturation), `src/notif_telegram.py` (Markdown V2 + mode `DRY_RUN`), `src/main.py` (orchestration).
- **Phase 5 — Automatisation** : `.github/workflows/veille.yml` (cron `0 6 * * *` UTC + cache SQLite), `README.md` portfolio-ready.
- **Phase 6 — Livraison** : push GitHub, secrets, premier workflow manuel, activation cron.

---

## Décisions techniques prises sans déranger l'utilisateur (à connaître)

1. **`pyproject.toml` minimal** pour la config pytest (plutôt qu'un `conftest.py`) — plus standard.
2. **Storage UPSERT** = `INSERT OR IGNORE` puis `UPDATE` séparé, pas `ON CONFLICT` — compatibilité SQLite < 3.24 sur d'anciens runners.
3. **`_DB_PATH` singleton de module** — simple, suffisant pour ce pipeline mono-thread. Si besoin de tests parallèles, refactor en passant `path` explicitement.
4. **Tests d'idempotence et de fusion de sources** ajoutés (non explicitement demandés par le brief, mais utiles).

---

## Pour reprendre la Phase 2

1. Vérifier que `pytest -q` passe toujours (sanity check).
2. **Migration Adzuna + FT** : lire `../Mail_track_AI/veille_emploi.py`, extraire les fonctions `fetch_adzuna()` et `fetch_france_travail()`, les déplacer dans `src/sources/adzuna.py` et `src/sources/france_travail.py`. Adapter les signatures pour qu'elles prennent `(config, session)` et retournent `list[Offre]`. Ne PAS oublier le correctif `maxCreationDate` déjà appliqué côté V2.
3. **Greenhouse / Lever / Ashby** : implémenter en respectant le pattern résilient (try/except par slug, log + continue).
4. **Peupler `config/slugs_ats.txt`** avec une liste généreuse de slugs FR connus (Doctolib, Alan, Spendesk, Mirakl, PayFit, Qonto, Pigment, Aircall, Algolia, ContentSquare, Datadog, Voodoo, Sorare, Swile, etc.). Mieux vaut 200 dont 30 obsolètes que 50 sûrs.
5. Tester chaque source en isolation (mocks ou intégration légère).
6. Commit `phase 2: sources core` avant de passer à la Phase 3.

---

## Liens vers la mémoire persistante

Voir `~/.claude/projects/<projet-mail-track>/memory/` :
- `project_mailtrack_status.md` — état final du projet Mail Track AI (tags `pipeline-ok-v1` et `batching-ok-v2`).
- `project_sourcing_offres.md` — vague 2 et migration vers vague 3.
- `feedback_verify_external_sites.md` — vérifier les domaines par `curl` avant de recommander un service, pas se fier à WebSearch.

---

## Points de vigilance hérités du brief

- **Pas de credentials commit** : `.env`, `*.sqlite`, `data/` ignorés.
- **Rate limits** : Adzuna 250 req/mois, FT 4 req/s, ATS 200ms entre slugs.
- **Logs** : `logging` Python avec ISO timestamps, niveau INFO par défaut, DEBUG si `VERBOSE=1`. Sortir vers `data/pipeline.log` ET stdout.
- **Encoding UTF-8** partout. `locale.setlocale('fr_FR.UTF-8')` pour les dates Telegram, dans un try/except (peut manquer sur Actions).
- **Une source défaillante ne doit jamais casser le pipeline** (critère d'acceptation #5).
