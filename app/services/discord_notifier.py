"""
Sends Discord embeds via webhook on server start / stop / crash.
"""
import json
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime

log = logging.getLogger(__name__)

_webhook_url: str = ""

_MODE_LABELS = {
    "GameModeType_PRACTICE":     "Practice",
    "GameModeType_QUALIFY":      "Qualifying",
    "GameModeType_RACE_WEEKEND": "Race Weekend",
}

_COLOR_GREEN  = 0x2ECC71
_COLOR_RED    = 0xE74C3C
_COLOR_ORANGE = 0xE67E22


def init(webhook_url: str):
    global _webhook_url
    _webhook_url = webhook_url


def _send(payload: dict):
    if not _webhook_url:
        return

    def _post():
        try:
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                _webhook_url + "?wait=true", data=data,
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

    _send({"embeds": [{
        "title":       "Serveur démarré",
        "color":       _COLOR_GREEN,
        "fields":      fields,
        "footer":      {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
    }]})


def notify_stop(config_name: str):
    _send({"embeds": [{
        "title":  "Serveur arrêté",
        "color":  _COLOR_ORANGE,
        "fields": [{"name": "Config", "value": config_name or "—", "inline": True}],
        "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
    }]})


def notify_crash(config_name: str, restarting: bool = True):
    title = "Crash détecté — Relance automatique" if restarting else "Crash détecté"
    _send({"embeds": [{
        "title":  title,
        "color":  _COLOR_RED,
        "fields": [{"name": "Config", "value": config_name or "—", "inline": True}],
        "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
    }]})
