import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_babel import _
from flask_login import current_user

from app.models import AdminAccount, Driver, Event, SessionResult
from app.services.database import db
from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name, get_running_server_info,
    load_config_by_name,
)
from app.services.process_manager import get_status, get_server_logs
from app.services.results_parser import parse_result_file
from app.services import mailer, discord_notifier
from app.utils import admin_required as _admin_required

admin_bp = Blueprint("admin", __name__)

_PROP_MAPS = {
    "property_1": {0: "Road", 1: "Race", 2: "Track"},
    "property_2": {0: "Modern", 1: "Vintage", 2: "YT"},
    "property_3": {0: "ICE", 1: "EV", 2: "Hybrid"},
}
_CATEGORY_ORDER = ["Road", "Race", "Track", "Modern", "Vintage", "YT", "ICE", "EV", "Hybrid"]


@admin_bp.route("/dashboard")
@_admin_required
def dashboard():
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
    recent_results = []
    for r in SessionResult.query.order_by(SessionResult.received_at.desc()).limit(4).all():
        try:
            p = parse_result_file(json.loads(r.raw_json))
        except Exception:
            p = {}
        recent_results.append({"id": r.id, "received_at": r.received_at, "parsed": p})
    return render_template("admin_dashboard.html",
                           status=status,
                           server_info=server_info,
                           upcoming=upcoming,
                           pending_count=pending_count,
                           recent_results=recent_results)


@admin_bp.route("/administration")
@_admin_required
def administration():
    if not current_user.is_superadmin:
        return redirect(url_for("admin.dashboard"))
    cfg = mailer._cfg
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
    cfg      = mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    to       = request.form.get("to", "").strip() or (cfg.get("admin") or [None])[0]
    result_email = mailer.send_test(to) if to else {"ok": False, "error": "Aucune adresse destinataire"}
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
    cfg      = mailer._cfg
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
    configs       = list_configs()
    active_config = get_active_config_name()
    server_view   = request.args.get("view", "status")
    if not configs:
        flash(_("Aucun fichier de configuration trouvé dans CONFIGS_DIR. Créez-en un via le bouton ci-dessous."), "warning")
        return render_template("server.html", config=None, cars=[], events_practice=[], events_race=[],
                               status=get_status(), configs=[], active_config="",
                               car_categories=[], pi_min=0.0, pi_max=999.0,
                               server_view=server_view, config_summaries=[],
                               server_events=[], current_track={})
    config          = load_config()
    cars            = load_cars()
    events_practice = load_events("practice")
    events_race     = load_events("race")
    status          = get_status()

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
    media_circuits = Path(__file__).parent.parent.parent / "media" / "circuits"
    circuit_files  = {p.stem: p.name for p in media_circuits.glob("*.webp")} if media_circuits.exists() else {}

    def _slug(value: str) -> str:
        value = (value or "").lower().replace("&", "and")
        value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
        return value.replace("grand_prix", "gp")

    def _track_meta(cfg: dict) -> dict:
        ev = cfg.get("Event", {}) if cfg else {}
        raw = ev.get("SelectedTrackValue", "") or ""
        parts = raw.split("|")
        track = parts[0] if len(parts) > 0 else "—"
        layout = parts[1] if len(parts) > 1 else ""
        length = parts[3] if len(parts) > 3 else ""
        candidates = [
            _slug(f"{track}_{layout}"),
            _slug(layout),
            _slug(track),
        ]
        image = ""
        for candidate in candidates:
            if candidate in circuit_files:
                image = f"circuits/{circuit_files[candidate]}"
                break
        if not image:
            track_slug = _slug(track)
            for stem, fname in circuit_files.items():
                if stem == track_slug or stem.startswith(f"{track_slug}_"):
                    image = f"circuits/{fname}"
                    break
        return {
            "track": track,
            "layout": layout,
            "length_km": f"{float(length) / 1000:.2f} km" if str(length).replace(".", "", 1).isdigit() else "",
            "image": image,
        }

    weather_labels = {
        "GameModeSelectionWeatherType_CLEAR": _("Dégagé"),
        "GameModeSelectionWeatherType_OVERCAST": _("Nuageux"),
        "GameModeSelectionWeatherType_RAIN": _("Pluie"),
    }
    behavior_labels = {
        "GameModeSelectionWeatherBehaviour_STATIC": _("Statique"),
        "GameModeSelectionWeatherBehaviour_DYNAMIC": _("Dynamique"),
    }
    mode_labels = {
        "GameModeType_PRACTICE": _("Practice"),
        "GameModeType_RACE_WEEKEND": _("Race Weekend"),
    }

    def _config_summary(name: str) -> dict:
        cfg = load_config_by_name(name) or {}
        srv = cfg.get("Server", {})
        ev = cfg.get("Event", {})
        ses = cfg.get("Sessions", {})
        selected_cars = [c for c in ev.get("Cars", []) if c.get("IsSelected") or c.get("is_selected")]
        track_meta = _track_meta(cfg)
        return {
            "name": name,
            "active": name == active_config,
            "server_name": srv.get("ServerName", name),
            "max_players": srv.get("MaxPlayers", "—"),
            "mode": mode_labels.get(ev.get("SelectedSessionTypeValue"), ev.get("SelectedSessionTypeValue", "—")),
            "weather": weather_labels.get(ev.get("SelectedWeatherTypeValue"), "—"),
            "behavior": behavior_labels.get(ev.get("SelectedWeatherBehaviorValue"), "—"),
            "track": track_meta,
            "car_count": len(selected_cars),
            "practice_minutes": int(ses.get("PracticeSession", {}).get("Length", 0) or 0) // 60,
            "race_minutes": int(ses.get("RaceSession", {}).get("Length", 0) or 0) // 60,
        }

    def _recent_server_activity() -> list[dict]:
        keywords = (
            "connect", "disconnect", "joined", "left", "driver", "player",
            "session", "lap", "result", "start", "stop", "restart",
            "connexion", "déconnexion", "deconnexion", "pilote", "joueur",
        )
        items: list[dict] = []
        for raw in reversed((get_server_logs(180) or "").splitlines()):
            line = raw.strip()
            if not line:
                continue
            low = line.lower()
            if not any(k in low for k in keywords):
                continue
            time_hint = ""
            message = line
            if len(line) > 8 and line[2:3] == ":" and line[5:6] == ":":
                time_hint, message = line[:8], line[8:].strip(" -|")
            elif len(line) > 19 and line[4:5] == "-" and line[13:14] == ":":
                time_hint, message = line[11:19], line[19:].strip(" -|")
            items.append({"time": time_hint or "—", "message": message[:150]})
            if len(items) >= 8:
                break
        return items

    config_summaries = [_config_summary(name) for name in configs]
    current_track = _track_meta(config)
    current_event = config.get("Event", {})

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
        server_view=server_view,
        server_info=get_running_server_info(),
        config_summaries=config_summaries,
        server_events=Event.query.order_by(Event.date.asc()).all(),
        current_track=current_track,
        current_weather=weather_labels.get(current_event.get("SelectedWeatherTypeValue"), "—"),
        current_weather_behavior=behavior_labels.get(current_event.get("SelectedWeatherBehaviorValue"), "—"),
        current_mode=mode_labels.get(current_event.get("SelectedSessionTypeValue"), "—"),
        recent_server_activity=_recent_server_activity(),
    )


# ── Helpers .env ──────────────────────────────────────────────────────────────

_ENV_SECTIONS = [
    ("panel",    "Panel",          ["PANEL_TITLE", "PANEL_BANNER_IMG", "PANEL_LOGO_IMG", "PANEL_URL", "PANEL_TIMEZONE"]),
    ("security", "Sécurité",       ["SECRET_KEY", "SESSION_COOKIE_SECURE", "RESULTS_INGEST_SECRET"]),
    ("accounts", "Comptes",        []),  # Géré via AdminAccount en base de données
    ("server",   "Serveur ACE",    ["ACESERVER_HTTP_PORT", "ACESERVER_TCP_HOST", "ACESERVER_TCP_PORT",
                                    "ACESERVER_DIR", "CONFIGS_DIR"]),
    ("bot",      "Bot TCP",        ["ACE_BOT_STEAM_ID", "ACE_BOT_CAR_MODEL", "ACE_BOT_DISPLAY_NAME",
                                    "ACE_BOT_ADMIN_PASSWORD"]),
    ("discord",  "Discord",        ["DISCORD_WEBHOOK_URL", "DISCORD_PILOTS_WEBHOOK_URL", "DISCORD_INVITE_URL"]),
    ("mail",     "Email SMTP",     ["MAIL_SERVER", "MAIL_PORT", "MAIL_USE_TLS", "MAIL_USERNAME",
                                    "MAIL_PASSWORD", "MAIL_FROM", "MAIL_ADMIN"]),
    ("locale",   "Langue & Fuseau",["DEFAULT_LOCALE", "PANEL_TIMEZONE"]),
]
_ENV_DESCS = {
    "PANEL_TITLE":      "Nom affiché dans la sidebar",
    "PANEL_BANNER_IMG": "Nom de fichier dans media/banner/ (ex: banner.jpg)",
    "PANEL_LOGO_IMG":   "Logo sur la bannière (ex: logo.png)",
    "PANEL_URL":        "URL publique du panel (liens dans les emails)",
    "PANEL_TIMEZONE":   "Fuseau horaire (ex: Europe/Paris)",
    "SECRET_KEY":       "Clé de session Flask — générer avec python -c \"import secrets; print(secrets.token_hex(32))\"",
    "SESSION_COOKIE_SECURE": "true si HTTPS, false si HTTP local",
    "RESULTS_INGEST_SECRET": "Secret HMAC du webhook résultats (/api/results/ingest)",
    "ACESERVER_HTTP_PORT": "Port HTTP de l'API du serveur (défaut 8080)",
    "ACESERVER_TCP_HOST":  "Hôte TCP ACE EVO (défaut 127.0.0.1)",
    "ACESERVER_TCP_PORT":  "Port TCP ACE EVO (défaut 9700)",
    "ACESERVER_DIR":    "Dossier d'installation ACE EVO",
    "CONFIGS_DIR":      "Dossier des fichiers de configuration JSON",
    "ACE_BOT_STEAM_ID":      "Steam ID du bot (laisser vide pour désactiver)",
    "ACE_BOT_CAR_MODEL":     "Modèle de voiture du bot",
    "ACE_BOT_DISPLAY_NAME":  "Nom affiché du bot",
    "ACE_BOT_ADMIN_PASSWORD":"Mot de passe admin pour élever le bot",
    "DISCORD_WEBHOOK_URL":   "Webhook principal Discord",
    "DISCORD_PILOTS_WEBHOOK_URL": "Webhook pilotes Discord",
    "DISCORD_INVITE_URL":    "Lien d'invitation Discord affiché sur le panel",
    "MAIL_SERVER":      "Serveur SMTP (laisser vide pour désactiver les emails)",
    "MAIL_PORT":        "Port SMTP (ex: 587 ou 465)",
    "MAIL_USE_TLS":     "TLS : true ou false",
    "MAIL_USERNAME":    "Identifiant SMTP",
    "MAIL_PASSWORD":    "Mot de passe SMTP",
    "MAIL_FROM":        "Adresse expéditeur",
    "MAIL_ADMIN":       "Adresse(s) admin pour les notifications (séparées par virgule)",
    "DEFAULT_LOCALE":   "Langue par défaut : fr, en, es, de, it",
}
_SENSITIVE = {"SECRET_KEY", "MAIL_PASSWORD", "ACE_BOT_ADMIN_PASSWORD",
              "DISCORD_WEBHOOK_URL", "DISCORD_PILOTS_WEBHOOK_URL",
              "RESULTS_INGEST_SECRET"}


def _read_env_file():
    import os
    env_path = Path(__file__).parent.parent.parent / ".env"
    values = {}
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    values[k.strip()] = v.strip()
    # Fallback: keys not in the file are read from the running environment
    all_keys = {k for _, _, keys in _ENV_SECTIONS for k in keys}
    for k in all_keys:
        if k not in values and k in os.environ:
            values[k] = os.environ[k]
    return values, str(env_path)


def _write_env_file(new_values: dict):
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
    else:
        lines = []

    updated = set()
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in new_values:
                result.append(f"{k}={new_values[k]}\n")
                updated.add(k)
                continue
        result.append(line)

    for k, v in new_values.items():
        if k not in updated:
            result.append(f"{k}={v}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(result)


@admin_bp.route("/settings", methods=["GET", "POST"])
@_admin_required
def settings():
    if not current_user.is_superadmin:
        return redirect(url_for("admin.dashboard"))

    env_values, env_path = _read_env_file()
    saved = False
    tab = request.args.get("tab", "panel")

    if request.method == "POST":
        tab = request.form.get("_tab", "panel")
        new_vals = {}
        for _, _, keys in _ENV_SECTIONS:
            for k in keys:
                val = request.form.get(k)
                if val is not None:
                    new_vals[k] = val.strip()
        _write_env_file(new_vals)
        env_values.update(new_vals)
        flash(_("Paramètres sauvegardés — redémarrez le panel pour les appliquer."), "success")
        saved = True
        return redirect(url_for("admin.settings", tab=tab))

    media_banners = []
    media_dir = Path(__file__).parent.parent.parent / "media" / "banner"
    if media_dir.exists():
        media_banners = [f.name for f in sorted(media_dir.iterdir())
                         if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}]
    drivers_list   = Driver.query.order_by(Driver.created_at.desc()).limit(8).all()
    admin_accounts = AdminAccount.query.order_by(AdminAccount.role.desc(), AdminAccount.username).all()

    return render_template("settings.html",
                           env_values=env_values,
                           env_sections=_ENV_SECTIONS,
                           env_descs=_ENV_DESCS,
                           sensitive=_SENSITIVE,
                           env_path=env_path,
                           tab=tab,
                           saved=saved,
                           media_banners=media_banners,
                           drivers_list=drivers_list,
                           admin_accounts=admin_accounts,
                           server_status=get_status())


@admin_bp.route("/settings/upload-media", methods=["POST"])
@_admin_required
def upload_media():
    if not current_user.is_superadmin:
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    if request.content_length and request.content_length > 5 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Fichier trop volumineux (max 5 Mo)"}), 413
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "No file"}), 400
    ext = Path(f.filename).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in allowed:
        return jsonify({"ok": False, "error": "Type non autorisé"}), 400
    header = f.stream.read(16)
    f.stream.seek(0)
    signatures = {
        ".jpg":  [b"\xff\xd8\xff"],
        ".jpeg": [b"\xff\xd8\xff"],
        ".png":  [b"\x89PNG\r\n\x1a\n"],
        ".gif":  [b"GIF87a", b"GIF89a"],
        ".webp": [b"RIFF"],
    }
    if not any(header.startswith(sig) for sig in signatures[ext]):
        return jsonify({"ok": False, "error": "Signature de fichier invalide"}), 400
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(f.filename).stem)[:40].strip("_")
    safe_name = f"{uuid.uuid4().hex}_{safe_stem or 'banner'}{ext}"
    dest = Path(__file__).parent.parent.parent / "media" / "banner" / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    return jsonify({"ok": True, "filename": safe_name})


# ── Gestion des comptes administrateurs ──────────────────────────────────────

@admin_bp.route("/accounts/create", methods=["POST"])
@_admin_required
def account_create():
    if not current_user.is_superadmin:
        return jsonify({"ok": False, "error": "Accès refusé"}), 403
    username     = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    password     = request.form.get("password", "")
    role         = request.form.get("role", "admin")
    if not username or not password:
        flash(_("Identifiant et mot de passe requis."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    if role not in ("admin", "superadmin"):
        role = "admin"
    if AdminAccount.query.filter_by(username=username).first():
        flash(_("Cet identifiant est déjà utilisé."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    acc = AdminAccount(username=username, display_name=display_name, role=role)
    acc.set_password(password)
    db.session.add(acc)
    db.session.commit()
    flash(_("Compte créé avec succès."), "success")
    return redirect(url_for("admin.settings", tab="accounts"))


@admin_bp.route("/accounts/<int:account_id>/edit", methods=["POST"])
@_admin_required
def account_edit(account_id):
    if not current_user.is_superadmin:
        return jsonify({"ok": False, "error": "Accès refusé"}), 403
    acc = db.session.get(AdminAccount, account_id)
    if not acc:
        flash(_("Compte introuvable."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    new_username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    role         = request.form.get("role", acc.role)
    password     = request.form.get("password", "").strip()
    if role not in ("admin", "superadmin"):
        role = acc.role
    if acc.role == "superadmin" and role != "superadmin":
        remaining = AdminAccount.query.filter_by(role="superadmin", is_active=True).count()
        if remaining <= 1:
            flash(_("Impossible : il doit rester au moins un superadmin actif."), "error")
            return redirect(url_for("admin.settings", tab="accounts"))
    if new_username and new_username != acc.username:
        if AdminAccount.query.filter_by(username=new_username).first():
            flash(_("Cet identifiant est déjà utilisé."), "error")
            return redirect(url_for("admin.settings", tab="accounts"))
        acc.username = new_username
    acc.display_name = display_name
    acc.role = role
    if password:
        acc.set_password(password)
    db.session.commit()
    flash(_("Compte mis à jour."), "success")
    return redirect(url_for("admin.settings", tab="accounts"))


@admin_bp.route("/accounts/<int:account_id>/toggle", methods=["POST"])
@_admin_required
def account_toggle(account_id):
    if not current_user.is_superadmin:
        return jsonify({"ok": False, "error": "Accès refusé"}), 403
    acc = db.session.get(AdminAccount, account_id)
    if not acc:
        return jsonify({"ok": False, "error": "Compte introuvable"}), 404
    if acc.is_active and acc.role == "superadmin":
        remaining = AdminAccount.query.filter_by(role="superadmin", is_active=True).count()
        if remaining <= 1:
            return jsonify({"ok": False, "error": "Dernier superadmin actif — impossible de désactiver"}), 400
    if str(current_user.get_id()) == acc.get_id():
        return jsonify({"ok": False, "error": "Impossible de vous désactiver vous-même"}), 400
    acc.is_active = not acc.is_active
    db.session.commit()
    return jsonify({"ok": True, "active": acc.is_active})


@admin_bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
@_admin_required
def account_delete(account_id):
    if not current_user.is_superadmin:
        flash(_("Accès refusé."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    acc = db.session.get(AdminAccount, account_id)
    if not acc:
        flash(_("Compte introuvable."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    if str(current_user.get_id()) == acc.get_id():
        flash(_("Impossible de supprimer votre propre compte."), "error")
        return redirect(url_for("admin.settings", tab="accounts"))
    if acc.role == "superadmin":
        remaining = AdminAccount.query.filter_by(role="superadmin").count()
        if remaining <= 1:
            flash(_("Impossible : il doit rester au moins un superadmin."), "error")
            return redirect(url_for("admin.settings", tab="accounts"))
    db.session.delete(acc)
    db.session.commit()
    flash(_("Compte supprimé."), "success")
    return redirect(url_for("admin.settings", tab="accounts"))
