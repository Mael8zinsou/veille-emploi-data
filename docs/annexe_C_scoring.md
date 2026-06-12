# Annexe C — Scoring & dédoublonnage

> Support de [`doc.md`](doc.md). Détaille les algorithmes du module `src/scoring.py` et
> la clé d'unicité de `src/models.py` : clé d'unicité, filtrage profil, fusion
> cross-source, scoring et **détection de saturation**. Tous les poids sont configurables
> dans `config/profil.yaml` — aucun n'est codé en dur.

---

## C.1 Clé d'unicité (`compute_cle_unique`)

But : reconnaître la **même offre** vue sur deux sources malgré des variations mineures
(casse, accents, espaces).

```
cle_unique = SHA256( normalise(entreprise) + "|" + normalise(titre)[:50] )[:16]
```

où `normalise(x)` = retrait des accents (NFD + filtrage des marques diacritiques),
minuscule, *strip*.

- **Pourquoi tronquer le titre à 50 caractères** : neutraliser les suffixes variables
  (« H/F », « - Paris », « (CDI) ») qui diffèrent d'une source à l'autre pour un même poste.
- **Pourquoi 16 caractères de hash** : largement assez pour éviter les collisions à cette
  volumétrie, tout en restant compact comme clé primaire SQLite.
- **Propriété** : déterministe (même entrée → même clé), donc réutilisable comme identité
  stable entre runs (c'est elle qui pilote le « déjà vu »).

> ⚠️ Compromis assumé : deux postes **réellement différents** portant le même intitulé
> court dans la même entreprise (ex. deux « Data Engineer » sur des équipes distinctes)
> seraient fusionnés. C'est rare et préférable au bruit inverse (notifier deux fois la
> même offre). Voir limitations, [`doc.md`](doc.md) §4.

---

## C.2 Filtrage par profil (`filtre_par_profil`)

Une offre est **gardée** si les trois conditions sont vraies :

1. **Mot-clé must-match** : au moins un terme de `mots_cles_must_match` apparaît dans
   `titre + description` (insensible à la casse).
2. **Pas d'exclusion de titre** : aucun terme de `exclusions_titre` (`senior`, `lead`,
   `staff`, `architect`, `5 ans`, **`alternance`**, **`apprentissage`**…) n'apparaît dans
   le **titre**. Les contrats d'études (alternance/apprentissage) sont écartés car hors
   cible CDI/CDD.
3. **Localisation non exclue** : la localisation (normalisée) ne contient **aucun** lieu
   étranger listé dans `exclusions_localisation` (Berlin, London, New York…). **Logique
   inversée** : on couvre **toute la France** (+ Belgique + remote) par défaut, donc on ne
   liste pas les lieux acceptés (impossible d'énumérer toutes les communes) mais seulement
   ceux à rejeter. Une localisation vide ou générique est donc gardée.

Le filtrage est volontairement **textuel et simple** : transparent, débogable, et entièrement
piloté par le YAML.

> **Note sur les deux filtres de localisation.** `filtre_par_profil` (ci-dessus) couvre
> toute la France via une liste d'**exclusion**. Les sources ATS, elles, appliquent en
> amont une liste d'**inclusion** (`_ats_common.localisation_pertinente`) car elles
> interrogent des entreprises internationales : sans ce garde-fou, Greenhouse/Ashby
> noieraient le flux sous des offres US. Les deux couches sont complémentaires.

---

## C.3 Dédoublonnage et fusion cross-source (`dedoublonne_et_fusionne`)

Regroupe les offres par `cle_unique` et produit **une** offre par clé :

- **Version conservée** : celle qui a la **description la plus longue** (la plus riche,
  donc la mieux scorable).
- **`sources_list`** : union ordonnée des sources distinctes où l'offre a été vue.
- **`nb_sources`** : `len(sources_list)` — c'est l'entrée de la détection de saturation.

Exemple : une offre vue sur Greenhouse (desc. courte) **et** Adzuna (desc. longue) →
1 offre, `nb_sources = 2`, on garde la description Adzuna.

> Note : une même source vue deux fois ne compte qu'une fois (`nb_sources` reste 1) — le
> comptage porte sur des sources **distinctes**.

---

## C.4 Scoring (`score_offre` / `score_toutes`)

Le score d'une offre = somme de quatre contributions, toutes paramétrées dans
`profil.yaml > scoring`.

### C.4.1 Bonus « signaux junior »
Termes présents dans `titre + description`, ex. (poids) :
`junior` (+3), `graduate` (+3), `premier emploi` (+3), `débutant` (+3),
`mentorat` (+2), `formation` (+2), `première expérience` (+2), `0-2 ans` (+2)…

> `alternance`/`apprenti` ne sont **plus** dans le bonus : ces offres sont désormais
> exclues au filtrage (cf. C.2), il serait contradictoire de les valoriser.

### C.4.2 Bonus « stack »
Technos du profil, ex. (poids) :
`airflow` (+3), `dbt` (+3), `snowflake` (+3), `mlops` (+3), `python` (+2), `sql` (+2),
`spark`/`pyspark` (+2), `docker` (+2), `aws`/`gcp` (+2), `kafka` (+2), `fastapi` (+2),
`github actions` (+2), `ci/cd` (+2), `kubernetes` (+1), `azure` (+1)…

### C.4.3 Malus ESN / conseil
Signaux d'une société de service (souvent moins junior-friendly) :
`esn ` (-2), `société de conseil` (-2), `consultant` (-2). Un tag `⚠ ESN/conseil` est posé.

### C.4.4 Saturation (le cœur de la valeur ajoutée)

Hypothèse métier : **plus une offre est présente sur de sources, plus elle est déjà
bombardée de candidatures** ; une offre **exclusive** est une pépite potentielle.

| `nb_sources` | Effet sur le score | Intention |
|---|---|---|
| **1** | `+ bonus_source_unique` (**+5**), tag `exclusif` | valoriser la pépite |
| **2 ou 3** | neutre | zone grise |
| **≥ 4** | `+ malus_par_source_supplementaire × (nb_sources − 1)` (**−3 × (n−1)**) | déclasser le saturé |

Exemple : `nb_sources = 5` → `-3 × 4 = -12` (et **pas** de bonus exclusif). Une offre
exclusive bien matchée passe ainsi devant une offre omniprésente.

### C.4.5 Tri final
`score_toutes` calcule tous les scores puis trie **par score décroissant**. `main.py`
applique ensuite le seuil `telegram.score_minimum` (5) et coupe au `top_n_par_jour` (30).
Les tags sont dédoublonnés en conservant l'ordre d'apparition.

---

## C.5 Détail d'implémentation : lecture des poids

Les sous-tables de scoring sont des `SimpleNamespace` après chargement YAML. On les relit
en `dict` via `vars()` (helper `_as_dict`) car certaines **clés contiennent des caractères
spéciaux** incompatibles avec l'accès par attribut : `"ci/cd"`, `"esn "` (espace final
significatif), `"première expérience"`. Le matching se fait en minuscule, en ignorant les
clés vides.

---

## C.6 Où ajuster le comportement (sans toucher au code)

Tout est dans `config/profil.yaml` :

- **Réintégrer les alternances ?** Les retirer de `exclusions_titre` (et, si on veut les
  valoriser, les remettre dans `bonus_signaux_junior`).
- **Privilégier certaines technos** : augmenter leur poids dans `bonus_stack`.
- **Restreindre la zone géographique** : ajouter des lieux à `exclusions_localisation`
  (la couverture est « toute la France » par défaut — on retire, on n'ajoute pas).
- **Être plus/moins sélectif** : ajuster `telegram.score_minimum` et `top_n_par_jour`.
- **Régler la sensibilité à la saturation** : `bonus_source_unique` et
  `malus_par_source_supplementaire`.

Un simple `git commit` + `git push` redéploie ces réglages (le workflow lit le YAML à
chaque run).
