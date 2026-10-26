# Cahier des charges : refonte v2 de la veille emploi

> Statut : **validé le 25 octobre 2026**. Rédigé à partir de l'échange de cadrage des 23 et
> 25 octobre et de l'audit de production du 23 octobre. Les décisions de la section 13 sont
> tranchées. La conception est décrite dans [`conception_v2.md`](conception_v2.md).

## 1. Pourquoi une refonte

L'outil tourne sans interruption depuis le 12 juin. Il a été conçu pour un besoin qui a changé :
un poste Data Engineer junior, en CDI ou CDD, notifié une fois par jour. Le besoin d'aujourd'hui
est plus large, plus urgent, et doit s'intégrer au reste du dispositif de recherche (suivi des
candidatures, Route B).

### 1.1 Ce que dit l'audit (12 juin au 22 octobre)

1 496 offres vues, 1 305 notifiées. Les chiffres « depuis août » portent sur les 777 offres
notifiées après les correctifs du 21 août.

| Constat | Chiffre | Conséquence pour la v2 |
|---|---|---|
| Volume réel | 12,5 offres par jour depuis août, pour un plafond de 30 | Le plafond n'est jamais atteint : la cible trop étroite limite le flux, pas le tri |
| Cible étroite | 77 % des titres contiennent « data engineer » | Élargir les métiers remplira le fil sans le noyer |
| Sources utiles | Adzuna 46 %, APEC 28 %, France Travail 14 %, HelloWork 11 % (depuis août) | Ces quatre sources sont le socle |
| Sources mortes | Greenhouse, Lever, Ashby, Teamtailor : 7 offres en quatre mois. Choose : aucune | Retrait |
| Saturation | 1 301 offres sur 1 305 vues par une seule source | Fonction morte, retrait |
| Intermédiaires | cadremploi, Handicap Job, Hellowork, Collective, « Choisir le Service Public » comme employeur : 13 %. Employeur absent : 7 % | Signal d'offre de seconde main, à déclasser et à signaler |
| Score | 85 % des notifiées entre 5 et 9 | Le score ne départage plus rien : le tri est à refaire |
| Stages | 0 depuis août | Correctif efficace |

### 1.2 Ce que l'audit ne voit pas

La base ne garde que les offres qui ont passé les filtres. On ne sait donc pas ce que l'outil
rate. La v2 doit conserver les offres rejetées avec leur motif, pour mesurer les oublis et pour
alimenter la Route B (§ 7.3).

### 1.3 L'usage réel

* Les notifications ont été lues jusqu'en septembre, puis délaissées au profit de la Route B.
* Plusieurs candidatures en sont sorties, sans suite. La cause tient surtout aux CV et à
  l'absence de relance à l'époque, mais une part des offres semble « fantôme ».
* L'onglet « Candidatures » du suivi ne compte que 6 lignes : les candidatures nées de la veille
  n'y ont jamais été reportées. L'intégration au suivi (§ 7) corrige ce trou.

## 2. Objectif

Faire de l'outil la **source principale d'offres** : efficace, fluide et décisif. Pas l'outil le
plus optimisé possible, mais celui qui dit clairement, chaque jour, quelles offres méritent une
candidature, et qui les dépose là où le travail de candidature se fait.

Trois exigences en découlent :

1. **Large en entrée** : tous les métiers de la data et de l'IA accessibles à un junior.
2. **Tranchant en sortie** : une alerte rare et fiable pour les meilleures offres, un résumé
   pour le reste.
3. **Intégré** : les offres arrivent dans le suivi des candidatures, les employeurs écartés
   nourrissent la Route B.

## 3. Périmètre de recherche

### 3.1 Métiers, par priorité

La reconnaissance du métier se fait d'abord sur le **titre**. La description sert à confirmer
et à noter, pas à repêcher une offre au titre hors sujet (sinon « data » seul ramène tout).

| Priorité | Famille | Exemples d'intitulés reconnus |
|---|---|---|
| 1 | Data Engineering | data engineer, ingénieur data, ingénieur données, développeur data ou big data, data ops, ingénieur ETL |
| 1 | Data Science | data scientist, ingénieur data science, machine learning scientist |
| 1 | IA et ML | AI engineer, ML engineer, MLOps, ingénieur IA, ingénieur LLM, IA générative, GenAI, coordinateur IA |
| 1 | Analytics Engineering | analytics engineer |
| 2 | Analyse de données | data analyst, chargé d'études statistiques, ingénieur d'études (secteur public) |
| 2 | BI et décisionnel | développeur BI, développeur décisionnel, consultant BI, Power BI |
| 2 | Qualité et gouvernance | data quality, data steward, data management, gouvernance des données |
| 3 | Satellites | développeur Python orienté données, backend data, data product, géomatique (QGIS) |

La liste vit dans la configuration, pas dans le code. Ajouter un intitulé ne demande aucune
modification de programme.

### 3.2 Formats et fils

Trois fils, séparés de bout en bout (sources, règles, sujets Telegram, onglet de suivi) :

| Fil | Contrats | Remarque |
|---|---|---|
| **Emploi** | CDI, CDD, intérim (CDD et intérim d'au moins 6 mois si la durée est connue) | Le fil principal |
| **Alternance** | Apprentissage, professionnalisation | Signaler les offres publiées par des écoles plutôt que par des entreprises (cas Kaischool) |
| **Immersion** | Période de mise en situation en milieu professionnel (PMSMP) | Voir § 3.3 |

Le freelance n'est pas un fil : les plateformes de missions restent exclues (Collective.work,
Free-Work et équivalents).

### 3.3 Le fil Immersion, point de vigilance

Hors inscription dans une formation, un stage classique est impossible : il exige une convention
signée par un établissement d'enseignement. Le stage « non scolaire » accessible est
l'**immersion professionnelle (PMSMP)**, prescrite par France Travail. Il n'existe pas d'offres
d'immersion au sens d'une annonce : le service public Immersion Facilitée recense des
**entreprises qui acceptent d'accueillir**.

Conséquence : le fil Immersion publie des **entreprises à contacter**, pas des offres, à un
rythme hebdomadaire. Son API est accordée sur demande (§ 4.3). Si l'accès est refusé, le fil se
limite aux offres « stage » explicitement ouvertes hors convention, ce qui sera rare.

Si une inscription en formation intervient (alternance avec Master, par exemple), les stages
conventionnés redeviennent accessibles et ce fil pourra être élargi.

### 3.4 Géographie

* France métropolitaine entière. **La Belgique sort.**
* Télétravail complet accepté sans condition de pays d'attache.
* Les zones préférées (Île-de-France, Hauts-de-France) donnent un léger bonus, jamais une
  exclusion.

### 3.5 Séniorité

* **Exclus** : senior, lead, staff, principal, head of, manager, directeur, architecte,
  expert, et toute exigence de **4 ans ou plus**.
* **Acceptés** : 0 à 3 ans. « Confirmé » et « expérimenté » ne sont plus éliminatoires mais
  déclassent l'offre (beaucoup acceptent un junior avec une alternance solide).
* Signaux junior (junior, débutant, premier emploi, jeune diplômé, graduate, 0 à 2 ans) :
  bonus.

## 4. Sources

### 4.1 Conservées

| Source | Fils | Évolution v2 |
|---|---|---|
| Adzuna | Emploi | Requêtes regroupées pour tenir le quota (§ 5.2) |
| APEC | Emploi, Alternance | Ajout des codes de contrat alternance pour le fil Alternance |
| France Travail | Emploi, Alternance | Requêtes par famille de métiers, contrats d'apprentissage pour le fil Alternance |
| HelloWork | Emploi, Alternance | Inchangée (scraping de la page liste, sans description) |

### 4.2 Retirées

Greenhouse, Lever, Ashby, Teamtailor et Choose : 7 offres utiles en quatre mois pour l'essentiel
de la complexité du code (slugs, découverte, maintenance). Le code reste dans l'historique Git.

### 4.3 Ajoutées, à valider par un sondage technique

Chaque nouvelle source passe d'abord un **sondage** (accès réel, structure des données, volume
utile sur une semaine) avant d'être développée. Une source qui ne rapporte rien est abandonnée,
comme les ATS l'ont été.

| Source | Fil | Accès connu au 25/10 | Risque |
|---|---|---|---|
| La bonne alternance (API apprentissage, service public) | Alternance | API officielle, clé gratuite sur compte, usage non commercial autorisé. Recherche par code ROME, lieu, rayon, niveau de diplôme | Faible. Agrège aussi des offres France Travail et HelloWork : dédoublonnage nécessaire |
| Choisir le service public | Emploi | L'API publique sert à publier, pas à chercher. Un jeu de données existe sur data.gouv.fr. Sinon, la page de recherche | Moyen. Fraîcheur du jeu de données à vérifier |
| Passerelles (ministère de l'Économie et des Finances) | Emploi | Pas d'API connue. Page de recherche HTML | Moyen. Structure à sonder |
| engagement-jeunes.com | Emploi, Alternance | Pas d'API connue. Recherche par paramètres d'URL (codes de contrat visibles) | Moyen. Conditions d'utilisation à lire avant tout scraping |
| Immersion Facilitée | Immersion | API sur demande auprès de l'équipe, publics éligibles non précisés | Élevé. Dépend d'une réponse de l'équipe |

Les autres employeurs publics de l'annuaire (INSEE, IGN, CNIL, Banque de France, Caisse des
Dépôts, URSSAF, CNAM) publient pour la plupart sur Choisir le service public, France Travail ou
APEC. Un connecteur par site employeur n'est pas prévu en v2.

Restent exclus : LinkedIn, Indeed et Welcome to the Jungle (protections anti-robot, alertes
natives déjà configurées).

## 5. Rythme et réactivité

### 5.1 Principe

Une bonne offre déclenche une **alerte** dès qu'elle est détectée. Le reste arrive dans un
**résumé quotidien**. Les fils Alternance et Immersion ne déclenchent pas d'alerte : résumé
quotidien pour l'Alternance, hebdomadaire pour l'Immersion.

### 5.2 Fréquence par source

| Source | Fréquence | Justification |
|---|---|---|
| France Travail, APEC, HelloWork, sources publiques | Toutes les heures, de 7h à 22h | Pas de quota contraignant connu |
| Adzuna | 3 passages par jour, 2 requêtes par passage | Quota gratuit de 250 requêtes par mois : 6 requêtes par jour donnent environ 186 par mois, avec une marge pour les essais |
| La bonne alternance | 2 passages par jour | L'alternance est moins pressée |
| Immersion | 1 passage par semaine | Pas d'urgence, liste d'entreprises |

Le regroupement Adzuna se fait par le paramètre de mots-clés alternatifs de l'API (plusieurs
intitulés dans une seule requête), à vérifier au sondage.

### 5.3 Limite de GitHub Actions

Les tâches planifiées partent avec retard : le passage de 7h (heure de Paris) démarre en
pratique entre midi et 16h. Deux mesures :

* planifier sur des minutes peu demandées (par exemple 17 ou 43) plutôt qu'à l'heure pile, où
  les files d'attente sont les plus longues.
* accepter une réactivité de l'ordre de l'heure, pas de la minute. Une alerte à la minute près
  demanderait une machine allumée en permanence, ce qui est hors périmètre.

GitHub désactive un workflow planifié après 60 jours sans activité sur le dépôt. Un mécanisme
de maintien en vie est prévu (§ 8).

## 6. Tri et qualité

### 6.1 Ordre des opérations

1. Normalisation : chaque offre reçoit son fil, sa famille de métier, son contrat, sa
   localisation et son employeur dans un format commun.
2. Filtres éliminatoires : métier hors liste, séniorité exclue, lieu étranger, plateforme de
   missions. **Chaque rejet est enregistré avec son motif.**
3. Dédoublonnage entre sources.
4. Note, puis classement en trois niveaux : **alerte**, **résumé**, **archive** (vue, non
   notifiée).

### 6.2 Une note qui départage

La note actuelle additionne des mots-clés et regroupe presque tout entre 5 et 9. La v2 combine
des composantes lisibles, chacune justifiable dans le message Telegram :

| Composante | Effet |
|---|---|
| Priorité de la famille de métier | Priorité 1 en tête, priorité 3 en bas |
| Adéquation technique | Correspondance entre la stack de l'offre et la tienne (Python, SQL, Airflow, dbt, Spark, Kafka, Snowflake, Docker, LLM, RAG…) |
| Signaux de niveau | Bonus junior, malus « confirmé » |
| Nature de l'employeur | Employeur final : neutre. ESN : malus. Intermédiaire ou employeur absent : malus et mention « seconde main » |
| Statut dans ton suivi | Entreprise marquée « Cible » ou « Cible prioritaire » dans l'onglet Entreprises : fort bonus. Entreprise marquée « Écarter » : malus fort |
| Signaux de fraîcheur et de concurrence | Offre récente, offre APEC « peu candidatée » : bonus |

Le passage en **alerte** exige une note au-dessus d'un seuil **et** au moins un signal fort
(famille de priorité 1, ou entreprise cible). Objectif : quelques alertes par semaine, pas par
heure.

### 6.3 Offres fantômes

Elles ne se détectent pas avec certitude. La v2 signale, sans exclure :

* l'offre de seconde main (intermédiaire ou employeur absent).
* l'offre **republiée** : même employeur et même intitulé revus plus de 30 jours après la
  première apparition.
* l'offre ancienne : date de publication très antérieure à la date de détection.

### 6.4 Notation par LLM, en option

Un tri par règles atteint vite un plafond sur un flux large. Une option, décidée **après**
mesure du tri par règles sur le jeu d'évaluation (§ 9.2) : faire noter les offres candidates
par Gemini au regard du CV, par lots, comme dans Mail Track AI.

Contraintes connues : quota gratuit de 20 requêtes par jour et par modèle. Il faudrait une clé
distincte de celle de Mail Track AI, et ne noter que les offres nouvelles ayant passé les
filtres. Si la mesure montre que les règles suffisent, l'option est abandonnée.

## 7. Sorties

### 7.1 Telegram : un groupe, trois sujets

Un groupe Telegram à sujets, un sujet par fil : Emploi, Alternance, Immersion.

* **Alerte** (fil Emploi seulement) : un message par offre, aussitôt. Intitulé, employeur,
  lieu, contrat, note et ses deux ou trois raisons principales, signaux d'alerte éventuels
  (seconde main, republiée), lien.
* **Résumé quotidien** : un message par fil, à heure fixe, offres classées.
* **Bilan hebdomadaire** : volumes par source, sources en panne, alertes envoyées. Il remplace
  l'audit manuel, qui n'a pas été relancé entre août et octobre.
* Pas de notification entre 22h et 7h : les alertes de la nuit sont envoyées au réveil.

### 7.2 Google Sheets : le suivi des candidatures

Le fichier `Route_B_Suivi_Candidatures_Spontanees` passe sur Google Sheets, avec sa structure
actuelle (onglets Tableau de bord, Contacts, Candidatures, Entreprises, Règles). Ses formules
(`WORKDAY`, `NETWORKDAYS`, `COUNTIFS`) existent dans Google Sheets. L'accès réutilise le mécanisme
d'autorisation déjà en place pour Mail Track AI.

**Proposition** : un nouvel onglet **Veille** sert de boîte de réception.

* Chaque offre notifiée y est ajoutée : date, fil, note, entreprise, poste, lien, source,
  signaux, et une case **Retenir**.
* Quand tu coches **Retenir**, le passage suivant de l'outil copie l'offre dans l'onglet
  **Candidatures** (Entreprise, Poste, Lien de l'offre, Source, Notes), avec la date de
  candidature vide. La colonne « Action à mener » affiche alors « À candidater ».
* L'outil n'écrit jamais dans les colonnes calculées. Il ne modifie jamais une ligne que tu as
  saisie.

Pourquoi pas une copie directe dans Candidatures : à 15 ou 25 offres par jour, l'onglet serait
noyé en une semaine et le tableau de bord deviendrait faux. La case garde la décision entre tes
mains, en un clic.

### 7.3 Google Sheets : les cibles Route B

C'est le mécanisme spécifié le 5 octobre et jamais construit, identifié dans le bilan du
16 octobre comme la seule faiblesse de fond du dispositif.

* Une offre rejetée pour **séniorité** ou **expiration**, dont l'employeur est un **employeur
  final** (ni ESN, ni intermédiaire, ni plateforme), signale une entreprise qui recrute en
  data.
* Si cette entreprise n'existe pas déjà dans l'onglet Entreprises, elle y est ajoutée avec le
  verdict **« À vérifier »**, la source « Veille auto » et le motif (intitulé de l'offre rejetée,
  date).
* Une entreprise déjà présente n'est jamais modifiée.

### 7.4 Le suivi pilote aussi la veille

Le lien fonctionne dans les deux sens : l'onglet Entreprises influence la note (§ 6.2). Une
offre chez une « Cible prioritaire » remonte en alerte, une offre chez une entreprise écartée
pour un motif définitif (« Écarter : nationalité », « Écarter : pas un employeur ») est
archivée.

## 8. Exigences de fonctionnement

* **Robustesse** : une source en panne n'interrompt jamais le passage. Une source en échec trois
  passages de suite déclenche un avertissement dans le bilan.
* **Maintien en vie** : un workflow mensuel garde le dépôt actif pour que GitHub ne désactive
  pas la planification.
* **Persistance** : la base SQLite reste en cache GitHub Actions, avec les offres rejetées et
  leur motif en plus des offres vues.
* **Secrets** : clés et jetons uniquement dans les secrets GitHub. Aucune donnée personnelle
  dans le dépôt public (l'identifiant du fichier Google Sheets est un secret).
* **Configuration** : métiers, exclusions, seuils, horaires et sources actives restent dans
  `config/`, modifiables sans toucher au code.

## 9. Tests et mesure

### 9.1 Tests automatiques

* Chaque source testée sur des **réponses réelles enregistrées** (JSON et HTML capturés au
  sondage), pas sur des exemples inventés.
* Filtres et note testés cas par cas, y compris les pièges connus : « Conseil Départemental »
  n'est pas une ESN, « Collective » est une plateforme, « confirmé » n'élimine plus.
* Écriture Google Sheets testée sur un faux client : jamais de colonne calculée touchée, jamais
  de ligne utilisateur modifiée, pas de doublon après deux passages.
* Routage Telegram testé : bon sujet, découpage des longs messages, silence de nuit.
* Un passage complet de bout en bout sans envoi (`DRY_RUN`) dans l'intégration continue.

### 9.2 Jeu d'évaluation du tri

Les tests vérifient que le code fait ce qu'on lui demande. Ils ne disent pas si le tri est bon.
Pour cela, sur le modèle de l'évaluation de rag-fiscal :

* tu annotes environ 150 offres réelles tirées de l'historique de production : « je postule »,
  « peut-être », « hors cible » (une trentaine de minutes).
* on y ajoute des offres connues qui **doivent** passer : Harvest (AI Engineer LLM et RAG),
  Exail (Coordinateur IA), Shift (Data Scientist), DINUM.
* un script mesure ce que le tri garde et ce qu'il place en tête, à chaque modification des
  règles.

En production, la case **Retenir** de l'onglet Veille fournit ensuite une mesure continue : la
part des alertes que tu retiens réellement.

## 10. Critères d'acceptation

| Critère | Seuil |
|---|---|
| Oublis sur le jeu d'évaluation | Au moins 90 % des offres « je postule » passent les filtres |
| Précision des alertes, jeu d'évaluation | Au moins 70 % des alertes sont des « je postule » |
| Précision des alertes, production | Au moins une alerte sur deux retenue sur les deux premières semaines |
| Fils | Aucune offre d'alternance dans le fil Emploi, et inversement, sur le jeu d'évaluation |
| Réactivité | Une offre France Travail ou APEC est notifiée au plus tard au passage horaire suivant sa détection |
| Suivi | Une offre cochée « Retenir » apparaît dans Candidatures au passage suivant, sans doublon |
| Robustesse | Une source coupée volontairement n'empêche ni le passage ni les notifications |
| Quota Adzuna | Moins de 220 requêtes sur un mois réel |

## 11. Hors périmètre

* Candidature automatique, génération de lettres, envoi de messages aux recruteurs.
* LinkedIn, Indeed, Welcome to the Jungle.
* Une machine allumée en permanence pour des alertes à la minute.
* Un connecteur par site carrière d'entreprise.

## 12. Découpage proposé

| Lot | Contenu | Livrable vérifiable |
|---|---|---|
| 0 | Sondage des nouvelles sources, demande de clés (La bonne alternance, Immersion Facilitée), migration du suivi sur Google Sheets | Fiche par source : accès, volume utile, décision |
| 1 | Socle : modèle d'offre v2 (fil, famille, contrat), base avec rejets et motifs, retrait des sources mortes, maintien en vie | Tests verts, passage à blanc identique en volume |
| 2 | Ciblage large, nouvelle note, jeu d'évaluation | Rapport d'évaluation, critères § 10 sur le tri |
| 3 | Trois fils, groupe Telegram à sujets, alertes, résumés, bilan, rythme horaire | Une semaine de production |
| 4 | Google Sheets : onglet Veille, case Retenir, cibles Route B, lien Entreprises vers la note | Critère « Suivi » validé |
| 5 | Nouvelles sources retenues au sondage | Une source par livraison, chacune mesurée |
| 6 | Notation par LLM, seulement si le lot 2 montre un plafond | Comparaison chiffrée avant et après |

Les lots 1 à 4 rendent l'outil utile sur le nouveau besoin avec les sources existantes. Le lot 5
ajoute de la couverture, le lot 6 de la finesse.

## 13. Décisions (25 octobre 2026)

1. **Onglet Veille et case Retenir** (§ 7.2) : retenu, pas de copie directe dans Candidatures.
2. **Durée minimale** des CDD et missions d'intérim : 6 mois, quand la durée est connue.
3. **Annotation** du jeu d'évaluation : Maël annote environ 150 offres.
4. **Immersion Facilitée** : Maël demande l'accès à l'API à son nom.
5. **Horaires** : passages de 7h à 22h, silence de nuit, alertes de la nuit envoyées au réveil.
