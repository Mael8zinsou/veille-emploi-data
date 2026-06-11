# 🌅 Veille emploi — Data Engineer junior

Pipeline autonome de **découverte d'offres data engineering** qui ratisse le marché
caché (ATS d'entreprises, plateformes niches FR) plutôt que les agrégateurs saturés,
dédoublonne, score selon un profil, et notifie chaque matin les meilleures nouveautés
via **Telegram**. Tourne tout seul sur **GitHub Actions**, sans serveur à maintenir.

> Side-project conçu pour automatiser ma propre recherche de premier poste de Data
> Engineer. L'idée : LinkedIn est noyé (200–500 candidatures par offre) ; les offres
> publiées directement sur les ATS (Greenhouse, Lever, Ashby) sont bien moins
> concurrentielles mais pénibles à ratisser à la main. Ce pipeline fait le ratissage.

---

## 🏗 Architecture

```
 GitHub Actions (cron 7h Paris)
        │
        ▼
     main.py  ─── orchestration, logging, résilience par source
        │
        ├── Sources "core"  (APIs)        ── Adzuna · France Travail
        │   Sources "core"  (ATS discovery) ── Greenhouse · Lever · Ashby
        │   Sources "niches" (désactivables) ── HelloWork (scraping) · Choose (no-op)
        │
        ▼
   Filtrage profil  ── mots-clés, exclusions, localisation
        ▼
   Dédoublonnage cross-source + fusion  ── une offre vue N fois = 1 entrée, N sources
        ▼
   Scoring  ── bonus stack/junior, malus ESN, et **détection de saturation** :
              exclusive à 1 source = pépite (boost) · présente sur 4+ = déjà bombardée (malus)
        ▼
   SQLite  ── mémoire des offres déjà vues, ne notifie que les nouveautés
        ▼
   Telegram  ── top N du jour, MarkdownV2, liens cliquables
```

Le détail des décisions de conception est dans [`brief_vague3.md`](brief_vague3.md).

---

## ⚙️ Installation

Prérequis : **Python 3.11+**.

```bash
git clone <url-du-repo>
cd veille-emploi-data

python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # puis remplir les credentials (voir ci-dessous)
```

Lancer en local sans rien envoyer (recommandé pour un premier test) :

```bash
DRY_RUN=1 python -m src.main     # affiche le message Telegram en console
```

Lancer pour de vrai (envoie sur Telegram) :

```bash
python -m src.main
```

Lancer les tests :

```bash
pytest -q
```

---

## 🔧 Configuration

### Variables d'environnement (`.env`)

| Variable | Requis | Rôle |
|---|---|---|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | optionnel¹ | API Adzuna (free tier 250 req/mois) |
| `FT_CLIENT_ID` / `FT_CLIENT_SECRET` | optionnel¹ | API France Travail (OAuth2) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | requis (sauf DRY_RUN) | Bot de notification |
| `DRY_RUN` | non | `1` = n'envoie rien, affiche en console |
| `VERBOSE` | non | `1` = logs en niveau DEBUG |

¹ Chaque source dont les credentials manquent est simplement ignorée (les ATS et
HelloWork ne nécessitent aucune clé). Le pipeline tourne donc même sans Adzuna/FT.

### Profil (`config/profil.yaml`)

Tout ce qui dépend du profil recherché est externalisé ici, **sans toucher au code** :
mots-clés à matcher, exclusions de titre (senior, lead…), localisations cibles,
fraîcheur max, **table de scoring** (poids par techno / signal junior, malus ESN),
sources actives, et paramètres Telegram (`top_n_par_jour`, `score_minimum`).

### Slugs ATS (`config/slugs_ats.txt`)

Liste des entreprises à interroger sur Greenhouse / Lever / Ashby, au format
`<ats>:<slug>`. Les slugs obsolètes (404) sont ignorés sans casser le run.
Le script [`scripts/decouvrir_slugs.py`](scripts/decouvrir_slugs.py) aide à en
découvrir de nouveaux.

### Telegram (setup unique)

1. Sur Telegram, parler à [@BotFather](https://t.me/BotFather), commande `/newbot`.
2. Récupérer le **token** fourni.
3. Envoyer un message à son nouveau bot, puis ouvrir
   `https://api.telegram.org/bot<TOKEN>/getUpdates` et y lire le **`chat_id`**.
4. Renseigner `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`.

---

## 📡 Sources couvertes

| Source | Type | Statut | Note |
|---|---|---|---|
| **Adzuna** | API agrégée | ✅ | Free tier, quelques requêtes/run |
| **France Travail** | API officielle | ✅ | OAuth2, exhaustif sur la France |
| **Greenhouse** | ATS (discovery) | ✅ | Endpoint board public, filtrage FR côté code |
| **Lever** | ATS (discovery) | ✅ | idem |
| **Ashby** | ATS (discovery) | ✅ | idem (+ gestion des postes remote) |
| **HelloWork** | Scraping HTML | ✅ | Page de recherche, parsing résilient, garde-fous anti-ban |
| **Choose** | — | ⏸ no-op | SPA sans API stable ; désactivé proprement (réactivable) |

Hors périmètre volontaire : **LinkedIn, Indeed, APEC, Welcome to the Jungle** — trop
d'anti-bot, et leurs alertes email natives sont déjà en place de mon côté.

---

## 🤖 Automatisation (GitHub Actions)

Le workflow [`.github/workflows/veille.yml`](.github/workflows/veille.yml) :

- s'exécute via **cron à 6h UTC** (7h Paris) et **manuellement** (`workflow_dispatch`) ;
- **persiste la base SQLite entre runs** via le cache Actions (restore + save), pour
  que le « déjà vu » survive d'un jour à l'autre sans serveur ni commit de données ;
- lit les credentials depuis les **GitHub Secrets** (jamais commités) ;
- **upload les logs** en artefact si le run échoue.

Mise en route : pousser le repo, ajouter les secrets (`Settings → Secrets and variables
→ Actions`), lancer un run manuel pour vérifier, puis laisser le cron faire le reste.

---

## 🧰 Stack technique

- **Python 3.11** — `requests` (sessions avec retry exponentiel), `PyYAML`, `python-dotenv`.
- **SQLite** — persistance légère du « déjà vu », UPSERT compatible runners anciens.
- **pytest** — 69 tests (parsing des sources, filtrage, dédoublonnage, scoring,
  escaping Telegram, résilience).
- **GitHub Actions** — cron, cache, secrets, artefacts.
- Conception : dataclass `Offre` partagée, sources isolées (une panne n'arrête jamais
  le pipeline), scoring configurable sans toucher au code.

---

## 📂 Structure

```
src/
├── main.py            # orchestration
├── models.py          # dataclass Offre + clé d'unicité
├── config.py          # chargement profil.yaml + slugs
├── storage.py         # SQLite (déjà vu / nouveaux)
├── scoring.py         # filtres, dédoublonnage/fusion, scoring + saturation
├── notif_telegram.py  # rendu MarkdownV2, découpage, DRY_RUN
├── sources/           # une source = un module fetch(config, session) -> list[Offre]
└── utils/http.py      # session requests partagée (retry, User-Agent)
config/                # profil.yaml, slugs_ats.txt
scripts/               # decouvrir_slugs.py, init_db.py
tests/                 # 69 tests
.github/workflows/     # veille.yml
```

---

## 🚫 Ce que ce pipeline ne fait pas

Pas d'auto-candidature, pas de génération de lettre, pas d'interface web. Il **alimente** ;
la candidature reste manuelle et ciblée.
