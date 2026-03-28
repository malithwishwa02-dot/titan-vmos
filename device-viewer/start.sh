#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "╔══════════════════════════════════════╗"
echo "║   Cuttlefish Desktop (Desktop-Only)  ║"
echo "╚══════════════════════════════════════╝"

TITAN_API_PORT="${TITAN_API_PORT:-8080}"
TITAN_DIR="${TITAN_DIR:-/opt/titan}"

# ── Source .env ────────────────────────────────────────────────────────
if [[ -f "${TITAN_DIR}/.env" ]]; then
    set -a
    source "${TITAN_DIR}/.env"
    set +a
fi

# ── Check dependencies ─────────────────────────────────────────────────
missing=()
command -v adb      >/dev/null 2>&1 || missing+=("adb")
command -v scrcpy   >/dev/null 2>&1 || missing+=("scrcpy")
command -v xdotool  >/dev/null 2>&1 || missing+=("xdotool")
command -v node     >/dev/null 2>&1 || missing+=("node")
command -v npm      >/dev/null 2>&1 || missing+=("npm")

if [ ${#missing[@]} -gt 0 ]; then
  echo "ERROR: Missing dependencies: ${missing[*]}"
  echo "Install them and try again."
  exit 1
fi

# ── Ensure Titan API is running (desktop-only: local backend) ─────────
echo "Checking Titan API on 127.0.0.1:${TITAN_API_PORT}..."
if ! curl -sf --connect-timeout 2 "http://127.0.0.1:${TITAN_API_PORT}/health/live" >/dev/null 2>&1; then
    echo "Titan API not running. Starting titan-api service..."
    systemctl start titan-api 2>/dev/null || true
    # Wait up to 10s for API to come online
    for i in $(seq 1 10); do
        sleep 1
        if curl -sf --connect-timeout 1 "http://127.0.0.1:${TITAN_API_PORT}/health/live" >/dev/null 2>&1; then
            echo "Titan API online."
            break
        fi
        [[ $i -eq 10 ]] && echo "WARNING: Titan API may not be ready yet."
    done
else
    echo "Titan API online."
fi

# ── Check device ───────────────────────────────────────────────────────
if ! adb devices 2>/dev/null | grep -q "device$"; then
  echo "WARNING: No Android device detected via ADB."
  echo "Make sure Cuttlefish is running (cvd start)."
fi

# ── Install node_modules if needed ─────────────────────────────────────
if [ ! -d node_modules ]; then
  echo "Installing dependencies…"
  npm install
fi

# ── Launch ─────────────────────────────────────────────────────────────
echo "Launching Cuttlefish Desktop (desktop-only mode)..."
exec npx electron --no-sandbox --disable-gpu-sandbox .
