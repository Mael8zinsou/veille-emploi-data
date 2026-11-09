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
from html.parser import HTMLParser

from src.models import Candidature, Fil, ModeCandidature, Offre
from src.normalisation import metiers
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


# ------------------------------------------------------------------ page de l'offre (9/11)
#
# La page liste ne donne ni description ni expérience. La page de l'offre porte, sous le titre,
# une ligne « Exp. 5 ans min. » (sondage du 9/11 : 4 offres sur 6 demandaient 3 ans ou plus),
# puis la description complète. Candidature : formulaire HelloWork, compte requis.

# « Exp. 5 ans min. », « Exp. 1 an min. », et « Exp. 2 à 5 ans » (Framatome, 9/11) : borne basse.
_EXP = re.compile(r"^Exp\.\s*(\d{1,2})\s*(?:(?:à|a|-)\s*\d{1,2}\s*)?ans?\b", re.IGNORECASE | re.MULTILINE)
_DEBUT = ("Les missions du poste", "Détail du poste")
_FIN = ("Les avantages", "Les étapes de recrutement", "Envoyez votre candidature", " en images\n", "Créer mon alerte",
        "Ces offres pourraient")
_BLOCS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "ul", "ol", "tr"}
_PARASITES = {"Voir plus", "Voir moins", "Lire dans l'app"}
CANDIDATURE = Candidature(ModeCandidature.COMPTE, "HelloWork")


class _Texte(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []
        self._ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self._ignore += 1
        elif tag in _BLOCS:
            self.morceaux.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"):
            self._ignore = max(0, self._ignore - 1)

    def handle_data(self, data):
        if not self._ignore:
            self.morceaux.append(data)


def texte_visible(page: str) -> str:
    p = _Texte()
    p.feed(page or "")
    t = re.sub(r"[ \t\xa0\u202f]+", " ", "".join(p.morceaux))
    return "\n".join(ligne.strip() for ligne in t.split("\n") if ligne.strip() and ligne.strip() not in _PARASITES)


def lire_detail(page: str) -> dict:
    """{"experience": années minimum ou None, "description": texte} depuis la page d'une offre."""
    t = texte_visible(page)
    m = _EXP.search(t)
    debut = min((i for i in (t.find(d) for d in _DEBUT) if i >= 0), default=-1)
    if debut < 0 and m:
        debut = m.end()
    description = ""
    if debut >= 0:
        fin = min((i for i in (t.find(f, debut) for f in _FIN) if i >= 0), default=len(t))
        description = t[debut:fin].strip()
    return {"experience": int(m.group(1)) if m else None, "description": description[:3000]}


def completer(o: Offre, detail: dict) -> None:
    if detail.get("experience") is not None:
        o.experience_annees = int(detail["experience"])
    if detail.get("description"):
        o.description = detail["description"]
    o.candidature = CANDIDATURE


def _a_lire(o: Offre, ctx: Contexte) -> bool:
    famille, _ = metiers.reconnaitre(o.titre, ctx.config.metiers)
    return famille is not None


def completer_toutes(offres: list[Offre], ctx: Contexte) -> int:
    """Page de chaque offre au titre reconnu, lue une fois (mémoire), `max_details` au plus
    par passage. Une offre dont la page n'est pas lue reste gardée : son mode de candidature
    est connu, son expérience le sera au passage suivant. Rend le nombre de pages lues."""
    cfg = ctx.config.sources.hellowork
    lues = 0
    for o in offres:
        if o.id_source in ctx.memoire:
            completer(o, ctx.memoire[o.id_source])
            continue
        o.candidature = CANDIDATURE
        if lues >= cfg.max_details or not _a_lire(o, ctx):
            continue
        r = ctx.get(o.url)
        lues += 1
        if r is None or _refuse(r.status_code, r.text):
            continue
        detail = lire_detail(r.text)
        ctx.memoire[o.id_source] = detail
        completer(o, detail)
        time.sleep(cfg.delai_secondes)
    return lues


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
    # Une même offre revient sous plusieurs recherches : une seule lecture de sa page.
    uniques = {o.id_source: o for o in offres}
    lues = completer_toutes(list(uniques.values()), ctx)
    for o in offres:
        source = uniques[o.id_source]
        if o is not source:
            o.experience_annees, o.description, o.candidature = source.experience_annees, source.description, source.candidature
    logger.info("hellowork : %d offres, %d pages d'offre lues, %d requêtes", len(offres), lues, ctx.requetes)
    return offres
