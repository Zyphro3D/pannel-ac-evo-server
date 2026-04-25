from pathlib import Path
from flask import Flask, request, session
from flask_babel import Babel
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config

_TRANSLATIONS_DIR = str(Path(__file__).parent.parent / "translations")
_VERSION_FILE     = Path(__file__).parent.parent / "VERSION"
_APP_VERSION      = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "?"

login_manager = LoginManager()
babel         = Babel()


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
        ("event",  "auto_launch",         "INTEGER DEFAULT 0"),
        ("event",  "launched",            "INTEGER DEFAULT 0"),
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

    app.jinja_env.globals["get_locale"]  = get_locale
    app.jinja_env.globals["app_version"] = _APP_VERSION
    import json as _json
    app.jinja_env.filters["from_json"] = lambda s: _json.loads(s or "[]")

    @app.context_processor
    def _inject_pending_pilots():
        from flask_login import current_user
        count = 0
        try:
            if current_user.is_authenticated and current_user.is_admin:
                from app.models import Driver
                count = Driver.query.filter_by(status="pending").count()
        except Exception:
            pass
        return {"pending_pilots_count": count}

    @app.after_request
    def _security_headers(response):
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        return response

    # ── Services ──────────────────────────────────────────────────────────────
    from app.services.process_manager import init_watchdog
    init_watchdog(app.config["ACESERVER_EXE_PATH"])

    from app.services import discord_notifier
    discord_notifier.init(
        app.config.get("DISCORD_WEBHOOK_URL", ""),
        app.config.get("DISCORD_PILOTS_WEBHOOK_URL", ""),
    )

    from app.services import mailer
    mailer.init(app.config)

    from app.services import entry_list
    entry_list.init(app.config["ACESERVER_DIR"])

    from app.services.event_scheduler import init as init_scheduler
    init_scheduler(app)

    return app
