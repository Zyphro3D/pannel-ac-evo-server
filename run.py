import logging
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
    from waitress import serve
    import socket

    host = "0.0.0.0"
    port = 4300

    local_ip = socket.gethostbyname(socket.gethostname())

    print("=" * 52)
    print(f"  AC EVO Server Panel  v{_version}")
    print("=" * 52)
    print(f"  Local   : http://127.0.0.1:{port}")
    print(f"  Réseau  : http://{local_ip}:{port}")
    print(f"  Threads : 8")
    print(f"  Logs    : logs/app.log")
    print("=" * 52)
    print("  CTRL+C pour arrêter")
    print()

    serve(app, host=host, port=port, threads=8)
