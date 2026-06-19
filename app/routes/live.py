"""
Live session monitoring — streame les logs du serveur ACE EVO en temps réel
et expose une API de l'état courant de la session.
"""
import json
import os
import re
import logging
from flask import Blueprint, render_template, Response, stream_with_context, jsonify, request
from flask_login import login_required
from flask_babel import _
from app.utils import admin_required

log = logging.getLogger(__name__)

live_bp = Blueprint("live", __name__)

_DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "native")
_CONTAINER   = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")

# ── Log parsers ───────────────────────────────────────────────────────────────

_RE_TS      = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
# connect : capture steam_id, car_model, car_id (optionnel)
_RE_CONNECT = re.compile(
    r'\[gameplay\] \[info\] (\d+) connected \(\d+\) on car ([^,\s]+)'
    r'(?:, with new carId ([0-9a-f-]+))?'
)
_RE_DRIVER  = re.compile(r'\[server\] \[info\] Car \[[^\]]+\] #(\d+) for driver (.+?) \[(\d+)\]')
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
    m  = ms // 60000
    s  = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return f"{m}:{s:02d}.{cs:03d}"


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
                "num": m.group(1), "name": m.group(2), "steam_id": m.group(3)}
    if m := _RE_DISCONN.search(line):
        return {"type": "disconnect", "ts": ts, "steam_id": m.group(1)}
    if m := _RE_PLAYERS.search(line):
        return {"type": "players", "ts": ts, "count": int(m.group(1))}
    if _RE_SPLIT.search(line):
        return {"type": "split", "ts": ts}
    return None


def _iter_log_lines(since_hours: int = 12):
    """Yield log lines. docker_split → Docker SDK ; native → log file."""
    if _DEPLOY_MODE == "docker_split":
        try:
            import docker as _docker
            import time as _time
            client    = _docker.from_env()
            container = client.containers.get(_CONTAINER)
            since_ts  = int(_time.time()) - since_hours * 3600
            raw = container.logs(stream=False, since=since_ts)
            if isinstance(raw, bytes):
                yield raw.decode("utf-8", errors="replace")
            else:
                for chunk in raw:
                    yield chunk.decode("utf-8", errors="replace")
        except Exception as e:
            log.warning("live: docker logs error: %s", e)
    else:
        from app.services.process_manager import _LOG_FILE
        try:
            with open(_LOG_FILE, encoding="utf-8", errors="replace") as f:
                yield from f
        except Exception as e:
            log.warning("live: log file error: %s", e)


def _iter_log_stream():
    """Generator that yields new log lines indefinitely (docker_split only)."""
    if _DEPLOY_MODE != "docker_split":
        return
    try:
        import docker as _docker
        import time as _time
        client    = _docker.from_env()
        container = client.containers.get(_CONTAINER)
        for chunk in container.logs(stream=True, follow=True, since=int(_time.time()) - 5):
            yield chunk.decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("live stream error: %s", e)


# ── Build current session state ───────────────────────────────────────────────

def _build_state() -> dict:
    """Parse recent logs → drivers connectés, events, leaderboard avec historique tours/secteurs."""
    car_to_steam:    dict[str, str]   = {}
    pending_connect: dict[str, dict]  = {}
    drivers:         dict[str, dict]  = {}
    # Ordered timeline per car: {"type":"sector","idx":N,"ms":M} | {"type":"lap","ms":M}
    car_timeline:    dict[str, list]  = {}
    events:          list[dict]       = []
    player_count = 0

    for raw_line in _iter_log_lines(since_hours=24):
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
                sid = ev["steam_id"]
                pc  = pending_connect.pop(sid, {})
                drivers[sid] = {
                    "steam_id":  sid,
                    "name":      ev["name"],
                    "num":       ev["num"],
                    "car_raw":   pc.get("car_raw", ""),
                    "car_id":    pc.get("car_id", ""),
                    "joined_ts": pc.get("ts") or ev["ts"],
                }
                events.append({"type": "connect", "ts": ev["ts"],
                                "name": ev["name"], "car_raw": pc.get("car_raw", "")})
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
        lap_times  = [l["lap_ms"] for l in laps if l["lap_ms"]]
        best_ms    = min(lap_times, default=None)
        last_ms    = laps[-1]["lap_ms"] if laps else None
        leaderboard.append({
            **d,
            "laps":         laps,
            "lap_count":    len(laps),
            "best_lap_ms":  best_ms,
            "best_lap_str": _fmt_ms(best_ms),
            "last_lap_ms":  last_ms,
            "last_lap_str": _fmt_ms(last_ms),
            "curr_s1_ms":   cs1,  "curr_s1_str": _fmt_sector(cs1),
            "curr_s2_ms":   cs2,  "curr_s2_str": _fmt_sector(cs2),
        })

    leaderboard.sort(key=lambda x: (x["best_lap_ms"] is None, x["best_lap_ms"] or 0))

    leader_ms = leaderboard[0]["best_lap_ms"] if leaderboard and leaderboard[0]["best_lap_ms"] else None
    for entry in leaderboard:
        if leader_ms and entry["best_lap_ms"]:
            gap = entry["best_lap_ms"] - leader_ms
            entry["gap_str"] = f"+{_fmt_ms(gap)}" if gap > 0 else "—"
        else:
            entry["gap_str"] = None

    return {
        "drivers":      list(drivers.values()),
        "leaderboard":  leaderboard,
        "events":       events[-50:],
        "player_count": player_count,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@live_bp.route("/live")
@login_required
def live_page():
    return render_template("live.html")


@live_bp.route("/timing")
def timing_page():
    """Page publique de classement en temps réel."""
    return render_template("timing.html")


@live_bp.route("/api/live/state")
@login_required
def live_state():
    return jsonify(_build_state())


def _session_timing() -> dict:
    """Retourne started_at et session_length_s depuis le state + config."""
    try:
        from app.services.process_manager import _read_state
        from app.services.server_config import load_config_by_name
        st = _read_state()
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
def timing_state():
    """API publique — classement en temps réel (pas de données sensibles)."""
    state   = _build_state()
    session = _session_timing()
    return jsonify({
        "leaderboard":    state["leaderboard"],
        "player_count":   state["player_count"],
        "started_at":     session.get("started_at"),
        "session_length_s": session.get("session_length_s"),
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


@live_bp.route("/api/live/stream")
@login_required
def live_stream():
    """SSE endpoint — envoie les nouveaux événements au fil des logs."""
    def _generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        for raw_line in _iter_log_stream():
            for line in raw_line.splitlines():
                ev = _parse_line(line)
                if ev:
                    yield f"data: {json.dumps(ev)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
