import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} doit être défini dans l'environnement ou dans .env")
    return value


# Défauts des messages du bot TCP — réutilisés tels quels par ace_tcp_client.py
# (paramètre par défaut de _welcome_loop_native/docker et fallback de _tcp_cfg_from_settings)
# pour éviter que les 2 côtés divergent si un seul est modifié.
DEFAULT_BOT_MSG_WELCOME = "Bienvenue {name} !"
DEFAULT_BOT_MSG_DISCORD = "Rejoins le discord : {discord_url}"
DEFAULT_BOT_MSG_SITE    = "Retrouve tes resultats et evenements sur : {site_url}"


class Config:
    SECRET_KEY          = _required_env("SECRET_KEY")
    ADMIN_USERNAME      = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD      = _required_env("ADMIN_PASSWORD")
    SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "superadmin")
    SUPERADMIN_PASSWORD = _required_env("SUPERADMIN_PASSWORD")

    # Dossier contenant les fichiers de config JSON du panel
    CONFIGS_DIR = os.environ.get("CONFIGS_DIR", "/aceserver/configs")

    # Dossier d'installation du serveur de jeu.
    ACESERVER_DIR = os.environ.get("ACESERVER_DIR", "/aceserver")

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

    ACESERVER_HTTP_PORT = int(os.environ.get("ACESERVER_HTTP_PORT") or 8081)
    ACESERVER_TCP_HOST  = os.environ.get("ACESERVER_TCP_HOST", "127.0.0.1")
    ACESERVER_TCP_PORT  = int(os.environ.get("ACESERVER_TCP_PORT")  or 9700)

    # ── Client TCP (chat in-game + leaderboard temps réel) ────────────────────
    # Steam ID du "bot" qui se connecte au serveur (laisser vide pour désactiver)
    ACE_BOT_STEAM_ID       = os.environ.get("ACE_BOT_STEAM_ID",       "")
    ACE_BOT_CAR_MODEL      = os.environ.get("ACE_BOT_CAR_MODEL",      "preset_190e_mech_1")
    ACE_BOT_IS_ADMIN       = os.environ.get("ACE_BOT_IS_ADMIN",       "false")
    ACE_BOT_MSG_WELCOME    = os.environ.get("ACE_BOT_MSG_WELCOME",    DEFAULT_BOT_MSG_WELCOME)
    ACE_BOT_MSG_DISCORD    = os.environ.get("ACE_BOT_MSG_DISCORD",    DEFAULT_BOT_MSG_DISCORD)
    ACE_BOT_MSG_SITE       = os.environ.get("ACE_BOT_MSG_SITE",       DEFAULT_BOT_MSG_SITE)
    DISCORD_WEBHOOK_URL        = os.environ.get("DISCORD_WEBHOOK_URL", "")
    DISCORD_PILOTS_WEBHOOK_URL = os.environ.get("DISCORD_PILOTS_WEBHOOK_URL", "")
    DISCORD_RACE_WEBHOOK_URL   = os.environ.get("DISCORD_RACE_WEBHOOK_URL", "")
    DISCORD_INVITE_URL         = os.environ.get("DISCORD_INVITE_URL", "")
    RESULTS_INGEST_SECRET      = os.environ.get("RESULTS_INGEST_SECRET", "")
    REQUIRE_EMAIL_CONFIRMATION = os.environ.get("REQUIRE_EMAIL_CONFIRMATION", "false").lower() == "true"
    SERVER_SHOW_CONSOLE = os.environ.get("SERVER_SHOW_CONSOLE", "true").lower() == "true"

    # ── Base de données ───────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI     = os.environ.get("DATABASE_URL", "sqlite:///ace_evo.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS   = {"connect_args": {"check_same_thread": False}}

    # ── Email ─────────────────────────────────────────────────────────────────
    MAIL_SERVER   = os.environ.get("MAIL_SERVER",   "")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT") or 587)
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

    # ── Historique des tours en direct ──────────────────────────────────────
    LAP_HISTORY_RETENTION_MONTHS = os.environ.get("LAP_HISTORY_RETENTION_MONTHS", "6")

    # ── Personnalisation du panel ─────────────────────────────────────────────
    PANEL_TITLE      = os.environ.get("PANEL_TITLE",      "AC EVO Panel")
    PANEL_BANNER_IMG = os.environ.get("PANEL_BANNER_IMG", "")   # nom de fichier dans media/banner/
    PANEL_LOGO_IMG   = os.environ.get("PANEL_LOGO_IMG",   "")   # nom de fichier dans media/banner/
    PANEL_GITHUB_URL = os.environ.get("PANEL_GITHUB_URL", "https://github.com/Zyphro3D/pannel-ac-evo-server")

    # ── SteamCMD (mise à jour du serveur de jeu) ─────────────────────────────
    # Le mot de passe Steam n'est jamais persisté : saisi à chaque mise à jour via le
    # formulaire (voir container_mgmt.py), donc pas de STEAM_PASSWORD ici.
    STEAMCMD_PATH     = os.environ.get("STEAMCMD_PATH",     "/opt/steamcmd/steamcmd.sh")
    STEAM_USERNAME    = os.environ.get("STEAM_USERNAME",    "anonymous")

    # ── Mode de déploiement ───────────────────────────────────────────────────
    # "docker_split" = panel contrôle le container aceserver (recommandé en prod)
    # "docker"       = Wine dans le même container
    # "native"       = Windows subprocess (legacy)
    DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "docker_split")

    # ── Cookies / Session ─────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY  = True
    SESSION_COOKIE_SAMESITE  = "Lax"
    SESSION_COOKIE_SECURE    = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
