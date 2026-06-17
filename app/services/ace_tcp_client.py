"""
Client TCP pour le serveur ACE EVO (port 9700).
Protocole : [uint16_LE: total_len-2][0x00][0x02][uint8: name_len][name][protobuf_payload]

Messages pris en charge :
  C2S  ClientConnectionRequest  — handshake initial
  C2S  MultiplayerChatMessage   — envoi d'un message dans le tchat du jeu
  S2C  BroadcastStateMessage    — état courant (PlatformRaceLeaderboard, etc.)
  S2C  SplitFromRemoteMessage   — passage de secteur
"""
import os
import re
import socket
import struct
import threading
import time
import logging

log = logging.getLogger(__name__)

# ── État global ────────────────────────────────────────────────────────────────

_host: str = "127.0.0.1"
_port: int = 9700
_steam_id: str = ""
_car_model: str = "preset_190_evo_ii"

_sock: socket.socket | None = None
_lock = threading.Lock()
_connected = False
_running   = False

# Leaderboard en mémoire : steam_id_str → {name, num, sector, time_ms, sectors}
_leaderboard: dict[str, dict] = {}
_lb_lock = threading.Lock()

# Callbacks externes (optionnels)
_on_event = None   # callable(dict) — appelé pour chaque événement parsé


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


def _build_connection_request() -> bytes:
    payload = (
        _field_varint(1, 1) +
        _field_varint(5, 8) +
        _field_varint(6, 5) +
        _field_str(7, _steam_id) +
        _field_str(9, _get_car_model())
    )
    return _wrap('ClientConnectionRequest', payload)


def _build_chat(text: str) -> bytes:
    ts_ns = int(time.time() * 1_000_000_000)
    payload = _field_varint(2, ts_ns) + _field_str(4, text)
    return _wrap('MultiplayerChatMessage', payload)


# ── Parsing des messages entrants ─────────────────────────────────────────────

def _parse_broadcast(payload: bytes):
    """BroadcastStateMessage → extrait PlatformRaceLeaderboard."""
    f = _parse_proto(payload)
    any_data = f.get(2, [None])[0]
    if not any_data:
        log.info("broadcast: pas de field 2 — fields=%s", list(f.keys()))
        return

    af = _parse_proto(any_data)
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
        with _lb_lock:
            for sid, data in updates.items():
                if sid in _leaderboard:
                    _leaderboard[sid].update(data)
                else:
                    _leaderboard[sid] = data

        if _on_event:
            try:
                _on_event({'type': 'leaderboard', 'entries': list(updates.values())})
            except Exception:
                pass


def _parse_split(payload: bytes):
    """SplitFromRemoteMessage — passage de secteur."""
    f = _parse_proto(payload)
    driver_id_bytes = f.get(1, [b''])[0]
    steam_id = _extract_steam_id(driver_id_bytes)
    sector_idx = (f.get(3, [0])[0])

    if _on_event:
        try:
            _on_event({'type': 'split_tcp', 'steam_id': steam_id, 'sector': sector_idx})
        except Exception:
            pass


def _handle_message(name: str, payload: bytes):
    if name == 'BroadcastStateMessage':
        _parse_broadcast(payload)
    elif name == 'SplitFromRemoteMessage':
        _parse_split(payload)


# ── Boucle de réception ───────────────────────────────────────────────────────

def _recv_loop(sock: socket.socket):
    buf = b''
    while _running:
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
                    _handle_message(name, payload)
                except Exception as e:
                    log.debug("handle_message %s error: %s", name, e)
        except OSError:
            break
    log.info("ace_tcp_client: connexion terminée")


# ── Thread de connexion avec reconnexion auto ─────────────────────────────────

def _connect_loop():
    global _sock, _connected
    while _running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((_host, _port))
            sock.settimeout(None)
            sock.sendall(_build_connection_request())
            log.info("ace_tcp_client: connecté à %s:%d (steam=%s)", _host, _port, _steam_id)
            with _lock:
                _sock = sock
                _connected = True
            # S'élever admin dès la connexion si configuré
            _pwd = _get_admin_password()
            if _pwd:
                time.sleep(1)
                send_chat(f"\\admin {_pwd}")
                log.info("ace_tcp_client: élévation admin envoyée")
            _recv_loop(sock)
        except Exception as e:
            log.debug("ace_tcp_client: erreur connexion %s:%d — %s", _host, _port, e)
        finally:
            with _lock:
                _sock = None
                _connected = False
            try:
                sock.close()
            except Exception:
                pass
        if _running:
            time.sleep(5)


# ── API publique ──────────────────────────────────────────────────────────────

def send_chat(text: str) -> bool:
    """Envoie un message dans le tchat du jeu. Retourne True si envoyé."""
    with _lock:
        if _sock is None:
            return False
        try:
            _sock.sendall(_build_chat(text))
            log.info("ace_tcp_client: chat envoyé : %r", text)
            return True
        except Exception as e:
            log.warning("ace_tcp_client: erreur envoi chat : %s", e)
            return False


def is_connected() -> bool:
    return _connected


def get_leaderboard() -> list[dict]:
    with _lb_lock:
        return list(_leaderboard.values())


def update_driver_info(steam_id: str, name: str | None = None, num: str | None = None):
    """Met à jour les infos d'un pilote (nom/numéro) depuis les logs."""
    with _lb_lock:
        entry = _leaderboard.setdefault(steam_id, {'steam_id': steam_id})
        if name:
            entry['name'] = name
        if num:
            entry['num'] = num


# ── Message de bienvenue automatique ─────────────────────────────────────────

_RE_DRIVER_LOG = re.compile(
    r'\[server\] \[info\] Car \[[^\]]+\] #(\d+) for driver (.+?) \[(\d+)\]'
)

_welcome_discord: str = ""
_welcome_site: str    = ""
_deploy_mode: str     = "native"
_log_file: str        = ""
_container_name: str  = "ace-server"
_msg_welcome: str     = "Bienvenue {name} !"
_msg_discord: str     = "Rejoins le discord : {discord_url}"
_msg_site: str        = "Retrouve tes resultats et evenements sur : {site_url}"


def _get_car_model() -> str:
    """Lit la première voiture de la config active. Fallback sur _car_model si introuvable."""
    try:
        configs_dir = os.environ.get("CONFIGS_DIR", "/aceserver/configs")
        active_file = os.path.join(configs_dir, ".active_config")
        if os.path.exists(active_file):
            with open(active_file) as f:
                name = f.read().strip()
        else:
            import glob
            files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
            name = os.path.basename(files[0]) if files else ""
        if not name:
            return _car_model
        import json as _json
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            cfg = _json.load(f)
        cars = cfg.get("Event", {}).get("Cars", [])
        if cars:
            model = cars[0].get("name", "")
            if model:
                log.info("ace_tcp_client: car_model auto-détecté depuis '%s': %s", name, model)
                return model
    except Exception as e:
        log.debug("ace_tcp_client: erreur lecture car_model: %s", e)
    return _car_model


def _get_admin_password() -> str:
    """Lit le mot de passe admin en temps réel depuis l'env et la config active."""
    if os.environ.get("ACE_BOT_IS_ADMIN", "false").lower() != "true":
        return ""
    try:
        configs_dir = os.environ.get("CONFIGS_DIR", "/aceserver/configs")
        active_file = os.path.join(configs_dir, ".active_config")
        if os.path.exists(active_file):
            with open(active_file) as f:
                name = f.read().strip()
        else:
            import glob
            files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
            name = os.path.basename(files[0]) if files else ""
        if not name:
            return ""
        import json as _json
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            return _json.load(f).get("Server", {}).get("AdminPassword", "")
    except Exception:
        return ""


def _send_welcome(name: str):
    time.sleep(2)   # laisser le temps au joueur de charger
    vars = {"name": name, "discord_url": _welcome_discord, "site_url": _welcome_site}
    if _msg_welcome:
        send_chat(_msg_welcome.format_map(vars))
    if _welcome_discord and _msg_discord:
        time.sleep(1)
        send_chat(_msg_discord.format_map(vars))
    if _welcome_site and _msg_site:
        time.sleep(1)
        send_chat(_msg_site.format_map(vars))
    log.info("ace_tcp_client: bienvenue envoyé à %s", name)


def _process_log_line(line: str, seen: set):
    m = _RE_DRIVER_LOG.search(line)
    if m:
        steam_id = m.group(3)
        name     = m.group(2)
        if steam_id not in seen:
            seen.add(steam_id)
            threading.Thread(
                target=_send_welcome, args=(name,), daemon=True
            ).start()


def _welcome_loop_native():
    seen: set[str] = set()
    while _running:
        try:
            with open(_log_file, encoding='utf-8', errors='replace') as f:
                f.seek(0, 2)
                while _running:
                    line = f.readline()
                    if line:
                        _process_log_line(line, seen)
                    else:
                        time.sleep(0.3)
        except Exception as e:
            log.debug("welcome_loop_native error: %s", e)
            time.sleep(5)


def _welcome_loop_docker():
    seen: set[str] = set()
    while _running:
        try:
            import docker as _docker
            client    = _docker.from_env()
            container = client.containers.get(_container_name)
            for chunk in container.logs(stream=True, follow=True,
                                        since=int(time.time()) - 5):
                if not _running:
                    break
                for line in chunk.decode('utf-8', errors='replace').splitlines():
                    _process_log_line(line, seen)
        except Exception as e:
            log.debug("welcome_loop_docker error: %s", e)
            if _running:
                time.sleep(5)


# ── API publique ──────────────────────────────────────────────────────────────

def start(host: str, port: int, steam_id: str,
          car_model: str   = "preset_190_evo_ii",
          discord_url: str = "",
          site_url: str       = "",
          msg_welcome: str    = "Bienvenue {name} !",
          msg_discord: str    = "Rejoins le discord : {discord_url}",
          msg_site: str       = "Retrouve tes resultats et evenements sur : {site_url}",
          deploy_mode: str    = "native",
          log_file: str       = "",
          container_name: str = "ace-server",
          on_event=None):
    """Démarre le client TCP (+ moniteur de bienvenue) en arrière-plan."""
    global _host, _port, _steam_id, _car_model
    global _on_event, _running
    global _welcome_discord, _welcome_site, _deploy_mode, _log_file, _container_name
    global _msg_welcome, _msg_discord, _msg_site
    _host            = host
    _port            = port
    _steam_id        = steam_id
    _car_model       = car_model
    _welcome_discord = discord_url
    _welcome_site     = site_url
    _msg_welcome      = msg_welcome
    _msg_discord      = msg_discord
    _msg_site         = msg_site
    _deploy_mode      = deploy_mode
    _log_file         = log_file
    _container_name   = container_name
    _on_event         = on_event
    _running          = True

    threading.Thread(target=_connect_loop, daemon=True, name="ace-tcp-client").start()

    has_welcome = msg_welcome or (discord_url and msg_discord) or (site_url and msg_site)
    if has_welcome:
        if deploy_mode == "docker_split":
            threading.Thread(target=_welcome_loop_docker, daemon=True,
                             name="ace-welcome-bot").start()
        elif log_file:
            threading.Thread(target=_welcome_loop_native, daemon=True,
                             name="ace-welcome-bot").start()

    log.info("ace_tcp_client: démarrage vers %s:%d", host, port)


def stop():
    global _running
    _running = False
    with _lock:
        if _sock:
            try:
                _sock.close()
            except Exception:
                pass
