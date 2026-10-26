# Lot 0 : résultats des vérifications et des sondages (25 octobre 2026)

> Deux passages du workflow `lot0.yml` (runs 40226361785 et 40226687251). Réponses brutes sur la
> branche `sondes`, dossiers `2026-10-25_1932/` et `2026-10-25_1935/`.

## 1. Accès

| Accès | Résultat | Suite |
|---|---|---|
| Jeton Google | Valide, portées `gmail.readonly` et `spreadsheets` | Rien à faire |
| Fichier de suivi | Ouvert, mais il ne contient qu'un onglet « Suivi candidatures » (2 145 lignes x 26 colonnes) : c'est la feuille de Mail Track AI, pas le suivi Route B importé. L'identifiant du secret correspond bien au lien envoyé | Importer le fichier Route B dans un fichier Google Sheets **distinct**, mettre à jour `SUIVI_SHEET_ID` |
| Groupe Telegram | Supergroupe à sujets trouvé. Sujet « Emploi » : `message_thread_id` 2, message de test envoyé. Le bot est **membre, pas administrateur**, et ne lit pas les messages de groupe | Passer le bot administrateur, écrire un message dans Alternance et Immersion, relancer |
| La bonne alternance | Clé acceptée. Documentation OpenAPI publique : `/api/job/v1/search`, `/offer`, `/export` | Rien à faire |

## 2. Sources

### France Travail : socle confirmé

* 21 requêtes, toutes en succès. Volume utile sur 7 jours : 115 offres « data engineer », 61 « data
  analyst », 96 « ingénieur IA », 360 « intelligence artificielle ».
* **Codes ROME utiles** (vus dans les réponses) : M1811 Data engineer, M1405 Data scientist,
  M1419 Data analyst, **M1889 Ingénieur en intelligence artificielle**, M1403 Chargé d'études
  socio-économiques, M1818 Ingénieur d'étude informatique. M1805 (développeur) et M1806
  (consultant fonctionnel) sont trop larges : écartés.
* **Alternance** : `natureContrat=E2,FS` fonctionne (apprentissage et professionnalisation).
* **Durée** : 151 missions d'intérim de 1 à 3 mois sur environ 1 100 offres. Le filtre de 6 mois
  du cahier des charges aura un effet réel.
* **Champs précieux, inutilisés en v1** : `experienceExige` (D débutant accepté, E exigée) et
  `experienceLibelle` (« 5 An(s) ») donnent la séniorité sans deviner ; `offresManqueCandidats`
  est l'équivalent du signal APEC « peu candidatée ».
* **78 % des offres sont des reprises de partenaires** (`origineOffre.origine = 2`) : Direct Emploi,
  Meteojob, Handicap Job, PMEJob… C'est la source des intermédiaires repérés par l'audit. Le nom
  de l'employeur reste souvent présent dans `entreprise.nom`.

### APEC : bloquée depuis le 1er octobre

* Toutes les requêtes répondent **403**. L'historique de production le confirme : la dernière offre
  APEC date du **1er octobre**. La v1 a perdu sa deuxième source (28 % des offres depuis août)
  sans qu'aucun signal ne le montre.
* Un 403 généralisé signifie que le site refuse désormais ce type d'accès. On ne cherche pas à le
  contourner. APEC sort du périmètre automatique. Ses offres restent consultables à la main, et
  une partie est reprise par d'autres agrégateurs.
* C'est l'argument concret du bilan hebdomadaire et de l'alerte de panne (CDC § 8) : trois
  semaines de silence sur une source majeure, détectées seulement par ce sondage.

### Adzuna : flux large, quota serré

| Requête (3 jours) | Correspondances |
|---|---|
| `what=data` et `what_or` sur les métiers | 3 793 |
| `what_or` IA (mlops, llm, genai, IA…) | 17 786 (« IA » ramène tout) |
| `title_only=data` | 1 097 |
| `title_only=machine learning` | 31 |

* La recherche **sur le titre** est la bonne approche. Environ 365 titres « data » par jour, dont
  une part de stages, de postes senior et de freelances.
* Avec 50 résultats par requête et 250 requêtes par mois, la couverture complète est impossible.
  Prochain essai : `title_only=data` avec `what_exclude` (stage, senior, lead, freelance,
  alternance) et tri par date, pour mesurer le volume restant.

### HelloWork : stable

Quatre recherches (data scientist, data analyst, ingénieur IA, alternance data) : 30 offres par
page, parsing de la v1 toujours valable.

### La bonne alternance : retenue pour le fil Alternance

* `/api/job/v1/search` par codes ROME, avec ou sans géolocalisation. Réponse : `jobs` (14 à 31) et
  `recruiters` (150 entreprises à fort potentiel sans offre publiée).
* Chaque offre porte `partner_label` (France Travail, Hellowork, Jobs that make sense…) : beaucoup
  de doublons avec France Travail, gérés par le dédoublonnage.
* Les `recruiters` sont une piste Route B pour l'alternance.
* Contenu observé : beaucoup de « Stage de fin d'études / Alternance » de cabinets de conseil, à
  trier par les règles de métier.

### Passerelles : retenue, par flux RSS

* Flux RSS public de la filière Numérique (`Rss_JobFamily=3043`) : 20 offres les plus récentes, dont
  « DNRED Ingénieur data scientiste », « Chargé(e) de mission Data ». Un passage par heure suffit
  largement pour ne rien manquer.

### Choisir le service public : retenue, par la page de recherche

* Le jeu de données data.gouv.fr est hebdomadaire et pèse 127 Mo : inutilisable pour la réactivité.
* Le flux RSS général (plateforme Talentsoft) ne donne que les 20 dernières offres, toutes filières
  confondues : trop généraliste.
* **La page de recherche** (« data » : 1 499 offres) renvoie 20 cartes par page, avec intitulé,
  lieu, versant de la fonction publique, employeur et date de mise en ligne. `robots.txt` autorise
  ces pages. Retenue, avec tri par date et une ou deux pages par passage.

### engagement-jeunes.com : à confirmer

* Les adresses de recherche ont changé (préfixe `/fr/`). `robots.txt` autorise tout et publie un plan
  du site des offres (130 fichiers, environ 58 000 adresses, beaucoup de bénévolat et de service
  civique).
* Les pages d'offre n'ont pas de données structurées (pas de JSON-LD).
* Avant tout développement : lire les conditions d'utilisation (`/fr/conditions-utilisation.html`)
  et sonder `/fr/offres-emploi.html?contrat[]=2` avec un mot-clé. Classée en lot 5, priorité basse.

## 3. Décisions proposées

| Source | Décision | Fils |
|---|---|---|
| France Travail | Socle, par codes ROME, avec séniorité structurée | Emploi, Alternance |
| Adzuna | Conservée, recherche sur le titre, à calibrer | Emploi |
| HelloWork | Conservée | Emploi, Alternance |
| La bonne alternance | Ajoutée (lot 5 avancé au lot 3 si le temps le permet) | Alternance |
| Passerelles | Ajoutée, flux RSS Numérique | Emploi |
| Choisir le service public | Ajoutée, page de recherche | Emploi |
| APEC | **Retirée** (403 depuis le 1er octobre, pas de contournement) | |
| engagement-jeunes.com | En attente des conditions d'utilisation | |
| Immersion Facilitée | En attente de la demande d'accès | Immersion |

**Effet sur la v1 dès maintenant** : la production tourne sans APEC depuis trois semaines. Retirer
APEC de la v1 ne change rien au flux, mais supprime des erreurs silencieuses. La v2 compensera par
France Travail (codes ROME, plus de métiers), Passerelles et Choisir le service public.

## 4. Lot 5 : sondage du 26/10 (sources publiques)

Sonde `sonde_lot5_public` (branche `sonde-lot5`, réponses dans `sondes/2026-10-26_1247/`), avec le
User-Agent honnête de la production.

* **Page de recherche de Choisir le service public : écartée.** 4,5 Mo par page de 20 offres ; tri
  par pertinence ; filtre « 48 heures » incohérent (2 offres quand le site en affiche du jour même).
  Le filtre de nature d'emploi fonctionne (`type/2349-2267`), mais lire 179 offres « data » sur
  7 jours coûterait 9 pages de 4,5 Mo.
* **Flux RSS de la Place de l'emploi public (Talentsoft) : retenus.** Un flux par métier du
  répertoire de la fonction publique (`Rss_Profile` : Data engineer 3871, Data Scientist 3872,
  Analyste de données 3552…) et par domaine (`Rss_JobFamily`, Numérique 3522). 20 offres par flux,
  avec description complète et nature de l'emploi. Le domaine Numérique couvre moins d'une journée,
  les flux métier plusieurs semaines.
* **Passerelles : pas de source séparée.** Les offres des ministères économiques et financiers sont
  dans les flux ci-dessus (références `MEF_…`).
* **Page d'une offre** (200 Ko) : bloc JSON-LD `JobPosting` avec employeur, niveau d'expérience
  (Débutant, Confirmé, Expert), date de publication et lieu. Lue une seule fois par offre (mémoire
  de la source en base), seulement pour les offres au titre reconnu, fraîches et ouvertes aux
  contractuels.

Essai réel du 26/10 (base de production, sans envoi) : 195 offres lues, 19 gardées, dont une alerte
(« Ingénieur Big Data - Data Engineer », Commissariat au Numérique de Défense) et des postes à la
DNRED, à la DEPP, à la DREES, au Contrôle général des armées.

### La bonne alternance (essai du 26/10)

Sur l'Île-de-France (60 km) et la France entière, une trentaine d'offres data en alternance au
total, dont la grande majorité sont des copies de France Travail et de HelloWork, sources déjà
interrogées : elles sont ignorées. Reste peu d'offres propres à la source (une gardée à l'essai :
« Data analyst » à la Direction générale des douanes, venue de la Place de l'apprentissage et des
stages). Coût faible (2 requêtes toutes les 8 heures) : source gardée pour ces offres publiques.
