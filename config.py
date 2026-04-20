import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "superadmin")
    SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "superadmin")

    # Dossier contenant tous les fichiers de config JSON
    CONFIGS_DIR = os.environ.get(
        "CONFIGS_DIR",
        r"C:\Users\Administrateur\Documents\ACE"
    )
    ACESERVER_EXE_PATH = os.environ.get(
        "ACESERVER_EXE_PATH",
        r"C:\aceserver\AssettoCorsaEVOServer.exe"
    )
    CARS_JSON_PATH = os.environ.get(
        "CARS_JSON_PATH",
        r"C:\aceserver\cars.json"
    )
    EVENTS_PRACTICE_JSON_PATH = os.environ.get(
        "EVENTS_PRACTICE_JSON_PATH",
        r"C:\aceserver\events_practice.json"
    )
    EVENTS_RACE_JSON_PATH = os.environ.get(
        "EVENTS_RACE_JSON_PATH",
        r"C:\aceserver\events_race_weekend.json"
    )

    ACESERVER_HTTP_PORT  = int(os.environ.get("ACESERVER_HTTP_PORT", 8080))
    DISCORD_WEBHOOK_URL  = os.environ.get("DISCORD_WEBHOOK_URL", "")
    SERVER_SHOW_CONSOLE = os.environ.get("SERVER_SHOW_CONSOLE", "true").lower() == "true"

    BABEL_DEFAULT_LOCALE = "fr"
    BABEL_SUPPORTED_LOCALES = ["fr", "en"]

    # Sécurité cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE   = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
