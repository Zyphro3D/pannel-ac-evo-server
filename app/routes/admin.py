import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

_env_write_lock = threading.Lock()  # protects concurrent os.environ writes in settings POST

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, jsonify, session
from flask_babel import _, lazy_gettext as _l
from flask_login import current_user


from app.models import AdminAccount, Driver, Event, SessionResult, Server, CarMeta, TrackMeta
from app.services.database import db
from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name, get_running_server_info,
    load_config_by_name, deployed_configs, delete_server_runtime_dir,
    ConfigJsonError, default_config,
)
from app.services.process_manager import get_status, get_server_logs
from app.services.results_parser import parse_result_file
from app.services import mailer, discord_notifier
from app.utils import admin_required as _admin_required, superadmin_required as _superadmin_required, superadmin_required_json as _superadmin_required_json

admin_bp = Blueprint("admin", __name__)

from app.services.server_config import CAR_PROP_MAPS as _PROP_MAPS, CAR_CATEGORY_ORDER as _CATEGORY_ORDER





@admin_bp.route("/administration")
@_admin_required
@_superadmin_required
def administration():
    cfg = mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
                           pilots_webhook_url=os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", ""))


@admin_bp.route("/administration/test-email", methods=["POST"])
@_admin_required
@_superadmin_required
def test_email():
    cfg      = mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    to       = request.form.get("to", "").strip() or (cfg.get("admin") or [None])[0]
    result_email = mailer.send_test(to) if to else {"ok": False, "error": "Aucune adresse destinataire"}
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
                           pilots_webhook_url=os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", ""),
                           result_email=result_email)


@admin_bp.route("/administration/test-webhook", methods=["POST"])
@_admin_required
@_superadmin_required
def test_webhook():
    cfg      = mailer._cfg
    safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
    channel  = request.form.get("channel", "server")
    url      = (os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", "")
                if channel == "pilots"
                else os.environ.get("DISCORD_WEBHOOK_URL", ""))
    result   = discord_notifier.test_webhook(url)
    return render_template("administration.html",
                           mail_cfg=safe_cfg,
                           webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
                           pilots_webhook_url=os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", ""),
                           result_webhook=result,
                           result_webhook_channel=channel)


@admin_bp.route("/server")
@_admin_required
def server():
    sid           = session.get("current_server_id", 1)
    configs       = list_configs()
    active_config = get_active_config_name()
    server_view   = request.args.get("view", "status")
    if not configs:
        flash(_("Aucun fichier de configuration trouvé dans CONFIGS_DIR. Créez-en un via le bouton ci-dessous."), "warning")
        return render_template("server.html", config=None, cars=[], events_practice=[], events_race=[],
                               status=get_status(sid), configs=[], active_config="",
                               car_categories=[], pi_min=0.0, pi_max=999.0,
                               server_view=server_view, config_summaries=[],
                               server_events=[], current_track={})
    try:
        config = load_config()
    except ConfigJsonError as e:
        flash(
            _("Fichier de configuration invalide (%(name)s) : erreur JSON ligne %(line)s colonne %(col)s. Corrigez et sauvegardez depuis l'onglet Configuration.",
              name=e.filename, line=e.line, col=e.col),
            "error",
        )
        config = default_config()
    cars            = load_cars()
    events_practice = load_events("practice")
    events_race     = load_events("race")
    status          = get_status(sid)

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

    def _track_meta(server_config: dict) -> dict:
        event_section = server_config.get("Event", {}) if server_config else {}
        raw = event_section.get("SelectedTrackValue", "") or ""
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

    running_status = status  # reuse the get_status() result from above — avoid double call
    running_config = running_status.get("config", "") if running_status.get("running") else ""

    config_dirty = False
    if running_status.get("running") and running_config:
        try:
            cfg_path   = Path(current_app.config["CONFIGS_DIR"]) / running_config
            started_at = running_status.get("started_at") or 0
            if cfg_path.exists() and cfg_path.stat().st_mtime > started_at:
                config_dirty = True
        except Exception:
            pass

    def _config_summary(name: str) -> dict:
        server_config  = load_config_by_name(name) or {}
        server_section = server_config.get("Server", {})
        event_section  = server_config.get("Event", {})
        sessions       = server_config.get("Sessions", {})
        selected_cars  = [c for c in event_section.get("Cars", []) if c.get("IsSelected") or c.get("is_selected")]
        track_meta     = _track_meta(server_config)
        return {
            "name": name,
            "active": name == active_config,
            "running": name == running_config,
            "server_name": server_section.get("ServerName", name),
            "max_players": server_section.get("MaxPlayers", "—"),
            "mode": mode_labels.get(event_section.get("SelectedSessionTypeValue"), event_section.get("SelectedSessionTypeValue", "—")),
            "weather": weather_labels.get(event_section.get("SelectedWeatherTypeValue"), "—"),
            "behavior": behavior_labels.get(event_section.get("SelectedWeatherBehaviorValue"), "—"),
            "track": track_meta,
            "car_count": len(selected_cars),
            "practice_minutes": int(sessions.get("PracticeSession", {}).get("Length", 0) or 0) // 60,
            "race_minutes": int(sessions.get("RaceSession", {}).get("Length", 0) or 0) // 60,
        }

    def _recent_server_activity() -> list[dict]:
        keywords = (
            "connect", "disconnect", "joined", "left", "driver", "player",
            "session", "lap", "result", "start", "stop", "restart",
            "connexion", "déconnexion", "deconnexion", "pilote", "joueur",
        )
        items: list[dict] = []
        for raw in reversed((get_server_logs(180, server_id=sid) or "").splitlines()):
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
        server_info=get_running_server_info(sid),
        config_summaries=config_summaries,
        server_events=Event.query.order_by(Event.date.asc()).all(),
        current_track=current_track,
        current_weather=weather_labels.get(current_event.get("SelectedWeatherTypeValue"), "—"),
        current_weather_behavior=behavior_labels.get(current_event.get("SelectedWeatherBehaviorValue"), "—"),
        current_mode=mode_labels.get(current_event.get("SelectedSessionTypeValue"), "—"),
        recent_server_activity=_recent_server_activity(),
        config_dirty=config_dirty,
        deployed_configs=deployed_configs(sid),
    )


# ── Helpers .env ──────────────────────────────────────────────────────────────

_ENV_SECTIONS = [
    ("panel", "Panel", [
        "PANEL_TITLE", "PANEL_BANNER_IMG", "PANEL_LOGO_IMG", "PANEL_URL",
        "PANEL_TIMEZONE", "DEFAULT_LOCALE",
        "SECRET_KEY", "SESSION_COOKIE_SECURE", "RESULTS_INGEST_SECRET",
    ]),
    ("accounts", _l("Comptes"), []),  # Géré via AdminAccount en base de données
    ("server", _l("Serveur"), [
        "SERVER_MAX_PLAYERS",
        "SERVER_DRIVER_PASSWORD", "SERVER_ADMIN_PASSWORD",
        "SERVER_ENTRY_LIST_PATH", "SERVER_RESULTS_PATH",
        "ACESERVER_TCP_HOST", "ACESERVER_TCP_PORT",
        "ACESERVER_DIR", "CONFIGS_DIR",
        "STEAM_USERNAME",
    ]),
    ("notifications", _l("Notifications"), [
        "ACE_BOT_STEAM_ID", "ACE_BOT_IS_ADMIN",
        "ACE_BOT_MSG_WELCOME", "ACE_BOT_MSG_DISCORD", "ACE_BOT_MSG_SITE",
        "DISCORD_WEBHOOK_URL", "DISCORD_PILOTS_WEBHOOK_URL", "DISCORD_RACE_WEBHOOK_URL",
        "DISCORD_INVITE_URL",
        "DISCORD_MENTION_MAIN", "DISCORD_MENTION_PILOTS", "DISCORD_MENTION_RACE",
        "DISCORD_MSG_SERVER_START", "DISCORD_MSG_SERVER_STOP", "DISCORD_MSG_SERVER_CRASH",
        "DISCORD_MSG_PLAYER_JOIN", "DISCORD_MSG_PLAYER_DISCONNECT", "DISCORD_MSG_VEHICLE_CHANGE",
        "DISCORD_MSG_BEST_LAP", "DISCORD_MSG_ADMIN_ACTION",
        "MAIL_SERVER", "MAIL_PORT", "MAIL_USE_TLS", "MAIL_USERNAME",
        "MAIL_PASSWORD", "MAIL_FROM", "MAIL_ADMIN",
    ]),
]
_ENV_DESCS = {
    "PANEL_TITLE":      _l("Nom affiché dans la sidebar"),
    "PANEL_BANNER_IMG": _l("Nom de fichier dans media/banner/ (ex: banner.jpg)"),
    "PANEL_LOGO_IMG":   _l("Logo sur la bannière (ex: logo.png)"),
    "PANEL_URL":        _l("URL publique du panel (liens dans les emails)"),
    "PANEL_TIMEZONE":   _l("Fuseau horaire (ex: Europe/Paris)"),
    "SECRET_KEY":       _l("Clé de session Flask — générer avec python -c \"import secrets; print(secrets.token_hex(32))\""),
    "SESSION_COOKIE_SECURE": _l("true si HTTPS, false si HTTP local"),
    "RESULTS_INGEST_SECRET": _l("Secret HMAC du webhook résultats (/api/results/ingest)"),
    "ACESERVER_HTTP_PORT": _l("Port HTTP de l'API du serveur (défaut 8081)"),
    "ACESERVER_TCP_HOST":  _l("Hôte TCP ACE EVO (défaut 127.0.0.1)"),
    "ACESERVER_TCP_PORT":  _l("Port TCP ACE EVO (défaut 9700)"),
    "ACESERVER_DIR":    _l("Dossier d'installation ACE EVO"),
    "CONFIGS_DIR":      _l("Dossier des fichiers de configuration JSON"),
    "SERVER_NAME":            _l("Nom du serveur affiché dans la liste des serveurs ACE EVO (commun à toutes les configs)"),
    "SERVER_MAX_PLAYERS":     _l("Nombre maximum de joueurs simultanés (1–128, défaut 8)"),
    "SERVER_TCP_PORT":        _l("Port TCP du serveur de jeu (défaut 9700) — doit correspondre aux règles firewall"),
    "SERVER_UDP_PORT":        _l("Port UDP du serveur de jeu (défaut 9700) — généralement identique au port TCP"),
    "SERVER_DRIVER_PASSWORD": _l("Mot de passe d'accès au serveur pour les pilotes. Laisser vide = accès libre"),
    "SERVER_ADMIN_PASSWORD":  _l("Mot de passe admin serveur (commandes /kick, /next, etc.) — utilisé aussi par le bot TCP"),
    "SERVER_ENTRY_LIST_PATH": _l("Chemin vers le fichier entry_list.ini (laisser vide si non utilisé)"),
    "SERVER_RESULTS_PATH":    _l("Dossier de sortie des résultats de session (laisser vide = dossier par défaut)"),
    "ACE_BOT_STEAM_ID":       _l("Steam ID 64-bit du compte bot — le bot se connecte au serveur avec ce compte. Laisser vide pour désactiver le bot."),
    "ACE_BOT_CAR_MODEL":      _l("Voiture utilisée par le bot pour rejoindre la session."),
    "ACE_BOT_IS_ADMIN":       _l("Activer les droits admin pour le bot (true/false). Le mot de passe est lu automatiquement depuis la config serveur active."),
    "ACE_BOT_MSG_WELCOME":    _l("Message de bienvenue envoyé à chaque connexion. Variable : {name}. Laisser vide pour désactiver."),
    "ACE_BOT_MSG_DISCORD":    _l("Message Discord envoyé si DISCORD_INVITE_URL est défini. Variables : {name}, {discord_url}. Laisser vide pour désactiver."),
    "ACE_BOT_MSG_SITE":       _l("Message site envoyé si PANEL_URL est défini. Variables : {name}, {site_url}. Laisser vide pour désactiver."),
    "STEAM_USERNAME":    _l("Pré-remplit le formulaire de mise à jour. Le mot de passe est saisi au moment de la mise à jour, jamais stocké."),
    "DISCORD_WEBHOOK_URL":        _l("Webhook principal — démarrage, arrêt, crash du serveur"),
    "DISCORD_PILOTS_WEBHOOK_URL": _l("Webhook pilotes — connexions, déconnexions, changements de véhicule"),
    "DISCORD_RACE_WEBHOOK_URL":   _l("Webhook course — meilleur tour, actions admin (kick, pénalités…)"),
    "DISCORD_INVITE_URL":         _l("Lien d'invitation Discord affiché sur le panel"),
    "DISCORD_MENTION_MAIN":       _l("Mention envoyée avec les événements serveur (ex: @here ou <@&123456789>). Laisser vide pour désactiver."),
    "DISCORD_MENTION_PILOTS":     _l("Mention envoyée avec les connexions joueurs. Laisser vide pour désactiver."),
    "DISCORD_MENTION_RACE":       _l("Mention envoyée avec les événements course. Laisser vide pour désactiver."),
    "DISCORD_MSG_SERVER_START":   _l("Titre embed — Serveur démarré. Variables : {config}, {mode}, {circuit}"),
    "DISCORD_MSG_SERVER_STOP":    _l("Titre embed — Serveur arrêté. Variables : {config}"),
    "DISCORD_MSG_SERVER_CRASH":   _l("Titre embed — Crash détecté. Variables : {config}"),
    "DISCORD_MSG_PLAYER_JOIN":    _l("Titre embed — Connexion joueur. Variables : {name}, {num}, {car}, {steam_id}"),
    "DISCORD_MSG_PLAYER_DISCONNECT": _l("Titre embed — Déconnexion joueur. Variables : {name}, {duration}, {steam_id}"),
    "DISCORD_MSG_VEHICLE_CHANGE": _l("Titre embed — Changement de véhicule. Variables : {name}, {num}, {old_car}, {new_car}"),
    "DISCORD_MSG_BEST_LAP":       _l("Titre embed — Meilleur tour serveur. Variables : {name}, {lap}, {car}"),
    "DISCORD_MSG_ADMIN_ACTION":   _l("Titre embed — Action admin. Variables : {action}, {target}, {admin}, {detail}"),
    "MAIL_SERVER":      _l("Serveur SMTP (laisser vide pour désactiver les emails)"),
    "MAIL_PORT":        _l("Port SMTP (ex: 587 ou 465)"),
    "MAIL_USE_TLS":     _l("TLS : true ou false"),
    "MAIL_USERNAME":    _l("Identifiant SMTP"),
    "MAIL_PASSWORD":    _l("Mot de passe SMTP"),
    "MAIL_FROM":        _l("Adresse expéditeur"),
    "MAIL_ADMIN":       _l("Adresse(s) admin pour les notifications (séparées par virgule)"),
    "DEFAULT_LOCALE":   _l("Langue par défaut : fr, en, es, de, it"),
}
_SENSITIVE = {"SECRET_KEY", "MAIL_PASSWORD", "MAIL_USERNAME",
              "DISCORD_WEBHOOK_URL", "DISCORD_PILOTS_WEBHOOK_URL", "DISCORD_RACE_WEBHOOK_URL",
              "DISCORD_MENTION_MAIN", "DISCORD_MENTION_PILOTS", "DISCORD_MENTION_RACE",
              "RESULTS_INGEST_SECRET",
              "SERVER_DRIVER_PASSWORD", "SERVER_ADMIN_PASSWORD"}
_SKIP_IF_EMPTY = {"MAIL_PASSWORD"}
_CHECKBOXES = {"ACE_BOT_IS_ADMIN"}


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
@_superadmin_required
def settings():
    env_values, env_path = _read_env_file()
    saved = False
    tab = request.args.get("tab", "panel")
    sid = session.get("current_server_id", 1)
    current_srv = db.session.get(Server, sid) or Server.query.order_by(Server.id).first()

    if request.method == "POST":
        tab = request.form.get("_tab", "panel")

        # ── Sauvegarde des champs par-serveur (DB) + env vars du même formulaire ─
        if request.form.get("_server_form") == "db" and current_srv:
            _name = request.form.get("srv_name", "").strip()
            _tcp  = request.form.get("srv_tcp_port", "").strip()
            _http = request.form.get("srv_http_port", "").strip()
            if _name:
                current_srv.name = _name
            if _tcp and _tcp.isdigit():
                current_srv.tcp_port = int(_tcp)
                current_srv.udp_port = int(_tcp)  # UDP = TCP
            if _http and _http.isdigit():
                current_srv.http_port = int(_http)
            current_srv.discord_webhook_main   = request.form.get("srv_discord_main",   "").strip()
            current_srv.discord_webhook_pilots = request.form.get("srv_discord_pilots", "").strip()
            current_srv.discord_webhook_race   = request.form.get("srv_discord_race",   "").strip()
            db.session.commit()
            # Sauvegarde aussi les champs env vars du même formulaire
            _env_keys_in_server_form = [
                "SERVER_MAX_PLAYERS", "SERVER_DRIVER_PASSWORD", "SERVER_ADMIN_PASSWORD",
                "SERVER_ENTRY_LIST_PATH", "SERVER_RESULTS_PATH",
            ]
            new_vals = {}
            for k in _env_keys_in_server_form:
                val = request.form.get(k)
                if val is not None:
                    stripped = val.strip()
                    if stripped == "" and k in _SKIP_IF_EMPTY:
                        pass
                    else:
                        new_vals[k] = stripped
            if new_vals:
                with _env_write_lock:
                    _write_env_file(new_vals)
                    for _k, _v in new_vals.items():
                        os.environ[_k] = _v
                        current_app.config[_k] = _v
            flash(_("Paramètres du serveur sauvegardés."), "success")
            return redirect(url_for("admin.settings", tab=tab))

        # ── Sauvegarde des variables d'environnement globales ─────────────────
        new_vals = {}
        for _sec_id, _sec_label, keys in _ENV_SECTIONS:
            for k in keys:
                if k in _CHECKBOXES:
                    new_vals[k] = "true" if "true" in request.form.getlist(k) else "false"
                else:
                    val = request.form.get(k)
                    if val is not None:
                        stripped = val.strip()
                        if stripped == "" and k in _SKIP_IF_EMPTY:
                            pass  # mot de passe laissé vide → conserver la valeur actuelle
                        else:
                            new_vals[k] = stripped
        with _env_write_lock:
            _write_env_file(new_vals)
            env_values.update(new_vals)
            # Applique immédiatement sans redémarrage
            for _k, _v in new_vals.items():
                os.environ[_k] = _v
                current_app.config[_k] = _v
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
    try:
        bot_cars = sorted(load_cars(), key=lambda c: c["display_name"])
    except Exception:
        bot_cars = []
    try:
        from app.services.server_config import load_config
        bot_admin_password_set = bool(load_config().get("Server", {}).get("AdminPassword", ""))
    except Exception:
        bot_admin_password_set = False

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
                           bot_cars=bot_cars,
                           bot_admin_password_set=bot_admin_password_set,
                           current_srv=current_srv,
                           server_status=get_status(sid))


def _validate_image_upload(allowed_exts=None):
    """Valide un upload image : Content-Length, extension, signature magic bytes.
    Retourne (file_object, ext) si valide, ou (None, response_json) si invalide.
    """
    if allowed_exts is None:
        allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    if request.content_length and request.content_length > 5 * 1024 * 1024:
        return None, (jsonify({"ok": False, "error": _("Fichier trop volumineux (max 5 Mo)")}), 413)
    f = request.files.get("file")
    if not f or not f.filename:
        return None, (jsonify({"ok": False, "error": _("Aucun fichier fourni")}), 400)
    ext = Path(f.filename).suffix.lower()
    if ext not in allowed_exts:
        return None, (jsonify({"ok": False, "error": _("Type non autorisé")}), 400)
    sigs = {
        ".jpg":  [b"\xff\xd8\xff"],
        ".jpeg": [b"\xff\xd8\xff"],
        ".png":  [b"\x89PNG\r\n\x1a\n"],
        ".gif":  [b"GIF87a", b"GIF89a"],
        ".webp": [b"RIFF"],
    }
    header = f.stream.read(16)
    f.stream.seek(0)
    if not any(header.startswith(s) for s in sigs.get(ext, [])):
        return None, (jsonify({"ok": False, "error": _("Signature de fichier invalide")}), 400)
    return f, ext


@admin_bp.route("/settings/upload-media", methods=["POST"])
@_admin_required
@_superadmin_required_json
def upload_media():
    f, err = _validate_image_upload(allowed_exts={".jpg", ".jpeg", ".png", ".gif", ".webp"})
    if f is None:
        return err
    ext = Path(f.filename).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(f.filename).stem)[:40].strip("_")
    safe_name = f"{uuid.uuid4().hex}_{safe_stem or 'banner'}{ext}"
    dest = Path(__file__).parent.parent.parent / "media" / "banner" / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    return jsonify({"ok": True, "filename": safe_name})


# ── Gestion des comptes administrateurs ──────────────────────────────────────

@admin_bp.route("/accounts/create", methods=["POST"])
@_admin_required
@_superadmin_required_json
def account_create():
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
@_superadmin_required_json
def account_edit(account_id):
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
@_superadmin_required_json
def account_toggle(account_id):
    acc = db.session.get(AdminAccount, account_id)
    if not acc:
        return jsonify({"ok": False, "error": _("Compte introuvable")}), 404
    if acc.is_active and acc.role == "superadmin":
        remaining = AdminAccount.query.filter_by(role="superadmin", is_active=True).count()
        if remaining <= 1:
            return jsonify({"ok": False, "error": _("Dernier superadmin actif — impossible de désactiver")}), 400
    if str(current_user.get_id()) == acc.get_id():
        return jsonify({"ok": False, "error": _("Impossible de vous désactiver vous-même")}), 400
    acc.is_active = not acc.is_active
    db.session.commit()
    return jsonify({"ok": True, "active": acc.is_active})


@admin_bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
@_admin_required
@_superadmin_required
def account_delete(account_id):
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


# ── Sélection du serveur actif ────────────────────────────────────────────────

@admin_bp.route("/server/select/<int:server_id>", methods=["POST"])
@_admin_required
def select_server(server_id):
    srv = db.session.get(Server, server_id)
    if srv and srv.is_enabled:
        session["current_server_id"] = server_id
    return redirect(url_for("admin.server"))


# ── Gestion des serveurs (superadmin) ─────────────────────────────────────────

@admin_bp.route("/servers")
@_admin_required
@_superadmin_required
def servers_list():
    from app.services.process_manager import get_status
    servers = Server.query.order_by(Server.sort_order, Server.id).all()
    statuses = {}
    for srv in servers:
        try:
            statuses[srv.id] = get_status(srv.id)
        except Exception:
            statuses[srv.id] = {"running": False}
    return render_template("servers.html", servers=servers, statuses=statuses)


@admin_bp.route("/servers/create", methods=["POST"])
@_admin_required
@_superadmin_required
def server_create():
    name = request.form.get("name", "").strip()
    if not name:
        flash(_("Le nom est requis."), "error")
        return redirect(url_for("admin.servers_list"))

    # Ports — parse + validation de plage côté serveur
    try:
        tcp_port  = int(request.form.get("tcp_port")  or 9701)
        http_port = int(request.form.get("http_port") or 8082)
    except (ValueError, TypeError):
        flash(_("Port invalide (1024–65535)."), "error")
        return redirect(url_for("admin.servers_list"))
    udp_port = tcp_port  # TCP et UDP utilisent toujours le même numéro
    for port in (tcp_port, http_port):
        if not (1024 <= port <= 65535):
            flash(_("Port invalide (1024–65535)."), "error")
            return redirect(url_for("admin.servers_list"))

    # Slug unique : base + suffixe numérique si collision
    base_slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-") or "server"
    slug, counter = base_slug, 1
    while Server.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # container_name : toujours auto-généré depuis le slug, jamais fourni par l'utilisateur
    container_name = f"ace-server-{slug}"
    # suffixe numérique si collision (très rare)
    cnt_base, cnt_i = container_name, 1
    while Server.query.filter_by(container_name=container_name).first():
        container_name = f"{cnt_base}-{cnt_i}"
        cnt_i += 1

    if Server.query.filter_by(container_name=container_name).first():
        flash(_("Un serveur avec ce nom de container existe déjà."), "error")
        return redirect(url_for("admin.servers_list"))

    # Vérifie si le container Docker existe déjà
    from app.services.server_docker import container_exists, create_server_container
    if container_exists(container_name):
        flash(_("Un container Docker nommé '%(name)s' existe déjà.", name=container_name), "error")
        return redirect(url_for("admin.servers_list"))

    # Crée l'entrée en DB
    srv = Server(
        name           = name,
        slug           = slug,
        tcp_port       = tcp_port,
        udp_port       = udp_port,
        http_port      = http_port,
        container_name = container_name,
        active_config  = "default.json",
        is_enabled     = True,
        sort_order     = Server.query.count(),
    )
    db.session.add(srv)
    db.session.flush()  # obtient srv.id avant le commit

    # Crée le container Docker
    result = create_server_container(srv)
    if not result["ok"]:
        db.session.rollback()
        flash(_("Erreur lors de la création du container : %(err)s", err=result["error"]), "error")
        return redirect(url_for("admin.servers_list"))

    db.session.commit()

    from app.services.server_docker import sync_compose_override
    sync_compose_override()

    # Démarre le watchdog pour ce nouveau serveur
    from flask import current_app as _ca
    from app.services.process_manager import init_watchdog
    init_watchdog(
        _ca.config["ACESERVER_EXE_PATH"],
        server_id      = srv.id,
        container_name = srv.container_name,
        http_host      = srv.container_name,
    )

    # Démarre le bot TCP pour ce nouveau serveur
    from app.services import ace_tcp_client
    ace_tcp_client.start_for_server(srv, _ca.config)

    flash(_("Serveur '%(name)s' créé avec succès.", name=name), "success")
    return redirect(url_for("admin.servers_list"))


@admin_bp.route("/servers/<int:server_id>/toggle", methods=["POST"])
@_admin_required
@_superadmin_required
def server_toggle(server_id):
    if server_id == 1:
        flash(_("Le serveur principal ne peut pas être désactivé."), "error")
        return redirect(url_for("admin.servers_list"))
    srv = db.session.get(Server, server_id)
    if not srv:
        flash(_("Serveur introuvable."), "error")
        return redirect(url_for("admin.servers_list"))
    srv.is_enabled = not srv.is_enabled
    db.session.commit()
    if srv.is_enabled:
        flash(_("Serveur '%(name)s' activé.", name=srv.name), "success")
    else:
        flash(_("Serveur '%(name)s' désactivé.", name=srv.name), "success")
    return redirect(url_for("admin.servers_list"))


@admin_bp.route("/servers/<int:server_id>/delete", methods=["POST"])
@_admin_required
@_superadmin_required
def server_delete(server_id):
    if server_id == 1:
        flash(_("Le serveur principal ne peut pas être supprimé."), "error")
        return redirect(url_for("admin.servers_list"))
    srv = db.session.get(Server, server_id)
    if not srv:
        flash(_("Serveur introuvable."), "error")
        return redirect(url_for("admin.servers_list"))

    # Arrête et supprime le container Docker
    from app.services.server_docker import remove_server_container, sync_compose_override
    remove_server_container(srv.container_name)

    # Supprime le dossier de configs déployées pour ce serveur
    delete_server_runtime_dir(server_id)

    db.session.delete(srv)
    db.session.commit()
    sync_compose_override()
    flash(_("Serveur '%(name)s' supprimé.", name=srv.name), "success")
    return redirect(url_for("admin.servers_list"))


# ── Véhicules ─────────────────────────────────────────────────────────────────

_CAR_CATEGORIES = ["Road", "Race", "Track"]

@admin_bp.route("/vehicles")
@_admin_required
def vehicles():
    cat_filter = request.args.get("cat", "")
    search     = request.args.get("q", "").strip().lower()
    q = CarMeta.query.order_by(CarMeta.category, CarMeta.display_name)
    if cat_filter in _CAR_CATEGORIES:
        q = q.filter_by(category=cat_filter)
    cars = q.all()
    if search:
        cars = [c for c in cars if search in c.display_name.lower() or search in c.slug.lower()]
    counts = {cat: CarMeta.query.filter_by(category=cat).count() for cat in _CAR_CATEGORIES}
    return render_template("vehicles.html", cars=cars, cat_filter=cat_filter,
                           search=search, counts=counts, categories=_CAR_CATEGORIES)


@admin_bp.route("/vehicles/<slug>/upload-image", methods=["POST"])
@_admin_required
@_superadmin_required_json
def vehicle_upload_image(slug):
    car = CarMeta.query.filter_by(slug=slug).first_or_404()
    f, err = _validate_image_upload()
    if f is None:
        return err
    ext = Path(f.filename).suffix.lower()
    dest = Path(__file__).parent.parent.parent / "media" / "cars" / f"{slug}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    car.image_path = f"cars/{slug}{ext}"
    db.session.commit()
    return jsonify({"ok": True, "image_path": car.image_path})


# ── Tracks ────────────────────────────────────────────────────────────────────

@admin_bp.route("/tracks")
@_admin_required
def tracks():
    all_tracks = TrackMeta.query.order_by(TrackMeta.track_name, TrackMeta.layout).all()
    return render_template("tracks.html", tracks=all_tracks)


@admin_bp.route("/tracks/<int:track_id>/upload-image", methods=["POST"])
@_admin_required
@_superadmin_required_json
def track_upload_image(track_id):
    track = TrackMeta.query.get_or_404(track_id)
    f, err = _validate_image_upload()
    if f is None:
        return err
    ext = Path(f.filename).suffix.lower()
    safe = re.sub(r"[^a-z0-9_-]", "_", track.track_name.lower())
    dest = Path(__file__).parent.parent.parent / "media" / "circuits" / f"{safe}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(dest))
    track.image_path = f"circuits/{safe}{ext}"
    db.session.commit()
    return jsonify({"ok": True, "image_path": track.image_path})


# ── Mods ──────────────────────────────────────────────────────────────────────

@admin_bp.route("/mods")
@_admin_required
def mods():
    return render_template("mods.html")
