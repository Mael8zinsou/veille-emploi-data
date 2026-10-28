# Veille emploi : métiers de la data, profil junior

Pipeline autonome qui collecte les offres d'emploi data (Data Engineer, Data Analyst,
Data Scientist et métiers voisins) publiées en France, écarte ce qui ne correspond pas à un
profil junior, dédoublonne d'une source et d'un jour à l'autre, note chaque offre et
prévient sur **Telegram** : alerte immédiate pour les meilleures, résumé quotidien pour les
autres, bilan chaque lundi. Les offres retenues alimentent aussi un fichier de suivi Google
Sheets. Tout tourne sur **GitHub Actions**, sans serveur.

> Projet personnel, conçu pour outiller ma propre recherche de premier poste. Version 2,
> en service depuis le 26/10/2026. Le besoin et la conception sont décrits dans
> [`docs/cahier_des_charges_v2.md`](docs/cahier_des_charges_v2.md) et
> [`docs/conception_v2.md`](docs/conception_v2.md).

---

## Fonctionnement

```
 cron-job.org, toutes les heures (cron GitHub en secours)
        │  workflow_dispatch
        ▼
   src/main.py : un passage
        │
        ├── planning : quelles sources sont dues (intervalles, plage horaire, quota Adzuna)
        ├── sources : France Travail · Adzuna · HelloWork · Choisir le service public
        │             · La bonne alternance            (une panne n'arrête jamais le passage)
        ▼
   normalisation : métier reconnu, contrat, type d'employeur (ESN, cabinet, école…)
        ▼
   filtres : métier hors cible, séniorité, stage déguisé en CDI, lieu, fraîcheur…
        ▼
   dédoublonnage : dans le passage (clé souple) puis avec les 30 derniers jours
                   (clé souple ou empreinte de la description)
        ▼
   notation : priorité du métier, compétences, niveau d'expérience, employeur,
              entreprises suivies, signaux (fraîcheur, republication, peu de candidats)
        ▼
   SQLite (cache Actions) ─▶ Telegram (alerte, résumé, bilan) ─▶ Google Sheets (onglet Veille)
```

### Dédoublonnage

Une même offre revient souvent sous un titre légèrement différent (« Data Scientist (H/F)
AEROMIN », « Data Engineer … F/H (CDI) ») ou sur plusieurs sources. Trois clés :

* `cle` : employeur et titre normalisés, identifiant stable de l'offre en base ;
* `cle_souple` : même calcul sur le titre débarrassé des mentions de genre, du type de
  contrat et d'un code interne final ; elle regroupe les variantes d'un même passage ;
* `empreinte` : employeur et 500 premiers caractères de la description, quand celle-ci
  est assez longue ; elle rattrape une offre republiée sous un autre titre.

Une offre inconnue dont la clé souple ou l'empreinte correspond à une offre vue depuis
moins de 30 jours n'est pas présentée à nouveau.

### Signaux affichés

Sans changer la note, l'alerte Telegram et la colonne « Signaux » du suivi indiquent :
permis B exigé, offre publiée par un cabinet de recrutement, description partielle
(Adzuna ne livre qu'un extrait : l'expérience demandée est à vérifier sur l'offre).

---

## Sources

| Source | Accès | Fréquence | Note |
|---|---|---|---|
| **France Travail** | API officielle (OAuth2) | environ toutes les heures | codes ROME et mots-clés, emploi et alternance |
| **Adzuna** | API | une fois par jour | quota gratuit de 250 requêtes par mois, plafonné à 220 |
| **HelloWork** | page de recherche publique | toutes les 3 heures | délai entre pages, arrêt propre en cas de blocage |
| **Choisir le service public** | flux RSS publics | toutes les 2 heures | page de l'offre lue une seule fois pour l'employeur |
| **La bonne alternance** | API publique (clé) | 3 fois par jour | fil alternance |

Hors périmètre : LinkedIn, Indeed, Welcome to the Jungle (alertes natives déjà en place),
APEC (accès refusé depuis octobre 2026, non contourné).

---

## Configuration

Tout ce qui dépend du profil est dans `config/`, validé au chargement (pydantic) :

| Fichier | Contenu |
|---|---|
| `metiers.yaml` | familles de métiers et priorités, exclusions de titre |
| `filtres.yaml` | fraîcheur, lieux, contrats, séniorité, ESN, cabinets, écoles |
| `notation.yaml` | barème et seuils d'alerte et de résumé |
| `sources.yaml` | sources actives et requêtes envoyées |
| `planning.yaml` | fuseau, plage horaire, intervalles, quotas, heures des envois |
| `telegram.yaml` | groupe et sujets par fil (emploi, alternance, immersion) |

Variables d'environnement (secrets GitHub en production) : `FT_CLIENT_ID`,
`FT_CLIENT_SECRET`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `LBA_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `GOOGLE_TOKEN_JSON`, `SUIVI_SHEET_ID`. Une source sans identifiants
est ignorée. `VEILLE_ENVOI=simulation` et `VEILLE_SUIVI=essai` permettent un passage sans
rien envoyer ni écrire.

---

## Développement

```bash
pip install -r requirements.txt
pytest -q --cov=src      # seuil de couverture : 90 %
ruff check src tests
```

Workflows : `veille.yml` (production), `v2_essai.yml` (essai réel sur une branche, sans
envoi), `ci.yml` (tests et lint), `comparaison.yml` et `evaluation.yml` (mesures).

```
src/
├── main.py            # un passage : collecte, filtres, dédoublonnage, notation, envois
├── models.py          # dataclass Offre, clés de dédoublonnage
├── config.py          # chargement et validation de config/*.yaml
├── filtres.py         # normalisation des offres et motifs de rejet
├── dedoublonnage.py   # fusion des variantes d'un même passage
├── notation.py        # note et niveau (alerte, résumé)
├── planning.py        # sources dues, quotas, heures des envois
├── stockage.py        # SQLite versionnée (schéma 3)
├── normalisation/     # texte, métiers, contrats, employeurs
├── sorties/           # telegram.py, sheets.py, suivi.py
└── sources/           # un module par source : NOM + fetch(ctx) -> list[Offre]
```

Le pipeline n'envoie aucune candidature et ne rédige rien : il trie, la candidature reste
manuelle.
