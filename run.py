import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Logging vers fichier rotatif (avant create_app) ──────────────────────────
_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
_file_handler = RotatingFileHandler(
    _log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])

_version = (Path(__file__).parent / "VERSION").read_text().strip()

from app import create_app

app = create_app()

if __name__ == "__main__":
    import socket

    host     = "0.0.0.0"
    port     = int(os.environ.get("PANEL_PORT", 4300))
    ssl_cert = os.environ.get("SSL_CERTFILE", "").strip()
    ssl_key  = os.environ.get("SSL_KEYFILE", "").strip()

    local_ip = socket.gethostbyname(socket.gethostname())
    scheme   = "https" if ssl_cert and ssl_key else "http"

    _log = logging.getLogger("panel.startup")
    _log.info("=" * 52)
    _log.info("  AC EVO Server Panel  v%s", _version)
    _log.info("=" * 52)
    _log.info("  Local   : %s://127.0.0.1:%s", scheme, port)
    _log.info("  Réseau  : %s://%s:%s", scheme, local_ip, port)
    _log.info("  Logs    : logs/app.log")
    _log.info("=" * 52)
    _log.info("  CTRL+C pour arrêter")

    if ssl_cert and ssl_key:
        # gunicorn gère nativement les certificats SSL
        os.execvp("gunicorn", [
            "gunicorn",
            "--bind",    f"{host}:{port}",
            "--workers", "1",   # single process — global state + background threads require it
            "--threads", "8",
            "--certfile", ssl_cert,
            "--keyfile",  ssl_key,
            "--access-logfile", "-",
            "run:app",
        ])
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
