"""Carte des accrochages (publique, comme les résultats dont elle est tirée)."""
import logging

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from app import limiter
from app.models import SessionResult
from app.services import collision_map

log = logging.getLogger(__name__)

collisions_bp = Blueprint("collisions", __name__)


def _rows():
    return SessionResult.query.order_by(SessionResult.received_at.asc()).yield_per(100)


def _label(r, parsed: dict) -> str:
    fmt = current_app.jinja_env.filters.get("local_dt_short")
    when = fmt(r.received_at) if fmt and r.received_at else ""
    kind = current_app.jinja_env.filters["session_type_label"](parsed.get("session_type", "")) \
        if "session_type_label" in current_app.jinja_env.filters else parsed.get("session_type", "")
    return f"{when} · {kind}".strip(" ·")


@collisions_bp.route("/accrochages")
@limiter.limit("60 per minute")
def collisions_page():
    circuits = collision_map.circuits_with_hits(_rows, _label)
    slug = request.args.get("c", "")
    if slug not in {c["slug"] for c in circuits}:
        slug = circuits[0]["slug"] if circuits else ""
    return render_template("collisions.html", circuits=circuits, slug=slug)


@collisions_bp.route("/accrochages/data/<slug>.json")
@limiter.limit("60 per minute")
def collisions_data(slug):
    from app.services.results_parser import get_parsed
    if not collision_map.has_map(slug):
        abort(404)
    only = request.args.get("session", type=int)
    sessions = []
    for r in _rows():
        if only is not None and r.id != only:
            continue
        try:
            p = get_parsed(r)
        except Exception:
            continue
        if collision_map.slug_for(p) == slug and p.get("hits"):
            sessions.append((r.id, _label(r, p), p))
    resp = jsonify(collision_map.build(sessions, slug, only))
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp
