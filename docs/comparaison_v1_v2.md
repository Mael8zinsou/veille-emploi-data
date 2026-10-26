# Comparaison v1 / v2 sur les mêmes offres (26 octobre 2026)

> Workflow `comparaison.yml` (branche `comparaison`) : la v1 (code de `main`) et la v2 tournent
> au même moment sur les vraies sources, **sans aucun envoi** (secrets Telegram non transmis),
> la base de production restaurée en lecture dans une copie jetable. Détail : branche `sondes`,
> dossiers `comparaison/2026-10-26_0013/` et `comparaison/2026-10-26_0020/`.

## Question 1 : la v2 écarte-t-elle des offres que la v1 enverrait ?

La v1 jugeait 91 offres notifiables (note d'au moins 5). La v2 en garde 76 et en écarte 15,
toutes à raison :

| Motif v2 | Offres | Vérification |
|---|---|---|
| Freelance | 8 | Contrat « Indépendant » ou « Freelance » : hors cible (CDC § 3.2). La v1 les envoyait |
| Trop ancienne | 3 | Offres de sites carrières publiées il y a 82 à 88 jours |
| Séniorité | 1 | « Minimum 8 ans d'expérience » dans la description. La v1 l'envoyait |
| Lieu étranger | 1 | Belgique, sortie du périmètre le 25/10 |
| Stage | 1 | Contrat déclaré « Stage » |
| Métier hors cible | 1 | « Software Engineering Intern » |

**Aucune régression de filtrage.** La v2 corrige deux défauts de la v1 : des freelances et une
offre à 8 ans d'expérience lui étaient envoyés.

## Question 2 : les requêtes de la v2 retrouvent-elles ces offres ?

| Version des requêtes | Retrouvées |
|---|---|
| Lot 1 initial (codes ROME seuls, « data » générique sur Adzuna) | 30 sur 91 |
| Après correction (mots-clés France Travail, intitulés ciblés Adzuna, HelloWork élargi) | **63 sur 91** |

Les 28 restantes :

* **Sites carrières (Greenhouse, Lever, Ashby, Teamtailor)** : retirés par décision (7 offres en
  quatre mois en production), dont les 3 offres de 82 à 88 jours.
* **Adzuna** : surtout des ESN et des republicateurs (Proxiad, Altim, Proxiel, Seenovate,
  Ingeniance, Mercato de l'emploi), et quelques employeurs finaux (Mondelez, 360Learning).
  Limite structurelle : le quota de 250 requêtes par mois. Deux requêtes ont été ajustées
  (Analytics Engineer à la place d'Ingénieur Data) après ce constat.
* **HelloWork** : résultats classés par pertinence, sans tri par date exploitable (sondage du
  26/10). Un passage toutes les trois heures sur quatre pages en rattrape une partie au fil de
  la journée.

Une comparaison sur un seul instant défavorise la v2 : en production, ses passages horaires
s'additionnent sur la journée, alors que cet essai n'en compte qu'un.

## Question 3 : qu'apporte la v2 ?

1 651 offres brutes, 592 gardées, dont **527 que la v1 ne voit pas du tout** : analyse de données
(167), Data Engineering (109), IA et ML (93), Data Science (84), métiers voisins (55), Analytics
Engineering (9), gouvernance (8), BI (2). C'est l'effet attendu de l'élargissement de la cible.

## Points à reprendre

1. **Quota Adzuna partagé pendant le mode ombre** : la v1 et la v2 utilisent la même clé. Pendant
   les jours où les deux tournent (lot 3), Adzuna doit être coupée dans l'une des deux.
2. La note (lot 2) doit faire le tri dans ce volume : 592 offres gardées sur un passage, c'est
   l'inverse du problème de la v1.
3. Refaire cette comparaison avant la bascule, avec la note, sur plusieurs jours.
