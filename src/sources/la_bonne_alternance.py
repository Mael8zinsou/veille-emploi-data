"""La bonne alternance : API publique de l'apprentissage (fil Alternance).

Sondage du 25/10 (docs/sondages_lot0.md, § 2) : `/api/job/v1/search` par codes ROME, avec ou
sans géolocalisation, offres triées de la plus récente à la plus ancienne. Chaque offre
porte `partner_label`, la plateforme d'origine.

Les offres reprises de France Travail et de HelloWork sont ignorées : ces deux sites sont
déjà interrogés directement, et leurs copies arrivent ici sous la raison sociale de
l'employeur (« MANUFACTURE FRANCAISE DES PNEUMATIQUES MICHELIN » au lieu de « Michelin »),
ce qui ferait des doublons. La source apporte donc ce que les autres n'ont pas : la Place
de l'apprentissage et des stages (fonction publique), Jobs that make sense, les offres
déposées directement sur La bonne alternance, etc.

Accès : clé personnelle (secret LBA_API_KEY). Usage non commercial.
"""
from __future__ import annotations

import html
import logging
import os
from urllib.parse import parse_qs, urlparse

from src.models import Fil, Offre
from src.sources import Contexte, SourceIndisponible

NOM = "la_bonne_alternance"
logger = logging.getLogger(__name__)

URL = "https://api.apprentissage.beta.gouv.fr/api/job/v1/search"


def _lien(apply_url: str) -> str:
    """Les liens HelloWork passent par un traceur qui porte l'adresse réelle dans `from`."""
    if not apply_url:
        return ""
    cible = parse_qs(urlparse(apply_url).query).get("from")
    return cible[0] if cible else apply_url


def convertir(job: dict) -> Offre:
    ident, lieu_travail = job.get("identifier") or {}, job.get("workplace") or {}
    offre, contrat = job.get("offer") or {}, job.get("contract") or {}
    publication = (offre.get("publication") or {}).get("creation") or ""
    romes = offre.get("rome_codes") or []
    return Offre(
        source=NOM,
        id_source=str(ident.get("id", "")),
        titre=html.unescape(offre.get("title") or "").strip(),
        entreprise=(lieu_travail.get("brand") or lieu_travail.get("name") or lieu_travail.get("legal_name") or "").strip(),
        lieu=((lieu_travail.get("location") or {}).get("address") or "").strip(),
        url=_lien((job.get("apply") or {}).get("url") or ""),
        description=html.unescape(offre.get("description") or ""),
        contrat_brut=" ou ".join(contrat.get("type") or []) or "Apprentissage",
        date_publication=publication[:10],
        duree_mois=contrat.get("duration"),
        code_rome=romes[0] if romes else "",
        diffuseur=ident.get("partner_label") or "",
        delegue_par_ecole=bool(job.get("is_delegated")),
        fil_demande=Fil.ALTERNANCE,
    )


def fetch(ctx: Contexte) -> list[Offre]:
    cle = os.getenv("LBA_API_KEY")
    if not cle:
        raise SourceIndisponible("la_bonne_alternance : LBA_API_KEY absent")
    cfg = ctx.config.sources.la_bonne_alternance
    exclus = {p.lower() for p in cfg.partenaires_exclus}
    par_id: dict[str, Offre] = {}
    ignorees = 0
    for recherche in cfg.recherches:
        params = {"romes": ",".join(cfg.romes)}
        if recherche.latitude is not None:
            params |= {"latitude": recherche.latitude, "longitude": recherche.longitude, "radius": recherche.rayon_km}
        r = ctx.get(URL, params=params, headers={"Authorization": f"Bearer {cle}"})
        if r is None:
            continue
        try:
            jobs = r.json().get("jobs") or []
        except ValueError:
            ctx.erreurs.append("la_bonne_alternance : réponse illisible")
            continue
        for job in jobs:
            o = convertir(job)
            if o.diffuseur.lower() in exclus:
                ignorees += 1
                continue
            if o.id_source and o.titre:
                par_id.setdefault(o.id_source, o)
    ctx.verifier(NOM)
    logger.info("la_bonne_alternance : %d offres (%d reprises de sources déjà lues), %d requêtes",
                len(par_id), ignorees, ctx.requetes)
    return list(par_id.values())
