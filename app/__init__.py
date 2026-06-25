import os
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

_GIT_HASH = ""
try:
    import subprocess as _sp
    _GIT_HASH = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(Path(__file__).parent.parent),
        stderr=_sp.DEVNULL, timeout=2,
    ).decode().strip()
except Exception:
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


def _seed_servers(db):
    """Au 1er démarrage, crée le Serveur #1 depuis les variables d'environnement."""
    from app.models import Server
    if Server.query.count() > 0:
        return
    import os, logging
    log = logging.getLogger(__name__)
    try:
        tcp = int(os.environ.get("SERVER_TCP_PORT", "") or 9700)
    except (ValueError, TypeError):
        tcp = 9700
    try:
        udp = int(os.environ.get("SERVER_UDP_PORT", "") or 9700)
    except (ValueError, TypeError):
        udp = 9700
    s = Server(
        name            = os.environ.get("SERVER_NAME", "").strip() or "ACE EVO Server",
        slug            = "server-1",
        tcp_port        = tcp,
        udp_port        = udp,
        http_port       = 8081,
        container_name  = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server"),
        driver_password = os.environ.get("SERVER_DRIVER_PASSWORD", ""),
        admin_password  = os.environ.get("SERVER_ADMIN_PASSWORD",  ""),
        active_config   = "default.json",
        is_enabled      = True,
        sort_order      = 1,
    )
    db.session.add(s)
    db.session.commit()
    log.info("Serveur #1 créé automatiquement depuis .env")


def _migrate_indexes(db):
    """Crée les index composites manquants sur les DB existantes."""
    import sqlalchemy as sa
    indexes = [
        ("ix_event_status_email_sent",       "CREATE INDEX IF NOT EXISTS ix_event_status_email_sent ON event (status, email_sent)"),
        ("ix_event_status_discord_notified",  "CREATE INDEX IF NOT EXISTS ix_event_status_discord_notified ON event (status, discord_notified)"),
    ]
    with db.engine.connect() as conn:
        for name, sql in indexes:
            try:
                conn.execute(sa.text(sql))
                conn.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Index %s ignoré : %s", name, e)


def _migrate_db(db):
    """Applique les ALTER TABLE manquants sur SQLite sans casser les données existantes."""
    import sqlalchemy as sa
    engine = db.engine
    allowed_tables = {"event", "driver", "session_result"}
    allowed_columns = {
        "practice_minutes", "qualifying_minutes", "warmup_minutes", "race_minutes",
        "allowed_cars", "reset_token", "reset_token_expires", "is_public",
        "auto_launch", "launched", "discord_notified", "cars_config",
        "config_name", "run_id", "server_id",
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
        ("session_result", "server_id",   "INTEGER"),
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
                    import logging
                    logging.getLogger(__name__).warning("Migration server.%s ignorée : %s", col, e)


_PROP_CATEGORY = {0: "Road", 1: "Race", 2: "Track"}


def _sync_car_meta(db):
    """Synchronise CarMeta depuis cars.json au démarrage (upsert)."""
    import logging, re as _re
    from pathlib import Path as _Path
    log = logging.getLogger(__name__)
    try:
        from app.models import CarMeta
        from app.services.server_config import load_cars
        _media_cars = _Path(__file__).parent.parent / "media" / "cars"
        cars = load_cars()
        for car in cars:
            slug    = car["name"]
            dn      = car.get("display_name", "")
            pi      = car.get("performance_indicator")
            cat     = _PROP_CATEGORY.get(car.get("property_1", 0), "Road")
            existing = CarMeta.query.filter_by(slug=slug).first()
            if existing:
                existing.display_name = dn
                existing.pi_min = existing.pi_max = pi
                if not existing.category:
                    existing.category = cat
                if not existing.image_path:
                    for ext in (".webp", ".jpg", ".jpeg", ".png"):
                        if (_media_cars / f"{slug}{ext}").exists():
                            existing.image_path = f"cars/{slug}{ext}"
                            break
            else:
                img = ""
                for ext in (".webp", ".jpg", ".jpeg", ".png"):
                    if (_media_cars / f"{slug}{ext}").exists():
                        img = f"cars/{slug}{ext}"
                        break
                db.session.add(CarMeta(
                    slug=slug, display_name=dn, category=cat,
                    pi_min=pi, pi_max=pi, image_path=img,
                ))
        db.session.commit()
        log.info("CarMeta synchronisé : %d voitures", len(cars))
    except Exception as e:
        import logging as _l2
        _l2.getLogger(__name__).warning("_sync_car_meta ignoré : %s", e)


def _sync_track_meta(db):
    """Synchronise TrackMeta depuis les fichiers events au démarrage (upsert)."""
    import logging, json as _json, re as _re
    from pathlib import Path as _Path
    log = logging.getLogger(__name__)
    try:
        from app.models import TrackMeta
        from app.services.server_config import load_events
        from flask import current_app
        _configs_dir = _Path(current_app.config["CONFIGS_DIR"])
        _media_circ  = _Path(__file__).parent.parent / "media" / "circuits"

        def _slug_img(s):
            return _re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

        # Collect tracks from the full events catalogue (practice + race)
        # Key: (track_name, layout) → (track_value, length_m)  — first seen wins
        track_map: dict = {}
        for mode in ("practice", "race"):
            try:
                events = load_events(mode)
            except Exception:
                continue
            for ev in events:
                tn = ev.get("track", "")
                ly = ev.get("layout", "")
                en = ev.get("event_name", "")
                lm = ev.get("track_length")
                if not tn:
                    continue
                tv = f"{tn}|{ly}|{en}|{lm}" if lm else f"{tn}|{ly}|{en}"
                if (tn, ly) not in track_map:
                    track_map[(tn, ly)] = (tv, lm)

        # Also scan existing configs for custom tracks not in the events catalogue
        for cfg_path in _configs_dir.glob("*.json"):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                tv = cfg.get("Event", {}).get("SelectedTrackValue", "")
                if not tv:
                    continue
                parts = tv.split("|")
                tn = parts[0] if parts else ""
                ly = parts[1] if len(parts) > 1 else ""
                if tn and (tn, ly) not in track_map:
                    try:
                        lm = int(parts[3]) if len(parts) > 3 else None
                    except (ValueError, IndexError):
                        lm = None
                    track_map[(tn, ly)] = (tv, lm)
            except Exception:
                continue

        for (track_name, layout), (tv, length_m) in track_map.items():
            if TrackMeta.query.filter_by(track_value=tv).first():
                continue
            img = ""
            for candidate in (
                f"{_slug_img(track_name)}_{_slug_img(layout)}.webp",
                f"{_slug_img(track_name)}.webp",
            ):
                if (_media_circ / candidate).exists():
                    img = f"circuits/{candidate}"
                    break
            db.session.add(TrackMeta(
                track_value=tv, track_name=track_name, layout=layout,
                length_m=length_m, image_path=img,
            ))
        db.session.commit()
        log.info("TrackMeta synchronisé : %d circuits", len(track_map))
    except Exception as e:
        import logging as _l2
        _l2.getLogger(__name__).warning("_sync_track_meta ignoré : %s", e)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Extensions Flask ──────────────────────────────────────────────────────
    babel.init_app(app, locale_selector=get_locale, default_translation_directories=_TRANSLATIONS_DIR)
    login_manager.init_app(app)
    login_manager.login_view    = "auth.login"
    login_manager.login_message = None
    csrf.init_app(app)
    limiter.init_app(app)

    # ── Base de données ───────────────────────────────────────────────────────
    from app.services.database import db
    db.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401 — enregistre les modèles
        db.create_all()
        _migrate_db(db)
        _migrate_indexes(db)
        _migrate_server_discord(db)
        _seed_admin_accounts(db, app.config)
        _seed_servers(db)
        _sync_car_meta(db)
        _sync_track_meta(db)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.routes.auth            import auth_bp
    from app.routes.admin           import admin_bp
    from app.routes.api             import api_bp, results_ingest
    from app.routes.public          import public_bp
    from app.routes.events_admin    import events_admin_bp
    from app.routes.leaderboard     import leaderboard_bp
    from app.routes.live            import live_bp
    from app.routes.container_mgmt import container_mgmt_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp,             url_prefix="/api")
    app.register_blueprint(public_bp)
    app.register_blueprint(events_admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(container_mgmt_bp)
    # SSE streaming endpoint can't send CSRF tokens — exempt it individually.
    # All POST routes in live_bp remain CSRF-protected.
    from app.routes.live import live_stream
    csrf.exempt(live_stream)
    csrf.exempt(results_ingest)  # Webhook externe protégé par HMAC/réseau privé.

    app.jinja_env.globals["get_locale"]  = get_locale
    app.jinja_env.globals["app_version"]    = _APP_VERSION
    app.jinja_env.globals["git_hash"]       = _GIT_HASH
    app.jinja_env.globals["static_version"] = _STATIC_VERSION
    app.jinja_env.globals["panel_title"]       = Config.PANEL_TITLE
    app.jinja_env.globals["panel_banner_img"]  = Config.PANEL_BANNER_IMG
    app.jinja_env.globals["panel_logo_img"]    = Config.PANEL_LOGO_IMG
    app.jinja_env.globals["github_url"]        = Config.PANEL_GITHUB_URL
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
        from flask import session as _session
        from flask_login import current_user
        count = 0
        servers = []
        server_running_ids = set()
        current_server_id = _session.get("current_server_id", 1)
        try:
            if current_user.is_authenticated and current_user.is_admin:
                from app.models import Driver, Server
                from app.services.process_manager import is_running
                count = Driver.query.filter_by(status="pending").count()
                servers = Server.query.filter_by(is_enabled=True).order_by(Server.sort_order, Server.id).all()
                if servers and current_server_id not in {s.id for s in servers}:
                    current_server_id = servers[0].id
                server_running_ids = {s.id for s in servers if is_running(s.id)}
        except Exception:
            pass
        return {
            "pending_pilots_count": count,
            "discord_invite":       os.environ.get("DISCORD_INVITE_URL", ""),
            "servers":              servers,
            "current_server_id":    current_server_id,
            "server_running_ids":   server_running_ids,
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

    from app.services.process_manager import (
        init_watchdog, _DOCKER_CONTAINER_NAME, _ACESERVER_HOST,
    )
    with app.app_context():
        from app.models import Server as _Server
        _exe = app.config["ACESERVER_EXE_PATH"]
        for _srv in (_Server.query
                     .filter_by(is_enabled=True)
                     .order_by(_Server.sort_order, _Server.id)
                     .all()):
            # Server 1 : utilise les alias compose (rétrocompat)
            # Server N>1 : container_name sert de hostname Docker
            if _srv.id == 1:
                _cname = _DOCKER_CONTAINER_NAME
                _hhost = _ACESERVER_HOST
            else:
                _cname = _srv.container_name
                _hhost = _srv.container_name
            init_watchdog(_exe, server_id=_srv.id, container_name=_cname, http_host=_hhost, app=app)

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
    discord_notifier.init(panel_timezone=app.config.get("PANEL_TIMEZONE", "Europe/Paris"))

    from app.services import mailer
    mailer.init(app.config)

    from app.services import entry_list
    entry_list.init(app.config["ACESERVER_DIR"])

    from app.services.event_scheduler import init as init_scheduler
    init_scheduler(app)

    # ── Client TCP ACE EVO (chat in-game + leaderboard temps réel) ───────────
    if app.config.get("ACE_BOT_STEAM_ID", ""):
        from app.services import ace_tcp_client
        with app.app_context():
            from app.models import Server as _BotServer
            from app.services.database import db as _db
            for _srv in _BotServer.query.filter_by(is_enabled=True).order_by(_BotServer.id).all():
                ace_tcp_client.start_for_server(_srv, app.config)

    @app.context_processor
    def _inject_system_warnings():
        from flask import session as _session
        from flask_login import current_user
        from app.services.process_manager import get_system_warnings
        try:
            if current_user.is_authenticated and current_user.is_admin:
                sid = _session.get("current_server_id", 1)
                return {"system_warnings": get_system_warnings(sid)}
        except Exception:
            pass
        return {"system_warnings": []}

    return app
