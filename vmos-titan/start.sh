#!/bin/bash
#
# VMOS Titan — Start Script
# Launch the VMOS Titan Electron application
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check for Electron
if ! command -v electron &> /dev/null && ! [ -d "$SCRIPT_DIR/node_modules/electron" ]; then
    echo "Installing dependencies..."
    cd "$SCRIPT_DIR"
    npm install
fi

# Launch
cd "$SCRIPT_DIR"
npx electron . "$@"
