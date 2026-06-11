# Brief d'exécution — Pipeline de veille emploi Data Engineer Junior (Vague 3)

> **À l'attention de Claude Code.** Ce document est ton brief complet. Lis-le entièrement avant de commencer. Toutes les décisions techniques majeures ont déjà été prises lors d'une session de conception avec le commanditaire (Maël Mike ZINSOU, Data Engineer junior en recherche d'emploi). Tu n'as pas besoin de lui poser des questions sur les choix de design : ils sont consignés ici. Pose des questions UNIQUEMENT si tu rencontres un blocage technique réel ou une ambiguïté non résolue par ce document.

---

## 1. Contexte du projet

### 1.1 Qui est l'utilisateur

Maël Mike ZINSOU, étudiant en Mastère Data Engineer (YNOV), en alternance à la DIRCOFI Île-de-France jusqu'en septembre 2026. Il cherche son **premier poste en CDI** ou une **alternance pour septembre 2026**, en tant que Data Engineer Junior, principalement en Île-de-France mais mobile sur le territoire FR + Belgique.

Stack maîtrisée : Python, SQL, Airflow, dbt, PySpark, Snowflake, Docker, GitHub Actions, Prometheus, Grafana, FastAPI, MLOps. Anglais professionnel.

### 1.2 Le problème

LinkedIn est saturé. Les offres data engineer junior visibles sur LinkedIn reçoivent 200 à 500 candidatures. Le marché caché (PME, scale-ups peu visibles, offres publiées directement sur les ATS sans passer par les agrégateurs) est beaucoup moins concurrentiel mais demande du travail manuel important pour être ratissé.

### 1.3 Les vagues précédentes (déjà livrées et validées)

**Vague 1 — Dorking Google ciblé** : batterie de requêtes booléennes sur les ATS (Greenhouse, Lever, Ashby, Teamtailor, etc.) + un script Python qui ouvre les requêtes en batch dans le navigateur. Livrable : `requetes_dorking.md` + `lance_recherches.py`. **Statut : validé.**

**Vague 2 — Veille semi-automatisée multi-source** : script Python qui interroge France Travail API + Adzuna API, filtre selon le profil, dédoublonne, exporte en MD + CSV. Configuration : variables d'environnement (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `FT_CLIENT_ID`, `FT_CLIENT_SECRET`). Livrable : `veille_emploi.py` + `setup_vague2.md`. **Statut : implémenté et validé par l'utilisateur.**

L'utilisateur a déjà :
- Inscription Adzuna validée, clés API en main
- Inscription France Travail validée, credentials OAuth en main
- Compte Talent.io créé (profil actif, reverse sourcing)
- Alertes Welcome to the Jungle configurées
- Alertes APEC configurées
- Compte Huntr créé + extension Chrome installée (tracker visuel des candidatures)

---

## 2. Objectif de la Vague 3

Transformer le script de veille semi-manuel (Vague 2) en **pipeline autonome de découverte d'offres cachées**, qui tourne automatiquement chaque matin sur GitHub Actions et notifie l'utilisateur via Telegram.

### 2.1 Objectifs fonctionnels

1. **Élargir massivement les sources** en ajoutant les ATS Greenhouse, Lever et Ashby en mode discovery (sans liste fermée d'entreprises, ratissage large).
2. **Ajouter des sources niches FR** : HelloWork et Choose (choose.app) pour capter les PME régionales et scale-ups françaises.
3. **Détecter et déclasser les offres saturées** : une offre présente sur 4+ sources est probablement déjà bombardée de candidatures, on la déclasse ; une offre exclusive à 1 source est probablement une pépite, on la boost.
4. **Mémoriser les offres déjà vues** dans une base SQLite locale pour ne notifier QUE les nouveautés du jour, jamais deux fois la même offre.
5. **Notifier via Telegram** les top N offres du jour, formatées proprement, avec liens cliquables.
6. **Tourner automatiquement** via GitHub Actions tous les matins à 7h heure de Paris, sans intervention manuelle.

### 2.2 Objectif portfolio

Le projet doit être **présentable comme side-project sur GitHub** : README propre, code lisible, structure de dossiers professionnelle, tests minimaux, instructions d'installation reproductibles. Le commanditaire pourra le mentionner en entretien comme illustration de ses compétences en data engineering.

### 2.3 Non-objectifs (à ne PAS faire)

- **Pas de scraping de LinkedIn, Indeed, APEC ou Welcome to the Jungle** : trop d'anti-bot, risque de blocage IP, et les alertes email natives de ces plateformes sont déjà configurées par l'utilisateur. Si tu es tenté de les ajouter, ne le fais pas.
- **Pas d'auto-apply** : on génère des offres ciblées, l'utilisateur candidate manuellement avec des lettres adaptées. Pas de soumission automatique de candidatures.
- **Pas de génération de lettres de motivation dans le pipeline** : déjà géré ailleurs (conversation Claude.ai).
- **Pas d'interface web** : le pipeline est CLI + GitHub Actions + notifications Telegram. Pas de frontend.

---

## 3. Architecture cible

### 3.1 Structure de dossiers

```
veille-emploi/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config/
│   ├── profil.yaml              # mots-clés, exclusions, localisations, scoring
│   └── slugs_ats.txt            # slugs Greenhouse/Lever/Ashby connus
├── src/
│   ├── __init__.py
│   ├── main.py                  # point d'entrée du pipeline
│   ├── models.py                # dataclass Offre
│   ├── config.py                # chargement de profil.yaml
│   ├── storage.py               # interactions SQLite
│   ├── scoring.py               # filtres + scoring + détection saturation
│   ├── notif_telegram.py        # envoi des notifications
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── adzuna.py            # adapté depuis veille_emploi.py V2
│   │   ├── france_travail.py    # adapté depuis veille_emploi.py V2
│   │   ├── greenhouse.py        # NOUVEAU
│   │   ├── lever.py             # NOUVEAU
│   │   ├── ashby.py             # NOUVEAU
│   │   ├── hellowork.py         # NOUVEAU (isolé, désactivable)
│   │   └── choose.py            # NOUVEAU (isolé, désactivable)
│   └── utils/
│       ├── __init__.py
│       └── http.py              # session requests avec retry + User-Agent
├── scripts/
│   ├── decouvrir_slugs.py       # scraper Google pour découvrir nouveaux slugs ATS
│   └── init_db.py               # initialise la base SQLite
├── tests/
│   ├── __init__.py
│   ├── test_scoring.py
│   └── test_storage.py
└── .github/
    └── workflows/
        └── veille.yml           # cron 7h Paris
```

### 3.2 Flux d'exécution

```
                    ┌──────────────────┐
                    │   GitHub Actions │
                    │  cron 7h Paris   │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │     main.py      │
                    └────────┬─────────┘
                             ▼
        ┌────────────────────┴────────────────────┐
        ▼                                         ▼
┌───────────────┐                         ┌──────────────┐
│   Sources     │                         │   Sources    │
│   "core"      │                         │   "niche"    │
│ (toujours ON) │                         │ (désactivable│
│               │                         │   si erreur) │
│  Adzuna       │                         │  HelloWork   │
│  France T.    │                         │  Choose      │
│  Greenhouse   │                         │              │
│  Lever        │                         │              │
│  Ashby        │                         │              │
└──────┬────────┘                         └──────┬───────┘
       │                                         │
       └────────────────┬────────────────────────┘
                        ▼
              ┌──────────────────┐
              │  Agrégation      │
              │  Dédoublonnage   │
              │  Scoring         │
              │  Détection sat.  │
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │  SQLite          │
              │  Filtre "déjà vu"│
              │  Marque nouveaux │
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │  Telegram bot    │
              │  Top N nouveaux  │
              └──────────────────┘
```

---

## 4. Spécifications détaillées par module

### 4.1 `config/profil.yaml`

Tout ce qui dépend du profil utilisateur est externalisé ici, pour qu'il puisse éditer sans toucher au code.

```yaml
profil:
  poste_cible: "Data Engineer Junior"
  experience_annees: 1
  
mots_cles_must_match:
  - "data engineer"
  - "ingénieur données"
  - "ingénieur data"
  - "développeur data"
  - "data software engineer"
  - "analytics engineer"
  - "mlops"
  
exclusions_titre:
  - "senior"
  - "lead"
  - "staff"
  - "principal"
  - "head of"
  - "manager"
  - "directeur"
  - "director"
  - "architect"
  - "expert"
  - "confirmé"
  - "expérimenté"
  - "10 ans"
  - "8 ans"
  - "7 ans"
  - "5 ans"
  
localisations:
  - "paris"
  - "île-de-france"
  - "ile-de-france"
  - "idf"
  - "nanterre"
  - "la défense"
  - "boulogne"
  - "issy"
  - "saint-denis"
  - "nantes"
  - "rennes"
  - "bordeaux"
  - "lille"
  - "lyon"
  - "toulouse"
  - "bruxelles"
  - "brussels"
  - "remote"
  - "télétravail"
  - "full remote"
  
fraicheur_max_jours: 14

scoring:
  bonus_signaux_junior:
    junior: 3
    graduate: 3
    "premier emploi": 3
    débutant: 3
    alternance: 3
    apprenti: 3
    mentorat: 2
    formation: 2
    accompagnement: 2
    "première expérience": 2
    "0-2 ans": 2
  
  bonus_stack:
    python: 2
    sql: 2
    airflow: 3
    dbt: 3
    snowflake: 3
    pyspark: 2
    spark: 2
    docker: 2
    kubernetes: 1
    aws: 2
    gcp: 2
    azure: 1
    kafka: 2
    fastapi: 2
    prometheus: 1
    grafana: 1
    mlops: 3
    "ci/cd": 2
    "github actions": 2
  
  malus:
    "esn ": -2
    "société de conseil": -2
    consultant: -2
  
  # Détection de saturation : pénalité par source supplémentaire
  malus_par_source_supplementaire: -3
  bonus_source_unique: 5

sources_actives:
  adzuna: true
  france_travail: true
  greenhouse: true
  lever: true
  ashby: true
  hellowork: true   # mettre false si scraping casse
  choose: true      # mettre false si scraping casse

telegram:
  top_n_par_jour: 15
  score_minimum: 5
```

### 4.2 `src/models.py`

Une seule dataclass `Offre` enrichie :

```python
@dataclass
class Offre:
    source: str
    titre: str
    entreprise: str
    localisation: str
    contrat: str
    description: str
    url: str
    date_publication: str  # format ISO YYYY-MM-DD
    
    # Calculés en aval
    cle_unique: str = ""        # hash entreprise+titre normalisés
    score: int = 0
    tags: list[str] = field(default_factory=list)
    nb_sources: int = 1         # incrémenté lors de la fusion multi-source
    sources_list: list[str] = field(default_factory=list)
```

La méthode `cle_unique` doit être déterministe et insensible aux variations mineures :
- Entreprise : lowercase, strip, accents retirés
- Titre : lowercase, strip, première moitié seulement (50 caractères), accents retirés
- Hash SHA256 du concaténé, 16 premiers caractères

### 4.3 `src/storage.py` — SQLite

Schéma minimaliste :

```sql
CREATE TABLE IF NOT EXISTS offres_vues (
    cle_unique TEXT PRIMARY KEY,
    titre TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    url TEXT NOT NULL,
    score INTEGER NOT NULL,
    date_premiere_vue TEXT NOT NULL,
    date_derniere_vue TEXT NOT NULL,
    sources TEXT NOT NULL,        -- CSV des sources où vue
    notifiee BOOLEAN DEFAULT 0
);

CREATE INDEX idx_date_premiere_vue ON offres_vues(date_premiere_vue);
```

Fonctions exposées :
- `init_db(path: str) -> None`
- `is_already_seen(cle_unique: str) -> bool`
- `mark_seen(offre: Offre) -> None`
- `mark_notified(cle_unique: str) -> None`
- `get_recent_unseen(days: int) -> list[str]` (pour debug)
- `prune_old(days: int = 90) -> int` (supprime les entrées > 90 jours)

**Chemin de la DB** : `data/offres.sqlite` (créer le dossier `data/` si nécessaire). Le `.gitignore` doit ignorer `data/*.sqlite` mais GitHub Actions doit pouvoir **persister la DB entre runs** via le cache d'Actions ou via un commit auto sur une branche `data` dédiée. **Décision : utiliser GitHub Actions Cache** avec restore + save autour de chaque run. Si l'utilisateur préfère un commit auto sur branche `data`, c'est documenté dans le README en option.

### 4.4 `src/sources/greenhouse.py`

**Endpoint** : `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`

**Logique** :
1. Charge la liste de slugs depuis `config/slugs_ats.txt` (lignes au format `greenhouse:slug`)
2. Pour chaque slug, GET l'endpoint avec timeout 10s, retry 2x
3. Parse les jobs retournés, filtre côté code par localisation FR (champ `location.name` contient une des localisations cibles OU contient "France" OU "Remote")
4. Mappe vers `Offre` (source = "Greenhouse")
5. Si un slug retourne 404 ou erreur, log et continue (ne pas faire planter le pipeline)

**Important** : ce scraper doit être **résilient** : un slug obsolète ne doit jamais casser la boucle. Toujours wrapper chaque appel dans un try/except local au slug.

### 4.5 `src/sources/lever.py`

**Endpoint** : `https://api.lever.co/v0/postings/{slug}?mode=json`

**Logique** : identique à Greenhouse, en adaptant le parsing JSON. Champ localisation : `categories.location`. Mots-clés FR à matcher : Paris, France, IDF, etc.

### 4.6 `src/sources/ashby.py`

**Endpoint** : `https://api.ashbyhq.com/posting-api/job-board/{slug}` (endpoint public non documenté officiellement mais stable)

**Logique** : identique aux deux précédents. Champ localisation : `locationName`.

**Fallback** : si l'endpoint JSON ne répond pas, NE PAS implémenter de fallback HTML scraping. Log et passe au slug suivant.

### 4.7 `src/sources/hellowork.py` (isolé, désactivable)

**Approche** : scraping HTML de la page de recherche `https://www.hellowork.com/fr-fr/emploi/recherche.html?k={mots_cles}&l={localisation}`

**Précautions** :
- User-Agent navigateur réaliste
- Délai entre requêtes : 2s minimum
- Maximum 3 pages de résultats par recherche
- Si HTTP 403 ou Cloudflare challenge détecté, **désactiver la source pour ce run** et logger un warning, sans faire planter le pipeline
- Toujours wrapper l'ensemble dans un try/except global

**Si tu trouves le scraping trop fragile** : génère le module avec une fonction `fetch_hellowork()` qui retourne `[]` et un commentaire `# TODO: HelloWork scraping désactivé, voir issue #X`. Mieux vaut un module no-op qu'un scraper qui casse tout.

### 4.8 `src/sources/choose.py` (isolé, désactivable)

**Approche** : Choose (choose.app) est une SPA React. Leur API interne est en `https://api.choose.app/` (à confirmer en inspectant les Network calls). 

**Si tu ne trouves pas l'endpoint stable** : même fallback que HelloWork, module no-op + TODO commenté. Cette source est nice-to-have, pas critique.

### 4.9 `src/scoring.py`

Reprend la logique de scoring de `veille_emploi.py` V2, en ajoutant :

1. **Dédoublonnage cross-source** : si deux offres ont la même `cle_unique`, on les fusionne en gardant l'offre avec le plus de détails, et on incrémente `nb_sources` et `sources_list`.

2. **Scoring de saturation** :
   - `nb_sources == 1` → `+ bonus_source_unique` (5 par défaut)
   - `nb_sources >= 4` → `+ malus_par_source_supplementaire * (nb_sources - 1)` (négatif)
   - `nb_sources == 2 ou 3` → neutre

3. Le tri final est par score décroissant.

### 4.10 `src/notif_telegram.py`

**API Telegram** : `https://api.telegram.org/bot{TOKEN}/sendMessage`

**Variables d'env requises** :
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Format du message** (Markdown V2) :

```
🌅 *Veille du 10 juin* — 7 nouvelles offres

*[1]* ⭐ score 18 \(2 sources\)
*Data Engineer Junior* chez *Spendesk*
📍 Paris · CDI
🏷 junior, airflow, dbt, snowflake
🔗 [Voir l'offre](https://boards.greenhouse.io/spendesk/...)

*[2]* ⭐ score 15 \(1 source — exclusif\)
*Analytics Engineer* chez *Atida*
📍 Paris · CDI
🏷 dbt, snowflake, python
🔗 [Voir l'offre](https://...)

\[...\]

_Pipeline lancé à 07:00 — 247 offres scannées, 7 nouvelles_
```

**Découpage** : Telegram limite à 4096 caractères par message. Si le top N dépasse, splitter en plusieurs messages numérotés (1/2, 2/2).

**Escapage Markdown V2** : penser à escaper les caractères réservés `_ * [ ] ( ) ~ \` > # + - = | { } . !` dans les contenus dynamiques.

**Mode dry-run** : si la variable d'env `DRY_RUN=1` est définie, ne PAS envoyer à Telegram, juste afficher le message en console.

### 4.11 `src/main.py`

Pipeline orchestré :

```python
def main():
    config = load_config("config/profil.yaml")
    init_db("data/offres.sqlite")
    
    toutes_offres = []
    for source_name, fetch_fn in get_active_sources(config):
        try:
            offres = fetch_fn(config)
            log(f"{source_name}: {len(offres)} offres")
            toutes_offres.extend(offres)
        except Exception as e:
            log_error(f"{source_name} a échoué: {e}")
            continue
    
    log(f"Total brut: {len(toutes_offres)}")
    
    # Filtrage par mots-clés + exclusions + localisation
    offres_filtrees = filtre_par_profil(toutes_offres, config)
    log(f"Après filtres profil: {len(offres_filtrees)}")
    
    # Dédoublonnage cross-source avec fusion
    offres_dedoublonnees = dedoublonne_et_fusionne(offres_filtrees)
    log(f"Après dédoublonnage: {len(offres_dedoublonnees)}")
    
    # Scoring (incluant saturation)
    offres_scorees = score_toutes(offres_dedoublonnees, config)
    
    # Filtre "déjà vues"
    nouvelles = [o for o in offres_scorees if not is_already_seen(o.cle_unique)]
    log(f"Nouvelles offres: {len(nouvelles)}")
    
    # Marque comme vues en DB
    for o in offres_scorees:
        mark_seen(o)
    
    # Filtre par score minimum + top N
    a_notifier = [o for o in nouvelles if o.score >= config.telegram.score_minimum]
    a_notifier.sort(key=lambda o: o.score, reverse=True)
    a_notifier = a_notifier[:config.telegram.top_n_par_jour]
    
    # Notification
    if a_notifier:
        send_telegram(a_notifier, total_scanne=len(toutes_offres))
        for o in a_notifier:
            mark_notified(o.cle_unique)
    else:
        send_telegram_empty_day(total_scanne=len(toutes_offres))
    
    log("Pipeline terminé avec succès")
```

### 4.12 `scripts/decouvrir_slugs.py`

Script optionnel et indépendant : scrape Google avec une dizaine de requêtes type `site:boards.greenhouse.io "France" "data"` pour extraire de nouveaux slugs et les ajouter à `config/slugs_ats.txt` (avec dédoublonnage).

**Lancé manuellement de temps en temps** par l'utilisateur, pas inclus dans le pipeline GitHub Actions (risque de blocage Google sinon).

Pour initialiser `slugs_ats.txt`, **inclure dès le départ une liste de 100-200 slugs FR connus** issue de ta propre connaissance (Doctolib, Alan, Spendesk, Mirakl, PayFit, Qonto, Pigment, Aircall, Algolia, ContentSquare, Datadog, Voodoo, Sorare, Swile, etc.). Sois généreux : mieux vaut 200 slugs dont 30 obsolètes que 50 slugs sûrs.

### 4.13 `.github/workflows/veille.yml`

```yaml
name: Veille emploi quotidienne

on:
  schedule:
    - cron: '0 6 * * *'   # 6h UTC = 7h Paris (8h en été)
  workflow_dispatch:       # permet le lancement manuel

jobs:
  veille:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Cache SQLite DB
        uses: actions/cache@v4
        with:
          path: data/
          key: veille-db-${{ github.run_id }}
          restore-keys: veille-db-
      
      - run: pip install -r requirements.txt
      
      - name: Lance le pipeline
        env:
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          FT_CLIENT_ID: ${{ secrets.FT_CLIENT_ID }}
          FT_CLIENT_SECRET: ${{ secrets.FT_CLIENT_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m src.main
      
      - name: Upload logs si échec
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: logs
          path: data/pipeline.log
```

---

## 5. Critères d'acceptation

Le projet est considéré comme livré quand :

1. **Le pipeline tourne en local** via `python -m src.main` avec toutes les variables d'env configurées, et produit un résultat cohérent (au moins 50 offres brutes scannées, au moins 5 après filtre, notification Telegram reçue en mode `DRY_RUN=0`).

2. **Le pipeline tourne sur GitHub Actions** déclenché manuellement (`workflow_dispatch`), produit le même résultat que le local.

3. **Le cron quotidien est configuré** et le commanditaire peut confirmer qu'il reçoit une notification Telegram chaque matin sans intervention de sa part.

4. **La SQLite persiste correctement entre runs** : le jour 2, le pipeline ne renvoie pas les offres du jour 1 dans la notification.

5. **Aucune source individuelle ne peut faire planter le pipeline** : si Greenhouse renvoie 500, le pipeline continue avec les autres sources. Si HelloWork est bloqué par Cloudflare, le pipeline continue.

6. **Le README est complet et exploitable** : un développeur tiers doit pouvoir cloner le repo et faire tourner le pipeline en suivant les instructions.

7. **Le code passe les tests** : au minimum, les tests dans `tests/test_scoring.py` et `tests/test_storage.py` passent (focus sur les fonctions critiques : `cle_unique`, scoring, dédoublonnage).

8. **Le projet est présentable en entretien** : structure claire, code commenté en français, README en français avec sections "Architecture", "Installation", "Configuration", "Sources couvertes", "Stack technique utilisée".

---

## 6. Plan d'exécution recommandé

Exécute dans cet ordre, en validant chaque étape avant de passer à la suivante :

### Phase 1 — Fondations (à faire en premier)
1. Crée la structure de dossiers
2. Écris `requirements.txt` (requests, pyyaml, python-dotenv, pytest)
3. Écris `src/models.py` avec la dataclass Offre + tests de `cle_unique`
4. Écris `src/config.py` qui charge `profil.yaml` en objet Python
5. Écris `src/storage.py` (SQLite) + tests
6. Écris `src/utils/http.py` (session requests avec retry)

### Phase 2 — Sources core
7. Migre `adzuna.py` et `france_travail.py` depuis `veille_emploi.py` V2 vers la nouvelle structure
8. Écris `greenhouse.py` + teste avec 5 slugs connus
9. Écris `lever.py` + teste avec 5 slugs connus
10. Écris `ashby.py` + teste avec 5 slugs connus
11. Initialise `config/slugs_ats.txt` avec ta liste de 100-200 slugs FR connus

### Phase 3 — Sources niches
12. Écris `hellowork.py` (si trop fragile : module no-op avec TODO)
13. Écris `choose.py` (si trop fragile : module no-op avec TODO)

### Phase 4 — Pipeline
14. Écris `src/scoring.py` avec dédoublonnage, fusion, scoring saturation + tests
15. Écris `src/notif_telegram.py` avec mode dry-run
16. Écris `src/main.py` qui orchestre tout
17. Teste en local avec `DRY_RUN=1` jusqu'à obtenir un message Telegram cohérent

### Phase 5 — Automatisation
18. Écris `.github/workflows/veille.yml`
19. Écris `README.md` complet
20. Écris `.env.example` et `.gitignore`
21. Écris `scripts/decouvrir_slugs.py` (bonus, dernier)

### Phase 6 — Livraison
22. Initialise le repo Git, commit propre, push sur GitHub (compte de l'utilisateur, repo `veille-emploi` ou autre nom à confirmer avec lui)
23. Configure les GitHub Secrets avec l'utilisateur (il aura besoin de t'autoriser sur son repo)
24. Lance un workflow manuel pour vérifier que tout tourne
25. Active le cron quotidien

---

## 7. Points de vigilance

- **Ne jamais commit de credentials**. Le `.gitignore` doit ignorer `.env`, `*.sqlite`, `data/`, `__pycache__/`, `.venv/`.

- **Respect des rate limits** : Adzuna 250 req/mois free tier, France Travail 4 req/s par app. Pour Greenhouse/Lever/Ashby, ajouter un délai de 200ms entre chaque slug pour rester poli.

- **Logs structurés** : utilise `logging` Python avec format ISO timestamps. Niveau INFO par défaut, DEBUG si variable d'env `VERBOSE=1`. Logger vers `data/pipeline.log` ET stdout pour que GitHub Actions le capture.

- **Encodage** : tout en UTF-8. Forcer `# -*- coding: utf-8 -*-` en tête des fichiers Python n'est pas nécessaire en Python 3 mais s'assurer que les fichiers sont sauvegardés en UTF-8.

- **Localisation Python** : utiliser `locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')` pour avoir les dates en français dans les messages Telegram (ex: "10 juin" plutôt que "10 June"). Wrapper dans un try/except au cas où la locale ne serait pas disponible sur GitHub Actions (fallback : laisser en anglais, c'est OK).

- **Anti-saturation côté slugs ATS** : un slug peut être obsolète (entreprise a changé d'ATS, fermeture, etc.). Le pipeline doit gérer ça gracieusement. Optionnel mais bonus : maintenir un compteur "nb d'échecs consécutifs" par slug et le retirer automatiquement après 30 échecs.

---

## 8. Communication avec le commanditaire pendant l'exécution

- **Si tu rencontres un blocage technique réel** (ex: Cloudflare bloque tous les scrapings niches, ou un endpoint API change de format), arrête-toi, documente le problème, et demande arbitrage.

- **Si tu hésites sur un détail mineur** (nommage de fichier, format exact d'un message, choix entre deux bibliothèques équivalentes), tranche toi-même et documente ton choix dans le code ou le README. Ne déranges pas l'utilisateur pour ça.

- **À la fin de chaque phase majeure**, fais un point synthétique : ce qui est fait, ce qui reste, blocages éventuels.

- **Livrables intermédiaires** : tu peux pousser sur une branche `dev` au fur et à mesure. La branche `main` ne reçoit que du code testé et fonctionnel.

---

## 9. Annexes

### 9.1 Profil utilisateur consolidé (pour générer le scoring et les keywords)

Voir le bloc "PROFIL IA — MAËL MIKE ZINSOU" généré précédemment dans la conversation Claude.ai. Ce profil est la source de vérité pour les compétences, localisations cibles, écart d'expérience à adresser, etc.

### 9.2 Référentiel des outils déjà mis en place

| Outil | Statut | Rôle |
|-------|--------|------|
| Adzuna API | ✅ Configuré | Source agrégée internationale |
| France Travail API | ✅ Configuré | Source officielle FR exhaustive |
| Talent.io | ✅ Profil actif | Reverse sourcing |
| WTTJ alertes | ✅ Configurées | Push email scale-ups |
| APEC alertes | ✅ Configurées | Push email PME/ETI |
| Huntr | ✅ Compte + extension | Tracker visuel des candidatures |
| Telegram bot | ⏳ À créer par utilisateur | Notification quotidienne |
| GitHub Actions | ⏳ À configurer | Automatisation cron |

### 9.3 Setup Telegram (à faire par l'utilisateur en parallèle du dev)

1. Sur Telegram, parler à `@BotFather`
2. Commande `/newbot`, suivre les instructions, choisir un nom
3. BotFather donne un token au format `1234567890:ABCdefGHI...`
4. Envoyer un message quelconque à son nouveau bot
5. Récupérer son `chat_id` via `https://api.telegram.org/bot<TOKEN>/getUpdates` (chercher `"chat":{"id": 123456789}`)
6. Conserver `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` pour les GitHub Secrets

---

**Fin du brief.** Lance-toi par la Phase 1.
