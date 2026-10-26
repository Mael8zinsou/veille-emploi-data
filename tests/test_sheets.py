"""Client Google Sheets sur un faux serveur : les garde-fous d'écriture sont vérifiés."""
import json
import random
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

from src.models import Motif, Rejet
from src.sorties.sheets import ClientSheets, ErreurSheets
from tests.conftest import Reponse, offre


class FauxSheets:
    """Simule l'API : onglets, valeurs par plage, journal des écritures."""

    def __init__(self, onglets=None, valeurs=None):
        self.onglets = dict(onglets or {"Candidatures": 1})
        self.valeurs = dict(valeurs or {})
        self.ecritures, self.lots = [], []

    def get(self, url, params=None):
        if "/values/" in url:
            v = self.valeurs.get(unquote(url.split("/values/")[-1]))
            return Reponse(200, {"values": [[v]]} if v is not None else {}, text="x")
        return Reponse(200, {"sheets": [{"properties": {"title": t, "sheetId": i}} for t, i in self.onglets.items()]},
                       text="x")

    def put(self, url, params=None, json=None):
        assert params["valueInputOption"] == "RAW"
        self.ecritures.append(json)
        return Reponse(200, {}, text="")

    def post(self, url, json=None):
        self.lots.append(json)
        for req in json["requests"]:
            if "addSheet" in req:
                titre = req["addSheet"]["properties"]["title"]
                self.onglets[titre] = 99
                return Reponse(200, {"replies": [{"addSheet": {"properties": {"sheetId": 99}}}]}, text="x")
        return Reponse(200, {"replies": []}, text="x")


def test_nouvel_onglet_ecrit_en_brut():
    faux = FauxSheets()
    client = ClientSheets(faux, "id")
    lignes = [["N°", "Titre"], [1, "=IMPORTXML(\"http://x\")"]]
    client.ajouter_onglet("Annotation", lignes, colonnes_masquees=(1,), liste_deroulante=(1, ["a", "b"]))
    assert faux.ecritures[0]["values"] == lignes          # écrit tel quel, en RAW : jamais interprété
    types = [next(iter(r)) for r in faux.lots[-1]["requests"]]
    assert "setDataValidation" in types and "updateDimensionProperties" in types


def test_onglet_existant_jamais_ecrase():
    faux = FauxSheets(onglets={"Annotation": 5})
    with pytest.raises(ErreurSheets):
        ClientSheets(faux, "id").ajouter_onglet("Annotation", [["a"]])
    assert faux.ecritures == []


def test_cellule_remplie_jamais_ecrasee():
    faux = FauxSheets(valeurs={"'Candidatures'!A5": "Shift Technology"})
    client = ClientSheets(faux, "id")
    with pytest.raises(ErreurSheets):
        client.ecrire_cellules_vides("Candidatures", {"A5": "Autre"})
    client.ecrire_cellules_vides("Candidatures", {"A12": "Doctolib"})
    assert faux.ecritures == [{"range": "'Candidatures'!A12", "majorDimension": "ROWS", "values": [["Doctolib"]]}]


def test_erreur_http_remontee():
    class Refus(FauxSheets):
        def get(self, url, params=None):
            return Reponse(403, {}, text="PERMISSION_DENIED")
    with pytest.raises(ErreurSheets):
        ClientSheets(Refus(), "id").onglets()


# --------------------------------------------------------------------------- échantillon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import echantillon_annotation  # noqa: E402


def test_echantillon_stratifie(config):
    from src.filtres import normaliser_offre
    gardees = [normaliser_offre(offre(titre=t, entreprise=f"E{i}"), config)
               for i, t in enumerate(["Data Engineer"] * 200 + ["Data Steward"] * 3 + ["Data Scientist"] * 40)]
    rejets = [Rejet(normaliser_offre(offre(titre="Senior Data Engineer", entreprise=f"S{i}"), config), Motif.SENIORITE)
              for i in range(20)]
    tirage = echantillon_annotation.tirer(gardees, rejets, random.Random(1))
    familles = [o.famille for o, v in tirage if v == "gardee"]
    assert familles.count("gouvernance") == 3                       # famille rare : tout est pris
    assert familles.count("data_science") >= echantillon_annotation.MINIMUM_PAR_FAMILLE
    assert sum(v.startswith("rejet:seniorite") for _, v in tirage) == echantillon_annotation.CIBLE_REJETS["seniorite"]
    # Même graine, même tirage : l'échantillon peut être reconstitué.
    assert [o.cle for o, _ in tirage] == [o.cle for o, _ in echantillon_annotation.tirer(gardees, rejets, random.Random(1))]
    json.dumps([v for _, v in tirage])
