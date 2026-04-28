#!/bin/bash
set -e

# Virtual display required by Wine even for headless server executables
Xvfb :99 -screen 0 1024x768x16 -ac &
export DISPLAY=:99

# Initialize Wine prefix on first run
if [ ! -d "$WINEPREFIX/drive_c" ]; then
    echo "[entrypoint] Initializing Wine prefix..."
    wine wineboot --init 2>/dev/null || true
    sleep 3
    echo "[entrypoint] Wine prefix ready."
fi

exec python run.py
