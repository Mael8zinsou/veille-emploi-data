"""
Tests du module scoring : filtrage profil, dédoublonnage/fusion cross-source, scoring
(mots-clés + saturation). Couvre les fonctions critiques exigées par le brief §5.7.
"""
from src.config import load_config
from src.models import Offre
from src.scoring import (
    dedoublonne_et_fusionne,
    filtre_par_profil,
    score_offre,
    score_toutes,
)

CONFIG = load_config("config/profil.yaml")


def _offre(titre="Data Engineer", entreprise="Acme", localisation="Paris",
           description="", source="Greenhouse", url="https://x"):
    return Offre(
        source=source, titre=titre, entreprise=entreprise, localisation=localisation,
        contrat="CDI", description=description, url=url, date_publication="2026-06-10",
    )


# --------------------------------------------------------------------------
# Filtrage par profil
# --------------------------------------------------------------------------

def test_filtre_garde_mot_cle_et_localisation():
    offres = [_offre(titre="Data Engineer Junior", localisation="Paris")]
    assert len(filtre_par_profil(offres, CONFIG)) == 1


def test_filtre_rejette_sans_mot_cle():
    offres = [_offre(titre="Chef de projet marketing", description="rien")]
    assert filtre_par_profil(offres, CONFIG) == []


def test_filtre_rejette_exclusion_titre():
    offres = [_offre(titre="Senior Data Engineer", localisation="Paris")]
    assert filtre_par_profil(offres, CONFIG) == []


def test_filtre_exclut_alternance_et_apprentissage():
    # On cherche un CDI/CDD : alternance / apprentissage sont hors cible.
    offres = [
        _offre(titre="Alternance Data Engineer", localisation="Lyon"),
        _offre(titre="Data Engineer en apprentissage", localisation="Paris"),
        _offre(titre="Apprenti Data Engineer", localisation="Nantes"),
        _offre(titre="Data Engineer Alternant", localisation="Lille"),
    ]
    assert filtre_par_profil(offres, CONFIG) == []


def test_filtre_rejette_localisation_etrangere():
    offres = [_offre(titre="Data Engineer", localisation="Berlin, Germany")]
    assert filtre_par_profil(offres, CONFIG) == []


def test_filtre_couvre_toute_la_france():
    # Couverture France entière : campagne et villes non listées passent aussi.
    offres = [
        _offre(titre="Data Engineer", localisation=""),
        _offre(titre="Data Engineer", localisation="France"),
        _offre(titre="Data Engineer", localisation="Guéret, Creuse"),       # campagne
        _offre(titre="Data Engineer", localisation="Aurillac"),             # ville non listée
        _offre(titre="Data Engineer", localisation="Remote"),
    ]
    assert len(filtre_par_profil(offres, CONFIG)) == 5


def test_filtre_localisation_insensible_accents():
    offres = [_offre(titre="Data Engineer", localisation="Île-de-France")]
    assert len(filtre_par_profil(offres, CONFIG)) == 1


# --------------------------------------------------------------------------
# Dédoublonnage + fusion
# --------------------------------------------------------------------------

def test_dedoublonne_fusionne_meme_cle():
    a = _offre(source="Greenhouse", description="court")
    b = _offre(source="Adzuna", description="description bien plus longue et détaillée")
    fusion = dedoublonne_et_fusionne([a, b])
    assert len(fusion) == 1
    o = fusion[0]
    assert o.nb_sources == 2
    assert set(o.sources_list) == {"Greenhouse", "Adzuna"}
    # On garde la version la plus détaillée.
    assert o.description == "description bien plus longue et détaillée"


def test_dedoublonne_garde_offres_distinctes():
    a = _offre(entreprise="Acme", titre="Data Engineer")
    b = _offre(entreprise="Globex", titre="Data Engineer")
    fusion = dedoublonne_et_fusionne([a, b])
    assert len(fusion) == 2
    assert all(o.nb_sources == 1 for o in fusion)


def test_dedoublonne_compte_sources_distinctes_seulement():
    # Même source deux fois -> nb_sources reste 1.
    a = _offre(source="Adzuna")
    b = _offre(source="Adzuna")
    fusion = dedoublonne_et_fusionne([a, b])
    assert len(fusion) == 1
    assert fusion[0].nb_sources == 1


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def test_score_bonus_stack_et_junior():
    o = _offre(titre="Data Engineer Junior",
               description="stack python sql airflow dbt snowflake")
    score_offre(o, CONFIG)
    # junior(3) + python(2)+sql(2)+airflow(3)+dbt(3)+snowflake(3) = 16, + exclusif(5) = 21
    assert o.score == 21
    assert "junior" in o.tags
    assert "airflow" in o.tags
    assert "exclusif" in o.tags


def test_score_malus_esn():
    o = _offre(titre="Data Engineer", description="société de conseil et esn ")
    score_offre(o, CONFIG)
    # malus société de conseil (-2) + esn  (-2) + exclusif (+5) = 1
    assert o.score == 1
    assert "⚠ ESN/conseil" in o.tags


def test_score_saturation_source_unique_boost():
    o = _offre(description="data engineer")
    o.nb_sources = 1
    score_offre(o, CONFIG)
    assert "exclusif" in o.tags
    assert o.score >= CONFIG.scoring.bonus_source_unique


def test_score_saturation_omnipresente_penalisee():
    base = _offre(description="data engineer python")
    base.nb_sources = 1
    score_offre(base, CONFIG)

    sature = _offre(description="data engineer python")
    sature.nb_sources = 5
    score_offre(sature, CONFIG)

    # 5 sources : malus -3 * (5-1) = -12, vs +5 d'exclusivité : nettement plus bas.
    assert sature.score < base.score
    assert "exclusif" not in sature.tags


def test_score_deux_ou_trois_sources_neutre():
    o = _offre(description="data engineer")
    o.nb_sources = 2
    score_offre(o, CONFIG)
    o3 = _offre(description="data engineer")
    o3.nb_sources = 3
    score_offre(o3, CONFIG)
    # Ni boost exclusif ni malus saturation : même score, sans tag exclusif.
    assert o.score == o3.score
    assert "exclusif" not in o.tags


def test_score_toutes_trie_decroissant():
    faible = _offre(titre="Data Engineer", description="data engineer")
    fort = _offre(entreprise="Globex", titre="Data Engineer Junior",
                  description="python sql airflow dbt snowflake mlops")
    resultat = score_toutes([faible, fort], CONFIG)
    assert resultat[0].score >= resultat[1].score
    assert resultat[0] is fort
