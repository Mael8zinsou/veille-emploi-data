# Annexe D — Déploiement, automatisation & exploitation

> Support de [`doc.md`](doc.md). Décrit le workflow GitHub Actions, la persistance SQLite
> par cache, la gestion des secrets, la procédure de mise en production (réalisée), et la
> maintenance courante.

---

## D.1 Le workflow `veille.yml` étape par étape

| Étape | Action | Rôle |
|---|---|---|
| `Checkout` | `actions/checkout@v4` | Récupère le code. |
| `Setup Python` | `actions/setup-python@v5` (3.11, `cache: pip`) | Python + cache des deps pip. |
| `Install dependencies` | `pip install -r requirements.txt` | Installe les 4 paquets. |
| `Restore SQLite cache` | `actions/cache/restore@v4` | Restaure la base de la veille (voir D.2). |
| `Lance le pipeline` | `python -m src.main` | Exécute la veille (secrets injectés en env). |
| `Save SQLite cache` | `actions/cache/save@v4`, `if: always()` | Sauvegarde la base mise à jour. |
| `Upload logs si échec` | `actions/upload-artifact@v4`, `if: failure()` | Diagnostic post-mortem. |

### Déclencheurs
- **`schedule: '0 6 * * *'`** — cron quotidien à **6h UTC** (= 7h Paris l'hiver, 8h l'été ;
  GitHub cron est toujours en UTC).
- **`workflow_dispatch`** — déclenchement **manuel** depuis l'onglet Actions ou
  `gh workflow run veille.yml`.

### Garde-fous
- **`concurrency: { group: veille-emploi, cancel-in-progress: false }`** — empêche deux
  runs (ex. cron + manuel) de tourner en même temps et de se marcher sur la base.
- **`permissions: contents: read`** — moindre privilège : le job ne peut pas écrire dans
  le dépôt.
- **`DRY_RUN: '0'`** explicite — envoi Telegram réel en prod.
- **`PYTHONIOENCODING: 'utf-8'`** — évite tout souci d'encodage des emojis dans les logs.

---

## D.2 Persistance SQLite via cache (le point subtil)

### Le problème
La base `data/offres.sqlite` doit **survivre d'un run à l'autre** (sinon chaque matin
renotifierait tout). Sur des runners éphémères, il faut un stockage externe. Deux options :
commit auto sur une branche `data`, ou **cache Actions**. On a choisi le cache (pas de
pollution de l'historique git).

### Pourquoi pas la recette « naïve »
Le cache GitHub est **immuable par clé** : une clé déjà écrite n'est jamais réécrite.
- Une **clé fixe** (`veille-db`) serait écrite au 1ᵉʳ run puis **jamais mise à jour** → la
  base resterait figée au jour 1.
- L'action combinée `actions/cache` ne sauvegarde qu'en *cache miss* en fin de job, ce qui
  se combine mal avec une clé fixe.

### La solution retenue
Séparer **restore** et **save**, avec une **clé datée unique** + **restore-keys** par préfixe :

```yaml
# Restauration : prend le cache le plus récent commençant par "veille-db-"
- uses: actions/cache/restore@v4
  with:
    path: data/
    key: veille-db-${{ github.run_id }}   # clé exacte (n'existera pas encore)
    restore-keys: |
      veille-db-                          # → fallback : dernier cache "veille-db-*"

# Sauvegarde : clé datée unique → toujours un nouvel upload, jamais bloqué
- uses: actions/cache/save@v4
  if: always()
  with:
    path: data/
    key: veille-db-${{ github.run_id }}
```

- À chaque run, `restore-keys: veille-db-` récupère **le cache le plus récent** du préfixe
  (donc la base de la veille).
- La sauvegarde utilise `run_id` (unique) → **toujours** un nouvel enregistrement, jamais
  rejeté pour cause de clé existante.
- `if: always()` sur le save → on **n'oublie pas** de mémoriser les offres vues même si
  l'envoi Telegram a échoué (sinon elles seraient renotifiées le lendemain).

> **Vérifié en prod** : `Cache saved with key: veille-db-<run_id>` (base ~14 KiB).
> Le run suivant restaure et ne notifie que les nouveautés.

> **Rétention** : GitHub évince les caches après ~7 jours d'inactivité et au-delà de 10 Go
> par dépôt. Pour cette base de quelques Ko et un run quotidien, c'est sans incidence.

---

## D.3 Secrets

Six secrets, configurés sur le dépôt (`Settings → Secrets and variables → Actions`) :

| Secret | Source |
|---|---|
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | developer.adzuna.com |
| `FT_CLIENT_ID`, `FT_CLIENT_SECRET` | francetravail.io (app partenaire) |
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `TELEGRAM_CHAT_ID` | `getUpdates` du bot |

Pose en ligne de commande (les valeurs passent par stdin, jamais dans `argv`/logs) :

```bash
gh secret set ADZUNA_APP_ID --repo <owner>/<repo> --body "<valeur>"
# ... idem pour les 6 ...
gh secret list --repo <owner>/<repo>   # vérifie les noms (valeurs invisibles)
```

> Le pipeline tourne **même sans Adzuna/FT** (ces sources renvoient `[]` proprement) ;
> seuls Telegram sont requis pour la notification. Les ATS et HelloWork ne demandent
> aucun credential.

---

## D.4 Procédure de mise en production (réalisée le 2026-06-12)

1. **Bot Telegram** : `@BotFather` → `/newbot` → token. Envoyer un message au bot, puis
   `getUpdates` pour lire le `chat_id`.
2. **Test local** : remplir `.env`, `python -m src.main` (DRY_RUN=0) → notif reçue.
3. **Push** : `git push origin main` (tout le code).
4. **Secrets** : `gh secret set …` ×6.
5. **Run de validation** : `gh workflow run veille.yml` → suivre avec
   `gh run watch` / `gh run view <id> --log`.
6. **Vérifs** : run *success*, notif Telegram reçue, `Cache saved with key …` présent.

Résultat observé : 2262 offres brutes → 15 notifiées ; cache écrit. ✅

---

## D.5 Exploitation et maintenance

### Surveiller
- **Onglet Actions** : un run vert par jour. En cas d'échec, l'artefact `pipeline-logs`
  contient `data/pipeline.log`.
- **`gh run list --workflow veille.yml`** pour l'historique en CLI.

### Tâches périodiques
- **Rafraîchir les slugs ATS** (mensuel conseillé) :
  ```bash
  python scripts/decouvrir_slugs.py            # prévisualise
  python scripts/decouvrir_slugs.py --write     # ajoute à config/slugs_ats.txt
  git commit -am "slugs: rafraîchissement" && git push
  ```
- **Ajuster le profil** : éditer `config/profil.yaml` (mots-clés, poids, seuils), commit,
  push. Pris en compte au run suivant (cf. [Annexe C](annexe_C_scoring.md) §C.6).

### Incidents courants
| Symptôme | Cause probable | Action |
|---|---|---|
| Aucune notif le matin | run échoué / pas de nouvelles offres | voir Actions ; un message « jour vide » est normal s'il n'y a rien. |
| Notif répète d'anciennes offres | cache SQLite non restauré | vérifier l'étape *Restore* et que `restore-keys` matche. |
| HelloWork = 0 offre | blocage Cloudflare | normal et géré ; la source se coupe pour ce run sans casser le pipeline. |
| Beaucoup de slugs 404 | ATS migrés | lancer `decouvrir_slugs.py`. |
| Quota Adzuna proche | trop de requêtes | réduire les requêtes dans `adzuna.py` ou la fréquence. |

### Réactiver Choose
Source en no-op (cf. [Annexe A](annexe_A_sources.md) §A.4.2). La réactiver suppose
d'identifier une API JSON stable ou d'évaluer un fetch *headless* dédié, **hors** cron.

---

## D.6 Coûts

- **GitHub Actions** : gratuit pour un dépôt personnel (le job dure ~1 min/jour).
- **Adzuna** : free tier (250 req/mois ; usage ~120/mois).
- **France Travail / Telegram / ATS** : gratuits.

Le projet tourne donc à **coût nul** dans les limites des offres gratuites.
