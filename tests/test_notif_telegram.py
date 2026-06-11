"""
Tests de la notification Telegram : escaping MarkdownV2, mise en forme,
découpage sous la limite 4096, et mode DRY_RUN.
"""
from src.models import Offre
from src.notif_telegram import (
    LIMITE_TELEGRAM,
    _escape,
    construire_messages,
    envoyer_messages,
    message_jour_vide,
)


def _offre(titre="Data Engineer", entreprise="Acme", score=10, nb_sources=1,
           tags=None, url="https://x/y", localisation="Paris", contrat="CDI"):
    o = Offre(
        source="Greenhouse", titre=titre, entreprise=entreprise,
        localisation=localisation, contrat=contrat, description="",
        url=url, date_publication="2026-06-10",
    )
    o.score = score
    o.nb_sources = nb_sources
    o.tags = tags or []
    return o


# --------------------------------------------------------------------------
# Escaping
# --------------------------------------------------------------------------

def test_escape_caracteres_reserves():
    assert _escape("a.b") == "a\\.b"
    assert _escape("C++ (3-5)") == "C\\+\\+ \\(3\\-5\\)"
    assert _escape("a_b*c") == "a\\_b\\*c"


def test_escape_vide():
    assert _escape("") == ""
    assert _escape(None) == ""


def test_format_offre_echappe_le_contenu():
    o = _offre(titre="Data Engineer (H/F)", entreprise="A.B-Corp", tags=["ci/cd"])
    [msg] = construire_messages([o], total_scanne=100, date_str="10 juin")
    # Les caractères réservés du titre/entreprise sont échappés.
    assert "Data Engineer \\(H/F\\)" in msg
    assert "A\\.B\\-Corp" in msg
    # L'URL dans les parenthèses du lien n'est PAS échappée.
    assert "(https://x/y)" in msg


def test_format_offre_exclusif_vs_multi():
    excl = _offre(nb_sources=1)
    multi = _offre(nb_sources=3)
    [m1] = construire_messages([excl], 10, "10 juin")
    [m2] = construire_messages([multi], 10, "10 juin")
    assert "exclusif" in m1
    assert "3 sources" in m2


# --------------------------------------------------------------------------
# Découpage
# --------------------------------------------------------------------------

def test_un_seul_message_si_court():
    offres = [_offre(titre=f"Data Engineer {i}", entreprise=f"E{i}") for i in range(3)]
    messages = construire_messages(offres, 50, "10 juin")
    assert len(messages) == 1


def test_decoupage_si_trop_long():
    # Beaucoup d'offres -> dépasse 4096 -> plusieurs messages, tous sous la limite.
    offres = [
        _offre(titre=f"Data Engineer poste numéro {i}", entreprise=f"Entreprise {i}",
               tags=["python", "airflow", "dbt", "snowflake"], url=f"https://x/{i}")
        for i in range(80)
    ]
    messages = construire_messages(offres, 500, "10 juin")
    assert len(messages) > 1
    assert all(len(m) <= LIMITE_TELEGRAM for m in messages)
    # Numérotation présente quand plusieurs messages.
    assert "1/" in messages[0]


def test_message_jour_vide():
    msg = message_jour_vide(total_scanne=200, date_str="10 juin")
    assert "Aucune nouvelle offre" in msg
    assert "200 offres" in msg


# --------------------------------------------------------------------------
# DRY_RUN
# --------------------------------------------------------------------------

def test_dry_run_n_envoie_rien(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "1")
    # Pas de token/chat_id : en DRY_RUN ça ne doit pas être un problème.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    ok = envoyer_messages(["bonjour"])
    assert ok is True
    out = capsys.readouterr().out
    assert "DRY_RUN" in out
    assert "bonjour" in out


def test_sans_dry_run_sans_credentials_echoue(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert envoyer_messages(["x"]) is False
