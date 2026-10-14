"""Championnats : pages publiques (liste, classement) et gestion par les admins."""
import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_babel import _

from app import limiter
from app.models import Championship, ChampionshipRound, SessionResult
from app.services import audit, championship as ch, csv_export
from app.services.database import db
from app.utils import admin_required

log = logging.getLogger(__name__)

championships_bp = Blueprint("championships", __name__)


# ── Calcul ───────────────────────────────────────────────────────────────────

def _compute(champ: Championship) -> dict:
    from app.services.results_parser import get_parsed
    points = ch.parse_points(champ.points)
    rounds, meta = [], []
    for r in champ.rounds:
        res = db.session.get(SessionResult, r.result_id)
        if res is None:
            continue
        try:
            parsed = get_parsed(res)
        except Exception:
            continue
        rounds.append({"label": r.label, "scores": ch.round_scores(parsed, points, champ.fastest_lap_bonus, champ.pole_bonus)})
        meta.append({"id": r.id, "label": r.label or parsed.get("track", ""), "track": parsed.get("track", ""),
                     "result_id": r.result_id, "date": res.received_at})
    table = ch.standings(rounds, champ.drop_worst, champ.min_rounds_ratio)
    return {"rounds": meta, "table": table, "points": points}


def _get_or_404(slug=None, cid=None) -> Championship:
    q = Championship.query
    champ = q.filter_by(slug=slug).first() if slug is not None else db.session.get(Championship, cid)
    if champ is None:
        abort(404)
    return champ


# ── Pages publiques ──────────────────────────────────────────────────────────

@championships_bp.route("/championships")
@limiter.limit("60 per minute")
def championships_list():
    items = []
    for c in Championship.query.filter_by(is_public=True).order_by(Championship.created_at.desc()).all():
        data = _compute(c)
        leader = next((p for p in data["table"] if p["ranked"]), None)
        items.append({"c": c, "rounds": len(data["rounds"]), "drivers": len(data["table"]), "leader": leader})
    return render_template("championships.html", items=items)


@championships_bp.route("/championships/<slug>")
@limiter.limit("60 per minute")
def championship_detail(slug):
    from flask_login import current_user
    champ = _get_or_404(slug=slug)
    if not champ.is_public and not (current_user.is_authenticated and current_user.is_admin):
        abort(404)
    return render_template("championship_detail.html", champ=champ, **_compute(champ))


@championships_bp.route("/championships/<slug>/export.csv")
@limiter.limit("30 per minute")
def championship_csv(slug):
    from flask_login import current_user
    champ = _get_or_404(slug=slug)
    if not champ.is_public and not (current_user.is_authenticated and current_user.is_admin):
        abort(404)
    data = _compute(champ)
    headers = ["rang", "pilote", "points"] + [m["label"] for m in data["rounds"]] + ["victoires", "podiums", "manches"]
    rows, rank = [], 0
    for p in data["table"]:
        if p["ranked"]:
            rank += 1
        cells = [("—" if not c else (f"{c['pts']}" + (" (retirée)" if c["dropped"] else ""))) for c in p["cells"]]
        rows.append([rank if p["ranked"] else "", p["nickname"], p["total"]] + cells + [p["wins"], p["podiums"], p["played"]])
    return csv_export.response(f"championnat-{champ.slug}.csv", headers, rows)


# ── Administration ───────────────────────────────────────────────────────────

def _fill(champ: Championship, form) -> str | None:
    """Applique le formulaire ; retourne un message d'erreur ou None."""
    name = form.get("name", "").strip()
    if not name:
        return _("Le nom est obligatoire.")
    try:
        points = ch.parse_points(form.get("points", ""))
    except ValueError:
        return _("Barème invalide : des nombres entiers entre 0 et 1000 séparés par des virgules (ex. 25,18,15,12,10).")

    def num(key, lo, hi, cast=int):
        try:
            return max(lo, min(hi, cast(form.get(key, 0) or 0)))
        except ValueError:
            return lo
    champ.name = name[:120]
    champ.description = form.get("description", "").strip()[:500]
    champ.points = ",".join(str(p) for p in points)
    champ.fastest_lap_bonus = num("fastest_lap_bonus", 0, 100)
    champ.pole_bonus = num("pole_bonus", 0, 100)
    champ.drop_worst = num("drop_worst", 0, 20)
    champ.min_rounds_ratio = num("min_rounds_ratio", 0.0, 1.0, float)
    champ.is_public = "true" in form.getlist("is_public")
    return None


@championships_bp.route("/admin/championships")
@admin_required
def championships_admin():
    return render_template("championships_admin.html",
                           champs=Championship.query.order_by(Championship.created_at.desc()).all())


@championships_bp.route("/admin/championships/create", methods=["POST"])
@admin_required
def championship_create():
    champ = Championship(name="", slug="")
    err = _fill(champ, request.form)
    if err:
        flash(err, "error")
        return redirect(url_for("championships.championships_admin"))
    base = ch.slugify(champ.name)
    slug, n = base, 2
    while Championship.query.filter_by(slug=slug).first():
        slug, n = f"{base}-{n}", n + 1
    champ.slug = slug
    db.session.add(champ)
    db.session.commit()
    flash(_("Championnat créé : ajoutez maintenant ses manches."), "success")
    return redirect(url_for("championships.championship_edit_page", cid=champ.id))


@championships_bp.route("/admin/championships/<int:cid>")
@admin_required
def championship_edit_page(cid):
    from app.services.results_parser import get_parsed
    champ = _get_or_404(cid=cid)
    used = {r.result_id for r in champ.rounds}
    candidates = []
    for res in SessionResult.query.order_by(SessionResult.received_at.desc()).limit(150).all():
        if res.id in used:
            continue
        try:
            parsed = get_parsed(res)
        except Exception:
            continue
        if not parsed.get("is_race"):
            continue
        humans = sum(1 for d in parsed.get("standings", []) if d.get("player_id"))
        if humans >= 1:
            candidates.append({"id": res.id, "date": res.received_at, "track": parsed.get("track", ""), "humans": humans})
    return render_template("championship_edit.html", champ=champ, candidates=candidates, **_compute(champ))


@championships_bp.route("/admin/championships/<int:cid>/edit", methods=["POST"])
@admin_required
def championship_edit(cid):
    champ = _get_or_404(cid=cid)
    err = _fill(champ, request.form)
    if err:
        db.session.rollback()
        flash(err, "error")
    else:
        db.session.commit()
        flash(_("Championnat enregistré."), "success")
    return redirect(url_for("championships.championship_edit_page", cid=cid))


@championships_bp.route("/admin/championships/<int:cid>/rounds/add", methods=["POST"])
@admin_required
def championship_round_add(cid):
    champ = _get_or_404(cid=cid)
    try:
        rid = int(request.form.get("result_id", ""))
    except ValueError:
        flash(_("Choisissez une course."), "error")
        return redirect(url_for("championships.championship_edit_page", cid=cid))
    if db.session.get(SessionResult, rid) is None or any(r.result_id == rid for r in champ.rounds):
        flash(_("Cette course est introuvable ou déjà comptée."), "error")
        return redirect(url_for("championships.championship_edit_page", cid=cid))
    pos = max((r.position for r in champ.rounds), default=0) + 1
    label = request.form.get("label", "").strip()[:120] or _("Manche %(n)s", n=pos)
    db.session.add(ChampionshipRound(championship_id=cid, result_id=rid, label=label, position=pos))
    db.session.commit()
    return redirect(url_for("championships.championship_edit_page", cid=cid))


@championships_bp.route("/admin/championships/<int:cid>/rounds/<int:rid>/delete", methods=["POST"])
@admin_required
def championship_round_delete(cid, rid):
    r = db.session.get(ChampionshipRound, rid)
    if r is not None and r.championship_id == cid:
        db.session.delete(r)
        db.session.commit()
    return redirect(url_for("championships.championship_edit_page", cid=cid))


@championships_bp.route("/admin/championships/<int:cid>/rounds/<int:rid>/move", methods=["POST"])
@admin_required
def championship_round_move(cid, rid):
    champ = _get_or_404(cid=cid)
    rounds = list(champ.rounds)
    idx = next((i for i, r in enumerate(rounds) if r.id == rid), None)
    if idx is not None:
        j = idx - 1 if request.form.get("dir") == "up" else idx + 1
        if 0 <= j < len(rounds):
            rounds[idx], rounds[j] = rounds[j], rounds[idx]
            for pos, r in enumerate(rounds, start=1):
                r.position = pos
            db.session.commit()
    return redirect(url_for("championships.championship_edit_page", cid=cid))


@championships_bp.route("/admin/championships/<int:cid>/delete", methods=["POST"])
@admin_required
def championship_delete(cid):
    champ = _get_or_404(cid=cid)
    audit.record("championships.delete_detail", target=champ.name)
    db.session.delete(champ)
    db.session.commit()
    flash(_("Championnat supprimé."), "success")
    return redirect(url_for("championships.championships_admin"))
