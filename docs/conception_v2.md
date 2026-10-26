# Conception : refonte v2 de la veille emploi

> Statut : **proposition à valider**, 25 octobre 2026. Traduit en choix techniques le
> [cahier des charges validé](cahier_des_charges_v2.md). Les renvois « CDC § n » pointent vers lui.

## 1. Vue d'ensemble

Un **passage** est une exécution du pipeline. Il a lieu toutes les heures de 7h à 22h (heure de
Paris) et enchaîne :

1. **Planification** : quelles sources interroger, quels envois sont dus (résumé, bilan, alertes
   de la nuit).
2. **Lecture du suivi** : verdicts de l'onglet Entreprises, cases « Retenir » cochées dans
   l'onglet Veille.
3. **Collecte** des sources dues, chacune isolée.
4. **Normalisation** : fil, famille de métier, contrat, durée, lieu, type d'employeur.
5. **Filtres** : une offre éliminée devient un **rejet** enregistré avec son motif.
6. **Dédoublonnage** entre sources et contre la base.
7. **Note** détaillée en composantes, puis **niveau** : alerte, résumé ou archive.
8. **Enregistrement** en base.
9. **Sorties** : alertes Telegram, ajout à l'onglet Veille, transfert des offres retenues vers
   Candidatures, ajout des cibles Route B, résumés et bilan s'ils sont dus.

Tout ce qui varie (métiers, exclusions, poids, seuils, horaires, requêtes) vit dans `config/`.

## 2. Planification

### 2.1 Un déclencheur simple, une logique dans le code

GitHub Actions ne connaît que l'heure UTC et part en retard. Le workflow se déclenche donc
**toutes les heures à la minute 17** sur une large plage UTC, et c'est `src/planning.py` qui
décide, en heure de Paris, ce qui est dû. Ce choix rend le changement d'heure transparent et
tolère les passages en retard ou sautés.

La règle n'est jamais « est-il 8h pile ? » mais « le dernier passage réussi de cette tâche
date-t-il de plus de N heures, et sommes-nous dans la plage autorisée ? ». Les dates des
derniers passages sont en base (table `executions`).

| Tâche | Condition | Valeur initiale |
|---|---|---|
| France Travail, APEC, HelloWork | Dernier succès il y a plus de 50 min, entre 7h et 22h | Chaque passage |
| Adzuna | Dernier succès il y a plus de 4 h, entre 7h et 22h, quota mensuel non atteint | 3 par jour |
| La bonne alternance | Dernier succès il y a plus de 8 h | 2 par jour |
| Immersion | Dernier succès il y a plus de 6 jours | 1 par semaine |
| Résumé quotidien | Pas encore envoyé aujourd'hui, à partir de 18h | 1 par jour et par fil |
| Bilan hebdomadaire | Pas encore envoyé cette semaine, lundi à partir de 8h | 1 par semaine |
| Alertes en attente | Premier passage à partir de 7h | Chaque matin |

Une fonction pure, `taches_dues(maintenant, historique, config)`, rend la liste des tâches. Elle
se teste sans horloge réelle.

### 2.2 Quota Adzuna

Chaque requête Adzuna est comptée en base. Au-delà de 220 requêtes dans le mois civil, Adzuna
n'est plus interrogée jusqu'au mois suivant et le bilan le signale. Deux requêtes par passage
regroupent les intitulés de priorité 1, puis ceux de priorité 2, par le paramètre de mots-clés
alternatifs de l'API (à confirmer au sondage).

## 3. Structure du code

```
src/
  main.py               un passage complet, rien d'autre
  planning.py           taches_dues(), fonction pure
  config.py             chargement et validation de config/*.yaml (pydantic)
  models.py             Offre, Rejet, Note, énumérations Fil, Contrat, TypeEmployeur, Niveau
  normalisation/
    metiers.py          titre -> famille et priorité
    contrats.py         libellés de chaque source -> Contrat, durée en mois, Fil
    employeurs.py       nom -> TypeEmployeur (final, ESN, intermédiaire, plateforme, école, inconnu)
    lieux.py            France métropolitaine, télétravail, étranger, zones préférées
    texte.py            normalisation commune (accents, casse, frontières de mots)
  filtres.py            Offre -> Rejet ou None
  dedoublonnage.py
  notation.py           Offre -> Note (total et liste de composantes)
  routage.py            Note + Offre -> Niveau
  stockage.py           SQLite, schéma versionné, migrations
  suivi.py              lecture de l'onglet Entreprises et des cases Retenir
  sources/
    adzuna.py  france_travail.py  apec.py  hellowork.py
    (lot 5 : la_bonne_alternance.py, choisir_service_public.py, passerelles.py,
     engagement_jeunes.py, immersion.py)
  sorties/
    telegram.py         alertes, résumés, bilan, sujets du groupe
    sheets.py           client Google Sheets minimal et écritures sûres
    veille_sheet.py     onglet Veille, transfert vers Candidatures, cibles Route B
config/
  metiers.yaml  filtres.yaml  notation.yaml  planning.yaml  sources.yaml
scripts/
  sonde.py              sondage d'une source (§ 9)
  telegram_ids.py       affiche l'identifiant du groupe et des sujets
  echantillon_annotation.py   prépare le jeu à annoter
  evaluer_tri.py        mesure le tri sur le jeu annoté
  audit_stats.py        conservé, adapté au schéma v2
eval/
  annotations.csv  incontournables.csv  REPORT.md
tests/
  fixtures/<source>/    réponses réelles capturées au sondage
```

Contrat des sources (mis en œuvre au lot 1) : chaque module expose `NOM` et
`fetch(ctx: Contexte) -> list[Offre]`. Le contexte porte la configuration, la session HTTP et
l'heure du passage, et compte les requêtes et les erreurs. Une source interroge elle-même les
fils qu'elle sert et renseigne `Offre.fil_demande`. Elle lève `SourceIndisponible` quand un
accès manque ou que toutes ses requêtes échouent.

Les sources Greenhouse, Lever, Ashby, Teamtailor et Choose, `slugs_ats.txt` et
`decouvrir_slugs.py` sont supprimés.

## 4. Modèle de données

### 4.1 L'offre

| Champ | Type | Origine |
|---|---|---|
| `source`, `id_source` | texte | Source |
| `titre`, `entreprise`, `lieu`, `description`, `url` | texte | Source |
| `contrat_brut`, `date_publication` | texte | Source |
| `faible_concurrence` | booléen | APEC |
| `contrat`, `duree_mois`, `fil` | énumération, entier | Normalisation |
| `famille`, `priorite` | texte, 1 à 3 | Normalisation |
| `type_employeur`, `zone_preferee`, `teletravail` | énumération, booléens | Normalisation |
| `cle` | texte | Calculée |

La **clé de dédoublonnage** reste celle de la v1 (entreprise normalisée et 50 premiers caractères
du titre, empreinte SHA-256 sur 16 caractères), avec une exception : quand l'entreprise est
absente, la clé utilise le titre et le lieu, pour ne pas fusionner toutes les offres anonymes de
même intitulé.

### 4.2 La note

Une `Note` contient un total et la liste de ses composantes `(raison, points)`. Les deux ou trois
composantes les plus fortes apparaissent dans le message Telegram et dans l'onglet Veille. Une
note n'est jamais un nombre opaque.

### 4.3 La base SQLite

| Table | Contenu | Usage |
|---|---|---|
| `offres` | Offres retenues : champs normalisés, note, composantes, niveau, état d'envoi, date d'ajout à l'onglet Veille, première et dernière détection | Déjà vu, alertes, résumés, republications |
| `rejets` | Clé, source, titre, entreprise, type d'employeur, motif, lien, date | Mesure des oublis, cibles Route B |
| `executions` | Tâche, début, fin, nombre d'offres, erreur, requêtes consommées | Planification, quota Adzuna, bilan, pannes |
| `envois` | Type (alerte, résumé, bilan), fil, date | Un seul résumé par jour et par fil |
| `route_b` | Entreprise normalisée, date d'ajout | Jamais deux fois la même cible |
| `version_schema` | Numéro | Migrations |

**Migration depuis la v1** : les clés de `offres_vues` sont importées comme « déjà vues ». Sans
cela, le premier passage v2 renverrait tout l'historique. La purge passe de 90 à 180 jours pour
détecter les republications à 30 jours et plus.

## 5. Normalisation et filtres

### 5.1 Reconnaissance du métier

`config/metiers.yaml` décrit chaque famille par une priorité et des motifs de titre. Les motifs
sont comparés sur le titre normalisé, **avec frontières de mots** : « IA » ne doit pas
reconnaître « média », ni « ML » « HTML ». Un titre qui ne correspond à aucune famille est
rejeté avec le motif `metier_hors_cible`.

### 5.2 Contrat et fil

Chaque source a sa table de correspondance (codes APEC, `typeContrat` et `natureContrat` de
France Travail, `contract_type` d'Adzuna, libellés HelloWork). Le titre complète la source
(« alternance », « apprenti » dans un titre classent en Alternance même si la source dit CDD).

| Contrat normalisé | Fil |
|---|---|
| CDI | Emploi |
| CDD, intérim d'au moins 6 mois ou de durée inconnue | Emploi |
| CDD, intérim de moins de 6 mois | Rejet `duree_trop_courte` |
| Apprentissage, professionnalisation | Alternance |
| Immersion | Immersion |
| Stage conventionné | Rejet `stage_conventionne` |
| Freelance, mission | Rejet `freelance` |

### 5.3 Employeur

`config/filtres.yaml` liste les plateformes de missions (rejet), les intermédiaires et
républicateurs (cadremploi, Handicap Job, Hellowork, Collective sous toutes ses graphies,
Direct Emploi, Jobgether, Meteojob…), les ESN, et les écoles connues pour publier des offres
d'alternance. Un nom absent donne `inconnu`. Le garde-fou de la v1 est conservé : « conseil »
seul n'est pas un marqueur d'ESN.

### 5.4 Ordre des filtres et motifs de rejet

L'ordre fixe le motif enregistré, donc ce que la Route B peut récupérer :

1. `metier_hors_cible`
2. `lieu_etranger`
3. `plateforme_missions`, `freelance`, `stage_conventionne`
4. `seniorite` (intitulé senior, lead, manager, ou exigence de 4 ans et plus)
5. `duree_trop_courte`
6. `trop_ancienne` (publication au-delà de la fraîcheur maximale)

Les cibles Route B viennent des rejets `seniorite` et `trop_ancienne`, quand l'employeur est un
employeur final identifié (CDC § 7.3).

## 6. Note et niveau

### 6.1 Composantes (valeurs de départ, calibrées au lot 2)

| Composante | Points |
|---|---|
| Famille de priorité 1, 2, 3 | +6, +3, +1 |
| Compétences techniques reconnues dans l'offre | +1 chacune, plafonnées à +6 |
| Signal junior | +3 |
| « Confirmé » ou « expérimenté » | −3 |
| ESN | −4 |
| Intermédiaire ou employeur inconnu (« seconde main ») | −2 |
| École (fil Alternance) | −3 |
| Entreprise « Cible prioritaire » ou « Cible » dans le suivi | +6 ou +4 |
| Entreprise « Écarter » au motif non définitif | −4 |
| Publiée depuis un jour au plus | +2 |
| Publiée depuis plus de 15 jours | −2 |
| Republiée (revue plus de 30 jours après sa première détection) | −3 |
| APEC « peu candidatée » | +2 |
| Zone préférée (Île-de-France, Hauts-de-France) | +1 |

Le plafond sur les compétences empêche qu'une description longue l'emporte sur une offre bien
ciblée. Une entreprise écartée pour un motif définitif (« pas un employeur », « nationalité »,
« ingénierie hors de France ») ne reçoit pas de note : l'offre passe en archive.

### 6.2 Niveau

| Niveau | Condition (seuils de départ) |
|---|---|
| Alerte | Fil Emploi, note d'au moins 12, priorité 1 **ou** entreprise cible, et pas de seconde main |
| Résumé | Note d'au moins 4 |
| Archive | Le reste, enregistré mais non notifié |

Les seuils sont fixés sur le jeu d'évaluation pour atteindre les critères du CDC § 10, pas à
l'intuition.

## 7. Telegram

* **Groupe à sujets.** Le bot actuel devient administrateur d'un groupe avec les sujets activés.
  Les envois utilisent `message_thread_id`. Nouveaux secrets : `TELEGRAM_CHAT_ID` (identifiant
  du groupe), `TELEGRAM_SUJET_EMPLOI`, `TELEGRAM_SUJET_ALTERNANCE`, `TELEGRAM_SUJET_IMMERSION`.
  Le script `telegram_ids.py` les affiche une fois le groupe créé.
* **Format HTML** au lieu de MarkdownV2 : seuls `<`, `>` et `&` sont à échapper, ce qui supprime
  la principale source de messages refusés.
* **Alerte** : un message par offre. Intitulé, employeur, lieu, contrat, note et ses raisons
  principales, signaux (republiée, seconde main), lien.
* **Résumé** : par fil, offres classées par note, 30 au plus, puis « et N autres dans l'onglet
  Veille ». Découpage automatique sous la limite de 4 096 caractères.
* **Nuit** : une alerte détectée entre 22h et 7h reste « en attente » et part au premier passage
  du matin.
* **Bilan du lundi** : offres par source et par fil, sources en panne, requêtes Adzuna du mois,
  alertes envoyées, part des alertes retenues (lue dans l'onglet Veille).
* Un échec d'envoi laisse l'offre « en attente » : elle repart au passage suivant, jamais deux
  fois.

## 8. Google Sheets

### 8.1 Accès

* Le fichier de suivi est importé dans Google Sheets, sur le compte Google qui a délivré le jeton
  de Mail Track AI.
* Ce jeton (autorisation OAuth avec la portée `spreadsheets`) est copié dans un secret
  `GOOGLE_TOKEN_JSON` du dépôt. L'identifiant du fichier va dans `SUIVI_SHEET_ID`.
* **Point à vérifier** : si l'application OAuth de Mail Track AI est restée en mode « test » dans
  la console Google Cloud, son jeton expire au bout de 7 jours. Il faudra alors la publier, ou
  créer un compte de service et lui partager le fichier.

### 8.2 Règles d'écriture

Le fichier est un outil de travail quotidien. L'outil y écrit sans jamais rien abîmer :

1. Il n'écrit que dans l'onglet Veille, dans des cellules vides de Candidatures, et en fin
   d'onglet Entreprises.
2. Il ne touche jamais une colonne calculée ni une ligne déjà remplie.
3. Il relit avant d'écrire, cellule par cellule. Il n'écrase jamais une plage entière.
4. Un échec Google Sheets n'empêche ni la collecte ni Telegram. Les écritures en échec sont
   rejouées au passage suivant (l'état est en base).

### 8.3 Onglet Veille

Créé par l'outil s'il n'existe pas.

| Colonne | Contenu |
|---|---|
| Ajoutée le | Date de détection |
| Fil, Niveau, Note | Fil (Emploi, Alternance, Immersion), niveau (alerte, résumé), total de la note |
| Entreprise, Poste, Lieu, Contrat, Source | De l'offre |
| Raisons | Composantes principales de la note |
| Signaux | Seconde main, republiée, peu candidatée |
| Lien | URL de l'offre |
| **Retenir** | Case à cocher, la seule colonne que tu modifies |
| Transférée le | Écrite par l'outil |
| Clé | Identifiant technique, colonne masquée |

### 8.4 Transfert vers Candidatures

À chaque passage, les lignes cochées et non transférées sont copiées dans la **première ligne
vide** de Candidatures, dans le bloc de formules existant (lignes 5 à 300) :

| Colonne de Candidatures | Valeur écrite |
|---|---|
| Entreprise, Poste, Lien de l'offre | De l'offre |
| Source | « Veille : APEC », « Veille : France Travail »… |
| Notes | « Ajoutée par la veille le JJ/MM, note N : raisons » |

La date de candidature reste vide, donc « Action à mener » affiche « À candidater ». L'outil
remplit ensuite « Transférée le » dans l'onglet Veille. Quand le bloc de 300 lignes est plein, le
bilan le signale au lieu d'écrire hors du bloc.

### 8.5 Cibles Route B

Pour chaque rejet `seniorite` ou `trop_ancienne` d'un employeur final identifié et absent de
l'onglet Entreprises (comparaison sur le nom normalisé), une ligne est ajoutée en fin d'onglet :

| Colonne d'Entreprises | Valeur |
|---|---|
| Entreprise | Nom |
| Catégorie | « Employeur final » |
| Verdict Route B | « À vérifier » |
| Secteur / implantation | Lieu de l'offre |
| Pourquoi ce verdict | « Recrute en data : offre « intitulé » repérée le JJ/MM, rejetée (trop senior) » |
| Source | « Veille auto » |

Au plus 5 ajouts par jour, pour que l'onglet reste lisible.

### 8.6 Lecture du suivi pour la note

À chaque passage, la colonne Verdict de l'onglet Entreprises est lue une fois et transformée en
table « entreprise normalisée → verdict ». Si la lecture échoue, la note est calculée sans cette
composante et le bilan le signale.

## 9. Sondage des sources (lot 0)

L'espace de travail de Claude n'atteint pas les sites d'offres (France Travail, APEC, Google,
Telegram : connexions refusées par le proxy). Les sondages passent donc par GitHub Actions :

* un workflow manuel `sonde.yml` lance `scripts/sonde.py <source>`.
* les réponses brutes sont **commitées sur une branche `sondes`**, comme le jeu de données de
  rag-fiscal, car les artefacts GitHub ne sont pas téléchargeables depuis l'espace de Claude.
* ces réponses réelles deviennent les fixtures des tests.

Pour chaque source, la fiche de sondage répond à quatre questions : l'accès fonctionne-t-il,
quels champs sont fiables, combien d'offres utiles sur 7 jours, quelles conditions d'utilisation.
Les points ouverts à trancher par sondage :

* France Travail : recherche par codes ROME plutôt que par mots-clés, codes de l'alternance
  (`natureContrat`).
* Adzuna : regroupement des intitulés dans une requête.
* Choisir le service public : fraîcheur du jeu de données data.gouv.fr ou page de recherche.
* Passerelles et engagement-jeunes.com : structure des pages, conditions d'utilisation.
* La bonne alternance : champs, part d'offres déjà vues ailleurs.

Le même mécanisme collecte, sur une semaine, un **échantillon large** (toutes familles, tous
fils) pour bâtir le jeu d'annotation. L'historique de production ne suffit pas : il ne contient
presque que des offres Data Engineer.

## 10. Évaluation du tri

* `echantillon_annotation.py` tire environ 150 offres de l'échantillon, stratifiées par famille,
  fil et note, et les dépose dans un onglet « Annotation » du fichier Google Sheets, avec une
  colonne à choix : « je postule », « peut-être », « hors cible ».
* `incontournables.csv` liste les offres réelles qui **doivent** passer : Harvest, Exail, Shift,
  DINUM, à compléter.
* `evaluer_tri.py` mesure à chaque modification de règle :
  * la part des « je postule » qui passent les filtres (objectif 90 %).
  * la précision des alertes (objectif 70 %).
  * la séparation des fils.
  * la liste des « je postule » rejetés, avec leur motif, pour corriger.
* Le rapport `eval/REPORT.md` est régénéré par l'intégration continue.

## 11. Tests

| Couche | Ce qui est vérifié |
|---|---|
| Sources | Parsing des réponses réelles capturées, résilience (erreur HTTP, JSON inattendu, blocage) |
| Normalisation | Familles, contrats, employeurs, lieux : un cas par règle, pièges connus compris |
| Filtres | Ordre et motif de chaque rejet |
| Note et niveau | Chaque composante, plafonds, seuils, cas limites |
| Planification | Tâches dues selon l'heure, le retard, le changement d'heure, le quota |
| Base | Migrations, import v1, idempotence d'un passage rejoué |
| Telegram | Sujet visé, échappement HTML, découpage, attente de nuit, renvoi après échec |
| Google Sheets | Sur un faux client : jamais de colonne calculée touchée, première ligne vide trouvée, pas de doublon après deux passages, échec rejoué |
| Bout en bout | Un passage complet sans envoi réel (`DRY_RUN`), dans l'intégration continue |

Un workflow `ci.yml` lance `ruff` et `pytest` à chaque push et pull request. Le code de décision
(normalisation, filtres, note, routage, planification, écritures Sheets) vise une couverture de
90 %.

## 12. Workflows GitHub

| Workflow | Déclenchement | Rôle |
|---|---|---|
| `veille.yml` | Chaque heure à :17, de 5h à 21h UTC, et manuel | Un passage |
| `ci.yml` | Push, pull request | Lint, tests, évaluation |
| `sonde.yml` | Manuel | Sondages, commit sur la branche `sondes` |
| `maintien.yml` | Mensuel | Réactive les workflows planifiés par l'API GitHub, pour éviter la désactivation à 60 jours sans commit factice |
| `audit.yml` | Manuel | Conservé, adapté au schéma v2 |

La plage UTC couvre 7h à 22h à Paris en hiver comme en été. `planning.py` ignore ce qui tombe
hors plage. La base reste en cache GitHub Actions comme en v1, avec `concurrency` pour éviter
deux passages simultanés.

## 13. Bascule

* La v1 continue de tourner sur `main` pendant tout le développement.
* La v2 est développée sur des branches, une pull request par lot.
* Au lot 3, la v2 tourne d'abord **en ombre** pendant deux ou trois jours : elle collecte, note et
  écrit son rapport sans envoyer, et l'on compare son résultat à celui de la v1.
* Bascule : la migration importe les clés v1, la v1 est désactivée, la v2 prend le groupe à sujets.

## 14. Ce dont j'ai besoin de toi (lot 0)

1. **Importer le fichier de suivi dans Google Sheets** avec le compte Google de Mail Track AI, et
   m'envoyer son identifiant (la partie de l'adresse entre `/d/` et `/edit`).
2. **Ajouter deux secrets** au dépôt : `GOOGLE_TOKEN_JSON` (même contenu que `GMAIL_TOKEN_JSON`
   de Mail Track AI) et `SUIVI_SHEET_ID`.
3. **Créer le groupe Telegram** : activer les sujets, créer Emploi, Alternance et Immersion,
   ajouter le bot comme administrateur, écrire un message dans chaque sujet.
4. **Créer un compte sur l'API apprentissage** (La bonne alternance), récupérer la clé et
   l'ajouter en secret `LBA_API_KEY`.
5. **Demander l'accès à l'API Immersion Facilitée** sur `immersion-facile.beta.gouv.fr/doc-api`.
6. **Vérifier le mode de l'application OAuth** de Mail Track AI dans la console Google Cloud
   (« test » ou « en production »), cf. § 8.1.

Les points 1 à 3 débloquent les lots 1 à 4. Les points 4 et 5 ne concernent que le lot 5 et
peuvent attendre une réponse.

## 15. Décisions techniques à valider

1. **pydantic** pour valider la configuration : une erreur de saisie dans un YAML arrête le
   passage avec un message clair, au lieu d'un comportement silencieusement faux.
2. **HTML** au lieu de MarkdownV2 pour Telegram.
3. **Planification dans le code**, déclencheur horaire unique.
4. **Sondages et fixtures** commités sur une branche `sondes` du dépôt public : ce ne sont que
   des offres publiques, sans donnée personnelle.
5. **Mode ombre** avant la bascule.
