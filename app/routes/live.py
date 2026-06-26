"""
Live session monitoring — streame les logs du serveur ACE EVO en temps réel
et expose une API de l'état courant de la session.
"""
import json
import os
import re
import time
import logging
from flask import Blueprint, render_template, Response, stream_with_context, jsonify, request, session, redirect, url_for
from flask_login import login_required
from flask_babel import _
from app import limiter
from app.utils import admin_required

log = logging.getLogger(__name__)

live_bp = Blueprint("live", __name__)

_DEPLOY_MODE       = os.environ.get("DEPLOY_MODE", "native")
_CONTAINER         = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")
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

# ── Log parsers ───────────────────────────────────────────────────────────────

_RE_TS      = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
# connect : capture steam_id, car_model, car_id (optionnel)
_RE_CONNECT = re.compile(
    r'\[gameplay\] \[info\] (\d+) connected \([^)]+\) on car ([^,\s]+)'
    r'(?:, with new carId ([0-9a-f-]+))?'
)
# Capture car_id depuis Car [<uuid>] pour fallback si connect ne matche pas
_RE_DRIVER  = re.compile(r'\[server\] \[info\] Car \[([0-9a-f-]+)\] #(\d+) for driver (.+?) \[(\d+)\]')
_RE_PLAYERS = re.compile(r'\[server\] \[info\] Server updated: (\d+) players')
_RE_DISCONN = re.compile(r'\[gameplay\] \[info\] (\d+) disconnected')
_RE_SPLIT   = re.compile(r'\[gameplay\] \[info\] Outplap split')
_RE_NEWLAP  = re.compile(r'\[gameplay\] \[info\] New lap carId ([0-9a-f-]+): (\d+:\d+\.\d+)')
_RE_SECTORC = re.compile(
    r'\[gameplay\] \[info\] Split completed for car ([0-9a-f-]+): \((\d+) ms, splitindex (\d+)\)'
)


def _parse_lapstr(s: str) -> int:
    """'2:33.982' → millisecondes."""
    try:
        parts = s.split(':')
        mins  = int(parts[0])
        rest  = parts[1].split('.')
        secs  = int(rest[0])
        ms    = int(rest[1]) if len(rest) > 1 else 0
        return mins * 60000 + secs * 1000 + ms
    except Exception:
        return 0


def _fmt_ms(ms: int | None) -> str | None:
    if not ms:
        return None
    m   = ms // 60000
    s   = (ms % 60000) // 1000
    rem = ms % 1000
    return f"{m}:{s:02d}.{rem:03d}"


def _fmt_sector(ms: int | None) -> str | None:
    if not ms:
        return None
    s  = ms // 1000
    cs = ms % 1000
    return f"{s}.{cs:03d}"


def _parse_line(line: str) -> dict | None:
    ts_m = _RE_TS.match(line)
    ts   = ts_m.group(1) if ts_m else ""

    if m := _RE_CONNECT.search(line):
        return {"type": "connect", "ts": ts,
                "steam_id": m.group(1), "car_raw": m.group(2),
                "car_id": m.group(3) or ""}
    if m := _RE_DRIVER.search(line):
        return {"type": "driver", "ts": ts,
                "car_id": m.group(1), "num": m.group(2),
                "name": m.group(3), "steam_id": m.group(4)}
    if m := _RE_DISCONN.search(line):
        return {"type": "disconnect", "ts": ts, "steam_id": m.group(1)}
    if m := _RE_PLAYERS.search(line):
        return {"type": "players", "ts": ts, "count": int(m.group(1))}
    if _RE_SPLIT.search(line):
        return {"type": "split", "ts": ts}
    return None


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


def _container_name(server_id: int) -> str:
    """Retourne le nom du container Docker pour le server_id donné."""
    if server_id == 1:
        return _CONTAINER
    try:
        from app.models import Server
        srv = Server.query.get(server_id)
        if srv and srv.container_name:
            return srv.container_name
    except Exception:
        pass
    return _CONTAINER


def _iter_log_lines(since_hours: int = 12, server_id: int = 1):
    """Yield log lines. docker_split → Docker SDK ; native → log file."""
    if _DEPLOY_MODE == "docker_split":
        try:
            import docker as _docker
            import time as _time
            client    = _docker.from_env()
            container = client.containers.get(_container_name(server_id))
            since_ts  = int(_time.time()) - since_hours * 3600
            raw = container.logs(stream=False, since=since_ts)
            if isinstance(raw, bytes):
                yield raw.decode("utf-8", errors="replace")
            else:
                for chunk in raw:
                    yield chunk.decode("utf-8", errors="replace")
        except Exception as e:
            log.warning("live: docker logs error (server=%d): %s", server_id, e)
    else:
        from app.services.process_manager import _log_file
        try:
            with open(_log_file(server_id), encoding="utf-8", errors="replace") as f:
                yield from f
        except Exception as e:
            log.warning("live: log file error (server=%d): %s", server_id, e)


def _iter_log_stream(server_id: int = 1):
    """Generator that yields new log lines indefinitely (docker_split only)."""
    if _DEPLOY_MODE != "docker_split":
        return
    try:
        import docker as _docker
        import time as _time
        client    = _docker.from_env()
        container = client.containers.get(_container_name(server_id))
        for chunk in container.logs(stream=True, follow=True, since=int(_time.time()) - 5):
            yield chunk.decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("live stream error: %s", e)


# ── Build current session state ───────────────────────────────────────────────

_state_cache: dict[int, tuple[float, dict]] = {}
_STATE_TTL = 10.0  # seconds — aligns with the 15s client poll interval


def _build_state_cached(server_id: int = 1) -> dict:
    """Returns a cached _build_state() result, re-parsed at most every _STATE_TTL seconds."""
    now = time.monotonic()
    cached = _state_cache.get(server_id)
    if cached and now - cached[0] < _STATE_TTL:
        return cached[1]
    state = _build_state(server_id)
    _state_cache[server_id] = (now, state)
    return state


def _build_state(server_id: int = 1) -> dict:
    """Parse recent logs → drivers connectés, events, leaderboard avec historique tours/secteurs."""
    car_to_steam:    dict[str, str]   = {}
    pending_connect: dict[str, dict]  = {}
    drivers:         dict[str, dict]  = {}
    # Ordered timeline per car: {"type":"sector","idx":N,"ms":M} | {"type":"lap","ms":M}
    car_timeline:    dict[str, list]  = {}
    events:          list[dict]       = []
    player_count = 0

    for raw_line in _iter_log_lines(since_hours=24, server_id=server_id):
        for line in raw_line.splitlines():
            if m := _RE_NEWLAP.search(line):
                car_id = m.group(1)
                lap_ms = _parse_lapstr(m.group(2))
                if lap_ms > 0:
                    car_timeline.setdefault(car_id, []).append({"type": "lap", "ms": lap_ms})
                continue

            if m := _RE_SECTORC.search(line):
                car_timeline.setdefault(m.group(1), []).append(
                    {"type": "sector", "idx": int(m.group(3)), "ms": int(m.group(2))}
                )
                continue

            ev = _parse_line(line)
            if not ev:
                continue

            t = ev["type"]
            if t == "connect":
                pending_connect[ev["steam_id"]] = ev
                if ev.get("car_id"):
                    car_to_steam[ev["car_id"]] = ev["steam_id"]
            elif t == "driver":
                sid    = ev["steam_id"]
                pc     = pending_connect.pop(sid, {})
                car_id = pc.get("car_id") or ev.get("car_id", "")
                car_raw = pc.get("car_raw", "")
                if car_id:
                    car_to_steam[car_id] = sid
                drivers[sid] = {
                    "steam_id":  sid,
                    "name":      ev["name"],
                    "num":       ev["num"],
                    "car_raw":   car_raw,
                    "car_id":    car_id,
                    "joined_ts": pc.get("ts") or ev["ts"],
                }
                events.append({"type": "connect", "ts": ev["ts"],
                                "name": ev["name"], "car_raw": car_raw})
            elif t == "disconnect":
                sid = ev["steam_id"]
                driver = drivers.pop(sid, {})
                events.append({"type": "disconnect", "ts": ev["ts"],
                                "name": driver.get("name", sid)})
            elif t == "players":
                player_count = ev["count"]
                if player_count == 0:
                    # Server restarted or session ended — start fresh
                    drivers.clear()
                    pending_connect.clear()
                    car_to_steam.clear()
                    car_timeline.clear()
            elif t == "split":
                events.append({"type": "split", "ts": ev["ts"]})

    def _car_laps(car_id: str):
        """Returns (laps_list, curr_s1_ms, curr_s2_ms).
        Sectors preceding each lap completion are assigned to that lap.
        Remaining sectors = current in-progress lap.
        """
        laps: list[dict] = []
        pending: list[dict] = []
        for ev in car_timeline.get(car_id, []):
            if ev["type"] == "sector":
                pending.append(ev)
            else:
                s1 = next((s["ms"] for s in pending if s["idx"] == 0), None)
                s2 = next((s["ms"] for s in pending if s["idx"] == 1), None)
                lms = ev["ms"]
                s3  = (lms - s1 - s2) if (s1 is not None and s2 is not None) else None
                laps.append({
                    "lap_num": len(laps) + 1,
                    "lap_ms":  lms, "lap_str": _fmt_ms(lms),
                    "s1_ms":   s1,  "s1_str":  _fmt_sector(s1),
                    "s2_ms":   s2,  "s2_str":  _fmt_sector(s2),
                    "s3_ms":   s3,  "s3_str":  _fmt_sector(s3),
                })
                pending = []
        curr_s1 = next((s["ms"] for s in pending if s["idx"] == 0), None)
        curr_s2 = next((s["ms"] for s in pending if s["idx"] == 1), None)
        return laps, curr_s1, curr_s2

    # ── Leaderboard ──────────────────────────────────────────────────────────
    leaderboard = []
    for sid, d in drivers.items():
        laps, cs1, cs2 = _car_laps(d.get("car_id", ""))
        lap_times = [l["lap_ms"] for l in laps if l["lap_ms"]]
        best_ms   = min(lap_times, default=None)
        last_ms   = laps[-1]["lap_ms"] if laps else None
        # Personal best par secteur (min individuel, pas forcément du meilleur tour)
        pb_s1_ms  = min((l["s1_ms"] for l in laps if l.get("s1_ms")), default=None)
        pb_s2_ms  = min((l["s2_ms"] for l in laps if l.get("s2_ms")), default=None)
        pb_s3_ms  = min((l["s3_ms"] for l in laps if l.get("s3_ms")), default=None)
        leaderboard.append({
            **d,
            "laps":         laps,
            "lap_count":    len(laps),
            "best_lap_ms":  best_ms,
            "best_lap_str": _fmt_ms(best_ms),
            "last_lap_ms":  last_ms,
            "last_lap_str": _fmt_ms(last_ms),
            # Personal bests secteur (pour coloration violet/vert)
            "pb_s1_ms": pb_s1_ms, "pb_s1_str": _fmt_sector(pb_s1_ms),
            "pb_s2_ms": pb_s2_ms, "pb_s2_str": _fmt_sector(pb_s2_ms),
            "pb_s3_ms": pb_s3_ms, "pb_s3_str": _fmt_sector(pb_s3_ms),
            # Secteurs du tour en cours
            "curr_s1_ms": cs1, "curr_s1_str": _fmt_sector(cs1),
            "curr_s2_ms": cs2, "curr_s2_str": _fmt_sector(cs2),
        })

    leaderboard.sort(key=lambda x: (x["best_lap_ms"] is None, x["best_lap_ms"] or 0))

    # Merge lap_invalid depuis le client TCP (keyed by steam_id)
    try:
        from app.services.ace_tcp_client import get_leaderboard as _tcp_lb
        tcp_by_sid = {e["steam_id"]: e for e in _tcp_lb(server_id)}
        for entry in leaderboard:
            tcp = tcp_by_sid.get(entry["steam_id"], {})
            entry["lap_invalid"] = tcp.get("lap_invalid", False)
    except Exception:
        pass

    leader_ms = leaderboard[0]["best_lap_ms"] if leaderboard and leaderboard[0]["best_lap_ms"] else None
    for entry in leaderboard:
        if leader_ms and entry["best_lap_ms"]:
            gap = entry["best_lap_ms"] - leader_ms
            entry["gap_str"] = f"+{_fmt_ms(gap)}" if gap > 0 else "—"
        else:
            entry["gap_str"] = None

    # Session bests (meilleur secteur tous pilotes confondus)
    sess_s1 = min((e["pb_s1_ms"] for e in leaderboard if e.get("pb_s1_ms")), default=None)
    sess_s2 = min((e["pb_s2_ms"] for e in leaderboard if e.get("pb_s2_ms")), default=None)
    sess_s3 = min((e["pb_s3_ms"] for e in leaderboard if e.get("pb_s3_ms")), default=None)

    return {
        "drivers":      list(drivers.values()),
        "leaderboard":  leaderboard,
        "events":       events[-50:],
        "player_count": player_count,
        "sess_s1_ms":   sess_s1,
        "sess_s2_ms":   sess_s2,
        "sess_s3_ms":   sess_s3,
    }


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
    return jsonify(_build_state_cached(_get_server_id()))


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
    except Exception:
        return {}


@live_bp.route("/api/timing")
@limiter.limit("120 per minute")
def timing_state():
    """API publique — classement en temps réel (pas de données sensibles)."""
    from flask import url_for
    from app.services.server_config import get_running_server_info
    from app.services.track_map import get_track_svg_name
    from app.services.kspkg_reader import get_car_name

    sid     = _get_server_id()
    state   = _build_state_cached(sid)
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
        sid = _get_server_id()
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
    sid = _get_server_id()
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


@live_bp.route("/api/live/stream")
@login_required
def live_stream():
    """SSE endpoint — envoie les nouveaux événements au fil des logs."""
    sid = _get_server_id()
    def _generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        for raw_line in _iter_log_stream(sid):
            for line in raw_line.splitlines():
                ev = _parse_line(line)
                if ev:
                    yield f"data: {json.dumps(ev)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
