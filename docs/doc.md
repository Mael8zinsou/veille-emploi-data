# Documentation technique — Pipeline de veille emploi Data Engineer

> Document de référence du projet. Il décrit le **but recherché**, le **plan d'action
> initial**, l'**architecture**, les **limitations** et les **modifications apportées**
> en cours de route. Le détail technique est déporté dans les annexes (voir la table
> ci-dessous) pour garder ce document lisible.
>
> Public visé : un développeur qui reprend le projet, ou qui veut s'en inspirer pour
> construire sa propre veille automatisée.

**Version doc :** 1.0 — état au 2026-06-12 (projet livré en production).
**Dépôt :** `veille-emploi-data` · **Langage :** Python 3.11+ · **Tests :** 69 (pytest).

---

## Table des annexes

| Annexe | Contenu |
|---|---|
| [Annexe A — Sources & contrat d'interface](annexe_A_sources.md) | Chaque source en détail (endpoints, parsing, résilience), contrat `fetch(config, session)`, gestion des slugs ATS. |
| [Annexe B — Technologies](annexe_B_technologies.md) | Stack détaillée : pourquoi chaque techno, comment elle est utilisée, alternatives écartées. |
| [Annexe C — Scoring & dédoublonnage](annexe_C_scoring.md) | Algorithmes de filtrage, fusion cross-source, scoring et détection de saturation. |
| [Annexe D — Déploiement & exploitation](annexe_D_deploiement.md) | GitHub Actions, persistance SQLite via cache, secrets, run de validation, maintenance. |

---

## 1. But recherché

### 1.1 Le problème

La recherche d'un premier poste de **Data Engineer junior** se heurte à la saturation
des canaux visibles. Une offre publiée sur LinkedIn reçoit couramment **200 à 500
candidatures**. Le « marché caché » — PME, scale-ups peu visibles, postes publiés
directement sur les ATS (*Applicant Tracking Systems*) sans passer par les agrégateurs —
est nettement moins concurrentiel, mais son ratissage manuel est chronophage et répétitif.

### 1.2 L'objectif

Construire un **pipeline autonome** qui, chaque matin :

1. agrège des offres depuis plusieurs sources (APIs publiques + ATS + plateformes FR) ;
2. filtre selon un profil configurable (mots-clés, exclusions, localisations) ;
3. dédoublonne entre sources et **score** chaque offre, en pénalisant celles présentes
   partout (déjà saturées) et en valorisant les exclusives (pépites potentielles) ;
4. ne retient que les **nouveautés** (mémoire persistante des offres déjà vues) ;
5. **notifie** le top du jour via Telegram, avec liens cliquables ;
6. tourne **sans serveur ni intervention**, via GitHub Actions (cron).

### 1.3 Objectif secondaire : portfolio

Le projet est pensé pour être **présentable en entretien** : structure claire, code
commenté en français, tests, README et cette documentation. Il illustre des compétences
de data engineering (ingestion multi-source, normalisation, déduplication, scoring,
persistance, orchestration, CI/CD).

### 1.4 Non-objectifs (périmètre volontairement exclu)

- **Pas de scraping LinkedIn / Indeed / APEC / Welcome to the Jungle** : anti-bot
  agressif, risque de blocage IP, et leurs alertes email natives sont déjà en place.
- **Pas d'auto-candidature ni de génération de lettre** : l'outil *alimente*, la
  candidature reste manuelle et ciblée.
- **Pas d'interface web** : CLI + Actions + notification Telegram suffisent.

---

## 2. Plan d'action initial

Le projet a été découpé en **6 phases** séquentielles, chacune validée avant la suivante.
Ce découpage vient du brief de conception (`brief_vague3.md`, versionné à la racine).

| Phase | Objet | Livrables clés |
|---|---|---|
| **1 — Fondations** | Socle technique | structure, `models.Offre`, `config`, `storage` (SQLite), `utils/http` |
| **2 — Sources core** | APIs + ATS | `adzuna`, `france_travail`, `greenhouse`, `lever`, `ashby`, `slugs_ats.txt` |
| **3 — Sources niches** | Plateformes FR | `hellowork` (scraping), `choose` (no-op assumé) |
| **4 — Pipeline** | Cœur logique | `scoring`, `notif_telegram`, `main` (orchestration) |
| **5 — Automatisation** | CI/CD + doc | workflow Actions, README, scripts bonus |
| **6 — Livraison** | Mise en prod | bot Telegram, push, secrets, run de validation |

Principe directeur retenu dès le départ : **une source défaillante ne doit jamais
casser le pipeline**. Chaque source est isolée ; une panne (API down, Cloudflare, slug
obsolète) est journalisée et le pipeline continue avec les autres.

---

## 3. Architecture

### 3.1 Vue d'ensemble du flux

```
GitHub Actions (cron 6h UTC ≈ 7h Paris)
        │
        ▼
     main.py  ── orchestration · logging · résilience par source
        │
        ├─ Sources "core"   (APIs)          : Adzuna · France Travail
        ├─ Sources "core"   (ATS discovery) : Greenhouse · Lever · Ashby
        └─ Sources "niches" (désactivables) : HelloWork · Choose (no-op)
        │
        ▼  list[Offre]  (≈ 2 300 offres brutes)
   filtre_par_profil          ── mots-clés must-match, exclusions titre, localisation
        ▼  (≈ 200)
   dedoublonne_et_fusionne    ── une offre vue N fois → 1 entrée, nb_sources = N
        ▼  (≈ 186)
   score_toutes               ── bonus stack/junior, malus ESN, saturation
        ▼
   storage (SQLite)           ── filtre "déjà vu", marque les nouvelles
        ▼
   notif_telegram             ── top N (15), MarkdownV2, liens cliquables
        ▼
   Telegram  ← message reçu par l'utilisateur
```

### 3.2 Modules et responsabilités

| Module | Rôle |
|---|---|
| `src/models.py` | Dataclass `Offre` partagée + `compute_cle_unique` (hash déterministe). |
| `src/config.py` | Charge `profil.yaml` → `SimpleNamespace`. Lit `slugs_ats.txt`. |
| `src/storage.py` | SQLite : `init_db`, `is_already_seen`, `mark_seen`, `mark_notified`, `prune_old`. |
| `src/utils/http.py` | Session `requests` partagée : retry exponentiel, User-Agent navigateur. |
| `src/sources/*.py` | Une source = un module exposant `fetch(config, session) -> list[Offre]`. |
| `src/scoring.py` | Filtrage profil, dédoublonnage/fusion, scoring + saturation. |
| `src/notif_telegram.py` | Rendu MarkdownV2, escaping, découpage 4096, mode DRY_RUN. |
| `src/main.py` | Orchestration de bout en bout, logging, locale FR, prune. |

> Le **contrat d'interface des sources** et le détail de chaque source sont en
> [Annexe A](annexe_A_sources.md). Les **algorithmes de scoring** sont en
> [Annexe C](annexe_C_scoring.md).

### 3.3 Décisions de conception structurantes

- **Dataclass `Offre` unique** partagée par toutes les sources → un seul format à
  filtrer, dédoublonner, scorer. Les sources sont responsables du *mapping* vers ce format.
- **Clé d'unicité tolérante** : `SHA256(entreprise normalisée + 50 premiers caractères
  du titre normalisé)`, tronquée à 16 caractères. Normalisation = minuscule, sans
  accents, *strip*. Volontairement insensible aux variations mineures de casse/accents
  pour reconnaître la même offre vue sur deux sources. (Détail en [Annexe C](annexe_C_scoring.md).)
- **Persistance par cache, pas par commit** : la base SQLite `data/offres.sqlite` est
  sauvegardée entre runs via le **cache GitHub Actions** (et non un commit auto sur une
  branche `data`). Plus simple, pas de pollution de l'historique git. (Détail en
  [Annexe D](annexe_D_deploiement.md).)
- **Credentials hors code** : lus dans l'environnement (`.env` en local, GitHub Secrets
  en CI). Jamais committés (`.gitignore`).
- **Résilience systématique** : chaque `fetch` est encapsulé dans un `try/except` au
  niveau de `main.py`, et chaque source gère en interne ses propres erreurs (slug 404,
  blocage anti-bot, réponse inattendue).

---

## 4. Limitations connues

Limitations assumées, documentées pour quiconque reprend le projet.

### 4.1 Sources

- **Choose (`choose.app`)** : **désactivée (no-op)**. C'est une SPA dont les offres ne
  sont rendues qu'après exécution JavaScript ; `api.choose.app` n'existe pas (DNS),
  aucune donnée statique exploitable. Un rendu *headless* (Playwright) serait hors
  périmètre et trop fragile pour un cron. Le module est un no-op propre, réactivable.
- **HelloWork** : scraping HTML. Fonctionne (parsing d'un `aria-label` structuré, stable),
  mais **sans description ni date de publication** sur la page liste. Le scoring stack
  (qui lit la description) est donc peu efficace sur ces offres ; elles passent surtout
  par le matching de titre. Récupérer le détail demanderait 1 requête par offre (coûteux,
  non fait). Un blocage Cloudflare couperait la source pour le run (géré, sans crash).
- **Slugs ATS volatils** : beaucoup de scale-ups FR « connues » ont quitté
  Greenhouse/Lever/Ashby (migration vers WTTJ/Teamtailor…). La liste `slugs_ats.txt`
  contient des slugs **vérifiés live** et un **filet** d'entrées potentiellement obsolètes
  (404 gérés sans casse). Elle doit être rafraîchie périodiquement
  (`scripts/decouvrir_slugs.py`).

### 4.2 Qualité du classement

- Le top du jour tend à être **dominé par HelloWork** (alternances FR aux titres bien
  matchés) car les offres ATS ont souvent des titres en anglais qui matchent moins les
  mots-clés FR. C'est un effet du scoring tel que paramétré, **pas un bug** : entièrement
  ajustable via `config/profil.yaml` (mots-clés, poids) **sans toucher au code**.

### 4.3 Quotas et politesse

- **Adzuna** : free tier 250 requêtes/mois. Le pipeline fait ~4 requêtes/run → ~120/mois,
  sous le quota. À surveiller si le nombre de requêtes augmente.
- **France Travail** : limite 4 req/s par application (le pipeline reste très en deçà).
- **ATS** : délai de politesse de 200 ms entre slugs ; HelloWork 2 s entre pages.

### 4.4 Divers

- **Locale FR** pour les dates Telegram : tentée puis *fallback* anglais si indisponible
  (cas possible sur certains runners). Non bloquant.
- **Encodage console Windows (cp1252)** : les sorties console (DRY_RUN, scripts) ont été
  rendues tolérantes aux emojis/accents pour ne pas planter en local. L'envoi réel
  (via `requests`) n'est pas concerné.

---

## 5. Modifications apportées en cours de route

Écarts par rapport au plan/brief initial, tranchés pendant l'implémentation et documentés.

| # | Sujet | Décision et raison |
|---|---|---|
| 1 | **Schéma Ashby** | Le brief annonçait le champ `locationName`. Le réel (vérifié en live) est `location` + `publishedAt` + flag `isRemote`. Alignement sur le réel, avec fallback sur l'ancien nom. Sans ça, 0 offre Ashby. |
| 2 | **Slugs ATS** | La majorité des slugs « connus » étaient en 404. Liste reconstruite autour de ce qui répond réellement (42 vérifiés live + 25 filet) plutôt que 200 slugs majoritairement morts qui gaspilleraient des requêtes. |
| 3 | **Choose en no-op** | Aucune API stable identifiée (cf. §4.1). Brief §4.8 autorise explicitement le module no-op. |
| 4 | **Cache SQLite** | Le brief proposait `actions/cache` (action combinée) avec clé `run_id`. Ce pattern ne persiste pas correctement une DB jour après jour (cache immuable par clé). Remplacé par `cache/restore` (+ `restore-keys`) puis `cache/save` (`if: always()`), pattern fiable. Détail en [Annexe D](annexe_D_deploiement.md). |
| 5 | **`decouvrir_slugs.py`** | Scraping Google trop bloqué → bascule sur **DuckDuckGo HTML**, plus tolérant. Script manuel, hors cron. |
| 6 | **Chargement `.env`** | Ajout de `load_dotenv()` au démarrage de `main()` : sans lui, `python -m src.main` en local ne voyait pas les credentials. Sans effet en CI (pas de `.env`, les vraies env vars priment). |
| 7 | **Sortie console ASCII** | Scripts utilitaires en `[OK]` plutôt que `✓` pour survivre à la console cp1252 Windows. |

---

## 6. État de livraison

Le projet est **livré et opérationnel en production** (2026-06-12) :

- Pipeline validé **en local** et **sur GitHub Actions** (run `workflow_dispatch` :
  *success*) : 2262 offres brutes → 206 filtrées → 186 dédoublonnées → 15 notifiées.
- **Persistance vérifiée** : 2ᵉ run → 0 nouvelle offre (la mémoire SQLite fonctionne).
- **6 GitHub Secrets** configurés (Adzuna ×2, France Travail ×2, Telegram ×2).
- **Cron quotidien actif** (6h UTC). Notification Telegram reçue et confirmée.
- **69 tests** passent.

Les critères d'acceptation du brief (§5) sont tous remplis. La procédure de mise en
production et d'exploitation est détaillée en [Annexe D](annexe_D_deploiement.md).

---

## 7. Démarrage rapide (pour reprendre le projet)

```bash
git clone <url>
cd veille-emploi-data
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # remplir les credentials (cf. README §Configuration)
DRY_RUN=1 python -m src.main  # test sans envoi (affiche le message en console)
pytest -q                     # 69 tests
```

Pour le sens des variables d'environnement, la configuration du profil et le setup
Telegram, voir le [README](../README.md). Pour le déploiement, voir
[Annexe D](annexe_D_deploiement.md).
