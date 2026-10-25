"""Session HTTP partagée : nouvelles tentatives sur les erreurs passagères, identité honnête.

L'outil se présente pour ce qu'il est (un robot de veille personnelle, avec l'adresse de son
dépôt) au lieu d'imiter un navigateur. Un site qui refuse ce type d'accès est respecté : la
source concernée s'arrête (cf. src/sources).
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "veille-emploi-data/2.0 (veille personnelle; +https://github.com/Mael8zinsou/veille-emploi-data)"


def build_session(total_retries: int = 3, backoff_factor: float = 0.5,
                  status_forcelist: tuple[int, ...] = (500, 502, 503, 504)) -> requests.Session:
    """Nouvelles tentatives espacées (0,5 s, 1 s, 2 s) sur les erreurs serveur passagères.

    Le code 429 (trop de requêtes) n'est pas rejoué : c'est une demande de ralentir.
    """
    s = requests.Session()
    retry = Retry(total=total_retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist,
                  allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s
