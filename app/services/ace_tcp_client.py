"""
Client TCP pour le serveur ACE EVO (port 9700).
Protocole : [uint16_LE: total_len-2][0x00][0x02][uint8: name_len][name][protobuf_payload]

Messages pris en charge :
  C2S  ClientConnectionRequest  — handshake initial
  C2S  RequestPlayerCar         — déclare le nom affiché du bot dans le tchat (driver_info)
  C2S  MultiplayerChatMessage   — envoi d'un message dans le tchat du jeu
  S2C  ConnectToServerHandshakeResponse — champ 4 = numéro de connexion (sert à l'association UDP)
  S2C  AssociateUDPSocketResponse — le canal UDP est associé : le direct commence
  S2C  MultiplayerChatMessage   — tchat des joueurs et réponses du serveur aux commandes admin
  S2C  BroadcastStateMessage    — état courant (PlatformRaceLeaderboard, etc.)
  S2C  SplitFromRemoteMessage   — passage de secteur

Depuis le serveur 0.9.0, le direct (tchat compris) n'est envoyé qu'aux clients qui ont associé
un canal UDP à leur connexion TCP, comme le fait le jeu (relevé par capture réseau le 24/11/2026) :
  C2S UDP  09 00 <numéro de connexion uint16 LE> + 14 zéros  — association
  S2C UDP  03 00 <8 octets> …                                 — ping du serveur
  C2S UDP  04 00 <les 8 octets reçus> <double : heure locale> — réponse au ping
La connexion TCP est entretenue par des cadres vides (00 00), comme le jeu.
"""
import collections
import glob
import json
import os
import re
import socket
import struct
import threading
import time
import logging

from config import (DEFAULT_BOT_MSG_WELCOME, DEFAULT_BOT_MSG_DISCORD, DEFAULT_BOT_MSG_SITE,
                    DEFAULT_BOT_WELCOME_DELAY)

log = logging.getLogger(__name__)

# Per-server client state (keyed by server_id)
_clients: dict    = {}
_clients_lock     = threading.Lock()

# Référence à l'app Flask, nécessaire pour ouvrir un app_context depuis les
# threads de fond du bot (persistance LapRecord) — fournie par init_app().
_flask_app = None


def init_app(app):
    """Donne au module une référence à l'app Flask pour les accès DB en thread."""
    global _flask_app
    _flask_app = app


def _get_client(server_id: int) -> dict:
    """Returns per-server state dict, creating it on first access."""
    with _clients_lock:
        if server_id not in _clients:
            _clients[server_id] = {
                "host":                  "127.0.0.1",
                "port":                  9700,
                "steam_id":              "",
                "car_model":             "preset_190_evo_ii",
                "server_name":           "",
                "sock":                  None,
                "lock":                  threading.Lock(),
                "connected":             False,
                "running":               False,
                "leaderboard":           {},
                "lb_lock":               threading.Lock(),
                "on_event":              None,
                "join_times":            {},
                "car_id_to_sid":         {},
                "num_to_sid":            {},
                "sid_car_raw":           {},
                "car_splits":            {},
                "recently_disconnected": {},
                "race_state":            {"server_best_ms": None},
                "chat_buffer":           collections.deque(maxlen=50),
                "chat_seq":              0,       # numéro du dernier message (pour ?since=)
                "chat_loaded":           False,   # historique rechargé depuis la base
                "pending_chat":          collections.deque(maxlen=20),  # envois en attente de reconnexion
                "bot_name":              "",
                "welcome_delay":         DEFAULT_BOT_WELCOME_DELAY,
                "conn_gen":              0,       # change à chaque connexion : arrête l'ancien fil UDP
                "welcome_discord":       "",
                "welcome_site":          "",
                "deploy_mode":           "native",
                "log_file":              "",
                "container_name":        "ace-server",
                "msg_welcome":           DEFAULT_BOT_MSG_WELCOME,
                "msg_discord":           DEFAULT_BOT_MSG_DISCORD,
                "msg_site":              DEFAULT_BOT_MSG_SITE,
                "track_cache":           {"track_value": "", "session_type": "", "circuit": "", "fetched_at": 0.0},
                "manual_admin":          False,
                # Contacts pour Discord (option DISCORD_NOTIFY_CONTACTS) : regroupés par minute
                "contacts":              None,
                "contacts_buffer":       [],
                "contacts_since":        0.0,
            }
        return _clients[server_id]


# ── Encodage protobuf minimal ─────────────────────────────────────────────────

def _varint(value: int) -> bytes:
    """Encode un entier non-signé en varint protobuf."""
    buf = []
    value = value & 0xFFFFFFFFFFFFFFFF  # uint64
    while True:
        part = value & 0x7F
        value >>= 7
        if value:
            buf.append(part | 0x80)
        else:
            buf.append(part)
            break
    return bytes(buf)


def _field_varint(num: int, value: int) -> bytes:
    return _varint((num << 3) | 0) + _varint(value)


def _field_bytes(num: int, data: bytes) -> bytes:
    return _varint((num << 3) | 2) + _varint(len(data)) + data


def _field_str(num: int, text: str) -> bytes:
    return _field_bytes(num, text.encode())


# ── Décodage protobuf minimal ─────────────────────────────────────────────────

def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _parse_proto(buf: bytes) -> dict:
    """Décode un message protobuf en dict {field_num: [values]}."""
    fields: dict[int, list] = {}
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field = tag >> 3
        wire  = tag & 7
        if wire == 0:
            v, pos = _read_varint(buf, pos)
            fields.setdefault(field, []).append(v)
        elif wire == 2:
            l, pos = _read_varint(buf, pos)
            v = buf[pos:pos+l]; pos += l
            fields.setdefault(field, []).append(v)
        elif wire == 5:
            v = buf[pos:pos+4]; pos += 4
            fields.setdefault(field, []).append(v)
        elif wire == 1:
            v = buf[pos:pos+8]; pos += 8
            fields.setdefault(field, []).append(v)
        else:
            break  # type inconnu → abandon
    return fields


# ── Extraction Steam ID depuis les 20 octets du driver ID ────────────────────

def _extract_steam_id(driver_id_bytes: bytes) -> str:
    """Le driver ID est un sous-message protobuf; field 2 = steam_id (varint)."""
    try:
        f = _parse_proto(driver_id_bytes)
        # field 2 contient le Steam ID comme varint
        vals = f.get(2, [])
        if vals:
            return str(vals[0])
        # Fallback : field 1
        vals = f.get(1, [])
        if vals:
            return str(vals[0])
    except Exception:
        pass
    return driver_id_bytes.hex()


# ── Construction des messages ─────────────────────────────────────────────────

def _wrap(name: str, payload: bytes) -> bytes:
    """Encapsule payload dans l'enveloppe protocolaire ACE EVO.
    Format : [uint16_LE: len(content)][0x02][0x00][uint8: name_len][name][payload]
    """
    name_b = name.encode()
    content = bytes([0x02, 0x00]) + bytes([len(name_b)]) + name_b + payload
    return struct.pack('<H', len(content)) + content


def _build_connection_request(c: dict, cfg: dict | None = None) -> bytes:
    payload = (
        _field_varint(1, 1) +
        _field_varint(5, c.get("protocol_version", 8)) +   # protocol version — inchangé depuis le build 23658359
        _field_varint(6, c.get("server_version", 6)) +     # server version — toujours 6 avec le build ACE EVO Server
                                 # 24991735 (0.9.0) : testé en le passant à 7, le serveur a
                                 # explicitement rejeté avec "Current: (Server:6, Protocol:8)",
                                 # confirmant que 6 reste la bonne valeur. Pas la cause de
                                 # l'absence de BroadcastStateMessage/chat sur ce build — voir
                                 # ailleurs (peut-être un flag de connexion "spectateur").
        _field_str(7, c["steam_id"]) +
        _field_str(9, _get_car_model(c, cfg))
    )
    return _wrap('ClientConnectionRequest', payload)


def _build_request_car(name: str) -> bytes:
    """RequestPlayerCar réduit au nom du pilote (driver_info : 1 = prénom, 2 = nom).
    Le serveur affiche ce nom comme expéditeur des messages du bot (sinon « LoadingPlayer »).
    Testé le 24/11/2026 : aucune voiture visible en piste, mais le bot occupe une place de stand."""
    return _wrap('RequestPlayerCar', _field_bytes(2, _field_str(1, name)))


def _build_udp_associate(conn_id: int) -> bytes:
    return b'\x09\x00' + struct.pack('<H', conn_id & 0xFFFF) + bytes(14)


def _build_chat(text: str) -> bytes:
    ts_ns = int(time.time() * 1_000_000_000)
    payload = _field_varint(2, ts_ns) + _field_str(4, text)
    return _wrap('MultiplayerChatMessage', payload)


# ── Parsing des messages entrants ─────────────────────────────────────────────

def _parse_broadcast(payload: bytes, server_id: int):
    """BroadcastStateMessage → extrait PlatformRaceLeaderboard."""
    c        = _get_client(server_id)
    f        = _parse_proto(payload)
    any_data = f.get(2, [None])[0]
    if not any_data:
        log.info("broadcast: pas de field 2 — fields=%s", list(f.keys()))
        return

    af       = _parse_proto(any_data)
    type_url = af.get(1, [b''])[0]
    type_str = type_url.decode('utf-8', errors='replace') if isinstance(type_url, bytes) else str(type_url)
    log.info("broadcast reçu: %s", type_str.split('/')[-1])
    if b'PlatformRaceLeaderboard' not in type_url:
        return

    lb_bytes = af.get(2, [b''])[0]
    lb = _parse_proto(lb_bytes)

    updates = {}
    for entry_bytes in lb.get(2, []):
        ef = _parse_proto(entry_bytes)
        driver_id_bytes = ef.get(1, [b''])[0]
        steam_id = _extract_steam_id(driver_id_bytes)

        timing_bytes = (ef.get(7, [b''])[0]) or b''
        tf = _parse_proto(timing_bytes) if timing_bytes else {}

        # field 1 = dernier secteur (-1 / max_int64 = pas encore commencé)
        sector_raw = tf.get(1, [None])[0]
        sector = None
        if sector_raw is not None:
            if sector_raw > 0x7FFFFF00000000:
                sector = None
            else:
                sector = sector_raw

        # field 12 (fixed32) = temps en ms (float32)
        time_raw = tf.get(12, [None])[0]
        time_ms = None
        if time_raw and len(time_raw) == 4:
            time_ms = struct.unpack_from('<f', time_raw)[0]
            if time_ms > 1e9 or time_ms < 0:
                time_ms = None

        updates[steam_id] = {
            'steam_id':      steam_id,
            'driver_id_hex': driver_id_bytes.hex(),
            'sector':        sector,
            'time_ms':       int(time_ms) if time_ms else None,
        }
        log.debug("leaderboard entry: steam_id=%s sector=%s time_ms=%s id_hex=%s",
                  steam_id, sector, int(time_ms) if time_ms else None, driver_id_bytes.hex())

    if updates:
        with c["lb_lock"]:
            for sid, data in updates.items():
                if sid in c["leaderboard"]:
                    c["leaderboard"][sid].update(data)
                else:
                    c["leaderboard"][sid] = data

        if c["on_event"]:
            try:
                c["on_event"]({'type': 'leaderboard', 'entries': list(updates.values())})
            except Exception:
                pass


def _parse_split(payload: bytes, server_id: int):
    """SplitFromRemoteMessage — passage de secteur."""
    c          = _get_client(server_id)
    f          = _parse_proto(payload)
    driver_id_bytes = f.get(1, [b''])[0]
    steam_id   = _extract_steam_id(driver_id_bytes)
    sector_idx = f.get(3, [0])[0]

    # Passage du secteur 0 = nouveau tour entamé → réinitialise l'invalidation
    if sector_idx == 0:
        with c["lb_lock"]:
            if steam_id in c["leaderboard"]:
                c["leaderboard"][steam_id]["lap_invalid"] = False

    if c["on_event"]:
        try:
            c["on_event"]({'type': 'split_tcp', 'steam_id': steam_id, 'sector': sector_idx})
        except Exception:
            pass


def _handle_message(name: str, payload: bytes, server_id: int):
    if name == 'ConnectToServerHandshakeResponse':
        _on_handshake(payload, server_id)
    elif name == 'AssociateUDPSocketResponse':
        _on_udp_associated(server_id)
    elif name == 'MultiplayerChatMessage':
        _on_chat_tcp(payload, server_id)
    elif name == 'BroadcastStateMessage':
        _parse_broadcast(payload, server_id)
    elif name == 'SplitFromRemoteMessage':
        _parse_split(payload, server_id)
    else:
        # Diagnostic : utile pour repérer un futur type de message non géré.
        log.debug("ace_tcp_client: message TCP non géré reçu : %r (server=%d, %d octets)",
                  name, server_id, len(payload))


# ── Boucle de réception ───────────────────────────────────────────────────────

def _on_handshake(payload: bytes, server_id: int):
    """Réponse de connexion : champ 4 = numéro de connexion → association du canal UDP."""
    c = _get_client(server_id)
    conn_id = _parse_proto(payload).get(4, [None])[0]
    if not isinstance(conn_id, int):
        log.warning("ace_tcp_client: réponse de connexion sans numéro de connexion (server=%d)", server_id)
        return
    gen = c["conn_gen"]
    threading.Thread(target=_udp_loop, args=(server_id, conn_id, gen), daemon=True,
                     name=f"ace-udp-{server_id}").start()


def _on_udp_associated(server_id: int):
    c = _get_client(server_id)
    log.info("ace_tcp_client: canal UDP associé, direct actif (server=%d)", server_id)
    if c["bot_name"]:
        with c["lock"]:
            sock = c["sock"]
        if sock is not None:
            try:
                sock.sendall(_build_request_car(c["bot_name"]))
            except OSError as e:
                log.warning("ace_tcp_client: envoi du nom du bot impossible : %s", e)


def _udp_loop(server_id: int, conn_id: int, gen: int):
    """Associe un canal UDP à la connexion et répond aux pings du serveur, tant que la
    connexion TCP de la même génération vit. Sans ce canal, le serveur n'envoie ni tchat ni
    état de course au bot."""
    c = _get_client(server_id)
    addr = (c["host"], c["port"])   # le jeu utilise le même port en TCP et en UDP
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.settimeout(1.0)
    try:
        u.sendto(_build_udp_associate(conn_id), addr)
        last_assoc = time.time()
        while c["running"] and c["conn_gen"] == gen:
            try:
                pkt, _ = u.recvfrom(4096)
            except socket.timeout:
                # Association perdue (paquet UDP égaré) : on la renvoie tant que rien n'arrive.
                if time.time() - last_assoc > 5:
                    u.sendto(_build_udp_associate(conn_id), addr)
                    last_assoc = time.time()
                continue
            last_assoc = time.time()
            if pkt[:2] == b'\x03\x00' and len(pkt) >= 10:
                u.sendto(b'\x04\x00' + pkt[2:10] + struct.pack('<d', time.time()), addr)
    except OSError as e:
        log.debug("ace_tcp_client: canal UDP fermé (server=%d) : %s", server_id, e)
    finally:
        u.close()


def _recv_loop(sock: socket.socket, server_id: int):
    """Boucle de réception. Le serveur coupe un client silencieux (~60 s, « software
    timeout ») : comme le jeu, on envoie un cadre vide (00 00) après chaque seconde sans
    trafic reçu. L'ancien battement (renvoi du ClientConnectionRequest toutes les 20 s)
    ouvrait une nouvelle connexion côté serveur à chaque fois et effaçait le statut admin."""
    c = _get_client(server_id)
    buf = b''
    sock.settimeout(1.0)
    while c["running"]:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 2:
                total_len = struct.unpack_from('<H', buf, 0)[0] + 2
                if total_len < 5:            # cadre vide (battement)
                    if len(buf) < total_len:
                        break
                    buf = buf[total_len:]
                    continue
                marker = struct.unpack_from('<H', buf, 2)[0]
                if marker != 0x0002:
                    buf = buf[1:]  # resync
                    continue
                if len(buf) < total_len:
                    break
                name_len = buf[4]
                name     = buf[5:5+name_len].decode('utf-8', errors='replace')
                payload  = buf[5+name_len:total_len]
                buf      = buf[total_len:]
                try:
                    _handle_message(name, payload, server_id)
                except Exception as e:
                    log.debug("handle_message %s error: %s", name, e)
        except socket.timeout:
            try:
                sock.sendall(b'\x00\x00')
            except OSError:
                break
        except OSError:
            break
    log.info("ace_tcp_client: connexion terminée (server=%d)", server_id)


# ── Thread de connexion avec reconnexion auto ─────────────────────────────────

def _connect_loop(server_id: int):
    c = _get_client(server_id)
    while c["running"]:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((c["host"], c["port"]))
            sock.settimeout(None)
            _active_cfg = _read_active_config(server_id)
            _conn_req = _build_connection_request(c, _active_cfg)
            sock.sendall(_conn_req)
            log.info("ace_tcp_client: connecté à %s:%d (steam=%s, server=%d)",
                     c["host"], c["port"], c["steam_id"], server_id)
            with c["lock"]:
                c["sock"]      = sock
                c["connected"] = True
                c["conn_gen"] += 1
            # S'élève admin dès la connexion si configuré (même config déjà lue ci-dessus),
            # ou si une élévation manuelle a déjà été demandée sur ce serveur : chaque
            # reconnexion repart sans droits admin.
            _pwd = _get_admin_password(_active_cfg)
            if not _pwd and c.get("manual_admin") and _active_cfg:
                _pwd = _active_cfg.get("Server", {}).get("AdminPassword", "")
            if _pwd:
                time.sleep(1)
                send_chat(f"\\admin {_pwd}", server_id)
                log.info("ace_tcp_client: élévation admin envoyée (server=%d)%s", server_id,
                          " [ré-élévation manuelle après reconnexion]" if c.get("manual_admin") else "")
            _flush_pending_chat(server_id)
            _recv_loop(sock, server_id)
        except Exception as e:
            log.debug("ace_tcp_client: erreur connexion %s:%d — %s", c["host"], c["port"], e)
        finally:
            with c["lock"]:
                c["sock"]      = None
                c["connected"] = False
                c["conn_gen"] += 1
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        if c["running"]:
            time.sleep(5)


# ── API publique ──────────────────────────────────────────────────────────────

# Le tchat du jeu n'a pas de police pour les emojis (carrés vides, testé le 24/11/2026) :
# les plus courants deviennent un symbole qui s'affiche, les autres sont retirés.
_EMOJI_TO_SYMBOL = {
    "🏁": "★", "🏆": "★", "⭐": "★", "👍": "✓", "✅": "✓", "👏": "✓",
    "❤": "♥", "💙": "♥", "💚": "♥", "🔥": "●", "💪": "♪", "🎉": "♪", "🎵": "♪", "⚡": "!!",
}
# Symboles hors Latin vérifiés en jeu ; ► et ☺ s'affichent en carrés.
_SAFE_SYMBOLS = set("★✓♥●♪€…–—‘’“”•")


def sanitize_game_text(text: str) -> str:
    """Rend un texte affichable dans le tchat du jeu : emojis connus → symbole, reste retiré."""
    out = []
    for ch in text:
        if ch in _EMOJI_TO_SYMBOL:
            out.append(_EMOJI_TO_SYMBOL[ch])
        elif ord(ch) < 0x2000 or ch in _SAFE_SYMBOLS:
            out.append(ch)
        # sinon : emoji, sélecteur de variante (U+FE0F), symbole sans glyphe → retiré
    return re.sub(r" {2,}", " ", "".join(out)).strip()


def _now_hms() -> str:
    """Heure affichée dans le tchat, dans le fuseau du panel (le conteneur tourne en UTC)."""
    try:
        from zoneinfo import ZoneInfo
        import datetime as _dt
        tz = (_flask_app.config.get("PANEL_TIMEZONE") if _flask_app else None) or "Europe/Paris"
        return _dt.datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")
    except Exception:
        return time.strftime("%H:%M:%S")


def _chat_add(c: dict, server_id: int, author: str, text: str, source: str, ts: str = "") -> None:
    """Ajoute un message à l'historique (mémoire + base). source : player | panel | server.
    Un même message reçu par deux voies (TCP et journal) en moins de 10 s n'est gardé qu'une fois."""
    ts = _now_hms()   # le message arrive en direct ; l'heure du journal du jeu est en UTC
    now = time.time()
    with c["lb_lock"]:
        for m in list(c["chat_buffer"])[-10:]:
            if m["author"] == author and m["text"] == text and now - m.get("t", 0) < 10:
                return
        c["chat_seq"] = c.get("chat_seq", 0) + 1
        c["chat_buffer"].append({"id": c["chat_seq"], "author": author, "text": text,
                                 "ts": ts, "source": source, "t": now})
    if _flask_app is None:
        return
    try:
        with _flask_app.app_context():
            from app.services.database import db
            from app.models import ChatMessage
            db.session.add(ChatMessage(server_id=server_id, author=author[:100],
                                       text=text[:500], source=source, ts=ts))
            db.session.commit()
    except Exception:
        log.exception("Échec persistance ChatMessage (server_id=%s)", server_id)


def _load_chat_history(c: dict, server_id: int) -> None:
    """Au premier appel après un redémarrage du panel, recharge les 50 derniers messages
    de la base, et purge ceux de plus de 30 jours."""
    if c.get("chat_loaded") or _flask_app is None:
        return
    c["chat_loaded"] = True
    try:
        import datetime as _dt
        with _flask_app.app_context():
            from app.services.database import db
            from app.models import ChatMessage
            limit = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=30)
            ChatMessage.query.filter(ChatMessage.created_at < limit).delete()
            db.session.commit()
            rows = (ChatMessage.query.filter_by(server_id=server_id)
                    .order_by(ChatMessage.id.desc()).limit(50).all())
            with c["lb_lock"]:
                old = list(c["chat_buffer"])
                c["chat_buffer"].clear()
                for r in reversed(rows):
                    c["chat_seq"] = c.get("chat_seq", 0) + 1
                    c["chat_buffer"].append({"id": c["chat_seq"], "author": r.author, "text": r.text,
                                             "ts": r.ts or "", "source": r.source, "t": 0})
                for m in old:     # messages arrivés avant le chargement
                    c["chat_seq"] += 1
                    c["chat_buffer"].append({**m, "id": c["chat_seq"]})
    except Exception:
        log.exception("Échec chargement de l'historique du tchat (server_id=%s)", server_id)


def _on_chat_tcp(payload: bytes, server_id: int) -> None:
    """Message de tchat relayé par le serveur (champ 3 = expéditeur, 4 = texte). Les réponses
    du serveur aux commandes admin arrivent sous l'expéditeur « >> Server » : réservées aux admins."""
    f = _parse_proto(payload)
    author = f.get(3, [b""])[0]
    text   = f.get(4, [b""])[0]
    if not isinstance(author, bytes) or not isinstance(text, bytes):
        return
    author = author.decode("utf-8", errors="replace").strip()
    text   = text.decode("utf-8", errors="replace").strip()
    if not text:
        return
    c = _get_client(server_id)
    if author.startswith(">>"):
        _chat_add(c, server_id, author.lstrip("> ").strip() or "Server", text, "server")
        return
    if text.startswith("\\"):
        return   # commande d'un joueur (\admin <mot de passe>…) : jamais dans l'historique public
    _chat_add(c, server_id, author, text, "player")


def _flush_pending_chat(server_id: int) -> None:
    """Renvoie, juste après une reconnexion, les messages qui n'avaient pas pu partir
    (au plus 2 minutes de retard ; au-delà, ils n'ont plus de sens dans le tchat)."""
    c = _get_client(server_id)
    while c["pending_chat"]:
        text, queued_at = c["pending_chat"].popleft()
        if time.time() - queued_at <= 120:
            send_chat(text, server_id, queue=False)


def send_chat(text: str, server_id: int = 1, queue: bool = True) -> bool:
    """Envoie un message dans le tchat du jeu. Retourne True si envoyé (ou mis en attente).

    Les commandes serveur (préfixe « \\ », ex. \\admin, \\kick) ne sont jamais
    journalisées en clair ni ajoutées à l'historique de chat : ce dernier est
    exposé publiquement via /api/live/chat-history, et \\admin contient le mot
    de passe admin du serveur de jeu. Elles ne sont jamais mises en attente non plus.

    Un message ordinaire envoyé pendant une reconnexion du bot est mis en attente et
    part dès la connexion suivante (queue=False pour l'interdire)."""
    c = _get_client(server_id)
    is_command = text.lstrip().startswith("\\")
    if not is_command:
        text = sanitize_game_text(text)
        if not text:
            return False
    with c["lock"]:
        sock = c["sock"]
    if sock is None:
        if queue and not is_command:
            c["pending_chat"].append((text, time.time()))
            log.info("ace_tcp_client: bot déconnecté, message mis en attente : %r", text)
            return True
        return False
    try:
        sock.sendall(_build_chat(text))
        _logged = "\\admin ***" if text.lstrip().lower().startswith("\\admin") else text
        log.info("ace_tcp_client: chat envoyé : %r", _logged)
        sent = True
    except Exception as e:
        log.warning("ace_tcp_client: erreur envoi chat : %s", e)
        sent = False
    if sent and not is_command:
        _chat_add(c, server_id, "Panel", text, "panel")
    return sent


def get_chat_history(server_id: int = 1, include_server: bool = False) -> list:
    """Historique récent du tchat (joueurs + panel), du plus ancien au plus récent. Les réponses
    du serveur aux commandes admin (source « server ») ne sont incluses que pour un admin."""
    c = _get_client(server_id)
    _load_chat_history(c, server_id)
    with c["lb_lock"]:
        msgs = list(c["chat_buffer"])
    return [{k: v for k, v in m.items() if k != "t"} for m in msgs
            if include_server or m["source"] != "server"]


def is_connected(server_id: int = 1) -> bool:
    c = _get_client(server_id)
    with c["lock"]:
        return c["connected"]


def update_server_name(server_id: int, name: str) -> None:
    """Met à jour le nom affiché dans les notifications Discord d'un serveur déjà
    en cours d'exécution, sans attendre son prochain redémarrage (c["server_name"]
    n'est sinon fixé qu'une fois, au lancement — voir start())."""
    c = _get_client(server_id)
    with c["lb_lock"]:
        c["server_name"] = name


def get_leaderboard(server_id: int = 1) -> list[dict]:
    c = _get_client(server_id)
    with c["lb_lock"]:
        return list(c["leaderboard"].values())


def update_driver_info(steam_id: str, name: str | None = None,
                       num: str | None = None, server_id: int = 1):
    """Met à jour les infos d'un pilote (nom/numéro) depuis les logs."""
    c = _get_client(server_id)
    with c["lb_lock"]:
        entry = c["leaderboard"].setdefault(steam_id, {'steam_id': steam_id})
        if name:
            entry['name'] = name
        if num:
            entry['num'] = num


# ── Message de bienvenue automatique ─────────────────────────────────────────

_RE_DRIVER_LOG = re.compile(
    r'^\[[^\]]*\] \[server\] \[info\] Car \[[^\]]+\] #(\d+) for driver (.+?) \[(\d+)\]'
)
_RE_CONNECT_LOG = re.compile(
    r'^\[[^\]]*\] \[gameplay\] \[info\] (\d+) connected \([^)]+\) on car ([^,\s]+)'
    r'(?:, with new carId ([0-9a-f-]+))?'
)
_RE_DISCONN_LOG = re.compile(r'^\[[^\]]*\] \[gameplay\] \[info\] (\d+) [Dd]isconnected')
_RE_DISCONN_CAR_LOG = re.compile(r'^\[[^\]]*\] \[gameplay\] \[info\] Disconnected carId ([0-9a-f-]+)')
_RE_NEWLAP_LOG  = re.compile(r'^\[[^\]]*\] \[gameplay\] \[info\] New lap carId ([0-9a-f-]+): (\d+:\d+\.\d+)')
# Le préfixe "[TimelineMessage] " est apparu avec la mise à jour 0.9.0 du serveur
# (build 0.8.1 -> 0.9.0) — optionnel pour rester compatible avec les deux formats.
_RE_SECTOR_LOG  = re.compile(r'^\[[^\]]*\] \[gameplay\] \[info\] (?:\[TimelineMessage\] )?Split completed for car ([0-9a-f-]+): \((\d+) ms, splitindex (\d+)\)')
_RE_LAP_INVALID = re.compile(r'^\[[^\]]*\] \[gameplay\] \[error\] Couldn\'t create lap from opensplits \(carId ([0-9a-f-]+)\)')
_RE_PLAYERS_LOG = re.compile(r'^\[[^\]]*\] \[server\] \[info\] Server updated: (\d+) players')
_RE_CHAT_LOG    = re.compile(r'^\[[^\]]*\] \[server\] \[info\] Chat from (.+?) \[(\d+)\]: (.+)')
# Le serveur refuse une version de protocole qui n'est pas la sienne et l'écrit dans son journal
# (« Network Version Mismatch. Current: (Server:6, Protocol:8), Requested: … ») : le bot reprend
# ces valeurs à la connexion suivante, sans attendre une version du panel (mise à jour du jeu).
_RE_VERSION_MISMATCH = re.compile(r'^\[[^\]]*\] \[[a-z]+\] \[[a-z]+\] Network Version Mismatch\. Current: \(Server:(\d+), Protocol:(\d+)\)')


def _get_active_config_name(server_id: int = 1) -> tuple[str, str]:
    """Retourne (configs_dir, config_filename) de la config réellement déployée pour ce
    serveur — lue depuis l'état du process manager (le nom de la config effectivement
    lancée), dans le sous-dossier server-{id}/ où deploy_config() écrit la copie propre
    à ce serveur.

    Auparavant, cette fonction lisait un marqueur .active_config à la racine de
    CONFIGS_DIR (dossier commun à tous les serveurs, pas le sous-dossier par serveur) —
    ce fichier n'était jamais écrit nulle part dans le code, donc le fallback ("premier
    .json par ordre alphabétique") était systématiquement utilisé, sans rapport avec la
    session réellement en cours ni avec server_id. Corrigé : v1.9.4."""
    from app.services.process_manager import _read_state
    configs_dir = os.path.join(os.environ.get("CONFIGS_DIR", "/aceserver/configs"), f"server-{server_id}")
    state = _read_state(server_id)
    name = state.get("config", "") if state else ""
    if name and os.path.exists(os.path.join(configs_dir, name)):
        return configs_dir, name
    files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
    name = os.path.basename(files[0]) if files else ""
    return configs_dir, name


def _read_active_config(server_id: int = 1) -> dict | None:
    """Lit et parse la config active une seule fois (partagée par _get_car_model et
    _get_admin_password pour éviter de relire le même fichier deux fois par tentative
    de connexion)."""
    try:
        configs_dir, name = _get_active_config_name(server_id)
        if not name:
            return None
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            return json.load(f) | {"__name__": name}
    except Exception as e:
        log.debug("ace_tcp_client: erreur lecture config active (server=%d): %s", server_id, e)
        return None


def _get_car_model(c: dict, cfg: dict | None = None) -> str:
    """Lit la première voiture SÉLECTIONNÉE de la config active — le bot doit se connecter
    avec un modèle réellement autorisé par la session, sinon ACE EVO rejette la connexion
    ("incorrect car or parts"). cars[0] n'est qu'un ordre de liste, pas une sélection.
    Fallback sur cars[0] si aucune n'est sélectionnée, puis sur c['car_model']."""
    if cfg is None:
        cfg = _read_active_config()
    if not cfg:
        return c["car_model"]
    cars = cfg.get("Event", {}).get("Cars", [])
    if cars:
        selected = next((car for car in cars if car.get("is_selected") or car.get("IsSelected")), None)
        car = selected or cars[0]
        model = car.get("name", "")
        if model:
            log.info("ace_tcp_client: car_model auto-détecté depuis '%s': %s%s",
                     cfg.get("__name__", "?"), model,
                     "" if selected else " (aucune voiture sélectionnée, fallback sur la 1ère de la liste)")
            return model
    return c["car_model"]


def _get_admin_password(cfg: dict | None = None) -> str:
    """Lit le mot de passe admin en temps réel depuis l'env et la config active."""
    if os.environ.get("ACE_BOT_IS_ADMIN", "false").lower() != "true":
        return ""
    if cfg is None:
        cfg = _read_active_config()
    if not cfg:
        return ""
    return cfg.get("Server", {}).get("AdminPassword", "")


def _send_welcome(name: str, server_id: int):
    c    = _get_client(server_id)
    # Laisser au joueur le temps de charger et de sortir des menus : envoyé trop tôt,
    # l'accueil défile avant qu'il ait le tchat sous les yeux (réglage ACE_BOT_WELCOME_DELAY).
    time.sleep(max(0, c["welcome_delay"]))
    _fmt = {"name": name, "discord_url": c["welcome_discord"], "site_url": c["welcome_site"]}
    if c["msg_welcome"]:
        send_chat(c["msg_welcome"].format_map(_fmt), server_id)
    if c["welcome_discord"] and c["msg_discord"]:
        time.sleep(1)
        send_chat(c["msg_discord"].format_map(_fmt), server_id)
    if c["welcome_site"] and c["msg_site"]:
        time.sleep(1)
        send_chat(c["msg_site"].format_map(_fmt), server_id)
    log.info("ace_tcp_client: bienvenue envoyé à %s (server=%d)", name, server_id)


def _parse_lap_ms(s: str) -> int:
    try:
        parts = s.split(':')
        rest  = parts[1].split('.')
        return int(parts[0]) * 60000 + int(rest[0]) * 1000 + (int(rest[1]) if len(rest) > 1 else 0)
    except Exception:
        return 0


def get_driver_by_num(num: str, server_id: int = 1) -> dict:
    """Retourne {name, steam_id, car_raw} du pilote par numéro de voiture, ou {}."""
    c = _get_client(server_id)
    with c["lb_lock"]:
        sid = c["num_to_sid"].get(str(num))
        if not sid:
            return {}
        return {
            "name":     c["leaderboard"].get(sid, {}).get("name", "?"),
            "steam_id": sid,
            "car_raw":  c["sid_car_raw"].get(sid, ""),
        }


def _on_connect_log(m, c, seen, server_id):
    """Seule ligne qui porte réellement la voiture (groupe 2) — c'est ici, pas
    dans _on_driver_log, que doivent partir les notifications Discord
    "arrivée"/"changement de véhicule" : la ligne "Car [...] for driver" arrive
    en pratique 10-20s AVANT cette ligne (constaté sur des logs réels), donc à
    ce moment-là la voiture n'existe encore nulle part, même pas dans un
    rescan large des logs — aucun repli ne peut trouver une donnée qui n'a pas
    encore été écrite."""
    sid, car_raw, car_id = m.group(1), m.group(2), m.group(3) or ""
    now = time.time()
    with c["lb_lock"]:
        c["join_times"][sid]  = now
        c["sid_car_raw"][sid] = car_raw
        if car_id:
            c["car_id_to_sid"][car_id] = sid
        name = c["leaderboard"].get(sid, {}).get("name", sid)
        num  = c["leaderboard"].get(sid, {}).get("num", "")
        recent = c["recently_disconnected"].pop(sid, None)
        # Fallback par nom : couvre les serveurs qui tournent les steam_ids à chaque connexion
        if recent is None:
            stale_sid = next(
                (k for k, v in c["recently_disconnected"].items()
                 if v.get("name") == name and (now - v["ts"]) < 600),
                None,
            )
            if stale_sid:
                recent = c["recently_disconnected"].pop(stale_sid, None)
        stale = [k for k, v in c["recently_disconnected"].items() if now - v["ts"] > 600]
        if stale:
            for k in stale:
                c["recently_disconnected"].pop(k, None)

    vehicle_changed = (
        recent is not None
        and recent["car_raw"]
        and car_raw
        and recent["car_raw"] != car_raw
        and (now - recent["ts"]) < 600
    )

    _srv_name = c.get("server_name", "")
    if vehicle_changed:
        seen.add(sid)
        threading.Thread(target=_send_welcome, args=(name, server_id), daemon=True).start()
        try:
            from app.services import discord_notifier
            discord_notifier.safe_notify(
                discord_notifier.notify_vehicle_change,
                name, num, recent["car_raw"], car_raw,
                server_id=server_id, server_name=_srv_name,
            )
        except Exception:
            pass
    elif sid not in seen:
        seen.add(sid)
        threading.Thread(target=_send_welcome, args=(name, server_id), daemon=True).start()
        try:
            from app.services import discord_notifier
            discord_notifier.safe_notify(
                discord_notifier.notify_player_join, name, num, car_raw, sid,
                server_id=server_id, server_name=_srv_name, online=len(seen),
            )
        except Exception:
            pass


def _on_driver_log(m, c, seen, server_id):
    """Alimente uniquement le nom/numéro du pilote (leaderboard, num_to_sid) —
    les notifications Discord se décident dans _on_connect_log, seul endroit
    qui a la voiture de façon fiable (voir sa docstring)."""
    num, name, sid = m.group(1), m.group(2), m.group(3)
    with c["lb_lock"]:
        c["num_to_sid"][num] = sid
        entry = c["leaderboard"].setdefault(sid, {"steam_id": sid})
        entry["name"] = name
        entry["num"]  = num


def _disconnect_sid(sid, c, seen, server_id):
    seen.discard(sid)
    with c["lb_lock"]:
        joined  = c["join_times"].pop(sid, None)
        old_car = c["sid_car_raw"].pop(sid, "")
        name    = c["leaderboard"].get(sid, {}).get("name", sid)
        num     = c["leaderboard"].get(sid, {}).get("num")
        if num:
            c["num_to_sid"].pop(str(num), None)
        # Mémorise pour détecter un éventuel changement de véhicule à la reconnexion
        c["recently_disconnected"][sid] = {"name": name, "car_raw": old_car, "ts": time.time()}
    duration_s = int(time.time() - joined) if joined else None
    try:
        from app.services import discord_notifier
        discord_notifier.safe_notify(
            discord_notifier.notify_player_disconnect, name, sid, duration_s,
            server_id=server_id, server_name=c.get("server_name", ""), online=len(seen),
        )
    except Exception:
        pass


def _on_disconn_log(m, c, seen, server_id):
    """Ancien format : '<steamid> disconnected'."""
    _disconnect_sid(m.group(1), c, seen, server_id)


def _on_disconn_car_log(m, c, seen, server_id):
    """Format apparu en 0.9.0 : 'Disconnected carId <carId>', sans le steamid — on le
    retrouve via car_id_to_sid (rempli à la connexion, voir _on_connect_log)."""
    car_id = m.group(1)
    with c["lb_lock"]:
        sid = c["car_id_to_sid"].get(car_id, "")
    if sid:
        _disconnect_sid(sid, c, seen, server_id)


def _on_sector_log(m, c):
    car_id, split_ms, idx = m.group(1), int(m.group(2)), int(m.group(3))
    with c["lb_lock"]:
        c["car_splits"].setdefault(car_id, []).append({"idx": idx, "ms": split_ms})


def _pop_car_sectors(c, car_id: str, lap_ms: int) -> tuple[int | None, int | None, int | None]:
    """Calcule s1/s2/s3 depuis les splits accumulés pour ce car_id depuis le
    dernier tour, puis vide la liste (même formule que live_state._car_laps)."""
    with c["lb_lock"]:
        splits = c["car_splits"].pop(car_id, [])
    s1 = next((s["ms"] for s in splits if s["idx"] == 0), None)
    s2 = next((s["ms"] for s in splits if s["idx"] == 1), None)
    s3 = (lap_ms - s1 - s2) if (s1 is not None and s2 is not None) else None
    return s1, s2, s3


def _on_newlap_log(m, c, server_id):
    car_id, lap_str = m.group(1), m.group(2)
    lap_ms = _parse_lap_ms(lap_str)
    if lap_ms <= 0:
        return
    notify = False
    with c["lb_lock"]:
        sid     = c["car_id_to_sid"].get(car_id, "")
        name    = c["leaderboard"].get(sid, {}).get("name", "?") if sid else "?"
        car_raw = c["sid_car_raw"].get(sid, "") if sid else ""
        best    = c["race_state"]["server_best_ms"]
        if best is None or lap_ms < best:
            c["race_state"]["server_best_ms"] = lap_ms
            notify = True

    # Repli : car_id_to_sid/sid_car_raw ne sont remplis qu'aux lignes "connected"/
    # "for driver", vues une seule fois par connexion TCP. Un pilote déjà connecté
    # avant un (re)démarrage du panel n'émet plus jamais ces lignes tant qu'il ne
    # se reconnecte pas — sid ET voiture peuvent alors manquer (pas seulement la
    # voiture). On reconstruit tout depuis live_state, qui rescane une fenêtre de
    # logs plus large que le suivi incrémental et retrouve donc pilote + voiture
    # même dans ce cas, via le car_id (stable, présent dans les deux mécanismes).
    if (not sid or not car_raw) and _flask_app is not None:
        try:
            with _flask_app.app_context():
                from app.services.live_state import build_state_cached
                state = build_state_cached(server_id)
            found = next((d for d in state.get("drivers", []) if d.get("car_id") == car_id), None)
            if found:
                if not sid:
                    sid  = found.get("steam_id", "")
                    name = found.get("name") or "?"
                if not car_raw:
                    car_raw = found.get("car_raw", "")
                if sid:
                    with c["lb_lock"]:
                        c["car_id_to_sid"][car_id] = sid
                        c["sid_car_raw"][sid] = car_raw
                        c["leaderboard"].setdefault(sid, {"steam_id": sid}).setdefault("name", name)
        except Exception:
            log.debug("newlap: repli sid/car_raw via live_state impossible (server=%s, car_id=%s)", server_id, car_id)

    s1, s2, s3 = _pop_car_sectors(c, car_id, lap_ms)
    if notify:
        cache = _refresh_track_cache(c, server_id)
        try:
            from app.services import discord_notifier
            discord_notifier.safe_notify(
                discord_notifier.notify_best_lap, name, lap_str, car_raw, cache.get("circuit", ""),
                server_id=server_id, server_name=c.get("server_name", ""),
                lap_ms=lap_ms, record=_server_record(server_id, cache.get("track_value", "")),
            )
        except Exception:
            pass
    if sid:
        _record_lap(c, server_id, sid, name, car_raw, lap_ms, s1, s2, s3)


def _refresh_track_cache(c, server_id):
    """Rafraîchit (au plus une fois par minute) le circuit/session courants —
    partagé entre _record_lap (persistance) et la notification Discord de
    meilleur tour (nom du circuit)."""
    if _flask_app is None:
        return c["track_cache"]
    cache = c["track_cache"]
    now = time.time()
    if now - cache["fetched_at"] > 60:
        try:
            with _flask_app.app_context():
                from app.services.server_config import get_running_server_info
                info = get_running_server_info(server_id) or {}
            cache["track_value"]   = info.get("track_value", "")
            cache["session_type"]  = info.get("current_session_label", "")
            cache["circuit"]       = info.get("circuit", "")
            cache["fetched_at"]    = now
        except Exception:
            log.exception("Échec rafraîchissement track_cache (server_id=%s)", server_id)
    return cache


def _server_record(server_id, track_value):
    """Record du serveur sur ce tracé avant le tour en cours : (ms, pseudo, voiture) ou None.
    Appelé avant _record_lap, donc sans le tour qu'on annonce."""
    if _flask_app is None or not track_value:
        return None
    try:
        with _flask_app.app_context():
            from app.models import LapRecord
            rec = (LapRecord.query.filter_by(server_id=server_id, track_value=track_value)
                   .order_by(LapRecord.lap_time_ms.asc()).first())
            return (rec.lap_time_ms, rec.nickname, rec.car) if rec else None
    except Exception:
        log.debug("record serveur illisible (server_id=%s)", server_id)
        return None


def _record_lap(c, server_id, sid, name, car_raw, lap_ms, s1_ms=None, s2_ms=None, s3_ms=None):
    """Persiste un tour en DB, indépendamment de toute fin de session (v1.9.4)."""
    if _flask_app is None:
        return
    cache = _refresh_track_cache(c, server_id)
    try:
        with _flask_app.app_context():
            from app.services.database import db
            from app.models import LapRecord
            db.session.add(LapRecord(
                server_id=server_id, steam_id=sid, nickname=name, car=car_raw,
                track_value=cache["track_value"], session_type=cache["session_type"],
                lap_time_ms=lap_ms,
                sector1_ms=s1_ms, sector2_ms=s2_ms, sector3_ms=s3_ms,
            ))
            db.session.commit()
    except Exception:
        log.exception("Échec persistance LapRecord (server_id=%s, sid=%s)", server_id, sid)


def _on_lap_invalid(m, c):
    car_id = m.group(1)
    with c["lb_lock"]:
        sid = c["car_id_to_sid"].get(car_id, "")
        if sid and sid in c["leaderboard"]:
            c["leaderboard"][sid]["lap_invalid"] = True


def _on_chat_log(m, line, c, server_id: int = 1):
    """Tchat lu dans le journal du serveur (formats d'avant 0.9.0) ; la voie normale est
    désormais le TCP (_on_chat_tcp), les doublons entre les deux sont écartés par _chat_add."""
    ts_m = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    ts   = ts_m.group(1)[11:] if ts_m else ""
    if m.group(3).lstrip().startswith("\\"):
        return   # commande serveur (\admin <mot de passe>…) : jamais dans l'historique public, comme send_chat
    _chat_add(c, server_id, m.group(1), m.group(3), "player", ts)


def _on_session_reset(c, seen):
    with c["lb_lock"]:
        c["car_id_to_sid"].clear()
        c["num_to_sid"].clear()
        c["sid_car_raw"].clear()
        c["join_times"].clear()
        c["recently_disconnected"].clear()
        c["car_splits"].clear()
        c["race_state"]["server_best_ms"] = None
    seen.clear()


_CONTACTS_WINDOW_S = 60     # un message Discord par minute au plus, même dans une mêlée


def _contacts_enabled() -> bool:
    return (os.environ.get("LIVE_COLLISIONS", "false").lower() == "true"
            and os.environ.get("DISCORD_NOTIFY_CONTACTS", "false").lower() == "true")


def _flush_contacts(c, server_id, force: bool = False):
    """Envoie les contacts avec dégâts accumulés depuis une minute (ou tout de suite si force)."""
    buf = c["contacts_buffer"]
    if not buf or (not force and time.time() - c["contacts_since"] < _CONTACTS_WINDOW_S):
        return
    c["contacts_buffer"] = []
    try:
        from app.services import discord_notifier
        discord_notifier.safe_notify(discord_notifier.notify_contacts, buf,
                                     server_id=server_id, server_name=c.get("server_name", ""))
    except Exception:
        pass


def _on_contact_line(line: str, c, server_id) -> bool:
    """Lignes « Car … for driver » et « Collision between … » (journal gameplay en debug).
    Retourne True si la ligne est une collision (rien d'autre à en tirer)."""
    from app.services import collisions
    ev = collisions.parse_line(line)
    if ev is None:
        return False
    if c["contacts"] is None:
        c["contacts"] = collisions.new_state()
    ts = line[1:24] if line.startswith("[") else ""
    from app.services.session_tracker import log_epoch
    new = collisions.apply_event(c["contacts"], ev, ts, log_epoch(ts))
    if new and new["damage"] and _contacts_enabled():
        if not c["contacts_buffer"]:
            c["contacts_since"] = time.time()
        c["contacts_buffer"].append({k: new[k] for k in ("driver", "other", "collider", "lap")})
    return ev["type"] == "collision"


def _process_log_line(line: str, seen: set, server_id: int):
    c = _get_client(server_id)
    _flush_contacts(c, server_id)
    if "Collision between" in line or " for driver " in line:
        if _on_contact_line(line, c, server_id):
            return

    m = _RE_CONNECT_LOG.search(line)
    if m:
        _on_connect_log(m, c, seen, server_id)
        return

    m = _RE_DRIVER_LOG.search(line)
    if m:
        _on_driver_log(m, c, seen, server_id)
        return

    m = _RE_DISCONN_LOG.search(line)
    if m:
        _on_disconn_log(m, c, seen, server_id)
        return

    m = _RE_DISCONN_CAR_LOG.search(line)
    if m:
        _on_disconn_car_log(m, c, seen, server_id)
        return

    m = _RE_SECTOR_LOG.search(line)
    if m:
        _on_sector_log(m, c)
        return

    m = _RE_NEWLAP_LOG.search(line)
    if m:
        if c["contacts"] is not None:
            from app.services import collisions
            collisions.note_lap(c["contacts"], m.group(1))
        _on_newlap_log(m, c, server_id)
        return

    m = _RE_LAP_INVALID.search(line)
    if m:
        _on_lap_invalid(m, c)
        return

    m = _RE_CHAT_LOG.search(line)
    if m:
        _on_chat_log(m, line, c, server_id)
        return

    m = _RE_PLAYERS_LOG.search(line)
    if m and m.group(1) == '0':
        _flush_contacts(c, server_id, force=True)
        c["contacts"] = None
        _on_session_reset(c, seen)
        return

    m = _RE_VERSION_MISMATCH.search(line)
    if m:
        _on_version_mismatch(m, c)


def _on_version_mismatch(m, c: dict):
    server_v, proto_v = int(m.group(1)), int(m.group(2))
    if (c.get("server_version", 6), c.get("protocol_version", 8)) != (server_v, proto_v):
        log.warning("Serveur de jeu : version réseau Server:%d Protocol:%d (le bot envoyait Server:%d Protocol:%d) — reprise à la prochaine connexion",
                    server_v, proto_v, c.get("server_version", 6), c.get("protocol_version", 8))
        c["server_version"], c["protocol_version"] = server_v, proto_v


def _log_tail_native(server_id: int):
    c    = _get_client(server_id)
    seen: set[str] = set()
    while c["running"]:
        try:
            with open(c["log_file"], encoding='utf-8', errors='replace') as f:
                f.seek(0, 2)
                while c["running"]:
                    line = f.readline()
                    if line:
                        _process_log_line(line, seen, server_id)
                    else:
                        time.sleep(0.3)
        except Exception as e:
            log.debug("log_tail_native error: %s", e)
            time.sleep(5)


def _log_tail_docker(server_id: int):
    c    = _get_client(server_id)
    seen: set[str] = set()
    import docker as _docker
    _client_cache = None
    while c["running"]:
        try:
            if _client_cache is None:
                # timeout borné : évite que le thread reste bloqué indéfiniment sur le socket
                # de logs Docker après un stop() si aucune nouvelle ligne n'arrive
                _client_cache = _docker.from_env(timeout=30)
            container = _client_cache.containers.get(c["container_name"])
            for chunk in container.logs(stream=True, follow=True,
                                        since=int(time.time()) - 5):
                if not c["running"]:
                    break
                for line in chunk.decode('utf-8', errors='replace').splitlines():
                    _process_log_line(line, seen, server_id)
        except Exception as e:
            _client_cache = None
            log.debug("log_tail_docker error: %s", e)
            if c["running"]:
                time.sleep(5)


# ── API publique ──────────────────────────────────────────────────────────────

def start(host: str, port: int, steam_id: str,
          car_model: str      = "preset_190_evo_ii",
          discord_url: str    = "",
          site_url: str       = "",
          msg_welcome: str    = DEFAULT_BOT_MSG_WELCOME,
          msg_discord: str    = DEFAULT_BOT_MSG_DISCORD,
          msg_site: str       = DEFAULT_BOT_MSG_SITE,
          deploy_mode: str    = "native",
          log_file: str       = "",
          container_name: str = "ace-server",
          on_event=None,
          server_id: int      = 1,
          server_name: str    = "",
          bot_name: str       = "",
          welcome_delay: int  = DEFAULT_BOT_WELCOME_DELAY):
    """Démarre le client TCP (+ tail de logs : tours, chat, connexions, bienvenue) en arrière-plan."""
    c = _get_client(server_id)
    c["host"]            = host
    c["port"]            = port
    c["steam_id"]        = steam_id
    c["car_model"]       = car_model
    c["server_name"]     = server_name
    c["welcome_discord"] = discord_url
    c["welcome_site"]    = site_url
    c["msg_welcome"]     = msg_welcome
    c["msg_discord"]     = msg_discord
    c["msg_site"]        = msg_site
    c["deploy_mode"]     = deploy_mode
    c["log_file"]        = log_file
    c["container_name"]  = container_name
    c["on_event"]        = on_event
    c["bot_name"]        = bot_name.strip()[:40]
    c["welcome_delay"]   = welcome_delay
    c["running"]         = True

    threading.Thread(target=_connect_loop, args=(server_id,),
                     daemon=True, name=f"ace-tcp-client-{server_id}").start()

    # Ce thread lit en continu les logs du serveur de jeu : tours (LapRecord), chat,
    # connexions/déconnexions, et messages de bienvenue s'ils sont configurés. Il doit
    # tourner même sans message de bienvenue actif, sinon aucune de ces données n'est
    # jamais capturée (le chat et l'historique de tours restent vides indéfiniment).
    if deploy_mode == "docker_split":
        threading.Thread(target=_log_tail_docker, args=(server_id,),
                         daemon=True, name=f"ace-log-tail-{server_id}").start()
    elif log_file:
        threading.Thread(target=_log_tail_native, args=(server_id,),
                         daemon=True, name=f"ace-log-tail-{server_id}").start()

    log.info("ace_tcp_client: démarrage vers %s:%d (server=%d)", host, port, server_id)


def elevate_admin(server_id: int = 1) -> str | None:
    """Envoie \\admin <password> au serveur avec le mot de passe de la config active.
    Ignore ACE_BOT_IS_ADMIN — appelé explicitement par l'admin via le panel.
    Retourne None si ok, message d'erreur sinon.
    """
    c = _get_client(server_id)
    with c["lock"]:
        connected = c["connected"]
    if not connected:
        return "Bot TCP non connecté"
    try:
        configs_dir, name = _get_active_config_name(server_id)
        if not name:
            return "Aucune configuration active trouvée"
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            pwd = json.load(f).get("Server", {}).get("AdminPassword", "")
        if not pwd:
            return "Aucun mot de passe admin configuré dans la session active"
    except Exception as e:
        return f"Erreur lecture config : {e}"
    sent = send_chat(f"\\admin {pwd}", server_id)
    if not sent:
        return "Échec envoi — bot TCP non connecté"
    c["manual_admin"] = True
    log.info("ace_tcp_client: élévation admin manuelle envoyée (server=%d)", server_id)
    return None


def send_admin_command(text: str, server_id: int = 1) -> tuple[bool, str | None]:
    """Envoie une commande admin in-game (« \\kick 12 »…) en ré-élevant le bot juste avant.

    Pourquoi : le statut admin est perdu à chaque reconnexion du bot ; la ré-élévation juste
    avant la commande garantit qu'elle passe. TCP garde l'ordre : le serveur traite \\admin
    avant la commande.

    Retourne (envoyé, erreur). Sans mot de passe admin configuré, la commande part quand même
    (cas où le bot est déjà admin autrement) : le serveur tranchera."""
    if not is_connected(server_id):
        return False, "not_connected"
    err = elevate_admin(server_id)
    if err:
        log.info("ace_tcp_client: élévation avant commande impossible (%s), commande envoyée telle quelle", err)
    else:
        time.sleep(0.2)
    return send_chat(text, server_id), None


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def start_for_server(srv, cfg: dict):
    """Démarre le bot TCP pour un objet Server de la DB, si ACE_BOT_STEAM_ID est configuré."""
    steam_id = cfg.get("ACE_BOT_STEAM_ID", "")
    if not steam_id or _get_client(srv.id)["running"]:
        return
    from app.services.process_manager import _log_file, _DEPLOY_MODE
    # En mode docker_split, chaque container ACE EVO écoute sur son port interne 9700.
    # On rejoint le container par son nom (hostname Docker), pas par le port host-mappé.
    if _DEPLOY_MODE == "docker_split":
        tcp_host = srv.container_name
        tcp_port = 9700
    else:
        tcp_host = cfg.get("ACESERVER_TCP_HOST", "127.0.0.1")
        tcp_port = srv.tcp_port or cfg.get("ACESERVER_TCP_PORT", 9700)
    start(
        host           = tcp_host,
        port           = tcp_port,
        steam_id       = steam_id,
        car_model      = cfg.get("ACE_BOT_CAR_MODEL", "preset_190_evo_ii"),
        server_name    = srv.name,
        discord_url    = cfg.get("DISCORD_INVITE_URL", ""),
        site_url       = cfg.get("PANEL_URL", ""),
        msg_welcome    = cfg.get("ACE_BOT_MSG_WELCOME", DEFAULT_BOT_MSG_WELCOME),
        msg_discord    = cfg.get("ACE_BOT_MSG_DISCORD", DEFAULT_BOT_MSG_DISCORD),
        msg_site       = cfg.get("ACE_BOT_MSG_SITE",    DEFAULT_BOT_MSG_SITE),
        bot_name       = cfg.get("ACE_BOT_NAME", ""),
        welcome_delay  = _int_or(cfg.get("ACE_BOT_WELCOME_DELAY"), DEFAULT_BOT_WELCOME_DELAY),
        deploy_mode    = _DEPLOY_MODE,
        log_file       = str(_log_file(srv.id)),
        container_name = srv.container_name,
        server_id      = srv.id,
    )


def stop(server_id: int = 1):
    c = _get_client(server_id)
    c["running"] = False
    with c["lock"]:
        if c["sock"]:
            try:
                c["sock"].close()
            except Exception:
                pass
