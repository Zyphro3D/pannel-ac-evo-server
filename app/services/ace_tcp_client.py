"""
Client TCP pour le serveur ACE EVO (port 9700).
Protocole : [uint16_LE: total_len-2][0x00][0x02][uint8: name_len][name][protobuf_payload]

Messages pris en charge :
  C2S  ClientConnectionRequest  — handshake initial
  C2S  MultiplayerChatMessage   — envoi d'un message dans le tchat du jeu
  S2C  BroadcastStateMessage    — état courant (PlatformRaceLeaderboard, etc.)
  S2C  SplitFromRemoteMessage   — passage de secteur
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

from config import DEFAULT_BOT_MSG_WELCOME, DEFAULT_BOT_MSG_DISCORD, DEFAULT_BOT_MSG_SITE

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
                "recently_disconnected": {},
                "race_state":            {"server_best_ms": None},
                "chat_buffer":           collections.deque(maxlen=50),
                "welcome_discord":       "",
                "welcome_site":          "",
                "deploy_mode":           "native",
                "log_file":              "",
                "container_name":        "ace-server",
                "msg_welcome":           DEFAULT_BOT_MSG_WELCOME,
                "msg_discord":           DEFAULT_BOT_MSG_DISCORD,
                "msg_site":              DEFAULT_BOT_MSG_SITE,
                "track_cache":           {"track_value": "", "session_type": "", "fetched_at": 0.0},
                "manual_admin":          False,
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
        _field_varint(5, 8) +   # protocol version — inchangé depuis le build 23658359
        _field_varint(6, 6) +   # server version — bump 5→6 avec le build ACE EVO Server 24104623,
                                 # sinon rejet "ConnectToServerResult_ClientOutdated"
        _field_str(7, c["steam_id"]) +
        _field_str(9, _get_car_model(c, cfg))
    )
    return _wrap('ClientConnectionRequest', payload)


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
    if name == 'BroadcastStateMessage':
        _parse_broadcast(payload, server_id)
    elif name == 'SplitFromRemoteMessage':
        _parse_split(payload, server_id)


# ── Boucle de réception ───────────────────────────────────────────────────────

def _recv_loop(sock: socket.socket, server_id: int, keepalive_payload: bytes | None = None):
    """Boucle de réception. ACE EVO Server déconnecte le bot après ~60s sans trafic reçu
    ("software timeout") — ce client minimal n'envoyant jamais rien après le handshake
    initial. En l'absence de tout message serveur pendant KEEPALIVE_S secondes, on
    renvoie la requête de connexion d'origine (message déjà accepté par le serveur,
    sans effet de bord visible côté jeu) pour faire office de heartbeat et éviter la
    coupure. Voir CHANGELOG v1.9.4."""
    c = _get_client(server_id)
    buf = b''
    KEEPALIVE_S = 20.0
    sock.settimeout(KEEPALIVE_S)
    while c["running"]:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 5:
                if len(buf) < 4:
                    break
                total_minus_2 = struct.unpack_from('<H', buf, 0)[0]
                marker        = struct.unpack_from('<H', buf, 2)[0]
                if marker != 0x0002:
                    buf = buf[1:]  # resync
                    continue
                total_len = total_minus_2 + 2
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
            if keepalive_payload is None:
                continue
            try:
                sock.sendall(keepalive_payload)
                log.debug("ace_tcp_client: keepalive envoyé (server=%d)", server_id)
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
            # S'élève admin dès la connexion si configuré (même config déjà lue ci-dessus),
            # ou si une élévation manuelle a déjà été demandée sur ce serveur — le serveur de
            # jeu déconnecte le bot toutes les ~60s ("software timeout", aucun keepalive
            # envoyé par ce client minimal), et chaque reconnexion repart sans droits admin :
            # sans ce re-envoi automatique, l'élévation manuelle ne "tenait" qu'une minute.
            _pwd = _get_admin_password(_active_cfg)
            if not _pwd and c.get("manual_admin") and _active_cfg:
                _pwd = _active_cfg.get("Server", {}).get("AdminPassword", "")
            if _pwd:
                time.sleep(1)
                send_chat(f"\\admin {_pwd}", server_id)
                log.info("ace_tcp_client: élévation admin envoyée (server=%d)%s", server_id,
                          " [ré-élévation manuelle après reconnexion]" if c.get("manual_admin") else "")
            _recv_loop(sock, server_id, keepalive_payload=_conn_req)
        except Exception as e:
            log.debug("ace_tcp_client: erreur connexion %s:%d — %s", c["host"], c["port"], e)
        finally:
            with c["lock"]:
                c["sock"]      = None
                c["connected"] = False
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        if c["running"]:
            time.sleep(5)


# ── API publique ──────────────────────────────────────────────────────────────

def send_chat(text: str, server_id: int = 1) -> bool:
    """Envoie un message dans le tchat du jeu. Retourne True si envoyé."""
    c = _get_client(server_id)
    with c["lock"]:
        sock = c["sock"]
    if sock is None:
        return False
    try:
        sock.sendall(_build_chat(text))
        log.info("ace_tcp_client: chat envoyé : %r", text)
        sent = True
    except Exception as e:
        log.warning("ace_tcp_client: erreur envoi chat : %s", e)
        sent = False
    if sent:
        ts = time.strftime("%H:%M:%S")
        with c["lb_lock"]:
            c["chat_buffer"].append({"author": "Panel", "text": text, "ts": ts, "source": "panel"})
    return sent


def get_chat_history(server_id: int = 1) -> list:
    """Retourne l'historique récent du chat (messages joueurs + panel)."""
    c = _get_client(server_id)
    with c["lb_lock"]:
        return list(c["chat_buffer"])


def is_connected(server_id: int = 1) -> bool:
    c = _get_client(server_id)
    with c["lock"]:
        return c["connected"]


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
    r'\[server\] \[info\] Car \[[^\]]+\] #(\d+) for driver (.+?) \[(\d+)\]'
)
_RE_CONNECT_LOG = re.compile(
    r'\[gameplay\] \[info\] (\d+) connected \([^)]+\) on car ([^,\s]+)'
    r'(?:, with new carId ([0-9a-f-]+))?'
)
_RE_DISCONN_LOG = re.compile(r'\[gameplay\] \[info\] (\d+) disconnected')
_RE_NEWLAP_LOG  = re.compile(r'\[gameplay\] \[info\] New lap carId ([0-9a-f-]+): (\d+:\d+\.\d+)')
_RE_LAP_INVALID = re.compile(r'\[gameplay\] \[error\] Couldn\'t create lap from opensplits \(carId ([0-9a-f-]+)\)')
_RE_PLAYERS_LOG = re.compile(r'\[server\] \[info\] Server updated: (\d+) players')
_RE_CHAT_LOG    = re.compile(r'\[server\] \[info\] Chat from (.+?) \[(\d+)\]: (.+)')


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
    time.sleep(2)   # laisser le temps au joueur de charger
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


def _on_connect_log(m, c, seen):
    sid, car_raw, car_id = m.group(1), m.group(2), m.group(3) or ""
    with c["lb_lock"]:
        c["join_times"][sid]  = time.time()
        c["sid_car_raw"][sid] = car_raw
        if car_id:
            c["car_id_to_sid"][car_id] = sid


def _on_driver_log(m, c, seen, server_id):
    num, name, sid = m.group(1), m.group(2), m.group(3)
    now = time.time()
    with c["lb_lock"]:
        c["num_to_sid"][num] = sid
        # Alimente le leaderboard avec le nom/numéro du pilote — sans ça, les notifications
        # Discord (meilleur tour, etc.) ne retrouvent pas le nom et affichent "?".
        entry = c["leaderboard"].setdefault(sid, {"steam_id": sid})
        entry["name"] = name
        entry["num"]  = num
        car_raw = c["sid_car_raw"].get(sid, "")
        recent  = c["recently_disconnected"].pop(sid, None)
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
                server_id=server_id, server_name=_srv_name,
            )
        except Exception:
            pass


def _on_disconn_log(m, c, seen, server_id):
    sid = m.group(1)
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
            server_id=server_id, server_name=c.get("server_name", ""),
        )
    except Exception:
        pass


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
    if notify:
        try:
            from app.services import discord_notifier
            discord_notifier.safe_notify(
                discord_notifier.notify_best_lap, name, lap_str, car_raw,
                server_id=server_id, server_name=c.get("server_name", ""),
            )
        except Exception:
            pass
    if sid:
        _record_lap(c, server_id, sid, name, car_raw, lap_ms)


def _record_lap(c, server_id, sid, name, car_raw, lap_ms):
    """Persiste un tour en DB, indépendamment de toute fin de session (v1.9.4)."""
    if _flask_app is None:
        return
    cache = c["track_cache"]
    now = time.time()
    if now - cache["fetched_at"] > 60:
        try:
            from app.services.server_config import get_running_server_info
            info = get_running_server_info(server_id) or {}
            cache["track_value"]   = info.get("track_value", "")
            cache["session_type"]  = info.get("current_session_label", "")
            cache["fetched_at"]    = now
        except Exception:
            log.exception("Échec rafraîchissement track_cache (server_id=%s)", server_id)
    try:
        with _flask_app.app_context():
            from app.services.database import db
            from app.models import LapRecord
            db.session.add(LapRecord(
                server_id=server_id, steam_id=sid, nickname=name, car=car_raw,
                track_value=cache["track_value"], session_type=cache["session_type"],
                lap_time_ms=lap_ms,
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


def _on_chat_log(m, line, c):
    ts_m = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    ts   = ts_m.group(1)[11:] if ts_m else ""
    with c["lb_lock"]:
        c["chat_buffer"].append({"author": m.group(1), "text": m.group(3), "ts": ts, "source": "player"})


def _on_session_reset(c, seen):
    with c["lb_lock"]:
        c["car_id_to_sid"].clear()
        c["num_to_sid"].clear()
        c["sid_car_raw"].clear()
        c["join_times"].clear()
        c["recently_disconnected"].clear()
        c["race_state"]["server_best_ms"] = None
    seen.clear()


def _process_log_line(line: str, seen: set, server_id: int):
    c = _get_client(server_id)

    m = _RE_CONNECT_LOG.search(line)
    if m:
        _on_connect_log(m, c, seen)
        return

    m = _RE_DRIVER_LOG.search(line)
    if m:
        _on_driver_log(m, c, seen, server_id)
        return

    m = _RE_DISCONN_LOG.search(line)
    if m:
        _on_disconn_log(m, c, seen, server_id)
        return

    m = _RE_NEWLAP_LOG.search(line)
    if m:
        _on_newlap_log(m, c, server_id)
        return

    m = _RE_LAP_INVALID.search(line)
    if m:
        _on_lap_invalid(m, c)
        return

    m = _RE_CHAT_LOG.search(line)
    if m:
        _on_chat_log(m, line, c)
        return

    m = _RE_PLAYERS_LOG.search(line)
    if m and m.group(1) == '0':
        _on_session_reset(c, seen)


def _welcome_loop_native(server_id: int):
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
            log.debug("welcome_loop_native error: %s", e)
            time.sleep(5)


def _welcome_loop_docker(server_id: int):
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
            log.debug("welcome_loop_docker error: %s", e)
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
          server_name: str    = ""):
    """Démarre le client TCP (+ moniteur de bienvenue) en arrière-plan."""
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
    c["running"]         = True

    threading.Thread(target=_connect_loop, args=(server_id,),
                     daemon=True, name=f"ace-tcp-client-{server_id}").start()

    has_welcome = msg_welcome or (discord_url and msg_discord) or (site_url and msg_site)
    if has_welcome:
        if deploy_mode == "docker_split":
            threading.Thread(target=_welcome_loop_docker, args=(server_id,),
                             daemon=True, name=f"ace-welcome-bot-{server_id}").start()
        elif log_file:
            threading.Thread(target=_welcome_loop_native, args=(server_id,),
                             daemon=True, name=f"ace-welcome-bot-{server_id}").start()

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
