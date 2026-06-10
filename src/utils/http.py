"""
Session HTTP partagée par toutes les sources : retry, timeout, User-Agent navigateur réaliste.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 15  # secondes


def build_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (500, 502, 503, 504, 429),
) -> requests.Session:
    """
    Crée une session avec retry exponentiel sur les codes serveur transitoires.
    backoff_factor=0.5 → attente 0.5s, 1s, 2s entre les tentatives.
    """
    s = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def get_json(session: requests.Session, url: str, **kwargs) -> dict | list | None:
    """
    GET avec timeout par défaut. Retourne le JSON parsé ou None en cas d'échec.
    Les sources individuelles gèrent leur propre logging des erreurs.
    """
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    try:
        r = session.get(url, **kwargs)
        if r.status_code >= 400:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None
