"""
Start / stop / status of AssettoCorsaEVOServer.exe.
State file stores PID + config name + launch args for auto-restart watchdog.
Supports DEPLOY_MODE=native (Windows subprocess) or docker (Wine on Linux).
"""
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import psutil
from flask import current_app

_STATE_FILE   = Path(__file__).parent.parent.parent / ".server_state"
_LOG_FILE     = Path(__file__).parent.parent.parent / ".server_output.log"
_PROCESS_NAME = "AssettoCorsaEVOServer"
_DEPLOY_MODE  = os.environ.get("DEPLOY_MODE", "native")

_watchdog_thread: threading.Thread | None = None
_watchdog_stop   = threading.Event()
_exe_path: str   = ""   # set once at app startup

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
                 auto_restart: bool, http_port: int = 8080):
    _STATE_FILE.write_text(json.dumps({
        "pid": pid,
        "config": config_name,
        "sc": sc_b64,
        "sd": sd_b64,
        "auto_restart": auto_restart,
        "http_port": http_port,
    }))


def _clear_state():
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()


def _set_auto_restart(enabled: bool):
    state = _read_state()
    if state:
        state["auto_restart"] = enabled
        _STATE_FILE.write_text(json.dumps(state))


# ── Process helpers ──────────────────────────────────────────────────────────

def _proc_matches(proc: psutil.Process) -> bool:
    """Returns True if proc is the ACE EVO server process."""
    try:
        if _DEPLOY_MODE == "docker":
            # Under Wine, the exe name appears in the cmdline
            return _PROCESS_NAME in " ".join(proc.cmdline())
        return proc.is_running() and _PROCESS_NAME in proc.name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def is_running() -> bool:
    state = _read_state()
    pid = state.get("pid")
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


def _ensure_race_weekend_file(exe_path: Path) -> bool:
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


def _launch(exe: Path, sc_b64: str, sd_b64: str) -> "subprocess.Popen | None":
    """Lance le processus serveur et retourne l'objet Popen."""
    try:
        log_f = open(_LOG_FILE, "a", encoding="utf-8", errors="replace")
        if _DEPLOY_MODE == "docker":
            cmd = ["wine", str(exe), "-serverconfig", sc_b64, "-seasondefinition", sd_b64]
            return subprocess.Popen(
                cmd, cwd=str(exe.parent),
                stdout=log_f, stderr=subprocess.STDOUT,
            )
        # Native Windows
        show_console = _show_console()
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


def _show_console() -> bool:
    try:
        from flask import current_app
        return current_app.config.get("SERVER_SHOW_CONSOLE", False)
    except RuntimeError:
        return False


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop():
    global _exe_path
    log.info("Watchdog started")
    while not _watchdog_stop.wait(timeout=10):
        state = _read_state()
        if not state or not state.get("auto_restart"):
            continue

        pid = state.get("pid")
        alive = False
        if pid:
            try:
                alive = _proc_matches(psutil.Process(pid))
            except psutil.NoSuchProcess:
                pass

        if not alive:
            exe          = Path(_exe_path)
            sc           = state.get("sc", "")
            sd           = state.get("sd", "")
            config_name  = state.get("config", "")
            auto_restart = state.get("auto_restart", True)

            log.warning("Watchdog: server crashed, restarting…")
            try:
                from app.services import discord_notifier
                discord_notifier.notify_crash(config_name, restarting=auto_restart)
            except Exception:
                pass

            # Append restart marker to log
            try:
                with open(_LOG_FILE, "a", encoding="utf-8") as lf:
                    lf.write("\n[watchdog] Server crash detected — restarting…\n")
            except Exception:
                pass

            proc = _launch(exe, sc, sd)
            if proc:
                _write_state(proc.pid, config_name, sc, sd, auto_restart)
                log.info("Watchdog: restarted with PID %d", proc.pid)
            else:
                log.error("Watchdog: restart failed")

    log.info("Watchdog stopped")


def _start_watchdog():
    global _watchdog_thread, _watchdog_stop
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="server-watchdog")
    _watchdog_thread.start()


def init_watchdog(exe_path: str):
    """Appelé au démarrage de l'app Flask pour enregistrer le chemin de l'exe."""
    global _exe_path
    _exe_path = exe_path
    _start_watchdog()


# ── Public API ───────────────────────────────────────────────────────────────

def get_player_count() -> int | None:
    """Interroge l'API HTTP du serveur pour le nombre de joueurs connectés."""
    state = _read_state()
    port = state.get("http_port", 8080)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            data = json.loads(r.read())
            return data.get("clients", 0)
    except Exception:
        return None


def start_server(serverconfig_b64: str, seasondefinition_b64: str,
                 config_name: str, auto_restart: bool = False) -> dict:
    if is_running():
        return {"ok": False, "error": "server_already_running"}

    exe = Path(current_app.config["ACESERVER_EXE_PATH"])
    http_port = current_app.config.get("ACESERVER_HTTP_PORT", 8080)
    proc = _launch(exe, serverconfig_b64, seasondefinition_b64)
    if not proc:
        return {"ok": False, "error": "launch_failed"}

    _write_state(proc.pid, config_name, serverconfig_b64, seasondefinition_b64,
                 auto_restart, http_port)
    return {"ok": True, "pid": proc.pid, "config": config_name}


def stop_server() -> dict:
    state = _read_state()
    pid = state.get("pid")
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

    _clear_state()   # clear AVANT que le watchdog se réveille
    return {"ok": killed, "error": None if killed else "process_not_found"}


def set_auto_restart(enabled: bool) -> dict:
    state = _read_state()
    if not state:
        return {"ok": False, "error": "server_not_running"}
    _set_auto_restart(enabled)
    return {"ok": True, "auto_restart": enabled}


def get_server_logs(lines: int = 100) -> str:
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
        "auto_restart": state.get("auto_restart", False),
        "players":      players,
    }
