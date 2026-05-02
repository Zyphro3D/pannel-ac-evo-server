import re
import json as _json
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_babel import _
from flask_login import current_user, login_user
from app import limiter

from app.models import Driver, Event, EventRegistration
from app.routes.auth import _validate_password
from app.services.database import db
from app.services.process_manager import get_status
from app.services.server_config import get_running_server_info

public_bp = Blueprint("public", __name__)

_INGAME_RE = re.compile(r'^[A-Za-z0-9_\-.\s]{2,30}$')

_WEEKEND_PALETTE = [
    "#6366f1",  # indigo
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#ec4899",  # pink
]
_PRACTICE_COLOR = "#64748b"
# Max gap between two consecutive sessions to be considered part of the same race weekend.
# In ACE EVO, Race Weekend sessions run back-to-back automatically; 2h covers restarts/pauses
# without accidentally pulling in a standalone practice done hours earlier.
_MAX_INTRA_GAP = timedelta(hours=2)


def _group_sessions(sessions):
    """
    Groupe les sessions en Race Weekends et pratiques isolées.

    Passe 1 — sessions avec config_name (résultats récents) :
      Même config_name + gap ≤ _MAX_INTRA_GAP = même run.
      Fiable car le config_name est capturé au moment de la réception,
      quand le serveur tourne encore avec le même fichier de configuration.

    Passe 2 — sessions sans config_name (anciens résultats) :
      Fallback : ancrage sur la session Race, remontée en arrière
      session par session tant que le gap consécutif ≤ _MAX_INTRA_GAP
      et que le circuit correspond.

    Retourne (sessions_annotées, groupes_triés_plus_récent_en_premier).
    """
    if not sessions:
        return sessions, []

    chrono  = sorted(sessions, key=lambda s: s["received_at"])
    id_to_s = {s["id"]: s for s in sessions}
    used    = set()
    raw_groups: list[dict] = []

    # ── Passe 1 : groupement par config_name ──────────────────────────────
    # On parcourt chronologiquement; on cherche à attacher chaque session
    # au dernier groupe ouvert avec le même config_name si le gap le permet.
    open_by_config: dict[str, dict] = {}   # config_name -> groupe en cours

    for s in chrono:
        cfg = s.get("config_name") or ""
        if not cfg:
            continue
        t = s["received_at"]
        g = open_by_config.get(cfg)
        if g and (t - g["last_time"]) <= _MAX_INTRA_GAP:
            g["session_ids"].append(s["id"])
            g["last_time"] = t
        else:
            g = {"session_ids": [s["id"]], "last_time": t, "config_name": cfg}
            open_by_config[cfg] = g
            raw_groups.append(g)
        used.add(s["id"])

    # ── Passe 2 : fallback anchor-on-Race pour les sessions sans config_name ─
    remaining = [s for s in chrono if s["id"] not in used]

    for i, s in enumerate(remaining):
        if s["id"] in used:
            continue
        stype = (s["parsed"].get("session_type") or "").lower()
        if stype != "race":
            continue

        track        = (s["parsed"].get("track") or "").strip()
        weekend_ids  = [s["id"]]
        used.add(s["id"])
        frontier_t   = s["received_at"]

        for j in range(i - 1, -1, -1):
            prev = remaining[j]
            if prev["id"] in used:
                continue
            prev_track = (prev["parsed"].get("track") or "").strip()
            prev_type  = (prev["parsed"].get("session_type") or "").lower()
            if prev_track != track:
                break
            if (frontier_t - prev["received_at"]) > _MAX_INTRA_GAP:
                break
            if prev_type not in {"practice", "qualifying", "warmup", "race"}:
                break
            weekend_ids.insert(0, prev["id"])
            used.add(prev["id"])
            frontier_t = prev["received_at"]

        raw_groups.append({"session_ids": weekend_ids, "config_name": None,
                           "last_time": id_to_s[weekend_ids[-1]]["received_at"]})

    # Sessions restantes = pratiques isolées (chacune son propre groupe)
    for s in chrono:
        if s["id"] not in used:
            raw_groups.append({"session_ids": [s["id"]], "config_name": None,
                               "last_time": s["received_at"]})
            used.add(s["id"])

    # ── Détermination weekend / couleur ───────────────────────────────────
    color_idx = 0
    for g in raw_groups:
        types = {
            (id_to_s[sid]["parsed"].get("session_type") or "").lower()
            for sid in g["session_ids"]
        } - {""}
        is_weekend = "race" in types or len(types) > 1
        g["types"]      = types
        g["is_weekend"] = is_weekend
        if is_weekend:
            g["color"] = _WEEKEND_PALETTE[color_idx % len(_WEEKEND_PALETTE)]
            color_idx += 1
        else:
            g["color"] = _PRACTICE_COLOR

    # ── Tri décroissant par session la plus récente ───────────────────────
    raw_groups.sort(
        key=lambda g: max(id_to_s[sid]["received_at"] for sid in g["session_ids"]),
        reverse=True,
    )

    # ── Annotation des sessions ───────────────────────────────────────────
    id_to_group = {sid: g for g in raw_groups for sid in g["session_ids"]}
    for s in sessions:
        g = id_to_group.get(s["id"], {})
        s["wkd_color"]  = g.get("color", _PRACTICE_COLOR)
        s["is_weekend"] = g.get("is_weekend", False)

    # ── Construction des groupes pour le template ─────────────────────────
    ordered_groups = []
    for g in raw_groups:
        group_sessions = sorted(
            [id_to_s[sid] for sid in g["session_ids"]],
            key=lambda s: s["received_at"],
            reverse=True,
        )
        types = {
            (s["parsed"].get("session_type") or "").lower()
            for s in group_sessions
            if s["parsed"].get("session_type")
        }
        track = (group_sessions[0]["parsed"].get("track") or "").strip() if group_sessions else ""
        ordered_groups.append({
            "color":       g["color"],
            "is_weekend":  g["is_weekend"],
            "track":       track,
            "types":       types,
            "sessions":    group_sessions,
            "config_name": g.get("config_name"),
        })

    return sessions, ordered_groups


def _now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@public_bp.route("/")
def index():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))


    from app.models import SessionResult
    from app.services.results_parser import parse_result_file

    status      = get_status()
    server_info = get_running_server_info() if status["running"] else None
    now = _now_utc()
    ongoing = (Event.query
               .filter_by(status="published")
               .filter(Event.date < now)
               .order_by(Event.date.desc())
               .all())
    upcoming = (Event.query
                .filter_by(status="published")
                .filter(Event.date >= now)
                .order_by(Event.date)
                .all())

    my_regs = {}
    if current_user.is_authenticated and current_user.is_pilot:
        for reg in EventRegistration.query.filter_by(driver_id=current_user.id).all():
            my_regs[reg.event_id] = reg

    recent_rows = (SessionResult.query
                   .order_by(SessionResult.received_at.desc())
                   .limit(4).all())
    recent_sessions = []
    for r in recent_rows:
        try:
            parsed = parse_result_file(_json.loads(r.raw_json))
        except Exception:
            parsed = {}
        recent_sessions.append({"id": r.id, "received_at": r.received_at,
                                 "source": r.source, "parsed": parsed,
                                 "config_name": r.config_name})
    recent_sessions, _ = _group_sessions(recent_sessions)

    return render_template("public.html",
                           status=status,
                           server_info=server_info,
                           ongoing=ongoing,
                           upcoming=upcoming,
                           my_regs=my_regs,
                           recent_sessions=recent_sessions)


@public_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
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
         .filter_by(status="published", is_public=False)
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


@public_bp.route("/results")
def results():

    from app.models import SessionResult
    from app.services.results_parser import parse_result_file
    rows = (SessionResult.query
            .order_by(SessionResult.received_at.desc())
            .limit(50).all())
    sessions = []
    for r in rows:
        try:
            parsed = parse_result_file(_json.loads(r.raw_json))
        except Exception:
            parsed = {}
        sessions.append({"id": r.id, "received_at": r.received_at,
                         "source": r.source, "parsed": parsed,
                         "config_name": r.config_name})
    sessions, groups = _group_sessions(sessions)
    return render_template("results.html", sessions=sessions, groups=groups)


@public_bp.route("/results/<int:result_id>")
def result_detail(result_id):

    from app.models import SessionResult
    from app.services.results_parser import parse_result_file
    r = SessionResult.query.get_or_404(result_id)
    parsed = parse_result_file(_json.loads(r.raw_json))
    return render_template("result_detail.html", result=r, parsed=parsed)


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
