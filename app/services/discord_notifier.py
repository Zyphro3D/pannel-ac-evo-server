"""
Sends Discord embeds via webhook on server start / stop / crash.
"""
import json
import logging
import os
import re
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_tz: ZoneInfo = ZoneInfo("Europe/Paris")


def _local_now() -> str:
    return datetime.now(tz=_tz).strftime("%d/%m/%Y %H:%M")


def _utc_to_local(dt_utc: datetime) -> str:
    """Convert a naive UTC datetime to local time string with offset label."""
    dt_aware = dt_utc.replace(tzinfo=timezone.utc).astimezone(_tz)
    offset = dt_aware.strftime("%z")
    offset_fmt = f"UTC{offset[:3]}:{offset[3:]}" if len(offset) == 5 else "UTC"
    return dt_aware.strftime("%d/%m/%Y à %H:%M") + f" ({offset_fmt})"

_MODE_LABELS = {
    "GameModeType_PRACTICE":     "Practice",
    "GameModeType_QUALIFY":      "Qualifying",
    "GameModeType_RACE_WEEKEND": "Race Weekend",
}

_COLOR_GREEN  = 0x2ECC71
_COLOR_RED    = 0xE74C3C
_COLOR_ORANGE = 0xE67E22


def init(panel_timezone: str = "Europe/Paris", **_ignored):
    global _tz
    try:
        _tz = ZoneInfo(panel_timezone)
    except Exception:
        log.warning("Fuseau horaire inconnu '%s', fallback Europe/Paris", panel_timezone)
        _tz = ZoneInfo("Europe/Paris")


def _post_to(url: str, payload: dict):
    def _post():
        try:
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                url + "?wait=true", data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.warning("Discord webhook HTTP %d: %s", e.code, body)
        except Exception as e:
            log.warning("Discord webhook failed: %s", e)

    threading.Thread(target=_post, daemon=True).start()


def _send(payload: dict):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if url:
        _post_to(url, payload)


def _send_pilots(payload: dict):
    url = os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if url:
        _post_to(url, payload)


def _send_race(payload: dict):
    url = os.environ.get("DISCORD_RACE_WEBHOOK_URL", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if url:
        _post_to(url, payload)


def _tmpl(env_key: str, default: str, **kwargs) -> str:
    """Résout un template de message depuis l'env, avec substitution de variables."""
    tpl = os.environ.get(env_key, default)
    try:
        return tpl.format(**kwargs)
    except (KeyError, ValueError):
        return tpl


def _with_mention(env_key: str, embeds: list) -> dict:
    """Construit le payload Discord avec la mention optionnelle du channel."""
    payload: dict = {"embeds": embeds}
    mention = os.environ.get(env_key, "").strip()
    if mention:
        payload["content"] = mention
    return payload


def _car_label(raw: str) -> str:
    if not raw:
        return "?"
    raw = re.sub(r'^preset_', '', raw)
    raw = re.sub(r'_mech_\d+$', '', raw)
    return raw.replace('_', ' ').upper()


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "ignoré"
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h{m:02d}"
    return f"{m} min"


def notify_start(config: dict, config_name: str):
    event    = config.get("Event", {})
    sessions = config.get("Sessions", {})

    mode      = event.get("SelectedSessionTypeValue", "GameModeType_PRACTICE")
    mode_lbl  = _MODE_LABELS.get(mode, mode)

    track_val = event.get("SelectedTrackValue", "")
    parts     = track_val.split("|")
    track     = parts[0] if parts[0] else "Inconnu"
    layout    = parts[1] if len(parts) > 1 else ""
    circuit   = f"{track} — {layout}" if layout else (track or "—")

    # Cars
    cars = [c for c in event.get("Cars", []) if c.get("IsSelected") or c.get("is_selected")]
    if cars:
        car_names = ", ".join(c.get("display_name", c.get("name", "?")) for c in cars[:10])
        if len(cars) > 10:
            car_names += f" (+{len(cars)-10})"
    else:
        car_names = "Choix libre"

    # Sessions fields
    fields = [
        {"name": "Mode",     "value": mode_lbl       or "—", "inline": True},
        {"name": "Circuit",  "value": circuit        or "—", "inline": True},
        {"name": "Config",   "value": config_name    or "—", "inline": True},
    ]

    if mode == "GameModeType_RACE_WEEKEND":
        sess_map = {
            "Practice":   sessions.get("PracticeSession", {}),
            "Qualifying": sessions.get("QualifyingSession", {}),
            "Warmup":     sessions.get("WarmupSession", {}),
            "Race":       sessions.get("RaceSession", {}),
        }
        for name, sess in sess_map.items():
            dur = _fmt_duration(sess.get("Length", 0))
            fields.append({"name": name, "value": dur, "inline": True})
    else:
        sess_key = "PracticeSession" if mode == "GameModeType_PRACTICE" else "QualifyingSession"
        sess     = sessions.get(sess_key, {})
        fields.append({"name": "Durée", "value": _fmt_duration(sess.get("Length", 300)), "inline": True})

    fields.append({"name": "Véhicules", "value": car_names, "inline": False})

    title = _tmpl("DISCORD_MSG_SERVER_START", "🏁 Serveur démarré",
                  config=config_name, mode=mode_lbl, circuit=circuit)
    _send(_with_mention("DISCORD_MENTION_MAIN", [{
        "title":  title,
        "color":  _COLOR_GREEN,
        "fields": fields,
        "footer": {"text": _local_now()},
    }]))


def notify_rotation_start(configs: list, cycle: bool):
    queue = "\n".join(f"{i+1}. {c}" for i, c in enumerate(configs)) or "—"
    cycle_txt = "Oui — retour au début après le dernier" if cycle else "Non — s'arrête après le dernier"
    _send({"embeds": [{
        "title":  "🔄 Cycle de roulement lancé",
        "color":  _COLOR_GREEN,
        "fields": [
            {"name": "File d'attente",   "value": queue,     "inline": False},
            {"name": "Cycle activé",     "value": cycle_txt, "inline": False},
        ],
        "footer": {"text": _local_now()},
    }]})


def notify_rotation_advance(from_cfg: str, next_cfg: str, next_config_data: dict):
    event    = next_config_data.get("Event", {})
    sessions = next_config_data.get("Sessions", {})

    mode     = event.get("SelectedSessionTypeValue", "GameModeType_PRACTICE")
    mode_lbl = _MODE_LABELS.get(mode, mode)

    track_val = event.get("SelectedTrackValue", "")
    parts     = track_val.split("|")
    track     = parts[0] if parts[0] else "Inconnu"
    layout    = parts[1] if len(parts) > 1 else ""
    circuit   = f"{track} — {layout}" if layout else (track or "—")

    fields = [
        {"name": "Config précédente", "value": from_cfg  or "—", "inline": True},
        {"name": "Nouvelle config",   "value": next_cfg  or "—", "inline": True},
        {"name": "​",            "value": "​",          "inline": True},
        {"name": "Mode",    "value": mode_lbl or "—", "inline": True},
        {"name": "Circuit", "value": circuit  or "—", "inline": True},
    ]

    if mode == "GameModeType_RACE_WEEKEND":
        sess_map = {
            "Practice":   sessions.get("PracticeSession", {}),
            "Qualifying": sessions.get("QualifyingSession", {}),
            "Warmup":     sessions.get("WarmupSession", {}),
            "Race":       sessions.get("RaceSession", {}),
        }
        for name, sess in sess_map.items():
            fields.append({"name": name, "value": _fmt_duration(sess.get("Length", 0)), "inline": True})
    else:
        sess_key = "PracticeSession" if mode == "GameModeType_PRACTICE" else "QualifyingSession"
        sess = sessions.get(sess_key, {})
        fields.append({"name": "Durée", "value": _fmt_duration(sess.get("Length", 300)), "inline": True})

    _send({"embeds": [{
        "title":  "⏭️ Changement de config",
        "color":  _COLOR_GREEN,
        "fields": fields,
        "footer": {"text": _local_now()},
    }]})


def notify_stop(config_name: str):
    title = _tmpl("DISCORD_MSG_SERVER_STOP", "⏹ Serveur arrêté", config=config_name or "—")
    _send(_with_mention("DISCORD_MENTION_MAIN", [{
        "title":  title,
        "color":  _COLOR_ORANGE,
        "fields": [{"name": "Config", "value": config_name or "—", "inline": True}],
        "footer": {"text": _local_now()},
    }]))


def notify_crash(config_name: str, restarting: bool = True):
    default = "💥 Crash détecté — Relance auto" if restarting else "💥 Crash détecté"
    title = _tmpl("DISCORD_MSG_SERVER_CRASH", default, config=config_name or "—")
    _send(_with_mention("DISCORD_MENTION_MAIN", [{
        "title":  title,
        "color":  _COLOR_RED,
        "fields": [{"name": "Config", "value": config_name or "—", "inline": True}],
        "footer": {"text": _local_now()},
    }]))


def test_webhook(url: str) -> dict:
    """Envoi synchrone pour le bouton de test — retourne {"ok": bool, "error": str|None}."""
    if not url:
        return {"ok": False, "error": "URL vide"}
    payload = {"embeds": [{
        "title":  "Test webhook AC EVO Panel",
        "color":  0x3498DB,
        "description": "La configuration Discord fonctionne correctement.",
        "footer": {"text": _local_now()},
    }]}
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url + "?wait=true", data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return {"ok": True}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code} — {body}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def notify_event_soon(event):
    date_str = _utc_to_local(event.date)
    circuit  = event.circuit_display or event.circuit or "—"
    fields   = [
        {"name": "Circuit",  "value": circuit,              "inline": True},
        {"name": "Mode",     "value": event.mode_display,   "inline": True},
        {"name": "Météo",    "value": event.weather_display,"inline": True},
        {"name": "Date",     "value": date_str,             "inline": False},
    ]
    if event.description:
        fields.append({"name": "Infos", "value": event.description, "inline": False})
    _send_pilots({"embeds": [{
        "title":  f"🏁 {event.title} — Départ dans 30 minutes !",
        "color":  0xE67E22,
        "fields": fields,
        "footer": {"text": _local_now()},
    }]})


def notify_new_registration(driver):
    _send_pilots({"embeds": [{
        "title":  "Nouvelle demande d'inscription pilote",
        "color":  0x3498DB,
        "fields": [
            {"name": "Nom in-game", "value": driver.ingame_name, "inline": True},
            {"name": "Email",       "value": driver.email,       "inline": True},
        ],
        "footer": {"text": _local_now()},
    }]})


def notify_player_join(name: str, num: str, car_raw: str, steam_id: str):
    car   = _car_label(car_raw)
    title = _tmpl("DISCORD_MSG_PLAYER_JOIN", "🟢 {num} — {name}",
                  name=name, num=num, car=car, steam_id=steam_id)
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [{
        "title":  title,
        "color":  _COLOR_GREEN,
        "fields": [
            {"name": "Pilote",   "value": f"#{num} — {name}", "inline": True},
            {"name": "Véhicule", "value": car,                "inline": True},
        ],
        "footer": {"text": _local_now()},
    }]))


def notify_player_disconnect(name: str, steam_id: str, duration_s: int | None = None):
    dur_str = ""
    if duration_s and duration_s > 0:
        h, m, s = duration_s // 3600, (duration_s % 3600) // 60, duration_s % 60
        dur_str = f"{h}h{m:02d}" if h else (f"{m}min {s:02d}s" if m else f"{s}s")
    title  = _tmpl("DISCORD_MSG_PLAYER_DISCONNECT", "🔴 {name}",
                   name=name, duration=dur_str, steam_id=steam_id)
    fields = [{"name": "Pilote", "value": name, "inline": True}]
    if dur_str:
        fields.append({"name": "Durée", "value": dur_str, "inline": True})
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [{
        "title":  title,
        "color":  _COLOR_ORANGE,
        "fields": fields,
        "footer": {"text": _local_now()},
    }]))


def notify_vehicle_change(name: str, num: str, old_car_raw: str, new_car_raw: str):
    old_car = _car_label(old_car_raw)
    new_car = _car_label(new_car_raw)
    title   = _tmpl("DISCORD_MSG_VEHICLE_CHANGE", "🔄 {name} — Changement de véhicule",
                    name=name, num=num, old_car=old_car, new_car=new_car)
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [{
        "title":  title,
        "color":  0x3498DB,
        "fields": [
            {"name": "Pilote",          "value": f"#{num} — {name}", "inline": False},
            {"name": "Ancien véhicule", "value": old_car,            "inline": True},
            {"name": "Nouveau",         "value": new_car,            "inline": True},
        ],
        "footer": {"text": _local_now()},
    }]))


def notify_best_lap(name: str, lap_str: str, car_raw: str):
    car   = _car_label(car_raw)
    title = _tmpl("DISCORD_MSG_BEST_LAP", "⏱ Meilleur tour du serveur",
                  name=name, lap=lap_str, car=car)
    _send_race(_with_mention("DISCORD_MENTION_RACE", [{
        "title":       title,
        "color":       0x9B59B6,
        "description": f"**{lap_str}**",
        "fields": [
            {"name": "Pilote",   "value": name, "inline": True},
            {"name": "Véhicule", "value": car,  "inline": True},
        ],
        "footer": {"text": _local_now()},
    }]))


_CMD_LABELS: dict[str, tuple[str, int]] = {
    "kick":        ("Expulsion",          _COLOR_RED),
    "to_pit":      ("Envoi aux stands",   _COLOR_ORANGE),
    "mute":        ("Mise en sourdine",   _COLOR_ORANGE),
    "unmute":      ("Retrait sourdine",   0x95A5A6),
    "add_time":    ("Temps ajouté",       0x3498DB),
    "add_penalty": ("Pénalité infligée",  _COLOR_RED),
    "del_penalty": ("Pénalité retirée",   _COLOR_GREEN),
    "ballast":     ("Ballast modifié",    0x3498DB),
    "restrictor":  ("Restrictor modifié", 0x3498DB),
    "skip":        ("Phase suivante",     0x3498DB),
}

_PENALTY_LABELS = {"disq": "Disqualification", "dt": "Drive-Through", "sg": "Stop & Go"}


def notify_admin_action(cmd: str, target_name: str, car_num: str, extra: str, by_admin: str):
    label, color = _CMD_LABELS.get(cmd, (cmd, _COLOR_ORANGE))
    target = f"#{car_num} — {target_name}" if (car_num and target_name) else (target_name or f"#{car_num}" if car_num else "—")
    detail = _PENALTY_LABELS.get(extra, extra) if extra else ""
    title  = _tmpl("DISCORD_MSG_ADMIN_ACTION", "⚙️ {action} — {target}",
                   action=label, target=target, admin=by_admin, detail=detail)
    fields = [{"name": "Action", "value": label, "inline": True}]
    if target_name or car_num:
        fields.append({"name": "Cible", "value": target, "inline": True})
    if detail:
        fields.append({"name": "Détail", "value": detail, "inline": True})
    fields.append({"name": "Par", "value": by_admin, "inline": True})
    _send_race(_with_mention("DISCORD_MENTION_RACE", [{
        "title":  title,
        "color":  color,
        "fields": fields,
        "footer": {"text": _local_now()},
    }]))


def safe_notify(fn, *args, **kwargs):
    """Appelle un notifier Discord en loggant l'erreur sans propager l'exception."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        log.warning("Discord notification skipped (%s): %s", fn.__name__, e)
