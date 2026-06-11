# CLAUDE.md — Veille emploi Data Engineer (Vague 3)

> Fichier de suivi pour les futures sessions Claude. Lis-le en premier avant de toucher au code.

---

## Contexte du projet

Pipeline autonome de veille d'offres Data Engineer junior, déclenché chaque matin sur GitHub Actions, qui agrège plusieurs sources (Adzuna, France Travail, ATS Greenhouse/Lever/Ashby, plateformes FR niches) et notifie l'utilisateur via Telegram.

**Brief complet :** `brief_vague3.md` (à la racine de CE repo depuis le commit `087bcc5`, copie versionnée ; l'original reste côté `../Mail_track_AI/`). Toutes les décisions de design y sont consignées — ne pas redécider seul.

**Contrat d'interface des sources** (établi en Phase 2, à respecter en Phase 4) : chaque module `src/sources/<x>.py` expose `fetch(config, session) -> list[Offre]`. `config` = SimpleNamespace (`config.fraicheur_max_jours`, etc.). `session` = `build_session()` de `utils/http`. Credentials API lus dans l'environnement, pas dans le YAML. Les sources ATS lisent elles-mêmes `config/slugs_ats.txt` via `load_slugs`.

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

## État actuel : PHASE 5 TERMINÉE ET COMMITTÉE

> Phase 1 = `028c9b4`. Phase 2 = `087bcc5`. Phase 3 = `9223e2b`. Phase 4 = `2c8ca0e`. Phase 5 (automatisation) = commit après `ec330ff`.

### Ce qui est fait en Phase 5 (automatisation)

| Fichier | État | Note |
|---|---|---|
| `.github/workflows/veille.yml` | ✅ | Cron 6h UTC + `workflow_dispatch`. **Cache SQLite en restore/save séparés avec clé datée** (`veille-db-${run_id}` + `restore-keys: veille-db-`) — une clé fixe ne serait jamais ré-uploadée car le cache GitHub est immuable par clé. `concurrency` pour éviter 2 runs simultanés, `permissions: contents:read`, `DRY_RUN=0`, upload logs si échec |
| `README.md` | ✅ | Portfolio-ready FR : architecture, install, config, sources, automatisation, stack, structure |
| `scripts/decouvrir_slugs.py` | ✅ | Découverte slugs via **DuckDuckGo HTML** (Google trop bloqué). Manuel, hors cron. `--write` pour ajouter au fichier. Validé : remonte de vrais slugs FR neufs |
| `scripts/init_db.py` | ✅ | Init manuelle de la base |
| **Total tests** | ✅ | **69 passent** (inchangé, scripts non testés unitairement — best-effort réseau) |

**Décision cache** : le brief §4.13 proposait une clé `veille-db-${{ github.run_id }}` avec `actions/cache` (action combinée). Problème : l'action combinée ne sauvegarde QUE si la clé n'existe pas, et avec une clé par run elle sauvegarde toujours mais ne restaure jamais l'ancienne sans restore-keys. J'ai donc séparé en `actions/cache/restore` (avec `restore-keys`) + `actions/cache/save` (`if: always()`), pattern fiable pour une DB qui doit persister jour après jour.

**Note Windows** : tous les scripts utilitaires sortent en ASCII (`[OK]` au lieu de `✓`) pour ne pas planter sur la console cp1252. Le pipeline (`main.py`) gère l'UTF-8 via `PYTHONIOENCODING` dans le workflow et le fallback `_print_console` en DRY_RUN.

### Ce qui est fait en Phase 4 (pipeline)

| Fichier | État | Note |
|---|---|---|
| `src/scoring.py` | ✅ | `filtre_par_profil`, `dedoublonne_et_fusionne` (fusion + cumul sources), `score_toutes` (junior+stack, malus ESN, **saturation** : +bonus si exclusif / −malus si ≥4 sources) |
| `src/notif_telegram.py` | ✅ | MarkdownV2 + escaping réservés, découpage <4096 numéroté, message jour vide, `DRY_RUN`. `_print_console` tolère cp1252 Windows |
| `src/main.py` | ✅ | Orchestration, chaque source isolée (try/except), logging stdout+`data/pipeline.log` (DEBUG si `VERBOSE=1`), locale FR, prune 90j |
| `tests/test_scoring.py` | ✅ | 15 tests (filtres, fusion, scoring, saturation) |
| `tests/test_notif_telegram.py` | ✅ | 9 tests (escaping, découpage, DRY_RUN) |
| **Total tests** | ✅ | **69 passent** |

**Validé end-to-end en DRY_RUN (2026-06-11)** : 1638 offres brutes → 92 après filtre profil → 86 après dédoublonnage → top 15 notifié. **2e run : 0 nouvelles** → persistance SQLite OK (critère d'acceptation #4 ✅). Sans credentials Adzuna/FT locaux, ces 2 sources renvoient `[]` proprement ; ATS + HelloWork tournent en réseau réel.

**Observation qualité (pas un bug)** : le top est dominé par HelloWork (alternances FR bien scorées) car les offres ATS ont des titres anglais qui matchent moins les mots-clés FR. C'est le comportement spécifié au brief ; ajustable via `config/profil.yaml` (mots-clés, poids) sans toucher au code.

**Reste pour un run live complet** : credentials Adzuna/FT + Telegram en env (cf. §4.10 / annexe 9.3 du brief). Le pipeline est prêt, il manque juste les secrets.

### Ce qui est fait en Phase 3 (sources niches)

| Fichier | État | Note |
|---|---|---|
| `src/sources/hellowork.py` | ✅ | **Scraping HTML réel**. Offres dans le HTML statique, parsées via l'aria-label structuré de chaque ancre `<a>`. Validé live (30 offres/page). Garde-fous : délai 2s, max 3 pages, détection Cloudflare/403 → coupe la source sans casser le run |
| `src/sources/choose.py` | ✅ | **NO-OP volontaire** (brief §4.8). SPA sans API stable : `api.choose.app` n'existe pas (DNS), pas de `__NEXT_DATA__`, routes `/jobs` en 404. TODO documenté dans le module |
| `tests/test_sources_niches.py` | ✅ | 6 tests (parsing, filtrage loc, salaire écarté, arrêt pagination, blocage CF, no-op) |
| **Total tests** | ✅ | **45 passent** (`pytest -q`) |

**À savoir pour la suite** : HelloWork n'expose ni description ni date de publication sur la page liste (`description=""`, `date_publication=""`). Le scoring stack/junior (qui lit la description) sera donc peu efficace sur ces offres — c'est attendu, elles passeront surtout par le matching titre. Si la fraîcheur devient critique, il faudrait fetch la page détail de chaque offre (1 requête/offre, coûteux) — pas fait, pas demandé.

### Ce qui est fait en Phase 2 (sources core)

| Fichier | État | Note |
|---|---|---|
| `src/sources/adzuna.py` | ✅ | Migré V2, `fetch(config, session)`, credentials via env, 4 requêtes |
| `src/sources/france_travail.py` | ✅ | Migré V2, OAuth2 token + correctif `maxCreationDate`, 3 requêtes |
| `src/sources/greenhouse.py` | ✅ | Discovery par slugs, résilient (404 → log debug + continue) |
| `src/sources/lever.py` | ✅ | idem, parsing `categories.location` |
| `src/sources/ashby.py` | ✅ | idem, **schéma réel** : `location`/`publishedAt`/`isRemote` (≠ brief qui disait `locationName`) |
| `src/sources/_ats_common.py` | ✅ | Helpers partagés : `localisation_pertinente`, `slugs_pour`, `pause_polie` (200ms) |
| `config/slugs_ats.txt` | ✅ | 42 slugs **vérifiés live** le 2026-06-11 + 25 filet (404 gérés). Total 67 |
| `tests/test_sources.py` | ✅ | 24 tests (parsing, filtrage loc, résilience slug, remote Ashby) |
| **Total tests** | ✅ | **39 passent** (`pytest -q`) |

**Validation live (2026-06-11)** : sur les slugs vivants, ~1472 offres FR brutes remontées (Greenhouse 744, Ashby 559, Lever 169). Beaucoup de remote international gonfle certains slugs (samsara, gitlab, elevenlabs, baseten) — sera écrémé par le filtrage profil en Phase 4.

**⚠️ Slugs ATS volatils** : la majorité des scale-ups FR « connues » (spendesk, qonto, payfit, alan/lever, sorare…) sont en 404 sur leur ancien ATS — elles ont migré (souvent WTTJ/Teamtailor). `slugs_ats.txt` distingue « vérifiés live » et « filet ». À rafraîchir via `scripts/decouvrir_slugs.py` (Phase 5).

### Ce qui était fait en Phase 1

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

- **Phase 6 — Livraison** (côté utilisateur, nécessite ses accès GitHub) : créer le repo distant, push, ajouter les **GitHub Secrets** (ADZUNA_*, FT_*, TELEGRAM_*), lancer un `workflow_dispatch` manuel pour valider en réel, puis laisser le cron tourner. Côté Telegram : créer le bot via @BotFather (cf. README). **Tout le code est prêt ; il ne reste que des actions de configuration côté compte.**

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
