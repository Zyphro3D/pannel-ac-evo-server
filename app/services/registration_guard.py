"""Serveur réservé aux inscrits (championnat) : un pilote non inscrit est prévenu par le bot,
puis expulsé s'il est toujours là à la fin du délai.

Inscrit = admin du panel dont le compte porte ce SteamID, ou compte pilote validé portant ce SteamID, avec une inscription confirmée à un événement
publié de ce serveur, à venir ou commencé depuis moins de 24 h. Un événement public (sans
inscription) de ce serveur dans la même fenêtre laisse entrer tout le monde.

Messages en anglais : ils s'adressent à des joueurs du monde entier, dans le tchat du jeu (sans
emojis, le serveur les refuse).
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_WINDOW = timedelta(hours=24)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def server_settings(server_id: int) -> tuple[bool, int]:
    from app.models import Server
    from app.services.database import db
    srv = db.session.get(Server, server_id)
    if srv is None:
        return False, 0
    return bool(srv.registration_required), int(srv.registration_grace_s or 180)


def registration_for(steam_id: str, server_id: int):
    """« admin », « public », l'inscription confirmée (EventRegistration) ou None."""
    from app.models import AdminAccount, Driver, Event, EventRegistration, EventStatus, RegStatus, DriverStatus
    since = _now() - _WINDOW
    events = (Event.query
              .filter(Event.server_id == server_id, Event.status == EventStatus.PUBLISHED, Event.date >= since)
              .order_by(Event.date.asc()).all())
    if not steam_id:
        return "public" if any(e.is_public for e in events) else None
    # Un admin du panel (Steam lié à son compte admin) n'est jamais expulsé de ses serveurs
    if AdminAccount.query.filter_by(steam_id=str(steam_id), is_active=True).first() is not None:
        driver = Driver.query.filter_by(steam_id=str(steam_id), status=DriverStatus.APPROVED).first()
        reg = _confirmed(driver, events) if driver else None
        return reg or "admin"
    driver = Driver.query.filter_by(steam_id=str(steam_id), status=DriverStatus.APPROVED).first()
    reg = _confirmed(driver, events) if driver else None
    if reg is not None:
        return reg
    return "public" if any(e.is_public for e in events) else None


def _confirmed(driver, events):
    from app.models import EventRegistration, RegStatus
    ids = [e.id for e in events]
    if not ids:
        return None
    return (EventRegistration.query
            .filter(EventRegistration.driver_id == driver.id, EventRegistration.event_id.in_(ids),
                    EventRegistration.status == RegStatus.CONFIRMED)
            .first())


def is_registered(steam_id: str, server_id: int) -> bool:
    return registration_for(steam_id, server_id) is not None


_car_maps: dict[str, tuple[float, dict]] = {}    # chemin → (mtime, {variante: modèle})


def _map_of(path) -> dict:
    from app.services.mod_scanner import preset_car_map
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _car_maps.get(str(path))
    if cached is None or cached[0] != mtime:
        cached = (mtime, preset_car_map(path))
        _car_maps[str(path)] = cached
    return cached[1]


def preset_car(preset: str) -> str:
    """Modèle de voiture (car_slug) d'une variante : paquet du jeu, puis mods de la bibliothèque.
    Lecture de la table des fichiers (mod_scanner), mise en cache tant que le fichier ne change pas."""
    import os
    from pathlib import Path
    from flask import current_app
    game = Path(os.environ.get("KSPKG_PATH") or Path(current_app.config["ACESERVER_DIR"]) / "content.kspkg")
    car = _map_of(game).get(preset, "")
    if car:
        return car
    for k in Path(current_app.config["MODS_DIR"]).glob("*.kspkg"):
        car = _map_of(k).get(preset, "")
        if car:
            return car
    return ""


def car_message(name: str, reg, car_raw: str) -> str | None:
    """Message d'un inscrit à son arrivée : bonne voiture ou rappel de celle choisie à l'inscription."""
    assigned = getattr(reg, "assigned_car", "") or ""
    if not assigned or not car_raw:
        return f"Hi {name}, you are registered: you can start driving. Good luck!"
    expected = preset_car(assigned)
    if not expected or expected.lower() == car_raw.lower():
        return f"Hi {name}, you are registered: you can start driving. Good luck!"
    label = (getattr(reg, "car_display", "") or assigned).encode("ascii", "ignore").decode() or assigned
    return f"Hi {name}, wrong car: you registered with {label}. Back to the pits: please come back with it."


def messages(name: str, site_url: str, grace_s: int, server_id: int = 0) -> list[str]:
    minutes = max(1, round(grace_s / 60))
    if site_url and server_id:
        how = f"Join in 1 minute with your Steam account: {site_url.rstrip('/')}/join/{server_id}"
    else:
        how = f"Register on {site_url or 'the server website'} with your Steam account and sign up for an event."
    return [
        f"Hi {name}, this server is reserved for registered championship drivers.",
        how,
        f"You will be kicked in {minutes} min if you are not registered.",
    ]


def _still_here(c: dict, sid: str) -> bool:
    with c["lb_lock"]:
        return sid in c["join_times"]


def _car_number(c: dict, sid: str) -> str:
    with c["lb_lock"]:
        return str(c["leaderboard"].get(sid, {}).get("num", "") or "")


def guard(sid: str, name: str, server_id: int, app) -> None:
    """Fil lancé à chaque arrivée d'un pilote (ace_tcp_client) ; ne fait rien si le serveur
    n'exige pas d'inscription."""
    from app.services import ace_tcp_client as bot
    try:
        c = bot._get_client(server_id)
        with app.app_context():
            required, grace = server_settings(server_id)
            if not required:
                return
            reg = registration_for(sid, server_id)
            note = None
            if reg not in (None, "admin", "public"):
                with c["lb_lock"]:
                    car_raw = c["sid_car_raw"].get(sid, "")
                note = car_message(name, reg, car_raw)
        if reg is not None:
            if note:
                time.sleep(max(0, c.get("welcome_delay", 20)) + 3)
                if _still_here(c, sid):
                    bot.send_chat(note, server_id)
                    if "wrong car" in note:
                        # Mauvaise voiture : renvoyé au stand (commande admin du jeu, comme la page Live)
                        num = _car_number(c, sid)
                        if num:
                            time.sleep(1)
                            sent, err = bot.send_admin_command(f"\\to_pit {num}", server_id)
                            log.info("registration_guard: %s (#%s) renvoyé au stand (mauvaise voiture) envoyé=%s %s",
                                     sid, num, sent, err or "")
            return
        # Même délai que l'accueil : le joueur doit avoir le tchat sous les yeux
        time.sleep(max(0, c.get("welcome_delay", 20)) + 3)
        if not _still_here(c, sid):
            return
        for line in messages(name, c.get("welcome_site", ""), grace, server_id):
            bot.send_chat(line, server_id)
            time.sleep(1)
        log.info("registration_guard: %s (%s) non inscrit, expulsion dans %d s (server=%d)", name, sid, grace, server_id)
        time.sleep(grace)
        if not _still_here(c, sid):
            return
        with app.app_context():
            if is_registered(sid, server_id):
                return
        num = _car_number(c, sid)
        if not num:
            log.warning("registration_guard: numéro de voiture inconnu pour %s, expulsion impossible", sid)
            return
        bot.send_chat(f"{name}: not registered, you are being kicked. See you after signing up!", server_id)
        time.sleep(1)
        sent, err = bot.send_admin_command(f"\\kick {num}", server_id)
        log.info("registration_guard: expulsion de %s (#%s) envoyée=%s %s", sid, num, sent, err or "")
    except Exception as e:
        log.error("registration_guard: %s", e)


def start(sid: str, name: str, server_id: int) -> None:
    from app.services import ace_tcp_client as bot
    if bot._flask_app is None:
        return
    threading.Thread(target=guard, args=(sid, name, server_id, bot._flask_app), daemon=True).start()
