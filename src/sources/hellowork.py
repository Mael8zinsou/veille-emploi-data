"""HelloWork, page de résultats de recherche (HTML statique).

Chaque carte d'offre est une ancre portant le lien et un `aria-label` structuré :
« Voir offre de <titre> à <lieu>, chez <entreprise>[, super recruteur], pour <contrat>[, …] ».
On lit cet `aria-label`, plus stable que des classes CSS générées.

Politesse : délai entre pages, peu de pages. Si le site refuse (403, 429, page de défi), la
source s'arrête pour ce passage, sans insister.
"""
from __future__ import annotations

import html
import logging
import re
import time

from src.models import Fil, Offre
from src.sources import Contexte, SourceIndisponible

NOM = "hellowork"
logger = logging.getLogger(__name__)

URL = "https://www.hellowork.com/fr-fr/emploi/recherche.html"
RACINE = "https://www.hellowork.com"

_ANCRE = re.compile(r'<a\b[^>]*href="(?P<href>/fr-fr/emplois/(?P<id>\d+)\.html)"[^>]*'
                    r'aria-label="(?P<label>Voir offre[^"]+)"', re.IGNORECASE)
# Le titre peut contenir « à » (« Bac+4 à Bac+5 ») : il est gourmand, et le lieu, qui ne
# contient jamais de virgule, est le dernier segment avant « , chez ».
_LABEL = re.compile(r"^Voir offre de (?P<titre>.+) (?:à|a) (?P<lieu>[^,]+?), chez (?P<ent>.+?)"
                    r"(?:, super recruteur)?, pour (?:un |une |le |du )?(?P<contrat>.+?)(?:, en (?P<temps>.+))?$")
_REFUS = ("just a moment", "cf-challenge", "captcha", "access denied")


def lire_page(texte: str, fil: Fil) -> list[Offre]:
    offres = []
    for m in _ANCRE.finditer(texte):
        champs = _LABEL.match(html.unescape(m.group("label")))
        if not champs:
            continue
        offres.append(Offre(
            source=NOM,
            id_source=m.group("id"),
            titre=champs.group("titre").strip(),
            entreprise=champs.group("ent").strip(),
            lieu=champs.group("lieu").strip(),
            url=RACINE + m.group("href"),
            contrat_brut=champs.group("contrat").split(",")[0].strip(),
            fil_demande=fil,
        ))
    return offres


def _refuse(statut: int, texte: str) -> bool:
    return statut in (403, 429, 503) or any(m in texte[:5000].lower() for m in _REFUS)


def fetch(ctx: Contexte) -> list[Offre]:
    cfg = ctx.config.sources.hellowork
    recherches = [(m, Fil.EMPLOI) for m in cfg.emploi] + [(m, Fil.ALTERNANCE) for m in cfg.alternance]
    offres: list[Offre] = []
    for recherche, fil in recherches:
        for page in range(1, cfg.max_pages + 1):
            ctx.requetes += 1
            params = {"k": recherche.k, "p": page}
            if recherche.l:
                params["l"] = recherche.l
            try:
                r = ctx.session.get(URL, params=params, timeout=20)
            except Exception as e:  # réseau : on journalise et on passe
                ctx.erreurs.append(f"hellowork : {e.__class__.__name__}")
                break
            if _refuse(r.status_code, r.text):
                ctx.erreurs.append(f"hellowork : refus (HTTP {r.status_code})")
                logger.warning("hellowork : refus du site (HTTP %s), arrêt pour ce passage", r.status_code)
                if not offres:
                    raise SourceIndisponible(f"hellowork : refus du site (HTTP {r.status_code})")
                return offres
            if r.status_code != 200:
                ctx.erreurs.append(f"hellowork : HTTP {r.status_code}")
                break
            trouvees = lire_page(r.text, fil)
            offres.extend(trouvees)
            if not trouvees:
                break
            time.sleep(cfg.delai_secondes)
    ctx.verifier(NOM)
    logger.info("hellowork : %d offres, %d requêtes", len(offres), ctx.requetes)
    return offres
