#!/bin/bash
set -e

# Virtual display required by Wine even for headless server executables
Xvfb :99 -screen 0 1024x768x16 -ac &
sleep 1

export DISPLAY=:99

# Initialize Wine prefix once (skipped on subsequent restarts thanks to the wine_prefix volume)
# wine wineboot --init is safe at container runtime (unlike docker build which has seccomp restrictions)
if [ ! -f "$WINEPREFIX/system.reg" ]; then
    echo "[entrypoint] First run — initializing Wine prefix (may take ~30s)..."
    wine wineboot --init 2>&1 | grep -v "^$" || true
    echo "[entrypoint] Wine prefix ready."
fi

exec python run.py
