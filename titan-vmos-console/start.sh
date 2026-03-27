#!/bin/bash
# Start Titan VMOS Console

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure DISPLAY is set for xRDP/VNC environments
export DISPLAY="${DISPLAY:-:10.0}"

# Install dependencies if missing
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start in development mode
exec npx electron --no-sandbox --disable-gpu-sandbox .
