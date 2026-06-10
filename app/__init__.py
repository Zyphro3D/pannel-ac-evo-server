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
_STATIC_DIR       = Path(__file__).parent / "static"
_STATIC_VERSION   = _APP_VERSION
try:
    _STATIC_VERSION = f"{_APP_VERSION}.{max((_STATIC_DIR / 'css' / 'main.css').stat().st_mtime_ns, (_STATIC_DIR / 'js' / 'app.js').stat().st_mtime_ns)}"
except OSError:
    pass

login_manager = LoginManager()
babel         = Babel()
csrf          = CSRFProtect()
limiter       = Limiter(key_func=get_remote_address, default_limits=[])


def get_locale():
    if "lang" in session:
        return session["lang"]
    return request.accept_languages.best_match(Config.BABEL_SUPPORTED_LOCALES, Config.BABEL_DEFAULT_LOCALE)


def _seed_admin_accounts(db, cfg):
    """Au 1er démarrage, crée les comptes admin depuis les variables d'environnement."""
    from app.models import AdminAccount
    if AdminAccount.query.count() > 0:
        return
    import logging
    log = logging.getLogger(__name__)
    su_user = cfg.get("SUPERADMIN_USERNAME", "superadmin")
    su_pass = cfg.get("SUPERADMIN_PASSWORD", "")
    ad_user = cfg.get("ADMIN_USERNAME", "admin")
    ad_pass = cfg.get("ADMIN_PASSWORD", "")
    if su_pass:
        sa = AdminAccount(username=su_user, display_name="Super Admin", role="superadmin")
        sa.set_password(su_pass)
        db.session.add(sa)
        log.info("Compte superadmin '%s' migré vers la base de données.", su_user)
    if ad_pass and ad_user != su_user:
        a = AdminAccount(username=ad_user, display_name="Administrateur", role="admin")
        a.set_password(ad_pass)
        db.session.add(a)
        log.info("Compte admin '%s' migré vers la base de données.", ad_user)
    db.session.commit()


def _migrate_db(db):
    """Applique les ALTER TABLE manquants sur SQLite sans casser les données existantes."""
    import sqlalchemy as sa
    engine = db.engine
    allowed_tables = {"event", "driver", "session_result"}
    allowed_columns = {
        "practice_minutes", "qualifying_minutes", "warmup_minutes", "race_minutes",
        "allowed_cars", "reset_token", "reset_token_expires", "is_public",
        "auto_launch", "launched", "discord_notified", "cars_config",
        "config_name", "run_id",
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
        ("session_result", "config_name", "TEXT"),
        ("session_result", "run_id",      "TEXT"),
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
        _seed_admin_accounts(db, app.config)

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
    from app.routes.api          import api_bp, results_ingest
    from app.routes.public       import public_bp
    from app.routes.events_admin import events_admin_bp
    from app.routes.leaderboard  import leaderboard_bp
    from app.routes.live         import live_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp,          url_prefix="/api")
    app.register_blueprint(public_bp)
    app.register_blueprint(events_admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(live_bp)
    csrf.exempt(live_bp)
    csrf.exempt(results_ingest)  # Webhook externe protégé par HMAC/réseau privé.

    app.jinja_env.globals["get_locale"]  = get_locale
    app.jinja_env.globals["app_version"] = _APP_VERSION
    app.jinja_env.globals["static_version"] = _STATIC_VERSION
    app.jinja_env.globals["panel_title"]       = Config.PANEL_TITLE
    app.jinja_env.globals["panel_banner_img"]  = Config.PANEL_BANNER_IMG
    app.jinja_env.globals["panel_logo_img"]    = Config.PANEL_LOGO_IMG
    import json as _json
    app.jinja_env.filters["from_json"] = lambda s: _json.loads(s) if s else []

    # ── Servir le dossier media/ ─────────────────────────────────────────────
    _media_dir = Path(__file__).parent.parent / "media"
    from flask import send_from_directory
    @app.route("/media/<path:filename>")
    def serve_media(filename):
        return send_from_directory(str(_media_dir), filename)

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
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.jsdelivr.net; "
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
    if not Config.RESULTS_INGEST_SECRET:
        _sec.warning("RESULTS_INGEST_SECRET non défini — /api/results/ingest accepte seulement les réseaux privés/locaux")

    from app.services.process_manager import init_watchdog
    init_watchdog(app.config["ACESERVER_EXE_PATH"])

    # Crée default.json si le dossier de configs est vide (premier démarrage)
    _configs_dir = Path(app.config["CONFIGS_DIR"])
    _configs_dir.mkdir(parents=True, exist_ok=True)
    if not any(_configs_dir.glob("*.json")):
        import json as _json2
        from app.services.server_config import _default_config
        _default_path = _configs_dir / "default.json"
        _default_path.write_text(
            _json2.dumps(_default_config(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _logging.getLogger(__name__).info("Config initiale créée : %s", _default_path)

    # Importe les fichiers de résultats existants (sessions passées hors panel)
    try:
        from app.services.results_parser import scan_and_import
        with app.app_context():
            scan_and_import(app.config["ACESERVER_DIR"])
    except Exception as _e:
        _logging.getLogger(__name__).warning("scan_and_import ignoré : %s", _e)

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

    # ── Client TCP ACE EVO (chat in-game + leaderboard temps réel) ───────────
    _bot_steam_id = app.config.get("ACE_BOT_STEAM_ID", "")
    if _bot_steam_id:
        from app.services import ace_tcp_client
        _tcp_host = app.config.get("ACESERVER_TCP_HOST", "127.0.0.1")
        _tcp_port = app.config.get("ACESERVER_TCP_PORT", 9700)
        _car_model = app.config.get("ACE_BOT_CAR_MODEL", "preset_190_evo_ii")
        from app.services.process_manager import _LOG_FILE, _DEPLOY_MODE, _DOCKER_CONTAINER_NAME
        ace_tcp_client.start(
            host=_tcp_host,
            port=_tcp_port,
            steam_id=_bot_steam_id,
            car_model=_car_model,
            display_name=app.config.get("ACE_BOT_DISPLAY_NAME", ""),
            admin_password=app.config.get("ACE_BOT_ADMIN_PASSWORD", ""),
            discord_url=app.config.get("DISCORD_INVITE_URL", ""),
            site_url=app.config.get("PANEL_URL", ""),
            deploy_mode=_DEPLOY_MODE,
            log_file=str(_LOG_FILE),
            container_name=_DOCKER_CONTAINER_NAME,
        )

    return app
