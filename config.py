import os
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
    # ACESERVER_DIR suffit ; les chemins individuels sont dérivés automatiquement.
    # Définir une variable individuelle uniquement si le fichier est ailleurs.
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
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    SERVER_SHOW_CONSOLE = os.environ.get("SERVER_SHOW_CONSOLE", "true").lower() == "true"

    BABEL_DEFAULT_LOCALE    = "fr"
    BABEL_SUPPORTED_LOCALES = ["fr", "en"]

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE   = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
