import hashlib
import os
import re
import secrets
import json as _json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MEDIA_ROOT = Path(__file__).parent.parent.parent / "media"

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_babel import _, get_locale
from sqlalchemy.orm import selectinload as _pub_selectinload
from flask_login import current_user, login_required
from app import limiter

from app.models import Driver, Event, EventRegistration, Server, SessionResult, EventStatus, RegStatus
from app.routes.auth import _validate_password
from app.services.database import db
from app.services.process_manager import get_status, get_player_history
from app.services.results_parser import get_parsed, group_sessions as _group_sessions
from app.services.server_config import get_running_server_info

public_bp = Blueprint("public", __name__)

_INGAME_RE = re.compile(r'^[A-Za-z0-9_\-.\s]{2,30}$')


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_email_confirmation() -> bool:
    return os.environ.get("REQUIRE_EMAIL_CONFIRMATION", "false").lower() == "true"


def _send_confirmation_email(driver):
    from app.services import mailer
    token = secrets.token_urlsafe(32)
    driver.email_confirm_token         = hashlib.sha256(token.encode()).hexdigest()
    driver.email_confirm_token_expires = _now_utc() + timedelta(hours=48)
    db.session.commit()
    mailer.send_email_confirmation(driver, token)


@public_bp.route("/")
@limiter.limit("60 per minute")
def index():
    servers = (Server.query
               .filter_by(is_enabled=True)
               .order_by(Server.sort_order, Server.id)
               .all())

    statuses     = {}
    server_infos = {}
    player_histories = {}
    for srv in servers:
        st = get_status(srv.id)
        statuses[srv.id]     = st
        server_infos[srv.id] = get_running_server_info(srv.id) if st["running"] else None
        player_histories[srv.id] = _json.dumps(get_player_history(srv.id)[-30:]) if st["running"] else "[]"

    # Enrichir les infos serveur avec l'image bannière du circuit en cours
    for srv in servers:
        si = server_infos.get(srv.id)
        if si:
            slug = si.get("track_slug", "")
            banner = _MEDIA_ROOT / "circuits" / f"{slug}.webp"
            si["banner_image"] = f"circuits/{slug}.webp" if slug and banner.exists() else ""

    now = _now_utc()
    ongoing = (Event.query
               .filter_by(status=EventStatus.PUBLISHED)
               .filter(Event.date < now)
               .order_by(Event.date.desc())
               .all())

    from zoneinfo import ZoneInfo as _ZI
    from babel.dates import format_date as _babel_fmt_date
    _panel_tz = _ZI(current_app.config.get("PANEL_TIMEZONE", "Europe/Paris"))
    _loc = str(get_locale())

    def _ev_dict(ev):
        local_dt = ev.date.replace(tzinfo=timezone.utc).astimezone(_panel_tz)
        parts  = (ev.circuit or "").split("|")
        tslug  = parts[0].strip().lower().replace(" ", "_") if parts else ""
        tpath  = _MEDIA_ROOT / "circuits" / f"{tslug}.webp"
        conf   = sum(1 for r in ev.registrations if r.status == RegStatus.CONFIRMED)
        total  = ev.total_minutes
        h, m   = divmod(total, 60)
        return {
            "ev":        ev,
            "day":       local_dt.strftime("%d"),
            "month":     _babel_fmt_date(local_dt, format="MMM", locale=_loc).rstrip("."),
            "time":      local_dt.strftime("%H:%M"),
            "duration":  f"{h}h{m:02d}" if h else f"{m} min",
            "track_img": f"circuits/{tslug}.webp" if tslug and tpath.exists() else "",
            "confirmed": conf,
            "fill_pct":  min(100, round(conf / ev.max_drivers * 100)) if ev.max_drivers else 0,
        }

    raw_upcoming = (Event.query
                    .filter_by(status=EventStatus.PUBLISHED)
                    .filter(Event.date >= now)
                    .options(_pub_selectinload(Event.registrations))
                    .order_by(Event.date)
                    .limit(5)
                    .all())
    upcoming = [_ev_dict(ev) for ev in raw_upcoming]

    my_regs = {}
    if current_user.is_authenticated and current_user.is_pilot:
        for reg in EventRegistration.query.filter_by(driver_id=current_user.id).all():
            my_regs[reg.event_id] = reg

    recent_rows = (SessionResult.query
                   .order_by(SessionResult.received_at.desc())
                   .limit(50).all())
    recent_sessions = []
    for r in recent_rows:
        try:
            parsed = get_parsed(r)
        except Exception:
            parsed = {}
        if not parsed.get("standings") or not any(
            s.get("best_lap_ms") or s.get("fastest_lap_ms") for s in parsed["standings"]
        ):
            continue
        recent_sessions.append({"id": r.id, "received_at": r.received_at,
                                 "source": r.source, "parsed": parsed,
                                 "config_name": r.config_name,
                                 "run_id": r.run_id})
        if len(recent_sessions) >= 4:
            break

    # Enrichir les résultats récents avec l'image de la voiture du vainqueur
    if recent_sessions:
        from app.models import CarMeta
        # Collecte tous les noms de voiture vainqueurs en une passe, puis charge en 1 requête
        winner_names = {
            (s["parsed"].get("standings") or [{}])[0].get("car", "")
            for s in recent_sessions
        } - {""}
        car_by_name: dict[str, CarMeta] = {}
        if winner_names:
            cms = CarMeta.query.filter(
                CarMeta.display_name.in_(winner_names), CarMeta.image_path != ""
            ).all()
            car_by_name = {cm.display_name: cm for cm in cms}
            # Fallback préfixe pour les noms sans variante (ex: "BMW M4 GT3" vs "BMW M4 GT3 Evo 2")
            missing = winner_names - set(car_by_name)
            if missing:
                for cm in CarMeta.query.filter(CarMeta.image_path != "").all():
                    for name in list(missing):
                        if cm.display_name.startswith(name + " "):
                            car_by_name.setdefault(name, cm)
                            missing.discard(name)
                    if not missing:
                        break

        for s in recent_sessions:
            standings = s["parsed"].get("standings") or []
            car_name = standings[0].get("car", "") if standings else ""
            cm = car_by_name.get(car_name)
            s["car_image"] = cm.image_path if cm else ""

            # Banner du circuit pour le fond de la carte résultat
            track_slug = (s["parsed"].get("track") or "").lower().replace(" ", "_")
            banner = _MEDIA_ROOT / "circuits" / f"{track_slug}.webp"
            s["track_banner"] = f"circuits/{track_slug}.webp" if track_slug and banner.exists() else ""

    recent_sessions, _ = _group_sessions(recent_sessions)

    return render_template("public.html",
                           servers=servers,
                           statuses=statuses,
                           server_infos=server_infos,
                           player_histories=player_histories,
                           ongoing=ongoing,
                           upcoming=upcoming,
                           my_regs=my_regs,
                           recent_sessions=recent_sessions)


@public_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    if request.method == "POST":
        ingame = request.form.get("ingame_name", "").strip()
        email  = request.form.get("email", "").strip().lower()
        pwd    = request.form.get("password", "")
        conf   = request.form.get("confirm", "")

        errors = []
        if not ingame:
            errors.append(_("Le nom in-game est requis."))
        elif not _INGAME_RE.match(ingame):
            errors.append(_("Nom in-game invalide (2–30 caractères)."))
        if not email or "@" not in email:
            errors.append(_("Adresse email invalide."))
        errors.extend(_validate_password(pwd))
        if pwd != conf:
            errors.append(_("Les mots de passe ne correspondent pas."))

        if not errors:
            if Driver.query.filter_by(ingame_name=ingame).first():
                errors.append(_("Ce nom in-game est déjà utilisé."))
            if Driver.query.filter_by(email=email).first():
                errors.append(_("Cet email est déjà utilisé."))

        if not errors:
            driver = Driver(ingame_name=ingame, email=email)
            driver.set_password(pwd)
            db.session.add(driver)
            db.session.commit()
            from app.services import mailer, discord_notifier
            mailer.send_new_registration(driver)
            mailer.send_registration_received(driver)
            discord_notifier.safe_notify(discord_notifier.notify_new_registration, driver)
            if _require_email_confirmation():
                _send_confirmation_email(driver)
            flash(_("Inscription reçue ! Votre compte sera activé par un administrateur."), "success")
            return redirect(url_for("auth.login"))

        for e in errors:
            flash(e, "error")

    return render_template("register.html")


@public_bp.route("/confirm-email/<token>")
def confirm_email(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    driver = Driver.query.filter_by(email_confirm_token=token_hash).first()
    if (not driver or not driver.email_confirm_token_expires
            or driver.email_confirm_token_expires < _now_utc()):
        flash(_("Ce lien de confirmation est invalide ou a expiré."), "error")
        return redirect(url_for("auth.login"))

    driver.email_confirmed_at          = _now_utc()
    driver.email_confirm_token         = None
    driver.email_confirm_token_expires = None
    db.session.commit()
    flash(_("Email confirmé avec succès."), "success")
    return redirect(url_for("auth.login"))


@public_bp.route("/pilot/email/resend-confirmation", methods=["POST"])
@login_required
@limiter.limit("3 per hour")
def resend_email_confirmation():
    if not current_user.is_pilot:
        return redirect(url_for("admin.server"))
    if not current_user.is_email_confirmed:
        _send_confirmation_email(current_user)
        flash(_("Email de confirmation renvoyé."), "success")
    return redirect(url_for("public.pilot_dashboard"))


@public_bp.route("/pilot/dashboard")
def pilot_dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not current_user.is_pilot:
        return redirect(url_for("admin.server"))

    regs = (EventRegistration.query
            .filter_by(driver_id=current_user.id)
            .options(_pub_selectinload(EventRegistration.event))
            .join(Event)
            .order_by(Event.date.asc())
            .all())

    now = _now_utc()
    upcoming_regs = [r for r in regs if r.event.date >= now]
    past_regs     = sorted([r for r in regs if r.event.date < now], key=lambda r: r.event.date, reverse=True)

    registered_ids = {r.event_id for r in regs}
    q = (Event.query
         .filter_by(status=EventStatus.PUBLISHED, is_public=False)
         .filter(Event.date >= now)
         .options(_pub_selectinload(Event.registrations)))
    if registered_ids:
        q = q.filter(Event.id.notin_(registered_ids))
    available = q.order_by(Event.date).all()

    return render_template("pilot_dashboard.html",
                           upcoming_regs=upcoming_regs,
                           past_regs=past_regs,
                           available=available,
                           require_email_confirmation=_require_email_confirmation())


@public_bp.route("/pilot/events/<int:event_id>/register", methods=["POST"])
@login_required
def pilot_register(event_id):
    if not current_user.is_authenticated or not current_user.is_pilot:
        return redirect(url_for("auth.login"))

    if not current_user.is_approved:
        flash(_("Votre compte doit être validé avant de vous inscrire."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    if _require_email_confirmation() and not current_user.is_email_confirmed:
        flash(_("Confirmez votre email avant de vous inscrire à un événement."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    event = db.get_or_404(Event, event_id)
    if event.status != EventStatus.PUBLISHED:
        flash(_("Cet événement n'est pas disponible."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    if EventRegistration.query.filter_by(event_id=event_id, driver_id=current_user.id).first():
        flash(_("Vous êtes déjà inscrit à cet événement."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    if event.is_full:
        flash(_("Cet événement est complet."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    db.session.add(EventRegistration(event_id=event_id, driver_id=current_user.id))
    db.session.commit()
    flash(_("Inscription envoyée !"), "success")
    return redirect(url_for("public.pilot_dashboard"))


@public_bp.route("/results")
@limiter.limit("60 per minute")
def results():
    from app.routes.leaderboard import build_circuits

    initial_view = request.args.get("v", "overview")
    if initial_view not in ("overview", "results", "leaderboard"):
        initial_view = "overview"

    rows = (SessionResult.query
            .order_by(SessionResult.received_at.desc())
            .limit(50).all())
    sessions = []
    for r in rows:
        try:
            parsed = get_parsed(r)
        except Exception:
            parsed = {}
        sessions.append({"id": r.id, "received_at": r.received_at,
                         "source": r.source, "parsed": parsed,
                         "config_name": r.config_name,
                         "run_id": r.run_id})
    sessions, groups = _group_sessions(sessions)

    for s in sessions:
        track_slug = (s["parsed"].get("track") or "").lower().replace(" ", "_")
        banner = _MEDIA_ROOT / "circuits" / f"{track_slug}.webp"
        s["track_banner"] = f"circuits/{track_slug}.webp" if track_slug and banner.exists() else ""

    circuits = build_circuits()

    return render_template("results.html",
                           sessions=sessions, groups=groups,
                           circuits=circuits,
                           initial_view=initial_view)


@public_bp.route("/results/<int:result_id>")
@limiter.limit("60 per minute")
def result_detail(result_id):
    from app.models import SessionResult
    from app.services.results_parser import get_parsed
    r = db.get_or_404(SessionResult, result_id)
    parsed = get_parsed(r)
    return render_template("result_detail.html", result=r, parsed=parsed)


@public_bp.route("/pilot/events/<int:event_id>/unregister", methods=["POST"])
@login_required
def pilot_unregister(event_id):
    if not current_user.is_authenticated or not current_user.is_pilot:
        return redirect(url_for("auth.login"))

    reg = EventRegistration.query.filter_by(event_id=event_id, driver_id=current_user.id).first()
    if reg and reg.status == RegStatus.PENDING:
        db.session.delete(reg)
        db.session.commit()
        flash(_("Désinscription effectuée."), "success")
    else:
        flash(_("Impossible de se désinscrire (inscription confirmée)."), "error")
    return redirect(url_for("public.pilot_dashboard"))
