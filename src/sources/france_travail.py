"""France Travail, API Offres d'emploi v2 (socle, sondage du lot 0).

* Authentification OAuth2 (client_credentials), jeton valable 24 heures.
* Emploi : une requête par code ROME, puis par mot-clé pour les métiers sans code propre.
* Alternance : `natureContrat` E2 (apprentissage) et FS (professionnalisation).
* L'API exige `minCreationDate` ET `maxCreationDate` ensemble (correctif hérité de la v1).
* Pagination par `range` (150 offres par page), tant que `Content-Range` annonce la suite.
* Champs exploités, nouveaux en v2 : `experienceExige` et `experienceLibelle` (séniorité
  sans deviner), `offresManqueCandidats` (offre peu candidatée), `romeCode`, partenaire de
  diffusion.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import timedelta

from src.models import Fil, Offre
from src.normalisation.experience import depuis_france_travail
from src.sources import Contexte, SourceIndisponible

NOM = "france_travail"
logger = logging.getLogger(__name__)

URL_JETON = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
URL_RECHERCHE = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
URL_DETAIL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"
PAR_PAGE = 150
PAUSE = 0.25   # secondes entre deux requêtes : l'API limite le débit par application


def _jeton(ctx: Contexte) -> str:
    cid, secret = os.getenv("FT_CLIENT_ID"), os.getenv("FT_CLIENT_SECRET")
    if not cid or not secret:
        raise SourceIndisponible("france_travail : FT_CLIENT_ID ou FT_CLIENT_SECRET absent")
    r = ctx.post(URL_JETON, params={"realm": "/partenaire"},
                 data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
                       "scope": "api_offresdemploiv2 o2dsoffre"})
    jeton = r.json().get("access_token") if r is not None else None
    if not jeton:
        raise SourceIndisponible("france_travail : jeton refusé")
    return jeton


def convertir(item: dict, fil: Fil) -> Offre:
    lieu = item.get("lieuTravail") or {}
    entreprise = item.get("entreprise") or {}
    origine = item.get("origineOffre") or {}
    partenaires = origine.get("partenaires") or []
    annees, debutant = depuis_france_travail(item.get("experienceExige"), item.get("experienceLibelle"))
    nature = item.get("natureContrat") or ""
    type_c = f"{item.get('typeContrat') or ''} {item.get('typeContratLibelle') or ''}".strip()
    return Offre(
        source=NOM,
        id_source=str(item.get("id", "")),
        titre=item.get("intitule") or "",
        entreprise=entreprise.get("nom") or "",
        lieu=lieu.get("libelle") or "",
        url=origine.get("urlOrigine") or URL_DETAIL.format(id=item.get("id", "")),
        description=(item.get("description") or "")[:3000],
        # La nature (apprentissage, professionnalisation) passe avant le type : un CDD
        # d'apprentissage est une alternance.
        contrat_brut=f"{nature} | {type_c}" if nature and nature != "Contrat travail" else type_c,
        date_publication=(item.get("dateCreation") or "")[:10],
        experience_annees=annees,
        debutant_accepte=debutant,
        faible_concurrence=bool(item.get("offresManqueCandidats")),
        code_rome=item.get("romeCode") or "",
        diffuseur=(partenaires[0].get("nom") or "") if partenaires else "",
        fil_demande=fil,
    )


def _rechercher(ctx: Contexte, jeton: str, params: dict, fil: Fil, max_pages: int) -> list[Offre]:
    entetes = {"Authorization": f"Bearer {jeton}", "Accept": "application/json"}
    fenetre = ctx.config.sources.france_travail.fenetre_jours
    dates = {"minCreationDate": (ctx.maintenant_utc - timedelta(days=fenetre)).strftime("%Y-%m-%dT00:00:00Z"),
             "maxCreationDate": ctx.maintenant_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
    offres: list[Offre] = []
    for page in range(max_pages):
        debut = page * PAR_PAGE
        time.sleep(PAUSE)
        r = ctx.get(URL_RECHERCHE, headers=entetes,
                    params={**params, **dates, "range": f"{debut}-{debut + PAR_PAGE - 1}"})
        if r is None or r.status_code == 204:
            break
        try:
            resultats = r.json().get("resultats", [])
        except ValueError:
            ctx.erreurs.append("france_travail : JSON illisible")
            break
        offres.extend(convertir(item, fil) for item in resultats)
        total = r.headers.get("Content-Range", "").rpartition("/")[2]
        if not total.isdigit() or debut + PAR_PAGE >= int(total):
            break
    return offres


def fetch(ctx: Contexte) -> list[Offre]:
    cfg = ctx.config.sources.france_travail
    jeton = _jeton(ctx)
    offres: list[Offre] = []
    e = cfg.emploi
    for code in e.romes:
        offres += _rechercher(ctx, jeton, {"codeROME": code, "typeContrat": e.types_contrat}, Fil.EMPLOI, cfg.max_pages)
    for mot in e.mots_cles:
        offres += _rechercher(ctx, jeton, {"motsCles": mot, "typeContrat": e.types_contrat}, Fil.EMPLOI, 1)
    a = cfg.alternance
    for code in a.romes:
        offres += _rechercher(ctx, jeton, {"codeROME": code, "natureContrat": a.nature_contrat}, Fil.ALTERNANCE, 1)
    for mot in a.mots_cles:
        offres += _rechercher(ctx, jeton, {"motsCles": mot, "natureContrat": a.nature_contrat}, Fil.ALTERNANCE, 1)
    ctx.verifier(NOM, preliminaires=1)
    logger.info("france_travail : %d offres, %d requêtes", len(offres), ctx.requetes)
    return offres
