from pathlib import Path
from flask import Flask, request, session
from flask_babel import Babel
from flask_login import LoginManager
from config import Config

_TRANSLATIONS_DIR = str(Path(__file__).parent.parent / "translations")

login_manager = LoginManager()
babel = Babel()


def get_locale():
    if "lang" in session:
        return session["lang"]
    return request.accept_languages.best_match(Config.BABEL_SUPPORTED_LOCALES, "fr")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    babel.init_app(app, locale_selector=get_locale, default_translation_directories=_TRANSLATIONS_DIR)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    app.jinja_env.globals["get_locale"] = get_locale

    from app.services.process_manager import init_watchdog
    init_watchdog(app.config["ACESERVER_EXE_PATH"])

    from app.services import discord_notifier
    discord_notifier.init(app.config.get("DISCORD_WEBHOOK_URL", ""))

    return app
