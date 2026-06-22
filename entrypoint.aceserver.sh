#!/bin/bash

SERVER_ID=${SERVER_ID:-1}
SUFFIX=""
if [ "$SERVER_ID" != "1" ]; then SUFFIX="_${SERVER_ID}"; fi
LAUNCH_CONFIG=/aceserver/.launch_config${SUFFIX}.json

# Virtual display — Wine needs it even for headless server executables
# Nettoyer un éventuel lock file laissé par un arrêt brutal
rm -f /tmp/.X99-lock /tmp/.X-unix/X99
Xvfb :99 -screen 0 1024x768x16 -ac &
sleep 1
export DISPLAY=:99

# Initialize Wine prefix on first run
echo "[aceserver] Initializing Wine prefix..."
wine wineboot 2>/dev/null || true
echo "[aceserver] Wine ready."

# If no launch config written by the panel, idle until the panel starts the server
if [ ! -f "$LAUNCH_CONFIG" ]; then
    echo "[aceserver] No launch config found — idling. Use the panel to start the server."
    exec tail -f /dev/null
fi

# Read launch args from the config file written by the panel
SC=$(python3 -c "import json; print(json.load(open('$LAUNCH_CONFIG'))['serverconfig'])")
SD=$(python3 -c "import json; print(json.load(open('$LAUNCH_CONFIG'))['seasondefinition'])")

echo "[aceserver] Starting AssettoCorsaEVOServer.exe..."
cd /aceserver
exec wine AssettoCorsaEVOServer.exe -serverconfig "$SC" -seasondefinition "$SD"
