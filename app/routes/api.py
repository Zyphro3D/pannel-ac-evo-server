import json
import logging
import hmac
import hashlib
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app, session
from flask_login import login_required, current_user
from app import limiter

from app.services.server_config import (
    load_config, apply_server_patch, load_cars, load_events,
    list_configs, get_active_config_name, set_active_config,
    create_config, delete_config, check_config, repair_config,
    get_running_server_info, load_config_by_name, rename_config,
    inject_global_server_settings, deploy_config, _current_server_id,
)
from app.services.process_manager import (
    start_server, stop_server, get_status, get_server_logs,
    set_auto_restart, _ensure_race_weekend_file, try_rotation_advance,
    update_session_state, get_player_history, get_container_stats,
    get_server_raw_state,
)
from app.services.rotation_manager import get_rotation, save_rotation
from app.services import config_builder, discord_notifier
from app.models import SessionResult
from app.services.database import db
from app.services.results_parser import parse_result_file, scan_and_import, get_parsed
from app.utils import admin_required_json as _admin_required_json

log = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


def _verify_ingest_signature(raw_body: bytes) -> bool:
    secret = (current_app.config.get("RESULTS_INGEST_SECRET") or "").encode()
    if not secret:
        log.warning(
            "Ingest rejeté : RESULTS_INGEST_SECRET non configuré — définir dans les paramètres (%s)",
            request.remote_addr,
        )
        return False
    provided = (
        request.headers.get("X-ACE-Signature")
        or request.headers.get("X-Webhook-Signature")
        or request.headers.get("X-Hub-Signature-256")
        or ""
    ).strip()
    if provided.startswith("sha256="):
        provided = provided.split("=", 1)[1]
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


# ── Serveur ──────────────────────────────────────────────────────────────────

@api_bp.route("/status")
@limiter.limit("120 per minute")
def status():
    sid  = _current_server_id()
    data = get_status(sid)
    if not (current_user.is_authenticated and current_user.is_admin):
        data = {
            "running":    data.get("running"),
            "players":    data.get("players"),
            "started_at": data.get("started_at"),
            "history":    get_player_history(sid)[-30:],
        }
    else:
        if data.get("running"):
            info = get_running_server_info(sid)
            if info:
                if info.get("is_race_weekend"):
                    dur = f"Q:{info['qualifying_dur']} R:{info['race_dur']}"
                else:
                    dur = info["practice_dur"]
                data["nav_label"] = f"{info['circuit']} — {info['mode']} — {dur}"
    return jsonify(data)


@api_bp.route("/server/logs")
@_admin_required_json
def server_logs():
    sid = _current_server_id()
    return jsonify({"logs": get_server_logs(server_id=sid)})


@api_bp.route("/server/container-stats")
@_admin_required_json
def server_container_stats():
    sid   = _current_server_id()
    stats = get_container_stats(sid)
    if stats is None:
        return jsonify({"available": False})
    return jsonify({"available": True, **stats})


def _do_start(auto_restart: bool = False, server_id: int = 1) -> dict:
    st = get_status(server_id)
    if st["running"] and st["config"] != get_active_config_name():
        stop_server(server_id)
    config = load_config()

    if config["Event"].get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        try:
            exe = Path(current_app.config["ACESERVER_EXE_PATH"])
            _ensure_race_weekend_file(exe)
        except Exception as e:
            log.warning("_ensure_race_weekend_file failed: %s", e)

    inject_global_server_settings(config)

    # Ports et nom propres au serveur (multi-serveur : chaque serveur a son port externe)
    from app.models import Server as _Server
    server = db.session.get(_Server, server_id)
    if server is None:
        return {"ok": False, "error": "Serveur introuvable"}
    tcp_port    = server.tcp_port
    udp_port    = server.udp_port
    server_name = server.name

    # Déploie la config dans server-{id}/ avec les bons ports (tracking + rotation)
    deploy_config(get_active_config_name(), server_id)

    serverconfig_b64, seasondefinition_b64 = config_builder.build_launch_args(
        config, tcp_listener=tcp_port, udp_listener=udp_port, server_name=server_name)
    result = start_server(serverconfig_b64, seasondefinition_b64, get_active_config_name(),
                          auto_restart=auto_restart, server_id=server_id)

    if result.get("ok"):
        discord_notifier.safe_notify(discord_notifier.notify_start, config, get_active_config_name(),
                                     server_id=server_id, server_name=server_name or "")

    return result


@api_bp.route("/server/start", methods=["POST"])
@login_required
@_admin_required_json
def server_start():
    try:
        data = request.get_json(silent=True) or {}
        result = _do_start(auto_restart=bool(data.get("auto_restart", False)),
                           server_id=_current_server_id())
    except Exception as e:
        log.exception("Server action failed")
        result = {"ok": False, "error": str(e)}
    return jsonify(result)


@api_bp.route("/server/auto-restart", methods=["POST"])
@login_required
@_admin_required_json
def server_auto_restart():
    data = request.get_json(force=True) or {}
    enabled = bool(data.get("enabled", False))
    return jsonify(set_auto_restart(enabled, server_id=_current_server_id()))


@api_bp.route("/server/stop", methods=["POST"])
@login_required
@_admin_required_json
def server_stop():
    sid = _current_server_id()
    config_name = get_status(sid).get("config") or get_active_config_name()
    from app.models import Server as _Server
    _stop_srv = db.session.get(_Server, sid)
    result = stop_server(sid)
    if result.get("ok"):
        discord_notifier.safe_notify(discord_notifier.notify_stop, config_name,
                                     server_id=sid, server_name=_stop_srv.name if _stop_srv else "")
    return jsonify(result)


@api_bp.route("/server/restart", methods=["POST"])
@login_required
@_admin_required_json
def server_restart():
    sid = _current_server_id()
    prev_auto_restart = get_status(sid).get("auto_restart", False)
    stop_server(sid)
    try:
        result = _do_start(auto_restart=prev_auto_restart, server_id=sid)
    except Exception as e:
        log.exception("Server action failed")
        result = {"ok": False, "error": str(e)}
    return jsonify(result)


# ── Config active ─────────────────────────────────────────────────────────────

@api_bp.route("/config", methods=["GET"])
@login_required
@_admin_required_json
def get_config():
    return jsonify(load_config())


@api_bp.route("/config", methods=["POST"])
@login_required
@_admin_required_json
def post_config():
    patch = request.get_json(force=True) or {}
    updated = apply_server_patch(patch, is_superadmin=current_user.is_superadmin)
    return jsonify({"ok": True, "config": updated})


# ── Gestion des fichiers de config ───────────────────────────────────────────

@api_bp.route("/configs", methods=["GET"])
@login_required
@_admin_required_json
def get_configs():
    return jsonify({
        "configs": list_configs(),
        "active": get_active_config_name(),
    })


@api_bp.route("/configs/select", methods=["POST"])
@login_required
@_admin_required_json
def select_config():
    name = (request.get_json(force=True) or {}).get("name", "")
    if set_active_config(name):
        return jsonify({"ok": True, "active": name})
    return jsonify({"ok": False, "error": "not_found"}), 404


@api_bp.route("/configs/create", methods=["POST"])
@login_required
@_admin_required_json
def create_config_route():
    data = request.get_json(force=True) or {}
    name = data.get("name", "").strip()
    copy_from = data.get("copy_from")
    if not name:
        return jsonify({"ok": False, "error": "name_required"}), 400
    return jsonify(create_config(name, copy_from))


@api_bp.route("/configs/<name>", methods=["GET"])
@login_required
@_admin_required_json
def get_config_by_name(name):
    if name not in list_configs():
        return jsonify({"ok": False, "error": "not_found"}), 404
    data = load_config_by_name(name)
    if data is None:
        return jsonify({"ok": False, "error": "read_error"}), 500
    return jsonify(data)


@api_bp.route("/configs/delete", methods=["POST"])
@login_required
@_admin_required_json
def delete_config_route():
    name = (request.get_json(force=True) or {}).get("name", "")
    return jsonify(delete_config(name))


@api_bp.route("/configs/rename", methods=["POST"])
@login_required
@_admin_required_json
def rename_config_route():
    data = request.get_json(force=True) or {}
    old_name = data.get("old_name", "")
    new_name = data.get("new_name", "").strip()
    if not new_name:
        return jsonify({"ok": False, "error": "name_required"}), 400
    return jsonify(rename_config(old_name, new_name))


# ── Réparation de config ─────────────────────────────────────────────────────

@api_bp.route("/config/check", methods=["GET"])
@login_required
@_admin_required_json
def config_check():
    issues = check_config()
    return jsonify({"ok": len(issues) == 0, "issues": issues})


@api_bp.route("/config/repair", methods=["POST"])
@login_required
@_admin_required_json
def config_repair():
    return jsonify(repair_config())


# ── Données de référence ─────────────────────────────────────────────────────

@api_bp.route("/cars")
@login_required
@_admin_required_json
def get_cars():
    return jsonify(load_cars())


@api_bp.route("/events/<mode>")
@login_required
@_admin_required_json
def get_events(mode):
    if mode not in ("practice", "race"):
        return jsonify({"ok": False, "error": "invalid mode"}), 400
    return jsonify(load_events(mode))


# ── Résultats de session ──────────────────────────────────────────────────────

@api_bp.route("/results/ingest", methods=["POST"])
@limiter.limit("60 per hour")
def results_ingest():
    """Reçoit la notification de fin de session d'AssettoCorsaEVOServer."""
    # server_id identifie quel serveur envoie ce webhook (serveur N configure
    # ResultsPostUrl avec ?server_id=N). Défaut 1 pour rétrocompat.
    sid = int(request.args.get("server_id", 1) or 1)

    # ACE EVO peut envoyer le webhook après avoir arrêté le serveur — is_running()
    # serait False et get_status() retournerait config=None. On lit l'état brut
    # directement pour conserver config_name et run_id même si le container vient
    # de s'arrêter.
    _raw_state = get_server_raw_state(sid)
    _st = get_status(sid)
    current_config = _st.get("config") or _raw_state.get("config") or None
    current_run_id = _st.get("run_id")  or _raw_state.get("run_id")  or None

    raw_body = request.get_data(cache=True) or b""
    if not _verify_ingest_signature(raw_body):
        return jsonify({"ok": False, "error": "invalid_signature"}), 403

    imported = 0
    data = request.get_json(silent=True)
    final_session_type = ""

    if data:
        raw_str  = json.dumps(data)
        raw_hash = hashlib.sha256(raw_str.encode()).hexdigest()
        parsed   = parse_result_file(data)
        if SessionResult.query.filter_by(raw_json_hash=raw_hash).first():
            log.info("Résultats webhook en double ignorés (hash=%s…)", raw_hash[:8])
        else:
            result = SessionResult(
                raw_json=raw_str,
                raw_json_hash=raw_hash,
                source="webhook",
                track=parsed["track"][:200],
                session_type=parsed["session_type"][:60],
                config_name=current_config,
                run_id=current_run_id,
                server_id=sid,
            )
            db.session.add(result)
            db.session.commit()
            log.info("Résultats reçus via webhook : track=%r type=%r config=%r run=%r id=%d",
                     parsed["track"], parsed["session_type"], current_config, current_run_id, result.id)
            imported = 1
            try:
                from app.routes.leaderboard import invalidate_circuits_cache
                invalidate_circuits_cache()
            except Exception:
                pass
        final_session_type = parsed["session_type"]
    else:
        log.info("results/ingest: body vide, scan du dossier aceserver (run=%r)", current_run_id)
        aceserver_dir = current_app.config.get("ACESERVER_DIR", "/aceserver")
        imported = scan_and_import(aceserver_dir, config_name=current_config,
                                   run_id=current_run_id, server_id=sid)
        if not imported:
            log.warning("results/ingest: aucun nouveau fichier trouvé après scan")
        else:
            last_r = (SessionResult.query
                      .filter_by(run_id=current_run_id)
                      .order_by(SessionResult.received_at.desc())
                      .first())
            if last_r:
                final_session_type = last_r.session_type or ""

    if imported and current_config:
        try_rotation_advance(final_session_type, current_config, server_id=sid)

    if imported and final_session_type:
        try:
            update_session_state(final_session_type, server_id=sid)
        except Exception as e:
            log.warning("update_session_state failed: %s", e)

    return jsonify({"ok": True, "imported": imported})


@api_bp.route("/results")
@login_required
def get_results():
    """Retourne les 50 dernières sessions avec classement parsé."""
    rows = (SessionResult.query
            .order_by(SessionResult.received_at.desc())
            .limit(50).all())
    out = []
    for r in rows:
        try:
            parsed = get_parsed(r)
        except Exception as e:
            log.warning("Failed to parse result id=%s: %s", r.id, e)
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
@_admin_required_json
def rotation_start():
    """Démarre le serveur sur le premier fichier du roulement."""
    sid = _current_server_id()
    rot = get_rotation()
    if not rot.get("enabled") or not rot.get("configs"):
        return jsonify({"ok": False, "error": "rotation_disabled_or_empty"}), 400

    first_cfg = rot["configs"][0]
    cfg_data  = load_config_by_name(first_cfg)
    if cfg_data is None:
        return jsonify({"ok": False, "error": "config_not_found", "name": first_cfg}), 404

    cfg_data.setdefault("Server", {})["IsCycleEnabled"] = False

    # Déploie toutes les configs du cycle dans server-{id}/ avec les bons ports
    for _cfg_name in rot["configs"]:
        deploy_config(_cfg_name, sid)

    if get_status(sid)["running"]:
        stop_server(sid)

    if cfg_data.get("Event", {}).get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND":
        try:
            exe = Path(current_app.config["ACESERVER_EXE_PATH"])
            _ensure_race_weekend_file(exe)
        except Exception as e:
            log.warning("_ensure_race_weekend_file failed: %s", e)

    inject_global_server_settings(cfg_data)
    sc, sd = config_builder.build_launch_args(cfg_data)
    result  = start_server(sc, sd, first_cfg, auto_restart=False, server_id=sid)

    if result.get("ok"):
        from app.models import Server as _Server
        _rot_srv = db.session.get(_Server, sid)
        discord_notifier.safe_notify(
            discord_notifier.notify_rotation_start, rot["configs"], bool(rot.get("cycle")),
            server_id=sid, server_name=_rot_srv.name if _rot_srv else "",
        )

    return jsonify(result)


@api_bp.route("/rotation", methods=["GET"])
@login_required
@_admin_required_json
def get_rotation_route():
    return jsonify(get_rotation())


@api_bp.route("/rotation", methods=["POST"])
@login_required
@_admin_required_json
def post_rotation_route():
    data = request.get_json(force=True) or {}
    save_rotation(data)
    return jsonify({"ok": True})


@api_bp.route("/results/<int:result_id>")
@login_required
def get_result(result_id):
    """Retourne le détail complet d'une session."""
    r = db.get_or_404(SessionResult, result_id)
    parsed = get_parsed(r)
    return jsonify({
        "id":           r.id,
        "received_at":  r.received_at.isoformat(),
        "source":       r.source,
        "parsed":       parsed,
        "raw":          json.loads(r.raw_json),
    })


# ── Client TCP — chat in-game ─────────────────────────────────────────────────

@api_bp.route("/live/chat", methods=["POST"])
@_admin_required_json
def live_chat():
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400
    if len(text) > 200:
        return jsonify({"ok": False, "error": "too_long"}), 400
    try:
        from app.services import ace_tcp_client
        sid  = max(1, int(request.args.get("server") or session.get("current_server_id") or 1))
        sent = ace_tcp_client.send_chat(text, sid)
        return jsonify({"ok": sent, "error": None if sent else "not_connected"})
    except Exception as e:
        log.warning("live_chat error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@api_bp.route("/live/tcp_status")
@_admin_required_json
def live_tcp_status():
    try:
        from app.services import ace_tcp_client
        sid = max(1, int(request.args.get("server") or session.get("current_server_id") or 1))
        return jsonify({
            "connected":   ace_tcp_client.is_connected(sid),
            "leaderboard": ace_tcp_client.get_leaderboard(sid),
        })
    except Exception as e:
        return jsonify({"connected": False, "leaderboard": [], "error": str(e)})


@api_bp.route("/live/admin_cmd", methods=["POST"])
@_admin_required_json
def live_admin_cmd():
    """Envoie une commande admin in-game via le chat TCP."""
    data    = request.get_json(force=True) or {}
    cmd     = (data.get("cmd") or "").strip().lower()
    car_num = str(data.get("car_num", "")).strip()
    extra   = str(data.get("extra", "")).strip()

    VALID = {"kick", "to_pit", "mute", "unmute", "add_time",
             "add_penalty", "del_penalty", "ballast", "restrictor", "skip"}
    if cmd not in VALID:
        return jsonify({"ok": False, "error": "invalid_cmd"}), 400

    if cmd == "skip":
        msg = "\\skip"
    elif car_num:
        msg = f"\\{cmd} {car_num}" + (f" {extra}" if extra else "")
    else:
        return jsonify({"ok": False, "error": "car_num_required"}), 400

    try:
        from app.services import ace_tcp_client
        _cmd_sid = _current_server_id()
        sent = ace_tcp_client.send_chat(msg, _cmd_sid)
        log.info("admin_cmd: %r → sent=%s", msg, sent)
        if sent:
            try:
                from app.services import discord_notifier
                from app.models import Server as _Server
                _cmd_srv  = db.session.get(_Server, _cmd_sid)
                driver = ace_tcp_client.get_driver_by_num(car_num) if car_num else {}
                discord_notifier.safe_notify(
                    discord_notifier.notify_admin_action,
                    cmd,
                    driver.get("name", "?"),
                    car_num,
                    extra,
                    current_user.username,
                    server_id=_cmd_sid,
                    server_name=_cmd_srv.name if _cmd_srv else "",
                )
            except Exception as _e:
                log.debug("Discord admin_action notification skipped : %s", _e)
        return jsonify({"ok": sent, "cmd": msg,
                        "error": None if sent else "not_connected"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@api_bp.route("/live/tcp_debug")
@_admin_required_json
def live_tcp_debug():
    """Endpoint de diagnostic : retourne les données brutes reçues via TCP."""
    try:
        from app.services import ace_tcp_client
        from app.routes.live import _build_state_cached
        state     = _build_state_cached()
        tcp_lb    = ace_tcp_client.get_leaderboard()
        log_sids  = [d.get('steam_id') for d in state.get('drivers', [])]
        tcp_sids  = [e.get('steam_id') for e in tcp_lb]
        return jsonify({
            "tcp_connected":  ace_tcp_client.is_connected(),
            "log_steam_ids":  log_sids,
            "tcp_steam_ids":  tcp_sids,
            "tcp_leaderboard": tcp_lb,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
