import re
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_babel import _
from flask_login import current_user, login_user

from app.models import Driver, Event, EventRegistration
from app.routes.auth import _validate_password
from app.services.database import db
from app.services.process_manager import get_status
from app.services.server_config import get_running_server_info

public_bp = Blueprint("public", __name__)

_INGAME_RE = re.compile(r'^[A-Za-z0-9_\-.\s]{2,30}$')


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@public_bp.route("/")
def index():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))

    status      = get_status()
    server_info = get_running_server_info() if status["running"] else None
    events = (Event.query
              .filter_by(status="published")
              .filter(Event.date >= _now_utc())
              .order_by(Event.date)
              .all())

    my_regs = {}
    if current_user.is_authenticated and current_user.is_pilot:
        for reg in EventRegistration.query.filter_by(driver_id=current_user.id).all():
            my_regs[reg.event_id] = reg

    return render_template("public.html",
                           status=status,
                           server_info=server_info,
                           events=events,
                           my_regs=my_regs)


@public_bp.route("/register", methods=["GET", "POST"])
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
            discord_notifier.notify_new_registration(driver)
            flash(_("Inscription reçue ! Votre compte sera activé par un administrateur."), "success")
            return redirect(url_for("auth.login"))

        for e in errors:
            flash(e, "error")

    return render_template("register.html")


@public_bp.route("/pilot/dashboard")
def pilot_dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if not current_user.is_pilot:
        return redirect(url_for("admin.dashboard"))

    regs = (EventRegistration.query
            .filter_by(driver_id=current_user.id)
            .join(Event)
            .order_by(Event.date.desc())
            .all())

    registered_ids = {r.event_id for r in regs}
    q = (Event.query
         .filter_by(status="published")
         .filter(Event.date >= _now_utc()))
    if registered_ids:
        q = q.filter(Event.id.notin_(registered_ids))
    available = q.order_by(Event.date).all()

    return render_template("pilot_dashboard.html", regs=regs, available=available)


@public_bp.route("/pilot/events/<int:event_id>/register", methods=["POST"])
def pilot_register(event_id):
    if not current_user.is_authenticated or not current_user.is_pilot:
        return redirect(url_for("auth.login"))

    if not current_user.is_approved:
        flash(_("Votre compte doit être validé avant de vous inscrire."), "error")
        return redirect(url_for("public.pilot_dashboard"))

    event = Event.query.get_or_404(event_id)
    if event.status != "published":
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


@public_bp.route("/pilot/events/<int:event_id>/unregister", methods=["POST"])
def pilot_unregister(event_id):
    if not current_user.is_authenticated or not current_user.is_pilot:
        return redirect(url_for("auth.login"))

    reg = EventRegistration.query.filter_by(event_id=event_id, driver_id=current_user.id).first()
    if reg and reg.status == "pending":
        db.session.delete(reg)
        db.session.commit()
        flash(_("Désinscription effectuée."), "success")
    else:
        flash(_("Impossible de se désinscrire (inscription confirmée)."), "error")
    return redirect(url_for("public.pilot_dashboard"))
