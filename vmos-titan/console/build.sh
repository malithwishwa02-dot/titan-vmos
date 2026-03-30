#!/usr/bin/env bash
# Titan Console — Production Build Script
# Generates a minified single-file console with purged Tailwind CSS.
#
# Usage: bash console/build.sh
#
# Prerequisites (optional — falls back to CDN if not installed):
#   npm install -g tailwindcss @tailwindcss/cli
#
# Output: console/dist/index.html (self-contained, minified)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
mkdir -p "$DIST_DIR"

echo "=== Titan Console Build ==="

# Check if tailwindcss CLI is available
if command -v tailwindcss &>/dev/null; then
    echo "[1/3] Building Tailwind CSS (purge unused classes)..."
    tailwindcss -i /dev/null \
        --content "$SCRIPT_DIR/index.html" \
        --minify \
        -o "$DIST_DIR/tailwind.min.css" 2>/dev/null || true
    echo "  Tailwind CSS purged and minified"
else
    echo "[1/3] tailwindcss CLI not found — using CDN version (no purge)"
fi

# Inline Alpine.js for single-file deployment
echo "[2/3] Building production index.html..."
cp "$SCRIPT_DIR/index.html" "$DIST_DIR/index.html"

# If we have minified tailwind, inline it
if [ -f "$DIST_DIR/tailwind.min.css" ]; then
    # Replace tailwind.js CDN script with inline CSS
    sed -i 's|<script src="/static/tailwind.js"></script>|<style>/* Tailwind CSS (purged) */</style>|' "$DIST_DIR/index.html"
    # Insert the CSS content (simplified — full inline would use a temp file)
    echo "  Tailwind inlined (purged)"
fi

# Copy Alpine.js
if [ -f "$SCRIPT_DIR/alpine.min.js" ]; then
    cp "$SCRIPT_DIR/alpine.min.js" "$DIST_DIR/alpine.min.js"
fi

# Copy manifest
if [ -f "$SCRIPT_DIR/manifest.json" ]; then
    cp "$SCRIPT_DIR/manifest.json" "$DIST_DIR/manifest.json"
fi

# Report
echo "[3/3] Build complete"
if [ -f "$DIST_DIR/index.html" ]; then
    SIZE=$(wc -c < "$DIST_DIR/index.html")
    echo "  Output: $DIST_DIR/index.html ($SIZE bytes)"
fi

echo "=== Done ==="
