from flask import Blueprint, render_template
from flask_login import login_required
from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name,
)
from app.services.process_manager import get_status

admin_bp = Blueprint("admin", __name__)

# Correspondance des valeurs numériques → labels affichés dans l'UI
_PROP_MAPS = {
    "property_1": {0: "Road", 1: "Race", 2: "Track"},
    "property_2": {0: "Modern", 1: "Vintage", 2: "YT"},
    "property_3": {0: "ICE", 1: "EV", 2: "Hybrid"},
}
# Ordre d'affichage des boutons (identique à l'appli de bureau)
_CATEGORY_ORDER = ["Road", "Race", "Track", "Modern", "Vintage", "YT", "ICE", "EV", "Hybrid"]


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

    # Ajouter les labels traduits à chaque voiture + collecter les catégories présentes
    present: set[str] = set()
    for car in cars:
        for key, mapping in _PROP_MAPS.items():
            val = car.get(key)
            label = mapping.get(val, "") if val is not None else ""
            car[f"{key}_label"] = label
            if label:
                present.add(label)

    car_categories = [c for c in _CATEGORY_ORDER if c in present]

    # Bornes PI pour le slider double
    pi_values = [c["performance_indicator"] for c in cars if c.get("performance_indicator") is not None]
    pi_min = min(pi_values) if pi_values else 0.0
    pi_max = max(pi_values) if pi_values else 999.0

    return render_template(
        "dashboard.html",
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
