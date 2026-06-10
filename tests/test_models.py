from src.models import Offre, compute_cle_unique


def _offre(**overrides) -> Offre:
    base = dict(
        source="Adzuna",
        titre="Data Engineer Junior",
        entreprise="Spendesk",
        localisation="Paris",
        contrat="CDI",
        description="...",
        url="https://example.com/1",
        date_publication="2026-06-10",
    )
    base.update(overrides)
    return Offre(**base)


def test_cle_unique_est_deterministe():
    a = compute_cle_unique("Spendesk", "Data Engineer Junior")
    b = compute_cle_unique("Spendesk", "Data Engineer Junior")
    assert a == b


def test_cle_unique_insensible_casse_et_espaces():
    a = compute_cle_unique("Spendesk", "Data Engineer Junior")
    b = compute_cle_unique("  SPENDESK ", "data engineer junior   ")
    assert a == b


def test_cle_unique_insensible_aux_accents():
    a = compute_cle_unique("Société X", "Ingénieur Données")
    b = compute_cle_unique("Societe X", "Ingenieur Donnees")
    assert a == b


def test_cle_unique_diffère_pour_offres_distinctes():
    a = compute_cle_unique("Spendesk", "Data Engineer Junior")
    b = compute_cle_unique("Spendesk", "Analytics Engineer")
    assert a != b


def test_cle_unique_tronque_les_titres_longs_identiques():
    """Deux titres identiques sur leurs 50 premiers caractères → même clé.
    C'est volontaire : on accepte les faux positifs sur les titres très longs."""
    prefix = "Data Engineer Junior — équipe Data Platform — Paris"  # ~50 car. normalisés
    t1 = prefix + " — temps plein"
    t2 = prefix + " — alternance possible"
    a = compute_cle_unique("X", t1)
    b = compute_cle_unique("X", t2)
    assert a == b


def test_offre_remplit_cle_unique_et_sources_list():
    o = _offre()
    assert o.cle_unique != ""
    assert o.sources_list == ["Adzuna"]
    assert o.nb_sources == 1
