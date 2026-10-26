"""Fichier de suivi, sur un faux tableur : onglet Veille, transfert, Route B, verdicts."""
from datetime import datetime

from src import main, stockage
from src.sorties.sheets import ClientSheets, ErreurSheets
from src.sorties.suivi import COL_RETENIR, Suivi
from src.sorties.telegram import Telegram
from tests.conftest import offre
from tests.faux_tableur import FauxTableur

QUAND = datetime(2026, 10, 27, 10, 0)
ENTETES_CANDIDATURES = ["Entreprise", "Poste", "Lien de l'offre", "Source", "Date de candidature", "CV utilisé", "Lettre",
                        "Contact derrière l'offre", "Réponse", "Relancé le", "Relance prévue", "Action à mener", "Statut",
                        "Notes"]


def tableur() -> FauxTableur:
    t = FauxTableur()
    t.creer("Candidatures", [["Candidatures, Route A"], [], [], ENTETES_CANDIDATURES,
                             ["Shift Technology", "Data Scientist", "", "Site carrière", "05/10/2026", "", "", "", "",
                              "", "=WORKDAY(E5,7)", "=IF(A5=\"\",\"\",\"En attente\")", "En cours", ""],
                             ["", "", "", "", "", "", "", "", "", "", "=WORKDAY(E6,7)", "=IF(A6=\"\",\"\",\"x\")"]])
    t.creer("Entreprises", [["Entreprises, triées"], [], [], ["Entreprise", "Catégorie", "Verdict Route B"],
                            ["SOCOTEC", "Employeur final", "Cible prioritaire"],
                            ["Mondial Relay by InPost", "Employeur final", "Écarter : ingénierie hors de France"],
                            ["Doctolib", "Employeur final", "Veille Route A"]])
    return t


def suivi(t, mode="reel"):
    return Suivi(ClientSheets(t, "id"), mode=mode)


def ligne_veille(**kw):
    o = {"cle": "k1", "fil": "emploi", "niveau": "alerte", "note": 14, "entreprise": "Doctolib", "titre": "Data Engineer",
         "lieu": "Paris", "contrat": "cdi", "sources": "france_travail", "raisons": ["priorité 1 +6"], "signaux": [],
         "url": "https://ex.fr/1"}
    o.update(kw)
    return o


def test_verdicts(config):
    v = suivi(tableur()).verdicts()
    assert v["socotec"] == "cible prioritaire" and v["mondial relay by inpost"].startswith("ecarter")


def test_onglet_veille_cree_puis_complete():
    t = tableur()
    s = suivi(t, mode="essai")
    assert s.ajouter_a_veille([ligne_veille()], QUAND) == 1
    assert s.ajouter_a_veille([ligne_veille(cle="k2", titre="Data Analyst")], QUAND) == 1
    assert t.cellule("Veille (essai)", 1, "A") == "Ajoutée le"
    assert t.cellule("Veille (essai)", 2, "F") == "Data Engineer" and t.cellule("Veille (essai)", 3, "F") == "Data Analyst"
    assert t.cellule("Veille (essai)", 2, "M") is False and t.cellule("Veille (essai)", 2, "I") == "France Travail"
    assert any(v["rule"]["condition"]["type"] == "BOOLEAN" for v in t.onglets["Veille (essai)"]["validations"])
    assert "Veille" not in t.onglets                         # le vrai onglet n'est pas créé en essai


def test_transfert_sans_doublon_ni_ecrasement():
    t = tableur()
    s = suivi(t)
    s.ajouter_a_veille([ligne_veille(), ligne_veille(cle="k2", url="https://ex.fr/2", titre="Data Analyst")], QUAND)
    t.onglets["Veille"]["lignes"][1][COL_RETENIR] = True          # Maël coche la première offre
    assert s.transferer_retenues(QUAND)["transferees"] == 1
    # Ligne 5 (Shift) intacte, l'offre arrive en ligne 6, la première libre du bloc.
    assert t.cellule("Candidatures", 5, "A") == "Shift Technology"
    assert t.cellule("Candidatures", 6, "A") == "Doctolib" and t.cellule("Candidatures", 6, "D") == "Veille : France Travail"
    assert t.cellule("Candidatures", 6, "K") == "=WORKDAY(E6,7)"   # formules du bloc intactes
    assert t.cellule("Candidatures", 6, "N").startswith("Ajoutée par la veille le 27/10, note 14")
    assert t.cellule("Veille", 2, "N") == "27/10/2026 10:00"
    assert s.transferer_retenues(QUAND)["transferees"] == 0       # rejouer ne duplique rien


def test_lien_deja_present_marque_seulement():
    t = tableur()
    t.onglets["Candidatures"]["lignes"][4][2] = "https://ex.fr/1"
    s = suivi(t)
    s.ajouter_a_veille([ligne_veille()], QUAND)
    t.onglets["Veille"]["lignes"][1][COL_RETENIR] = True
    assert s.transferer_retenues(QUAND) == {"transferees": 0, "deja_presentes": 1, "bloc_plein": 0}
    assert t.cellule("Veille", 2, "N")


def test_bloc_plein_rien_ecrit():
    t = tableur()
    for i in range(4, 300):
        t.onglets["Candidatures"]["lignes"].setdefault(i, {})[0] = f"E{i}"
    s = suivi(t)
    s.ajouter_a_veille([ligne_veille()], QUAND)
    t.onglets["Veille"]["lignes"][1][COL_RETENIR] = True
    assert s.transferer_retenues(QUAND)["bloc_plein"] == 1
    assert not t.cellule("Veille", 2, "N")                     # sera retenté quand une ligne se libère


def test_pas_de_transfert_en_essai():
    t = tableur()
    s = suivi(t, mode="essai")
    s.ajouter_a_veille([ligne_veille()], QUAND)
    t.onglets["Veille (essai)"]["lignes"][1][COL_RETENIR] = True
    assert s.transferer_retenues(QUAND)["transferees"] == 0
    assert t.cellule("Candidatures", 6, "A") is None


def _rejet(entreprise, motif="seniorite"):
    return {"entreprise": entreprise, "titre": "Senior Data Engineer", "lieu": "Paris", "motif": motif,
            "vu_le": "2026-10-27 09:00:00"}


def test_cibles_route_b():
    t = tableur()
    s = suivi(t)
    v = s.verdicts()
    choisies = s.cibles_route_b([_rejet("Qonto"), _rejet("SOCOTEC Group"), _rejet("Qonto"), _rejet("Alan")], set(), v, 5)
    assert [n for n, _ in choisies] == ["qonto", "alan"]          # SOCOTEC est déjà connue, Qonto une seule fois
    s.ajouter_route_b([lg for _, lg in choisies])
    assert t.cellule("Entreprises", 8, "A") == "Qonto" and t.cellule("Entreprises", 8, "C") == "À vérifier"
    assert t.cellule("Entreprises", 8, "I") == "Veille auto" and "trop senior" in t.cellule("Entreprises", 8, "E")
    assert t.cellule("Entreprises", 5, "A") == "SOCOTEC"          # existant intact
    assert len(s.cibles_route_b([_rejet(f"E{i}") for i in range(10)], set(), v, 3)) == 3


def test_route_b_en_essai_ne_touche_pas_entreprises():
    t = tableur()
    s = suivi(t, mode="essai")
    s.ajouter_route_b([lg for _, lg in s.cibles_route_b([_rejet("Qonto")], set(), s.verdicts(), 5)])
    assert t.cellule("Route B (essai)", 2, "A") == "Qonto" and t.cellule("Entreprises", 8, "A") is None


# --------------------------------------------------------------------------- dans le passage

BONNE = {"titre": "Data Engineer junior", "description": "Python SQL Airflow dbt", "date_publication": "2026-10-27",
         "lieu": "Paris"}


def test_passage_complet_en_essai(tmp_path, config):
    t = tableur()
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    lot = [offre(**BONNE), offre(titre="Data Analyst", entreprise="SOCOTEC Group", lieu="Guyancourt"),
           offre(titre="Senior Data Engineer", entreprise="Qonto"),
           offre(titre="Data Engineer", entreprise="Mondial Relay by InPost")]
    sources = {"france_travail": lambda ctx: list(lot), "adzuna": lambda ctx: [], "hellowork": lambda ctx: []}
    r = main.passage(config, base, QUAND, sources_imposees=["france_travail"], session=object(), sources=sources,
                     telegram=Telegram(None, None, 1, config.telegram.sujets), suivi=suivi(t, "essai"))
    assert r.suivi["verdicts_lus"] == 3 and r.suivi["ajoutees_veille"] >= 2 and r.suivi["cibles_route_b"] == 1
    titres = [t.cellule("Veille (essai)", i, "F") for i in range(2, 6)]
    assert "Data Analyst" in titres                       # SOCOTEC : cible prioritaire, présentée
    assert "Data Engineer" not in titres                  # Mondial Relay : écartée définitivement
    assert t.cellule("Route B (essai)", 2, "A") == "Qonto"
    assert t.cellule("Entreprises", 8, "A") is None and t.cellule("Candidatures", 6, "A") is None
    r = main.passage(config, base, datetime(2026, 10, 27, 11, 0), sources_imposees=["france_travail"], session=object(),
                     sources=sources, suivi=suivi(t, "essai"))
    assert r.suivi["ajoutees_veille"] == 0 and r.suivi.get("cibles_route_b", 0) == 0


def test_panne_du_tableur_isolee(tmp_path, config):
    class EnPanne(FauxTableur):
        def get(self, url, params=None):
            raise ErreurSheets("HTTP 503")
    base = stockage.ouvrir(tmp_path / "b.sqlite")
    sources = {"france_travail": lambda ctx: [offre(**BONNE)], "adzuna": lambda ctx: [], "hellowork": lambda ctx: []}
    r = main.passage(config, base, QUAND, sources_imposees=["france_travail"], session=object(), sources=sources,
                     suivi=suivi(EnPanne()))
    assert r.gardees == 1 and "erreur_verdicts" in r.suivi and "erreur_veille" in r.suivi
    assert stockage.a_ajouter_veille(base)                 # rien de perdu : sera ajoutée au passage suivant
