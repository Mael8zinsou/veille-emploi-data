import pytest

from src import storage
from src.models import Offre


def _offre(**overrides) -> Offre:
    base = dict(
        source="Greenhouse",
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


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "test.sqlite")
    yield
    # nettoyage : variable globale du module (singleton de chemin)
    storage._DB_PATH = None


def test_offre_inconnue_pas_vue(db):
    o = _offre()
    assert storage.is_already_seen(o.cle_unique) is False


def test_mark_seen_puis_is_already_seen(db):
    o = _offre()
    storage.mark_seen(o)
    assert storage.is_already_seen(o.cle_unique) is True


def test_mark_seen_idempotent(db):
    o = _offre()
    storage.mark_seen(o)
    storage.mark_seen(o)  # ne doit pas lever
    assert storage.is_already_seen(o.cle_unique) is True


def test_mark_seen_met_a_jour_score_et_sources(db):
    o = _offre(score=10, sources_list=["Greenhouse"])
    storage.mark_seen(o)

    # Même clé, nouvelles infos.
    o.score = 18
    o.sources_list = ["Greenhouse", "Lever"]
    storage.mark_seen(o)

    # On lit en direct la DB pour vérifier les champs mis à jour.
    with storage._conn() as conn:
        row = conn.execute(
            "SELECT score, sources FROM offres_vues WHERE cle_unique = ?",
            (o.cle_unique,),
        ).fetchone()
    assert row == (18, "Greenhouse,Lever")


def test_mark_notified(db):
    o = _offre()
    storage.mark_seen(o)
    storage.mark_notified(o.cle_unique)
    with storage._conn() as conn:
        row = conn.execute(
            "SELECT notifiee FROM offres_vues WHERE cle_unique = ?",
            (o.cle_unique,),
        ).fetchone()
    assert row[0] == 1


def test_init_db_obligatoire():
    storage._DB_PATH = None
    with pytest.raises(RuntimeError):
        storage.is_already_seen("xxx")
