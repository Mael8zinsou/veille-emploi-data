"""Liste du matin vérifiée (9/11) : offres fermées, années lues dans le texte, lien direct."""
from datetime import date, datetime, timedelta

import pytest
import requests

from src import liste_matin as lm
from src import main, stockage
from src.disponibilite import Verificateur
from src.filtres import motif_de_rejet, normaliser_offre
from src.sorties.sheets import ClientSheets
from src.sorties.suivi import Suivi
from src.sorties.telegram import Telegram
from src.sources import Contexte
from tests.conftest import FausseSession, Reponse, offre
from tests.test_liste_matin import LUNDI_9H, ligne
from tests.test_suivi import tableur

FT = "https://candidat.francetravail.fr/offres/recherche/detail/{}"


@pytest.fixture
def identifiants(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "x")
    monkeypatch.setenv("FT_CLIENT_SECRET", "y")


def verificateur(config, statuts: dict[str, object]):
    """statuts : fragment d'URL -> code HTTP ou exception."""
    def repondre(m, u, k):
        if m == "POST":
            return Reponse(200, {"access_token": "jeton"})
        for frag, statut in statuts.items():
            if frag in u:
                return statut if isinstance(statut, Exception) else Reponse(statut, {}, text="x")
        return Reponse(200, {}, text="x")
    return Verificateur(Contexte(config=config, session=FausseSession(repondre), maintenant_utc=LUNDI_9H))


def test_france_travail_par_l_api(config, identifiants):
    v = verificateur(config, {"offres/AAA": 200, "offres/BBB": 404, "offres/CCC": 204, "offres/DDD": 500})
    assert v.en_ligne(FT.format("AAA")) is True
    assert v.en_ligne(FT.format("BBB")) is False and v.en_ligne(FT.format("CCC")) is False
    assert v.en_ligne(FT.format("DDD")) is None
    posts = [a for a in v.ctx.session.appels if a[0] == "POST"]
    assert len(posts) == 1                                           # un seul jeton par passage
    get = next(a for a in v.ctx.session.appels if "offres/AAA" in a[1])
    assert get[2]["headers"]["Authorization"] == "Bearer jeton" and get[2]["allow_redirects"] is False


def test_france_travail_sans_acces(config, monkeypatch):
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    v = verificateur(config, {})
    assert v.en_ligne(FT.format("AAA")) is None and v.en_ligne(FT.format("BBB")) is None


def test_pages_et_sources_non_verifiables(config):
    v = verificateur(config, {"emplois/1.html": 410, "emplois/2.html": 200, "offre-emploi/X": 404,
                              "emplois/3.html": requests.ConnectionError()})
    assert v.en_ligne("https://www.hellowork.com/fr-fr/emplois/1.html") is False
    assert v.en_ligne("https://www.hellowork.com/fr-fr/emplois/2.html") is True
    assert v.en_ligne("https://www.hellowork.com/fr-fr/emplois/3.html") is None
    assert v.en_ligne("https://choisirleservicepublic.gouv.fr/offre-emploi/X/") is False
    assert v.en_ligne("https://www.adzuna.fr/details/1") is None and v.en_ligne("") is None


# --------------------------------------------------------------------------- années lues dans le texte

def test_annees_du_texte_au_dessus_du_champ_structure(config):
    o = normaliser_offre(offre(experience_annees=0, debutant_accepte=True,
                               description="Vous avez une expérience de plus de 8 ans en environnement data."), config)
    assert o.annees_requises == 0 and o.annees_texte == 8
    assert motif_de_rejet(o, config, date(2026, 10, 26)) is None            # signal, pas rejet
    assert "le texte demande 8 ans" in stockage.signaux_offre(o)


@pytest.mark.parametrize("kw", [
    {"experience_annees": 2, "description": "2 ans d'expérience."},          # pas au-dessus
    {"experience_annees": 0, "description": "Une première expérience de 1 an."},  # sous 3 ans
    {"experience_annees": None, "description": "5 ans d'expérience."},       # pas de champ structuré
])
def test_pas_de_signal(config, kw):
    assert normaliser_offre(offre(**kw), config).annees_texte is None


def test_signal_texte_rend_tentative():
    o = ligne(signaux=["le texte demande 8 ans"])
    assert lm.ecarts(o) == ["le texte demande 8 ans"] and lm.verdict(o, lm.ecarts(o)) == lm.TENTATIVE


# --------------------------------------------------------------------------- liste vérifiée

def _base(tmp_path, config, n=4):
    base = stockage.ouvrir(tmp_path / "v.sqlite")
    offres = [normaliser_offre(offre(entreprise=f"E{i}", url=FT.format(f"ID{i}")), config) for i in range(n)]
    stockage.enregistrer_offres(base, offres, LUNDI_9H - timedelta(hours=2))
    for i, o in enumerate(offres):
        stockage.noter(base, o.cle, 20 - i, [("priorité 1", 6)], "resume")
    return base, offres


def test_offres_fermees_archivees_et_remplacees(tmp_path, config):
    base, _ = _base(tmp_path, config)
    envois = config.planning.envois.model_copy(
        update={"liste_matin": config.planning.envois.liste_matin.model_copy(update={"max_offres": 2})})
    c = config.model_copy(update={"planning": config.planning.model_copy(update={"envois": envois})})
    tg = Telegram(object(), None, c.telegram.groupe_id, c.telegram.sujets)
    rapport = main.Rapport("", {})
    fermees = {FT.format("ID0"), FT.format("ID2")}
    main.envoyer_liste(base, c, tg, None, LUNDI_9H, rapport, en_ligne=lambda u: False if u in fermees else None)
    assert rapport.suivi["liste_fermees"] == 2 and rapport.envois["listes"] == 1
    assert "2 offre(s)" in tg.envoyes[0][1] and "E0" not in tg.envoyes[0][1] and "E2" not in tg.envoyes[0][1]
    assert "E1" in tg.envoyes[0][1] and "E3" in tg.envoyes[0][1]             # remplacées par les suivantes
    assert stockage.candidats_liste(base, LUNDI_9H - timedelta(days=3)) == []  # fermées archivées, autres listées


def test_colonne_postuler_ici(tmp_path):
    t = tableur()
    s = Suivi(ClientSheets(t, "id"), mode="reel")
    t.creer("Liste du matin", [["Date", "N°"]])                              # onglet d'avant la colonne Q
    ch = lm.Choix(ligne(candidature={"mode": "formulaire", "plateforme": "Beetween", "lien": "https://app.beetween.com/x"}),
                  lm.PRETE)
    s.ajouter_liste([ch, lm.Choix(ligne(cle="k2", candidature=None, url="https://offre/2"), lm.PRETE)], LUNDI_9H)
    assert t.cellule("Liste du matin", 1, "Q") == "Postuler ici"
    assert t.cellule("Liste du matin", 2, "Q") == "https://app.beetween.com/x"
    assert t.cellule("Liste du matin", 3, "Q") == "https://offre/2"
    s.ajouter_liste([ch], LUNDI_9H)                                          # en-tête déjà là : pas réécrit
    assert t.cellule("Liste du matin", 1, "Q") == "Postuler ici"


def test_passage_transmet_la_verification(tmp_path, config):
    base, _ = _base(tmp_path, config, 2)
    tg = Telegram(object(), None, config.telegram.groupe_id, config.telegram.sujets)
    vus = []
    r = main.passage(config, base, LUNDI_9H, sources_imposees=[], session=object(), telegram=tg,
                     en_ligne=lambda u: vus.append(u) or True)
    assert r.envois["listes"] == 1 and len(vus) == 2 and r.suivi["liste_fermees"] == 0


def test_maintenant():
    assert isinstance(LUNDI_9H, datetime)
