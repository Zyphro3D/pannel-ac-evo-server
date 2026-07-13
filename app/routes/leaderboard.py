import logging
import time
from flask import Blueprint, redirect, url_for, request, render_template
from app.models import SessionResult, TrackMeta
from app.services.server_config import load_cars, CAR_PROP_MAPS as _PROP_MAPS, CAR_CATEGORY_ORDER as _CAT_ORDER

log = logging.getLogger(__name__)

leaderboard_bp = Blueprint("leaderboard", __name__)

_circuits_cache: dict | None = None
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


def _collect_best_by_track() -> dict:
    """Meilleur temps par (track, layout, véhicule), tous circuits confondus (cache 60s)."""
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

        track  = parsed.get("track", "")
        layout = parsed.get("layout", "")
        if not track.strip():
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

            key = (track, layout, car_name)
            if key not in best or lap_ms < best[key]["time_ms"]:
                info = car_lookup.get(car_name, {})
                best[key] = {
                    "time_ms": lap_ms,
                    "time":    lap_str,
                    "driver":  driver.get("nickname", ""),
                    "car":     car_name,
                    "p1":      info.get("p1", ""),
                    "pi":      info.get("pi", 0),
                    "splits":  driver.get("best_splits", []),
                }

    by_track: dict[tuple, list] = {}
    for (track, layout, _car), entry in best.items():
        by_track.setdefault((track, layout), []).append(entry)

    _circuits_cache = by_track
    _circuits_cache_at = time.monotonic()
    return by_track


def build_circuit_overview() -> list:
    """Un élément par circuit actif (TrackMeta), avec ou sans résultat.

    Tri : circuits avec un temps enregistré d'abord (ordre alphabétique),
    puis circuits sans résultat (ordre alphabétique) — un circuit avec temps
    n'est jamais moins prioritaire qu'un circuit sans temps, peu importe le nom.
    """
    by_track = _collect_best_by_track()
    overview = []
    for tm in TrackMeta.query.filter_by(is_active=True).order_by(TrackMeta.track_name).all():
        entries = by_track.get((tm.track_name, tm.layout), [])
        best = min(entries, key=lambda e: e["time_ms"]) if entries else None
        overview.append({"track_meta": tm, "best": best, "total": len(entries)})
    overview.sort(key=lambda c: (c["best"] is None, c["track_meta"].track_name))
    return overview


def get_circuit_entries(track_meta, car: str | None = None, category: str | None = None,
                         pi_min: float | None = None, pi_max: float | None = None):
    """Entrées filtrées pour un circuit + options de filtre disponibles (véhicules/catégories/PI)."""
    by_track = _collect_best_by_track()
    entries = list(by_track.get((track_meta.track_name, track_meta.layout), []))
    entries.sort(key=lambda e: e["time_ms"])

    cars_available = sorted({e["car"] for e in entries})
    cats_available = [c for c in _CAT_ORDER if any(e["p1"] == c for e in entries)]
    pis = [e["pi"] for e in entries if e["pi"]]
    filter_options = {
        "cars": cars_available,
        "categories": cats_available,
        "pi_bounds": (min(pis), max(pis)) if pis else (0, 0),
    }

    filtered = entries
    if car:
        filtered = [e for e in filtered if e["car"] == car]
    if category:
        filtered = [e for e in filtered if e["p1"] == category]
    if pi_min is not None:
        filtered = [e for e in filtered if e["pi"] >= pi_min]
    if pi_max is not None:
        filtered = [e for e in filtered if e["pi"] <= pi_max]

    return filtered, filter_options


@leaderboard_bp.route("/leaderboard")
def leaderboard():
    return redirect(url_for("public.results", v="leaderboard"))


@leaderboard_bp.route("/results/circuit/<int:track_id>")
def circuit_detail(track_id):
    tm = TrackMeta.query.get_or_404(track_id)
    car      = request.args.get("car") or None
    category = request.args.get("cat") or None
    pi_min   = request.args.get("pi_min", type=float)
    pi_max   = request.args.get("pi_max", type=float)

    entries, filter_options = get_circuit_entries(tm, car, category, pi_min, pi_max)

    if request.headers.get("HX-Request"):
        return render_template("_partials/circuit_results_table.html", entries=entries)

    return render_template("circuit_detail.html", track=tm, entries=entries,
                           filter_options=filter_options,
                           car=car, category=category, pi_min=pi_min, pi_max=pi_max)
