import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY          = os.environ.get("SECRET_KEY", "dev-secret-key")
    ADMIN_USERNAME      = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD      = os.environ.get("ADMIN_PASSWORD", "admin")
    SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "superadmin")
    SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "superadmin")

    # Dossier contenant les fichiers de config JSON du panel
    CONFIGS_DIR = os.environ.get("CONFIGS_DIR", r"C:\Users\Administrateur\Documents\ACE")

    # Dossier d'installation du serveur de jeu.
    ACESERVER_DIR = os.environ.get("ACESERVER_DIR", r"C:\aceserver")

    ACESERVER_EXE_PATH = os.environ.get(
        "ACESERVER_EXE_PATH",
        os.path.join(ACESERVER_DIR, "AssettoCorsaEVOServer.exe"),
    )
    CARS_JSON_PATH = os.environ.get(
        "CARS_JSON_PATH",
        os.path.join(ACESERVER_DIR, "cars.json"),
    )
    EVENTS_PRACTICE_JSON_PATH = os.environ.get(
        "EVENTS_PRACTICE_JSON_PATH",
        os.path.join(ACESERVER_DIR, "events_practice.json"),
    )
    EVENTS_RACE_JSON_PATH = os.environ.get(
        "EVENTS_RACE_JSON_PATH",
        os.path.join(ACESERVER_DIR, "events_race_weekend.json"),
    )

    ACESERVER_HTTP_PORT = int(os.environ.get("ACESERVER_HTTP_PORT", 8080))
    DISCORD_WEBHOOK_URL        = os.environ.get("DISCORD_WEBHOOK_URL", "")
    DISCORD_PILOTS_WEBHOOK_URL = os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", "")
    DISCORD_INVITE_URL         = os.environ.get("DISCORD_INVITE_URL", "")
    SERVER_SHOW_CONSOLE = os.environ.get("SERVER_SHOW_CONSOLE", "true").lower() == "true"

    # ── Base de données ───────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI     = os.environ.get("DATABASE_URL", "sqlite:///ace_evo.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Email ─────────────────────────────────────────────────────────────────
    MAIL_SERVER   = os.environ.get("MAIL_SERVER",   "")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS  = os.environ.get("MAIL_USE_TLS",  "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM     = os.environ.get("MAIL_FROM",     "")
    MAIL_ADMIN    = os.environ.get("MAIL_ADMIN",    "")

    # URL publique du panel (pour les liens dans les emails)
    PANEL_URL = os.environ.get("PANEL_URL", "http://localhost:4300")

    # ── i18n ─────────────────────────────────────────────────────────────────
    BABEL_DEFAULT_LOCALE    = os.environ.get("DEFAULT_LOCALE", "fr")
    BABEL_SUPPORTED_LOCALES = ["fr", "en", "es", "de", "it"]

    # ── Fuseau horaire ────────────────────────────────────────────────────────
    PANEL_TIMEZONE = os.environ.get("PANEL_TIMEZONE", "Europe/Paris")

    # ── Mode de déploiement ───────────────────────────────────────────────────
    # "native" = Windows subprocess, "docker" = Wine sur Linux
    DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "native")

    # ── Cookies / Session ─────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = "Lax"
    SESSION_COOKIE_SECURE    = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
