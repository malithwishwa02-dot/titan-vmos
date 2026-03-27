#!/bin/bash
# Build script for Titan VMOS Console

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_TYPE="${1:-all}"

echo "========================================"
echo " Titan VMOS Console — Build Script"
echo "========================================"
echo ""

cd "$SCRIPT_DIR"

# Check dependencies
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is required. Install with: sudo apt install nodejs npm"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "Error: npm is required. Install with: sudo apt install npm"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

case "$BUILD_TYPE" in
    "deb")
        echo "Building DEB package..."
        npm run build:deb
        ;;
    "appimage")
        echo "Building AppImage..."
        npm run build:appimage
        ;;
    "win"|"windows")
        echo "Building Windows installer..."
        npm run build:win
        ;;
    "all")
        echo "Building all packages..."
        npm run build:all
        ;;
    "dev"|"start")
        echo "Starting in development mode..."
        npm start
        ;;
    *)
        echo "Usage: $0 [deb|appimage|win|all|dev]"
        echo ""
        echo "  deb      - Build Debian package"
        echo "  appimage - Build AppImage"
        echo "  win      - Build Windows installer"
        echo "  all      - Build all packages"
        echo "  dev      - Start in development mode"
        exit 1
        ;;
esac

echo ""
echo "Build complete! Check the dist/ directory for output."
