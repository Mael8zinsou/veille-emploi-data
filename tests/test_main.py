"""Passage complet, sources simulées : idempotence, isolation des pannes, rapport."""
import sqlite3
from datetime import datetime

from src import main, stockage
from src.sources import SourceIndisponible
from tests.conftest import offre

MAINTENANT = datetime(2026, 10, 27, 9, 0)   # mardi 10h à Paris


def _sources(**fetchs):
    return fetchs


def test_passage_puis_rejeu(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    lot = [offre(), offre(titre="Senior Data Engineer"), offre(titre="Alternance Data Analyst", contrat_brut="")]
    sources = _sources(france_travail=lambda ctx: list(lot), adzuna=lambda ctx: [offre(source="adzuna")],
                       hellowork=lambda ctx: [])
    r1 = main.passage(config, base, MAINTENANT, session=object(), sources=sources)
    assert r1.brutes == 4 and r1.gardees == 2 and r1.nouvelles == 2
    assert r1.rejets_par_motif == {"seniorite": 1}
    assert r1.par_fil == {"emploi": 1, "alternance": 1}

    # Une heure plus tard, mêmes offres : rien de nouveau.
    lot = [offre(), offre(titre="Senior Data Engineer"), offre(titre="Alternance Data Analyst", contrat_brut="")]
    r2 = main.passage(config, base, datetime(2026, 10, 27, 10, 0), sources_imposees=["france_travail"],
                      session=object(), sources=sources)
    assert r2.gardees == 2 and r2.nouvelles == 0
    with sqlite3.connect(base.chemin) as c:
        assert c.execute("SELECT COUNT(*) FROM offres").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM rejets").fetchone()[0] == 1


def test_panne_isolee_et_enregistree(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")

    def en_panne(ctx):
        raise SourceIndisponible("france_travail : jeton refusé")

    def en_erreur(ctx):
        raise KeyError("champ")
    sources = _sources(france_travail=en_panne, adzuna=en_erreur, hellowork=lambda ctx: [offre()])
    r = main.passage(config, base, MAINTENANT, session=object(), sources=sources)
    assert r.sources["france_travail"]["etat"] == "indisponible"
    assert r.sources["adzuna"]["etat"] == "erreur"
    assert r.sources["hellowork"]["etat"] == "ok" and r.gardees == 1
    assert stockage.echecs_consecutifs(base, "france_travail") == 1
    assert set(stockage.dernier_succes(base)) == {"hellowork"}


def test_planning_respecte(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    appels = []
    sources = _sources(france_travail=lambda ctx: appels.append("ft") or [], adzuna=lambda ctx: appels.append("az") or [],
                       hellowork=lambda ctx: appels.append("hw") or [])
    main.passage(config, base, MAINTENANT, session=object(), sources=sources)
    main.passage(config, base, datetime(2026, 10, 27, 9, 20), session=object(), sources=sources)
    assert appels == ["ft", "az", "hw"]       # 20 minutes après : rien n'est dû
    r = main.passage(config, base, datetime(2026, 10, 27, 23, 0), session=object(), sources=sources)
    assert r.plan["hors_plage"] and appels == ["ft", "az", "hw"]


def test_resume_du_rapport(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    r = main.passage(config, base, MAINTENANT, session=object(),
                     sources=_sources(france_travail=lambda ctx: [offre()], adzuna=lambda ctx: [], hellowork=lambda ctx: []))
    texte = "\n".join(r.resume())
    assert "france_travail : ok, 1 offres" in texte and "nouvelles 1" in texte
