#!/usr/bin/env bash
# Titan Console — Post-installation script
# Runs after .deb install to set up venv, .env, data dirs, and systemd service.
#
# Usage (automatic via dpkg): runs as root after package install
# Usage (manual): sudo bash /opt/titan-console/scripts/postinstall.sh

set -euo pipefail

INSTALL_DIR="${TITAN_INSTALL_DIR:-/opt/titan-console/resources}"
DATA_DIR="${TITAN_DATA:-/opt/titan/data}"
VENV_DIR="${TITAN_VENV:-/opt/titan/venv}"
ENV_FILE="$DATA_DIR/.env"
SERVICE_NAME="titan-console"
API_PORT="${TITAN_API_PORT:-8080}"

log() { echo "[titan-postinstall] $*"; }

# ─── 1. Data directories ─────────────────────────────────────────────
log "Creating data directories..."
mkdir -p "$DATA_DIR"/{devices,profiles,config,forge_gallery,gapps,logs}
chmod 755 "$DATA_DIR"

# ─── 2. Python virtual environment ───────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    log "ERROR: Python 3.10+ not found. Install python3 >= 3.10 and re-run."
    exit 1
fi

if [ ! -f "$VENV_DIR/bin/python3" ]; then
    log "Creating Python venv at $VENV_DIR..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

log "Installing/upgrading Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q 2>/dev/null || true

REQ_FILE="$INSTALL_DIR/server/requirements.txt"
if [ -f "$REQ_FILE" ]; then
    "$VENV_DIR/bin/pip" install -r "$REQ_FILE" -q
    log "Dependencies installed from $REQ_FILE"
else
    # Minimal fallback
    "$VENV_DIR/bin/pip" install fastapi uvicorn[standard] httpx pydantic aiofiles -q
    log "Installed minimal dependencies (requirements.txt not found)"
fi

# ─── 3. Seed .env from template ──────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    TEMPLATE="$INSTALL_DIR/.env.example"
    if [ -f "$TEMPLATE" ]; then
        cp "$TEMPLATE" "$ENV_FILE"
        # Generate a unique API secret
        SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
        sed -i "s|^TITAN_API_SECRET=.*|TITAN_API_SECRET=$SECRET|" "$ENV_FILE"
        sed -i "s|^TITAN_DATA=.*|TITAN_DATA=$DATA_DIR|" "$ENV_FILE"
        log "Created $ENV_FILE with unique API secret"
    else
        cat > "$ENV_FILE" <<EOF
TITAN_API_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
TITAN_API_PORT=$API_PORT
TITAN_DATA=$DATA_DIR
CVD_BIN_DIR=/opt/titan/cuttlefish/cf/bin
CVD_HOME_BASE=/opt/titan/cuttlefish
CVD_IMAGES_DIR=/opt/titan/cuttlefish/images
EOF
        log "Created minimal $ENV_FILE"
    fi
fi
chmod 600 "$ENV_FILE"

# ─── 4. Systemd service ──────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ ! -f "$SERVICE_FILE" ] || [ "${TITAN_FORCE_SERVICE:-0}" = "1" ]; then
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Titan V11.3 Cuttlefish Android Console API
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/server
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$INSTALL_DIR/server:$INSTALL_DIR/core:/opt/titan/core
ExecStart=$VENV_DIR/bin/uvicorn titan_api:app --host 127.0.0.1 --port $API_PORT --workers 1
Restart=on-failure
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" 2>/dev/null || true
    log "Systemd service created and enabled: $SERVICE_NAME"
else
    log "Systemd service already exists, skipping"
fi

# ─── 5. Permissions ──────────────────────────────────────────────────
# Ensure adb is accessible
if command -v adb &>/dev/null; then
    adb start-server 2>/dev/null || true
fi

# ─── 6. Summary ──────────────────────────────────────────────────────
log "════════════════════════════════════════════════════"
log "Titan Console post-install complete!"
log "  Data:    $DATA_DIR"
log "  Venv:    $VENV_DIR"
log "  Env:     $ENV_FILE"
log "  Service: $SERVICE_NAME"
log ""
log "Start the API:  systemctl start $SERVICE_NAME"
log "Open console:   http://127.0.0.1:$API_PORT"
log "════════════════════════════════════════════════════"
