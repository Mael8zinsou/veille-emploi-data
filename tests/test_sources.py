"""Sources, sur des réponses réelles capturées au sondage du 25 octobre 2026 (branche `sondes`)."""
from datetime import datetime

import pytest
import requests

from src.filtres import normaliser_offre
from src.models import Contrat, Fil
from src.sources import Contexte, SourceIndisponible, adzuna, france_travail, hellowork, la_bonne_alternance, service_public
from tests.conftest import FausseSession, Reponse, fixture_json, fixture_texte, offre

MAINTENANT = datetime(2026, 10, 26, 9, 0)


def ctx(config, repondre):
    return Contexte(config=config, session=FausseSession(repondre), maintenant_utc=MAINTENANT)


@pytest.fixture(autouse=True)
def sans_pause(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture
def identifiants(monkeypatch):
    for nom in ("FT_CLIENT_ID", "FT_CLIENT_SECRET", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.setenv(nom, "x")


# --------------------------------------------------------------------------- France Travail

def test_ft_conversion_reelle(config):
    items = fixture_json("france_travail/emploi_data_engineer.json")["resultats"]
    offres = [france_travail.convertir(i, Fil.EMPLOI) for i in items]
    assert len(offres) == 40 and all(o.titre and o.url for o in offres)
    assert any(o.experience_annees is not None for o in offres)
    assert any(o.diffuseur for o in offres)          # reprises de partenaires
    assert {o.code_rome for o in offres} >= {"M1811"}


def test_ft_alternance_reelle(config):
    items = fixture_json("france_travail/alternance.json")["resultats"]
    offres = [normaliser_offre(france_travail.convertir(i, Fil.ALTERNANCE), config) for i in items]
    assert offres and all(o.contrat == Contrat.ALTERNANCE for o in offres)
    assert all(o.fil == Fil.ALTERNANCE for o in offres)


def _repondeur_ft(pages_totales=1, statut=200):
    items = fixture_json("france_travail/emploi_ia.json")["resultats"]

    def repondre(methode, url, kw):
        if "access_token" in url:
            return Reponse(200, {"access_token": "jeton"})
        debut = int(kw["params"]["range"].split("-")[0])
        total = 150 * pages_totales
        return Reponse(statut, {"resultats": items}, headers={"Content-Range": f"offres {debut}-{debut + 149}/{total}"})
    return repondre


def test_ft_pagination_et_dates(config, identifiants):
    c = ctx(config, _repondeur_ft(pages_totales=3))
    offres = france_travail.fetch(c)
    appels = [a for a in c.session.appels if "search" in a[1]]
    cfg = config.sources.france_travail
    attendus = len(cfg.emploi.romes) * cfg.max_pages + len(cfg.emploi.mots_cles) + len(cfg.alternance.romes) \
        + len(cfg.alternance.mots_cles)
    assert len(appels) == attendus
    assert all("minCreationDate" in a[2]["params"] and "maxCreationDate" in a[2]["params"] for a in appels)
    assert c.requetes == attendus + 1      # + le jeton
    assert {o.fil_demande for o in offres} == {Fil.EMPLOI, Fil.ALTERNANCE}


def test_ft_sans_identifiants(config, monkeypatch):
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, lambda *a: Reponse()))


def test_ft_jeton_refuse(config, identifiants):
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, lambda m, u, k: Reponse(401, {})))


def test_ft_toutes_requetes_en_echec(config, identifiants):
    def repondre(m, u, k):
        return Reponse(200, {"access_token": "j"}) if "access_token" in u else Reponse(500, {})
    with pytest.raises(SourceIndisponible):
        france_travail.fetch(ctx(config, repondre))


def test_ft_aucun_resultat(config, identifiants):
    def repondre(m, u, k):
        return Reponse(200, {"access_token": "j"}) if "access_token" in u else Reponse(204)
    assert france_travail.fetch(ctx(config, repondre)) == []


def test_ft_erreur_reseau_isolee(config, identifiants):
    items = fixture_json("france_travail/emploi_ia.json")["resultats"]
    n = {"i": 0}

    def repondre(m, u, k):
        if "access_token" in u:
            return Reponse(200, {"access_token": "j"})
        n["i"] += 1
        return requests.ConnectionError() if n["i"] == 1 else Reponse(200, {"resultats": items}, headers={})
    c = ctx(config, repondre)
    assert france_travail.fetch(c) and len(c.erreurs) == 1


# --------------------------------------------------------------------------- Adzuna

def test_adzuna_reel_et_pages(config, identifiants):
    donnees = fixture_json("adzuna/titre_data.json")
    c = ctx(config, lambda m, u, k: Reponse(200, donnees))
    offres = adzuna.fetch(c)
    pages = sum(r.pages for r in config.sources.adzuna.requetes)
    assert c.requetes == pages and len(offres) == 50 * pages
    params = c.session.appels[0][2]["params"]
    assert params["title_only"] == config.sources.adzuna.requetes[0].title_only
    assert params["sort_by"] == "date" and "what_exclude" not in params


def test_adzuna_derniere_page_courte(config, identifiants):
    donnees = fixture_json("adzuna/titre_data.json")
    donnees = {**donnees, "results": donnees["results"][:10]}
    c = ctx(config, lambda m, u, k: Reponse(200, donnees))
    n = len(config.sources.adzuna.requetes)
    assert len(adzuna.fetch(c)) == 10 * n and c.requetes == n     # page courte : pas de page suivante


def test_adzuna_sans_identifiants(config, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    with pytest.raises(SourceIndisponible):
        adzuna.fetch(ctx(config, lambda *a: Reponse()))


# --------------------------------------------------------------------------- HelloWork

def test_hellowork_lecture_reelle():
    offres = hellowork.lire_page(fixture_texte("hellowork/data_scientist.html"), Fil.EMPLOI)
    assert len(offres) == 30
    assert all(o.titre and o.entreprise and o.lieu and o.url.startswith("https://www.hellowork.com/") for o in offres)


def test_hellowork_titre_avec_a():
    offres = hellowork.lire_page(fixture_texte("hellowork/alternance_data.html"), Fil.ALTERNANCE)
    o = next(o for o in offres if "Bac+4 à Bac+5" in o.titre)
    assert "," not in o.lieu and o.entreprise == "NEXA Digital School"


def test_hellowork_refus_coupe_la_source(config, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(SourceIndisponible):
        hellowork.fetch(ctx(config, lambda m, u, k: Reponse(403, text="Access denied")))


def test_hellowork_parcourt_les_recherches(config, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    page = fixture_texte("hellowork/data_scientist.html")
    c = ctx(config, lambda m, u, k: Reponse(200, text=page if k["params"]["p"] == 1 else "<html></html>"))
    offres = hellowork.fetch(c)
    cfg = config.sources.hellowork
    assert len(offres) == 30 * (len(cfg.emploi) + len(cfg.alternance))
    assert {o.fil_demande for o in offres} == {Fil.EMPLOI, Fil.ALTERNANCE}
    assert any(a[2]["params"].get("l") == "Paris" for a in c.session.appels)


def test_session_honnete():
    from src.utils.http import build_session
    s = build_session()
    assert "veille-emploi-data" in s.headers["User-Agent"] and "Mozilla" not in s.headers["User-Agent"]


# --------------------------------------------------------------------------- Choisir le service public

def test_service_public_flux_reel():
    offres = service_public.lire_flux(fixture_texte("service_public/rss_contractuels.xml"))
    assert len(offres) == 20
    dgcl = next(o for o in offres if "Data Analyst" in o.titre)
    assert dgcl.id_source == "MINT_BI075ACA-127426"
    assert dgcl.titre.startswith("DGCL- Data Analyst")
    assert dgcl.url == "https://choisirleservicepublic.gouv.fr/offre-emploi/MINT_BI075ACA-127426/"
    assert dgcl.contrat_brut == service_public.CONTRACTUEL and dgcl.lieu.startswith("2 Place des Saussaies")
    assert dgcl.description and dgcl.date_publication and dgcl.entreprise == ""


@pytest.mark.parametrize("nature, attendu", [
    ("Emploi ouvert aux titulaires et/ou aux contractuels", service_public.CONTRACTUEL),
    ("Emploi ouvert uniquement aux contractuels", service_public.CONTRACTUEL),
    ("Emploi ouvert aux titulaires", service_public.FONCTIONNAIRES),
    ("Emploi réservé aux fonctionnaires et lauréats d'un concours territorial", service_public.FONCTIONNAIRES),
])
def test_service_public_nature(nature, attendu):
    assert service_public.nature_vers_contrat(nature) == attendu


def test_service_public_fonctionnaires_hors_cible(config):
    from src.filtres import motif_de_rejet
    o = normaliser_offre(offre(contrat_brut=service_public.FONCTIONNAIRES), config)
    assert motif_de_rejet(o, config, MAINTENANT.date())[0].value == "contrat_hors_cible"
    o = normaliser_offre(offre(contrat_brut=service_public.CONTRACTUEL), config)
    assert o.contrat == Contrat.CDD and o.fil == Fil.EMPLOI


def test_service_public_detail_reel():
    detail = service_public.lire_detail(fixture_texte("service_public/detail_mef.html"))
    o = offre(entreprise="", lieu="Ivry")
    service_public.completer(o, detail)
    assert o.entreprise == "Direction nationale du renseignement et des enquêtes douanières (DNRED)"
    assert o.lieu == "Val de Marne (94)" and o.date_publication == "2026-10-22"
    assert o.debutant_accepte is None and o.experience_annees is None     # « Confirmé » : neutre


@pytest.mark.parametrize("niveau, debutant, annees", [("Débutant", True, None), ("Expert", None, 5)])
def test_service_public_niveaux(niveau, debutant, annees):
    o = offre()
    service_public.completer(o, {"experienceRequirements": niveau})
    assert o.debutant_accepte == debutant and o.experience_annees == annees


def test_service_public_detail_absent():
    assert service_public.lire_detail("<html>rien</html>") == {}
    assert service_public.lire_detail('<script type="application/ld+json">{pas du json</script>') == {}


def test_service_public_fetch(config):
    flux = fixture_texte("service_public/rss_contractuels.xml")
    detail = fixture_texte("service_public/detail_mef.html")

    def repondre(methode, url, kw):
        if "offerRss" in url:
            return Reponse(text=flux)
        return Reponse(text=detail)

    c = Contexte(config=config, session=FausseSession(repondre), maintenant_utc=datetime(2026, 10, 26, 13, 0))
    offres = service_public.fetch(c)
    assert len(offres) == 20                                  # mêmes offres dans chaque flux : dédoublonnées
    pages = [u for _, u, _ in c.session.appels if "offerRss" not in u]
    # Seules les offres au titre reconnu sont complétées (Data Analyst, développement pour le data…)
    assert pages and all("/offre-emploi/" in u for u in pages)
    completees = [o for o in offres if o.entreprise]
    assert len(completees) == len(pages)
    assert all(o.entreprise == "" for o in offres if "Cuisinier" in o.titre or "Technicien" in o.titre)
    flux_appels = [kw["params"] for _, u, kw in c.session.appels if "offerRss" in u]
    assert {"LCID": 1036, "Rss_Profile": 3871} in flux_appels and {"LCID": 1036, "Rss_JobFamily": 3522} in flux_appels


def test_service_public_limite_de_pages(config):
    flux = fixture_texte("service_public/rss_contractuels.xml")
    sp = config.sources.service_public.model_copy(update={"max_details": 0})
    cfg = config.model_copy(update={"sources": config.sources.model_copy(update={"service_public": sp})})
    c = Contexte(config=cfg, session=FausseSession(lambda m, u, k: Reponse(text=flux)),
                 maintenant_utc=datetime(2026, 10, 26, 13, 0))
    offres = service_public.fetch(c)
    assert all("offerRss" in u for _, u, _ in c.session.appels)
    # Les offres à compléter sont reportées, pas rendues sans employeur.
    assert 0 < len(offres) < 20 and not any("Data Analyst" in o.titre for o in offres)


def test_service_public_indisponible(config):
    c = Contexte(config=config, session=FausseSession(lambda m, u, k: Reponse(status_code=503)),
                 maintenant_utc=MAINTENANT)
    with pytest.raises(SourceIndisponible):
        service_public.fetch(c)


def test_service_public_flux_illisible():
    assert service_public.lire_flux("<html>maintenance</html>") == []


def test_service_public_memoire(config):
    """Une page d'offre n'est lue qu'une fois : la mémoire de la source sert aux passages suivants."""
    flux = fixture_texte("service_public/rss_contractuels.xml")
    detail = fixture_texte("service_public/detail_mef.html")

    def repondre(methode, url, kw):
        return Reponse(text=flux if "offerRss" in url else detail)

    premier = Contexte(config=config, session=FausseSession(repondre), maintenant_utc=datetime(2026, 10, 26, 13, 0))
    service_public.fetch(premier)
    assert premier.memoire and all(v["hiringOrganization"] for v in premier.memoire.values())
    second = Contexte(config=config, session=FausseSession(repondre), maintenant_utc=datetime(2026, 10, 26, 15, 0),
                      memoire=premier.memoire)
    offres = service_public.fetch(second)
    assert all("offerRss" in u for _, u, _ in second.session.appels)
    assert sum(1 for o in offres if o.entreprise) == len(premier.memoire)


# --------------------------------------------------------------------------- La bonne alternance

@pytest.fixture
def cle_lba(monkeypatch):
    monkeypatch.setenv("LBA_API_KEY", "x")


def test_lba_conversion_reelle(config):
    jobs = fixture_json("la_bonne_alternance/recherche_paris.json")["jobs"]
    pass_ = la_bonne_alternance.convertir(next(j for j in jobs if j["identifier"]["partner_label"] == "PASS"))
    assert pass_.titre.startswith('"Data analyst"') and pass_.entreprise.startswith("Direction générale")
    assert pass_.url.startswith("https://www.pass.fonction-publique.gouv.fr/offre/")
    assert pass_.fil_demande == Fil.ALTERNANCE and pass_.duree_mois == 12 and pass_.date_publication == "2026-10-22"
    o = normaliser_offre(pass_, config)
    assert o.contrat == Contrat.ALTERNANCE and o.fil == Fil.ALTERNANCE


def test_lba_lien_hellowork_sans_traceur():
    url = ("https://r.holeest.com/redirect?jd_token=t&o=1&from=https%3A%2F%2Fwww.hellowork.com"
           "%2Ffr-fr%2Femplois%2F123.html")
    assert la_bonne_alternance._lien(url) == "https://www.hellowork.com/fr-fr/emplois/123.html"
    assert la_bonne_alternance._lien("https://exemple.fr/offre") == "https://exemple.fr/offre"
    assert la_bonne_alternance._lien("") == ""


def test_lba_ecole_deleguee(config):
    job = {"identifier": {"id": "1"}, "workplace": {"brand": "Doctolib"}, "offer": {"title": "Alternance Data Engineer"},
           "contract": {"type": ["Apprentissage"]}, "is_delegated": True}
    from src.models import TypeEmployeur
    assert normaliser_offre(la_bonne_alternance.convertir(job), config).type_employeur == TypeEmployeur.ECOLE


def test_lba_fetch(config, cle_lba):
    donnees = fixture_json("la_bonne_alternance/recherche_paris.json")
    c = ctx(config, lambda m, u, k: Reponse(donnees=donnees))
    offres = la_bonne_alternance.fetch(c)
    assert len(c.session.appels) == 2
    assert all(k["headers"]["Authorization"] == "Bearer x" for _, _, k in c.session.appels)
    assert c.session.appels[0][2]["params"]["radius"] == 60 and "latitude" not in c.session.appels[1][2]["params"]
    # Copies France Travail et HelloWork ignorées, doublons d'identifiant fusionnés.
    assert {o.diffuseur for o in offres} == {"PASS", "Jobs that make sense"}
    assert len({o.id_source for o in offres}) == len(offres) == 2


def test_lba_sans_cle(config, monkeypatch):
    monkeypatch.delenv("LBA_API_KEY", raising=False)
    with pytest.raises(SourceIndisponible):
        la_bonne_alternance.fetch(ctx(config, lambda m, u, k: Reponse()))


def test_lba_indisponible(config, cle_lba):
    with pytest.raises(SourceIndisponible):
        la_bonne_alternance.fetch(ctx(config, lambda m, u, k: Reponse(status_code=401)))


def test_lba_reponse_illisible(config, cle_lba):
    with pytest.raises(SourceIndisponible):
        la_bonne_alternance.fetch(ctx(config, lambda m, u, k: Reponse(text="<html>")))
