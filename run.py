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

    print("=" * 52)
    print(f"  AC EVO Server Panel  v{_version}")
    print("=" * 52)
    print(f"  Local   : {scheme}://127.0.0.1:{port}")
    print(f"  Réseau  : {scheme}://{local_ip}:{port}")
    print(f"  Logs    : logs/app.log")
    print("=" * 52)
    print("  CTRL+C pour arrêter")
    print()

    if ssl_cert and ssl_key:
        # gunicorn gère nativement les certificats SSL
        os.execvp("gunicorn", [
            "gunicorn",
            "--bind",    f"{host}:{port}",
            "--workers", "4",
            "--certfile", ssl_cert,
            "--keyfile",  ssl_key,
            "--access-logfile", "-",
            "run:app",
        ])
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
