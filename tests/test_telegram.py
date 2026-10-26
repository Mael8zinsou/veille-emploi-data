"""Messages Telegram et envois du passage (alertes, résumés, bilan, pannes)."""
from datetime import date, datetime

from src import main, stockage
from src.sorties import telegram as tgm
from src.sorties.telegram import Telegram
from src.sources import SourceIndisponible
from tests.conftest import Reponse, offre

LIGNE = {"titre": "Data <Engineer> & co", "entreprise": "Doctolib", "lieu": "Paris", "contrat": "cdi", "note": 14,
         "raisons": ["priorité 1 +6", "compétences (python) +1"], "signaux": ["republiée"],
         "url": "https://exemple.fr/o?a=1&b=2"}


def test_alerte_echappee():
    m = tgm.message_alerte(LIGNE)
    assert "Data &lt;Engineer&gt; &amp; co" in m and "<b>" in m
    assert 'href="https://exemple.fr/o?a=1&amp;b=2"' in m
    assert "priorité 1 +6" in m and "republiée" in m


def test_resume_decoupe_et_plafonne():
    offres = [{**LIGNE, "titre": f"Data Engineer {'x' * 150} {i}", "note": i} for i in range(80)]
    messages = tgm.messages_resume("emploi", offres, date(2026, 10, 26), maximum=60)
    assert len(messages) > 1 and all(len(m) <= tgm.LIMITE for m in messages)
    assert "1. <b>79</b>" in messages[0]                # classé par note décroissante
    assert "et 20 autre(s)" in messages[-1]
    assert "Aucune nouvelle offre" in tgm.messages_resume("alternance", [], date(2026, 10, 26), 30)[0]


class FauxTelegram:
    def __init__(self, statut=200, ok=True):
        self.statut, self.ok, self.corps = statut, ok, []

    def post(self, url, json=None, timeout=None):
        self.corps.append(json)
        return Reponse(self.statut, {"ok": self.ok}, text="x")


def test_envoi_dans_le_bon_sujet(config):
    faux = FauxTelegram()
    tg = Telegram(faux, "jeton", config.telegram.groupe_id, config.telegram.sujets, mode="telegram")
    assert tg.envoyer("a", "alternance") and tg.envoyer("b")
    assert faux.corps[0]["message_thread_id"] == config.telegram.sujets["alternance"]
    assert "message_thread_id" not in faux.corps[1] and faux.corps[1]["parse_mode"] == "HTML"


def test_echecs_d_envoi(config):
    assert not Telegram(FauxTelegram(400, False), "j", 1, {}, mode="telegram").envoyer("a")
    assert not Telegram(FauxTelegram(), None, 1, {}, mode="telegram").envoyer("a")
    sim = Telegram(None, None, 1, {}, mode="simulation")
    assert sim.envoyer("a", "emploi") and sim.envoyes == [("emploi", "a")]


# --------------------------------------------------------------------------- envois du passage

BONNE = {"titre": "Data Engineer junior", "description": "Python SQL Airflow dbt", "date_publication": "2026-10-27",
         "lieu": "Paris"}
MARDI_10H = datetime(2026, 10, 27, 9, 0)
MARDI_18H30 = datetime(2026, 10, 27, 17, 30)


def _passage(config, base, quand, tg, lot):
    sources = {"france_travail": lambda ctx: list(lot), "adzuna": lambda ctx: [], "hellowork": lambda ctx: []}
    return main.passage(config, base, quand, sources_imposees=["france_travail"], session=object(), sources=sources,
                        telegram=tg)


def test_alerte_envoyee_une_fois(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    tg = Telegram(FauxTelegram(), "j", 1, config.telegram.sujets, mode="telegram")
    r = _passage(config, base, MARDI_10H, tg, [offre(**BONNE)])
    assert r.envois["alertes"] == 1 and "Data Engineer junior" in tg.envoyes[0][1] and tg.envoyes[0][0] == "emploi"
    r = _passage(config, base, datetime(2026, 10, 27, 10, 0), tg, [offre(**BONNE)])
    assert r.envois["alertes"] == 0


def test_alerte_rejouee_apres_echec(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    en_panne = Telegram(FauxTelegram(500, False), "j", 1, config.telegram.sujets, mode="telegram")
    r = _passage(config, base, MARDI_10H, en_panne, [offre(**BONNE)])
    assert r.envois == {**r.envois, "alertes": 0, "alertes_en_attente": 1}
    retabli = Telegram(FauxTelegram(), "j", 1, config.telegram.sujets, mode="telegram")
    r = _passage(config, base, datetime(2026, 10, 27, 10, 0), retabli, [])
    assert r.envois["alertes"] == 1


def test_resume_du_soir_une_fois_par_jour(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    tg = Telegram(None, None, 1, config.telegram.sujets, mode="simulation")
    moyenne = offre(titre="Data Analyst", entreprise="Doctolib", lieu="Paris", date_publication="2026-10-25")
    alternance = offre(titre="Alternance Data Analyst", entreprise="Doctolib", date_publication="2026-10-27")
    _passage(config, base, MARDI_10H, tg, [moyenne, alternance])
    r = _passage(config, base, MARDI_18H30, tg, [])
    assert r.envois["resumes"] == 2                       # emploi et alternance
    textes = [t for _, t in tg.envoyes]
    assert any("Data Analyst" in t and "Emploi" in t for t in textes)
    assert any("Alternance" in t for t in textes)
    r = _passage(config, base, datetime(2026, 10, 27, 19, 30), tg, [])
    assert r.envois["resumes"] == 0
    assert stockage.a_resumer(base, "emploi") == []


def test_bilan_du_lundi(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    tg = Telegram(None, None, 1, config.telegram.sujets, mode="simulation")
    r = _passage(config, base, datetime(2026, 11, 2, 9, 0), tg, [offre(**BONNE)])    # lundi 10h
    assert r.envois["bilans"] == 1 and any("Bilan de la semaine" in t for _, t in tg.envoyes)
    r = _passage(config, base, datetime(2026, 11, 2, 10, 0), tg, [])
    assert r.envois["bilans"] == 0


def test_avertissement_de_panne_au_troisieme_echec(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    tg = Telegram(None, None, 1, config.telegram.sujets, mode="simulation")

    def panne(ctx):
        raise SourceIndisponible("france_travail : jeton refusé")
    sources = {"france_travail": panne, "adzuna": lambda ctx: [], "hellowork": lambda ctx: []}
    pannes = []
    for h in range(9, 14):
        r = main.passage(config, base, datetime(2026, 10, 27, h, 0), sources_imposees=["france_travail"],
                         session=object(), sources=sources, telegram=tg)
        pannes.append(r.envois["pannes"])
    assert pannes == [0, 0, 1, 0, 0]
    assert any("Source en panne : france_travail" in t for _, t in tg.envoyes)


def test_rien_la_nuit(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    tg = Telegram(None, None, 1, config.telegram.sujets, mode="simulation")
    _passage(config, base, datetime(2026, 10, 27, 22, 30), tg, [offre(**BONNE)])
    assert tg.envoyes == []
