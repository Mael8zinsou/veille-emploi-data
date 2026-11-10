"""Liste du matin, 10/11 : lettre demandée et famille de CV, préparées par la veille."""
import pytest

from src import liste_matin as lm
from src.filtres import lettre_demandee
from src.sorties import telegram as tgm
from src.sorties.sheets import ClientSheets
from src.sorties.suivi import Suivi
from src.stockage import signaux_offre
from tests.conftest import offre
from tests.test_liste_matin import JOUR, LUNDI_9H, ligne
from tests.test_suivi import tableur


@pytest.mark.parametrize("texte, attendu", [
    ("Envoyez votre CV et lettre de motivation à rh@ex.fr", True),
    ("Merci de joindre CV + lettre.", True),
    ("Candidature : CV et une lettre", True),
    ("Envoyez votre CV.", False),
    ("", False),
])
def test_lettre_demandee(texte, attendu):
    assert lettre_demandee(texte) is attendu


def test_signal_lettre():
    o = offre()
    assert "lettre demandée" not in signaux_offre(o)
    o.lettre_demandee = True
    assert "lettre demandée" in signaux_offre(o)


@pytest.mark.parametrize("titre, famille", [
    ("Analytics Engineer H/F", "analytics_engineer"),
    ("Data Scientist junior", "data_scientist"),
    ("Ingénieur Machine Learning", "data_scientist"),
    ("Développeur IA générative", "dev_ia"),
    ("Data Manager / gouvernance", "data_manager"),
    ("Chargé d'études statistiques", "data_analyst"),
    ("Consultant BI Power BI", "data_analyst"),
    ("Data Analyst", "data_analyst"),
    ("Data Engineer H/F", "data_engineer"),
    ("Ingénieur informatique", "data_engineer"),
    ("", "data_engineer"),
])
def test_famille_cv(titre, famille):
    assert lm.famille_cv(titre) == famille


def test_mode_complet_et_telegram():
    ch = lm.Choix(ligne(titre="Data Analyst", signaux=["lettre demandée"]), lm.PRETE)
    assert ch.lettre and ch.mode_complet == "compte HelloWork ; lettre demandée"
    assert lm.Choix(ligne(), lm.PRETE).mode_complet == "compte HelloWork"
    (m,) = tgm.messages_liste([ch], JOUR)
    assert "lettre demandée" in m and "CV data_analyst" in m


def test_colonne_cv(tmp_path):
    t = tableur()
    s = Suivi(ClientSheets(t, "id"), mode="reel")
    t.creer("Liste du matin", [["Date", "N°"]])                              # onglet d'avant les colonnes Q et R
    s.ajouter_liste([lm.Choix(ligne(titre="Analytics Engineer", signaux=["lettre demandée"]), lm.PRETE)], LUNDI_9H)
    assert t.cellule("Liste du matin", 1, "R") == "CV"
    assert t.cellule("Liste du matin", 2, "R") == "analytics_engineer"
    assert t.cellule("Liste du matin", 2, "J") == "compte HelloWork ; lettre demandée"
    s.ajouter_liste([lm.Choix(ligne(cle="k2"), lm.PRETE)], LUNDI_9H)       # en-tête déjà là : pas réécrit
    assert t.cellule("Liste du matin", 1, "R") == "CV"
