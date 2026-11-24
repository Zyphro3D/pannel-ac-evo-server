"""Tchat en jeu reçu par TCP (serveur 0.9.0+), canal UDP et envoi (symboles, file d'attente).

Les formats viennent d'une capture réseau du jeu et d'essais sur le serveur de test (24/11/2026)."""
import struct

import pytest

from app.services import ace_tcp_client as tcp


@pytest.fixture
def client(monkeypatch):
    """Client d'un serveur fictif, sans base de données (persistance coupée)."""
    monkeypatch.setattr(tcp, "_flask_app", None)
    sid = 9001
    tcp._clients.pop(sid, None)
    c = tcp._get_client(sid)
    yield sid, c
    tcp._clients.pop(sid, None)


def _chat_payload(author: str, text: str, msg_type: int = 0) -> bytes:
    return (tcp._field_varint(1, msg_type) + tcp._field_varint(2, 1)
            + tcp._field_str(3, author) + tcp._field_str(4, text))


def test_player_chat_received_over_tcp(client):
    sid, c = client
    tcp._handle_message("MultiplayerChatMessage", _chat_payload("Florian Praturlon", "test 5"), sid)
    msgs = tcp.get_chat_history(sid)
    assert [(m["author"], m["text"], m["source"]) for m in msgs] == [("Florian Praturlon", "test 5", "player")]
    assert msgs[0]["id"] == 1


def test_admin_replies_are_for_admins_only(client):
    sid, c = client
    tcp._handle_message("MultiplayerChatMessage", _chat_payload(">> Server", "You are now an admin.", 3), sid)
    assert tcp.get_chat_history(sid) == []
    assert [m["source"] for m in tcp.get_chat_history(sid, include_server=True)] == ["server"]


def test_player_commands_never_reach_history(client):
    sid, c = client
    tcp._handle_message("MultiplayerChatMessage", _chat_payload("Jean", "\\admin secret"), sid)
    assert tcp.get_chat_history(sid, include_server=True) == []


def test_same_message_from_tcp_and_log_kept_once(client):
    sid, c = client
    tcp._handle_message("MultiplayerChatMessage", _chat_payload("Jean", "salut"), sid)
    line = "[2026-11-24 21:00:00.000] [server] [info] Chat from Jean [76561197960287930]: salut"
    tcp._on_chat_log(tcp._RE_CHAT_LOG.search(line), line, c, sid)
    assert len(tcp.get_chat_history(sid)) == 1


@pytest.mark.parametrize("raw, shown", [
    ("🏁 Beau tour !", "★ Beau tour !"),
    ("❤️ Courage", "♥ Courage"),
    ("GG 😂🚗 !", "GG !"),
    ("é è à ç ù ô €", "é è à ç ù ô €"),
    ("► ☺ ok", "ok"),
])
def test_text_is_made_displayable_in_game(raw, shown):
    assert tcp.sanitize_game_text(raw) == shown


def test_message_queued_while_disconnected_then_sent(client, monkeypatch):
    sid, c = client
    assert tcp.send_chat("Bienvenue !", sid) is True        # pas de socket : mis en attente
    assert tcp.send_chat("\\kick 3", sid) is False          # une commande n'attend jamais
    assert [t for t, _ in c["pending_chat"]] == ["Bienvenue !"]

    sent = []

    class FakeSock:
        def sendall(self, data):
            sent.append(data)

    c["sock"] = FakeSock()
    tcp._flush_pending_chat(sid)
    assert len(sent) == 1 and b"Bienvenue !" in sent[0]
    assert not c["pending_chat"]
    assert [m["text"] for m in tcp.get_chat_history(sid)] == ["Bienvenue !"]


def test_stale_queued_message_is_dropped(client):
    sid, c = client
    c["pending_chat"].append(("vieux message", 0.0))
    c["sock"] = object()     # aucun envoi ne doit être tenté
    tcp._flush_pending_chat(sid)
    assert not c["pending_chat"]


def test_udp_association_packet_matches_game():
    # Capture du jeu : 09 00 b3 02 + 14 zéros pour la connexion n° 691
    assert tcp._build_udp_associate(691) == bytes.fromhex("0900b302") + bytes(14)


def test_bot_name_request():
    frame = tcp._build_request_car("Zyphro")
    total = struct.unpack_from("<H", frame)[0] + 2
    assert total == len(frame)
    name_len = frame[4]
    assert frame[5:5 + name_len] == b"RequestPlayerCar"
    driver_info = tcp._parse_proto(frame[5 + name_len:])[2][0]
    assert tcp._parse_proto(driver_info)[1] == [b"Zyphro"]


def test_handshake_starts_udp_with_connection_id(client, monkeypatch):
    sid, c = client
    started = []

    class FakeThread:
        def __init__(self, target, args, **kw):
            started.append(args)

        def start(self):
            pass

    monkeypatch.setattr(tcp.threading, "Thread", FakeThread)
    payload = tcp._field_varint(1, 1) + tcp._field_varint(4, 699)
    tcp._handle_message("ConnectToServerHandshakeResponse", payload, sid)
    assert started == [(sid, 699, c["conn_gen"])]


def test_bot_name_sent_once_per_connection(client):
    """Le serveur répond à chaque RequestPlayerCar par un AssociateUDPSocketResponse :
    renvoyer le nom à chaque fois faisait tourner les deux messages en boucle."""
    sid, c = client
    sent = []

    class FakeSock:
        def sendall(self, data):
            sent.append(data)

    c["sock"], c["bot_name"], c["conn_gen"] = FakeSock(), "Zyphro", 5
    for _ in range(3):
        tcp._handle_message("AssociateUDPSocketResponse", tcp._field_varint(1, 1), sid)
    assert len(sent) == 1
    c["conn_gen"] = 7     # nouvelle connexion : le nom repart une fois
    tcp._handle_message("AssociateUDPSocketResponse", tcp._field_varint(1, 1), sid)
    assert len(sent) == 2


def test_saved_settings_reach_running_bot(client):
    sid, c = client
    sent = []

    class FakeSock:
        def sendall(self, data):
            sent.append(data)

    c.update(running=True, sock=FakeSock(), conn_gen=3, assoc_gen=3)
    cfg = {"ACE_BOT_NAME": "Zyphro - Admin", "ACE_BOT_WELCOME_DELAY": "30",
           "ACE_BOT_MSG_WELCOME": "Welcome {name}!"}
    tcp.apply_bot_settings(cfg)
    assert (c["bot_name"], c["welcome_delay"], c["msg_welcome"]) == ("Zyphro - Admin", 30, "Welcome {name}!")
    assert len(sent) == 1 and b"Zyphro - Admin" in sent[0]
    tcp.apply_bot_settings(cfg)          # même nom : rien n'est renvoyé
    assert len(sent) == 1
