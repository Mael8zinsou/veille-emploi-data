"""
Modèle de données du pipeline.
Une seule dataclass Offre, partagée par toutes les sources.
"""
import hashlib
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Offre:
    source: str
    titre: str
    entreprise: str
    localisation: str
    contrat: str
    description: str
    url: str
    date_publication: str  # ISO YYYY-MM-DD

    # Calculés en aval (post-fetch).
    cle_unique: str = ""
    score: int = 0
    tags: list[str] = field(default_factory=list)
    nb_sources: int = 1
    sources_list: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.sources_list:
            self.sources_list = [self.source]
        if not self.cle_unique:
            self.cle_unique = compute_cle_unique(self.entreprise, self.titre)


def _strip_accents(text: str) -> str:
    """Retire les accents (NFD + filtrage des marques diacritiques)."""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _normalize(text: str) -> str:
    return _strip_accents(text or "").lower().strip()


def compute_cle_unique(entreprise: str, titre: str) -> str:
    """
    Identifiant déterministe et insensible aux variations mineures.
    - entreprise : normalisée complète
    - titre : normalisé, première moitié (50 caractères max)
    - hash SHA256, 16 premiers caractères
    """
    ent = _normalize(entreprise)
    tit = _normalize(titre)[:50]
    payload = f"{ent}|{tit}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
