"""Liste du matin (chantier « candidatures de A à Z », 9/11).

Chaque matin, au plus `max_offres` offres jouables, prises parmi les offres présentées des
derniers jours : pas déjà dans l'onglet Candidatures, une seule par employeur, date limite
non dépassée. Chaque offre porte un verdict, ses écarts avec le profil et son mode de
candidature. Maël valide ensuite un lot nommé (« envoie 1, 3 et 4 ») auprès de Claude, qui
prépare et dépose les candidatures.

Verdicts :
* « prête » : rien ne bloque, la candidature peut partir telle quelle ;
* « tentative » : un critère est au-dessus du profil (3 ans demandés, « confirmé », permis) ;
* « à vérifier » : la page n'a pas pu être lue (Adzuna), l'expérience reste inconnue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.normalisation.texte import normaliser

PRETE, TENTATIVE, A_VERIFIER = "prête", "tentative", "à vérifier"
# Écarts qui font d'une offre une tentative : l'exigence dépasse le profil.
_AU_DESSUS = ("an(s) d'expérience demandé", "« confirmé »", "permis b", "le texte demande")
_SIGNAUX_ECARTS = {"permis B exigé": "permis B exigé", "via cabinet": "via cabinet",
                   "description partielle (Adzuna) : expérience à vérifier": "description partielle"}
# Bonus de rang : à note égale, ce qui demande le moins à Maël passe devant.
_BONUS_MODE = {"formulaire": 2, "mail": 1, "compte": 0, "site": 0, "a_verifier": -1, "inconnu": -1}
_BONUS_VERDICT = {PRETE: 0, A_VERIFIER: -2, TENTATIVE: -3}
# Famille de CV proposée (familles de `cv_rapide.py`), d'après le titre ; la première qui
# correspond l'emporte. Par défaut : data_engineer, le poste visé.
_FAMILLES_CV = (
    ("analytics_engineer", r"\banalytics engineer"),
    ("data_scientist", r"\bdata scien|\bmachine learning\b|\bml\b|\bmlops\b"),
    ("dev_ia", r"\bia\b|\bai\b|intelligence artificielle|\bllm\b|\bgenai\b"),
    ("data_manager", r"\bdata manager|\bgouvernance\b|\bdata steward|\bqualite des donnees|\bchef de projet data"
                     r"|\bmdm\b"),
    ("data_analyst", r"\banalyst|\banalyste\b|\bbi\b|business intelligence|\breporting\b|\bpower bi\b"
                     r"|\bstatistici|\bcharge d etudes"),
)


def famille_cv(titre: str) -> str:
    t = normaliser(titre or "")
    return next((nom for nom, motif in _FAMILLES_CV if re.search(motif, t)), "data_engineer")


@dataclass
class Choix:
    offre: dict
    verdict: str
    ecarts: list[str] = field(default_factory=list)

    @property
    def candidature(self) -> dict:
        return self.offre.get("candidature") or {}

    @property
    def mode(self) -> str:
        """Libellé court du mode de candidature, sans adresse mail."""
        c = self.candidature
        m, p = c.get("mode", "inconnu"), c.get("plateforme", "")
        textes = {"formulaire": f"formulaire sans compte{f' ({p})' if p else ''}",
                  "compte": f"compte {p}" if p else "compte requis", "mail": "par mail",
                  "site": f"site de l'employeur{f' ({p})' if p else ''}", "a_verifier": "à vérifier dans Chrome",
                  "inconnu": "mode inconnu"}
        return textes.get(m, m)

    @property
    def lettre(self) -> bool:
        return "lettre demandée" in (self.offre.get("signaux") or [])

    @property
    def famille_cv(self) -> str:
        return famille_cv(self.offre.get("titre") or "")

    @property
    def mode_complet(self) -> str:
        """Mode de candidature, suivi de « lettre demandée » si l'annonce en parle."""
        return self.mode + (" ; lettre demandée" if self.lettre else "")

    @property
    def lien_candidature(self) -> str:
        """Lien direct vers le formulaire ou le mail ; à défaut, la page de l'offre."""
        return self.candidature.get("lien") or self.offre.get("url") or ""

    @property
    def date_limite(self) -> str:
        d = self.candidature.get("date_limite") or ""
        return f"{d[8:10]}/{d[5:7]}" if d else ""


def ecarts(o: dict) -> list[str]:
    """Composantes négatives de la note (« ESN -4 ») et signaux d'écart, sans doublon."""
    sortie = [f"{n} {p:+d}" for n, p in (o.get("composantes") or []) if p < 0]
    deja = {s.rsplit(" ", 1)[0] for s in sortie}
    for s in o.get("signaux") or []:
        libelle = _SIGNAUX_ECARTS.get(s) or (s if s.startswith("le texte demande") else None)
        if libelle and libelle not in deja:
            sortie.append(libelle)
            deja.add(libelle)
    return sortie


def verdict(o: dict, liste_ecarts: list[str]) -> str:
    c = o.get("candidature") or {}
    if c.get("mode") == "a_verifier" or "description partielle" in liste_ecarts:
        return A_VERIFIER
    if any(motif in normaliser(e) or motif in e for e in liste_ecarts for motif in _AU_DESSUS):
        return TENTATIVE
    return PRETE


def _rang(ch: Choix) -> int:
    return (ch.offre.get("note") or 0) + _BONUS_MODE.get(ch.candidature.get("mode", "inconnu"), 0) \
        + _BONUS_VERDICT[ch.verdict]


def choisir(candidats: list[dict], deja_postulees: set[str], aujourdhui: date, maximum: int,
            fils: list[str], exclure_titre=None, exclure_entreprise=None) -> list[Choix]:
    """`candidats` : lignes de la table offres (stockage). `deja_postulees` : liens de l'onglet
    Candidatures. `exclure_titre(titre)` : vrai si le titre tombe sous les règles actuelles (une
    offre notée avant un changement de règle reste en base avec son ancien niveau).
    `exclure_entreprise(nom)` : même principe pour l'employeur (filières réservées). Rend au plus
    `maximum` choix, classés."""
    choix = []
    for o in candidats:
        if str(o.get("fil") or "") not in fils or (o.get("url") or "").strip() in deja_postulees:
            continue
        if exclure_titre is not None and exclure_titre(o.get("titre") or ""):
            continue
        if exclure_entreprise is not None and exclure_entreprise(o.get("entreprise") or ""):
            continue
        limite = (o.get("candidature") or {}).get("date_limite") or ""
        if limite and limite < aujourdhui.isoformat():
            continue
        le = ecarts(o)
        choix.append(Choix(o, verdict(o, le), le))
    choix.sort(key=_rang, reverse=True)
    retenus, employeurs = [], set()
    for ch in choix:
        nom = normaliser(ch.offre.get("entreprise") or "")
        if nom and nom in employeurs:
            continue
        employeurs.add(nom)
        retenus.append(ch)
        if len(retenus) >= maximum:
            break
    return retenus
