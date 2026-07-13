import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path

_env_write_lock = threading.Lock()  # protects concurrent os.environ writes in settings POST

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, jsonify, session
from flask_babel import _, lazy_gettext as _l
from flask_login import current_user


from app.models import AdminAccount, Driver, Event, Server, CarMeta, TrackMeta
from app.services.database import db
from app.services.server_config import (
    load_config, load_cars, load_events,
    list_configs, get_active_config_name, get_running_server_info,
    load_config_by_name, deployed_configs, delete_server_runtime_dir,
    ConfigJsonError, default_config,
)
from app.services.process_manager import get_status, get_server_logs
from app.services import mailer, discord_notifier
from app.utils import (
    admin_required as _admin_required,
    superadmin_required as _superadmin_required,
    superadmin_required_json as _superadmin_required_json,
    is_htmx,
    htmx_redirect,
    htmx_toast as _toast,
    flash_or_toast,
)

admin_bp = Blueprint("admin", __name__)

from app.services.server_config import CAR_PROP_MAPS as _PROP_MAPS, CAR_CATEGORY_ORDER as _CATEGORY_ORDER

_log = logging.getLogger(__name__)


# ── Migrations DB (appelées depuis create_app()) ───────────────────────────────

def _migrate_indexes(db):
    """Crée les index composites manquants sur les DB existantes."""
    import sqlalchemy as sa
    indexes = [
        ("ix_event_status_email_sent",       "CREATE INDEX IF NOT EXISTS ix_event_status_email_sent ON event (status, email_sent)"),
        ("ix_event_status_discord_notified",  "CREATE INDEX IF NOT EXISTS ix_event_status_discord_notified ON event (status, discord_notified)"),
        ("ix_car_meta_display_name",          "CREATE INDEX IF NOT EXISTS ix_car_meta_display_name ON car_meta (display_name)"),
        ("ix_session_result_run_id",           "CREATE INDEX IF NOT EXISTS ix_session_result_run_id ON session_result (run_id)"),
        ("ix_event_status_date",               "CREATE INDEX IF NOT EXISTS ix_event_status_date ON event (status, date)"),
        ("ix_session_result_raw_json_hash",    "CREATE INDEX IF NOT EXISTS ix_session_result_raw_json_hash ON session_result (raw_json_hash)"),
        ("ix_event_registration_driver_id",    "CREATE INDEX IF NOT EXISTS ix_event_registration_driver_id ON event_registration (driver_id)"),
    ]
    with db.engine.connect() as conn:
        for name, sql in indexes:
            try:
                conn.execute(sa.text(sql))
                conn.commit()
            except Exception as e:
                _log.warning("Index %s ignoré : %s", name, e)


def _migrate_db(db):
    """Applique les ALTER TABLE manquants sur SQLite sans casser les données existantes."""
    import sqlalchemy as sa
    engine = db.engine
    allowed_tables = {"event", "driver", "session_result"}
    allowed_columns = {
        "practice_minutes", "qualifying_minutes", "warmup_minutes", "race_minutes",
        "allowed_cars", "reset_token", "reset_token_expires", "is_public",
        "auto_launch", "launched", "discord_notified", "cars_config",
        "config_name", "run_id", "server_id", "raw_json_hash",
    }
    cols_to_add = [
        ("event",  "practice_minutes",    "INTEGER DEFAULT 60"),
        ("event",  "qualifying_minutes",  "INTEGER DEFAULT 30"),
        ("event",  "warmup_minutes",      "INTEGER DEFAULT 10"),
        ("event",  "race_minutes",        "INTEGER DEFAULT 60"),
        ("event",  "allowed_cars",        "TEXT    DEFAULT '[]'"),
        ("driver", "reset_token",         "TEXT"),
        ("driver", "reset_token_expires", "DATETIME"),
        ("event",  "is_public",           "INTEGER DEFAULT 0"),
        ("event",  "auto_launch",          "INTEGER DEFAULT 0"),
        ("event",  "launched",            "INTEGER DEFAULT 0"),
        ("event",  "discord_notified",    "INTEGER DEFAULT 0"),
        ("event",  "cars_config",         "TEXT    DEFAULT '{}'"),
        ("session_result", "config_name",    "TEXT"),
        ("session_result", "run_id",         "TEXT"),
        ("session_result", "server_id",      "INTEGER"),
        ("session_result", "raw_json_hash",  "VARCHAR(64)"),
    ]
    with engine.connect() as conn:
        for table, col, col_def in cols_to_add:
            try:
                if table not in allowed_tables or col not in allowed_columns:
                    raise ValueError(f"Migration non whitelistée: {table}.{col}")
                existing = [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))]
                if col not in existing:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                    conn.commit()
            except Exception as e:
                _log.warning("Migration %s.%s ignorée : %s", table, col, e)


def _migrate_result_hash(db):
    """Backfille raw_json_hash sur les SessionResult existants qui n'en ont pas."""
    import hashlib
    from app.models import SessionResult
    try:
        to_fill = SessionResult.query.filter(SessionResult.raw_json_hash.is_(None)).all()
        if to_fill:
            for r in to_fill:
                r.raw_json_hash = hashlib.sha256(r.raw_json.encode()).hexdigest()
            db.session.commit()
            _log.info("Migration: raw_json_hash backfillé pour %d résultats", len(to_fill))
    except Exception as e:
        db.session.rollback()
        _log.warning("_migrate_result_hash ignoré : %s", e)


def _migrate_server_discord(db):
    """Ajoute les colonnes discord_webhook_* à la table server si absentes."""
    import sqlalchemy as sa
    cols = [
        ("discord_webhook_main",   "TEXT DEFAULT ''"),
        ("discord_webhook_pilots", "TEXT DEFAULT ''"),
        ("discord_webhook_race",   "TEXT DEFAULT ''"),
    ]
    with db.engine.connect() as conn:
        existing = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(server)"))]
        for col, col_def in cols:
            if col not in existing:
                try:
                    conn.execute(sa.text(f"ALTER TABLE server ADD COLUMN {col} {col_def}"))
                    conn.commit()
                except Exception as e:
                    _log.warning("Migration server.%s ignorée : %s", col, e)


def _migrate_driver_steam_id(db):
    """Ajoute steam_id/steam_id_confirmed_at à la table driver (v1.9.0+)."""
    import sqlalchemy as sa
    cols = [
        ("steam_id",              "VARCHAR(32)"),
        ("steam_id_confirmed_at", "DATETIME"),
    ]
    with db.engine.connect() as conn:
        existing = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(driver)"))]
        for col, col_def in cols:
            if col not in existing:
                try:
                    conn.execute(sa.text(f"ALTER TABLE driver ADD COLUMN {col} {col_def}"))
                    conn.commit()
                except Exception as e:
                    _log.warning("Migration driver.%s ignorée : %s", col, e)
        try:
            conn.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_driver_steam_id_unique "
                "ON driver (steam_id) WHERE steam_id IS NOT NULL"
            ))
            conn.commit()
        except Exception as e:
            _log.warning("Index ix_driver_steam_id_unique ignoré : %s", e)


def _migrate_admin_account_extra(db):
    """Ajoute email/steam_id/steam_id_confirmed_at à admin_account, facultatifs (v1.9.0+)."""
    import sqlalchemy as sa
    cols = [
        ("email",                  "VARCHAR(120)"),
        ("steam_id",               "VARCHAR(32)"),
        ("steam_id_confirmed_at",  "DATETIME"),
    ]
    with db.engine.connect() as conn:
        existing = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(admin_account)"))]
        for col, col_def in cols:
            if col not in existing:
                try:
                    conn.execute(sa.text(f"ALTER TABLE admin_account ADD COLUMN {col} {col_def}"))
                    conn.commit()
                except Exception as e:
                    _log.warning("Migration admin_account.%s ignorée : %s", col, e)
        try:
            conn.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_account_steam_id_unique "
                "ON admin_account (steam_id) WHERE steam_id IS NOT NULL"
            ))
            conn.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_account_email_unique "
                "ON admin_account (email) WHERE email IS NOT NULL"
            ))
            conn.commit()
        except Exception as e:
            _log.warning("Index admin_account (steam_id/email) ignoré : %s", e)


def _migrate_driver_email_confirmation(db):
    """Ajoute email_confirmed_at/email_confirm_token(_expires) à driver (v1.9.0+).

    Confirmation d'email facultative, activable via REQUIRE_EMAIL_CONFIRMATION.
    Les pilotes déjà existants au moment de la migration sont "grandfather" —
    on les marque confirmés immédiatement pour ne jamais les bloquer rétroactivement
    si la fonctionnalité est activée plus tard.
    """
    import sqlalchemy as sa
    cols = [
        ("email_confirmed_at",          "DATETIME"),
        ("email_confirm_token",         "VARCHAR(64)"),
        ("email_confirm_token_expires", "DATETIME"),
    ]
    with db.engine.connect() as conn:
        existing = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(driver)"))]
        added_confirmed_at = False
        for col, col_def in cols:
            if col not in existing:
                try:
                    conn.execute(sa.text(f"ALTER TABLE driver ADD COLUMN {col} {col_def}"))
                    conn.commit()
                    if col == "email_confirmed_at":
                        added_confirmed_at = True
                except Exception as e:
                    _log.warning("Migration driver.%s ignorée : %s", col, e)
        if added_confirmed_at:
            try:
                conn.execute(sa.text(
                    "UPDATE driver SET email_confirmed_at = created_at WHERE email_confirmed_at IS NULL"
                ))
                conn.commit()
            except Exception as e:
                _log.warning("Grandfathering driver.email_confirmed_at ignoré : %s", e)


def _migrate_event_server_id(db):
    """Ajoute la colonne server_id à la table event (v1.8.3+)."""
    import sqlalchemy as sa
    with db.engine.connect() as conn:
        try:
            conn.execute(sa.text("ALTER TABLE event ADD COLUMN server_id INTEGER DEFAULT 1"))
            conn.commit()
            _log.info("Migration event.server_id : colonne ajoutée")
        except Exception:
            pass  # colonne déjà présente


def _migrate_server_http_port(db):
    """Corrige http_port 8080 → 8081 pour les installations créées avant v1.8.1."""
    import sqlalchemy as sa
    with db.engine.connect() as conn:
        try:
            result = conn.execute(sa.text(
                "UPDATE server SET http_port = 8081 WHERE http_port = 8080"
            ))
            conn.commit()
            if result.rowcount:
                _log.info(
                    "Migration http_port : %d serveur(s) mis à jour 8080→8081", result.rowcount
                )
        except Exception as e:
            _log.warning("Migration http_port ignorée : %s", e)


def _migrate_car_meta_props(db):
    """Ajoute property_2_label et property_3_label à car_meta (v1.9.0+)."""
    import sqlalchemy as sa
    with db.engine.connect() as conn:
        for col in ("property_2_label", "property_3_label"):
            try:
                conn.execute(sa.text(f"ALTER TABLE car_meta ADD COLUMN {col} VARCHAR(60) DEFAULT ''"))
                conn.commit()
                _log.info("Migration car_meta.%s : colonne ajoutée", col)
            except Exception:
                pass  # colonne déjà présente



@admin_bp.route("/settings/mail-preview")
@_admin_required
@_superadmin_required
def mail_preview():
    html = mailer.render_preview(request.args.get("type", ""))
    if html is None:
        flash(_("Type d'email inconnu."), "error")
        return redirect(url_for("admin.settings", tab="notifications"))
    return html


@admin_bp.route("/settings/test-email", methods=["POST"])
@_admin_required
@_superadmin_required
def test_email():
    cfg = mailer._cfg
    to  = request.form.get("to", "").strip() or (cfg.get("admin") or [None])[0]
    result_email = mailer.send_test(to) if to else {"ok": False, "error": _("Aucune adresse destinataire")}
    if is_htmx():
        if result_email.get("ok"):
            return _toast("success", _("Email envoyé avec succès"))
        return _toast("error", _("Erreur SMTP") + " : " + str(result_email.get("error", "")))
    if result_email.get("ok"):
        flash(_("Email envoyé avec succès"), "success")
    else:
        flash(_("Erreur SMTP") + " : " + str(result_email.get("error", "")), "error")
    return redirect(url_for("admin.settings", tab="notifications"))


@admin_bp.route("/settings/test-webhook", methods=["POST"])
@_admin_required
@_superadmin_required
def test_webhook():
    channel = request.form.get("channel", "server")
    url     = (os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", "")
               if channel == "pilots"
               else os.environ.get("DISCORD_WEBHOOK_URL", ""))
    result  = discord_notifier.test_webhook(url)
    if is_htmx():
        if result.get("ok"):
            return _toast("success", _("Message de test envoyé sur Discord"))
        return _toast("error", _("Erreur webhook") + " : " + str(result.get("error", "")))
    if result.get("ok"):
        flash(_("Message de test envoyé sur Discord"), "success")
    else:
        flash(_("Erreur webhook") + " : " + str(result.get("error", "")), "error")
    return redirect(url_for("admin.settings", tab="notifications"))


def _track_slug(value: str) -> str:
    value = (value or "").lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value.replace("grand_prix", "gp")


def _get_track_meta(server_config: dict, circuit_files: dict) -> dict:
    event_section = server_config.get("Event", {}) if server_config else {}
    raw    = event_section.get("SelectedTrackValue", "") or ""
    parts  = raw.split("|")
    track  = parts[0] if len(parts) > 0 else "—"
    layout = parts[1] if len(parts) > 1 else ""
    length = parts[3] if len(parts) > 3 else ""
    candidates = [
        _track_slug(f"{track}_{layout}"),
        _track_slug(layout),
        _track_slug(track),
    ]
    image = ""
    for candidate in candidates:
        if candidate in circuit_files:
            image = f"circuits/{circuit_files[candidate]}"
            break
    if not image:
        track_slug = _track_slug(track)
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


def _get_config_summary(name: str, active_config: str, running_config: str,
                        weather_labels: dict, behavior_labels: dict, mode_labels: dict,
                        circuit_files: dict) -> dict:
    server_config  = load_config_by_name(name) or {}
    server_section = server_config.get("Server", {})
    event_section  = server_config.get("Event", {})
    sessions       = server_config.get("Sessions", {})
    selected_cars  = [c for c in event_section.get("Cars", []) if c.get("IsSelected") or c.get("is_selected")]
    track_meta     = _get_track_meta(server_config, circuit_files)
    return {
        "name":             name,
        "active":           name == active_config,
        "running":          name == running_config,
        "server_name":      server_section.get("ServerName", name),
        "max_players":      server_section.get("MaxPlayers", "—"),
        "mode":             mode_labels.get(event_section.get("SelectedSessionTypeValue"),
                                            event_section.get("SelectedSessionTypeValue", "—")),
        "weather":          weather_labels.get(event_section.get("SelectedWeatherTypeValue"), "—"),
        "behavior":         behavior_labels.get(event_section.get("SelectedWeatherBehaviorValue"), "—"),
        "track":            track_meta,
        "car_count":        len(selected_cars),
        "practice_minutes": int(sessions.get("PracticeSession", {}).get("Length", 0) or 0) // 60,
        "race_minutes":     int(sessions.get("RaceSession", {}).get("Length", 0) or 0) // 60,
    }


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
        car["is_mod"] = bool(car.get("is_mod", False))
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

    config_summaries = [
        _get_config_summary(name, active_config, running_config,
                            weather_labels, behavior_labels, mode_labels, circuit_files)
        for name in configs
    ]
    current_track = _get_track_meta(config, circuit_files)
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
        current_weather_key=current_event.get("SelectedWeatherTypeValue", ""),
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
        "REQUIRE_EMAIL_CONFIRMATION", "LAP_HISTORY_RETENTION_MONTHS",
    ]),
    ("accounts", _l("Comptes"), []),  # Géré via AdminAccount en base de données
    ("server", _l("Serveur"), [
        "SERVER_NAME", "SERVER_MAX_PLAYERS", "SERVER_TCP_PORT", "SERVER_UDP_PORT",
        "SERVER_DRIVER_PASSWORD", "SERVER_ADMIN_PASSWORD",
        "SERVER_ENTRY_LIST_PATH", "SERVER_RESULTS_PATH",
        "ACESERVER_TCP_HOST", "ACESERVER_TCP_PORT", "ACESERVER_HTTP_PORT",
        "ACESERVER_DIR", "CONFIGS_DIR",
        "STEAM_USERNAME",
    ]),
    ("notifications", _l("Notifications"), [
        "ACE_BOT_STEAM_ID", "ACE_BOT_CAR_MODEL", "ACE_BOT_IS_ADMIN",
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
    "REQUIRE_EMAIL_CONFIRMATION": _l("Exige que les pilotes confirment leur email (lien envoyé à l'inscription) avant de pouvoir s'inscrire à un événement. Les comptes existants ne sont pas affectés rétroactivement."),
    "LAP_HISTORY_RETENTION_MONTHS": _l("Nombre de mois de conservation détaillée de l'historique des tours (temps, voiture, circuit). Au-delà, archivé en résumé mensuel compact plutôt que supprimé."),
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
_CHECKBOXES = {"ACE_BOT_IS_ADMIN", "SESSION_COOKIE_SECURE", "MAIL_USE_TLS", "REQUIRE_EMAIL_CONFIRMATION"}


from app import _SETTINGS_PATH, _SETTINGS_SKIP_KEYS, _SETTINGS_BOOL_KEYS, _APPCONFIG_RESERVED_KEYS, _APP_VERSION


def _read_env_file():
    """Lit la config depuis data/settings.json, avec fallback sur os.environ."""
    values = {}
    if _SETTINGS_PATH.exists():
        try:
            values = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("_read_env_file: settings.json illisible, fallback sur os.environ : %s", e)
    all_keys = {k for _, _, keys in _ENV_SECTIONS for k in keys}
    for k in all_keys:
        if k not in values and k in os.environ:
            values[k] = os.environ[k]
    return values, str(_SETTINGS_PATH)


def _write_env_file(new_values: dict):
    """Écrit la config dans data/settings.json (merge avec l'existant), en écriture atomique
    (fichier temporaire + os.replace) pour éviter de tronquer tous les settings sur un crash
    en cours d'écriture."""
    from app.services.process_manager import _atomic_write
    to_write = {k: v for k, v in new_values.items() if k not in _SETTINGS_SKIP_KEYS}
    existing = {}
    if _SETTINGS_PATH.exists():
        try:
            existing = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("_write_env_file: settings.json illisible, on repart d'un dict vide : %s", e)
    existing.update(to_write)
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(_SETTINGS_PATH, json.dumps(existing, indent=2, ensure_ascii=False))


# ── Bandeau "nouveautés .env" après une mise à jour ──────────────────────────
# Ajouter une entrée ici à chaque release qui introduit une variable .env, même
# optionnelle — c'est ce qui alimente le bandeau affiché aux admins tant qu'ils
# ne l'ont pas explicitement fermé (cf. dismiss_env_notice ci-dessous).
NEW_ENV_VARS_BY_VERSION: dict[str, list[tuple[str, str]]] = {
    "1.9.2": [
        ("STEAM_HOME", _l("Dossier de session Steam à monter si le panel est lancé via systemd "
                          "ou sudo sans -E (sinon ça reste vide et $HOME est utilisé, comme avant).")),
    ],
}

_LAST_SEEN_VERSION_KEY = "__last_seen_version"


def _get_last_seen_version() -> str:
    if not _SETTINGS_PATH.exists():
        return "0.0.0"
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data.get(_LAST_SEEN_VERSION_KEY, "0.0.0")
    except Exception:
        return "0.0.0"


def _set_last_seen_version(version: str) -> None:
    from app.services.process_manager import _atomic_write
    data = {}
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning("_set_last_seen_version: settings.json illisible, on repart d'un dict vide : %s", e)
    data[_LAST_SEEN_VERSION_KEY] = version
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(_SETTINGS_PATH, json.dumps(data, indent=2, ensure_ascii=False))


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def get_pending_env_notices() -> list[tuple[str, str]]:
    """Variables .env introduites depuis la dernière version vue par l'admin et
    absentes de l'environnement actuel. Liste vide = rien à signaler (défaut sûr
    déjà en place, ou déjà configuré, ou déjà vu et fermé)."""
    last_seen = _version_tuple(_get_last_seen_version())
    current   = _version_tuple(_APP_VERSION)
    notices: list[tuple[str, str]] = []
    for version, entries in NEW_ENV_VARS_BY_VERSION.items():
        if last_seen < _version_tuple(version) <= current:
            for key, desc in entries:
                if not os.environ.get(key, "").strip():
                    notices.append((key, desc))
    return notices


@admin_bp.route("/settings/dismiss-env-notice", methods=["POST"])
@_admin_required
def dismiss_env_notice():
    _set_last_seen_version(_APP_VERSION)
    # 200 (pas 204) : htmx ne swap jamais le contenu sur un 204, or on veut bien
    # que le hx-swap="outerHTML" fasse disparaître le bandeau.
    return "", 200


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
            from app.services.server_config import save_server_form
            _errors = save_server_form(current_srv, request.form)
            _port_errors = []
            for _err in _errors:
                if _err["type"] == "invalid_range":
                    _msg = _("Port invalide (1024–65535).")
                else:
                    _msg = _("Le port %(port)d est déjà utilisé par '%(name)s'.",
                             port=_err["port"], name=_err["name"])
                flash(_msg, "error")
                _port_errors.append(_msg)
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
                        if _k not in _APPCONFIG_RESERVED_KEYS:
                            current_app.config[_k] = _v
            if is_htmx():
                if _port_errors:
                    return _toast("error", " — ".join(_port_errors))
                return _toast("success", _("Paramètres du serveur sauvegardés."))
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
            # Applique immédiatement sans redémarrage (sauf clés structurelles, ex. SECRET_KEY :
            # les changer à chaud invaliderait/casserait les sessions en cours — nécessitent un redémarrage)
            for _k, _v in new_vals.items():
                if _k in _SETTINGS_SKIP_KEYS:
                    continue
                os.environ[_k] = _v
                if _k not in _APPCONFIG_RESERVED_KEYS:
                    current_app.config[_k] = (_v.lower() == "true") if _k in _SETTINGS_BOOL_KEYS else _v
        if is_htmx():
            return _toast("success", _("Paramètres sauvegardés"))
        flash(_("Paramètres sauvegardés"), "success")
        saved = True
        return redirect(url_for("admin.settings", tab=tab))

    media_banners = []
    media_dir = Path(__file__).parent.parent.parent / "media" / "banner"
    if media_dir.exists():
        media_banners = [f.name for f in sorted(media_dir.iterdir())
                         if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}]
    drivers_list   = Driver.query.order_by(Driver.created_at.desc()).limit(8).all() if tab == "users" else []
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

    mail_cfg = {k: v for k, v in mailer._cfg.items() if k != "password"}
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
                           server_status=get_status(sid),
                           mail_cfg=mail_cfg,
                           mail_preview_types=mailer.PREVIEW_TYPES)


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


# ── Mon compte (self-service admin/superadmin : email + Steam) ───────────────

@admin_bp.route("/mon-compte")
@_admin_required
def my_account():
    return render_template("my_account.html")


@admin_bp.route("/mon-compte/email", methods=["POST"])
@_admin_required
def my_account_email():
    email = request.form.get("email", "").strip().lower()
    if email:
        conflict = AdminAccount.query.filter(
            AdminAccount.email == email, AdminAccount.id != current_user.id
        ).first()
        if conflict:
            flash(_("Cet email est déjà utilisé."), "error")
            return redirect(url_for("admin.my_account"))
    current_user.email = email or None
    db.session.commit()
    flash(_("Email mis à jour."), "success")
    return redirect(url_for("admin.my_account"))


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
    from app.services.server_docker import resolve_new_server, create_server_container
    resolved = resolve_new_server(
        request.form.get("name", ""),
        request.form.get("tcp_port"),
        request.form.get("http_port"),
    )
    if not resolved["ok"]:
        _err = resolved["error"]
        if _err == "name_required":
            _msg = _("Le nom est requis.")
        elif _err == "invalid_port":
            _msg = _("Port invalide (1024–65535).")
        elif _err == "port_conflict":
            _msg = _("Le port %(port)d est déjà utilisé par un autre serveur.", port=resolved.get("port"))
        else:  # container_exists
            _msg = _("Un container Docker nommé '%(name)s' existe déjà.", name=resolved.get("container_name"))
        return flash_or_toast("error", _msg, "admin.servers_list")

    # Crée l'entrée en DB
    srv = Server(
        name           = resolved["name"],
        slug           = resolved["slug"],
        tcp_port       = resolved["tcp_port"],
        udp_port       = resolved["udp_port"],
        http_port      = resolved["http_port"],
        container_name = resolved["container_name"],
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
        return flash_or_toast("error",
            _("Erreur lors de la création du container : %(err)s", err=result["error"]),
            "admin.servers_list")

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

    if is_htmx():
        return htmx_redirect(url_for("admin.servers_list"))
    flash(_("Serveur '%(name)s' créé avec succès.", name=resolved["name"]), "success")
    return redirect(url_for("admin.servers_list"))


@admin_bp.route("/servers/<int:server_id>/toggle", methods=["POST"])
@_admin_required
@_superadmin_required
def server_toggle(server_id):
    if server_id == 1:
        return flash_or_toast("error", _("Le serveur principal ne peut pas être désactivé."), "admin.servers_list")
    srv = db.session.get(Server, server_id)
    if not srv:
        return flash_or_toast("error", _("Serveur introuvable."), "admin.servers_list")
    srv.is_enabled = not srv.is_enabled
    db.session.commit()
    msg = _("Serveur '%(name)s' activé.", name=srv.name) if srv.is_enabled else _("Serveur '%(name)s' désactivé.", name=srv.name)
    if is_htmx():
        try:
            st = get_status(srv.id)
        except Exception:
            st = {"running": False}
        return render_template("_partials/server_row.html", srv=srv, st=st,
                               toast_msg=msg, toast_type="success")
    flash(msg, "success")
    return redirect(url_for("admin.servers_list"))


@admin_bp.route("/servers/<int:server_id>/delete", methods=["POST"])
@_admin_required
@_superadmin_required
def server_delete(server_id):
    if server_id == 1:
        return flash_or_toast("error", _("Le serveur principal ne peut pas être supprimé."), "admin.servers_list")
    srv = db.session.get(Server, server_id)
    if not srv:
        return flash_or_toast("error", _("Serveur introuvable."), "admin.servers_list")

    # Stoppe les threads background du serveur (bot TCP + watchdog) avant suppression
    from app.services import ace_tcp_client, process_manager
    ace_tcp_client.stop(server_id)
    process_manager.stop_watchdog(server_id)

    # Arrête et supprime le container Docker
    from app.services.server_docker import remove_server_container, sync_compose_override
    remove_server_container(srv.container_name)

    # Supprime le dossier de configs déployées pour ce serveur
    delete_server_runtime_dir(server_id)

    name = srv.name
    db.session.delete(srv)
    db.session.commit()
    sync_compose_override()
    if is_htmx():
        from app.utils import htmx_oob_toast
        return htmx_oob_toast("success", _("Serveur '%(name)s' supprimé.", name=name))
    flash(_("Serveur '%(name)s' supprimé.", name=name), "success")
    return redirect(url_for("admin.servers_list"))


# ── Véhicules ─────────────────────────────────────────────────────────────────

@admin_bp.route("/vehicles")
@_admin_required
def vehicles():
    cat_filter = request.args.get("cat", "")
    search     = request.args.get("q", "").strip().lower()
    q = CarMeta.query.order_by(CarMeta.category, CarMeta.display_name)
    if cat_filter in _CATEGORY_ORDER:
        q = q.filter_by(category=cat_filter)
    cars = q.all()
    if search:
        cars = [c for c in cars if search in c.display_name.lower() or search in c.slug.lower()]
    from sqlalchemy import func as _func
    _raw_counts = dict(
        db.session.query(CarMeta.category, _func.count()).group_by(CarMeta.category).all()
    )
    counts = {cat: _raw_counts.get(cat, 0) for cat in _CATEGORY_ORDER}
    if is_htmx():
        return render_template("_partials/vehicle_grid.html", cars=cars)
    return render_template("vehicles.html", cars=cars, cat_filter=cat_filter,
                           search=search, counts=counts, categories=_CATEGORY_ORDER)


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
    track = db.get_or_404(TrackMeta, track_id)
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
