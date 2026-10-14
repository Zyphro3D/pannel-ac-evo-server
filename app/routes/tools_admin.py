"""Outils d'administration : journal d'audit, remise à zéro du fair-play, exports CSV,
sauvegarde / restauration, santé du serveur (v2.3.0)."""
import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, redirect, send_file, url_for, request, flash
from flask_babel import _

from app.models import AuditLog, Driver, SessionResult, _utcnow
from app import limiter
from app.services import audit, csv_export
from app.services.database import db
from app.utils import admin_required, superadmin_required

log = logging.getLogger(__name__)

tools_bp = Blueprint("tools", __name__)

_AUDIT_PAGE = 50


# ── Fair-play : remise à zéro ────────────────────────────────────────────────

@tools_bp.route("/results/fairplay/reset", methods=["POST"])
@superadmin_required
def fairplay_reset():
    from app.services import fairplay
    when = fairplay.reset()
    audit.record("fairplay.reset", detail={"since": when})
    flash(_("Compteur fair-play remis à zéro : seuls les incidents à partir de maintenant comptent."), "success")
    return redirect(url_for("public.results", v="fairplay"))


# ── Journal d'audit ──────────────────────────────────────────────────────────

def _audit_query():
    q = AuditLog.query
    actor = request.args.get("actor", "").strip()
    action = request.args.get("action", "").strip()
    only_fail = request.args.get("fail") == "1"
    days = request.args.get("days", "30")
    if actor:
        q = q.filter(AuditLog.actor == actor)
    if action:
        q = q.filter(AuditLog.action.like(action.replace("%", "") + "%"))
    if only_fail:
        q = q.filter(AuditLog.ok.is_(False))
    if days.isdigit() and int(days) > 0:
        q = q.filter(AuditLog.ts >= _utcnow() - timedelta(days=int(days)))
    return q.order_by(AuditLog.id.desc())


@tools_bp.route("/admin/audit")
@superadmin_required
def audit_page():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    q = _audit_query()
    total = q.count()
    rows = q.offset((page - 1) * _AUDIT_PAGE).limit(_AUDIT_PAGE).all()
    actors = [r[0] for r in db.session.query(AuditLog.actor).filter(AuditLog.actor != "").distinct().order_by(AuditLog.actor)]
    return render_template("audit.html", rows=rows, total=total, page=page, per_page=_AUDIT_PAGE, actors=actors,
                           retention=audit.retention_days(), args=request.args,
                           qargs={k: v for k, v in request.args.items() if k != "page"})


@tools_bp.route("/admin/audit.csv")
@superadmin_required
def audit_csv():
    rows = [(r.ts.isoformat(sep=" ", timespec="seconds"), r.actor, r.actor_role, r.ip, r.action, r.target,
             r.detail, "ok" if r.ok else "échec") for r in _audit_query().limit(50000)]
    audit.record("export.audit", detail={"rows": len(rows)})
    return csv_export.response("journal-audit.csv",
                               ["date (UTC)", "acteur", "rôle", "adresse IP", "action", "cible", "détail", "résultat"], rows)


# ── Exports CSV ──────────────────────────────────────────────────────────────

_STANDING_HEADERS = ["position", "pilote", "voiture", "numéro", "grille", "tours", "temps course",
                     "meilleur tour", "meilleur tour (ms)", "pénalités", "contacts", "murs", "objets", "dégâts"]


def _standing_row(d: dict) -> list:
    st = d.get("incident_stats") or {}
    return [d.get("position"), d.get("nickname"), d.get("car"), d.get("race_number"), d.get("starting_position"),
            d.get("laps_count"), d.get("race_time") if d.get("race_time") not in (None, "—") else "",
            d.get("best_lap") if d.get("best_lap") not in (None, "—") else d.get("fastest_lap", ""),
            d.get("best_lap_ms") or d.get("fastest_lap_ms") or "", d.get("penalty_count", 0),
            st.get("car", 0), st.get("wall", 0), st.get("object", 0), st.get("damage", 0)]


@tools_bp.route("/results/<int:result_id>/export.csv")
@limiter.limit("30 per minute")
def result_csv(result_id):
    """Classement d'une session (mêmes données que la page de détail, publique)."""
    from app.services.results_parser import get_parsed
    r = db.session.get(SessionResult, result_id)
    if r is None:
        return ("", 404)
    parsed = get_parsed(r)
    rows = [_standing_row(d) for d in parsed.get("standings", [])]
    name = f"session-{result_id}-{(parsed.get('track') or 'circuit').lower().replace(' ', '_')}.csv"
    return csv_export.response(name, _STANDING_HEADERS, rows)


@tools_bp.route("/export/results.csv")
@admin_required
def results_csv():
    """Tous les résultats importés : une ligne par pilote et par session (avec SteamID)."""
    from app.services.results_parser import get_parsed
    days = request.args.get("days", "")
    q = SessionResult.query.order_by(SessionResult.received_at.asc())
    if days.isdigit() and int(days) > 0:
        q = q.filter(SessionResult.received_at >= _utcnow() - timedelta(days=int(days)))
    rows = []
    for r in q.yield_per(100):
        try:
            parsed = get_parsed(r)
        except Exception:
            continue
        meta = [r.id, r.received_at.isoformat(sep=" ", timespec="seconds") if r.received_at else "",
                r.server_id or "", parsed.get("track", ""), parsed.get("layout", ""), parsed.get("session_type", "")]
        for d in parsed.get("standings", []):
            rows.append(meta + [d.get("player_id", "")] + _standing_row(d))
    audit.record("export.results", detail={"rows": len(rows), "days": days or "tout"})
    return csv_export.response("resultats.csv", ["session", "date (UTC)", "serveur", "circuit", "layout", "type", "steamid"]
                               + _STANDING_HEADERS, rows)


@tools_bp.route("/export/drivers.csv")
@admin_required
def drivers_csv():
    rows = [(d.id, d.ingame_name, d.email, d.steam_id or "", d.status,
             d.created_at.isoformat(sep=" ", timespec="seconds") if d.created_at else "")
            for d in Driver.query.order_by(Driver.ingame_name).all()]
    audit.record("export.drivers", detail={"rows": len(rows)})
    return csv_export.response("pilotes.csv", ["id", "pseudo", "email", "steamid", "statut", "inscrit le (UTC)"], rows)


@tools_bp.route("/export/fairplay.csv")
@limiter.limit("30 per minute")
def fairplay_csv():
    from app.services.fairplay import build_fairplay
    ranking = build_fairplay(lambda: SessionResult.query.order_by(SessionResult.received_at.asc()).yield_per(100))
    rows, rank = [], 0
    for d in ranking:
        if d["ranked"]:
            rank += 1
        rows.append([rank if d["ranked"] else "", d["nickname"], d["sessions"], d["laps"], d["contacts"], d["walls"],
                     d["objects"], d["damage"], round(d["max_impact_kmh"], 1), d["penalties"], d["severe_penalties"],
                     d["per_lap"]])
    return csv_export.response("fairplay.csv", ["rang", "pilote", "sessions", "tours", "contacts", "murs", "objets",
                                                "dégâts", "choc max (km/h)", "sanctions", "sanctions lourdes",
                                                "incidents par tour"], rows)


# ── Sauvegarde / restauration (super-admin) ──────────────────────────────────

@tools_bp.route("/admin/backup")
@superadmin_required
def backup_page():
    from app.services import backup
    import os
    return render_template("backup.html", backups=backup.list_backups(),
                           auto=os.environ.get("BACKUP_AUTO", "true").lower() == "true",
                           keep=os.environ.get("BACKUP_KEEP", "7"),
                           restored=request.args.get("restored"))


@tools_bp.route("/admin/backup/settings", methods=["POST"])
@superadmin_required
def backup_settings():
    import os
    from app.routes.admin import _write_env_file, _env_write_lock
    try:
        keep = str(max(1, min(60, int(request.form.get("BACKUP_KEEP", 7) or 7))))
    except ValueError:
        keep = "7"
    new_vals = {"BACKUP_AUTO": "true" if "true" in request.form.getlist("BACKUP_AUTO") else "false", "BACKUP_KEEP": keep}
    with _env_write_lock:
        _write_env_file(new_vals)
        for k, v in new_vals.items():
            os.environ[k] = v
            current_app.config[k] = (v == "true") if k == "BACKUP_AUTO" else v
    audit.record("backup.settings", detail=new_vals)
    flash(_("Réglages de sauvegarde enregistrés."), "success")
    return redirect(url_for("tools.backup_page"))


@tools_bp.route("/admin/backup/create", methods=["POST"])
@superadmin_required
def backup_create():
    from app.services import backup
    secrets_in = "true" in request.form.getlist("include_secrets")
    try:
        f = backup.create_backup("manuelle", include_secrets=secrets_in)
    except Exception as e:
        log.exception("sauvegarde impossible")
        audit.record("backup.create", ok=False, detail=str(e)[:200])
        flash(_("La sauvegarde a échoué : %(e)s", e=str(e)[:200]), "error")
        return redirect(url_for("tools.backup_page"))
    audit.record("backup.create", target=f.name, detail={"settings": secrets_in})
    flash(_("Sauvegarde créée : %(n)s", n=f.name), "success")
    return redirect(url_for("tools.backup_page"))


@tools_bp.route("/admin/backup/<name>/download")
@superadmin_required
def backup_download(name):
    from app.services import backup
    try:
        f = backup.backup_path(name)
    except backup.BackupError as e:
        flash(str(e), "error")
        return redirect(url_for("tools.backup_page"))
    audit.record("backup.download", target=name)
    return send_file(f, as_attachment=True, download_name=name, mimetype="application/zip")


@tools_bp.route("/admin/backup/<name>/delete", methods=["POST"])
@superadmin_required
def backup_delete(name):
    from app.services import backup
    try:
        backup.delete_backup(name)
        audit.record("backup.delete", target=name)
        flash(_("Sauvegarde supprimée."), "success")
    except backup.BackupError as e:
        flash(str(e), "error")
    return redirect(url_for("tools.backup_page"))


@tools_bp.route("/admin/backup/<name>/restore", methods=["POST"])
@superadmin_required
def backup_restore_stored(name):
    return _do_restore(name=name)


@tools_bp.route("/admin/backup/upload", methods=["POST"])
@superadmin_required
def backup_restore_upload():
    return _do_restore(upload=request.files.get("file"))


def _do_restore(name=None, upload=None):
    import tempfile
    from pathlib import Path
    from app.services import backup
    confirm = request.form.get("confirm", "").strip().upper()
    if confirm != "RESTAURER":
        flash(_("Tapez RESTAURER pour confirmer."), "error")
        return redirect(url_for("tools.backup_page"))
    tmp = None
    label = name or ""
    try:
        if upload is not None and upload.filename:
            tmp = Path(tempfile.mkdtemp(prefix="panel-upload-")) / "upload.zip"
            upload.save(str(tmp))
            path = tmp
            label = "(fichier envoyé)"
        else:
            path = backup.backup_path(name or "")
            label = name
        result = backup.restore(path)
    except backup.BackupError as e:
        audit.record("backup.restore", target=label, ok=False, detail=str(e)[:200])
        flash(str(e), "error")
        return redirect(url_for("tools.backup_page"))
    except Exception as e:
        log.exception("restauration impossible")
        audit.record("backup.restore", ok=False, detail=str(e)[:200])
        flash(_("La restauration a échoué : %(e)s", e=str(e)[:200]), "error")
        return redirect(url_for("tools.backup_page"))
    finally:
        if tmp is not None:
            import shutil
            shutil.rmtree(tmp.parent, ignore_errors=True)
    audit.record("backup.restore", target=label, detail={"safety_backup": result["safety_backup"]})
    return redirect(url_for("tools.backup_page", restored=result["safety_backup"]))


# ── Santé du serveur ─────────────────────────────────────────────────────────

def _spark(points, key, width=300, height=48, ceil=None):
    """Courbe SVG (attribut ``points``) d'une série de mesures ; vide si moins de 2 points."""
    vals = [p[key] for p in points]
    if len(vals) < 2:
        return ""
    top = ceil or max(max(vals), 1e-9)
    step = width / (len(vals) - 1)
    return " ".join(f"{i * step:.1f},{height - (min(v, top) / top) * (height - 4) - 2:.1f}" for i, v in enumerate(vals))


@tools_bp.route("/admin/health")
@admin_required
def health_page():
    from app.services import health
    snap = health.snapshot(current_app.config)
    for srv in snap["servers"]:
        h = srv["history"]
        srv["spark"] = {"cpu": _spark(h, "cpu"), "mem": _spark(h, "mem"), "players": _spark(h, "players")}
    return render_template("health.html", snap=snap)


@tools_bp.route("/admin/health.json")
@admin_required
def health_json():
    from app.services import health
    snap = health.snapshot(current_app.config)
    for k in ("last_result_at", "last_backup_at"):
        snap[k] = snap[k].isoformat() if snap[k] else None
    return jsonify(snap)
