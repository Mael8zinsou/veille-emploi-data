"""Lot 0 : sondage des sources, réponses brutes conservées.

Pour chaque source, on interroge largement (toutes familles de métiers, tous fils), on
enregistre les réponses brutes dans SONDE_DIR/<source>/, et on résume en annotation :
statut HTTP, volume, champs utiles. Les réponses servent ensuite de fixtures de tests et
d'échantillon pour le jeu d'annotation.

Budget : Adzuna 2 requêtes (quota de 250 par mois). Les autres sources sont interrogées
avec des pauses de politesse.
"""
from __future__ import annotations

import collections
import os
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from commun import ecrire, notice

SORTIE = Path(os.getenv("SONDE_DIR", "sondes_out"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA})

# Intitulés couvrant les trois priorités du cahier des charges (§ 3.1).
MOTS_CLES = [
    "data engineer", "data scientist", "data analyst", "analytics engineer",
    "machine learning", "mlops", "ingénieur IA", "intelligence artificielle", "LLM",
    "ingénieur données", "développeur BI", "data steward", "chargé d'études statistiques",
]


def pause(s: float = 0.4) -> None:
    time.sleep(s)


def slug(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texte.lower()).strip("_")


# --------------------------------------------------------------------------- France Travail

def sonde_france_travail() -> list[str]:
    d = SORTIE / "france_travail"
    tok = S.post("https://entreprise.francetravail.fr/connexion/oauth2/access_token",
                 params={"realm": "/partenaire"},
                 data={"grant_type": "client_credentials", "client_id": os.environ["FT_CLIENT_ID"],
                       "client_secret": os.environ["FT_CLIENT_SECRET"],
                       "scope": "api_offresdemploiv2 o2dsoffre"}, timeout=20)
    token = tok.json().get("access_token")
    lignes = [f"Jeton : HTTP {tok.status_code}"]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    now = datetime.now(timezone.utc)
    dates = {"minCreationDate": (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z"),
             "maxCreationDate": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    romes: collections.Counter = collections.Counter()
    natures: collections.Counter = collections.Counter()
    contrats: collections.Counter = collections.Counter()

    def requete(nom: str, params: dict) -> None:
        r = S.get(url, headers=h, params={**params, **dates, "range": "0-149"}, timeout=30)
        total = r.headers.get("Content-Range", "").split("/")[-1]
        n = 0
        if r.status_code in (200, 206):
            data = r.json()
            ecrire(d, f"{nom}.json", data)
            res = data.get("resultats", [])
            n = len(res)
            for o in res:
                romes[f"{o.get('romeCode')} {o.get('romeLibelle')}"] += 1
                natures[f"{o.get('natureContrat')}"] += 1
                contrats[f"{o.get('typeContrat')} {o.get('typeContratLibelle')}"] += 1
        lignes.append(f"{nom} : HTTP {r.status_code}, {n} reçues, total {total or '?'}")
        pause()

    for mc in MOTS_CLES:
        requete(f"mc_{slug(mc)}", {"motsCles": mc, "typeContrat": "CDI,CDD,MIS"})
    # Alternance : codes de nature de contrat à confirmer (E2 apprentissage, FS professionnalisation).
    requete("alternance_natureE2_FS", {"motsCles": "data", "natureContrat": "E2,FS"})
    requete("alternance_mc", {"motsCles": "data alternance"})
    # Codes ROME candidats, pour vérifier qu'ils couvrent les métiers.
    for code in ("M1811", "M1405", "M1419", "M1403", "M1805", "M1806"):
        requete(f"rome_{code}", {"codeROME": code, "typeContrat": "CDI,CDD,MIS"})
    lignes.append("Codes ROME les plus vus : " + "; ".join(f"{k} ({v})" for k, v in romes.most_common(15)))
    lignes.append("Natures de contrat : " + "; ".join(f"{k} ({v})" for k, v in natures.most_common(8)))
    lignes.append("Types de contrat : " + "; ".join(f"{k} ({v})" for k, v in contrats.most_common(8)))
    return lignes


# --------------------------------------------------------------------------- APEC

def sonde_apec() -> list[str]:
    d = SORTIE / "apec"
    url = "https://www.apec.fr/cms/webservices/rechercheOffre"
    lignes = []
    contrats: collections.Counter = collections.Counter()
    jeux = [(f"emploi_{slug(mc)}", mc, [101888, 101887]) for mc in MOTS_CLES]
    jeux += [("alternance_data", "data", [597137, 597139]), ("tous_contrats_data_engineer", "data engineer", [])]
    for nom, mc, codes in jeux:
        corps = {"motsCles": mc, "pagination": {"range": 50, "startIndex": 0},
                 "sorts": [{"type": "DATE", "direction": "DESCENDING"}]}
        if codes:
            corps["typesContrat"] = codes
        r = S.post(url, json=corps, headers={"Accept": "application/json"}, timeout=30)
        n, total = 0, "?"
        if r.status_code == 200:
            data = r.json()
            ecrire(d, f"{nom}.json", data)
            n, total = len(data.get("resultats", [])), data.get("totalCount", "?")
            for o in data.get("resultats", []):
                contrats[str(o.get("typeContrat"))] += 1
        lignes.append(f"{nom} : HTTP {r.status_code}, {n} reçues, total {total}")
        pause(0.8)
    lignes.append("Codes de contrat vus : " + ", ".join(f"{k} ({v})" for k, v in contrats.most_common()))
    return lignes


# --------------------------------------------------------------------------- Adzuna (2 requêtes)

def sonde_adzuna() -> list[str]:
    d = SORTIE / "adzuna"
    base = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    auth = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"],
            "results_per_page": 50, "max_days_old": 3, "content-type": "application/json"}
    jeux = {
        "regroupe_data": {"what": "data", "what_or": "engineer scientist analyst analytics ingénieur ingenieur steward"},
        "regroupe_ia": {"what_or": "mlops llm genai IA machine-learning"},
    }
    lignes = []
    for nom, p in jeux.items():
        r = S.get(base, params={**auth, **p}, timeout=30)
        n, total = 0, "?"
        if r.status_code == 200:
            data = r.json()
            ecrire(d, f"{nom}.json", data)
            n, total = len(data.get("results", [])), data.get("count", "?")
            titres = collections.Counter(o.get("title", "")[:40] for o in data.get("results", []))
            lignes.append(f"  exemples {nom} : " + "; ".join(t for t, _ in titres.most_common(6)))
        lignes.append(f"{nom} : HTTP {r.status_code}, {n} reçues, {total} correspondances sur 3 jours")
        pause()
    return lignes


# --------------------------------------------------------------------------- HelloWork

def sonde_hellowork() -> list[str]:
    d = SORTIE / "hellowork"
    lignes = []
    for mc in ("data scientist", "data analyst", "ingénieur IA", "alternance data"):
        r = S.get("https://www.hellowork.com/fr-fr/emploi/recherche.html", params={"k": mc}, timeout=30)
        n = len(re.findall(r'aria-label="Voir offre', r.text))
        ecrire(d, f"{slug(mc)}.html", r.text)
        lignes.append(f"{mc} : HTTP {r.status_code}, {n} cartes d'offre")
        pause(2.0)
    return lignes


# --------------------------------------------------------------------------- La bonne alternance

def sonde_lba() -> list[str]:
    d = SORTIE / "la_bonne_alternance"
    cle = os.environ.get("LBA_API_KEY", "")
    lignes = []
    for nom, params in (("paris_romes_data", {"romes": "M1811,M1405,M1419,M1805,M1806", "latitude": 48.8566,
                                               "longitude": 2.3522, "radius": 60}),
                        ("france_romes_data", {"romes": "M1811,M1405,M1419"})):
        r = S.get("https://api.apprentissage.beta.gouv.fr/api/job/v1/search", params=params,
                  headers={"Authorization": f"Bearer {cle}"}, timeout=40)
        lignes.append(f"{nom} : HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            ecrire(d, f"{nom}.json", data)
            if isinstance(data, dict):
                for k, v in data.items():
                    lignes.append(f"  {k} : {len(v) if isinstance(v, list) else type(v).__name__}")
        else:
            lignes.append("  " + r.text[:300])
        pause()
    return lignes


# --------------------------------------------------------------------------- Passerelles (RSS)

def _resume_rss(texte: str) -> tuple[int, list[str]]:
    try:
        racine = ET.fromstring(texte.encode("utf-8"))
    except ET.ParseError:
        return 0, []
    items = racine.findall(".//item")
    return len(items), [(i.findtext("title") or "")[:60] for i in items[:8]]


def sonde_passerelles() -> list[str]:
    d = SORTIE / "passerelles"
    base = "https://passerelles.economie.gouv.fr/handlers/offerRss.ashx?LCID=1036"
    lignes = []
    for nom, suffixe in (("numerique", "&Rss_JobFamily=3043"), ("toutes", "")):
        r = S.get(base + suffixe, timeout=30)
        ecrire(d, f"rss_{nom}.xml", r.text)
        n, titres = _resume_rss(r.text)
        lignes.append(f"RSS {nom} : HTTP {r.status_code}, {n} offres")
        lignes.append("  " + "; ".join(titres))
        pause(1.0)
    r = S.get("https://passerelles.economie.gouv.fr/offre-de-emploi/tous-les-flux-rss.aspx", timeout=30)
    ecrire(d, "page_flux_rss.html", r.text)
    profils = re.findall(r"Rss_Profile=(\d+)[^>]*>([^<]{3,90})<", r.text)
    data = [f"{t.strip()} ({i})" for i, t in profils if re.search(r"donn|data|statist|numér|informat|décision", t, re.IGNORECASE)]
    lignes.append("Profils data repérés : " + "; ".join(data[:15]))
    return lignes


# --------------------------------------------------------------------------- Choisir le service public

def sonde_csp() -> list[str]:
    d = SORTIE / "choisir_service_public"
    lignes = []
    r = S.get("https://www.data.gouv.fr/api/1/datasets/6322e99e12175f7eb26ff465/", timeout=30)
    lignes.append(f"Jeu de données data.gouv.fr : HTTP {r.status_code}")
    if r.status_code == 200:
        meta = r.json()
        ecrire(d, "datagouv_dataset.json", meta)
        lignes.append(f"  fréquence {meta.get('frequency')}, dernière mise à jour {meta.get('last_update')}")
        for res in meta.get("resources", [])[:6]:
            lignes.append(f"  ressource {res.get('format')} {res.get('title', '')[:50]} "
                          f"modifiée {str(res.get('last_modified'))[:10]} taille {res.get('filesize')}")
    for nom, url in (("flux_wordpress", "https://choisirleservicepublic.gouv.fr/feed/"),
                     ("recherche_data", "https://choisirleservicepublic.gouv.fr/nos-offres/filtres/mot-cles/data/"),
                     ("robots", "https://choisirleservicepublic.gouv.fr/robots.txt")):
        r = S.get(url, timeout=30)
        ecrire(d, f"{nom}.html", r.text)
        n = len(re.findall(r"/offre-emploi/", r.text))
        lignes.append(f"{nom} : HTTP {r.status_code}, {len(r.text)} caractères, {n} liens d'offre")
        pause(1.0)
    return lignes


# --------------------------------------------------------------------------- engagement-jeunes.com

def sonde_engagement_jeunes() -> list[str]:
    d = SORTIE / "engagement_jeunes"
    lignes = []
    for nom, url in (("robots", "https://www.engagement-jeunes.com/robots.txt"),
                     ("cdi", "https://www.engagement-jeunes.com/offres-emploi.html?contrat[]=2"),
                     ("cdi_data", "https://www.engagement-jeunes.com/offres-emploi.html?contrat[]=2&keywords=data"),
                     ("alternance_data", "https://www.engagement-jeunes.com/offres-emploi.html?keywords=data+alternance"),
                     ("cgu", "https://www.engagement-jeunes.com/conditions-utilisation.html")):
        r = S.get(url, timeout=30)
        ecrire(d, f"{nom}.html", r.text)
        liens = set(re.findall(r'href="([^"]*offre[^"]*\d{3,}[^"]*)"', r.text))
        lignes.append(f"{nom} : HTTP {r.status_code}, {len(r.text)} caractères, {len(liens)} liens d'offre")
        pause(2.0)
    return lignes


# --------------------------------------------------------------------------- Second passage (25/10)

def sonde_adzuna_titre() -> list[str]:
    """Deux requêtes : recherche limitée au titre, pour un flux plus net que what_or."""
    d = SORTIE / "adzuna_titre"
    base = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    auth = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"],
            "results_per_page": 50, "max_days_old": 3, "content-type": "application/json", "sort_by": "date"}
    lignes = []
    for nom, p in (("titre_data", {"title_only": "data"}), ("titre_machine_learning", {"title_only": "machine learning"})):
        r = S.get(base, params={**auth, **p}, timeout=30)
        n, total = 0, "?"
        if r.status_code == 200:
            data = r.json()
            ecrire(d, f"{nom}.json", data)
            n, total = len(data.get("results", [])), data.get("count", "?")
            titres = [o.get("title", "")[:45] for o in data.get("results", [])[:8]]
            lignes.append(f"  exemples {nom} : " + "; ".join(titres))
        lignes.append(f"{nom} : HTTP {r.status_code}, {n} reçues, {total} correspondances sur 3 jours")
        pause()
    return lignes


def sonde_csp_rss() -> list[str]:
    """Choisir le service public renvoie vers des flux RSS Talentsoft publics, comme Passerelles."""
    d = SORTIE / "choisir_service_public_rss"
    base = "https://place-ep-recrute.talent-soft.com"
    lignes = []
    r = S.get(f"{base}/offre-de-emploi/tous-les-flux-rss.aspx", timeout=30)
    ecrire(d, "page_flux_rss.html", r.text)
    lignes.append(f"Page des flux : HTTP {r.status_code}, {len(r.text)} caractères")
    familles = re.findall(r"Rss_JobFamily=(\d+)[^>]*>\s*([^<]{3,90})<", r.text)
    num = [(i, t.strip()) for i, t in familles if re.search(r"num|informat|syst", t, re.IGNORECASE)]
    lignes.append("Familles repérées : " + "; ".join(f"{t} ({i})" for i, t in num[:8]))
    flux = [("toutes", "")] + [(f"famille_{i}", f"&Rss_JobFamily={i}") for i, _ in num[:2]]
    for nom, suffixe in flux:
        r = S.get(f"{base}/handlers/offerRss.ashx?LCID=1036{suffixe}", timeout=30)
        ecrire(d, f"rss_{nom}.xml", r.text)
        n, titres = _resume_rss(r.text)
        lignes.append(f"RSS {nom} : HTTP {r.status_code}, {n} offres. " + "; ".join(titres[:5]))
        pause(1.0)
    return lignes


def sonde_engagement_sitemap() -> list[str]:
    """engagement-jeunes.com : robots.txt autorise tout et publie un plan du site des offres."""
    d = SORTIE / "engagement_jeunes_sitemap"
    lignes = []
    r = S.get("https://www.engagement-jeunes.com/fr/sitemap-index-poste.xml", timeout=30)
    ecrire(d, "sitemap_index_poste.xml", r.text)
    enfants = re.findall(r"<loc>([^<]+)</loc>", r.text)
    lignes.append(f"Index des offres : HTTP {r.status_code}, {len(enfants)} plans enfants")
    if enfants:
        r2 = S.get(enfants[-1], timeout=30)
        ecrire(d, "sitemap_enfant.xml", r2.text[:400000])
        urls = re.findall(r"<loc>([^<]+)</loc>", r2.text)
        lignes.append(f"Plan enfant : HTTP {r2.status_code}, {len(urls)} adresses. Exemples : " + "; ".join(urls[:4]))
        if urls:
            pause(2.0)
            r3 = S.get(urls[0], timeout=30)
            ecrire(d, "offre_exemple.html", r3.text)
            lignes.append(f"Offre exemple : HTTP {r3.status_code}, JSON-LD JobPosting : {'JobPosting' in r3.text}")
    pause(2.0)
    r = S.get("https://www.engagement-jeunes.com/", timeout=30)
    ecrire(d, "accueil.html", r.text)
    liens = sorted(set(re.findall(r'href="([^"]*(?:offre|emploi|recherche|cgu|conditions)[^"]*)"', r.text)))
    lignes.append("Liens utiles sur l'accueil : " + "; ".join(liens[:12]))
    return lignes


SONDES = {
    "France Travail": sonde_france_travail, "APEC": sonde_apec, "Adzuna": sonde_adzuna,
    "HelloWork": sonde_hellowork, "La bonne alternance": sonde_lba, "Passerelles": sonde_passerelles,
    "Choisir le service public": sonde_csp, "engagement-jeunes": sonde_engagement_jeunes,
    "Adzuna titre": sonde_adzuna_titre, "Choisir le service public RSS": sonde_csp_rss,
    "engagement-jeunes plan du site": sonde_engagement_sitemap,
}


def main() -> int:
    SORTIE.mkdir(parents=True, exist_ok=True)
    choix = [s.strip() for s in os.getenv("SONDES", "").split(",") if s.strip()]
    for nom, fn in SONDES.items():
        if choix and fn.__name__ not in choix:
            continue
        try:
            notice(f"Sonde {nom}", fn())
        except Exception:  # noqa: BLE001 (une sonde ne doit pas bloquer les autres)
            notice(f"Sonde {nom} : erreur", traceback.format_exc()[-1500:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
