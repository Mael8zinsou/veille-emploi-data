# Annexe B — Technologies utilisées

> Support de [`doc.md`](doc.md). Pour chaque technologie : **rôle dans le projet**,
> **comment elle est utilisée**, et **alternatives écartées** (avec la raison). L'idée
> est qu'un lecteur comprenne non seulement *quoi*, mais *pourquoi*.

---

## B.1 Vue d'ensemble de la stack

| Couche | Techno | Version | Rôle |
|---|---|---|---|
| Langage | Python | 3.11+ | Tout le pipeline |
| HTTP | `requests` | 2.32.3 | Appels API + scraping, session avec retry |
| Config | `PyYAML` | 6.0.2 | Lecture de `profil.yaml` |
| Env local | `python-dotenv` | 1.0.1 | Chargement du `.env` en local |
| Persistance | `sqlite3` | (stdlib) | Mémoire des offres déjà vues |
| Tests | `pytest` | 8.3.3 | 69 tests |
| CI/CD | GitHub Actions | — | Cron, cache, secrets, artefacts |
| Notification | API Telegram Bot | — | Envoi du top du jour |

Dépendances volontairement **minimales** : 4 paquets runtime (`requests`, `pyyaml`,
`python-dotenv`) + `pytest` en dev. Pas de framework lourd : le projet est un script
orchestré, pas une application.

---

## B.2 Python 3.11+

- **Rôle** : langage unique du projet.
- **Usage** : dataclasses (`Offre`), type hints (`list[Offre]`, `str | None`),
  `SimpleNamespace` pour la config, `pathlib` pour les chemins, `logging` pour les logs.
- **Pourquoi 3.11** : syntaxe d'union `X | Y` native, et `tomllib`/perf ; surtout c'est
  la version testée et celle du runner Actions. Le code reste compatible 3.10+.
- **Alternatives écartées** : aucune sérieuse — l'écosystème data et les APIs visées sont
  tous Python-friendly.

---

## B.3 `requests` (+ retry)

- **Rôle** : tous les appels réseau (APIs JSON, OAuth France Travail, scraping HelloWork,
  envoi Telegram).
- **Usage** : `src/utils/http.py` fournit `build_session()` qui monte un
  `HTTPAdapter` avec une politique `Retry` :
  - `total_retries=3`, `backoff_factor=0.5` → attentes 0.5 s, 1 s, 2 s ;
  - `status_forcelist=(500, 502, 503, 504, 429)` → on ne réessaie que sur les erreurs
    transitoires ;
  - `raise_on_status=False` → on inspecte le code nous-mêmes plutôt que de lever ;
  - User-Agent navigateur réaliste (utile pour le scraping et certains ATS).
  La fonction `get_json()` enveloppe un GET : retourne le JSON parsé ou `None` (jamais
  d'exception remontée).
- **Pourquoi** : standard de fait, API simple, gestion de session/retry mûre.
- **Alternatives écartées** :
  - `httpx` : excellent (HTTP/2, async), mais l'async n'apporte rien ici (volumétrie
    modeste, exécution séquentielle voulue pour la politesse) ; dépendance en plus sans gain.
  - `urllib` (stdlib) : trop bas niveau pour la session/retry/headers.

---

## B.4 `PyYAML`

- **Rôle** : externaliser **toute la configuration métier** hors du code.
- **Usage** : `config/profil.yaml` (mots-clés, exclusions, localisations, table de
  scoring, sources actives, params Telegram) est chargé par `load_config()` puis converti
  **récursivement** en `SimpleNamespace`, ce qui permet l'accès par attribut
  (`config.telegram.score_minimum`). Les sous-tables de scoring sont relues en `dict` via
  `vars()` car certaines clés contiennent des caractères spéciaux (`"ci/cd"`, `"esn "`).
- **Pourquoi YAML plutôt que JSON** : commentaires possibles, lisibilité pour un humain
  qui édite son profil sans être développeur.
- **Sécurité** : `yaml.safe_load` (jamais `load`) pour éviter l'exécution de code arbitraire.

---

## B.5 `python-dotenv`

- **Rôle** : charger les credentials depuis un fichier `.env` **en local uniquement**.
- **Usage** : `load_dotenv()` est appelé au début de `main()`. En CI, il n'y a pas de
  `.env` et les variables déjà présentes dans l'environnement (GitHub Secrets) ne sont
  pas écrasées → le même code marche en local et en prod.
- **Pourquoi** : confort de dev (un fichier au lieu d'exports manuels) sans coût en prod.
- **Sécurité** : `.env` est dans `.gitignore` ; `.env.example` (vide) est versionné comme
  gabarit.

---

## B.6 SQLite (`sqlite3`, stdlib)

- **Rôle** : **mémoire persistante** des offres déjà vues, pour ne notifier que les
  nouveautés. C'est le composant qui rend la veille « intelligente » d'un jour à l'autre.
- **Schéma** : une table `offres_vues` (clé primaire `cle_unique`, métadonnées, dates de
  première/dernière vue, `notifiee`) + un index sur `date_premiere_vue`.
- **Choix d'implémentation** :
  - **UPSERT en deux passes** (`INSERT OR IGNORE` puis `UPDATE`) plutôt que
    `ON CONFLICT` → compatibilité avec SQLite < 3.24 sur d'anciens runners.
  - `_DB_PATH` mémorisé au niveau module (singleton simple) → suffisant pour un pipeline
    mono-thread.
  - `prune_old(days=90)` purge les entrées non revues depuis 90 jours.
- **Pourquoi SQLite** : zéro serveur, fichier unique, parfait pour un cron. La volumétrie
  (quelques centaines de lignes/jour) est triviale.
- **Alternatives écartées** :
  - Postgres/MySQL : surdimensionné, nécessiterait un service hébergé.
  - Fichier JSON/CSV : pas de requêtes indexées, gestion concurrente fragile.
- **Persistance entre runs CI** : la base est restaurée/sauvegardée via le **cache GitHub
  Actions** (cf. [Annexe D](annexe_D_deploiement.md)), pas commitée.

---

## B.7 `pytest`

- **Rôle** : filet de sécurité sur les fonctions critiques.
- **Couverture (69 tests)** :
  - `test_models` : déterminisme et tolérance de `cle_unique`.
  - `test_config` / `test_storage` : chargement YAML, slugs, UPSERT, idempotence.
  - `test_sources` : parsing de chaque source, filtrage localisation, **résilience slug**
    (404 ne casse pas), branche remote Ashby — le tout sur des réponses **mockées** (zéro
    réseau).
  - `test_sources_niches` : parsing HelloWork, détection de blocage, no-op Choose.
  - `test_scoring` : filtres, fusion cross-source, scoring, **saturation**.
  - `test_notif_telegram` : escaping MarkdownV2, découpage 4096, DRY_RUN.
- **Config** : `pyproject.toml` avec `pythonpath = ["."]` (imports `src.*` sans install).
- **Pourquoi pytest** : syntaxe `assert` directe, fixtures, `monkeypatch` pour mocker
  env/réseau. Standard de l'écosystème.

---

## B.8 GitHub Actions

- **Rôle** : ordonnanceur (cron) + exécuteur sans serveur + coffre à secrets.
- **Usage** : workflow `veille.yml` — déclencheur `schedule` (cron 6h UTC) +
  `workflow_dispatch` (manuel) ; étapes checkout → setup Python (cache pip) → install →
  **restore cache SQLite** → run pipeline → **save cache SQLite** → upload logs si échec.
  `concurrency` empêche deux runs simultanés ; `permissions: contents:read` applique le
  moindre privilège. Détail complet en [Annexe D](annexe_D_deploiement.md).
- **Pourquoi** : gratuit pour un repo perso, intégré au dépôt, secrets chiffrés natifs,
  pas d'infra à gérer. Idéal pour un job quotidien léger.
- **Alternatives écartées** : cron sur un VPS (coût + maintenance) ; services type
  cron-as-a-service (dépendance externe, gestion des secrets moins intégrée).

---

## B.9 API Telegram Bot

- **Rôle** : canal de notification (push sur mobile, gratuit, fiable).
- **Usage** : `notif_telegram.py` appelle `https://api.telegram.org/bot{TOKEN}/sendMessage`
  en **MarkdownV2**. Points délicats traités :
  - **Escaping** des caractères réservés MarkdownV2 (`_ * [ ] ( ) ~ \` > # + - = | { } . !`)
    dans tout contenu dynamique ; l'URL des liens, elle, n'est pas échappée.
  - **Découpage** sous la limite de 4096 caractères (messages numérotés `1/n`).
  - **Mode `DRY_RUN`** : affiche les messages en console au lieu de les envoyer.
- **Setup** : bot créé via `@BotFather`, `chat_id` récupéré via `getUpdates`. Token et
  chat_id en variables d'environnement / secrets.
- **Pourquoi Telegram** : API bot triviale, pas d'OAuth utilisateur, notifications
  instantanées. Alternatives écartées : email (déjà saturé d'alertes), Slack/Discord
  (moins direct sur mobile pour cet usage perso).

---

## B.10 Bibliothèques standard notables

- **`logging`** : logs ISO timestampés vers stdout **et** `data/pipeline.log`. Niveau INFO,
  DEBUG si `VERBOSE=1`. En CI, stdout est capturé par Actions ; le fichier est uploadé en
  artefact si le run échoue.
- **`hashlib` + `unicodedata`** : `cle_unique` (SHA256 sur chaîne normalisée sans accents).
- **`locale`** : dates en français pour Telegram (`%-d %B` → « 12 juin »), avec fallback.
- **`re` + `html`** : parsing du scraping HelloWork (regex sur `aria-label`, `unescape`).
- **`argparse`** : interface du script `decouvrir_slugs.py`.
