#!/bin/bash

SERVER_ID=${SERVER_ID:-1}
# Valider SERVER_ID : chiffres uniquement pour éviter l'injection de chemin
if ! echo "$SERVER_ID" | grep -qE '^[0-9]+$'; then
    echo "[aceserver] SERVER_ID invalide : '$SERVER_ID' — valeur forcée à 1"
    SERVER_ID=1
fi
SUFFIX=""
if [ "$SERVER_ID" != "1" ]; then SUFFIX="_${SERVER_ID}"; fi
LAUNCH_CONFIG=/aceserver/.launch_config${SUFFIX}.json

# Sanity check: the game server binary is installed via SteamCMD into the
# bind-mounted /aceserver directory — it is never part of the git repo or the
# Docker image, and nothing here reinstalls it automatically. If it's missing
# (fresh setup not finished yet, or files were deleted by mistake), fail with a
# clear, actionable message instead of Wine's cryptic "ShellExecuteEx failed:
# File not found" further down.
EXE=/aceserver/AssettoCorsaEVOServer.exe
if [ ! -f "$EXE" ]; then
    echo "[aceserver] ============================================================"
    echo "[aceserver] ERROR: $EXE not found."
    echo "[aceserver] The ACE EVO Server game files are not installed in ./aceserver."
    echo "[aceserver] This is expected on first setup, and can also happen if the"
    echo "[aceserver] folder content was deleted by mistake — SteamCMD never"
    echo "[aceserver] reinstalls it automatically."
    echo "[aceserver] How to fix:"
    echo "[aceserver]   Log in to the panel as superadmin: it offers to download the server,"
    echo "[aceserver]   you only enter your Steam account (Settings > Server > Update later on)."
    echo "[aceserver] This container will idle and retry every 30s until the file appears —"
    echo "[aceserver] no need to restart it manually once the install is done."
    echo "[aceserver] ============================================================"
    while [ ! -f "$EXE" ]; do
        sleep 30
    done
    echo "[aceserver] $EXE found — continuing startup."
fi

# Virtual display — Wine needs it even for headless server executables
# Nettoyer un éventuel lock file laissé par un arrêt brutal
rm -f /tmp/.X99-lock /tmp/.X-unix/X99
Xvfb :99 -screen 0 1024x768x16 -ac &
# Attendre que Xvfb soit prêt (socket disponible = display actif)
timeout 10 sh -c 'until [ -S /tmp/.X11-unix/X99 ]; do sleep 0.2; done'
export DISPLAY=:99

# Initialize Wine prefix on first run
echo "[aceserver] Initializing Wine prefix..."
wine wineboot 2>/dev/null || true
echo "[aceserver] Wine ready."

# Visual C++ 2022 runtime (msvcp140, vcruntime140...). Wine's own copy is incomplete and the server
# aborts on it ("unimplemented function msvcp140.dll..."). Installed once into the Wine prefix
# (wine_prefix volume): from the package Steam ships with the server when it is complete, otherwise
# from Microsoft. WINEDLLOVERRIDES (Dockerfile) makes Wine use it instead of its builtin DLLs.
VCDLL="$WINEPREFIX/drive_c/windows/system32/msvcp140.dll"
if [ ! -f "$VCDLL" ] || grep -q "Wine builtin DLL" "$VCDLL"; then
    VCREDIST=/aceserver/_CommonRedist/vcredist/2022/VC_redist.x64.exe
    if [ ! -f "$VCREDIST" ]; then
        VCREDIST=/tmp/vc_redist.x64.exe
        echo "[aceserver] Downloading the Visual C++ 2022 runtime (Microsoft)..."
        python3 -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
            https://aka.ms/vs/17/release/vc_redist.x64.exe "$VCREDIST" || VCREDIST=""
    fi
    if [ -n "$VCREDIST" ]; then
        echo "[aceserver] Installing the Visual C++ 2022 runtime into Wine..."
        wine "$VCREDIST" /install /quiet /norestart 2>/dev/null || true
        wineserver -w
    fi
    if grep -q "Wine builtin DLL" "$VCDLL" 2>/dev/null; then
        echo "[aceserver] WARNING: Visual C++ runtime not installed, the server may crash at startup."
    else
        echo "[aceserver] Visual C++ 2022 runtime ready."
    fi
fi

# If no launch config written by the panel, idle until the panel starts the server
if [ ! -f "$LAUNCH_CONFIG" ]; then
    echo "[aceserver] No launch config found — idling. Use the panel to start the server."
    exec tail -f /dev/null
fi

# Read launch args from the config file written by the panel (path passed as arg, not interpolated)
SC=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['serverconfig'])" "$LAUNCH_CONFIG")
SD=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['seasondefinition'])" "$LAUNCH_CONFIG")

# Arguments facultatifs (ex. -log_debug gameplay), un par ligne ; absents = lancement inchangé
mapfile -t EXTRA < <(python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1])).get('extra_args', [])))" "$LAUNCH_CONFIG" | grep .)

echo "[aceserver] Starting AssettoCorsaEVOServer.exe..."
cd /aceserver
exec wine AssettoCorsaEVOServer.exe -serverconfig "$SC" -seasondefinition "$SD" ${EXTRA[@]+"${EXTRA[@]}"}
