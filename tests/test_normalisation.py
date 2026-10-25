import pytest

from src.models import Contrat, Fil, TypeEmployeur
from src.normalisation import contrats, employeurs, experience, lieux, metiers
from src.normalisation.texte import contient, normaliser, retirer

# --------------------------------------------------------------------------- texte


def test_normaliser():
    assert normaliser("Ingénieur·e Data (H/F) – CDI") == "ingenieur e data h f cdi"
    assert normaliser(None) == ""


def test_frontieres_de_mots():
    assert contient("ingenieur ia h f", "ia")
    assert not contient("chef de projet media", "ia")
    assert not contient("developpeur html", "ml")
    assert contient("data engineer", "data engineer")


def test_retirer():
    assert retirer("data manager junior", ["data manager"]) == "junior"


# --------------------------------------------------------------------------- métiers

@pytest.mark.parametrize("titre, famille", [
    ("Data Engineer H/F", "data_engineering"),
    ("Ingénieur Données (F/H)", "data_engineering"),
    ("Data Scientist & ML Engineer", "data_science"),
    ("AI Engineer (LLM / RAG) F/H", "ia_ml"),
    ("Ingénieur IA générative", "ia_ml"),
    ("Coordinateur IA", "ia_ml"),
    ("Analytics Engineer", "analytics_engineering"),
    ("Data Analyst junior", "analyse"),
    ("Chargé d'études statistiques", "analyse"),
    ("Développeur BI Power BI", "bi"),
    ("Data Steward", "gouvernance"),
    ("Chef de projet data", "satellites"),
])
def test_familles(config, titre, famille):
    f, _ = metiers.reconnaitre(titre, config.metiers)
    assert f is not None and f.nom == famille


def test_priorite_la_plus_haute_l_emporte(config):
    # « data analyst » (2) et « data engineer » (1) : la priorité 1 gagne.
    f, _ = metiers.reconnaitre("Data Analyst / Data Engineer", config.metiers)
    assert f.nom == "data_engineering" and f.priorite == 1


@pytest.mark.parametrize("titre", ["Chef de projet média", "Développeur HTML/CSS", "Comptable", "Business Developer"])
def test_hors_cible(config, titre):
    assert metiers.reconnaitre(titre, config.metiers)[0] is None


def test_code_rome_en_secours(config):
    f, motif = metiers.reconnaitre("Ingénieur en analyse de simulations", config.metiers, code_rome="M1811")
    assert f.nom == "data_engineering" and motif == "rome M1811"


# --------------------------------------------------------------------------- contrats

@pytest.mark.parametrize("brut, attendu", [
    ("CDI", Contrat.CDI), ("CDD CDD - 12 Mois", Contrat.CDD), ("MIS Intérim - 3 Mois", Contrat.INTERIM),
    ("Contrat apprentissage | CDD CDD - 12 Mois", Contrat.ALTERNANCE),
    ("Cont. professionnalisation | CDD", Contrat.ALTERNANCE),
    ("LIB Profession libérale", Contrat.FREELANCE), ("permanent", Contrat.CDI), ("contract", Contrat.CDD),
    ("Alternance", Contrat.ALTERNANCE), ("Stage", Contrat.STAGE), ("SAI Saisonnier", Contrat.AUTRE),
    ("", Contrat.INCONNU), ("Temps plein", Contrat.INCONNU),
])
def test_contrat_declare(brut, attendu):
    assert contrats.contrat_declare(brut) == attendu


@pytest.mark.parametrize("brut, mois", [("CDD - 12 Mois", 12), ("Intérim - 15 Jour(s)", 0), ("2 ans", 24), ("CDI", None)])
def test_duree(brut, mois):
    assert contrats.duree_en_mois(brut) == mois


def test_le_titre_l_emporte(config):
    f = config.filtres
    assert contrats.determiner("Alternance - Data Analyst", "CDD", f) == Contrat.ALTERNANCE
    assert contrats.determiner("Stage de fin d'études / Alternance Data", "", f) == Contrat.ALTERNANCE
    assert contrats.determiner("Stage Data Science", "CDI", f) == Contrat.STAGE
    assert contrats.determiner("Data Engineer Freelance", "CDI", f) == Contrat.FREELANCE
    # Un « CDI » dans le titre ne transforme pas une alternance déclarée en emploi.
    assert contrats.determiner("Data Analyst en CDI", "Contrat apprentissage", f) == Contrat.ALTERNANCE


def test_fil_demande_en_dernier_recours(config):
    assert contrats.determiner("Data Analyst", "", config.filtres, Fil.ALTERNANCE) == Contrat.ALTERNANCE
    assert contrats.determiner("Data Analyst", "", config.filtres, Fil.EMPLOI) == Contrat.INCONNU


def test_fils():
    assert contrats.fil_du_contrat(Contrat.CDI) == Fil.EMPLOI
    assert contrats.fil_du_contrat(Contrat.INCONNU) == Fil.EMPLOI
    assert contrats.fil_du_contrat(Contrat.ALTERNANCE) == Fil.ALTERNANCE
    assert contrats.fil_du_contrat(Contrat.STAGE) is None
    assert contrats.fil_du_contrat(Contrat.FREELANCE) is None


# --------------------------------------------------------------------------- employeurs

@pytest.mark.parametrize("nom, attendu", [
    ("Collective.work", TypeEmployeur.PLATEFORME),
    ("Collective", TypeEmployeur.PLATEFORME),
    ("cadremploi", TypeEmployeur.INTERMEDIAIRE),
    ("Handicap Job", TypeEmployeur.INTERMEDIAIRE),
    ("LHH Recruitment Solutions", TypeEmployeur.INTERMEDIAIRE),
    ("Kaischool", TypeEmployeur.ECOLE),
    ("Studi CFA", TypeEmployeur.ECOLE),
    ("ALTEN", TypeEmployeur.ESN),
    ("T-T Consulting", TypeEmployeur.ESN),
    ("OCI Informatique", TypeEmployeur.ESN),
    ("Conseil Départemental du Nord", TypeEmployeur.FINAL),
    ("Doctolib", TypeEmployeur.FINAL),
    ("", TypeEmployeur.INCONNU),
    ("—", TypeEmployeur.INCONNU),
])
def test_employeurs(config, nom, attendu):
    assert employeurs.classer(nom, config.filtres.employeurs) == attendu


def test_ecole_par_signal_de_la_source(config):
    assert employeurs.classer("HOLIS", config.filtres.employeurs, delegue_par_ecole=True) == TypeEmployeur.ECOLE


# --------------------------------------------------------------------------- lieux

def test_lieux(config):
    lx = config.filtres.lieux
    a = lieux.analyser("Bruxelles, Belgique", "Data Engineer", lx)
    assert a.etranger and not a.teletravail_complet
    assert lieux.analyser("Remote", "Data Engineer", lx).teletravail_complet
    assert lieux.analyser("London", "Data Engineer - Full remote", lx).teletravail_complet
    assert not lieux.analyser("Paris", "Data Engineer (télétravail 2 jours)", lx).teletravail_complet
    assert lieux.analyser("75 - Paris 9e", "Data", lx).zone_preferee
    assert lieux.analyser("971 - Pointe-à-Pitre", "Data", lx).etranger == "971"
    assert lieux.analyser("Lyon 2e - 69", "Data", lx).etranger is None


# --------------------------------------------------------------------------- expérience

@pytest.mark.parametrize("titre, description, attendu", [
    ("Data Engineer", "Vous justifiez de 3 ans d'expérience en Python.", 3),
    ("Data Engineer", "Expérience de 5 ans minimum sur Spark.", 5),
    ("Data Engineer", "2 à 4 ans d'expérience souhaités.", 2),
    ("Data Engineer", "5+ years of experience with SQL.", 5),
    ("Data Engineer", "Au moins 4 ans dans un poste similaire.", 4),
    ("Data Engineer 5 ans d'exp", "", 5),
    # L'âge de l'entreprise n'est pas une exigence d'expérience.
    ("Data Engineer", "Notre société existe depuis plus de 10 ans.", None),
    ("Data Engineer", "Poste ouvert aux débutants.", None),
])
def test_annees_requises(titre, description, attendu):
    assert experience.annees_requises(titre, description) == attendu


def test_structure_prioritaire():
    assert experience.annees_requises("Data Engineer", "10 ans d'expérience", structure=1) == 1


@pytest.mark.parametrize("exige, libelle, attendu", [
    ("D", "Débutant accepté", (0, True)), ("E", "5 An(s)", (5, False)), ("E", "24 Mois", (2, False)),
    (None, None, (None, None)),
])
def test_france_travail(exige, libelle, attendu):
    assert experience.depuis_france_travail(exige, libelle) == attendu
