from flask import Blueprint, render_template
from flask_login import login_required
from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name,
)
from app.services.process_manager import get_status

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
@login_required
def dashboard():
    config = load_config()
    cars = load_cars()
    events_practice = load_events("practice")
    events_race = load_events("race")
    status = get_status()
    configs = list_configs()
    active_config = get_active_config_name()
    return render_template(
        "dashboard.html",
        config=config,
        cars=cars,
        events_practice=events_practice,
        events_race=events_race,
        status=status,
        configs=configs,
        active_config=active_config,
    )
