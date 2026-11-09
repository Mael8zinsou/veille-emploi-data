"""Mode de candidature d'une offre : ce qu'il faudra faire pour postuler (vérification du 9/11).

Sert à la liste du matin : une offre se joue de A à Z (formulaire sans compte), demande que
Maël soit connecté au site (compte), se fait par mail (brouillon Gmail), ou reste à vérifier
dans Chrome (Adzuna, dont les pages refusent les robots).

Le classement se fait sur le domaine du lien de candidature. Les listes ci-dessous viennent
des sondages du 9/11 et des sites vus pendant la recherche ; un domaine inconnu donne « site
de l'employeur », à regarder.
"""
from __future__ import annotations

import re
from datetime import date

from src.models import Candidature, ModeCandidature

# Formulaires qu'on remplit sans créer de compte (nom, mail, CV, quelques questions).
SANS_COMPTE = {
    "greenhouse.io": "Greenhouse", "lever.co": "Lever", "ashbyhq.com": "Ashby", "teamtailor.com": "Teamtailor",
    "welcometothejungle.com": "Welcome to the Jungle", "welcomekit.co": "Welcome Kit", "recruitee.com": "Recruitee",
    "smartrecruiters.com": "SmartRecruiters", "flatchr.io": "Flatchr", "beetween.com": "Beetween",
    "jobaffinity.fr": "Jobaffinity", "digitalrecruiters.com": "Digitalrecruiters", "werecruit.io": "WeRecruit",
    "breezy.hr": "Breezy", "jobs.personio.de": "Personio", "jobs.personio.com": "Personio", "join.com": "JOIN",
    "profils.org": "Profils", "taleez.com": "Taleez", "jobs.workable.com": "Workable", "apply.workable.com": "Workable",
}
# Sites où il faut être connecté (Maël se connecte une fois dans Chrome, Claude ne saisit
# jamais de mot de passe).
AVEC_COMPTE = {
    "myworkdayjobs.com": "Workday", "taleo.net": "Taleo", "successfactors.com": "SuccessFactors",
    "successfactors.eu": "SuccessFactors", "talent-soft.com": "Talentsoft", "emploi.cnrs.fr": "CNRS",
    "hellowork.com": "HelloWork", "francetravail.fr": "France Travail", "apec.fr": "APEC", "indeed.com": "Indeed",
    "indeed.fr": "Indeed", "linkedin.com": "LinkedIn", "meteojob.com": "Meteojob", "directemploi.com": "Direct Emploi",
    "cadremploi.fr": "Cadremploi", "monster.fr": "Monster", "jobteaser.com": "JobTeaser", "icims.com": "iCIMS",
    "jobvite.com": "Jobvite", "csod.com": "Cornerstone", "choisirleservicepublic.gouv.fr": "Choisir le service public",
}
# Diffuseurs France Travail (champ `partenaires`), par nom.
PARTENAIRES_SANS_COMPTE = {"BEETWEEN": "Beetween", "FLATCHR": "Flatchr", "TALEEZ": "Taleez", "JOBAFFINITY": "Jobaffinity"}

_DOMAINE = re.compile(r"^(?:https?://)?([^/?#]+)", re.IGNORECASE)
_DATE_FR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def domaine(url: str) -> str:
    m = _DOMAINE.match(url or "")
    return m.group(1).lower().removeprefix("www.") if m else ""


def _chercher(dom: str, table: dict[str, str]) -> str | None:
    return next((nom for suffixe, nom in table.items() if dom == suffixe or dom.endswith("." + suffixe)), None)


def depuis_lien(lien: str, date_limite: str = "") -> Candidature:
    """Mode de candidature déduit du lien « Postuler »."""
    if (lien or "").lower().startswith("mailto:"):
        return Candidature(ModeCandidature.MAIL, "", lien, date_limite)
    dom = domaine(lien)
    if not dom:
        return Candidature(ModeCandidature.INCONNU, "", "", date_limite)
    nom = _chercher(dom, SANS_COMPTE)
    if nom:
        return Candidature(ModeCandidature.FORMULAIRE, nom, lien, date_limite)
    nom = _chercher(dom, AVEC_COMPTE)
    if nom:
        return Candidature(ModeCandidature.COMPTE, nom, lien, date_limite)
    return Candidature(ModeCandidature.SITE, dom, lien, date_limite)


def depuis_france_travail(item: dict) -> Candidature:
    """Fiche de l'API France Travail : diffuseur partenaire, lien de candidature, mail, ou
    candidature dans l'espace France Travail."""
    contact = item.get("contact") or {}
    partenaires = (item.get("origineOffre") or {}).get("partenaires") or []
    if contact.get("urlPostulation"):
        return depuis_lien(contact["urlPostulation"])
    if contact.get("courriel") and "@" in str(contact["courriel"]):
        return Candidature(ModeCandidature.MAIL, "", f"mailto:{str(contact['courriel']).strip()}")
    if partenaires:
        p = partenaires[0]
        nom = str(p.get("nom") or "").strip()
        if nom.upper() in PARTENAIRES_SANS_COMPTE:
            return Candidature(ModeCandidature.FORMULAIRE, PARTENAIRES_SANS_COMPTE[nom.upper()], p.get("url") or "")
        c = depuis_lien(p.get("url") or "")
        if c.mode in (ModeCandidature.SITE, ModeCandidature.INCONNU):
            # Un diffuseur inconnu (PMEJob, AdSearch...) : on garde son nom, compte probable.
            return Candidature(ModeCandidature.COMPTE, nom.title() or c.plateforme, p.get("url") or "")
        return c
    return Candidature(ModeCandidature.COMPTE, "France Travail", "")


def date_limite_fr(texte: str) -> str:
    """« Date limite de candidature : 20/11/2026 » -> « 2026-11-20 »."""
    m = _DATE_FR.search(texte or "")
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return ""


def depuis_dict(d: dict) -> Candidature | None:
    """Inverse de `Candidature.en_dict` (mémoire des sources, base)."""
    try:
        return Candidature(ModeCandidature(d.get("mode", "inconnu")), d.get("plateforme", ""), d.get("lien", ""),
                           d.get("date_limite", ""))
    except (ValueError, AttributeError):
        return None
