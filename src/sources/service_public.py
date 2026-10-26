"""Choisir le service public : flux RSS publics de la Place de l'emploi public (Talentsoft).

Sondages du 25 et du 26/10 (docs/sondages_lot0.md, § 2) :

* La page de recherche du site pèse 4,5 Mo par page de 20 offres, n'est pas triée par date
  et son filtre de date est peu fiable : écartée.
* Les flux RSS de la plateforme existent par métier du répertoire de la fonction publique
  (« Data engineer », « Data Scientist », « Analyste de données »…) et par domaine
  (« Numérique »). Chaque flux rend les 20 offres les plus récentes, avec la description
  complète et la nature de l'emploi (ouvert aux contractuels ou réservé aux fonctionnaires).
  Les flux métier couvrent plusieurs semaines ; le flux Numérique, moins d'une journée,
  sert de filet pour les offres mal rangées.
* Passerelles (ministères économiques et financiers) publie sur la même plateforme : ses
  offres sont déjà dans ces flux (références MEF_…). Pas de source séparée.
* Le flux ne donne pas l'employeur. La page de l'offre porte un bloc JSON-LD JobPosting :
  employeur, niveau d'expérience (Débutant, Confirmé, Expert), date de publication, lieu.
  On ne la lit que pour les offres au titre reconnu, fraîches et ouvertes aux contractuels,
  dans la limite de `max_details` par passage.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

from src.models import Offre
from src.normalisation import metiers
from src.normalisation.texte import normaliser
from src.sources import Contexte

NOM = "service_public"
logger = logging.getLogger(__name__)

FLUX = "https://place-ep-recrute.talent-soft.com/handlers/offerRss.ashx"
CONTRACTUEL = "CDD (contractuel de la fonction publique)"
FONCTIONNAIRES = "Réservé aux fonctionnaires"

_TITRE = re.compile(r"^\s*(?P<ref>\S+) - (?P<titre>.+)$", re.S)
_JSON_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_BALISES = re.compile(r"<[^>]+>")


def _texte(fragment: str) -> str:
    t = _BALISES.sub("\n", html.unescape(fragment or ""))
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _date(rfc822: str) -> str:
    try:
        return parsedate_to_datetime(rfc822.replace(" Z", " +0000")).date().isoformat()
    except (TypeError, ValueError):
        return ""


def nature_vers_contrat(nature: str) -> str:
    """« Emploi ouvert aux titulaires et/ou aux contractuels » : CDD de contractuel.
    « Emploi ouvert aux titulaires », « réservé aux fonctionnaires » : hors cible."""
    return CONTRACTUEL if "contractuel" in normaliser(nature) else FONCTIONNAIRES


def lire_flux(texte: str) -> list[Offre]:
    """Offres d'un flux RSS, sans employeur (complété par `completer`)."""
    try:
        racine = ET.fromstring(texte.encode("utf-8"))
    except ET.ParseError:
        return []
    offres = []
    for item in racine.findall(".//item"):
        m = _TITRE.match(html.unescape(item.findtext("title") or ""))
        if not m:
            continue
        categories = [(c.text or "").strip() for c in item.findall("category")]
        nature = next((c for c in categories if "emploi" in normaliser(c)), "")
        lieu = categories[2] if len(categories) > 2 else ""
        lien = (item.findtext("link") or "").split("?")[0]
        offres.append(Offre(
            source=NOM,
            id_source=m.group("ref"),
            titre=re.sub(r"\s+", " ", m.group("titre")).strip(),
            entreprise="",
            lieu=lieu,
            url=lien,
            description=_texte(item.findtext("description") or ""),
            contrat_brut=nature_vers_contrat(nature),
            date_publication=_date(item.findtext("pubDate") or ""),
        ))
    return offres


def lire_detail(texte: str) -> dict:
    """Bloc JSON-LD JobPosting de la page d'une offre, ou {}."""
    for bloc in _JSON_LD.findall(texte or ""):
        try:
            donnees = json.loads(bloc)
        except ValueError:
            continue
        if isinstance(donnees, dict) and donnees.get("@type") == "JobPosting":
            return donnees
    return {}


def completer(o: Offre, detail: dict) -> None:
    """Employeur, lieu, date et expérience depuis la page de l'offre."""
    employeur = detail.get("hiringOrganization")
    if isinstance(employeur, dict):
        employeur = employeur.get("name", "")
    if employeur:
        o.entreprise = str(employeur).strip()
    if detail.get("addressLocality"):
        o.lieu = str(detail["addressLocality"]).replace(", France", "").strip()
    publie = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(detail.get("datePosted", "")))
    if publie:
        o.date_publication = f"{publie.group(3)}-{publie.group(2)}-{publie.group(1)}"
    niveau = normaliser(str(detail.get("experienceRequirements", "")))
    if niveau == "debutant":
        o.debutant_accepte = True
    elif niveau == "expert":
        # Niveau « Expert » du site : poste senior. Traduit en exigence d'expérience pour
        # passer par la règle de séniorité (plus de 3 ans : écarté).
        o.experience_annees = 5


def _a_completer(o: Offre, ctx: Contexte) -> bool:
    if o.contrat_brut != CONTRACTUEL:
        return False
    famille, _ = metiers.reconnaitre(o.titre, ctx.config.metiers)
    if famille is None:
        return False
    if o.date_publication:
        limite = ctx.maintenant_utc.date() - timedelta(days=ctx.config.filtres.fraicheur_max_jours)
        if date.fromisoformat(o.date_publication) < limite:
            return False
    return True


def fetch(ctx: Contexte) -> list[Offre]:
    cfg = ctx.config.sources.service_public
    par_ref: dict[str, Offre] = {}
    for flux in cfg.flux:
        params = {"LCID": 1036}
        if flux.profil:
            params["Rss_Profile"] = flux.profil
        if flux.famille:
            params["Rss_JobFamily"] = flux.famille
        r = ctx.get(FLUX, params=params)
        if r is not None:
            for o in lire_flux(r.text):
                par_ref.setdefault(o.id_source, o)
        time.sleep(cfg.delai_secondes)
    ctx.verifier(NOM)

    offres = list(par_ref.values())
    a_lire = [o for o in offres if _a_completer(o, ctx)]
    lues = 0
    for o in a_lire[:cfg.max_details]:
        r = ctx.get(o.url)
        if r is not None:
            completer(o, lire_detail(r.text))
            lues += 1
        time.sleep(cfg.delai_secondes)
    if len(a_lire) > cfg.max_details:
        logger.warning("service_public : %d pages d'offre à lire, limite %d", len(a_lire), cfg.max_details)
    logger.info("service_public : %d offres, %d pages d'offre lues, %d requêtes", len(offres), lues, ctx.requetes)
    return offres
