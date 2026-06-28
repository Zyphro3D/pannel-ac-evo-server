import re
import json as _json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_MEDIA_ROOT = Path(__file__).parent.parent.parent / "media"

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_babel import _, get_locale
from sqlalchemy.orm import selectinload as _pub_selectinload
from flask_login import current_user, login_user, login_required
from app import limiter

from app.models import Driver, Event, EventRegistration, Server, SessionResult
from app.routes.auth import _validate_password
from app.services.database import db
from app.services.process_manager import get_status, get_player_history
from app.services.results_parser import get_parsed
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
    Groupe les sessions par run_id (identifiant unique généré à chaque start_server).

    Passe 1 — sessions avec run_id : regroupement exact, sans heuristique.
    Passe 2 — sessions sans run_id (anciens résultats) : fallback anchor-on-Race.

    Retourne (sessions_annotées, groupes_triés_plus_récent_en_premier).
    """
    if not sessions:
        return sessions, []

    chrono  = sorted(sessions, key=lambda s: s["received_at"])
    id_to_s = {s["id"]: s for s in sessions}
    used    = set()
    raw_groups: list[dict] = []

    # ── Passe 1 : run_id (fiable) ─────────────────────────────────────────
    by_run: dict[str, dict] = {}
    for s in chrono:
        rid = s.get("run_id") or ""
        if not rid:
            continue
        if rid not in by_run:
            g = {"session_ids": [], "run_id": rid,
                 "config_name": s.get("config_name") or ""}
            by_run[rid] = g
            raw_groups.append(g)
        by_run[rid]["session_ids"].append(s["id"])
        used.add(s["id"])

    # ── Passe 2 : fallback anchor-on-Race (anciens résultats sans run_id) ─
    remaining = [s for s in chrono if s["id"] not in used]
    for i, s in enumerate(remaining):
        if s["id"] in used:
            continue
        if (s["parsed"].get("session_type") or "").lower() != "race":
            continue

        track       = (s["parsed"].get("track") or "").strip()
        group_ids   = [s["id"]]
        used.add(s["id"])
        frontier_t  = s["received_at"]

        for j in range(i - 1, -1, -1):
            prev = remaining[j]
            if prev["id"] in used:
                continue
            if (prev["parsed"].get("track") or "").strip() != track:
                break
            if (frontier_t - prev["received_at"]) > _MAX_INTRA_GAP:
                break
            if (prev["parsed"].get("session_type") or "").lower() not in \
                    {"practice", "qualifying", "warmup", "race"}:
                break
            group_ids.insert(0, prev["id"])
            used.add(prev["id"])
            frontier_t = prev["received_at"]

        raw_groups.append({"session_ids": group_ids, "run_id": None, "config_name": None})

    # Sessions restantes sans run_id = standalone
    for s in chrono:
        if s["id"] not in used:
            raw_groups.append({"session_ids": [s["id"]], "run_id": None, "config_name": None})
            used.add(s["id"])

    # ── Couleurs ──────────────────────────────────────────────────────────
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

    # ── Tri : groupe le plus récent en premier ────────────────────────────
    raw_groups.sort(
        key=lambda g: max(id_to_s[sid]["received_at"] for sid in g["session_ids"]),
        reverse=True,
    )

    # ── Annotation + construction template ───────────────────────────────
    id_to_group = {sid: g for g in raw_groups for sid in g["session_ids"]}
    for s in sessions:
        g = id_to_group.get(s["id"], {})
        s["wkd_color"]  = g.get("color", _PRACTICE_COLOR)
        s["is_weekend"] = g.get("is_weekend", False)

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
    servers = (Server.query
               .filter_by(is_enabled=True)
               .order_by(Server.sort_order, Server.id)
               .all())

    statuses     = {}
    server_infos = {}
    player_histories = {}
    for srv in servers:
        st = get_status(srv.id)
        statuses[srv.id]     = st
        server_infos[srv.id] = get_running_server_info(srv.id) if st["running"] else None
        player_histories[srv.id] = _json.dumps(get_player_history(srv.id)[-30:]) if st["running"] else "[]"

    # Enrichir les infos serveur avec l'image bannière du circuit en cours
    for srv in servers:
        si = server_infos.get(srv.id)
        if si:
            slug = si.get("track_slug", "")
            banner = _MEDIA_ROOT / "circuits" / f"{slug}.webp"
            si["banner_image"] = f"circuits/{slug}.webp" if slug and banner.exists() else ""

    now = _now_utc()
    ongoing = (Event.query
               .filter_by(status="published")
               .filter(Event.date < now)
               .order_by(Event.date.desc())
               .all())

    from zoneinfo import ZoneInfo as _ZI
    from babel.dates import format_date as _babel_fmt_date
    _panel_tz = _ZI(current_app.config.get("PANEL_TIMEZONE", "Europe/Paris"))
    _loc = str(get_locale())

    def _ev_dict(ev):
        local_dt = ev.date.replace(tzinfo=timezone.utc).astimezone(_panel_tz)
        parts  = (ev.circuit or "").split("|")
        tslug  = parts[0].strip().lower().replace(" ", "_") if parts else ""
        tpath  = _MEDIA_ROOT / "circuits" / f"{tslug}.webp"
        conf   = sum(1 for r in ev.registrations if r.status == "confirmed")
        total  = ev.total_minutes
        h, m   = divmod(total, 60)
        return {
            "ev":        ev,
            "day":       local_dt.strftime("%d"),
            "month":     _babel_fmt_date(local_dt, format="MMM", locale=_loc).rstrip("."),
            "time":      local_dt.strftime("%H:%M"),
            "duration":  f"{h}h{m:02d}" if h else f"{m} min",
            "track_img": f"circuits/{tslug}.webp" if tslug and tpath.exists() else "",
            "confirmed": conf,
            "fill_pct":  min(100, round(conf / ev.max_drivers * 100)) if ev.max_drivers else 0,
        }

    raw_upcoming = (Event.query
                    .filter_by(status="published")
                    .filter(Event.date >= now)
                    .options(_pub_selectinload(Event.registrations))
                    .order_by(Event.date)
                    .limit(5)
                    .all())
    upcoming = [_ev_dict(ev) for ev in raw_upcoming]

    my_regs = {}
    if current_user.is_authenticated and current_user.is_pilot:
        for reg in EventRegistration.query.filter_by(driver_id=current_user.id).all():
            my_regs[reg.event_id] = reg

    recent_rows = (SessionResult.query
                   .order_by(SessionResult.received_at.desc())
                   .limit(50).all())
    recent_sessions = []
    for r in recent_rows:
        try:
            parsed = get_parsed(r)
        except Exception:
            parsed = {}
        if not parsed.get("standings") or not any(
            s.get("best_lap_ms") or s.get("fastest_lap_ms") for s in parsed["standings"]
        ):
            continue
        recent_sessions.append({"id": r.id, "received_at": r.received_at,
                                 "source": r.source, "parsed": parsed,
                                 "config_name": r.config_name,
                                 "run_id": r.run_id})
        if len(recent_sessions) >= 4:
            break

    # Enrichir les résultats récents avec l'image de la voiture du vainqueur
    if recent_sessions:
        from app.models import CarMeta
        # Collecte tous les noms de voiture vainqueurs en une passe, puis charge en 1 requête
        winner_names = {
            (s["parsed"].get("standings") or [{}])[0].get("car", "")
            for s in recent_sessions
        } - {""}
        car_by_name: dict[str, CarMeta] = {}
        if winner_names:
            cms = CarMeta.query.filter(
                CarMeta.display_name.in_(winner_names), CarMeta.image_path != ""
            ).all()
            car_by_name = {cm.display_name: cm for cm in cms}
            # Fallback préfixe pour les noms sans variante (ex: "BMW M4 GT3" vs "BMW M4 GT3 Evo 2")
            missing = winner_names - set(car_by_name)
            if missing:
                for cm in CarMeta.query.filter(CarMeta.image_path != "").all():
                    for name in list(missing):
                        if cm.display_name.startswith(name + " "):
                            car_by_name.setdefault(name, cm)
                            missing.discard(name)
                    if not missing:
                        break

        for s in recent_sessions:
            standings = s["parsed"].get("standings") or []
            car_name = standings[0].get("car", "") if standings else ""
            cm = car_by_name.get(car_name)
            s["car_image"] = cm.image_path if cm else ""

            # Banner du circuit pour le fond de la carte résultat
            track_slug = (s["parsed"].get("track") or "").lower().replace(" ", "_")
            banner = _MEDIA_ROOT / "circuits" / f"{track_slug}.webp"
            s["track_banner"] = f"circuits/{track_slug}.webp" if track_slug and banner.exists() else ""

    recent_sessions, _ = _group_sessions(recent_sessions)

    return render_template("public.html",
                           servers=servers,
                           statuses=statuses,
                           server_infos=server_infos,
                           player_histories=player_histories,
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
            mailer.send_registration_received(driver)
            discord_notifier.safe_notify(discord_notifier.notify_new_registration, driver)
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
        return redirect(url_for("admin.server"))

    regs = (EventRegistration.query
            .filter_by(driver_id=current_user.id)
            .options(_pub_selectinload(EventRegistration.event))
            .join(Event)
            .order_by(Event.date.asc())
            .all())

    now = _now_utc()
    upcoming_regs = [r for r in regs if r.event.date >= now]
    past_regs     = sorted([r for r in regs if r.event.date < now], key=lambda r: r.event.date, reverse=True)

    registered_ids = {r.event_id for r in regs}
    q = (Event.query
         .filter_by(status="published", is_public=False)
         .filter(Event.date >= now)
         .options(_pub_selectinload(Event.registrations)))
    if registered_ids:
        q = q.filter(Event.id.notin_(registered_ids))
    available = q.order_by(Event.date).all()

    return render_template("pilot_dashboard.html",
                           upcoming_regs=upcoming_regs,
                           past_regs=past_regs,
                           available=available)


@public_bp.route("/pilot/events/<int:event_id>/register", methods=["POST"])
@login_required
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
@limiter.limit("60 per minute")
def results():
    from app.routes.leaderboard import build_circuits

    initial_view = request.args.get("v", "overview")
    if initial_view not in ("overview", "results", "leaderboard"):
        initial_view = "overview"

    rows = (SessionResult.query
            .order_by(SessionResult.received_at.desc())
            .limit(50).all())
    sessions = []
    for r in rows:
        try:
            parsed = get_parsed(r)
        except Exception:
            parsed = {}
        sessions.append({"id": r.id, "received_at": r.received_at,
                         "source": r.source, "parsed": parsed,
                         "config_name": r.config_name,
                         "run_id": r.run_id})
    sessions, groups = _group_sessions(sessions)

    for s in sessions:
        track_slug = (s["parsed"].get("track") or "").lower().replace(" ", "_")
        banner = _MEDIA_ROOT / "circuits" / f"{track_slug}.webp"
        s["track_banner"] = f"circuits/{track_slug}.webp" if track_slug and banner.exists() else ""

    circuits = build_circuits()

    return render_template("results.html",
                           sessions=sessions, groups=groups,
                           circuits=circuits,
                           initial_view=initial_view)


@public_bp.route("/results/<int:result_id>")
@limiter.limit("60 per minute")
def result_detail(result_id):
    from app.models import SessionResult
    from app.services.results_parser import get_parsed
    r = SessionResult.query.get_or_404(result_id)
    parsed = get_parsed(r)
    return render_template("result_detail.html", result=r, parsed=parsed)


@public_bp.route("/pilot/events/<int:event_id>/unregister", methods=["POST"])
@login_required
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
