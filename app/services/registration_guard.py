"""Serveur réservé aux inscrits (championnat) : un pilote non inscrit est prévenu par le bot,
puis expulsé s'il est toujours là à la fin du délai.

Inscrit = compte pilote validé portant ce SteamID, avec une inscription confirmée à un événement
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


def is_registered(steam_id: str, server_id: int) -> bool:
    from app.models import Driver, Event, EventRegistration, EventStatus, RegStatus, DriverStatus
    since = _now() - _WINDOW
    events = (Event.query
              .filter(Event.server_id == server_id, Event.status == EventStatus.PUBLISHED, Event.date >= since)
              .all())
    if any(e.is_public for e in events):
        return True
    if not steam_id:
        return False
    driver = Driver.query.filter_by(steam_id=str(steam_id), status=DriverStatus.APPROVED).first()
    if driver is None:
        return False
    ids = [e.id for e in events]
    if not ids:
        return False
    return EventRegistration.query.filter(
        EventRegistration.driver_id == driver.id,
        EventRegistration.event_id.in_(ids),
        EventRegistration.status == RegStatus.CONFIRMED,
    ).first() is not None


def messages(name: str, site_url: str, grace_s: int) -> list[str]:
    site = site_url or "the server website"
    minutes = max(1, round(grace_s / 60))
    return [
        f"Hi {name}, this server is reserved for registered championship drivers.",
        f"Register on {site} with your Steam account and sign up for an event to race here.",
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
        with app.app_context():
            required, grace = server_settings(server_id)
            if not required or is_registered(sid, server_id):
                return
        c = bot._get_client(server_id)
        # Même délai que l'accueil : le joueur doit avoir le tchat sous les yeux
        time.sleep(max(0, c.get("welcome_delay", 20)) + 3)
        if not _still_here(c, sid):
            return
        for line in messages(name, c.get("welcome_site", ""), grace):
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
