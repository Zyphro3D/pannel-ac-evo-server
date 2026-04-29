#!/bin/bash
set -e

# Virtual display required by Wine even for headless server executables
Xvfb :99 -screen 0 1024x768x16 -ac &
sleep 1

export DISPLAY=:99

# Re-initialize the Wine prefix when the installed Wine version changes.
# This handles the case where docker compose up --build installs a newer Wine
# while the wine_prefix volume still holds a prefix from the previous version.
WINE_PKG_VER=$(dpkg -s winehq-stable 2>/dev/null | awk '/^Version:/{print $2}' || echo "unknown")
WINE_VER_TAG="$WINEPREFIX/.panel_wine_version"

needs_init=false
if [ ! -f "$WINEPREFIX/system.reg" ]; then
    needs_init=true
elif [ ! -f "$WINE_VER_TAG" ] || [ "$(cat "$WINE_VER_TAG")" != "$WINE_PKG_VER" ]; then
    echo "[entrypoint] Wine version changed to $WINE_PKG_VER — reinitializing prefix..."
    rm -rf "$WINEPREFIX"
    needs_init=true
fi

if $needs_init; then
    echo "[entrypoint] Initializing Wine prefix ($WINE_PKG_VER)..."
    wine wineboot --init 2>&1 | grep -v "^$" || true
    echo "$WINE_PKG_VER" > "$WINE_VER_TAG"
    echo "[entrypoint] Wine prefix ready."
fi

exec python run.py
