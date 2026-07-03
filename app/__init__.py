import os
import logging as _log
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
    try:
        _hash_file = Path(__file__).parent.parent / ".git_hash"
        _v = _hash_file.read_text().strip()
        if _v and _v != "unknown":
            _GIT_HASH = _v
    except Exception:
        pass

login_manager = LoginManager()
babel         = Babel()
csrf          = CSRFProtect()
limiter       = Limiter(key_func=get_remote_address, default_limits=[])

# ── Persistance des paramètres (Portainer-compatible) ─────────────────────────
_SETTINGS_PATH      = Path(__file__).parent.parent / "data" / "settings.json"
_SETTINGS_SKIP_KEYS = {"SECRET_KEY"}   # clés structurelles : restent dans .env uniquement
_SETTINGS_BOOL_KEYS = {"SESSION_COOKIE_SECURE", "MAIL_USE_TLS", "ACE_BOT_IS_ADMIN", "REQUIRE_EMAIL_CONFIRMATION"}
# "SERVER_NAME" ici = nom d'affichage du serveur ACE EVO, mais c'est aussi une clé Flask
# réservée qui pilote url_for(_external=True)/le subdomain matching. Ne jamais la répercuter
# dans app.config, sous peine de casser toute génération d'URL externe (ex. callback Steam OpenID).
_APPCONFIG_RESERVED_KEYS = {"SERVER_NAME"}


def _load_settings(app):
    """Charge data/settings.json dans os.environ + app.config au démarrage."""
    import json as _json
    if not _SETTINGS_PATH.exists():
        return
    try:
        data = _json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        count = 0
        for k, v in data.items():
            if k not in _SETTINGS_SKIP_KEYS:
                os.environ[k] = str(v)
                if k not in _APPCONFIG_RESERVED_KEYS:
                    app.config[k] = (str(v).lower() == "true") if k in _SETTINGS_BOOL_KEYS else v
                count += 1
        _log.getLogger(__name__).info("settings.json chargé : %d clé(s)", count)
    except Exception as e:
        _log.getLogger(__name__).warning("settings.json illisible : %s", e)


def _migrate_dotenv_to_settings():
    """Migration one-time : copie les variables .env configurables dans settings.json."""
    import json as _json
    if _SETTINGS_PATH.exists():
        return
    try:
        from app.routes.admin import _ENV_SECTIONS
        user_keys = {k for _, _, keys in _ENV_SECTIONS for k in keys} - _SETTINGS_SKIP_KEYS
    except Exception:
        user_keys = set()
    data = {k: os.environ[k] for k in user_keys if k in os.environ}
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _log.getLogger(__name__).info("Migration .env → settings.json : %d clé(s) exportées", len(data))


def get_locale():
    if "lang" in session:
        return session["lang"]
    return request.accept_languages.best_match(Config.BABEL_SUPPORTED_LOCALES, Config.BABEL_DEFAULT_LOCALE)


def _seed_admin_accounts(db, cfg):
    """Au 1er démarrage, crée les comptes admin depuis les variables d'environnement."""
    from app.models import AdminAccount
    if AdminAccount.query.count() > 0:
        return
    log = _log.getLogger(__name__)
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
    log = _log.getLogger(__name__)
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


# Les migrations DB (_migrate_indexes, _migrate_db, _migrate_result_hash,
# _migrate_server_discord, _migrate_event_server_id, _migrate_server_http_port,
# _migrate_car_meta_props) vivent dans app/routes/admin.py (règle CLAUDE.md #4)
# et sont importées à l'appel dans create_app().

_PROP_CATEGORY = {0: "Road", 1: "Race", 2: "Track"}
_PROP_2        = {0: "Modern", 1: "Vintage", 2: "YT"}
_PROP_3        = {0: "ICE", 1: "EV", 2: "Hybrid"}


def _sync_car_meta(db):
    """Synchronise CarMeta depuis cars.json au démarrage (upsert, 1 requête SELECT)."""
    from pathlib import Path as _Path
    log = _log.getLogger(__name__)
    try:
        from app.models import CarMeta
        from app.services.server_config import load_cars
        _media_cars = _Path(__file__).parent.parent / "media" / "cars"
        cars = load_cars()
        existing_map = {c.slug: c for c in CarMeta.query.all()}
        for car in cars:
            slug  = car["name"]
            dn    = car.get("display_name", "")
            pi    = car.get("performance_indicator")
            cat   = _PROP_CATEGORY.get(car.get("property_1", 0), "Road")
            p2    = _PROP_2.get(car.get("property_2"), "")
            p3    = _PROP_3.get(car.get("property_3"), "")

            def _find_img(s):
                for ext in (".webp", ".jpg", ".jpeg", ".png"):
                    if (_media_cars / f"{s}{ext}").exists():
                        return f"cars/{s}{ext}"
                return ""

            existing = existing_map.get(slug)
            if existing:
                existing.display_name     = dn
                existing.pi_min           = existing.pi_max = pi
                existing.property_2_label = p2
                existing.property_3_label = p3
                if not existing.category:
                    existing.category = cat
                if not existing.image_path:
                    existing.image_path = _find_img(slug)
            else:
                db.session.add(CarMeta(
                    slug=slug, display_name=dn, category=cat,
                    property_2_label=p2, property_3_label=p3,
                    pi_min=pi, pi_max=pi, image_path=_find_img(slug),
                ))
        db.session.commit()
        log.info("CarMeta synchronisé : %d voitures", len(cars))
    except Exception as e:
        _log.getLogger(__name__).warning("_sync_car_meta ignoré : %s", e)


def _sync_track_meta(db):
    """Synchronise TrackMeta depuis les fichiers events au démarrage (upsert)."""
    import json as _json, re as _re
    from pathlib import Path as _Path
    log = _log.getLogger(__name__)
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
        log.warning("_sync_track_meta ignoré : %s", e)


def _register_extensions(app):
    babel.init_app(app, locale_selector=get_locale, default_translation_directories=_TRANSLATIONS_DIR)
    login_manager.init_app(app)
    login_manager.login_view    = "auth.login"
    login_manager.login_message = None
    csrf.init_app(app)
    limiter.init_app(app)


def _register_blueprints(app):
    from app.routes.auth            import auth_bp
    from app.routes.admin           import admin_bp
    from app.routes.api             import api_bp, results_ingest
    from app.routes.public          import public_bp
    from app.routes.events_admin    import events_admin_bp
    from app.routes.leaderboard     import leaderboard_bp
    from app.routes.live            import live_bp, live_stream
    from app.routes.container_mgmt import container_mgmt_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp,          url_prefix="/api")
    app.register_blueprint(public_bp)
    app.register_blueprint(events_admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(container_mgmt_bp)
    # SSE endpoint can't carry CSRF tokens — exempt individually.
    csrf.exempt(live_stream)
    csrf.exempt(results_ingest)  # Webhook protégé par HMAC/réseau privé.


def _register_jinja(app):
    import json as _json
    from flask import send_from_directory
    from zoneinfo import ZoneInfo as _ZoneInfo
    from datetime import timezone as _utc_tz

    app.jinja_env.globals.update({
        "get_locale":        get_locale,
        "app_version":       _APP_VERSION,
        "git_hash":          _GIT_HASH,
        "static_version":    _STATIC_VERSION,
        "panel_title":       Config.PANEL_TITLE,
        "panel_banner_img":  Config.PANEL_BANNER_IMG,
        "panel_logo_img":    Config.PANEL_LOGO_IMG,
        "github_url":        Config.PANEL_GITHUB_URL,
    })
    app.jinja_env.filters["from_json"] = lambda s: _json.loads(s) if s else []

    _media_dir = Path(__file__).parent.parent / "media"

    @app.route("/media/<path:filename>")
    def serve_media(filename):
        return send_from_directory(str(_media_dir), filename)

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

    def _session_type_label(value):
        """Traduit un session_type brut (valeur du jeu, en anglais) en libellé localisé.
        Retombe sur la valeur brute si elle n'est pas reconnue."""
        if not value:
            return value
        from flask_babel import gettext as _gt
        labels = {
            "practice":   _gt("Practice"),
            "qualify":    _gt("Qualifying"),
            "qualifying": _gt("Qualifying"),
            "warmup":     _gt("Warmup"),
            "race":       _gt("Race"),
        }
        return labels.get(value.strip().lower(), value)

    app.jinja_env.filters['session_type_label'] = _session_type_label


def _register_request_hooks(app):
    import secrets
    from flask import g

    @app.before_request
    def _generate_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_globals():
        from flask import session as _session, g as _g
        from flask_login import current_user
        count = 0
        servers = []
        server_running_ids = set()
        current_server_id = _session.get("current_server_id", 1)
        try:
            if current_user.is_authenticated and current_user.is_admin:
                from app.models import Driver, Server, DriverStatus
                from app.services.process_manager import is_running
                count = Driver.query.filter_by(status=DriverStatus.PENDING).count()
                servers = Server.query.filter_by(is_enabled=True).order_by(Server.sort_order, Server.id).all()
                if servers and current_server_id not in {s.id for s in servers}:
                    current_server_id = servers[0].id
                server_running_ids = {s.id for s in servers if is_running(s.id)}
        except Exception:
            pass
        from datetime import datetime as _dt
        return {
            "pending_pilots_count": count,
            "discord_invite":       os.environ.get("DISCORD_INVITE_URL", ""),
            "servers":              servers,
            "current_server_id":    current_server_id,
            "server_running_ids":   server_running_ids,
            "csp_nonce":            getattr(_g, "csp_nonce", ""),
            "now":                  _dt.utcnow(),
        }

    @app.after_request
    def _security_headers(response):
        from flask import g as _g
        nonce = getattr(_g, "csp_nonce", "")
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' 'unsafe-inline' https://cdn.jsdelivr.net 'unsafe-eval'; "
            "script-src-attr 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.jsdelivr.net; "
            "font-src 'self'; "
            "connect-src 'self'"
        )
        if Config.SESSION_COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.context_processor
    def _inject_status_constants():
        from app.models import EventStatus, DriverStatus, RegStatus
        return {"EventStatus": EventStatus, "DriverStatus": DriverStatus, "RegStatus": RegStatus}

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


def _start_services(app):
    import json as _json

    _sec = _log.getLogger("security")
    if Config.SECRET_KEY == "dev-secret-key":
        _sec.critical("SECRET_KEY utilise la valeur par défaut — les sessions sont forgeable !")
    if Config.ADMIN_PASSWORD == "admin":
        _sec.warning("ADMIN_PASSWORD utilise la valeur par défaut 'admin' — changez-la dans .env")
    if Config.SUPERADMIN_PASSWORD == "superadmin":
        _sec.warning("SUPERADMIN_PASSWORD utilise la valeur par défaut 'superadmin' — changez-la dans .env")
    if not Config.RESULTS_INGEST_SECRET:
        _sec.warning("RESULTS_INGEST_SECRET non défini — /api/results/ingest accepte seulement les réseaux privés/locaux")

    from app.services.process_manager import init_watchdog, _DOCKER_CONTAINER_NAME, _ACESERVER_HOST
    with app.app_context():
        from app.models import Server as _Server
        _exe = app.config["ACESERVER_EXE_PATH"]
        for _srv in _Server.query.filter_by(is_enabled=True).order_by(_Server.sort_order, _Server.id).all():
            _cname = _DOCKER_CONTAINER_NAME if _srv.id == 1 else _srv.container_name
            _hhost = _ACESERVER_HOST        if _srv.id == 1 else _srv.container_name
            init_watchdog(_exe, server_id=_srv.id, container_name=_cname, http_host=_hhost, app=app)

    _configs_dir = Path(app.config["CONFIGS_DIR"])
    _configs_dir.mkdir(parents=True, exist_ok=True)
    if not any(_configs_dir.glob("*.json")):
        from app.services.server_config import _default_config
        _default_path = _configs_dir / "default.json"
        _default_path.write_text(
            _json.dumps(_default_config(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log.getLogger(__name__).info("Config initiale créée : %s", _default_path)

    try:
        from app.services.results_parser import scan_and_import
        with app.app_context():
            scan_and_import(app.config["ACESERVER_DIR"])
    except Exception as _e:
        _log.getLogger(__name__).warning("scan_and_import ignoré : %s", _e)

    try:
        from app.services.server_docker import sync_compose_override
        with app.app_context():
            sync_compose_override()
    except Exception as _e:
        _log.getLogger(__name__).warning("sync_compose_override ignoré : %s", _e)

    from app.services import discord_notifier
    discord_notifier.init(panel_timezone=app.config.get("PANEL_TIMEZONE", "Europe/Paris"))

    from app.services import mailer
    mailer.init(app.config)

    from app.services import entry_list
    entry_list.init(app.config["ACESERVER_DIR"])

    from app.services.event_scheduler import init as init_scheduler
    init_scheduler(app)

    if app.config.get("ACE_BOT_STEAM_ID", ""):
        from app.services import ace_tcp_client
        with app.app_context():
            from app.models import Server as _BotServer
            for _srv in _BotServer.query.filter_by(is_enabled=True).order_by(_BotServer.id).all():
                ace_tcp_client.start_for_server(_srv, app.config)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    _load_settings(app)   # surcharge avec les paramètres UI sauvegardés (settings.json)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _register_extensions(app)

    from app.services.database import db
    db.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401 — enregistre les modèles
        db.create_all()
        from sqlalchemy import text as _sql_text
        db.session.execute(_sql_text("PRAGMA journal_mode=WAL"))
        db.session.execute(_sql_text("PRAGMA synchronous=NORMAL"))
        db.session.commit()
        from app.routes.admin import (
            _migrate_db, _migrate_indexes, _migrate_server_discord,
            _migrate_server_http_port, _migrate_event_server_id,
            _migrate_car_meta_props, _migrate_result_hash,
            _migrate_driver_steam_id, _migrate_admin_account_extra,
            _migrate_driver_email_confirmation,
        )
        _migrate_db(db)
        _migrate_indexes(db)
        _migrate_server_discord(db)
        _migrate_server_http_port(db)
        _migrate_event_server_id(db)
        _migrate_car_meta_props(db)
        _migrate_result_hash(db)
        _migrate_driver_steam_id(db)
        _migrate_admin_account_extra(db)
        _migrate_driver_email_confirmation(db)
        _seed_admin_accounts(db, app.config)
        _seed_servers(db)
        _sync_car_meta(db)
        _sync_track_meta(db)
        _migrate_dotenv_to_settings()   # one-time : exporte .env → settings.json

    _register_blueprints(app)
    _register_jinja(app)
    _register_request_hooks(app)
    _start_services(app)

    return app
