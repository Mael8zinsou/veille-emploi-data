"""
Filtrage, dédoublonnage cross-source (avec fusion) et scoring (avec saturation).

Reprend la logique de scoring de veille_emploi.py V2, enrichie de :
- la détection de saturation (une offre vue sur N sources est boostée si exclusive,
  déclassée si présente partout — signe qu'elle est déjà bombardée de candidatures) ;
- la fusion des doublons cross-source en une seule Offre cumulant ses sources.

Toutes les fonctions prennent `config` (SimpleNamespace issu de load_config).
Les sous-sections de scoring (bonus_stack, malus…) sont des SimpleNamespace ;
on les relit en dict via vars() car certaines clés contiennent des caractères
spéciaux ("ci/cd", "esn ", "première expérience").
"""
import logging

from src.models import Offre, _normalize

logger = logging.getLogger(__name__)


def _as_dict(ns) -> dict:
    """SimpleNamespace -> dict (les clés spéciales du YAML sont préservées)."""
    return vars(ns) if ns is not None else {}


# ---------------------------------------------------------------------------
# 1. Filtrage par profil
# ---------------------------------------------------------------------------

def filtre_par_profil(offres: list[Offre], config) -> list[Offre]:
    """
    Garde une offre si :
      - au moins un mot-clé must-match apparaît dans titre+description, ET
      - aucune exclusion de titre n'apparaît dans le titre (senior, lead,
        alternance, apprentissage…), ET
      - la localisation n'est pas un lieu étranger exclu (cf. exclusions_localisation).
    Couverture géographique par défaut : toute la France + Belgique + remote.
    """
    mots_cles = [m.lower() for m in config.mots_cles_must_match]
    exclusions = [e.lower() for e in config.exclusions_titre]
    # Couverture France entière : on n'a PAS de liste blanche de lieux. On garde
    # par défaut, et on n'écarte que les localisations clairement à l'étranger
    # listées dans exclusions_localisation. Ainsi la campagne et les TPE/PME de
    # province passent (elles n'ont aucune raison d'être énumérées).
    exclusions_loc = [_normalize(l) for l in getattr(config, "exclusions_localisation", [])]

    gardees = []
    for o in offres:
        titre_l = o.titre.lower()
        texte = f"{titre_l} {o.description.lower()}"

        if not any(kw in texte for kw in mots_cles):
            continue
        if any(excl in titre_l for excl in exclusions):
            continue

        loc_l = _normalize(o.localisation)
        # Écarte uniquement si la localisation mentionne un lieu étranger exclu.
        if loc_l and any(ex in loc_l for ex in exclusions_loc):
            continue

        gardees.append(o)
    return gardees


# ---------------------------------------------------------------------------
# 2. Dédoublonnage cross-source avec fusion
# ---------------------------------------------------------------------------

def dedoublonne_et_fusionne(offres: list[Offre]) -> list[Offre]:
    """
    Fusionne les offres partageant la même cle_unique.
    On conserve celle qui a le plus de détails (description la plus longue) et on
    cumule nb_sources / sources_list sur l'ensemble des sources distinctes vues.
    """
    par_cle: dict[str, Offre] = {}
    sources_par_cle: dict[str, list[str]] = {}

    for o in offres:
        cle = o.cle_unique
        sources_par_cle.setdefault(cle, [])
        for src in o.sources_list or [o.source]:
            if src not in sources_par_cle[cle]:
                sources_par_cle[cle].append(src)

        gardee = par_cle.get(cle)
        if gardee is None or len(o.description) > len(gardee.description):
            par_cle[cle] = o

    fusionnees = []
    for cle, offre in par_cle.items():
        sources = sources_par_cle[cle]
        offre.sources_list = sources
        offre.nb_sources = len(sources)
        fusionnees.append(offre)
    return fusionnees


# ---------------------------------------------------------------------------
# 3. Scoring (mots-clés + saturation)
# ---------------------------------------------------------------------------

def _score_signaux(texte: str, table: dict) -> tuple[int, list[str]]:
    """Additionne les poids des signaux présents dans le texte. Retourne (score, tags)."""
    score = 0
    tags = []
    for signal, poids in table.items():
        if signal.strip() and signal.lower() in texte:
            score += int(poids)
            tags.append(signal.strip())
    return score, tags


def score_offre(offre: Offre, config) -> Offre:
    """Calcule offre.score et offre.tags (mots-clés + saturation). Mutation en place."""
    sc = config.scoring
    texte = f"{offre.titre} {offre.description}".lower()

    score = 0
    tags: list[str] = []

    s_junior, t_junior = _score_signaux(texte, _as_dict(sc.bonus_signaux_junior))
    s_stack, t_stack = _score_signaux(texte, _as_dict(sc.bonus_stack))
    s_malus, t_malus = _score_signaux(texte, _as_dict(sc.malus))
    score += s_junior + s_stack + s_malus
    tags.extend(t_junior + t_stack)
    if t_malus:
        tags.append("⚠ ESN/conseil")

    # Saturation : exclusive = pépite (boost), omniprésente = déjà bombardée (malus).
    n = offre.nb_sources
    if n == 1:
        score += int(sc.bonus_source_unique)
        tags.append("exclusif")
    elif n >= 4:
        score += int(sc.malus_par_source_supplementaire) * (n - 1)

    offre.score = score
    offre.tags = list(dict.fromkeys(tags))  # dédoublonne en gardant l'ordre
    return offre


def score_toutes(offres: list[Offre], config) -> list[Offre]:
    """Score toutes les offres et les trie par score décroissant."""
    for o in offres:
        score_offre(o, config)
    offres.sort(key=lambda o: o.score, reverse=True)
    return offres
