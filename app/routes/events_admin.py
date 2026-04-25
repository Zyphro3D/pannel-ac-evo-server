import json
from functools import wraps
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_babel import _
from flask_login import current_user

from app.models import Event, EventRegistration, Driver
from app.services.database import db
from app.services.server_config import load_events as load_tracks, load_cars

events_admin_bp = Blueprint("events_admin", __name__)


def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def _event_from_form(event, form):
    event.title         = form.get("title", "").strip()
    event.description   = form.get("description", "").strip()
    event.circuit       = form.get("circuit", "")
    event.circuit_display = form.get("circuit_display", "").strip()
    event.mode          = form.get("mode", "GameModeType_PRACTICE")
    event.weather       = form.get("weather", "GameModeSelectionWeatherType_CLEAR")
    event.max_drivers   = max(1, int(form.get("max_drivers", 20) or 20))
    event.password      = form.get("password", "").strip()
    event.notify_before = max(0, int(form.get("notify_before", 60) or 60))
    date_str = form.get("date", "")
    try:
        event.date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        pass
    # Durées de session (heures + minutes → total minutes)
    def _total_min(h_key, m_key, default):
        h = max(0, int(form.get(h_key, 0) or 0))
        m = max(0, min(59, int(form.get(m_key, 0) or 0)))
        total = h * 60 + m
        return total if total > 0 else default
    event.practice_minutes   = _total_min("practice_h",   "practice_m",   60)
    event.qualifying_minutes = _total_min("qualifying_h", "qualifying_m", 30)
    event.warmup_minutes     = _total_min("warmup_h",     "warmup_m",     10)
    event.race_minutes       = _total_min("race_h",       "race_m",       60)
    # Voitures autorisées (multi-valeur)
    event.allowed_cars = json.dumps(form.getlist("allowed_cars"))
    # Visibilité
    event.is_public   = form.get("is_public") == "1"
    # Lancement automatique
    event.auto_launch  = form.get("auto_launch") == "1"
    return event


# ── Events CRUD ──────────────────────────────────────────────────────────────

@events_admin_bp.route("/events")
@_admin_required
def events_list():
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template("events_admin.html", events=events)


_PROP_MAPS = {
    "property_1": {0: "Road", 1: "Race", 2: "Track"},
    "property_2": {0: "Modern", 1: "Vintage", 2: "YT"},
    "property_3": {0: "ICE", 1: "EV", 2: "Hybrid"},
}
_CATEGORY_ORDER = ["Road", "Race", "Track", "Modern", "Vintage", "YT", "ICE", "EV", "Hybrid"]


def _cars_context(cars):
    present = set()
    for car in cars:
        for key, mapping in _PROP_MAPS.items():
            val = car.get(key)
            label = mapping.get(val, "") if val is not None else ""
            car[f"{key}_label"] = label
            if label:
                present.add(label)
    categories = [c for c in _CATEGORY_ORDER if c in present]
    pi_values  = [c["performance_indicator"] for c in cars if c.get("performance_indicator") is not None]
    return categories, (min(pi_values) if pi_values else 0.0), (max(pi_values) if pi_values else 999.0)


@events_admin_bp.route("/events/create", methods=["GET", "POST"])
@_admin_required
def event_create():
    tracks = load_tracks("practice")
    cars   = load_cars()
    car_categories, pi_min, pi_max = _cars_context(cars)
    if request.method == "POST":
        event = _event_from_form(Event(), request.form)
        db.session.add(event)
        db.session.commit()
        flash(_("Événement créé."), "success")
        return redirect(url_for("events_admin.events_list"))
    return render_template("event_form.html", event=None, action="create",
                           tracks=tracks, cars=cars,
                           car_categories=car_categories, pi_min=pi_min, pi_max=pi_max)


@events_admin_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@_admin_required
def event_edit(event_id):
    event  = Event.query.get_or_404(event_id)
    tracks = load_tracks("practice")
    cars   = load_cars()
    car_categories, pi_min, pi_max = _cars_context(cars)
    if request.method == "POST":
        _event_from_form(event, request.form)
        db.session.commit()
        flash(_("Événement mis à jour."), "success")
        return redirect(url_for("events_admin.events_list"))
    return render_template("event_form.html", event=event, action="edit",
                           tracks=tracks, cars=cars,
                           car_categories=car_categories, pi_min=pi_min, pi_max=pi_max)


@events_admin_bp.route("/events/<int:event_id>/delete", methods=["POST"])
@_admin_required
def event_delete(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash(_("Événement supprimé."), "success")
    return redirect(url_for("events_admin.events_list"))


@events_admin_bp.route("/events/<int:event_id>/publish", methods=["POST"])
@_admin_required
def event_publish(event_id):
    event = Event.query.get_or_404(event_id)
    if event.status == "draft":
        event.status = "published"
        msg = _("Événement publié.")
    elif event.status == "published":
        event.status = "draft"
        msg = _("Événement repassé en brouillon.")
    else:
        msg = _("Statut inchangé.")
    db.session.commit()
    flash(msg, "success")
    return redirect(url_for("events_admin.events_list"))


@events_admin_bp.route("/events/<int:event_id>/finish", methods=["POST"])
@_admin_required
def event_finish(event_id):
    event = Event.query.get_or_404(event_id)
    event.status = "finished"
    db.session.commit()
    flash(_("Événement marqué comme terminé."), "success")
    return redirect(url_for("events_admin.events_list"))


# ── Registrations ─────────────────────────────────────────────────────────────

@events_admin_bp.route("/events/<int:event_id>/registrations")
@_admin_required
def event_registrations(event_id):
    event = Event.query.get_or_404(event_id)
    regs  = event.registrations.order_by(EventRegistration.created_at).all()
    cars  = load_cars()
    return render_template("event_detail.html", event=event, regs=regs, cars=cars)


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/approve", methods=["POST"])
@_admin_required
def reg_approve(event_id, rid):
    reg = EventRegistration.query.get_or_404(rid)
    reg.status = "confirmed"
    db.session.commit()
    flash(_("%(name)s confirmé(e).", name=reg.driver.ingame_name), "success")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/reject", methods=["POST"])
@_admin_required
def reg_reject(event_id, rid):
    reg = EventRegistration.query.get_or_404(rid)
    reg.status = "rejected"
    db.session.commit()
    flash(_("%(name)s refusé.", name=reg.driver.ingame_name), "success")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/assign-car", methods=["POST"])
@_admin_required
def reg_assign_car(event_id, rid):
    reg = EventRegistration.query.get_or_404(rid)
    car_name = request.form.get("assigned_car", "")
    car_disp = request.form.get("car_display", "")
    reg.assigned_car = car_name
    reg.car_display  = car_disp
    db.session.commit()
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/entry-list", methods=["POST"])
@_admin_required
def event_entry_list(event_id):
    event = Event.query.get_or_404(event_id)
    from app.services import entry_list
    ok = entry_list.generate(event)
    flash(_("Entry list générée.") if ok else _("Erreur lors de la génération."), "success" if ok else "error")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


# ── Drivers ───────────────────────────────────────────────────────────────────

@events_admin_bp.route("/drivers")
@_admin_required
def drivers_list():
    pending  = Driver.query.filter_by(status="pending").order_by(Driver.created_at).all()
    approved = Driver.query.filter_by(status="approved").order_by(Driver.ingame_name).all()
    rejected = Driver.query.filter_by(status="rejected").order_by(Driver.ingame_name).all()
    return render_template("drivers.html", pending=pending, approved=approved, rejected=rejected)


@events_admin_bp.route("/drivers/<int:driver_id>/approve", methods=["POST"])
@_admin_required
def driver_approve(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.status = "approved"
    db.session.commit()
    from app.services import mailer
    mailer.send_registration_approved(driver)
    flash(_("%(name)s approuvé.", name=driver.ingame_name), "success")
    return redirect(url_for("events_admin.drivers_list"))


@events_admin_bp.route("/drivers/<int:driver_id>/reject", methods=["POST"])
@_admin_required
def driver_reject(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.status = "rejected"
    db.session.commit()
    from app.services import mailer
    mailer.send_registration_rejected(driver)
    flash(_("%(name)s refusé.", name=driver.ingame_name), "error")
    return redirect(url_for("events_admin.drivers_list"))


@events_admin_bp.route("/drivers/<int:driver_id>/delete", methods=["POST"])
@_admin_required
def driver_delete(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    name = driver.ingame_name
    db.session.delete(driver)
    db.session.commit()
    flash(_("%(name)s supprimé.", name=name), "success")
    return redirect(url_for("events_admin.drivers_list"))
