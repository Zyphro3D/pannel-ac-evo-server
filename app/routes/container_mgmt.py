"""Gestion du conteneur de jeu ACE EVO — statut, redémarrage, mise à jour SteamCMD."""
import logging
import os
import re
import threading

log = logging.getLogger(__name__)
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from flask_babel import _
from flask_login import login_required

from app.utils import admin_required, superadmin_required

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
    except Exception as _e:
        log.debug("ACF parse skipped : %s", _e)
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
@admin_required
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
        "updating":       _updating.locked(),
    })


@container_mgmt_bp.route("/api/container/restart", methods=["POST"])
@login_required
@admin_required
def container_restart():
    try:
        import docker as _docker
        client = _docker.from_env()
        c = client.containers.get(_container_name())
        c.restart(timeout=15)
        return jsonify({"ok": True})
    except Exception as e:
        log.error("container_restart error: %s", e)
        return jsonify({"ok": False, "error": _("Erreur lors du redémarrage du container")}), 500


@container_mgmt_bp.route("/api/container/update", methods=["POST"])
@superadmin_required
def container_update():
    data          = request.get_json(silent=True) or {}
    steamcmd      = current_app.config.get("STEAMCMD_PATH",  "/opt/steamcmd/steamcmd.sh")
    aceserver_dir = current_app.config.get("ACESERVER_DIR", "/aceserver")
    steam_user    = (data.get("username") or current_app.config.get("STEAM_USERNAME", "anonymous")).strip() or "anonymous"
    steam_pass    = (data.get("password") or "").strip()
    steam_guard   = (data.get("guard_code") or "").strip()

    import re as _re
    if not _re.fullmatch(r'[\w.\-@]{1,64}', steam_user):
        return jsonify({"error": _("Nom d'utilisateur Steam invalide")}), 400
    if len(steam_pass) > 128:
        return jsonify({"error": _("Mot de passe Steam trop long")}), 400
    if any(ch in steam_pass for ch in ("\n", "\r", "\x00")):
        return jsonify({"error": _("Mot de passe Steam invalide")}), 400
    if steam_guard and not _re.fullmatch(r'[A-Za-z0-9]{1,16}', steam_guard):
        return jsonify({"error": _("Code Steam Guard invalide")}), 400
    appid         = _APPID

    # Le verrou n'est acquis qu'après validation complète des entrées, pour ne jamais
    # rester bloqué (locked) si la requête est rejetée avant le début du generator SSE.
    if not _updating.acquire(blocking=False):
        return jsonify({"error": _("Mise à jour déjà en cours")}), 409

    from app.services import steam_updater

    def _gen():
        try:
            yield from steam_updater.run_update(
                steamcmd, aceserver_dir, steam_user, steam_pass, steam_guard,
                appid, _container_name(),
            )
        finally:
            _updating.release()

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
