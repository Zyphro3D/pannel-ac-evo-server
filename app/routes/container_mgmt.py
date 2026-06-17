"""Gestion du conteneur de jeu ACE EVO — statut, redémarrage, mise à jour SteamCMD."""
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_babel import _
from flask_login import login_required

from app.utils import admin_required

container_mgmt_bp = Blueprint("container_mgmt", __name__)

_ACF_RE   = re.compile(r'"(\w+)"\s+"([^"]*)"')
_APPID    = "4564210"
_updating = threading.Lock()  # empêche les lancements simultanés


def _acf_path() -> str:
    aceserver_dir = os.environ.get("ACESERVER_DIR", "/aceserver")
    return os.path.join(aceserver_dir, "steamapps", f"appmanifest_{_APPID}.acf")


def _parse_acf() -> dict:
    result = {}
    try:
        with open(_acf_path()) as f:
            for m in _ACF_RE.finditer(f.read()):
                result[m.group(1)] = m.group(2)
    except Exception:
        pass
    return result


def _container_name() -> str:
    from app.services.process_manager import _DOCKER_CONTAINER_NAME
    return _DOCKER_CONTAINER_NAME


def _get_container_status() -> dict:
    try:
        import docker as _docker
        client = _docker.from_env()
        c = client.containers.get(_container_name())
        started = c.attrs["State"].get("StartedAt", "")
        started_dt = None
        if started:
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            except Exception:
                pass
        uptime_s = None
        if started_dt:
            uptime_s = int((datetime.now(timezone.utc) - started_dt).total_seconds())
        return {
            "status":    c.status,
            "started_at": started,
            "uptime_s":  uptime_s,
        }
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


@container_mgmt_bp.route("/api/container/info")
@login_required
def container_info():
    acf    = _parse_acf()
    status = _get_container_status()
    installed  = acf.get("buildid", "?")
    target     = acf.get("TargetBuildID", installed)
    last_upd   = acf.get("LastUpdated", "")
    last_upd_dt = ""
    if last_upd.isdigit():
        try:
            last_upd_dt = datetime.fromtimestamp(int(last_upd), tz=timezone.utc).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return jsonify({
        "container":      status,
        "installed_build": installed,
        "target_build":   target,
        "update_pending": installed != target and target != "?",
        "last_updated":   last_upd_dt,
        "updating":       not _updating.acquire(blocking=False) or (_updating.release() or False),
    })


@container_mgmt_bp.route("/api/container/restart", methods=["POST"])
@admin_required
def container_restart():
    try:
        import docker as _docker
        client = _docker.from_env()
        c = client.containers.get(_container_name())
        c.restart(timeout=15)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@container_mgmt_bp.route("/api/container/update", methods=["POST"])
@admin_required
def container_update():
    if not _updating.acquire(blocking=False):
        return jsonify({"error": _("Mise à jour déjà en cours")}), 409

    data          = request.get_json(silent=True) or {}
    steamcmd      = current_app.config.get("STEAMCMD_PATH",  "/opt/steamcmd/steamcmd.sh")
    aceserver_dir = current_app.config.get("ACESERVER_DIR", "/aceserver")
    steam_user    = (data.get("username") or current_app.config.get("STEAM_USERNAME", "anonymous")).strip() or "anonymous"
    steam_pass    = (data.get("password") or "").strip()
    steam_guard   = (data.get("guard_code") or "").strip()
    appid         = _APPID

    def _gen():
        try:
            import docker as _docker

            def _msg(text, done=False, error=False):
                return f"data: {json.dumps({'msg': text, 'done': done, 'error': error})}\n\n"

            # 1 — Arrêt du conteneur
            yield _msg("⏹ Arrêt du serveur de jeu...")
            try:
                client = _docker.from_env()
                c = client.containers.get(_container_name())
                c.stop(timeout=20)
                yield _msg("✓ Serveur arrêté")
            except Exception as e:
                yield _msg(f"✗ Impossible d'arrêter le serveur : {e}", error=True, done=True)
                return

            # 2 — SteamCMD
            if not os.path.exists(steamcmd):
                yield _msg(f"✗ SteamCMD introuvable : {steamcmd}", error=True)
            else:
                login_args = ["+login", steam_user]
                if steam_pass:
                    login_args.append(steam_pass)
                if steam_guard:
                    login_args.append(steam_guard)
                yield _msg(f"⬇ Lancement de SteamCMD (compte : {steam_user})...")
                cmd = [
                    steamcmd,
                    "+force_install_dir", aceserver_dir,
                    *login_args,
                    "+app_update",        appid,
                    "+quit",
                ]
                # HOME isolé pour éviter les conflits avec la session Steam du host
                steam_home = "/tmp/steamcmd_session"
                os.makedirs(steam_home, exist_ok=True)
                try:
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1,
                        env={**os.environ, "HOME": steam_home},
                    )
                    for line in proc.stdout:
                        line = line.rstrip()
                        if line:
                            yield _msg(line)
                    proc.wait()
                    rc = proc.returncode
                    if rc == 0:
                        yield _msg("✓ SteamCMD terminé avec succès")
                    else:
                        yield _msg(f"⚠ SteamCMD code de sortie : {rc}")
                except Exception as e:
                    yield _msg(f"✗ Erreur SteamCMD : {e}", error=True)

            # 3 — Redémarrage
            yield _msg("🚀 Redémarrage du serveur...")
            try:
                c.start()
                yield _msg("✓ Serveur redémarré", done=True)
            except Exception as e:
                yield _msg(f"✗ Erreur redémarrage : {e}", error=True, done=True)
        finally:
            _updating.release()

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
