#!/bin/bash
set -e

# Virtual display required by Wine even for headless server executables
Xvfb :99 -screen 0 1024x768x16 -ac &
sleep 1

export DISPLAY=:99

exec python run.py
