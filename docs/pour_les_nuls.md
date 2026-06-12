# Ce projet, expliqué simplement

> Ce fichier s'adresse à toi si tu débutes en programmation — ou si tu n'y connais
> rien du tout. Pas de jargon non expliqué, pas de prérequis. On va voir **ce que fait
> ce projet**, **pourquoi il le fait comme ça**, et **ce que tu peux en apprendre**.
> Prends ton temps, lis dans l'ordre.

---

## 1. Le problème, en une image

Imagine que tu cherches un travail. Tous les matins, tu devrais :

- ouvrir une dizaine de sites d'offres d'emploi,
- taper les mêmes recherches (« data engineer », « débutant », « Paris »…),
- lire des centaines d'annonces,
- noter celles qui sont nouvelles (sans re-noter celles d'hier),
- repérer les bonnes (junior-friendly) et écarter le bruit.

C'est long, répétitif, et démotivant. Pire : les sites les plus connus (comme LinkedIn)
sont saturés — une offre y reçoit souvent **200 à 500 candidatures**. Tu te bats contre
une foule.

**L'idée du projet** : faire faire tout ce travail pénible par un programme, chaque matin,
automatiquement. Le programme va chercher les offres là où il y a **moins de concurrence**
(des sites moins connus, ou directement les pages « carrières » des entreprises), il fait
le tri, et il t'envoie seulement le meilleur sur **Telegram** (une application de messagerie).

Tu te réveilles, tu as une petite liste d'offres pertinentes. Tu n'as plus qu'à postuler.

---

## 2. Qu'est-ce qu'un « pipeline » ?

Le mot revient souvent. Un **pipeline**, c'est juste une **chaîne d'étapes** où le résultat
de chaque étape alimente la suivante — comme une chaîne de montage dans une usine.

Ici, la chaîne ressemble à ça :

```
1. Aller chercher les offres partout      (collecte)
2. Garder seulement celles qui me concernent (filtrage)
3. Repérer les doublons et les fusionner   (nettoyage)
4. Donner une note à chaque offre          (scoring)
5. Mettre de côté celles déjà vues hier     (mémoire)
6. Envoyer les meilleures sur Telegram      (notification)
```

Chaque étape est un petit bout de code qui fait **une seule chose, bien**. C'est plus
facile à comprendre, à tester et à réparer que si tout était mélangé.

---

## 3. D'où viennent les offres ? (les « sources »)

Le programme va piocher à plusieurs endroits. On les appelle des **sources**. Il y en a
de deux types.

### Les sources « API »
Une **API**, c'est une porte officielle qu'un site ouvre pour que des programmes (pas des
humains) viennent lui poser des questions et reçoivent des réponses bien rangées. C'est
propre et autorisé. Deux exemples ici :
- **France Travail** (l'ex-Pôle Emploi) : la source officielle, très complète.
- **Adzuna** : un agrégateur qui rassemble des offres de partout.

### Les sources « ATS »
Beaucoup d'entreprises publient leurs offres sur des outils spécialisés appelés **ATS**
(*Applicant Tracking System*, « système de suivi des candidatures »). Des noms comme
**Greenhouse**, **Lever**, **Ashby**. Ce sont les pages « carrières » des entreprises.
L'astuce : peu de candidats vont les regarder une par une, donc il y a **moins de
concurrence**. Le programme, lui, peut en visiter beaucoup très vite.

### Une source « scraping »
Parfois, il n'y a pas de porte officielle (pas d'API). Il faut alors **lire la page web
comme le ferait un humain** et en extraire les informations. Ça s'appelle du **scraping**
(« grattage »). C'est plus fragile (si le site change sa présentation, ça casse), donc on
le fait avec précaution. Ici, le site **HelloWork** est lu de cette façon.

> Un détail malin : sur HelloWork, chaque offre a une petite description cachée prévue
> pour les personnes malvoyantes (un `aria-label`), du genre *« Voir offre de Data
> Engineer à Paris, chez Team.is, pour un CDI »*. Cette phrase est **bien rangée et
> stable** : on l'utilise pour extraire le titre, le lieu, l'entreprise et le contrat
> d'un coup. C'est plus fiable que de deviner à partir de la mise en page.

### Quand une source ne marche pas
Règle d'or du projet : **si une source tombe en panne, le programme continue avec les
autres**. Un site en panne, une page qui a changé, une entreprise qui a fermé sa page —
rien de tout ça ne doit arrêter toute la chaîne. Chaque source est isolée, comme un
disjoncteur qui saute tout seul sans couper la maison entière.

---

## 4. Le tri : garder le bon, jeter le bruit (le « filtrage »)

Une fois toutes les offres rassemblées (environ **2 300** chaque matin !), il faut faire
le ménage. Le programme garde une offre seulement si :

1. elle parle bien du métier visé (« data engineer », « analytics engineer »…),
2. elle **n'est pas** pour un profil expérimenté (on jette les « senior », « lead »,
   « 5 ans d'expérience »… car on cherche un **premier emploi**),
3. elle est au bon endroit (Paris, Lyon, télétravail…).

Après ce tri, il reste environ **200** offres. On est passé de 2 300 à 200 : le bruit a
été écarté.

---

## 5. Les doublons : la même offre, vue plusieurs fois

La même offre peut apparaître sur plusieurs sources à la fois. Si on ne fait rien, tu la
recevrais en double. Le programme doit donc reconnaître que « Data Engineer chez X » vu
sur deux sites, c'est **la même chose**.

Comment ? Il fabrique une sorte d'**empreinte digitale** pour chaque offre, à partir du
nom de l'entreprise et du début du titre. Avant de comparer, il met tout en minuscules et
enlève les accents, pour que « Ingénieur Données » et « ingenieur donnees » donnent la
même empreinte. Deux offres avec la même empreinte = la même offre → on n'en garde qu'une.

> Le terme technique pour cette empreinte est un **hash**. Retiens juste l'idée : une
> petite signature qui identifie une offre de façon stable, même si l'écriture varie un peu.

---

## 6. La note : quelles offres sont les meilleures ? (le « scoring »)

Toutes les offres ne se valent pas pour toi. Le programme donne donc une **note** à
chacune (le *scoring*). Plus la note est haute, plus l'offre te correspond.

- **+ des points** si l'offre mentionne des mots qui t'arrangent : « junior »,
  « débutant », ou des technologies que tu maîtrises (Python, SQL, Airflow…).
- **− des points** si elle sent le poste peu adapté (certaines sociétés de conseil).

(Certaines offres sont même **écartées d'emblée** si elles ne correspondent pas à la
cible : un poste « senior », ou une **alternance** — qui est un contrat d'études, alors
qu'on cherche ici un vrai premier emploi en CDI/CDD.)

### L'idée la plus astucieuse du projet : la « saturation »
Voici le raisonnement : **si une offre est partout, c'est qu'elle a déjà été vue par tout
le monde** — donc elle est sûrement déjà submergée de candidatures. À l'inverse, une offre
qu'on ne trouve **que sur une seule source** est une **pépite** potentielle, encore peu
connue.

Alors le programme :
- **booste** les offres exclusives (vues sur 1 seule source),
- **pénalise** les offres présentes partout (4 sources ou plus).

C'est exactement la stratégie d'un bon chercheur d'emploi : viser là où les autres ne
regardent pas encore.

À la fin, les offres sont triées de la meilleure note à la moins bonne, et on garde le
**top 30**.

---

## 7. La mémoire : ne jamais te répéter

Si le programme tournait sans mémoire, il t'enverrait les **mêmes** offres tous les jours.
Insupportable.

Il garde donc un petit **carnet** où il note les offres déjà vues. Ce carnet est une
**base de données** (un fichier qui stocke des informations de façon organisée et
interrogeable) appelée **SQLite**. SQLite est minuscule et tient dans un seul fichier —
parfait pour ce besoin modeste.

Chaque matin, le programme compare les offres du jour avec son carnet :
- offre déjà connue → on l'ignore,
- offre nouvelle → on te la propose, et on l'ajoute au carnet.

C'est ce qui fait que tu ne reçois **que les nouveautés**.

---

## 8. La livraison : le message Telegram

Les meilleures offres nouvelles te sont envoyées sur **Telegram**, sous forme d'un message
clair : titre, entreprise, lieu, type de contrat, et un **lien cliquable** pour postuler.

Pourquoi Telegram et pas un email ? Parce que ta boîte mail est déjà pleine d'alertes, et
qu'un bot Telegram est très simple à mettre en place et arrive directement sur ton
téléphone. Un **bot**, c'est juste un compte automatique qui envoie des messages à ta place.

> Petit détail technique : Telegram impose des règles d'écriture strictes (certains
> caractères comme `.` ou `-` doivent être « protégés »). Le programme s'en occupe tout
> seul, pour que le message s'affiche correctement.

---

## 9. L'automatisation : tourner tout seul, tous les matins

Tout ce qu'on a décrit, il faut que ça se déclenche **chaque matin, sans que personne
n'appuie sur un bouton**. C'est le rôle de **GitHub Actions**.

- **GitHub** est un site où l'on stocke et partage du code.
- **GitHub Actions** est un service qui peut **exécuter ton code automatiquement** selon
  un horaire que tu fixes.

On lui a dit : « tous les jours à 7h du matin (heure de Paris), lance le programme ». Et il
le fait, sur les serveurs de GitHub, gratuitement. On appelle ça un **cron** : une tâche
programmée à heure fixe (le mot vient d'un vieil outil Unix qui faisait déjà ça).

> Comme ces serveurs sont « jetables » (ils disparaissent après chaque exécution), il faut
> ruser pour conserver le fameux carnet (la base SQLite) d'un jour à l'autre. On le range
> dans un **cache** : un petit espace de stockage que GitHub garde entre deux exécutions.

---

## 10. Et la sécurité ? (les « secrets »)

Pour utiliser certaines sources et Telegram, le programme a besoin de **clés** et de
**mots de passe** (des identifiants). Règle absolue : **on ne met JAMAIS ces secrets dans
le code**. Si on le faisait, quiconque voit le code verrait aussi tes mots de passe.

À la place :
- en local (sur ton ordinateur), ils sont dans un fichier `.env` qui **n'est jamais
  partagé** (il est volontairement exclu de ce qui part sur GitHub) ;
- sur GitHub, ils sont rangés dans un coffre-fort intégré appelé **Secrets**, chiffrés et
  invisibles.

C'est une habitude fondamentale en programmation : **le code peut être public, les secrets
restent privés**.

---

## 11. Comment on s'assure que ça marche ? (les « tests »)

Quand on écrit du code, on peut facilement casser quelque chose sans le voir. Pour s'en
prémunir, on écrit des **tests** : de petits programmes qui vérifient automatiquement que
le code fait bien ce qu'il doit.

Par exemple : « si je donne au programme une offre à Berlin, est-ce qu'il la rejette bien
(puisqu'on vise la France) ? ». Si un jour on casse cette règle par erreur, le test échoue
et nous prévient **avant** que le problème n'arrive en vrai.

Ce projet a **69 tests**. C'est un filet de sécurité : on peut modifier le code sereinement,
les tests nous disent tout de suite si on a cassé quelque chose.

---

## 12. Le vocabulaire, en résumé

| Mot | En une phrase |
|---|---|
| **Pipeline** | Une chaîne d'étapes qui se passent le relais. |
| **Source** | Un endroit d'où viennent les offres. |
| **API** | Une porte officielle pour que les programmes posent des questions à un site. |
| **ATS** | L'outil où les entreprises publient leurs offres (leur page carrières). |
| **Scraping** | Lire une page web pour en extraire des infos, faute d'API. |
| **Filtrage** | Garder ce qui nous concerne, jeter le reste. |
| **Hash** | Une empreinte stable qui identifie une offre. |
| **Scoring** | Donner une note pour classer les offres. |
| **Saturation** | Pénaliser les offres vues partout, booster les exclusives. |
| **Base de données / SQLite** | Le carnet qui mémorise ce qu'on a déjà vu. |
| **Bot Telegram** | Un compte automatique qui t'envoie les offres. |
| **GitHub Actions / cron** | Le système qui lance le programme tout seul, chaque matin. |
| **Secret** | Un identifiant sensible, gardé en dehors du code. |
| **Test** | Un petit programme qui vérifie que le code marche. |

---

## 13. Ce qu'il faut retenir

Ce projet n'invente rien de magique. Il **automatise un travail humain pénible** en le
découpant en petites étapes simples, et il ajoute **une pointe d'intelligence** (la
détection de saturation) pour viser là où la concurrence est plus faible.

Les grands principes que tu peux emporter avec toi, même débutant :

1. **Découper un gros problème en petites étapes claires.**
2. **Prévoir la panne** : un composant qui tombe ne doit pas tout faire tomber.
3. **Ne pas se répéter** : garder une mémoire de ce qui a déjà été fait.
4. **Garder les secrets en dehors du code.**
5. **Écrire des tests** pour avancer sans peur.
6. **Laisser la configuration dehors** (ici un simple fichier que tu peux éditer sans
   toucher au code) pour adapter le comportement sans tout reprogrammer.

Si tu as compris ces six idées, tu as compris l'essentiel — pas seulement de ce projet,
mais d'une bonne partie de ce qu'est « bien programmer ».

---

> Pour aller plus loin : la documentation technique complète est dans
> [`doc.md`](doc.md) et ses annexes. Le fonctionnement côté utilisateur est dans le
> [README](../README.md).
