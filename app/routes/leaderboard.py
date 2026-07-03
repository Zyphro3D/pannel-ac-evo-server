import json
import logging
import time
from flask import Blueprint, redirect, url_for
from app.models import SessionResult
from app.services.server_config import load_cars, CAR_PROP_MAPS as _PROP_MAPS, CAR_CATEGORY_ORDER as _CAT_ORDER

log = logging.getLogger(__name__)

leaderboard_bp = Blueprint("leaderboard", __name__)

_circuits_cache: list | None = None
_circuits_cache_at: float = 0.0
_CIRCUITS_TTL = 60.0


def invalidate_circuits_cache():
    global _circuits_cache, _circuits_cache_at
    _circuits_cache = None
    _circuits_cache_at = 0.0


def _build_car_lookup() -> dict:
    try:
        cars = load_cars()
    except Exception:
        return {}
    lookup = {}
    for c in cars:
        key = c["display_name"].split(" - ")[0]
        if key not in lookup:
            lookup[key] = {
                "p1": _PROP_MAPS["property_1"].get(c.get("property_1"), ""),
                "pi": round(c.get("performance_indicator", 0), 1),
            }
    return lookup


def build_circuits() -> list:
    """Construit la liste des meilleurs temps par circuit (cache 60s)."""
    global _circuits_cache, _circuits_cache_at
    if _circuits_cache is not None and (time.monotonic() - _circuits_cache_at) < _CIRCUITS_TTL:
        return _circuits_cache

    from app.services.results_parser import get_parsed

    car_lookup = _build_car_lookup()
    best: dict[tuple, dict] = {}

    rows = SessionResult.query.order_by(SessionResult.received_at.asc()).limit(2000).all()
    for r in rows:
        try:
            parsed = get_parsed(r)
        except Exception:
            continue

        track   = parsed.get("track", "")
        layout  = parsed.get("layout", "")
        circuit = f"{track} — {layout}" if layout else track
        if not circuit.strip():
            continue

        is_race = parsed.get("is_race", False)

        for driver in parsed.get("standings", []):
            car_name = driver.get("car", "")
            if not car_name:
                continue

            if is_race:
                lap_ms  = driver.get("fastest_lap_ms", 0)
                lap_str = driver.get("fastest_lap", "")
            else:
                lap_ms  = driver.get("best_lap_ms", 0)
                lap_str = driver.get("best_lap", "")

            if not lap_ms or lap_ms <= 0:
                continue

            key = (circuit, car_name)
            if key not in best or lap_ms < best[key]["time_ms"]:
                info = car_lookup.get(car_name, {})
                best[key] = {
                    "time_ms": lap_ms,
                    "time":    lap_str,
                    "driver":  driver.get("nickname", ""),
                    "car":     car_name,
                    "p1":      info.get("p1", ""),
                    "pi":      info.get("pi", 0),
                }

    circuit_map: dict[str, list] = {}
    for (circuit, _), entry in best.items():
        circuit_map.setdefault(circuit, []).append(entry)

    circuits = []
    for circuit_name in sorted(circuit_map.keys()):
        entries = sorted(circuit_map[circuit_name], key=lambda x: x["time_ms"])

        by_cat: dict[str, list] = {}
        for e in entries:
            cat = e["p1"] or "Autre"
            by_cat.setdefault(cat, []).append(e)

        ordered_cats = [(cat, by_cat[cat]) for cat in _CAT_ORDER if cat in by_cat]
        if "Autre" in by_cat:
            ordered_cats.append(("Autre", by_cat["Autre"]))

        circuits.append({
            "name":       circuit_name,
            "best":       entries[0],
            "categories": ordered_cats,
            "total":      len(entries),
        })

    _circuits_cache = circuits
    _circuits_cache_at = time.monotonic()
    return circuits


@leaderboard_bp.route("/leaderboard")
def leaderboard():
    return redirect(url_for("public.results", v="leaderboard"))
