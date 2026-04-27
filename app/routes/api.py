import logging

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

log = logging.getLogger(__name__)
from app.services.server_config import (
    load_config, apply_server_patch, load_cars, load_events,
    list_configs, get_active_config_name, set_active_config,
    create_config, delete_config, check_config, repair_config,
)

from app.services.process_manager import start_server, stop_server, get_status, get_server_logs, set_auto_restart, _ensure_race_weekend_file
from pathlib import Path
from app.services import config_builder

api_bp = Blueprint("api", __name__)


# ── Serveur ──────────────────────────────────────────────────────────────────

@api_bp.route("/status")
def status():
    data = get_status()
    if not (current_user.is_authenticated and current_user.is_admin):
        data = {"running": data.get("running"), "players": data.get("players")}
    return jsonify(data)


@api_bp.route("/server/logs")
@login_required
def server_logs():
    if not current_user.is_admin:
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"logs": get_server_logs()})


def _do_start(auto_restart: bool = False) -> dict:
    status = get_status()
    if status["running"] and status["config"] != get_active_config_name():
        stop_server()
    config = load_config()

    if config["Event"].get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        exe = Path(current_app.config["ACESERVER_EXE_PATH"])
        _ensure_race_weekend_file(exe)

    sc, sd = config_builder.build_launch_args(config)
    result = start_server(sc, sd, get_active_config_name(), auto_restart=auto_restart)

    if result.get("ok"):
        try:
            from app.services import discord_notifier
            discord_notifier.notify_start(config, get_active_config_name())
        except Exception:
            pass

    return result


@api_bp.route("/server/start", methods=["POST"])
@login_required
def server_start():
    try:
        data = request.get_json(silent=True) or {}
        result = _do_start(auto_restart=bool(data.get("auto_restart", False)))
    except Exception as e:
        log.exception("Server action failed")
        result = {"ok": False, "error": str(e)}
    return jsonify(result)


@api_bp.route("/server/auto-restart", methods=["POST"])
@login_required
def server_auto_restart():
    data = request.get_json(force=True) or {}
    enabled = bool(data.get("enabled", False))
    return jsonify(set_auto_restart(enabled))


@api_bp.route("/server/stop", methods=["POST"])
@login_required
def server_stop():
    config_name = get_status().get("config") or get_active_config_name()
    result = stop_server()
    if result.get("ok"):
        try:
            from app.services import discord_notifier
            discord_notifier.notify_stop(config_name)
        except Exception:
            pass
    return jsonify(result)


@api_bp.route("/server/restart", methods=["POST"])
@login_required
def server_restart():
    prev_auto_restart = get_status().get("auto_restart", False)
    stop_server()
    try:
        result = _do_start(auto_restart=prev_auto_restart)
    except Exception as e:
        log.exception("Server action failed")
        result = {"ok": False, "error": str(e)}
    return jsonify(result)


# ── Config active ─────────────────────────────────────────────────────────────

@api_bp.route("/config", methods=["GET"])
@login_required
def get_config():
    return jsonify(load_config())


@api_bp.route("/config", methods=["POST"])
@login_required
def post_config():
    patch = request.get_json(force=True) or {}
    updated = apply_server_patch(patch, is_superadmin=current_user.is_superadmin)
    return jsonify({"ok": True, "config": updated})


# ── Gestion des fichiers de config ───────────────────────────────────────────

@api_bp.route("/configs", methods=["GET"])
@login_required
def get_configs():
    return jsonify({
        "configs": list_configs(),
        "active": get_active_config_name(),
    })


@api_bp.route("/configs/select", methods=["POST"])
@login_required
def select_config():
    name = (request.get_json(force=True) or {}).get("name", "")
    if set_active_config(name):
        return jsonify({"ok": True, "active": name})
    return jsonify({"ok": False, "error": "not_found"}), 404


@api_bp.route("/configs/create", methods=["POST"])
@login_required
def create_config_route():
    data = request.get_json(force=True) or {}
    name = data.get("name", "").strip()
    copy_from = data.get("copy_from")
    if not name:
        return jsonify({"ok": False, "error": "name_required"}), 400
    return jsonify(create_config(name, copy_from))


@api_bp.route("/configs/delete", methods=["POST"])
@login_required
def delete_config_route():
    name = (request.get_json(force=True) or {}).get("name", "")
    return jsonify(delete_config(name))


# ── Réparation de config ─────────────────────────────────────────────────────

@api_bp.route("/config/check", methods=["GET"])
@login_required
def config_check():
    issues = check_config()
    return jsonify({"ok": len(issues) == 0, "issues": issues})


@api_bp.route("/config/repair", methods=["POST"])
@login_required
def config_repair():
    return jsonify(repair_config())


# ── Données de référence ─────────────────────────────────────────────────────

@api_bp.route("/cars")
@login_required
def get_cars():
    return jsonify(load_cars())


@api_bp.route("/events/<mode>")
@login_required
def get_events(mode):
    if mode not in ("practice", "race"):
        return jsonify({"error": "invalid mode"}), 400
    return jsonify(load_events(mode))
