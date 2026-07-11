"""
Live session monitoring — streame les logs du serveur ACE EVO en temps réel
et expose une API de l'état courant de la session.
"""
import re
import logging
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
from flask_login import current_user, login_required
from flask_babel import _
from app import limiter
from app.utils import admin_required

log = logging.getLogger(__name__)

live_bp = Blueprint("live", __name__)

from app.services import live_state as _live_state

_DEPLOY_MODE = _live_state._DEPLOY_MODE
# Clés i18n des messages de réaction — Flask-Babel traduit selon Accept-Language du spectateur
_REACTION_MSGIDS = {
    "🏁": "Beau tour !",
    "👍": "Bien joué !",
    "❤️": "Courage !",
    "🔥": "En feu !",
    "💪": "Bravo !",
    "⚡": "Allez !",
}
_ALLOWED_REACTIONS  = set(_REACTION_MSGIDS.keys())
_RE_DRIVER_SAFE     = re.compile(r'[^\w\s\-\'\.]', re.UNICODE)
# Champs internes non exposés sur l'API publique /api/timing
_TIMING_STRIP_FIELDS = {"steam_id", "car_id", "joined_ts"}


def _get_server_id() -> int:
    """Returns the current server_id.
    Query param ?server=<id> takes priority (for public/spectator pages),
    then falls back to session (admin pages).
    """
    try:
        qp = request.args.get("server")
        if qp:
            return max(1, int(qp))
        return int(session.get("current_server_id", 1) or 1)
    except (ValueError, RuntimeError):
        return 1


def _get_public_server_id() -> int:
    """Comme _get_server_id(), mais retombe sur le premier serveur activé si l'id demandé
    ne correspond à aucun serveur avec is_enabled=True (évite l'énumération de serveurs
    désactivés/non publics via ?server=<id> sur les endpoints anonymes)."""
    from app.models import Server
    sid = _get_server_id()
    public_servers = Server.query.filter_by(is_enabled=True).order_by(Server.sort_order).all()
    if any(s.id == sid for s in public_servers):
        return sid
    return public_servers[0].id if public_servers else sid


# ── Routes ────────────────────────────────────────────────────────────────────

@live_bp.route("/live")
@login_required
def live_page():
    return redirect(url_for('live.timing_page'))


@live_bp.route("/timing")
def timing_page():
    """Page publique de classement en temps réel."""
    from app.models import Server
    from app.services.process_manager import is_running
    sid            = _get_server_id()
    public_servers = Server.query.filter_by(is_enabled=True).order_by(Server.sort_order).all()
    active_server  = next((s for s in public_servers if s.id == sid), None) or (public_servers[0] if public_servers else None)
    if active_server:
        sid = active_server.id
    running_ids = {s.id for s in public_servers if is_running(s.id)}
    return render_template("timing.html",
                           active_server=active_server,
                           active_server_id=sid,
                           public_servers=public_servers,
                           server_running_ids=running_ids)


@live_bp.route("/api/live/state")
@login_required
def live_state():
    state = _live_state.build_state_cached(_get_server_id())
    if not current_user.is_admin:
        strip = _TIMING_STRIP_FIELDS
        state = {
            **state,
            "leaderboard": [{k: v for k, v in e.items() if k not in strip}
                            for e in state.get("leaderboard", [])],
            "drivers":     [{k: v for k, v in d.items() if k not in strip}
                            for d in state.get("drivers", [])],
        }
    return jsonify(state)


def _session_timing(server_id: int = 1) -> dict:
    """Retourne started_at et session_length_s depuis le state + config."""
    try:
        from app.services.process_manager import _read_state
        from app.services.server_config import load_config_by_name
        st = _read_state(server_id)
        started_at = st.get("started_at")
        cfg_name   = st.get("config")
        if not cfg_name:
            return {}
        cfg  = load_config_by_name(cfg_name) or {}
        ev   = cfg.get("Event", {})
        ses  = cfg.get("Sessions", {})
        mode = ev.get("SelectedSessionTypeValue", "")
        if mode == "GameModeType_RACE_WEEKEND":
            length_s = (
                ses.get("PracticeSession",   {}).get("Length", 0) +
                ses.get("QualifyingSession", {}).get("Length", 0) +
                ses.get("WarmupSession",     {}).get("Length", 0) +
                ses.get("RaceSession",       {}).get("Length", 0)
            )
        elif mode == "GameModeType_QUALIFY":
            length_s = ses.get("QualifyingSession", {}).get("Length", 0)
        else:
            length_s = ses.get("PracticeSession", {}).get("Length", 0)
        return {"started_at": started_at, "session_length_s": length_s}
    except Exception as _e:
        log.warning("session_time_info failed : %s", _e)
        return {}


@live_bp.route("/api/timing")
@limiter.limit("120 per minute")
def timing_state():
    """API publique — classement en temps réel (pas de données sensibles)."""
    from flask import url_for
    from app.services.server_config import get_running_server_info
    from app.services.track_map import get_track_svg_name
    from app.services.kspkg_reader import get_car_name

    sid     = _get_public_server_id()
    state   = _live_state.build_state_cached(sid)
    timing  = _session_timing(sid)

    for entry in state["leaderboard"]:
        entry["car_display_name"] = get_car_name(entry.get("car_raw", ""))

    track_svg_url = None
    track_label   = None
    srv_info = get_running_server_info(sid)
    if srv_info:
        svg_name = get_track_svg_name(srv_info.get("track_name", ""),
                                      srv_info.get("track_layout", ""))
        if svg_name:
            track_svg_url = url_for("static", filename=f"img/tracks/{svg_name}.svg")
        track_label = srv_info.get("circuit")

    safe_lb = [
        {k: v for k, v in entry.items() if k not in _TIMING_STRIP_FIELDS}
        for entry in state["leaderboard"]
    ]
    return jsonify({
        "leaderboard":      safe_lb,
        "player_count":     state["player_count"],
        "started_at":       timing.get("started_at"),
        "session_length_s": timing.get("session_length_s"),
        "sess_s1_ms":       state.get("sess_s1_ms"),
        "sess_s2_ms":       state.get("sess_s2_ms"),
        "sess_s3_ms":       state.get("sess_s3_ms"),
        "track_svg_url":    track_svg_url,
        "track_label":      track_label,
    })


@live_bp.route("/api/live/bot/elevate-admin", methods=["POST"])
@admin_required
def bot_elevate_admin():
    """Envoie \\admin <password> au serveur via le bot TCP, même si ACE_BOT_IS_ADMIN=false."""
    from app.services.ace_tcp_client import elevate_admin
    err = elevate_admin()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@live_bp.route("/api/live/chat-history")
@limiter.limit("60 per minute")
def live_chat_history():
    """API publique — historique récent du chat in-game."""
    try:
        from app.services.ace_tcp_client import get_chat_history
        sid = _get_public_server_id()
        return jsonify({"messages": get_chat_history(sid)})
    except Exception as e:
        log.warning("live_chat_history error: %s", e)
        return jsonify({"messages": []})


@live_bp.route("/api/timing/react", methods=["POST"])
@limiter.limit("10 per minute")
def timing_react():
    """Réaction emoji spectateur → tchat in-game. Whitelist stricte, rate-limitée."""
    data     = request.get_json(silent=True) or {}
    reaction = str(data.get("reaction", "")).strip()
    if reaction not in _ALLOWED_REACTIONS:
        return jsonify({"ok": False, "error": "invalid_reaction"}), 400
    sid = _get_public_server_id()
    from app.services.ace_tcp_client import send_chat, is_connected
    if not is_connected(sid):
        return jsonify({"ok": False, "error": "not_connected"}), 503
    msg_text   = _(_REACTION_MSGIDS[reaction])   # traduit selon Accept-Language du spectateur
    driver_raw = str(data.get("driver", "")).strip()
    if driver_raw:
        driver = _RE_DRIVER_SAFE.sub("", driver_raw)[:30].strip()
        msg = f"@{driver} {msg_text} [Spec]" if driver else f"{msg_text} [Spec]"
    else:
        msg = f"{msg_text} [Spec]"
    ok = send_chat(msg, sid)
    return jsonify({"ok": ok})


