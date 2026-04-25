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

_webhook_url: str        = ""
_pilots_webhook_url: str = ""

_MODE_LABELS = {
    "GameModeType_PRACTICE":     "Practice",
    "GameModeType_QUALIFY":      "Qualifying",
    "GameModeType_RACE_WEEKEND": "Race Weekend",
}

_COLOR_GREEN  = 0x2ECC71
_COLOR_RED    = 0xE74C3C
_COLOR_ORANGE = 0xE67E22


def init(webhook_url: str, pilots_webhook_url: str = ""):
    global _webhook_url, _pilots_webhook_url
    _webhook_url        = webhook_url
    _pilots_webhook_url = pilots_webhook_url


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
    if _webhook_url:
        _post_to(_webhook_url, payload)


def _send_pilots(payload: dict):
    url = _pilots_webhook_url or _webhook_url
    if url:
        _post_to(url, payload)


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


def test_webhook(url: str) -> dict:
    """Envoi synchrone pour le bouton de test — retourne {"ok": bool, "error": str|None}."""
    if not url:
        return {"ok": False, "error": "URL vide"}
    payload = {"embeds": [{
        "title":  "Test webhook AC EVO Panel",
        "color":  0x3498DB,
        "description": "La configuration Discord fonctionne correctement.",
        "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
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
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    circuit  = event.circuit_display or event.circuit or "—"
    fields   = [
        {"name": "Circuit",  "value": circuit,           "inline": True},
        {"name": "Mode",     "value": event.mode_display, "inline": True},
        {"name": "Météo",    "value": event.weather_display, "inline": True},
        {"name": "Date",     "value": date_str,          "inline": False},
    ]
    if event.description:
        fields.append({"name": "Infos", "value": event.description, "inline": False})
    _send_pilots({"embeds": [{
        "title":       f"🏁 {event.title} — Départ dans 30 minutes !",
        "color":       0xE67E22,
        "fields":      fields,
        "footer":      {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
    }]})


def notify_new_registration(driver):
    _send_pilots({"embeds": [{
        "title":  "Nouvelle demande d'inscription pilote",
        "color":  0x3498DB,
        "fields": [
            {"name": "Nom in-game", "value": driver.ingame_name, "inline": True},
            {"name": "Email",       "value": driver.email,       "inline": True},
        ],
        "footer": {"text": datetime.now().strftime("%d/%m/%Y %H:%M")},
    }]})
