"""Commande admin : le bot est ré-élevé juste avant, car le battement efface le statut admin."""
from app.services import ace_tcp_client


def test_reelevation_puis_commande_dans_l_ordre(monkeypatch):
    sent = []
    monkeypatch.setattr(ace_tcp_client, "is_connected", lambda sid=1: True)
    monkeypatch.setattr(ace_tcp_client, "elevate_admin", lambda sid=1: sent.append(("admin", sid)) or None)
    monkeypatch.setattr(ace_tcp_client, "send_chat", lambda text, sid=1: sent.append((text, sid)) or True)
    monkeypatch.setattr(ace_tcp_client.time, "sleep", lambda s: None)
    ok, err = ace_tcp_client.send_admin_command("\\kick 12", 3)
    assert (ok, err) == (True, None)
    assert sent == [("admin", 3), ("\\kick 12", 3)]


def test_bot_non_connecte_ne_envoie_rien(monkeypatch):
    sent = []
    monkeypatch.setattr(ace_tcp_client, "is_connected", lambda sid=1: False)
    monkeypatch.setattr(ace_tcp_client, "send_chat", lambda text, sid=1: sent.append(text) or True)
    assert ace_tcp_client.send_admin_command("\\skip") == (False, "not_connected")
    assert sent == []


def test_sans_mot_de_passe_admin_la_commande_part_quand_meme(monkeypatch):
    sent = []
    monkeypatch.setattr(ace_tcp_client, "is_connected", lambda sid=1: True)
    monkeypatch.setattr(ace_tcp_client, "elevate_admin", lambda sid=1: "Aucun mot de passe admin configuré dans la session active")
    monkeypatch.setattr(ace_tcp_client, "send_chat", lambda text, sid=1: sent.append(text) or True)
    assert ace_tcp_client.send_admin_command("\\skip") == (True, None)
    assert sent == ["\\skip"]
