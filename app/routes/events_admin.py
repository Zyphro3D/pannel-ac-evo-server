import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_babel import _
from sqlalchemy.orm import selectinload

from app.models import AccessRule, Event, EventRegistration, Driver, EventStatus, DriverStatus, RegStatus
from app.services.database import db
from app.services.server_config import load_events as load_tracks, load_cars, list_configs
from app.services import mailer, entry_list
from app.utils import (admin_required as _admin_required, superadmin_required as _superadmin_required,
                       is_htmx, htmx_oob_toast)

log = logging.getLogger(__name__)

events_admin_bp = Blueprint("events_admin", __name__)


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
        panel_tz = ZoneInfo(current_app.config.get("PANEL_TIMEZONE", "Europe/Paris"))
        naive_local = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
        event.date = naive_local.replace(tzinfo=panel_tz).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, KeyError):
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
    # Voitures autorisées + réglages ballast/restrictor par voiture
    allowed_names = form.getlist("allowed_cars")
    event.allowed_cars = json.dumps(allowed_names)
    try:
        event.cars_config = form.get("cars_config_json", "{}")
        json.loads(event.cars_config)  # valide le JSON
    except (ValueError, TypeError) as e:
        log.warning("cars_config_json invalide pour event id=%s: %s", getattr(event, 'id', '?'), e)
        event.cars_config = "{}"
    # Visibilité — getlist car hidden+checkbox envoient deux valeurs pour le même name
    event.is_public   = "1" in form.getlist("is_public")
    # Lancement automatique → publie automatiquement l'événement
    event.auto_launch = "1" in form.getlist("auto_launch")
    if event.auto_launch and event.status != EventStatus.FINISHED:
        event.status = EventStatus.PUBLISHED
    return event


# ── Events CRUD ──────────────────────────────────────────────────────────────

@events_admin_bp.route("/events")
@_admin_required
def events_list():
    events = Event.query.options(selectinload(Event.registrations)).order_by(Event.date.desc()).all()
    return render_template("events_admin.html", events=events)


from app.services.server_config import annotate_cars as _cars_context


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
                           car_categories=car_categories, pi_min=pi_min, pi_max=pi_max,
                           configs=list_configs())


@events_admin_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@_admin_required
def event_edit(event_id):
    event  = db.get_or_404(Event, event_id)
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
                           car_categories=car_categories, pi_min=pi_min, pi_max=pi_max,
                           configs=list_configs())


@events_admin_bp.route("/events/<int:event_id>/delete", methods=["POST"])
@_admin_required
def event_delete(event_id):
    event = db.get_or_404(Event, event_id)
    db.session.delete(event)
    db.session.commit()
    if is_htmx():
        return htmx_oob_toast("success", _("Événement supprimé."))
    flash(_("Événement supprimé."), "success")
    return redirect(url_for("events_admin.events_list"))


@events_admin_bp.route("/events/<int:event_id>/publish", methods=["POST"])
@_admin_required
def event_publish(event_id):
    event = db.get_or_404(Event, event_id)
    if event.status == EventStatus.DRAFT:
        event.status = EventStatus.PUBLISHED
        msg = _("Événement publié.")
    elif event.status == EventStatus.PUBLISHED:
        event.status = EventStatus.DRAFT
        msg = _("Événement repassé en brouillon.")
    else:
        msg = _("Statut inchangé.")
    db.session.commit()
    if is_htmx():
        return render_template("_partials/event_row.html", ev=event,
                               toast_msg=msg, toast_type="success")
    flash(msg, "success")
    return redirect(url_for("events_admin.events_list"))


@events_admin_bp.route("/events/<int:event_id>/finish", methods=["POST"])
@_admin_required
def event_finish(event_id):
    event = db.get_or_404(Event, event_id)
    event.status = EventStatus.FINISHED
    db.session.commit()
    if is_htmx():
        return render_template("_partials/event_row.html", ev=event,
                               toast_msg=_("Événement marqué comme terminé."), toast_type="success")
    flash(_("Événement marqué comme terminé."), "success")
    return redirect(url_for("events_admin.events_list"))


# ── Registrations ─────────────────────────────────────────────────────────────

@events_admin_bp.route("/events/<int:event_id>/registrations")
@_admin_required
def event_registrations(event_id):
    event = db.get_or_404(Event, event_id)
    regs  = (EventRegistration.query
             .filter_by(event_id=event.id)
             .options(selectinload(EventRegistration.driver))
             .order_by(EventRegistration.created_at)
             .all())
    cars  = load_cars()
    return render_template("event_detail.html", event=event, regs=regs, cars=cars)


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/approve", methods=["POST"])
@_admin_required
def reg_approve(event_id, rid):
    reg = EventRegistration.query.filter_by(id=rid, event_id=event_id).first_or_404()
    reg.status = RegStatus.CONFIRMED
    db.session.commit()
    mailer.send_event_registration_confirmed(reg.driver, reg.event)
    flash(_("%(name)s confirmé(e).", name=reg.driver.ingame_name), "success")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/reject", methods=["POST"])
@_admin_required
def reg_reject(event_id, rid):
    reg = EventRegistration.query.filter_by(id=rid, event_id=event_id).first_or_404()
    reg.status = RegStatus.REJECTED
    db.session.commit()
    mailer.send_event_registration_rejected(reg.driver, reg.event)
    flash(_("%(name)s refusé.", name=reg.driver.ingame_name), "success")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/registrations/<int:rid>/assign-car", methods=["POST"])
@_admin_required
def reg_assign_car(event_id, rid):
    reg = EventRegistration.query.filter_by(id=rid, event_id=event_id).first_or_404()
    car_name = request.form.get("assigned_car", "")
    car_disp = request.form.get("car_display", "")
    reg.assigned_car = car_name
    reg.car_display  = car_disp
    db.session.commit()
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


@events_admin_bp.route("/events/<int:event_id>/entry-list", methods=["POST"])
@_admin_required
def event_entry_list(event_id):
    event = db.get_or_404(Event, event_id)
    ok = entry_list.generate(event)
    flash(_("Entry list générée.") if ok else _("Erreur lors de la génération."), "success" if ok else "error")
    return redirect(url_for("events_admin.event_registrations", event_id=event_id))


# ── Drivers ───────────────────────────────────────────────────────────────────

@events_admin_bp.route("/drivers")
@_admin_required
def drivers_list():
    pending  = Driver.query.filter_by(status=DriverStatus.PENDING).order_by(Driver.created_at).all()
    approved = Driver.query.filter_by(status=DriverStatus.APPROVED).order_by(Driver.ingame_name).all()
    rejected = Driver.query.filter_by(status=DriverStatus.REJECTED).order_by(Driver.ingame_name).all()
    return render_template("drivers.html", pending=pending, approved=approved, rejected=rejected)


def _drivers_oob(toast_type, toast_msg):
    pending  = Driver.query.filter_by(status=DriverStatus.PENDING).order_by(Driver.created_at).all()
    approved = Driver.query.filter_by(status=DriverStatus.APPROVED).order_by(Driver.ingame_name).all()
    return render_template("_partials/drivers_oob.html", pending=pending, approved=approved,
                           toast_type=toast_type, toast_msg=toast_msg)


@events_admin_bp.route("/drivers/<int:driver_id>/approve", methods=["POST"])
@_admin_required
def driver_approve(driver_id):
    driver = db.get_or_404(Driver, driver_id)
    driver.status = DriverStatus.APPROVED
    db.session.commit()
    mailer.send_registration_approved(driver)
    if is_htmx():
        return _drivers_oob("success", _("%(name)s approuvé.", name=driver.ingame_name))
    flash(_("%(name)s approuvé.", name=driver.ingame_name), "success")
    return redirect(url_for("events_admin.drivers_list"))


@events_admin_bp.route("/drivers/<int:driver_id>/reject", methods=["POST"])
@_admin_required
def driver_reject(driver_id):
    driver = db.get_or_404(Driver, driver_id)
    driver.status = DriverStatus.REJECTED
    # Ses inscriptions en cours tombent avec le compte (liste d'engagés, rappels, effectifs)
    for reg in EventRegistration.query.filter(EventRegistration.driver_id == driver.id,
                                              EventRegistration.status != RegStatus.REJECTED):
        reg.status = RegStatus.REJECTED
    db.session.commit()
    mailer.send_registration_rejected(driver)
    if is_htmx():
        return _drivers_oob("success", _("%(name)s refusé.", name=driver.ingame_name))
    flash(_("%(name)s refusé.", name=driver.ingame_name), "error")
    return redirect(url_for("events_admin.drivers_list"))


@events_admin_bp.route("/drivers/<int:driver_id>/delete", methods=["POST"])
@_admin_required
def driver_delete(driver_id):
    driver = db.get_or_404(Driver, driver_id)
    name = driver.ingame_name
    db.session.delete(driver)
    db.session.commit()
    if is_htmx():
        return _drivers_oob("success", _("%(name)s supprimé.", name=name))
    flash(_("%(name)s supprimé.", name=name), "success")
    return redirect(url_for("events_admin.drivers_list"))


# ── Contrôle d'accès (liste blanche, bannissements, handicaps par SteamID) ────

@events_admin_bp.route("/access")
@_admin_required
def access_page():
    import os
    from app.services import access_control
    rules = AccessRule.query.order_by(AccessRule.banned.desc(), AccessRule.label, AccessRule.steam_id).all()
    names = {d.steam_id: d.ingame_name for d in Driver.query.filter(Driver.steam_id.isnot(None)).all()}
    approved_count = Driver.query.filter(Driver.status == DriverStatus.APPROVED,
                                         Driver.steam_id.isnot(None)).count()
    from app.services import rating
    from app.models import SessionResult
    ranking = rating.build_rating(lambda: SessionResult.query.order_by(SessionResult.received_at.asc()).yield_per(100))
    need = max(rating.min_races(), rating.PROVISIONAL_RACES)
    below = [p for p in ranking if rating.min_to_join() > 0 and p["races"] >= need and p["rating"] < rating.min_to_join()]
    return render_template("access.html", rules=rules, names=names, approved_count=approved_count,
                           rating_enforce=rating.enforce(), rating_min=rating.min_to_join(),
                           rating_min_races=rating.min_races(), rating_below=below,
                           enabled=access_control.enabled(), approved_only=access_control.approved_only(),
                           path_overridden=bool(os.environ.get("SERVER_ENTRY_LIST_PATH", "").strip()),
                           max_ballast=access_control.MAX_BALLAST, max_restrictor=access_control.MAX_RESTRICTOR)


@events_admin_bp.route("/access/settings", methods=["POST"])
@_superadmin_required
def access_settings():
    """Active ou désactive le contrôle d'accès (réglage global du panel, comme Paramètres)."""
    import os
    from app.routes.admin import _write_env_file, _env_write_lock
    new_vals = {
        # champ caché « false » + case à cocher « true » : coché, le navigateur envoie les deux valeurs
        "ACCESS_CONTROL_ENABLED": "true" if "true" in request.form.getlist("ACCESS_CONTROL_ENABLED") else "false",
        "ACCESS_APPROVED_ONLY":   "true" if "true" in request.form.getlist("ACCESS_APPROVED_ONLY") else "false",
    }
    if "RATING_MIN_TO_JOIN" in request.form:           # bloc ELO du formulaire (absent des anciens formulaires)
        def _int(key, lo, hi, default):
            try:
                return str(max(lo, min(hi, int(request.form.get(key, default) or default))))
            except ValueError:
                return str(default)
        new_vals["RATING_ENFORCE"] = "true" if "true" in request.form.getlist("RATING_ENFORCE") else "false"
        new_vals["RATING_MIN_TO_JOIN"] = _int("RATING_MIN_TO_JOIN", 0, 5000, 0)
        new_vals["RATING_MIN_RACES"] = _int("RATING_MIN_RACES", 5, 500, 5)
    with _env_write_lock:
        _write_env_file(new_vals)
        for k, v in new_vals.items():
            os.environ[k] = v
            current_app.config[k] = (v == "true")
    flash(_("Contrôle d'accès enregistré. Il s'applique au prochain démarrage du serveur de jeu."), "success")
    return redirect(url_for("events_admin.access_page"))


@events_admin_bp.route("/access/rules", methods=["POST"])
@_admin_required
def access_rule_save():
    """Crée ou met à jour la règle d'un SteamID."""
    from app.services import access_control
    steam_id = request.form.get("steam_id", "").strip()
    if not access_control.valid_steam_id(steam_id):
        flash(_("SteamID invalide : 17 chiffres commençant par 7656119."), "error")
        return redirect(url_for("events_admin.access_page"))
    ballast, restrictor = access_control.clamp_rule(request.form.get("ballast", 0), request.form.get("restrictor", 0))
    banned = "true" in request.form.getlist("banned")
    label = request.form.get("label", "").strip()[:100]
    rule = AccessRule.query.filter_by(steam_id=steam_id).first()
    was_banned = bool(rule and rule.banned)
    if rule is None:
        rule = AccessRule(steam_id=steam_id)
        db.session.add(rule)
    if not label:
        driver = Driver.query.filter_by(steam_id=steam_id).first()
        label = driver.ingame_name if driver else (rule.label or "")
    rule.label, rule.banned, rule.ballast, rule.restrictor = label, banned, ballast, restrictor
    db.session.commit()
    if banned != was_banned:     # annonce Discord d'un bannissement / d'une levée (webhook course)
        from flask_login import current_user
        from app.services import discord_notifier
        discord_notifier.safe_notify(discord_notifier.notify_access_ban, label or steam_id[-6:],
                                     getattr(current_user, "username", "") or getattr(current_user, "ingame_name", ""),
                                     banned)
    flash(_("Règle enregistrée. Elle s'applique au prochain démarrage du serveur de jeu."), "success")
    return redirect(url_for("events_admin.access_page"))


@events_admin_bp.route("/access/rules/<int:rule_id>/delete", methods=["POST"])
@_admin_required
def access_rule_delete(rule_id):
    rule = db.get_or_404(AccessRule, rule_id)
    db.session.delete(rule)
    db.session.commit()
    flash(_("Règle supprimée."), "success")
    return redirect(url_for("events_admin.access_page"))
