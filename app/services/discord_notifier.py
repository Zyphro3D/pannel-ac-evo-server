"""
Sends Discord embeds via webhook on server start / stop / crash.
"""
import json
import logging
import os
import re
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_tz: ZoneInfo = ZoneInfo("Europe/Paris")


def _local_now() -> str:
    return datetime.now(tz=_tz).strftime("%d/%m/%Y %H:%M")


_MODE_LABELS = {
    "GameModeType_PRACTICE":     "Practice",
    "GameModeType_QUALIFY":      "Qualifying",
    "GameModeType_RACE_WEEKEND": "Race Weekend",
    "GameModeType_INSTANT_RACE": "Course instantanée",
    "GameModeType_HOTLAP":       "Tour lancé",
    "GameModeType_RALLY":        "Rallye",
    "GameModeType_A_TO_B":       "A vers B",
    "GameModeType_TEST_DRIVE":   "Test drive",
}

_COLOR_GREEN  = 0x2ECC71
_COLOR_RED    = 0xE74C3C
_COLOR_ORANGE = 0xE67E22
_COLOR_GREY   = 0x80848E   # arrêt ou départ voulu : pas une alerte
_COLOR_BLUE   = 0x3498DB
_COLOR_PURPLE = 0xA970FF   # chrono (violet = meilleur temps, comme en F1)
_COLOR_GOLD   = 0xF1C40F   # fin de session


def init(panel_timezone: str = "Europe/Paris", **_ignored):
    global _tz
    try:
        _tz = ZoneInfo(panel_timezone)
    except Exception:
        log.warning("Fuseau horaire inconnu '%s', fallback Europe/Paris", panel_timezone)
        _tz = ZoneInfo("Europe/Paris")


def _post_to(url: str, payload: dict, on_sent=None):
    """Envoi en arrière-plan. `on_sent(message_id)` est appelé une fois le message publié,
    pour pouvoir le modifier ensuite (?wait=true fait renvoyer le message par Discord)."""
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        log.warning("Discord webhook URL invalide ou non autorisée : %r", url[:60] if url else "")
        return

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
            with urllib.request.urlopen(req, timeout=5) as resp:
                if on_sent:
                    msg_id = str(json.loads(resp.read() or b"{}").get("id", ""))
                    if msg_id.isdigit():
                        on_sent(msg_id)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.warning("Discord webhook HTTP %d: %s", e.code, body)
        except Exception as e:
            log.warning("Discord webhook failed: %s", e)

    threading.Thread(target=_post, daemon=True).start()


def _edit_message(url: str, msg_id: str, payload: dict):
    """Modifie en arrière-plan un message déjà publié par ce webhook."""
    if not url.startswith("https://discord.com/api/webhooks/") or not msg_id.isdigit():
        return

    def _patch():
        try:
            req = urllib.request.Request(
                f"{url}/messages/{msg_id}", data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
                },
                method="PATCH",
            )
            urllib.request.urlopen(req, timeout=5).close()
        except urllib.error.HTTPError as e:
            log.warning("Discord webhook (modification) HTTP %d: %s", e.code, e.read().decode("utf-8", errors="replace"))
        except Exception as e:
            log.warning("Discord webhook (modification) failed: %s", e)

    threading.Thread(target=_patch, daemon=True).start()


_WEBHOOK_DB_FIELD = {
    "DISCORD_WEBHOOK_URL":        "discord_webhook_main",
    "DISCORD_PILOTS_WEBHOOK_URL": "discord_webhook_pilots",
    "DISCORD_RACE_WEBHOOK_URL":   "discord_webhook_race",
}


def _resolve_url(server_id: int | None, env_key: str, fallback_env_key: str = "") -> str:
    """Résout le webhook : DB du serveur > env var spécifique > env var générale.
    Les appels depuis un thread background (bot TCP) n'ont pas de contexte Flask —
    on en ouvre un via process_manager._db_context() pour que les webhooks par-serveur
    configurés en DB soient quand même pris en compte (sinon ils sont silencieusement
    ignorés au profit des env vars globales).
    """
    if server_id:
        try:
            from app.services.process_manager import _db_context
            from app.models import Server
            from app.services.database import db
            with _db_context():
                srv = db.session.get(Server, server_id)
                if srv:
                    url = getattr(srv, _WEBHOOK_DB_FIELD.get(env_key, ""), "") or ""
                    if url.strip():
                        return url.strip()
        except Exception:
            pass
    url = os.environ.get(env_key, "")
    if not url and fallback_env_key:
        url = os.environ.get(fallback_env_key, "")
    return url


def _send(payload: dict, server_id: int | None = None):
    url = _resolve_url(server_id, "DISCORD_WEBHOOK_URL")
    if url:
        _post_to(url, payload)


def _send_pilots(payload: dict, server_id: int | None = None):
    url = _resolve_url(server_id, "DISCORD_PILOTS_WEBHOOK_URL", "DISCORD_WEBHOOK_URL")
    if url:
        _post_to(url, payload)


def _send_race(payload: dict, server_id: int | None = None):
    url = _resolve_url(server_id, "DISCORD_RACE_WEBHOOK_URL", "DISCORD_WEBHOOK_URL")
    if url:
        _post_to(url, payload)


def _tmpl(env_key: str, default: str, **kwargs) -> str:
    """Résout un template de message depuis l'env, avec substitution de variables."""
    tpl = os.environ.get(env_key, "").strip() or default     # champ laissé vide = texte par défaut
    try:
        return tpl.format(**kwargs)
    except (KeyError, ValueError, IndexError, AttributeError):
        return tpl


def _with_mention(env_key: str, embeds: list) -> dict:
    """Construit le payload Discord avec la mention optionnelle du channel."""
    payload: dict = {"embeds": embeds}
    mention = os.environ.get(env_key, "").strip()
    if mention:
        payload["content"] = mention
    return payload


def _embed(color: int, server_name: str = "", footer: str = "", **parts) -> dict:
    """Embed commun : le serveur en en-tête (auteur), « EvoPanel » en pied et l'heure native
    de Discord (affichée dans le fuseau et la langue de chaque lecteur). Les parties vides
    (titre, description, champs…) sont omises."""
    embed: dict = {"color": color}
    if server_name:
        embed["author"] = {"name": server_name[:256]}
    embed.update({k: v for k, v in parts.items() if v})
    embed["footer"] = {"text": f"EvoPanel · {footer}"[:2048] if footer else "EvoPanel"}
    embed["timestamp"] = datetime.now(timezone.utc).isoformat()
    return embed


# Les noms n'ouvrent jamais une ligne : inutile d'échapper # et -, qui n'agissent qu'en début de ligne.
_MD_SPECIAL = re.compile(r'([\\*_~`|\[\]])')


def _md(text: str) -> str:
    """Échappe le markdown Discord d'un texte venu des joueurs (pseudo, voiture)."""
    return _MD_SPECIAL.sub(r'\\\1', text or "")


def _pilot(name: str, steam_id: str = "") -> str:
    """Pseudo échappé, cliquable vers le profil Steam quand l'identifiant est un SteamID64."""
    if steam_id and steam_id.isdigit() and len(steam_id) == 17:
        return f"[{_md(name)}](https://steamcommunity.com/profiles/{steam_id})"
    return _md(name)


def _app_ctx():
    """Contexte Flask pour lire cars.json ou la base depuis un thread de fond (bot TCP, watchdog)."""
    import contextlib
    try:
        from flask import has_app_context
        if not has_app_context():
            from app.services.process_manager import _db_context
            return _db_context()
    except Exception:
        pass
    return contextlib.nullcontext()


def _car_label(raw: str) -> str:
    """Nom lisible d'une voiture (« BMW M3 E30 Evo III ») depuis son slug ou son preset."""
    if not raw:
        return "?"
    slug = re.sub(r'_mech_\d+$', '', raw)
    bare = re.sub(r'^preset_', '', slug)
    try:
        from app.services.kspkg_reader import get_car_name, slug_to_name
        # get_car_name retombe sur slug_to_name quand aucune table ne connaît le slug :
        # on n'accepte que les vrais noms, en essayant le preset complet puis la voiture.
        with _app_ctx():
            for candidate in dict.fromkeys((raw, slug, bare)):
                name = get_car_name(candidate)
                if name and name != slug_to_name(candidate):
                    return name
        return slug_to_name(bare)
    except Exception:
        return bare.replace('_', ' ').upper()


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "ignoré"
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h{m:02d}"
    return f"{m} min"


def _fmt_stay(seconds: int | None) -> str:
    """Durée de présence d'un pilote : « 7 min 48 s », « 1 h 05 », « 40 s »."""
    if not seconds or seconds <= 0:
        return ""
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f"{h} h {m:02d}"
    return f"{m} min {s:02d} s" if m else f"{s} s"


def _fmt_lap_ms(ms: int) -> str:
    m, rest = divmod(int(ms), 60000)
    return f"{m}:{rest // 1000:02d}.{rest % 1000:03d}"


def _pilots_online(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n} pilote en ligne" if n == 1 else f"{n} pilotes en ligne"


# (libellé, abréviation, clé dans Sessions) — ordre d'un Race Weekend
_SESSION_KEYS = (("Practice", "P", "PracticeSession"), ("Qualif", "Q", "QualifyingSession"),
                 ("Warmup", "W", "WarmupSession"), ("Course", "R", "RaceSession"))


def _config_summary(config: dict) -> tuple[str, str, list[tuple[str, str, int]]]:
    """(mode lisible, circuit, programme) d'une config. Le programme ne garde que les
    sessions jouées : [(libellé, abréviation, durée en s)]."""
    event    = config.get("Event", {})
    sessions = config.get("Sessions", {})
    mode     = event.get("SelectedSessionTypeValue", "GameModeType_PRACTICE")
    parts    = event.get("SelectedTrackValue", "").split("|")
    track    = parts[0] if parts[0] else "Inconnu"
    layout   = parts[1] if len(parts) > 1 else ""
    circuit  = f"{track} — {layout}" if layout else track
    if mode == "GameModeType_RACE_WEEKEND":
        programme = [(lbl, short, sessions.get(key, {}).get("Length", 0)) for lbl, short, key in _SESSION_KEYS]
    else:
        key = "PracticeSession" if mode == "GameModeType_PRACTICE" else "QualifyingSession"
        programme = [("Durée", "", sessions.get(key, {}).get("Length", 300))]
    return _MODE_LABELS.get(mode, mode), circuit, [p for p in programme if p[2] > 0]


def _programme_inline(programme: list) -> str:
    """`Q 20 min` → `W 10 min` → `R 40 min`"""
    return " → ".join(f"`{short} {_fmt_duration(sec)}`" if short else f"`{_fmt_duration(sec)}`"
                      for _lbl, short, sec in programme)


def _programme_compact(programme: list) -> str:
    """Q20 W10 R40 (minutes), pour les tableaux."""
    return " ".join(f"{short}{sec // 60}" if short else f"{sec // 60} min" for _lbl, short, sec in programme)


def _load_named_config(name: str) -> dict | None:
    if not name:
        return None
    try:
        from app.services.server_config import load_config_by_name
        with _app_ctx():
            return load_config_by_name(name)
    except Exception:
        return None


def _circuit_of(config_name: str) -> str:
    cfg = _load_named_config(config_name)
    return _config_summary(cfg)[1] if cfg else ""


def notify_start(config: dict, config_name: str, server_id: int | None = None, server_name: str = ""):
    mode_lbl, circuit, programme = _config_summary(config)

    cars = [c for c in config.get("Event", {}).get("Cars", []) if c.get("IsSelected") or c.get("is_selected")]
    names = [(c.get("display_name") or c.get("name", "?")).rsplit(" - ", 1)[0] for c in cars]
    car_names = " · ".join(_md(n) for n in names[:12]) or "Choix libre"
    if len(names) > 12:
        car_names += f" · +{len(names) - 12}"

    desc = mode_lbl
    if programme:
        desc += "\n```\n" + "\n".join(f"{lbl:<9}{_fmt_duration(sec)}" for lbl, _s, sec in programme) + "\n```"
    title = _tmpl("DISCORD_MSG_SERVER_START", "🏁 En ligne · {circuit}",
                  config=config_name, mode=mode_lbl, circuit=circuit)
    _send(_with_mention("DISCORD_MENTION_MAIN", [_embed(
        _COLOR_GREEN, server_name, config_name, title=title, description=desc,
        fields=[{"name": f"Voitures ({len(names)})" if names else "Voitures",
                 "value": car_names[:1024], "inline": False}],
    )]), server_id=server_id)


def notify_rotation_start(configs: list, cycle: bool, server_id: int | None = None, server_name: str = ""):
    rows, total, complete = [], 0, True
    for i, name in enumerate(configs[:15]):
        cfg = _load_named_config(name)
        if cfg:
            _mode, circuit, programme = _config_summary(cfg)
            total += sum(sec for _l, _s, sec in programme)
            progr = _programme_compact(programme)
        else:
            circuit, progr, complete = name, "", False
        marker = "▶" if i == 0 else " "
        rows.append(f"{marker} {i + 1:<2} {circuit[:24]:<24} {progr}".rstrip())
    if len(configs) > 15:
        rows.append(f"  … +{len(configs) - 15}")
    desc = "```\n" + "\n".join(rows) + "\n```" if rows else "—"
    if cycle and complete and total:
        h, m = divmod(total // 60, 60)
        desc += f"\n-# Un tour complet ≈ **{f'{h} h {m:02d}' if h else f'{m} min'}**"
    title = "🔄 Roulement lancé · en boucle" if cycle else "🔄 Roulement lancé · s'arrête après la dernière"
    _send({"embeds": [_embed(_COLOR_GREEN, server_name, title=title, description=desc)]}, server_id=server_id)


def _rotation_step(config_name: str) -> tuple[int, int] | None:
    try:
        from app.services.rotation_manager import get_rotation
        configs = get_rotation().get("configs", [])
        return (configs.index(config_name) + 1, len(configs)) if config_name in configs else None
    except Exception:
        return None


def notify_rotation_advance(from_cfg: str, next_cfg: str, next_config_data: dict, server_id: int | None = None, server_name: str = ""):
    mode_lbl, circuit, programme = _config_summary(next_config_data)
    previous = _circuit_of(from_cfg) or from_cfg
    lines = [f"~~{previous}~~ → **{circuit}** · {mode_lbl}" if previous else f"**{circuit}** · {mode_lbl}"]
    if programme:
        lines.append(_programme_inline(programme))
    step = _rotation_step(next_cfg)
    lines.append("-# " + " · ".join(filter(None, [
        f"étape {step[0]}/{step[1]} du roulement" if step else "", next_cfg])))
    _send({"embeds": [_embed(_COLOR_GREEN, server_name, title=f"⏭️ Place à {circuit}",
                             description="\n".join(lines))]}, server_id=server_id)


def notify_stop(config_name: str, server_id: int | None = None, server_name: str = ""):
    title = _tmpl("DISCORD_MSG_SERVER_STOP", "⏹ Serveur arrêté", config=config_name or "—")
    circuit = _circuit_of(config_name)
    desc = "\n".join(filter(None, [circuit, f"-# {config_name}" if config_name else ""]))
    _send(_with_mention("DISCORD_MENTION_MAIN", [_embed(_COLOR_GREY, server_name, title=title, description=desc)]),
          server_id=server_id)


# ── Plantage : un message qui passe au vert quand le serveur repart ─────────────
# server_id -> {"url", "msg_id", "crash_ts", "server_name", "circuit", "config", "count", "outcome"}
_crashes: dict[int, dict] = {}
_crash_lock = threading.Lock()
_crash_counts: dict[tuple[int, str], int] = {}   # (server_id, jour local) -> plantages du jour


def _crash_embed(info: dict) -> dict:
    nth = "1er plantage aujourd'hui" if info["count"] == 1 else f"{info['count']}ᵉ plantage aujourd'hui"
    where = " · ".join(filter(None, [info["circuit"], info["config"]]))
    if info["outcome"] is None:
        title = info["title"]
        desc, color = f"{where}\n-# {nth}" if where else f"-# {nth}", _COLOR_RED
    elif info["outcome"] == "ok":
        delay = max(1, int(info["recovered_ts"] - info["crash_ts"]))
        title, color = "✅ Relancé après plantage", _COLOR_GREEN
        desc = f"{info['circuit'] or info['config']} · de nouveau en ligne en **{delay} s**\n-# {nth}"
    else:
        title, color = "💥 Plantage, la relance a échoué", _COLOR_RED
        desc = f"{where}\n-# {nth} · à relancer depuis le panneau" if where else f"-# {nth}"
    embed = _embed(color, info["server_name"], title=title, description=desc)
    embed["timestamp"] = datetime.fromtimestamp(info["crash_ts"], timezone.utc).isoformat()
    return embed


def notify_crash(config_name: str, restarting: bool = True, server_id: int | None = None, server_name: str = ""):
    default = "💥 Plantage, redémarrage automatique" if restarting else "💥 Plantage du serveur"
    day = datetime.now(tz=_tz).strftime("%Y-%m-%d")
    with _crash_lock:
        key = (server_id or 0, day)
        _crash_counts[key] = _crash_counts.get(key, 0) + 1
        info = {"url": _resolve_url(server_id, "DISCORD_WEBHOOK_URL"), "msg_id": None,
                "crash_ts": time.time(), "server_name": server_name, "config": config_name or "",
                "circuit": _circuit_of(config_name), "count": _crash_counts[key], "outcome": None,
                "title": _tmpl("DISCORD_MSG_SERVER_CRASH", default, config=config_name or "—")}
        if restarting:
            _crashes[server_id or 0] = info
    if not info["url"]:
        return
    payload = _with_mention("DISCORD_MENTION_MAIN", [_crash_embed(info)])

    def _remember(msg_id: str):
        with _crash_lock:
            info["msg_id"] = msg_id
            done = info["outcome"] is not None
        if done:      # le serveur est reparti avant que Discord n'ait répondu
            _edit_message(info["url"], msg_id, {"embeds": [_crash_embed(info)]})

    _post_to(info["url"], payload, on_sent=_remember if restarting else None)


def notify_crash_recovered(server_id: int | None = None, ok: bool = True):
    """Met à jour le message de plantage : vert si le serveur est reparti, rouge sinon."""
    with _crash_lock:
        info = _crashes.pop(server_id or 0, None)
        if info is None:
            return
        info["outcome"] = "ok" if ok else "failed"
        info["recovered_ts"] = time.time()
        msg_id = info["msg_id"]
    if msg_id:
        _edit_message(info["url"], msg_id, {"embeds": [_crash_embed(info)]})


def test_webhook(url: str) -> dict:
    """Envoi synchrone pour le bouton de test — retourne {"ok": bool, "error": str|None}."""
    if not url:
        return {"ok": False, "error": "URL vide"}
    if not url.startswith("https://discord.com/api/webhooks/"):
        return {"ok": False, "error": "URL invalide — doit commencer par https://discord.com/api/webhooks/"}
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


def _server_name_of(server_id: int | None) -> str:
    if not server_id:
        return ""
    try:
        from app.models import Server
        from app.services.database import db
        with _app_ctx():
            srv = db.session.get(Server, server_id)
            return srv.name if srv else ""
    except Exception:
        return ""


def notify_event_soon(event):
    start_ts = int(event.date.replace(tzinfo=timezone.utc).timestamp())
    circuit  = event.circuit_display or event.circuit or "—"
    lines = [" · ".join(filter(None, [f"**{_md(circuit)}**", event.mode_display, event.weather_display])),
             f"Départ à **<t:{start_ts}:t>** (<t:{start_ts}:R>)"]
    if event.description:
        lines += [f"> {line}" if line.strip() else ">" for line in event.description.strip().splitlines()]
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [_embed(
        _COLOR_ORANGE, _server_name_of(getattr(event, "server_id", None)),
        title=f"🏁 {event.title} · départ dans 30 min", description="\n".join(lines)[:4096],
    )]))


def _public_panel_url() -> str:
    """PANEL_URL seulement s'il est joignable depuis Discord (https, pas une adresse locale)."""
    url = os.environ.get("PANEL_URL", "").strip().rstrip("/")
    if not url.startswith("https://"):
        return ""
    host = url[len("https://"):].split("/", 1)[0].split(":", 1)[0].lower()
    if host in ("localhost", "127.0.0.1") or host.endswith((".local", ".lan", ".home", ".internal")):
        return ""
    if re.fullmatch(r"(10|192\.168|172\.(1[6-9]|2\d|3[01]))(\.\d{1,3}){2,3}", host):
        return ""
    return url


def notify_new_registration(driver):
    lines = [f"📝 **{_md(driver.ingame_name)}** demande à s'inscrire"]
    panel = _public_panel_url()
    lines.append(f"[Ouvrir la demande]({panel}/drivers)" if panel
                 else "-# à valider dans le panneau, page Pilotes")
    _send_pilots({"embeds": [_embed(_COLOR_BLUE, description="\n".join(lines))]})


def notify_player_join(name: str, num: str, car_raw: str, steam_id: str, server_id: int | None = None,
                       server_name: str = "", online: int | None = None):
    car  = _car_label(car_raw)
    line = _tmpl("DISCORD_MSG_PLAYER_JOIN", "🟢 **{pilot}** rejoint la piste",
                 name=name, num=num, car=car, steam_id=steam_id, pilot=_pilot(name, steam_id))
    num_txt = f" · n°{num}" if num and str(num) != "0" else ""     # tout le monde a 0 en trackday
    lines = [line, f"{_md(car)}{num_txt}"]
    if online is not None:
        lines.append(f"-# {_pilots_online(online)}")
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [_embed(
        _COLOR_GREEN, server_name, description="\n".join(lines))]), server_id=server_id)


def notify_player_disconnect(name: str, steam_id: str, duration_s: int | None = None, server_id: int | None = None,
                             server_name: str = "", online: int | None = None):
    dur_str = _fmt_stay(duration_s)
    default = "🔴 **{pilot}** quitte la piste après **{duration}**" if dur_str else "🔴 **{pilot}** quitte la piste"
    line = _tmpl("DISCORD_MSG_PLAYER_DISCONNECT", default,
                 name=name, duration=dur_str, steam_id=steam_id, pilot=_md(name))
    lines = [line] + ([f"-# {_pilots_online(online)}"] if online is not None else [])
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [_embed(
        _COLOR_GREY, server_name, description="\n".join(lines))]), server_id=server_id)


def notify_vehicle_change(name: str, num: str, old_car_raw: str, new_car_raw: str, server_id: int | None = None, server_name: str = ""):
    old_car = _car_label(old_car_raw)
    new_car = _car_label(new_car_raw)
    line = _tmpl("DISCORD_MSG_VEHICLE_CHANGE", "🔄 **{pilot}** change de voiture",
                 name=name, num=num, old_car=old_car, new_car=new_car, pilot=_md(name))
    _send_pilots(_with_mention("DISCORD_MENTION_PILOTS", [_embed(
        _COLOR_BLUE, server_name, description=f"{line}\n~~{_md(old_car)}~~ → **{_md(new_car)}**",
    )]), server_id=server_id)


def notify_best_lap(name: str, lap_str: str, car_raw: str, circuit: str = "", server_id: int | None = None,
                    server_name: str = "", lap_ms: int | None = None, record: tuple | None = None):
    """Meilleur tour de la session. `record` = (ms, pseudo, voiture) : record du serveur sur
    ce tracé avant ce tour, rappelé à côté (ou battu)."""
    car = _car_label(car_raw)
    new_record = bool(lap_ms and (record is None or lap_ms < record[0]))
    default = "🏆 Nouveau record du serveur" if new_record else "⏱ Meilleur tour de la session"
    title = _tmpl("DISCORD_MSG_BEST_LAP", default, name=name, lap=lap_str, car=car, circuit=circuit)
    lines = [f"# {lap_str}", f"**{_md(name)}** · {_md(car)}"]
    if circuit:
        lines.append(f"-# {circuit}")
    fields = []
    if record:
        rec_ms, rec_name, rec_car = record
        holder = f"`{_fmt_lap_ms(rec_ms)}` · {_md(rec_name or '?')} · {_md(_car_label(rec_car))}"
        if new_record:
            fields.append({"name": "Ancien record", "inline": False,
                           "value": f"{holder}\n-# −{(rec_ms - lap_ms) / 1000:.3f} s"})
        else:
            fields.append({"name": "Record absolu", "value": holder, "inline": False})
    _send_race(_with_mention("DISCORD_MENTION_RACE", [_embed(
        _COLOR_PURPLE, server_name, title=title, description="\n".join(lines), fields=fields,
    )]), server_id=server_id)


_CMD_LABELS: dict[str, tuple[str, int, str]] = {
    "kick":        ("Expulsion",          _COLOR_RED,    "🛑"),
    "ban":         ("Bannissement",       _COLOR_RED,    "🚫"),
    "to_pit":      ("Envoi aux stands",   _COLOR_ORANGE, "🅿️"),
    "mute":        ("Mise en sourdine",   _COLOR_ORANGE, "🔇"),
    "unmute":      ("Retrait sourdine",   0x95A5A6,      "🔊"),
    "add_time":    ("Temps ajouté",       _COLOR_BLUE,   "⏱"),
    "add_penalty": ("Pénalité infligée",  _COLOR_RED,    "🚩"),
    "del_penalty": ("Pénalité retirée",   _COLOR_GREEN,  "✅"),
    "ballast":     ("Ballast modifié",    _COLOR_BLUE,   "⚖️"),
    "restrictor":  ("Restrictor modifié", _COLOR_BLUE,   "🔧"),
    "skip":        ("Phase suivante",     _COLOR_BLUE,   "⏭️"),
}

_PENALTY_LABELS = {"disq": "Disqualification", "dt": "Drive-Through", "sg": "Stop & Go"}


def notify_admin_action(cmd: str, target_name: str, car_num: str, extra: str, by_admin: str, server_id: int | None = None, server_name: str = ""):
    label, color, icon = _CMD_LABELS.get(cmd, (cmd, _COLOR_ORANGE, "⚙️"))
    target = f"#{car_num} {target_name}" if (car_num and target_name) else (target_name or (f"#{car_num}" if car_num else ""))
    detail = _PENALTY_LABELS.get(extra, extra) if extra else ""
    # Une pénalité se lit par son type (« Drive-Through pour… ») ; les autres actions
    # gardent leur libellé et ajoutent la valeur (« Ballast modifié pour… · 30 »).
    what = detail if cmd == "add_penalty" and detail else label
    brace = lambda t: t.replace("{", "{{").replace("}", "}}")      # texte inséré dans un template
    default = f"{icon} **{brace(what)}**" + (" pour **{target}**" if target else "") + \
              (f" · {brace(_md(detail))}" if detail and what != detail else "")
    line = _tmpl("DISCORD_MSG_ADMIN_ACTION", default,
                 action=label, target=_md(target) or "—", admin=by_admin, detail=detail, icon=icon)
    _send_race(_with_mention("DISCORD_MENTION_RACE", [_embed(
        color, server_name, description=f"{line}\n-# décidé par {_md(by_admin or '—')}",
    )]), server_id=server_id)


_SESSION_NAMES_FR = {"practice": "Practice", "qualify": "Qualification", "qualifying": "Qualification",
                     "warmup": "Warmup", "race": "Course"}
_MEDALS = ("🥇", "🥈", "🥉")
_MAX_PENALTY_LINES = 6
_SEVERE_PENALTIES = {"PenaltyType_Disqualification", "PenaltyType_Drive_Through", "PenaltyType_Stop_And_Go"}


def build_session_summary_embed(parsed: dict, server_name: str = "",
                                penalty_label=lambda raw: raw, investigation_label=lambda raw: raw) -> dict | None:
    """Embed Discord « fin de session » à partir d'un résultat décodé (results_parser).

    Retourne None s'il n'y a rien à annoncer (aucun pilote classé). Les libellés de sanctions
    et de causes sont fournis par l'appelant (traduits) ; sans eux, les valeurs brutes."""
    standings = [d for d in parsed.get("standings", []) if d.get("position")]
    if not standings:
        return None
    is_race = bool(parsed.get("is_race"))
    session = _SESSION_NAMES_FR.get((parsed.get("session_type") or "").strip().lower(),
                                    parsed.get("session_type") or "Session")
    circuit = parsed.get("track") or ""
    if parsed.get("layout"):
        circuit = f"{circuit} ({parsed['layout']})" if circuit else parsed["layout"]

    lines = []
    for medal, d in zip(_MEDALS, standings):
        score = d.get("race_time") if is_race else d.get("best_lap")
        if not score or score == "—":
            continue
        extra = f" ({d['gap']})" if is_race and d.get("gap") not in (None, "", "—") else ""
        lines.append(f"{medal} **{_md(d.get('nickname') or '?')}** — {score}{extra}")

    fields = []
    best_driver = next((d for d in standings if (d.get("is_fastest_lap") if is_race else d.get("is_session_fastest"))), None)
    if parsed.get("session_best_ms") and best_driver:
        fields.append({"name": "Meilleur tour", "inline": True,
                       "value": f"`{parsed.get('session_best')}` {_md(best_driver.get('nickname') or '?')}"})
    if parsed.get("has_incidents"):
        walls = sum(d.get("incident_stats", {}).get("wall", 0) + d.get("incident_stats", {}).get("object", 0)
                    for d in standings)
        fields.append({"name": "Contacts", "value": str(len(parsed.get("contacts", []))), "inline": True})
        fields.append({"name": "Chocs mur/objet", "value": str(walls), "inline": True})
    penalties = parsed.get("penalties", [])
    if penalties:
        # Regroupées par pilote (une course produit vite des dizaines d'avertissements) ; les
        # sanctions lourdes passent en premier et gardent leur cause.
        by_driver: dict[str, dict[str, int]] = {}
        severe_drivers: set[str] = set()
        for p in penalties:
            who = p.get("nickname") or "?"
            label = penalty_label(p.get("type", ""))
            if p.get("type") in _SEVERE_PENALTIES:
                label = f"{label} ({investigation_label(p.get('investigation', ''))})"
                severe_drivers.add(who)
            by_driver.setdefault(who, {})
            by_driver[who][label] = by_driver[who].get(label, 0) + 1
        ordered = sorted(by_driver, key=lambda w: (w not in severe_drivers, -sum(by_driver[w].values()), w.lower()))
        shown = ["• **{}** · {}".format(_md(w), ", ".join(f"{n}× {lab}" if n > 1 else lab
                                                         for lab, n in by_driver[w].items()))
                 for w in ordered[:_MAX_PENALTY_LINES]]
        if len(ordered) > _MAX_PENALTY_LINES:
            shown.append(f"… +{len(ordered) - _MAX_PENALTY_LINES} pilote(s)")
        fields.append({"name": f"Sanctions ({len(penalties)})", "value": "\n".join(shown)[:1000], "inline": False})

    title = _tmpl("DISCORD_MSG_SESSION_SUMMARY", "🏁 {session} terminée — {circuit}",
                  session=session, circuit=circuit or "—")
    return _embed(_COLOR_GOLD, server_name, title=title, description="\n".join(lines), fields=fields)


def notify_session_summary(parsed: dict, server_id: int | None = None, server_name: str = ""):
    """Récapitulatif de fin de session sur le webhook course (option DISCORD_NOTIFY_SESSION_SUMMARY)."""
    from app.services import race_labels
    try:
        from flask_babel import force_locale
        with force_locale("fr"):        # les messages Discord sont en français, comme les autres
            embed = build_session_summary_embed(parsed, server_name, race_labels.penalty_type_label,
                                                race_labels.investigation_label)
    except RuntimeError:                # pas de contexte Flask : valeurs brutes
        embed = build_session_summary_embed(parsed, server_name)
    if embed is None:
        return
    _send_race(_with_mention("DISCORD_MENTION_RACE", [embed]), server_id=server_id)


def notify_access_ban(name: str, by_admin: str, banned: bool = True, server_id: int | None = None):
    """Annonce un bannissement (ou une levée) décidé dans la page Accès du panel.
    Les règles d'accès valent pour tous les serveurs."""
    line = f"🚫 **{_md(name or '—')}** est banni" if banned else f"✅ **{_md(name or '—')}** n'est plus banni"
    _send_race(_with_mention("DISCORD_MENTION_RACE", [_embed(
        _COLOR_RED if banned else _COLOR_GREEN, "Tous les serveurs",
        description=f"{line}\n-# décidé par {_md(by_admin or '—')}",
    )]), server_id=server_id)


def safe_notify(fn, *args, **kwargs):
    """Appelle un notifier Discord en loggant l'erreur sans propager l'exception."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        log.warning("Discord notification skipped (%s): %s", fn.__name__, e)
