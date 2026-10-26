"""Adzuna, API de recherche (quota gratuit de 250 requêtes par mois).

Sondage du lot 0 : la recherche sur le titre (`title_only`) donne un flux net, environ 365
titres « data » par jour en France. Chaque page coûte une requête ; le planning et le
compteur mensuel en base gardent la consommation sous le plafond configuré.
"""
from __future__ import annotations

import logging
import os

from src.models import Offre
from src.sources import Contexte, SourceIndisponible

NOM = "adzuna"
logger = logging.getLogger(__name__)

URL = "https://api.adzuna.com/v1/api/jobs/fr/search/{page}"


def convertir(item: dict) -> Offre:
    return Offre(
        source=NOM,
        id_source=str(item.get("id", "")),
        titre=item.get("title") or "",
        entreprise=(item.get("company") or {}).get("display_name") or "",
        lieu=(item.get("location") or {}).get("display_name") or "",
        url=item.get("redirect_url") or "",
        description=(item.get("description") or "")[:3000],
        contrat_brut=item.get("contract_type") or "",
        date_publication=(item.get("created") or "")[:10],
    )


def fetch(ctx: Contexte) -> list[Offre]:
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise SourceIndisponible("adzuna : ADZUNA_APP_ID ou ADZUNA_APP_KEY absent")
    cfg = ctx.config.sources.adzuna
    offres: list[Offre] = []
    for req in cfg.requetes:
        for page in range(1, req.pages + 1):
            params = {"app_id": app_id, "app_key": app_key, "results_per_page": cfg.par_page,
                      "max_days_old": cfg.max_jours, "sort_by": "date", "content-type": "application/json"}
            if req.title_only:
                params["title_only"] = req.title_only
            if req.what:
                params["what"] = req.what
            r = ctx.get(URL.format(page=page), params=params)
            if r is None:
                break
            try:
                resultats = r.json().get("results", [])
            except ValueError:
                ctx.erreurs.append("adzuna : JSON illisible")
                break
            offres.extend(convertir(i) for i in resultats)
            if len(resultats) < cfg.par_page:
                break
    ctx.verifier(NOM)
    logger.info("adzuna : %d offres, %d requêtes", len(offres), ctx.requetes)
    return offres
