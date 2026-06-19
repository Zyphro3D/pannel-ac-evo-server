"""
Client TCP pour le serveur ACE EVO (port 9700).
Protocole : [uint16_LE: total_len-2][0x00][0x02][uint8: name_len][name][protobuf_payload]

Messages pris en charge :
  C2S  ClientConnectionRequest  — handshake initial
  C2S  MultiplayerChatMessage   — envoi d'un message dans le tchat du jeu
  S2C  BroadcastStateMessage    — état courant (PlatformRaceLeaderboard, etc.)
  S2C  SplitFromRemoteMessage   — passage de secteur
"""
import glob
import json
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
_RE_CONNECT_LOG = re.compile(
    r'\[gameplay\] \[info\] (\d+) connected \([^)]+\) on car ([^,\s]+)'
    r'(?:, with new carId ([0-9a-f-]+))?'
)
_RE_DISCONN_LOG = re.compile(r'\[gameplay\] \[info\] (\d+) disconnected')
_RE_NEWLAP_LOG  = re.compile(r'\[gameplay\] \[info\] New lap carId ([0-9a-f-]+): (\d+:\d+\.\d+)')
_RE_PLAYERS_LOG = re.compile(r'\[server\] \[info\] Server updated: (\d+) players')

# État supplémentaire pour les notifs Discord (protégé par _lb_lock)
_join_times:           dict[str, float] = {}  # steam_id → timestamp connexion
_car_id_to_sid:        dict[str, str]   = {}  # car_id → steam_id (pour les tours)
_num_to_sid:           dict[str, str]   = {}  # car_num → steam_id (pour actions admin)
_sid_car_raw:          dict[str, str]   = {}  # steam_id → modèle voiture
_recently_disconnected: dict[str, dict] = {}  # steam_id → {name, car_raw, ts} pour détecter changement véhicule
_race_state:           dict              = {"server_best_ms": None}  # best lap serveur

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
            files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
            name = os.path.basename(files[0]) if files else ""
        if not name:
            return _car_model
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            cfg = json.load(f)
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
            files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
            name = os.path.basename(files[0]) if files else ""
        if not name:
            return ""
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            return json.load(f).get("Server", {}).get("AdminPassword", "")
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


def _parse_lap_ms(s: str) -> int:
    try:
        parts = s.split(':')
        rest  = parts[1].split('.')
        return int(parts[0]) * 60000 + int(rest[0]) * 1000 + (int(rest[1]) if len(rest) > 1 else 0)
    except Exception:
        return 0


def get_driver_by_num(num: str) -> dict:
    """Retourne {name, steam_id, car_raw} du pilote par numéro de voiture, ou {}."""
    with _lb_lock:
        sid = _num_to_sid.get(str(num))
        if not sid:
            return {}
        return {
            "name":     _leaderboard.get(sid, {}).get("name", "?"),
            "steam_id": sid,
            "car_raw":  _sid_car_raw.get(sid, ""),
        }


def _process_log_line(line: str, seen: set):
    # Gameplay: connexion — stocke car_raw + car_id avant le log server
    m = _RE_CONNECT_LOG.search(line)
    if m:
        sid, car_raw, car_id = m.group(1), m.group(2), m.group(3) or ""
        with _lb_lock:
            _join_times[sid]  = time.time()
            _sid_car_raw[sid] = car_raw
            if car_id:
                _car_id_to_sid[car_id] = sid
        return

    # Server: nom + numéro (arrive après le connect log)
    m = _RE_DRIVER_LOG.search(line)
    if m:
        num, name, sid = m.group(1), m.group(2), m.group(3)
        now = time.time()
        with _lb_lock:
            _num_to_sid[num] = sid
            car_raw = _sid_car_raw.get(sid, "")
            recent  = _recently_disconnected.pop(sid, None)
            stale   = [k for k, v in _recently_disconnected.items() if now - v["ts"] > 600]
        # Purge hors du lock — évite O(N) pendant la section critique
        for k in stale:
            with _lb_lock:
                _recently_disconnected.pop(k, None)

        vehicle_changed = (
            recent is not None
            and recent["car_raw"]
            and car_raw
            and recent["car_raw"] != car_raw
            and (now - recent["ts"]) < 600
        )

        if vehicle_changed:
            seen.add(sid)  # bloque la notif "join" standard
            threading.Thread(target=_send_welcome, args=(name,), daemon=True).start()
            try:
                from app.services import discord_notifier
                discord_notifier.safe_notify(
                    discord_notifier.notify_vehicle_change,
                    name, num, recent["car_raw"], car_raw
                )
            except Exception:
                pass
        elif sid not in seen:
            seen.add(sid)
            threading.Thread(target=_send_welcome, args=(name,), daemon=True).start()
            try:
                from app.services import discord_notifier
                discord_notifier.safe_notify(
                    discord_notifier.notify_player_join, name, num, car_raw, sid
                )
            except Exception:
                pass
        return

    # Gameplay: déconnexion
    m = _RE_DISCONN_LOG.search(line)
    if m:
        sid = m.group(1)
        seen.discard(sid)
        with _lb_lock:
            joined   = _join_times.pop(sid, None)
            old_car  = _sid_car_raw.pop(sid, "")
            name     = _leaderboard.get(sid, {}).get("name", sid)
            num      = _leaderboard.get(sid, {}).get("num")
            if num:
                _num_to_sid.pop(str(num), None)
            # Mémorise pour détecter un éventuel changement de véhicule à la reconnexion
            _recently_disconnected[sid] = {"name": name, "car_raw": old_car, "ts": time.time()}
        duration_s = int(time.time() - joined) if joined else None
        try:
            from app.services import discord_notifier
            discord_notifier.safe_notify(
                discord_notifier.notify_player_disconnect, name, sid, duration_s
            )
        except Exception:
            pass
        return

    # Gameplay: nouveau tour — notifie uniquement si meilleur temps du serveur
    m = _RE_NEWLAP_LOG.search(line)
    if m:
        car_id, lap_str = m.group(1), m.group(2)
        lap_ms = _parse_lap_ms(lap_str)
        if lap_ms > 0:
            notify = False
            with _lb_lock:
                sid     = _car_id_to_sid.get(car_id, "")
                name    = _leaderboard.get(sid, {}).get("name", "?") if sid else "?"
                car_raw = _sid_car_raw.get(sid, "") if sid else ""
                best    = _race_state["server_best_ms"]
                if best is None or lap_ms < best:
                    _race_state["server_best_ms"] = lap_ms
                    notify = True
            if notify:
                try:
                    from app.services import discord_notifier
                    discord_notifier.safe_notify(
                        discord_notifier.notify_best_lap, name, lap_str, car_raw
                    )
                except Exception:
                    pass
        return

    # Server: reset de session (0 joueurs = nouveau démarrage serveur)
    m = _RE_PLAYERS_LOG.search(line)
    if m and m.group(1) == '0':
        with _lb_lock:
            _car_id_to_sid.clear()
            _num_to_sid.clear()
            _sid_car_raw.clear()
            _join_times.clear()
            _recently_disconnected.clear()
            _race_state["server_best_ms"] = None
        seen.clear()


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


def elevate_admin() -> str | None:
    """Envoie \\admin <password> au serveur avec le mot de passe de la config active.
    Ignore ACE_BOT_IS_ADMIN — appelé explicitement par l'admin via le panel.
    Retourne None si ok, message d'erreur sinon.
    """
    if not _connected:
        return "Bot TCP non connecté"
    try:
        configs_dir = os.environ.get("CONFIGS_DIR", "/aceserver/configs")
        active_file = os.path.join(configs_dir, ".active_config")
        if os.path.exists(active_file):
            with open(active_file) as f:
                name = f.read().strip()
        else:
            files = sorted(glob.glob(os.path.join(configs_dir, "*.json")))
            name = os.path.basename(files[0]) if files else ""
        if not name:
            return "Aucune configuration active trouvée"
        with open(os.path.join(configs_dir, name), encoding="utf-8") as f:
            pwd = json.load(f).get("Server", {}).get("AdminPassword", "")
        if not pwd:
            return "Aucun mot de passe admin configuré dans la session active"
    except Exception as e:
        return f"Erreur lecture config : {e}"
    sent = send_chat(f"\\admin {pwd}")
    if not sent:
        return "Échec envoi — bot TCP non connecté"
    log.info("ace_tcp_client: élévation admin manuelle envoyée")
    return None


def stop():
    global _running
    _running = False
    with _lock:
        if _sock:
            try:
                _sock.close()
            except Exception:
                pass
