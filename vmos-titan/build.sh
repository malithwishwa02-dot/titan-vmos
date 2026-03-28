#!/bin/bash
#
# VMOS Titan v2.0 — Build & Install Script
# Builds Linux desktop packages (AppImage, DEB) and localhost ops-web
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${CYAN}[*]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  VMOS Titan v2.0 — Linux Build & Install"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Architecture Detection ─────────────────────────────────────────
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ELECTRON_ARCH="x64" ;;
  aarch64) ELECTRON_ARCH="arm64" ;;
  armv7l)  ELECTRON_ARCH="armv7l" ;;
  *)       fail "Unsupported architecture: $ARCH" ;;
esac
ok "Architecture: $ARCH → electron-builder target: $ELECTRON_ARCH"

# ── Node.js Check ──────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  fail "Node.js not found. Install Node.js 18+ first:\n  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
fi

NODE_MAJOR=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_MAJOR" -lt 18 ]; then
  fail "Node.js 18+ required. Current: $(node -v)"
fi
ok "Node.js $(node -v) — npm $(npm -v)"

# ── Build Mode ─────────────────────────────────────────────────────
BUILD_MODE="${1:-all}"
case "$BUILD_MODE" in
  desktop|electron) BUILD_DESKTOP=1; BUILD_OPSWEB=0 ;;
  opsweb|web)       BUILD_DESKTOP=0; BUILD_OPSWEB=1 ;;
  all)              BUILD_DESKTOP=1; BUILD_OPSWEB=1 ;;
  clean)
    log "Cleaning build artifacts..."
    rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/node_modules/.cache" "$SCRIPT_DIR/ops-web/node_modules"
    ok "Clean complete."
    exit 0
    ;;
  *)
    echo "Usage: $0 [desktop|opsweb|all|clean]"
    echo "  desktop  — Build Electron desktop app (AppImage + DEB)"
    echo "  opsweb   — Build localhost ops-web server"
    echo "  all      — Build both (default)"
    echo "  clean    — Remove build artifacts"
    exit 0
    ;;
esac

# ── Dependency Install ─────────────────────────────────────────────
log "Installing desktop app dependencies..."
npm install --no-audit --no-fund 2>&1 | tail -3
ok "Desktop dependencies installed"

# ── Build Ops-Web ──────────────────────────────────────────────────
if [ "$BUILD_OPSWEB" -eq 1 ]; then
  echo ""
  log "Building ops-web localhost server..."
  OPS_DIR="$SCRIPT_DIR/ops-web"
  if [ -d "$OPS_DIR" ]; then
    cd "$OPS_DIR"
    npm install --no-audit --no-fund 2>&1 | tail -3
    ok "ops-web dependencies installed"
    cd "$SCRIPT_DIR"
  else
    warn "ops-web directory not found — skipping"
  fi
fi

# ── Build Desktop App ─────────────────────────────────────────────
if [ "$BUILD_DESKTOP" -eq 1 ]; then
  echo ""
  log "Building Linux desktop packages..."

  # Ensure assets exist
  for f in assets/icon.png assets/tray.png; do
    if [ ! -f "$f" ]; then
      warn "Missing $f — build may fail or produce generic icons"
    fi
  done

  # Build AppImage + DEB
  npx electron-builder --linux AppImage deb --$ELECTRON_ARCH 2>&1 | grep -E '(Building|packaging|•|✓|electron-builder)' || true
  echo ""

  if [ -d "$SCRIPT_DIR/dist" ]; then
    ok "Desktop build complete!"
    echo ""
    echo "  Output files:"
    ls -lh "$SCRIPT_DIR/dist/"*.AppImage "$SCRIPT_DIR/dist/"*.deb 2>/dev/null | awk '{print "    " $NF " (" $5 ")"}'
  else
    warn "dist/ directory not found — check build output above"
  fi
fi

# ── Install Desktop Entry ──────────────────────────────────────────
if [ "$BUILD_DESKTOP" -eq 1 ]; then
  echo ""
  log "Installing desktop entry..."
  DESKTOP_FILE="$HOME/.local/share/applications/vmos-titan.desktop"
  mkdir -p "$(dirname "$DESKTOP_FILE")"
  APPIMAGE_PATH=$(ls "$SCRIPT_DIR/dist/"*.AppImage 2>/dev/null | head -1)
  EXEC_CMD="${APPIMAGE_PATH:-$SCRIPT_DIR/start.sh}"
  cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=VMOS Titan
Comment=VMOS Pro Cloud Device Management with Genesis Studio
Exec=$EXEC_CMD --no-sandbox %U
Icon=$SCRIPT_DIR/assets/icon.png
Type=Application
Categories=Development;Utility;
Terminal=false
StartupWMClass=VMOS Titan
Keywords=android;vmos;cloud;genesis;antidetect;device
EOF
  chmod +x "$DESKTOP_FILE" 2>/dev/null || true
  ok "Desktop entry installed: $DESKTOP_FILE"
fi

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Build Complete!"
echo "═══════════════════════════════════════════════════════════"
echo ""
if [ "$BUILD_DESKTOP" -eq 1 ]; then
  echo "  Desktop App:"
  echo "    Run dev:  npm start"
  echo "    Package:  ls dist/*.AppImage dist/*.deb"
  echo ""
fi
if [ "$BUILD_OPSWEB" -eq 1 ]; then
  echo "  Ops-Web (localhost):"
  echo "    Run:   cd ops-web && npm start"
  echo "    URL:   http://localhost:3000"
  echo ""
fi
