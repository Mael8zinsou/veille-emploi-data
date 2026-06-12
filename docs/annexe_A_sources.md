# Annexe A — Sources & contrat d'interface

> Support de [`doc.md`](doc.md). Détaille le contrat commun des sources, puis chaque
> source individuellement (endpoint, parsing, résilience), et la gestion des slugs ATS.

---

## A.1 Contrat d'interface commun

Toute source vit dans `src/sources/<nom>.py` et expose **une seule fonction publique** :

```python
def fetch(config, session) -> list[Offre]:
    ...
```

- **`config`** : `SimpleNamespace` issu de `load_config("config/profil.yaml")`. Une source
  y lit ce dont elle a besoin (ex. `config.fraicheur_max_jours`).
- **`session`** : objet `requests.Session` produit par `build_session()`
  (retry + User-Agent partagés). La source ne crée jamais sa propre session.
- **Retour** : une `list[Offre]`. Vide (`[]`) si la source est sans credentials,
  désactivée, ou en échec — **jamais d'exception qui remonte** jusqu'à casser le pipeline.
- **Credentials** : lus dans l'environnement (`os.getenv`), **pas** dans le YAML.

Cette uniformité permet à `main.py` de traiter toutes les sources de façon identique :

```python
SOURCES = {
    "adzuna": adzuna.fetch, "france_travail": france_travail.fetch,
    "greenhouse": greenhouse.fetch, "lever": lever.fetch, "ashby": ashby.fetch,
    "hellowork": hellowork.fetch, "choose": choose.fetch,
}
```

Les sources actives sont déterminées par `config.sources_actives` (`profil.yaml`), ce qui
permet d'en désactiver une sans toucher au code.

---

## A.2 Sources « core » — APIs

### A.2.1 Adzuna (`adzuna.py`)

- **Type** : API REST agrégée. Free tier **250 requêtes/mois**.
- **Endpoint** : `https://api.adzuna.com/v1/api/jobs/fr/search/1`
- **Auth** : `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (query params).
- **Requêtes** : 4 par run (`data engineer`, `ingénieur données`, `analytics engineer`,
  `mlops`), 50 résultats/page, filtrées par `max_days_old = fraicheur_max_jours`.
- **Mapping** : `title`, `company.display_name`, `location.display_name`,
  `contract_type`/`contract_time`, `description` (tronquée 500), `redirect_url`, `created`.
- **Résilience** : credentials absents → `[]` ; HTTP ≥ 400 ou JSON invalide → log + `[]`.

### A.2.2 France Travail (`france_travail.py`)

- **Type** : API officielle FR, la plus exhaustive sur le territoire.
- **Auth** : OAuth2 *client_credentials* → token 24 h. `FT_CLIENT_ID` + `FT_CLIENT_SECRET`,
  scope `api_offresdemploiv2 o2dsoffre`.
- **Endpoints** : token sur `entreprise.francetravail.fr/.../access_token` (POST),
  recherche sur `api.francetravail.io/partenaire/offresdemploi/v2/offres/search` (GET).
- **Correctif clé** : l'API **exige `minCreationDate` ET `maxCreationDate` ensemble**
  (ISO 8601), sinon HTTP 400. Hérité de la V2, conservé.
- **Requêtes** : 3 (`data engineer`, `ingénieur données`, `data`), `range` 0–149,
  `typeContrat = CDI,CDD,MIS,LIB`.
- **Statuts gérés** : 200/206 = ok, 204 = aucun résultat, autres = log + `[]`.

---

## A.3 Sources « core » — ATS (mode *discovery*)

Les trois ATS partagent un même schéma, factorisé dans **`_ats_common.py`** :

- `localisation_pertinente(loc)` : `True` si la localisation (normalisée) évoque la
  France, la Belgique ou un poste remote (liste de *hints* : `paris`, `france`, `lyon`,
  `bruxelles`, `remote`, `teletravail`, …). Une localisation vide est rejetée.
- `slugs_pour(ats, slugs)` : filtre la liste `(ats, slug)` pour un ATS donné.
- `pause_polie()` : `time.sleep(0.2)` entre slugs (politesse, cf. doc §4.3).

Chaque source ATS lit elle-même `config/slugs_ats.txt` via `load_slugs`, itère sur ses
slugs, et pour chacun : requête JSON → parse → filtre localisation → `Offre`. **Un slug
en erreur (404, JSON inattendu) est journalisé en `debug` et la boucle continue.**

### A.3.1 Greenhouse (`greenhouse.py`)

- **Endpoint** : `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- **Réponse** : `{"jobs": [...]}`. Localisation dans `location.name`.
- **Mapping** : `title`, entreprise = `slug` (le nom légal n'est pas exposé),
  `content` (description), `absolute_url`, `updated_at`.

### A.3.2 Lever (`lever.py`)

- **Endpoint** : `https://api.lever.co/v0/postings/{slug}?mode=json`
- **Réponse** : **liste** de postings. Localisation dans `categories.location`.
- **Mapping** : `text` (titre), `categories.commitment` (contrat), `descriptionPlain`,
  `hostedUrl`. Date non fiable (epoch ms) → laissée vide.

### A.3.3 Ashby (`ashby.py`)

- **Endpoint** : `https://api.ashbyhq.com/posting-api/job-board/{slug}` (public, non
  documenté officiellement mais stable).
- **Réponse** : `{"jobs": [...]}`.
- **Schéma réel** (vérifié live, ≠ brief) : champ **`location`** (pas `locationName`),
  **`publishedAt`**, et **flag `isRemote`**. Un poste `isRemote = true` est conservé même
  si la chaîne `location` ne mentionne pas la France (souvent « Remote »).
- **Mapping** : `title`, `location`/fallback `locationName`, `employmentType`,
  `descriptionPlain`, `jobUrl`/fallback `applyUrl`, `publishedAt`/fallback `publishedDate`.
- **Pas de fallback HTML** (brief §4.6) : si le JSON ne répond pas, on log et on passe.

---

## A.4 Sources « niches » (désactivables)

### A.4.1 HelloWork (`hellowork.py`) — scraping HTML

- **Page** : `https://www.hellowork.com/fr-fr/emploi/recherche.html?k={mots}&l={lieu}`
- **Insight clé** : les offres sont dans le **HTML statique**. Chaque carte est une ancre
  `<a>` portant le lien **et** un `aria-label` très structuré :
  > *« Voir offre de **Data Engineer H/F** à **Paris 17e - 75**, chez **Team.is**, super
  > recruteur, pour un **CDI**, en temps plein »*

  On parse cet `aria-label` (plus stable que des classes CSS générées). Deux regex :
  une pour extraire `(href, label)`, une pour décomposer le label en
  `titre / lieu / entreprise / contrat / temps`.
- **Requêtes** : `(data engineer, Paris)`, `(data engineer, Lyon)`, `(analytics engineer, Paris)`.
- **Garde-fous (brief §4.7)** : max **3 pages**/recherche, **2 s** entre pages, User-Agent
  navigateur. Détection de blocage (HTTP 403/429/503 ou marqueurs Cloudflare/captcha) →
  **coupe la source pour ce run**, sans crash. `try/except` global par recherche.
- **Limite** : ni `description` ni `date_publication` sur la page liste (cf. doc §4.1).

### A.4.2 Choose (`choose.py`) — no-op assumé

- **Statut** : **désactivée**. SPA React, offres rendues uniquement après JS.
  Sondage : `api.choose.app` n'existe pas (DNS), pas de `__NEXT_DATA__`, routes `/jobs`
  en 404. Extraction nécessiterait un navigateur headless → hors périmètre.
- **Implémentation** : `fetch` retourne `[]` avec un log, et un `# TODO` documente les
  conditions de réactivation. Conforme au brief §4.8.

---

## A.5 Gestion des slugs ATS (`config/slugs_ats.txt`)

- **Format** : une ligne `<ats>:<slug>` (ex. `greenhouse:doctolib`). Lignes vides et
  commentaires (`#`) ignorés. Lu par `load_slugs()`.
- **État actuel** : **67 slugs** (greenhouse 28, ashby 24, lever 15), répartis en deux
  sections commentées : **« vérifiés live »** (board accessible au 2026-06-11) et
  **« filet »** (FR notoires potentiellement obsolètes, 404 gérés gracieusement).
- **Pourquoi un filet d'entrées mortes ?** Un slug peut « revivre » (l'entreprise revient
  sur l'ATS, rouvre des postes). Le coût d'un slug mort est ~200 ms + un log debug : on
  l'accepte pour ne pas perdre une entreprise au premier 404.
- **Rafraîchissement** : `scripts/decouvrir_slugs.py` interroge DuckDuckGo HTML avec des
  requêtes ciblées (`site:boards.greenhouse.io "France" data engineer`, etc.), extrait
  les slugs des URLs trouvées, dédoublonne contre l'existant. Lancé **manuellement**
  (`--write` pour ajouter au fichier), **jamais dans le cron** (risque de blocage moteur).

---

## A.6 Résumé de la résilience par source

| Source | Échec credentials | Échec réseau / HTTP | Réponse inattendue |
|---|---|---|---|
| Adzuna | `[]` + log | log + `[]` | `data.get("results", [])` → `[]` |
| France Travail | `[]` + log | log + `[]` (gère 204) | idem sur `resultats` |
| Greenhouse/Lever/Ashby | n/a | slug ignoré (log debug), boucle continue | type vérifié (dict/list) → `[]` |
| HelloWork | n/a | blocage → coupe la source ; erreur → `try/except` | label non parsé → ignoré |
| Choose | n/a | n/a (no-op) | n/a |

Garantie globale : **aucune source ne peut interrompre le pipeline** (critère
d'acceptation #5). Le `try/except` de `main.py` est la dernière ligne de défense.
