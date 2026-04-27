from functools import wraps
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import current_user

from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name, get_running_server_info,
)
from app.services.process_manager import get_status

admin_bp = Blueprint("admin", __name__)

_PROP_MAPS = {
    "property_1": {0: "Road", 1: "Race", 2: "Track"},
    "property_2": {0: "Modern", 1: "Vintage", 2: "YT"},
    "property_3": {0: "ICE", 1: "EV", 2: "Hybrid"},
}
_CATEGORY_ORDER = ["Road", "Race", "Track", "Modern", "Vintage", "YT", "ICE", "EV", "Hybrid"]


def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/dashboard")
@_admin_required
def dashboard():
    from app.models import Event, Driver
    now            = datetime.now(timezone.utc).replace(tzinfo=None)
    status         = get_status()
    server_info    = get_running_server_info()
    upcoming       = (Event.query
                      .filter_by(status="published")
                      .filter(Event.date >= now)
                      .order_by(Event.date)
                      .limit(5)
                      .all())
    pending_count  = Driver.query.filter_by(status="pending").count()
    return render_template("admin_dashboard.html",
                           status=status,
                           server_info=server_info,
                           upcoming=upcoming,
                           pending_count=pending_count)


@admin_bp.route("/administration")
@_admin_required
def administration():
    if not current_user.is_superadmin:
        return redirect(url_for("admin.dashboard"))
    from app.services import mailer as _mailer, discord_notifier
    cfg = _mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=discord_notifier._webhook_url,
                           pilots_webhook_url=discord_notifier._pilots_webhook_url)


@admin_bp.route("/administration/test-email", methods=["POST"])
@_admin_required
def test_email():
    if not current_user.is_superadmin:
        return redirect(url_for("admin.dashboard"))
    from app.services import mailer as _mailer, discord_notifier
    cfg      = _mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    to       = request.form.get("to", "").strip() or (cfg.get("admin") or [None])[0]
    result_email = _mailer.send_test(to) if to else {"ok": False, "error": "Aucune adresse destinataire"}
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=discord_notifier._webhook_url,
                           pilots_webhook_url=discord_notifier._pilots_webhook_url,
                           result_email=result_email)


@admin_bp.route("/administration/test-webhook", methods=["POST"])
@_admin_required
def test_webhook():
    if not current_user.is_superadmin:
        return redirect(url_for("admin.dashboard"))
    from app.services import mailer as _mailer, discord_notifier
    cfg      = _mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    channel  = request.form.get("channel", "server")
    url      = discord_notifier._pilots_webhook_url if channel == "pilots" else discord_notifier._webhook_url
    result   = discord_notifier.test_webhook(url)
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=discord_notifier._webhook_url,
                           pilots_webhook_url=discord_notifier._pilots_webhook_url,
                           result_webhook=result,
                           result_webhook_channel=channel)


@admin_bp.route("/server")
@_admin_required
def server():
    config         = load_config()
    cars           = load_cars()
    events_practice = load_events("practice")
    events_race    = load_events("race")
    status         = get_status()
    configs        = list_configs()
    active_config  = get_active_config_name()

    present: set[str] = set()
    for car in cars:
        for key, mapping in _PROP_MAPS.items():
            val   = car.get(key)
            label = mapping.get(val, "") if val is not None else ""
            car[f"{key}_label"] = label
            if label:
                present.add(label)

    car_categories = [c for c in _CATEGORY_ORDER if c in present]
    pi_values      = [c["performance_indicator"] for c in cars if c.get("performance_indicator") is not None]
    pi_min         = min(pi_values) if pi_values else 0.0
    pi_max         = max(pi_values) if pi_values else 999.0

    return render_template(
        "server.html",
        config=config,
        cars=cars,
        events_practice=events_practice,
        events_race=events_race,
        status=status,
        configs=configs,
        active_config=active_config,
        car_categories=car_categories,
        pi_min=pi_min,
        pi_max=pi_max,
    )
