"""
Start / stop / status of AssettoCorsaEVOServer.exe.

Modes:
  DEPLOY_MODE=native       → Windows subprocess (legacy)
  DEPLOY_MODE=docker       → Wine dans le même container (legacy)
  DEPLOY_MODE=docker_split → Panel contrôle le container aceserver via Docker socket
"""
import collections
import contextlib
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import psutil
from flask import current_app

_PROCESS_NAME = "AssettoCorsaEVOServer"
_DEPLOY_MODE  = os.environ.get("DEPLOY_MODE", "native")

# Flask app reference — set by init_watchdog to enable app_context in background threads
_app = None


def _db_context():
    """Context manager: enters app_context if _app is set, otherwise a no-op."""
    return _app.app_context() if _app else contextlib.nullcontext()

# docker_split — nom du container aceserver (défini dans docker-compose container_name)
_DOCKER_CONTAINER_NAME = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")
# Hostname du service aceserver dans le réseau Docker (pour l'API HTTP)
_ACESERVER_HOST        = os.environ.get("ACESERVER_HOST", "aceserver")

# Per-server runtime state (keyed by server_id)
_servers: dict      = {}
_servers_lock       = threading.Lock()

# Per-server rotation lock — prevents double rotation from watchdog + webhook
_rotation_locks: dict[int, threading.Lock] = {}
_rotation_locks_meta = threading.Lock()

# is_running() cache for docker_split mode — avoids a Docker API call on every request
_is_running_cache: dict[int, tuple[bool, float]] = {}
_IS_RUNNING_CACHE_TTL = 5.0  # seconds


def _rotation_lock(server_id: int) -> threading.Lock:
    with _rotation_locks_meta:
        if server_id not in _rotation_locks:
            _rotation_locks[server_id] = threading.Lock()
        return _rotation_locks[server_id]

log = logging.getLogger(__name__)


def _get_server(server_id: int) -> dict:
    """Returns the mutable per-server state dict, creating it on first access."""
    with _servers_lock:
        if server_id not in _servers:
            _servers[server_id] = {
                "watchdog_thread":     None,
                "watchdog_stop":       threading.Event(),
                "exe_path":            "",
                "wine_ready":          threading.Event(),
                "player_history":      collections.deque(maxlen=120),
                "player_history_lock": threading.Lock(),
                "system_warnings":     [],
                "last_history_sample": 0.0,
                "container_name":      "",  # populated by init_watchdog
                "http_host":           "",  # hostname used for HTTP player-count API
            }
        return _servers[server_id]


# ── Atomic file write ────────────────────────────────────────────────────────

def _atomic_write(path: Path, content: str):
    """Write content to path atomically (tmp file + os.replace) to avoid corruption."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Path helpers ─────────────────────────────────────────────────────────────

def _state_file(server_id: int) -> Path:
    suffix = "" if server_id == 1 else f"_{server_id}"
    if _DEPLOY_MODE == "docker_split":
        base = Path(os.environ.get("ACESERVER_DIR", "/aceserver"))
        return base / f".panel_state{suffix}.json"
    return Path(__file__).parent.parent.parent / f".server_state{suffix}"


def _log_file(server_id: int) -> Path:
    suffix = "" if server_id == 1 else f"_{server_id}"
    return Path(__file__).parent.parent.parent / f".server_output{suffix}.log"


def _launch_config_path(server_id: int) -> Path:
    suffix = "" if server_id == 1 else f"_{server_id}"
    return Path(os.environ.get("ACESERVER_DIR", "/aceserver")) / f".launch_config{suffix}.json"


# ── State file ───────────────────────────────────────────────────────────────

def _read_state(server_id: int) -> dict:
    sf = _state_file(server_id)
    if sf.exists():
        try:
            return json.loads(sf.read_text())
        except Exception:
            pass
    return {}


def _write_state(pid: int, config_name: str, sc_b64: str, sd_b64: str,
                 auto_restart: bool, http_port: int = 8080, run_id: str = "",
                 server_id: int = 1):
    import time as _t
    sf       = _state_file(server_id)
    existing = _read_state(server_id)
    # Preserve started_at across state rewrites; set a new one only when launching a fresh process
    if pid and pid != existing.get("pid"):
        started_at = _t.time()
    else:
        started_at = existing.get("started_at") or _t.time()
    _atomic_write(sf, json.dumps({
        "pid":          pid,
        "config":       config_name,
        "sc":           sc_b64,
        "sd":           sd_b64,
        "auto_restart": auto_restart,
        "http_port":    http_port,
        "run_id":       run_id,
        "started_at":   started_at,
    }))


def _clear_state(server_id: int):
    sf = _state_file(server_id)
    if sf.exists():
        sf.unlink()


def update_session_state(session_type: str, server_id: int = 1):
    """Called after each result ingest to track session timing."""
    state = _read_state(server_id)
    if not state:
        return
    state["session_changed_at"] = time.time()
    state["last_session_type"]  = session_type.lower()
    _atomic_write(_state_file(server_id), json.dumps(state))


def _sample_player_history(server_id: int):
    """Append current player count to in-memory history every ~30s."""
    srv = _get_server(server_id)
    now = time.time()
    if now - srv["last_history_sample"] < 30:
        return
    srv["last_history_sample"] = now
    count = get_player_count(server_id)
    if count is not None:
        with srv["player_history_lock"]:
            srv["player_history"].append({"ts": int(now), "count": count})


def get_player_history(server_id: int = 1) -> list:
    srv = _get_server(server_id)
    with srv["player_history_lock"]:
        return list(srv["player_history"])


def _set_auto_restart(enabled: bool, server_id: int):
    state = _read_state(server_id)
    if state:
        state["auto_restart"] = enabled
        _atomic_write(_state_file(server_id), json.dumps(state))


# ── Docker split helpers ──────────────────────────────────────────────────────

_docker_client = None
_docker_client_lock = threading.Lock()


def _get_docker_client():
    global _docker_client
    with _docker_client_lock:
        if _docker_client is None:
            import docker
            _docker_client = docker.from_env()
        return _docker_client


def _get_aceserver_container(server_id: int = 1):
    """Retourne l'objet Container Docker du serveur ACE EVO, ou None."""
    srv  = _get_server(server_id)
    name = srv["container_name"] or _DOCKER_CONTAINER_NAME
    try:
        return _get_docker_client().containers.get(name)
    except Exception as e:
        log.debug("Container '%s' introuvable : %s", name, e)
        return None


# ── Process helpers (native/docker modes) ────────────────────────────────────

def _proc_matches(proc: psutil.Process) -> bool:
    try:
        if _DEPLOY_MODE == "docker":
            return _PROCESS_NAME in " ".join(proc.cmdline())
        return proc.is_running() and _PROCESS_NAME in proc.name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def _prewarm_wine(server_id: int):
    log.info("Wine prefix pre-warm starting… (server=%d)", server_id)
    try:
        subprocess.run(
            ["wine", "wineboot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180,
        )
    except Exception as e:
        log.warning("Wine pre-warm ended: %s", e)
    finally:
        _get_server(server_id)["wine_ready"].set()
        log.info("Wine prefix ready (server=%d)", server_id)


def _wait_for_wineboot(timeout: int = 90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        running = False
        for proc in psutil.process_iter(["cmdline"]):
            try:
                if "wineboot" in " ".join(proc.cmdline()):
                    running = True
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        if not running:
            return
        time.sleep(3)
    log.warning("wineboot didn't finish within %ds, launching anyway", timeout)


def _launch(exe: Path, sc_b64: str, sd_b64: str, server_id: int) -> "subprocess.Popen | None":
    try:
        log_f = open(_log_file(server_id), "a", encoding="utf-8", errors="replace")
        try:
            if _DEPLOY_MODE == "docker":
                cmd = ["wine", str(exe), "-serverconfig", sc_b64, "-seasondefinition", sd_b64]
                return subprocess.Popen(cmd, cwd=str(exe.parent), stdout=log_f, stderr=subprocess.STDOUT)
            show_console   = _show_console()
            creation_flags = 0 if show_console else subprocess.CREATE_NO_WINDOW
            cmd = [str(exe), "-serverconfig", sc_b64, "-seasondefinition", sd_b64]
            return subprocess.Popen(
                cmd, cwd=str(exe.parent),
                stdout=None if show_console else log_f,
                stderr=None if show_console else subprocess.STDOUT,
                creationflags=creation_flags,
            )
        finally:
            log_f.close()  # parent closes; child process keeps its inherited copy
    except Exception as e:
        log.error("Failed to launch server: %s", e)
        return None


def _ensure_race_weekend_file(exe_path: Path) -> bool:
    """Crée race_weekend.seasondefinition s'il n'existe pas (requis par l'exe)."""
    f = exe_path.parent / "content" / "data" / "race_weekend.seasondefinition"
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists():
        try:
            f.read_text(encoding="utf-8")
            return True
        except Exception:
            pass
    f.write_text(json.dumps({"name": "Race Weekend"}), encoding="utf-8")
    return True


def _show_console() -> bool:
    try:
        from flask import current_app
        return current_app.config.get("SERVER_SHOW_CONSOLE", False)
    except RuntimeError:
        return False


# ── Rotation helpers ─────────────────────────────────────────────────────────

def _rotation_next(config_name: str) -> str | None:
    try:
        from app.services.rotation_manager import get_next_config
        return get_next_config(config_name)
    except Exception as e:
        log.error("rotation_manager error: %s", e)
        return None


def _watchdog_rotate_docker(container, next_cfg: str, auto_restart: bool,
                             from_cfg: str = "", server_id: int = 1):
    """Passe à la prochaine config du roulement (container en cours ou arrêté)."""
    configs_dir = Path(os.environ.get("CONFIGS_DIR", "/aceserver/configs"))
    try:
        cfg_data = json.loads((configs_dir / next_cfg).read_text())
    except Exception as e:
        log.error("Rotation: cannot load config %r: %s", next_cfg, e)
        return
    cfg_data.setdefault("Server", {})["IsCycleEnabled"] = False
    try:
        from app.services import config_builder
        from app.models import Server as _Server
        from app.services.database import db as _db
        with _db_context():
            _srv = _db.session.get(_Server, server_id)
        sc_b64, sd_b64 = config_builder.build_launch_args(
            cfg_data,
            tcp_listener=_srv.tcp_port if _srv else None,
            udp_listener=_srv.udp_port if _srv else None,
            server_name=_srv.name     if _srv else None,
        )
    except Exception as e:
        log.error("Rotation: build_launch_args failed for %r: %s", next_cfg, e)
        return

    new_run_id = uuid.uuid4().hex
    lcp = _launch_config_path(server_id)
    lcp.write_text(json.dumps({
        "serverconfig":     sc_b64,
        "seasondefinition": sd_b64,
    }))
    try:
        container.reload()
        # Restart si en cours (rotation déclenchée par webhook), start si arrêté (watchdog)
        if container.status == "running":
            container.restart(timeout=10)
        else:
            container.start()
        http_port = int(os.environ.get("ACESERVER_HTTP_PORT", "8080"))
        _write_state(0, next_cfg, sc_b64, sd_b64, auto_restart, http_port,
                     run_id=new_run_id, server_id=server_id)
        log.info("Rotation: started %r (run=%s)", next_cfg, new_run_id)
        try:
            from app.services import discord_notifier
            from app.models import Server as _Server
            from app.services.database import db as _db
            with _db_context():
                _rot_srv = _db.session.get(_Server, server_id)
                discord_notifier.notify_rotation_advance(from_cfg, next_cfg, cfg_data,
                                                         server_id=server_id,
                                                         server_name=_rot_srv.name if _rot_srv else "")
        except Exception:
            pass
    except Exception as e:
        log.error("Rotation: failed to start container for %r: %s", next_cfg, e)
        lcp.unlink(missing_ok=True)


def _watchdog_rotate_native(exe: Path, next_cfg: str, auto_restart: bool,
                             from_cfg: str = "", server_id: int = 1):
    """Lance le serveur natif avec la prochaine config du roulement."""
    configs_dir = Path(os.environ.get(
        "CONFIGS_DIR",
        str(exe.parent / "configs"),
    ))
    try:
        cfg_data = json.loads((configs_dir / next_cfg).read_text())
    except Exception as e:
        log.error("Rotation: cannot load config %r: %s", next_cfg, e)
        return
    cfg_data.setdefault("Server", {})["IsCycleEnabled"] = False
    try:
        from app.services import config_builder
        from app.models import Server as _Server
        from app.services.database import db as _db
        with _db_context():
            _srv = _db.session.get(_Server, server_id)
        sc_b64, sd_b64 = config_builder.build_launch_args(
            cfg_data,
            tcp_listener=_srv.tcp_port if _srv else None,
            udp_listener=_srv.udp_port if _srv else None,
            server_name=_srv.name     if _srv else None,
        )
    except Exception as e:
        log.error("Rotation: build_launch_args failed for %r: %s", next_cfg, e)
        return

    new_run_id = uuid.uuid4().hex
    if cfg_data.get("Event", {}).get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        _ensure_race_weekend_file(exe)
    try:
        with open(_log_file(server_id), "a", encoding="utf-8") as lf:
            lf.write(f"\n[rotation] Starting next config: {next_cfg}\n")
    except Exception:
        pass
    proc = _launch(exe, sc_b64, sd_b64, server_id)
    if proc:
        _write_state(proc.pid, next_cfg, sc_b64, sd_b64, auto_restart,
                     run_id=new_run_id, server_id=server_id)
        log.info("Rotation: started %r (PID=%d)", next_cfg, proc.pid)
        try:
            from app.services import discord_notifier
            from app.models import Server as _Server
            from app.services.database import db as _db
            with _db_context():
                _rot_srv = _db.session.get(_Server, server_id)
                discord_notifier.notify_rotation_advance(from_cfg, next_cfg, cfg_data,
                                                         server_id=server_id,
                                                         server_name=_rot_srv.name if _rot_srv else "")
        except Exception:
            pass
    else:
        log.error("Rotation: failed to launch %r", next_cfg)


# ── Rotation webhook-driven ──────────────────────────────────────────────────

def try_rotation_advance(session_type: str, config_name: str, server_id: int = 1):
    """
    Appelé depuis le webhook de fin de session (results_ingest).
    ACE EVO garde son processus en vie après une session — le container ne s'arrête
    pas forcément. On déclenche donc la rotation ici, sans attendre la mort du process.

    Règle "dernière session" :
      - Config Practice  → toujours la dernière (une seule session par run)
      - Config Race Weekend → uniquement après la session "Race"
    """
    import threading, time

    try:
        from app.services.rotation_manager import get_rotation, get_next_config
        rot = get_rotation()
        if not rot.get("enabled"):
            return

        next_cfg = get_next_config(config_name)
        if next_cfg is None:
            return

        # Charger la config courante pour déterminer son mode (sans contexte Flask)
        configs_dir = Path(os.environ.get("CONFIGS_DIR", "/aceserver/configs"))
        try:
            cfg_data  = json.loads((configs_dir / config_name).read_text())
            game_mode = cfg_data.get("Event", {}).get("SelectedSessionTypeValue", "")
        except Exception:
            game_mode = ""

        is_race_weekend = (game_mode == "GameModeType_RACE_WEEKEND")
        is_last_session = (not is_race_weekend) or (session_type.lower() == "race")

        if not is_last_session:
            log.debug("Rotation: session %r pas finale pour %r, skip", session_type, config_name)
            return

        state        = _read_state(server_id)
        auto_restart = state.get("auto_restart", False)
        log.info("Rotation (webhook): %r → %r (session=%r)", config_name, next_cfg, session_type)

    except Exception as e:
        log.error("try_rotation_advance: %s", e)
        return

    def _rotate():
        time.sleep(3)  # Laisse ACE EVO finir d'écrire ses fichiers résultats
        lock = _rotation_lock(server_id)
        if not lock.acquire(blocking=False):
            log.info("Rotation (webhook): rotation déjà en cours sur serveur %d, skip", server_id)
            return
        try:
            # Évite la double rotation si le watchdog a déjà avancé la config
            current = _read_state(server_id)
            if current.get("config") != config_name:
                log.info("Rotation (webhook): state déjà avancé par watchdog, skip")
                return
            if _DEPLOY_MODE == "docker_split":
                container = _get_aceserver_container(server_id)
                if not container:
                    return
                _watchdog_rotate_docker(container, next_cfg, auto_restart,
                                        from_cfg=config_name, server_id=server_id)
            else:
                exe_path = _get_server(server_id)["exe_path"]
                if exe_path:
                    _watchdog_rotate_native(Path(exe_path), next_cfg, auto_restart,
                                            from_cfg=config_name, server_id=server_id)
        finally:
            lock.release()

    threading.Thread(target=_rotate, daemon=True,
                     name=f"rotation-webhook-{server_id}").start()


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop(server_id: int):
    srv = _get_server(server_id)
    log.info("Watchdog started (mode=%s, server=%d)", _DEPLOY_MODE, server_id)
    while not srv["watchdog_stop"].wait(timeout=10):
        if is_running(server_id):
            _sample_player_history(server_id)
        state = _read_state(server_id)
        if not state:
            continue

        auto_restart = state.get("auto_restart", False)
        config_name  = state.get("config", "")
        next_cfg     = _rotation_next(config_name)

        # Rien à faire si ni auto_restart ni rotation active
        if not auto_restart and next_cfg is None:
            continue

        if _DEPLOY_MODE == "docker_split":
            container = _get_aceserver_container(server_id)
            if not container:
                continue
            try:
                container.reload()
            except Exception:
                continue
            if container.status == "running":
                continue

            # Container stoppé — rotation ou auto_restart
            if next_cfg is not None:
                with _rotation_lock(server_id):
                    _watchdog_rotate_docker(container, next_cfg, auto_restart,
                                            from_cfg=config_name, server_id=server_id)
            else:
                log.warning("Watchdog: container aceserver stoppé, redémarrage…")
                try:
                    from app.services import discord_notifier
                    from app.models import Server as _Server
                    from app.services.database import db as _db
                    with _db_context():
                        _crash_srv = _db.session.get(_Server, server_id)
                        discord_notifier.notify_crash(config_name, restarting=True,
                                                      server_id=server_id,
                                                      server_name=_crash_srv.name if _crash_srv else "")
                except Exception:
                    pass
                try:
                    container.start()
                    log.info("Watchdog: container aceserver redémarré")
                except Exception as e:
                    log.error("Watchdog: échec redémarrage container : %s", e)
            continue

        # Modes native / docker : vérification psutil
        pid   = state.get("pid")
        alive = False
        if pid:
            try:
                alive = _proc_matches(psutil.Process(pid))
            except psutil.NoSuchProcess:
                pass
        if alive:
            continue

        exe    = Path(srv["exe_path"])
        run_id = state.get("run_id", "")

        if next_cfg is not None:
            with _rotation_lock(server_id):
                _watchdog_rotate_native(exe, next_cfg, auto_restart,
                                        from_cfg=config_name, server_id=server_id)
        else:
            sc = state.get("sc", "")
            sd = state.get("sd", "")
            log.warning("Watchdog: server crashed, restarting…")
            try:
                from app.services import discord_notifier
                from app.models import Server as _Server
                from app.services.database import db as _db
                with _db_context():
                    _crash_srv = _db.session.get(_Server, server_id)
                    discord_notifier.notify_crash(config_name, restarting=auto_restart,
                                                  server_id=server_id,
                                                  server_name=_crash_srv.name if _crash_srv else "")
            except Exception:
                pass
            try:
                with open(_log_file(server_id), "a", encoding="utf-8") as lf:
                    lf.write("\n[watchdog] Server crash detected — restarting…\n")
            except Exception:
                pass
            proc = _launch(exe, sc, sd, server_id)
            if proc:
                _write_state(proc.pid, config_name, sc, sd, auto_restart,
                             run_id=run_id, server_id=server_id)
                log.info("Watchdog: restarted with PID %d", proc.pid)
            else:
                log.error("Watchdog: restart failed")

    log.info("Watchdog stopped (server=%d)", server_id)


def _start_watchdog(server_id: int):
    srv = _get_server(server_id)
    if srv["watchdog_thread"] and srv["watchdog_thread"].is_alive():
        return
    srv["watchdog_stop"].clear()
    t = threading.Thread(
        target=_watchdog_loop,
        args=(server_id,),
        daemon=True,
        name=f"server-watchdog-{server_id}",
    )
    srv["watchdog_thread"] = t
    t.start()


def _check_docker_restart_policy(server_id: int) -> None:
    """Vérifie que le container a restart:no — sinon double lancement possible."""
    try:
        container = _get_aceserver_container(server_id)
        if not container:
            return
        policy = container.attrs.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", "no")
        if policy != "no":
            name = _get_server(server_id)["container_name"] or _DOCKER_CONTAINER_NAME
            msg = (
                f"Le container '{name}' a la politique "
                f"restart='{policy}' au lieu de 'no'. "
                f"Le watchdog du panel gère déjà les redémarrages — "
                f"une politique Docker active peut provoquer un double lancement du serveur. "
                f"Corrigez restart: \"no\" dans votre docker-compose.yml puis relancez docker compose up -d."
            )
            _get_server(server_id)["system_warnings"].append(msg)
            log.warning("CONFIG: %s", msg)
    except Exception as e:
        log.debug("Impossible de vérifier la politique restart : %s", e)


def init_watchdog(exe_path: str, server_id: int = 1,
                  container_name: str = "", http_host: str = "", app=None):
    global _app
    if app is not None:
        _app = app
    srv = _get_server(server_id)
    srv["exe_path"]       = exe_path
    srv["container_name"] = container_name or _DOCKER_CONTAINER_NAME
    srv["http_host"]      = http_host or _ACESERVER_HOST
    if _DEPLOY_MODE == "docker":
        threading.Thread(
            target=_prewarm_wine, args=(server_id,),
            daemon=True, name=f"wine-prewarm-{server_id}",
        ).start()
    else:
        srv["wine_ready"].set()
    if _DEPLOY_MODE == "docker_split":
        _check_docker_restart_policy(server_id)
    _start_watchdog(server_id)


# ── Public API ───────────────────────────────────────────────────────────────

def get_system_warnings(server_id: int = 1) -> list[str]:
    """Retourne les avertissements de configuration détectés au démarrage."""
    return list(_get_server(server_id)["system_warnings"])


def is_running(server_id: int = 1) -> bool:
    if _DEPLOY_MODE == "docker_split":
        # Check cache first (5s TTL) to avoid a Docker API call on every Flask request
        cached = _is_running_cache.get(server_id)
        if cached is not None:
            result, ts = cached
            if time.monotonic() - ts < _IS_RUNNING_CACHE_TTL:
                return result
        # L'intention de faire tourner le serveur est indiquée par le fichier de config
        if not _launch_config_path(server_id).exists():
            _is_running_cache[server_id] = (False, time.monotonic())
            return False
        container = _get_aceserver_container(server_id)
        if not container:
            _is_running_cache[server_id] = (False, time.monotonic())
            return False
        try:
            container.reload()
        except Exception:
            _is_running_cache[server_id] = (False, time.monotonic())
            return False
        result = container.status == "running"
        _is_running_cache[server_id] = (result, time.monotonic())
        return result

    # native / docker
    state = _read_state(server_id)
    pid   = state.get("pid")
    if pid:
        try:
            if _proc_matches(psutil.Process(pid)):
                return True
        except psutil.NoSuchProcess:
            pass
    for proc in psutil.process_iter(["name", "cmdline"]):
        if _proc_matches(proc):
            return True
    return False


def get_player_count(server_id: int = 1) -> int | None:
    state = _read_state(server_id)
    if _DEPLOY_MODE == "docker_split":
        port      = state.get("http_port", 8080)
        http_host = _get_server(server_id)["http_host"] or _ACESERVER_HOST
        url       = f"http://{http_host}:{port}/"
    else:
        port = state.get("http_port", 8080)
        url  = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            data = json.loads(r.read())
            return data.get("clients", 0)
    except Exception:
        return None


def start_server(serverconfig_b64: str, seasondefinition_b64: str,
                 config_name: str, auto_restart: bool = False,
                 server_id: int = 1) -> dict:
    _is_running_cache.pop(server_id, None)  # invalidate cache before state change
    if is_running(server_id):
        return {"ok": False, "error": "server_already_running"}

    # Identifiant unique pour ce run — toutes les sessions de ce démarrage partageront ce run_id.
    # Généré ici (démarrage explicite admin/scheduler), jamais recalculé par le watchdog.
    run_id = uuid.uuid4().hex

    if _DEPLOY_MODE == "docker_split":
        lcp = _launch_config_path(server_id)
        lcp.write_text(json.dumps({
            "serverconfig":    serverconfig_b64,
            "seasondefinition": seasondefinition_b64,
        }))
        try:
            container = _get_aceserver_container(server_id)
            if not container:
                lcp.unlink(missing_ok=True)
                return {"ok": False, "error": "aceserver_container_not_found"}
            container.reload()
            if container.status == "running":
                container.restart(timeout=10)
            else:
                container.start()
            http_port = int(os.environ.get("ACESERVER_HTTP_PORT", "8080"))
            _write_state(0, config_name, serverconfig_b64, seasondefinition_b64,
                         auto_restart, http_port, run_id=run_id, server_id=server_id)
            return {"ok": True, "pid": 0, "config": config_name, "run_id": run_id}
        except Exception as e:
            lcp.unlink(missing_ok=True)
            return {"ok": False, "error": str(e)}

    # native / docker
    exe       = Path(current_app.config["ACESERVER_EXE_PATH"])
    http_port = current_app.config.get("ACESERVER_HTTP_PORT", 8080)
    proc = _launch(exe, serverconfig_b64, seasondefinition_b64, server_id)
    if not proc:
        return {"ok": False, "error": "launch_failed"}
    _write_state(proc.pid, config_name, serverconfig_b64, seasondefinition_b64,
                 auto_restart, http_port, run_id=run_id, server_id=server_id)
    return {"ok": True, "pid": proc.pid, "config": config_name, "run_id": run_id}


def stop_server(server_id: int = 1) -> dict:
    _is_running_cache.pop(server_id, None)  # invalidate cache before state change
    if _DEPLOY_MODE == "docker_split":
        # Supprimer la config de lancement avant d'arrêter le container
        _launch_config_path(server_id).unlink(missing_ok=True)
        try:
            container = _get_aceserver_container(server_id)
            if container:
                container.stop(timeout=10)
        except Exception as e:
            log.warning("stop_server docker_split : %s", e)
        _clear_state(server_id)
        return {"ok": True, "error": None}

    # native / docker
    state  = _read_state(server_id)
    pid    = state.get("pid")
    killed = False
    if pid:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=10)
                killed = True
            except psutil.TimeoutExpired:
                log.warning("stop_server: SIGTERM timeout for PID %d, sending SIGKILL", pid)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                    killed = True
                except Exception as e:
                    log.error("stop_server: SIGKILL failed for PID %d: %s", pid, e)
        except psutil.NoSuchProcess:
            killed = True  # already gone
    if not killed:
        for proc in psutil.process_iter(["name", "pid", "cmdline"]):
            if _proc_matches(proc):
                psutil.Process(proc.info["pid"]).terminate()
                killed = True
                break
    _clear_state(server_id)
    return {"ok": killed, "error": None if killed else "process_not_found"}


def set_auto_restart(enabled: bool, server_id: int = 1) -> dict:
    state = _read_state(server_id)
    if not state:
        return {"ok": False, "error": "server_not_running"}
    _set_auto_restart(enabled, server_id)
    return {"ok": True, "auto_restart": enabled}


def get_server_logs(lines: int = 100, server_id: int = 1) -> str:
    if _DEPLOY_MODE == "docker_split":
        try:
            container = _get_aceserver_container(server_id)
            if not container:
                return ""
            raw = container.logs(tail=lines, timestamps=False)
            return raw.decode("utf-8", errors="replace")
        except Exception as e:
            log.debug("get_server_logs docker_split : %s", e)
            return ""

    lf = _log_file(server_id)
    if not lf.exists():
        return ""
    try:
        text = lf.read_text(encoding="utf-8", errors="replace")
        tail = text.strip().splitlines()[-lines:]
        return "\n".join(tail)
    except Exception:
        return ""


def get_status(server_id: int = 1) -> dict:
    running = is_running(server_id)
    state   = _read_state(server_id)
    players = get_player_count(server_id) if running else None
    return {
        "running":            running,
        "pid":                state.get("pid")               if running else None,
        "config":             state.get("config")            if running else None,
        "run_id":             state.get("run_id")            if running else None,
        "auto_restart":       state.get("auto_restart", False),
        "players":            players,
        "started_at":         state.get("started_at")        if running else None,
        "session_changed_at": state.get("session_changed_at") if running else None,
        "last_session_type":  state.get("last_session_type") if running else None,
    }
