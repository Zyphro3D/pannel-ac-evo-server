import logging

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

log = logging.getLogger(__name__)
from app.services.server_config import (
    load_config, apply_server_patch, load_cars, load_events,
    list_configs, get_active_config_name, set_active_config,
    create_config, delete_config, check_config, repair_config,
    get_running_server_info,
)

from app.services.process_manager import start_server, stop_server, get_status, get_server_logs, set_auto_restart, _ensure_race_weekend_file, try_rotation_advance
from pathlib import Path
from app.services import config_builder

api_bp = Blueprint("api", __name__)


# ── Serveur ──────────────────────────────────────────────────────────────────

@api_bp.route("/status")
def status():
    data = get_status()
    if not (current_user.is_authenticated and current_user.is_admin):
        data = {"running": data.get("running"), "players": data.get("players")}
    else:
        if data.get("running"):
            info = get_running_server_info()
            if info:
                if info.get("is_race_weekend"):
                    dur = f"Q:{info['qualifying_dur']} R:{info['race_dur']}"
                else:
                    dur = info["practice_dur"]
                data["nav_label"] = f"{info['circuit']} — {info['mode']} — {dur}"
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


@api_bp.route("/configs/<name>", methods=["GET"])
@login_required
def get_config_by_name(name):
    from app.services.server_config import load_config_by_name, list_configs
    if name not in list_configs():
        return jsonify({"error": "not_found"}), 404
    data = load_config_by_name(name)
    if data is None:
        return jsonify({"error": "read_error"}), 500
    return jsonify(data)


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


# ── Résultats de session ──────────────────────────────────────────────────────

@api_bp.route("/results/ingest", methods=["POST"])
def results_ingest():
    """Reçoit la notification de fin de session d'AssettoCorsaEVOServer.

    ACE EVO poste soit le JSON de résultats directement, soit un body vide (signal
    uniquement). Dans les deux cas on tente d'abord de parser le body, puis on
    scanne le dossier aceserver pour importer les fichiers non encore traités.
    """
    import json as _json
    from app.models import SessionResult
    from app.services.database import db
    from app.services.results_parser import parse_result_file, scan_and_import

    # Le serveur tourne encore quand ACE EVO envoie la notification de fin de session.
    # On capture run_id (unique par démarrage) et config_name pour grouper les sessions.
    _st = get_status()
    current_config = _st.get("config") or None
    current_run_id = _st.get("run_id") or None

    imported = 0
    data = request.get_json(force=True, silent=True)

    final_session_type = ""

    if data:
        # ACE EVO a envoyé le JSON directement dans le body
        parsed = parse_result_file(data)
        result = SessionResult(
            raw_json=_json.dumps(data),
            source="webhook",
            track=parsed["track"][:200],
            session_type=parsed["session_type"][:60],
            config_name=current_config,
            run_id=current_run_id,
        )
        db.session.add(result)
        db.session.commit()
        log.info("Résultats reçus via webhook : track=%r type=%r config=%r run=%r id=%d",
                 parsed["track"], parsed["session_type"], current_config, current_run_id, result.id)
        imported = 1
        final_session_type = parsed["session_type"]
    else:
        log.info("results/ingest: body vide, scan du dossier aceserver (run=%r)", current_run_id)
        aceserver_dir = current_app.config.get("ACESERVER_DIR", "/aceserver")
        imported = scan_and_import(aceserver_dir, config_name=current_config,
                                   run_id=current_run_id)
        if not imported:
            log.warning("results/ingest: aucun nouveau fichier trouvé après scan")
        else:
            # Récupérer le type de la dernière session importée pour ce run
            last_r = (SessionResult.query
                      .filter_by(run_id=current_run_id)
                      .order_by(SessionResult.received_at.desc())
                      .first())
            if last_r:
                final_session_type = last_r.session_type or ""

    # Rotation : si le roulement est actif, vérifier si on doit passer à la config suivante
    if imported and current_config:
        try_rotation_advance(final_session_type, current_config)

    return jsonify({"ok": True, "imported": imported})


@api_bp.route("/results")
@login_required
def get_results():
    """Retourne les 50 dernières sessions avec classement parsé."""
    import json as _json
    from app.models import SessionResult
    from app.services.results_parser import parse_result_file

    rows = (SessionResult.query
            .order_by(SessionResult.received_at.desc())
            .limit(50).all())
    out = []
    for r in rows:
        try:
            parsed = parse_result_file(_json.loads(r.raw_json))
        except Exception:
            parsed = {}
        out.append({
            "id":           r.id,
            "received_at":  r.received_at.isoformat(),
            "source":       r.source,
            "track":        r.track,
            "session_type": r.session_type,
            "parsed":       parsed,
        })
    return jsonify(out)


# ── Rotation de configs ───────────────────────────────────────────────────────

@api_bp.route("/rotation/start", methods=["POST"])
@login_required
def rotation_start():
    """Démarre le serveur sur le premier fichier du roulement."""
    from app.services.rotation_manager import get_rotation
    from app.services.server_config import load_config_by_name

    rot = get_rotation()
    if not rot.get("enabled") or not rot.get("configs"):
        return jsonify({"ok": False, "error": "rotation_disabled_or_empty"}), 400

    first_cfg = rot["configs"][0]
    cfg_data  = load_config_by_name(first_cfg)
    if cfg_data is None:
        return jsonify({"ok": False, "error": "config_not_found", "name": first_cfg}), 404

    # Cycle interne off — le watchdog gère l'enchaînement entre configs
    cfg_data.setdefault("Server", {})["IsCycleEnabled"] = False

    # Arrêt préalable si serveur déjà en cours
    if get_status()["running"]:
        stop_server()

    if cfg_data.get("Event", {}).get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        try:
            exe = Path(current_app.config["ACESERVER_EXE_PATH"])
            _ensure_race_weekend_file(exe)
        except Exception:
            pass

    sc, sd = config_builder.build_launch_args(cfg_data)
    result  = start_server(sc, sd, first_cfg, auto_restart=False)

    if result.get("ok"):
        try:
            from app.services import discord_notifier
            discord_notifier.notify_rotation_start(rot["configs"], bool(rot.get("cycle")))
        except Exception:
            pass

    return jsonify(result)


@api_bp.route("/rotation", methods=["GET"])
@login_required
def get_rotation_route():
    from app.services.rotation_manager import get_rotation
    return jsonify(get_rotation())


@api_bp.route("/rotation", methods=["POST"])
@login_required
def post_rotation_route():
    from app.services.rotation_manager import save_rotation
    data = request.get_json(force=True) or {}
    save_rotation(data)
    return jsonify({"ok": True})


@api_bp.route("/results/<int:result_id>")
@login_required
def get_result(result_id):
    """Retourne le détail complet d'une session."""
    import json as _json
    from app.models import SessionResult
    from app.services.results_parser import parse_result_file

    r = SessionResult.query.get_or_404(result_id)
    parsed = parse_result_file(_json.loads(r.raw_json))
    return jsonify({
        "id":           r.id,
        "received_at":  r.received_at.isoformat(),
        "source":       r.source,
        "parsed":       parsed,
        "raw":          _json.loads(r.raw_json),
    })
