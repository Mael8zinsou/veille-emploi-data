"""Normalisation complète d'une offre, puis filtres éliminatoires avec motif (conception § 5).

`trier(offres, config, aujourdhui)` rend deux listes : les offres gardées (normalisées) et les
rejets, chacun avec son motif. L'ordre des filtres fixe le motif enregistré, ce qui compte
pour la Route B : une offre senior d'un employeur final doit être reconnue comme telle, pas
comme « trop ancienne ».
"""
from __future__ import annotations

import re
from datetime import date

from src.config import Config
from src.models import Contrat, Motif, Offre, Rejet, TypeEmployeur
from src.normalisation import contrats, employeurs, experience, lieux, metiers
from src.normalisation.texte import normaliser, premier_motif, retirer


def normaliser_offre(o: Offre, config: Config, delegue_par_ecole: bool = False) -> Offre:
    """Complète l'offre en place : famille, contrat, fil, employeur, lieu, expérience."""
    famille, _ = metiers.reconnaitre(o.titre, config.metiers, o.code_rome)
    if famille:
        o.famille, o.priorite = famille.nom, famille.priorite
    o.contrat = contrats.determiner(o.titre, o.contrat_brut, config.filtres, o.fil_demande)
    if o.duree_mois is None:
        o.duree_mois = contrats.duree_en_mois(o.contrat_brut)
    o.fil = contrats.fil_du_contrat(o.contrat)
    o.type_employeur = employeurs.classer(o.entreprise, config.filtres.employeurs,
                                         delegue_par_ecole or o.delegue_par_ecole)
    a = lieux.analyser(o.lieu, o.titre, config.filtres.lieux)
    o.teletravail_complet, o.zone_preferee = a.teletravail_complet, a.zone_preferee
    o.annees_requises = experience.annees_requises(o.titre, o.description, o.experience_annees)
    # 9/11 (EXPERTIME) : France Travail affichait « Débutant accepté », le texte demandait 8 ans.
    # Le champ structuré reste la règle (calibrage du 26/10) ; l'écart devient un signal.
    if o.experience_annees is not None:
        texte = experience.annees_requises("", o.description)
        o.annees_texte = texte if texte is not None and texte >= 3 and texte > o.experience_annees else None
    o.via_cabinet = employeurs.est_cabinet(o.entreprise, config.filtres.employeurs)
    o.permis_exige = permis_exige(f"{o.titre}. {o.description}", config)
    o.lettre_demandee = lettre_demandee(o.description)
    return o


_LETTRE = re.compile(r"\blettre de motivation\b|\bcv (?:et )?(?:une )?lettre\b")


def lettre_demandee(description: str) -> bool:
    """Lettre de motivation citée dans l'annonce (10/11) : Claude la prépare avant la session,
    au lieu de la découvrir dans le formulaire."""
    return bool(_LETTRE.search(normaliser(description or "")))


_STAGE_DUREE = re.compile(r"\bstage (?:de |d )?\d{1,2} (?:a \d{1,2} )?mois\b")


def stage_dans_description(description: str, config: Config) -> str | None:
    """Stage annoncé dans le texte d'une offre déclarée CDI ou CDD : « pour un stage de 6 mois »,
    « pour la réussite de ce stage ». Rend l'expression trouvée."""
    texte = normaliser(description)
    m = _STAGE_DUREE.search(texte)
    if m:
        return m.group(0)
    return premier_motif(texte, config.filtres.contrats.stage_description)


def permis_exige(texte: str, config: Config) -> bool:
    """« Permis B exigé », « permis de conduire obligatoire » : même règle de proximité que pour les
    certifications, proposition par proposition. Signalé, jamais éliminatoire."""
    mots = "|".join(re.escape(m) for m in config.filtres.certification_exigee.mots)
    motif = re.compile(rf"\bpermis (?:b|de conduire)(?: \w+){{0,3}} (?:{mots})\b")
    return any(motif.search(normaliser(p)) for p in re.split(r"[.,;:!?\n()]", texte or ""))


def titre_senior(titre: str, config: Config) -> str | None:
    """Mot de séniorité du titre (« senior », « docteur »...), hors métiers en exception."""
    s = config.filtres.seniorite
    return premier_motif(retirer(normaliser(titre), s.exceptions), s.titre)


def filiere_reservee(entreprise: str, config: Config) -> str | None:
    """Motif de filière réservée (« talents handicap »...) reconnu dans le nom de l'employeur."""
    return premier_motif(normaliser(entreprise or ""), config.filtres.employeurs.filieres_reservees)


def _seniorite(o: Offre, config: Config) -> str | None:
    s = config.filtres.seniorite
    mot = titre_senior(o.titre, config)
    if mot:
        return f"titre : {mot}"
    if o.annees_requises is not None and o.annees_requises > s.annees_max:
        return f"{o.annees_requises} ans d'expérience demandés"
    return None


def _certification_exigee(texte: str, config: Config) -> str | None:
    """« certifi… » suivi, dans la même proposition et à quelques mots au plus, d'un mot
    d'exigence. Rend l'extrait trouvé. La recherche se fait proposition par proposition (le
    texte brut est coupé sur la ponctuation) : « une certification, le permis est requis »
    ne compte pas."""
    c = config.filtres.certification_exigee
    mots = "|".join(re.escape(m) for m in c.mots)
    motif = re.compile(rf"\bcertifi\w*(?: \w+){{0,{c.fenetre}}} (?:{mots})\b")
    for proposition in re.split(r"[.,;:!?\n()]", texte):
        m = motif.search(normaliser(proposition))
        if m:
            return m.group(0)
    return None


def motif_de_rejet(o: Offre, config: Config, aujourdhui: date) -> tuple[Motif, str] | None:
    """Premier filtre qui élimine l'offre normalisée, ou None si elle est gardée."""
    f = config.filtres
    if not o.famille:
        return Motif.METIER_HORS_CIBLE, ""
    analyse = lieux.analyser(o.lieu, o.titre, f.lieux)
    if analyse.etranger and not analyse.teletravail_complet:
        return Motif.LIEU_ETRANGER, analyse.etranger
    if o.type_employeur == TypeEmployeur.PLATEFORME:
        return Motif.PLATEFORME_MISSIONS, o.entreprise
    if filiere_reservee(o.entreprise, config):
        return Motif.FILIERE_RESERVEE, o.entreprise
    if o.contrat == Contrat.FREELANCE:
        return Motif.FREELANCE, o.contrat_brut
    if o.contrat == Contrat.STAGE:
        return Motif.STAGE_CONVENTIONNE, ""
    if o.contrat in (Contrat.CDI, Contrat.CDD, Contrat.INTERIM, Contrat.INCONNU):
        stage = stage_dans_description(o.description, config)
        if stage:
            return Motif.STAGE_CONVENTIONNE, f"description : {stage}"
    if o.fil is None:
        return Motif.CONTRAT_HORS_CIBLE, o.contrat_brut
    detail = _seniorite(o, config)
    if detail:
        return Motif.SENIORITE, detail
    certification = _certification_exigee(f"{o.titre}. {o.description}", config)
    if certification:
        return Motif.CERTIFICATION_EXIGEE, certification
    if (o.contrat in (Contrat.CDD, Contrat.INTERIM) and o.duree_mois is not None
            and o.duree_mois < f.duree_min_mois):
        return Motif.DUREE_TROP_COURTE, f"{o.duree_mois} mois"
    if o.date_publication:
        try:
            age = (aujourdhui - date.fromisoformat(o.date_publication[:10])).days
        except ValueError:
            age = None
        if age is not None and age > f.fraicheur_max_jours:
            return Motif.TROP_ANCIENNE, f"{age} jours"
    return None


def trier(offres: list[Offre], config: Config, aujourdhui: date) -> tuple[list[Offre], list[Rejet]]:
    gardees, rejets = [], []
    for o in offres:
        normaliser_offre(o, config)
        motif = motif_de_rejet(o, config, aujourdhui)
        if motif:
            rejets.append(Rejet(o, *motif))
        else:
            gardees.append(o)
    return gardees, rejets
