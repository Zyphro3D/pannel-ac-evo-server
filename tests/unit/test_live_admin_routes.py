"""Page Live : commandes admin saisies dans le chat — ré-élévation, bannissement enregistré, Discord."""
import pytest

from app.models import AccessRule
from app.services import ace_tcp_client, discord_notifier
from app.services.database import db

BANNED = "76561190000000042"


@pytest.fixture
def spy(monkeypatch):
    calls = {"admin": [], "chat": [], "discord": []}
    monkeypatch.setattr(ace_tcp_client, "send_admin_command", lambda text, sid=1: calls["admin"].append(text) or (True, None))
    monkeypatch.setattr(ace_tcp_client, "send_chat", lambda text, sid=1: calls["chat"].append(text) or True)
    monkeypatch.setattr(ace_tcp_client, "get_driver_by_num",
                        lambda num, sid=1: {"name": "Mauvais Joueur", "steam_id": BANNED} if str(num) == "7" else {})
    monkeypatch.setattr(discord_notifier, "notify_admin_action", lambda *a, **k: calls["discord"].append((a[0], a[1])))
    return calls


def _chat(client, text):
    return client.post("/api/live/chat", json={"message": text})


def test_commande_admin_passe_par_la_reelevation(admin_client, spy):
    r = _chat(admin_client, "\\kick 7")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert spy["admin"] == ["\\kick 7"] and spy["chat"] == []
    assert spy["discord"] == [("kick", "Mauvais Joueur")]


def test_message_normal_reste_un_message_de_chat(admin_client, spy):
    _chat(admin_client, "Bonne course à tous")
    assert spy["chat"] == ["Bonne course à tous"] and spy["admin"] == []


def test_elevation_manuelle_n_est_pas_reelevee(admin_client, spy):
    _chat(admin_client, "\\admin motdepasse")
    assert spy["chat"] == ["\\admin motdepasse"] and spy["admin"] == []


def test_commande_inconnue_part_sans_message_discord(admin_client, spy):
    _chat(admin_client, "\\inconnue 7")
    assert spy["admin"] == ["\\inconnue 7"] and spy["discord"] == []


def test_ban_en_direct_est_enregistre_dans_la_page_acces(admin_client, spy):
    with admin_client.app.app_context():
        AccessRule.query.delete(); db.session.commit()
    r = _chat(admin_client, "\\ban 7")
    assert r.get_json()["ok"] is True
    with admin_client.app.app_context():
        rule = AccessRule.query.filter_by(steam_id=BANNED).one()
        assert rule.banned is True and rule.label == "Mauvais Joueur"
    assert spy["discord"] == [("ban", "Mauvais Joueur")]


def test_ban_d_un_numero_inconnu_n_ecrit_rien(admin_client, spy):
    with admin_client.app.app_context():
        AccessRule.query.delete(); db.session.commit()
    _chat(admin_client, "\\ban 99")
    with admin_client.app.app_context():
        assert AccessRule.query.count() == 0


def test_bot_non_connecte_renvoie_une_erreur(admin_client, monkeypatch):
    monkeypatch.setattr(ace_tcp_client, "send_admin_command", lambda text, sid=1: (False, "not_connected"))
    r = _chat(admin_client, "\\kick 7")
    assert r.get_json() == {"ok": False, "error": "not_connected"}
