from pathlib import Path
from flask import Flask, request, session
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config

_TRANSLATIONS_DIR = str(Path(__file__).parent.parent / "translations")
_VERSION_FILE     = Path(__file__).parent.parent / "VERSION"
_APP_VERSION      = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "?"

login_manager = LoginManager()
babel         = Babel()
csrf          = CSRFProtect()
limiter       = Limiter(key_func=get_remote_address, default_limits=[])


def get_locale():
    if "lang" in session:
        return session["lang"]
    return request.accept_languages.best_match(Config.BABEL_SUPPORTED_LOCALES, Config.BABEL_DEFAULT_LOCALE)


def _migrate_db(db):
    """Applique les ALTER TABLE manquants sur SQLite sans casser les données existantes."""
    import sqlalchemy as sa
    engine = db.engine
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
    ]
    with engine.connect() as conn:
        for table, col, col_def in cols_to_add:
            try:
                existing = [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))]
                if col not in existing:
                    conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                    conn.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Migration %s.%s ignorée : %s", table, col, e)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Base de données ───────────────────────────────────────────────────────
    from app.services.database import db
    db.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401 — enregistre les modèles
        db.create_all()
        _migrate_db(db)

    # ── Extensions Flask ──────────────────────────────────────────────────────
    babel.init_app(app, locale_selector=get_locale, default_translation_directories=_TRANSLATIONS_DIR)
    login_manager.init_app(app)
    login_manager.login_view    = "auth.login"
    login_manager.login_message = None
    csrf.init_app(app)
    limiter.init_app(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.routes.auth         import auth_bp
    from app.routes.admin        import admin_bp
    from app.routes.api          import api_bp
    from app.routes.public       import public_bp
    from app.routes.events_admin import events_admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp,          url_prefix="/api")
    app.register_blueprint(public_bp)
    app.register_blueprint(events_admin_bp)
    csrf.exempt(api_bp)  # API JSON : CSRF géré via X-CSRFToken dans app.js

    app.jinja_env.globals["get_locale"]  = get_locale
    app.jinja_env.globals["app_version"] = _APP_VERSION
    import json as _json
    app.jinja_env.filters["from_json"] = lambda s: _json.loads(s) if s else []

    from zoneinfo import ZoneInfo as _ZoneInfo
    from datetime import timezone as _utc_tz
    _panel_tz = _ZoneInfo(Config.PANEL_TIMEZONE)
    def _local_dt(dt):
        if dt is None:
            return ''
        aware = dt.replace(tzinfo=_utc_tz.utc).astimezone(_panel_tz)
        return aware.strftime('%d/%m/%Y %H:%M') + f' ({aware.strftime("%Z")})'
    def _local_dt_short(dt):
        if dt is None:
            return ''
        aware = dt.replace(tzinfo=_utc_tz.utc).astimezone(_panel_tz)
        return aware.strftime('%d/%m %H:%M')
    def _local_dt_input(dt):
        if dt is None:
            return ''
        aware = dt.replace(tzinfo=_utc_tz.utc).astimezone(_panel_tz)
        return aware.strftime('%Y-%m-%dT%H:%M')
    app.jinja_env.filters['local_dt']       = _local_dt
    app.jinja_env.filters['local_dt_short'] = _local_dt_short
    app.jinja_env.filters['local_dt_input'] = _local_dt_input

    @app.context_processor
    def _inject_globals():
        from flask_login import current_user
        count = 0
        try:
            if current_user.is_authenticated and current_user.is_admin:
                from app.models import Driver
                count = Driver.query.filter_by(status="pending").count()
        except Exception:
            pass
        return {
            "pending_pilots_count": count,
            "discord_invite": Config.DISCORD_INVITE_URL,
        }

    @app.after_request
    def _security_headers(response):
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'"
        )
        if Config.SESSION_COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── Services ──────────────────────────────────────────────────────────────
    # ── Avertissements de sécurité au démarrage ───────────────────────────────
    import logging as _logging
    _sec = _logging.getLogger("security")
    if Config.SECRET_KEY == "dev-secret-key":
        _sec.critical("SECRET_KEY utilise la valeur par défaut — les sessions sont forgeable !")
    if Config.ADMIN_PASSWORD == "admin":
        _sec.warning("ADMIN_PASSWORD utilise la valeur par défaut 'admin' — changez-la dans .env")
    if Config.SUPERADMIN_PASSWORD == "superadmin":
        _sec.warning("SUPERADMIN_PASSWORD utilise la valeur par défaut 'superadmin' — changez-la dans .env")

    from app.services.process_manager import init_watchdog
    init_watchdog(app.config["ACESERVER_EXE_PATH"])

    from app.services import discord_notifier
    discord_notifier.init(
        app.config.get("DISCORD_WEBHOOK_URL", ""),
        app.config.get("DISCORD_PILOTS_WEBHOOK_URL", ""),
        app.config.get("PANEL_TIMEZONE", "Europe/Paris"),
    )

    from app.services import mailer
    mailer.init(app.config)

    from app.services import entry_list
    entry_list.init(app.config["ACESERVER_DIR"])

    from app.services.event_scheduler import init as init_scheduler
    init_scheduler(app)

    return app
