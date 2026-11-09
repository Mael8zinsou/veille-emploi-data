"""Liste du matin (9/11) : choix, verdicts, écarts, planning, Telegram, onglet, passage."""
from datetime import date, datetime, timedelta

import pytest

from src import liste_matin as lm
from src import main, stockage
from src.filtres import normaliser_offre
from src.models import Candidature, ModeCandidature
from src.sorties import telegram as tgm
from src.sorties.sheets import ClientSheets, ErreurSheets
from src.sorties.suivi import COL_JE_POSTULE, Suivi
from src.sorties.telegram import Telegram
from tests.conftest import offre
from tests.faux_tableur import FauxTableur
from tests.test_planning import plan
from tests.test_suivi import tableur

JOUR = date(2026, 11, 9)
LUNDI_9H = datetime(2026, 11, 9, 8, 0)     # 9h à Paris


def ligne(**kw):
    o = {"cle": "k1", "fil": "emploi", "note": 10, "entreprise": "Doctolib", "titre": "Data Engineer", "lieu": "Paris",
         "contrat": "cdi", "url": "https://ex.fr/1", "composantes": [("priorité 1", 6)], "signaux": [],
         "candidature": {"mode": "compte", "plateforme": "HelloWork", "lien": "", "date_limite": ""}}
    o.update(kw)
    return o


# --------------------------------------------------------------------------- verdicts et écarts

def test_verdict_prete():
    o = ligne(composantes=[("priorité 1", 6), ("ESN", -4)])
    assert lm.ecarts(o) == ["ESN -4"] and lm.verdict(o, lm.ecarts(o)) == lm.PRETE


@pytest.mark.parametrize("o", [
    ligne(composantes=[("3 an(s) d'expérience demandé(s)", -4)]),
    ligne(composantes=[("« confirmé » dans le titre", -4)]),
    ligne(signaux=["permis B exigé"]),
])
def test_verdict_tentative(o):
    assert lm.verdict(o, lm.ecarts(o)) == lm.TENTATIVE


def test_verdict_a_verifier_et_doublons_d_ecarts():
    o = ligne(candidature={"mode": "a_verifier", "plateforme": "Adzuna"},
              composantes=[("seconde main", -2)],
              signaux=["seconde main", "description partielle (Adzuna) : expérience à vérifier"])
    assert lm.ecarts(o) == ["seconde main -2", "description partielle"]
    assert lm.verdict(o, lm.ecarts(o)) == lm.A_VERIFIER


def test_modes_lisibles():
    ch = lm.Choix(ligne(candidature={"mode": "mail", "lien": "mailto:rh@ex.fr", "date_limite": "2026-11-20"}), lm.PRETE)
    assert ch.mode == "par mail" and ch.date_limite == "20/11"
    assert lm.Choix(ligne(candidature=None), lm.PRETE).mode == "mode inconnu"
    assert lm.Choix(ligne(candidature={"mode": "formulaire", "plateforme": "Lever"}), lm.PRETE).mode == \
        "formulaire sans compte (Lever)"
    assert lm.Choix(ligne(candidature={"mode": "site", "plateforme": "x.fr"}), lm.PRETE).mode == "site de l'employeur (x.fr)"


# --------------------------------------------------------------------------- choix

def test_choisir_exclusions_et_plafond():
    candidats = [
        ligne(cle="a", url="https://deja", entreprise="A"),                                    # déjà dans Candidatures
        ligne(cle="b", entreprise="B", candidature={"mode": "mail", "date_limite": "2026-11-01"}),  # date limite passée
        ligne(cle="c", entreprise="C", fil="immersion"),                                     # fil hors liste
        ligne(cle="d", entreprise="Doctolib", note=12, url="https://d1"),
        ligne(cle="e", entreprise="DOCTOLIB", note=11, url="https://d2"),                    # même employeur
        *[ligne(cle=f"z{i}", entreprise=f"Z{i}", note=5, url=f"https://z{i}") for i in range(20)],
    ]
    choix = lm.choisir(candidats, {"https://deja"}, JOUR, 10, ["emploi", "alternance"])
    cles = [c.offre["cle"] for c in choix]
    assert len(choix) == 10 and cles[0] == "d"
    assert not {"a", "b", "c", "e"} & set(cles)


def test_choisir_classe_par_facilite_a_note_egale():
    choix = lm.choisir([ligne(cle="compte", entreprise="X"),
                        ligne(cle="form", entreprise="Y", candidature={"mode": "formulaire"}),
                        ligne(cle="tent", entreprise="W", note=12, composantes=[("3 an(s) d'expérience demandé(s)", -4)])],
                       set(), JOUR, 10, ["emploi"])
    assert [c.offre["cle"] for c in choix] == ["form", "compte", "tent"]


def test_employeur_inconnu_n_ecarte_pas_les_autres():
    choix = lm.choisir([ligne(cle="a", entreprise="", url="1"), ligne(cle="b", entreprise="", url="2")], set(), JOUR, 10,
                       ["emploi"])
    assert len(choix) == 2    # employeurs non indiqués : pas comptés comme un même employeur


# --------------------------------------------------------------------------- planning

def test_liste_due_apres_8h_une_fois_par_jour(config):
    assert not plan(config, datetime(2026, 11, 9, 6, 30)).liste_du_matin            # 7h30 à Paris
    assert plan(config, LUNDI_9H).liste_du_matin
    assert not plan(config, LUNDI_9H, envois={("liste", None): datetime(2026, 11, 9, 7, 10)}).liste_du_matin
    assert plan(config, LUNDI_9H, envois={("liste", None): datetime(2026, 11, 8, 7, 10)}).liste_du_matin


def test_liste_coupee(config):
    envois = config.planning.envois.model_copy(update={"liste_matin": None})
    c = config.model_copy(update={"planning": config.planning.model_copy(update={"envois": envois})})
    assert not plan(c, LUNDI_9H).liste_du_matin


# --------------------------------------------------------------------------- Telegram

def test_message_liste():
    choix = [lm.Choix(ligne(titre="Data <Engineer>"), lm.PRETE, ["ESN -4"]),
             lm.Choix(ligne(candidature={"mode": "mail", "date_limite": "2026-11-20"}), lm.TENTATIVE)]
    (m,) = tgm.messages_liste(choix, JOUR)
    assert "Liste du matin, 9 novembre" in m and "2 offre(s)" in m
    assert "<b>1.</b> Data &lt;Engineer&gt;" in m and "<b>2.</b>" in m
    assert "écarts : ESN -4" in m and "par mail, avant le 20/11" in m and "<b>tentative</b>" in m
    assert "envoie 1, 3 et 4" in m


def test_message_liste_vide_et_decoupe():
    assert "Rien de jouable" in tgm.messages_liste([], JOUR)[0]
    longues = [lm.Choix(ligne(titre="x" * 600, cle=str(i)), lm.PRETE, ["e" * 200]) for i in range(10)]
    messages = tgm.messages_liste(longues, JOUR)
    assert len(messages) > 1 and all(len(m) <= tgm.LIMITE for m in messages)
    assert "(suite)" in messages[1] and "Valide un lot" in messages[-1]


# --------------------------------------------------------------------------- base

def test_candidats_et_marquage(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "v.sqlite")
    recente = normaliser_offre(offre(titre="Data Engineer", candidature=Candidature(ModeCandidature.MAIL)), config)
    ancienne = normaliser_offre(offre(titre="Data Analyst", entreprise="Alan"), config)
    archivee = normaliser_offre(offre(titre="Data Scientist", entreprise="Qonto"), config)
    stockage.enregistrer_offres(base, [ancienne], LUNDI_9H - timedelta(days=5))
    stockage.enregistrer_offres(base, [recente, archivee], LUNDI_9H - timedelta(hours=3))
    for o, niv in ((recente, "resume"), (ancienne, "alerte"), (archivee, "archive")):
        stockage.noter(base, o.cle, 9, [("priorité 1", 6)], niv)
    (c,) = stockage.candidats_liste(base, LUNDI_9H - timedelta(days=3))
    assert c["cle"] == recente.cle and c["candidature"]["mode"] == "mail"
    stockage.marquer_liste(base, [recente.cle], LUNDI_9H)
    assert stockage.candidats_liste(base, LUNDI_9H - timedelta(days=3)) == []


# --------------------------------------------------------------------------- onglet

def test_onglet_liste_et_liens_candidatures():
    t = tableur()
    t.onglets["Candidatures"]["lignes"].setdefault(5, {})[2] = "https://deja.fr/1"
    s = Suivi(ClientSheets(t, "id"), mode="reel")
    assert "https://deja.fr/1" in s.liens_candidatures()
    n = s.ajouter_liste([lm.Choix(ligne(), lm.PRETE, ["ESN -4"])], LUNDI_9H)
    assert n == 1 and "Liste du matin" in t.onglets
    assert t.cellule("Liste du matin", 1, "N") == "Je postule"
    assert t.cellule("Liste du matin", 2, "C") == "prête" and t.cellule("Liste du matin", 2, "J") == "compte HelloWork"
    assert t.cellule("Liste du matin", 2, "L") == "ESN -4" and t.cellule("Liste du matin", 2, "P") == "k1"
    assert COL_JE_POSTULE == 13 and s.ajouter_liste([], LUNDI_9H) == 0
    assert Suivi(ClientSheets(t, "id"), mode="essai").onglet_liste == "Liste du matin (essai)"


# --------------------------------------------------------------------------- passage

def _base_avec_offres(tmp_path, config):
    base = stockage.ouvrir(tmp_path / "v.sqlite")
    offres = [normaliser_offre(offre(entreprise=f"E{i}", url=f"https://ex.fr/{i}"), config) for i in range(3)]
    stockage.enregistrer_offres(base, offres, LUNDI_9H - timedelta(hours=2))
    for o in offres:
        stockage.noter(base, o.cle, 8, [("priorité 1", 6)], "resume")
    return base


def test_envoyer_liste_complet(tmp_path, config):
    base, t = _base_avec_offres(tmp_path, config), tableur()
    t.onglets["Candidatures"]["lignes"].setdefault(5, {})[2] = "https://ex.fr/0"
    tg = Telegram(object(), None, config.telegram.groupe_id, config.telegram.sujets)
    rapport = main.Rapport("", {})
    main.envoyer_liste(base, config, tg, Suivi(ClientSheets(t, "id"), mode="reel"), LUNDI_9H, rapport)
    assert rapport.envois["listes"] == 1 and rapport.suivi["liste_du_matin"] == 2
    assert len(tg.envoyes) == 1 and tg.envoyes[0][0] is None and "2 offre(s)" in tg.envoyes[0][1]
    assert ("liste", None) in stockage.derniers_envois(base)
    rapport2 = main.Rapport("", {})
    main.envoyer_liste(base, config, tg, None, LUNDI_9H, rapport2)          # les offres listées ne reviennent pas
    assert "Rien de jouable" in tg.envoyes[-1][1] or "1 offre(s)" in tg.envoyes[-1][1]


def test_envoyer_liste_resiste_au_tableur(tmp_path, config):
    class EnPanne(FauxTableur):
        def get(self, url, params=None):
            raise ErreurSheets("panne")
    base = _base_avec_offres(tmp_path, config)
    tg = Telegram(object(), None, config.telegram.groupe_id, config.telegram.sujets)
    rapport = main.Rapport("", {})
    s = Suivi(ClientSheets(EnPanne(), "id"), mode="reel")
    main.envoyer_liste(base, config, tg, s, LUNDI_9H, rapport)
    assert rapport.envois["listes"] == 1 and "erreur_liste_lecture" in rapport.suivi and "erreur_liste" in rapport.suivi


def test_liste_non_marquee_si_telegram_echoue(tmp_path, config):
    base = _base_avec_offres(tmp_path, config)

    class Muet(Telegram):
        def envoyer(self, texte, fil=None):
            return False
    rapport = main.Rapport("", {})
    main.envoyer_liste(base, config, Muet(object(), None, 1, {}), None, LUNDI_9H, rapport)
    assert rapport.envois["listes"] == 0 and len(stockage.candidats_liste(base, LUNDI_9H - timedelta(days=3))) == 3


def test_passage_envoie_la_liste(tmp_path, config):
    base = _base_avec_offres(tmp_path, config)
    tg = Telegram(object(), None, config.telegram.groupe_id, config.telegram.sujets)
    r = main.passage(config, base, LUNDI_9H, sources_imposees=[], session=object(), telegram=tg)
    assert r.envois["listes"] == 1
