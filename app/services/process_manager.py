"""
Start / stop / status of AssettoCorsaEVOServer.exe.

Modes:
  DEPLOY_MODE=native       → Windows subprocess (legacy)
  DEPLOY_MODE=docker       → Wine dans le même container (legacy)
  DEPLOY_MODE=docker_split → Panel contrôle le container aceserver via Docker socket
"""
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

# En docker_split, le state est sur le volume partagé (/aceserver) pour survivre aux rebuilds du panel
if _DEPLOY_MODE == "docker_split":
    _STATE_FILE = Path(os.environ.get("ACESERVER_DIR", "/aceserver")) / ".panel_state.json"
else:
    _STATE_FILE = Path(__file__).parent.parent.parent / ".server_state"
_LOG_FILE = Path(__file__).parent.parent.parent / ".server_output.log"

# docker_split — nom du container aceserver (défini dans docker-compose container_name)
_DOCKER_CONTAINER_NAME = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")
# Hostname du service aceserver dans le réseau Docker (pour l'API HTTP)
_ACESERVER_HOST        = os.environ.get("ACESERVER_HOST", "aceserver")

_watchdog_thread: threading.Thread | None = None
_watchdog_stop   = threading.Event()
_exe_path: str   = ""
_wine_ready      = threading.Event()

log = logging.getLogger(__name__)


# ── State file ───────────────────────────────────────────────────────────────

def _read_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _write_state(pid: int, config_name: str, sc_b64: str, sd_b64: str,
                 auto_restart: bool, http_port: int = 8080, run_id: str = ""):
    _STATE_FILE.write_text(json.dumps({
        "pid":          pid,
        "config":       config_name,
        "sc":           sc_b64,
        "sd":           sd_b64,
        "auto_restart": auto_restart,
        "http_port":    http_port,
        "run_id":       run_id,
    }))


def _clear_state():
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()


def _set_auto_restart(enabled: bool):
    state = _read_state()
    if state:
        state["auto_restart"] = enabled
        _STATE_FILE.write_text(json.dumps(state))


# ── Docker split helpers ──────────────────────────────────────────────────────

def _get_docker_client():
    import docker
    return docker.from_env()


def _get_aceserver_container():
    """Retourne l'objet Container Docker du serveur ACE EVO, ou None."""
    try:
        return _get_docker_client().containers.get(_DOCKER_CONTAINER_NAME)
    except Exception as e:
        log.debug("Container '%s' introuvable : %s", _DOCKER_CONTAINER_NAME, e)
        return None


def _launch_config_path() -> Path:
    return Path(os.environ.get("ACESERVER_DIR", "/aceserver")) / ".launch_config.json"


# ── Process helpers (native/docker modes) ────────────────────────────────────

def _proc_matches(proc: psutil.Process) -> bool:
    try:
        if _DEPLOY_MODE == "docker":
            return _PROCESS_NAME in " ".join(proc.cmdline())
        return proc.is_running() and _PROCESS_NAME in proc.name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def _prewarm_wine():
    log.info("Wine prefix pre-warm starting…")
    try:
        subprocess.run(
            ["wine", "wineboot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180,
        )
    except Exception as e:
        log.warning("Wine pre-warm ended: %s", e)
    finally:
        _wine_ready.set()
        log.info("Wine prefix ready")


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


def _launch(exe: Path, sc_b64: str, sd_b64: str) -> "subprocess.Popen | None":
    try:
        log_f = open(_LOG_FILE, "a", encoding="utf-8", errors="replace")
        if _DEPLOY_MODE == "docker":
            cmd = ["wine", str(exe), "-serverconfig", sc_b64, "-seasondefinition", sd_b64]
            return subprocess.Popen(cmd, cwd=str(exe.parent), stdout=log_f, stderr=subprocess.STDOUT)
        show_console  = _show_console()
        creation_flags = 0 if show_console else subprocess.CREATE_NO_WINDOW
        cmd = [str(exe), "-serverconfig", sc_b64, "-seasondefinition", sd_b64]
        return subprocess.Popen(
            cmd, cwd=str(exe.parent),
            stdout=None if show_console else log_f,
            stderr=None if show_console else subprocess.STDOUT,
            creationflags=creation_flags,
        )
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


def _watchdog_rotate_docker(container, next_cfg: str, auto_restart: bool, from_cfg: str = ""):
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
        sc_b64, sd_b64 = config_builder.build_launch_args(cfg_data)
    except Exception as e:
        log.error("Rotation: build_launch_args failed for %r: %s", next_cfg, e)
        return

    new_run_id = uuid.uuid4().hex
    lcp = _launch_config_path()
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
        _write_state(0, next_cfg, sc_b64, sd_b64, auto_restart, http_port, run_id=new_run_id)
        log.info("Rotation: started %r (run=%s)", next_cfg, new_run_id)
        try:
            from app.services import discord_notifier
            discord_notifier.notify_rotation_advance(from_cfg, next_cfg, cfg_data)
        except Exception:
            pass
    except Exception as e:
        log.error("Rotation: failed to start container for %r: %s", next_cfg, e)
        lcp.unlink(missing_ok=True)


def _watchdog_rotate_native(exe: Path, next_cfg: str, auto_restart: bool, from_cfg: str = ""):
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
        sc_b64, sd_b64 = config_builder.build_launch_args(cfg_data)
    except Exception as e:
        log.error("Rotation: build_launch_args failed for %r: %s", next_cfg, e)
        return

    new_run_id = uuid.uuid4().hex
    if cfg_data.get("Event", {}).get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        _ensure_race_weekend_file(exe)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(f"\n[rotation] Starting next config: {next_cfg}\n")
    except Exception:
        pass
    proc = _launch(exe, sc_b64, sd_b64)
    if proc:
        _write_state(proc.pid, next_cfg, sc_b64, sd_b64, auto_restart, run_id=new_run_id)
        log.info("Rotation: started %r (PID=%d)", next_cfg, proc.pid)
        try:
            from app.services import discord_notifier
            discord_notifier.notify_rotation_advance(from_cfg, next_cfg, cfg_data)
        except Exception:
            pass
    else:
        log.error("Rotation: failed to launch %r", next_cfg)


# ── Rotation webhook-driven ──────────────────────────────────────────────────

def try_rotation_advance(session_type: str, config_name: str):
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

        state        = _read_state()
        auto_restart = state.get("auto_restart", False)
        log.info("Rotation (webhook): %r → %r (session=%r)", config_name, next_cfg, session_type)

    except Exception as e:
        log.error("try_rotation_advance: %s", e)
        return

    def _rotate():
        time.sleep(3)  # Laisse ACE EVO finir d'écrire ses fichiers résultats
        # Évite la double rotation si le watchdog a déjà avancé la config
        current = _read_state()
        if current.get("config") != config_name:
            log.info("Rotation (webhook): state déjà avancé par watchdog, skip")
            return
        if _DEPLOY_MODE == "docker_split":
            container = _get_aceserver_container()
            if not container:
                return
            _watchdog_rotate_docker(container, next_cfg, auto_restart, from_cfg=config_name)
        elif _exe_path:
            _watchdog_rotate_native(Path(_exe_path), next_cfg, auto_restart, from_cfg=config_name)

    threading.Thread(target=_rotate, daemon=True, name="rotation-webhook").start()


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop():
    global _exe_path
    log.info("Watchdog started (mode=%s)", _DEPLOY_MODE)
    while not _watchdog_stop.wait(timeout=10):
        state = _read_state()
        if not state:
            continue

        auto_restart = state.get("auto_restart", False)
        config_name  = state.get("config", "")
        next_cfg     = _rotation_next(config_name)

        # Rien à faire si ni auto_restart ni rotation active
        if not auto_restart and next_cfg is None:
            continue

        if _DEPLOY_MODE == "docker_split":
            container = _get_aceserver_container()
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
                _watchdog_rotate_docker(container, next_cfg, auto_restart, from_cfg=config_name)
            else:
                log.warning("Watchdog: container aceserver stoppé, redémarrage…")
                try:
                    from app.services import discord_notifier
                    discord_notifier.notify_crash(config_name, restarting=True)
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

        exe    = Path(_exe_path)
        run_id = state.get("run_id", "")

        if next_cfg is not None:
            _watchdog_rotate_native(exe, next_cfg, auto_restart, from_cfg=config_name)
        else:
            sc = state.get("sc", "")
            sd = state.get("sd", "")
            log.warning("Watchdog: server crashed, restarting…")
            try:
                from app.services import discord_notifier
                discord_notifier.notify_crash(config_name, restarting=auto_restart)
            except Exception:
                pass
            try:
                with open(_LOG_FILE, "a", encoding="utf-8") as lf:
                    lf.write("\n[watchdog] Server crash detected — restarting…\n")
            except Exception:
                pass
            proc = _launch(exe, sc, sd)
            if proc:
                _write_state(proc.pid, config_name, sc, sd, auto_restart, run_id=run_id)
                log.info("Watchdog: restarted with PID %d", proc.pid)
            else:
                log.error("Watchdog: restart failed")

    log.info("Watchdog stopped")


def _start_watchdog():
    global _watchdog_thread, _watchdog_stop
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_watchdog_loop, daemon=True, name="server-watchdog"
    )
    _watchdog_thread.start()


def init_watchdog(exe_path: str):
    global _exe_path
    _exe_path = exe_path
    if _DEPLOY_MODE == "docker":
        threading.Thread(target=_prewarm_wine, daemon=True, name="wine-prewarm").start()
    else:
        _wine_ready.set()
    _start_watchdog()


# ── Public API ───────────────────────────────────────────────────────────────

def is_running() -> bool:
    if _DEPLOY_MODE == "docker_split":
        # L'intention de faire tourner le serveur est indiquée par le fichier de config
        if not _launch_config_path().exists():
            return False
        container = _get_aceserver_container()
        if not container:
            return False
        try:
            container.reload()
        except Exception:
            return False
        return container.status == "running"

    # native / docker
    state = _read_state()
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


def get_player_count() -> int | None:
    state = _read_state()
    if _DEPLOY_MODE == "docker_split":
        port = state.get("http_port", 8080)
        url  = f"http://{_ACESERVER_HOST}:{port}/"
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
                 config_name: str, auto_restart: bool = False) -> dict:
    if is_running():
        return {"ok": False, "error": "server_already_running"}

    # Identifiant unique pour ce run — toutes les sessions de ce démarrage partageront ce run_id.
    # Généré ici (démarrage explicite admin/scheduler), jamais recalculé par le watchdog.
    run_id = uuid.uuid4().hex

    if _DEPLOY_MODE == "docker_split":
        lcp = _launch_config_path()
        lcp.write_text(json.dumps({
            "serverconfig":    serverconfig_b64,
            "seasondefinition": seasondefinition_b64,
        }))
        try:
            container = _get_aceserver_container()
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
                         auto_restart, http_port, run_id=run_id)
            return {"ok": True, "pid": 0, "config": config_name, "run_id": run_id}
        except Exception as e:
            lcp.unlink(missing_ok=True)
            return {"ok": False, "error": str(e)}

    # native / docker
    exe       = Path(current_app.config["ACESERVER_EXE_PATH"])
    http_port = current_app.config.get("ACESERVER_HTTP_PORT", 8080)
    proc = _launch(exe, serverconfig_b64, seasondefinition_b64)
    if not proc:
        return {"ok": False, "error": "launch_failed"}
    _write_state(proc.pid, config_name, serverconfig_b64, seasondefinition_b64,
                 auto_restart, http_port, run_id=run_id)
    return {"ok": True, "pid": proc.pid, "config": config_name, "run_id": run_id}


def stop_server() -> dict:
    if _DEPLOY_MODE == "docker_split":
        # Supprimer la config de lancement avant d'arrêter le container
        _launch_config_path().unlink(missing_ok=True)
        try:
            container = _get_aceserver_container()
            if container:
                container.stop(timeout=10)
        except Exception as e:
            log.warning("stop_server docker_split : %s", e)
        _clear_state()
        return {"ok": True, "error": None}

    # native / docker
    state  = _read_state()
    pid    = state.get("pid")
    killed = False
    if pid:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=10)
            killed = True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
    if not killed:
        for proc in psutil.process_iter(["name", "pid", "cmdline"]):
            if _proc_matches(proc):
                psutil.Process(proc.info["pid"]).terminate()
                killed = True
                break
    _clear_state()
    return {"ok": killed, "error": None if killed else "process_not_found"}


def set_auto_restart(enabled: bool) -> dict:
    state = _read_state()
    if not state:
        return {"ok": False, "error": "server_not_running"}
    _set_auto_restart(enabled)
    return {"ok": True, "auto_restart": enabled}


def get_server_logs(lines: int = 100) -> str:
    if _DEPLOY_MODE == "docker_split":
        try:
            container = _get_aceserver_container()
            if not container:
                return ""
            raw = container.logs(tail=lines, timestamps=False)
            return raw.decode("utf-8", errors="replace")
        except Exception as e:
            log.debug("get_server_logs docker_split : %s", e)
            return ""

    if not _LOG_FILE.exists():
        return ""
    try:
        text = _LOG_FILE.read_text(encoding="utf-8", errors="replace")
        tail = text.strip().splitlines()[-lines:]
        return "\n".join(tail)
    except Exception:
        return ""


def get_status() -> dict:
    running = is_running()
    state   = _read_state()
    players = get_player_count() if running else None
    return {
        "running":      running,
        "pid":          state.get("pid") if running else None,
        "config":       state.get("config") if running else None,
        "run_id":       state.get("run_id") if running else None,
        "auto_restart": state.get("auto_restart", False),
        "players":      players,
    }
