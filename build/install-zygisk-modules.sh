#!/usr/bin/env bash
# build/install-zygisk-modules.sh — Install Zygisk modules for Play Integrity spoofing
set -euo pipefail

TITAN_DATA="${TITAN_DATA:-/opt/titan/data}"
ZYGISK_DIR="${TITAN_DATA}/zygisk-modules"
MODULES_INSTALL_DIR="${TITAN_DATA}/modules/active"
ADB_TARGET="${1:-127.0.0.1:6520}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ZYGISK: $*"; }

log "=== Zygisk Module Installer ==="
log "Target device: $ADB_TARGET"

mkdir -p "$MODULES_INSTALL_DIR"

check_adb() {
    adb -s "$ADB_TARGET" shell echo "connected" &>/dev/null
}

install_play_integrity_module() {
    local module_zip="/tmp/PlayIntegrityFix_$(date +%s).zip"
    log "Installing Play Integrity Fix module"
    local LATEST_URL
    LATEST_URL=$(curl -sf "https://api.github.com/repos/chiteroman/PlayIntegrityFix/releases/latest" 2>/dev/null | \
        python3 -c "import sys,json; data=json.load(sys.stdin); [print(a['browser_download_url']) for a in data.get('assets',[]) if a['name'].endswith('.zip')]" 2>/dev/null | head -1 || echo "")
    if [[ -n "$LATEST_URL" ]]; then
        curl -sL --retry 3 -o "$module_zip" "$LATEST_URL" || { log "WARN: Download failed"; return 0; }
        if check_adb 2>/dev/null; then
            adb -s "$ADB_TARGET" push "$module_zip" /data/local/tmp/PlayIntegrityFix.zip
            adb -s "$ADB_TARGET" shell "mkdir -p /data/adb/modules/playintegrityfix && cd /data/adb/modules/playintegrityfix && unzip -oq /data/local/tmp/PlayIntegrityFix.zip && rm /data/local/tmp/PlayIntegrityFix.zip"
            log "PlayIntegrityFix installed on device"
        else
            cp "$module_zip" "${MODULES_INSTALL_DIR}/PlayIntegrityFix.zip"
        fi
        rm -f "$module_zip"
    else
        log "WARN: Could not determine latest PlayIntegrityFix URL"
    fi
}

configure_pi_props() {
    check_adb 2>/dev/null || { log "ADB not available"; return 0; }
    adb -s "$ADB_TARGET" shell "su -c 'id'" &>/dev/null || { log "WARN: Root not available"; return 0; }
    adb -s "$ADB_TARGET" shell "su -c '/data/local/tmp/magisk64 resetprop ro.boot.verifiedbootstate green'" 2>/dev/null || true
    adb -s "$ADB_TARGET" shell "su -c '/data/local/tmp/magisk64 resetprop ro.boot.flash.locked 1'" 2>/dev/null || true
    log "Play Integrity props configured"
}

install_play_integrity_module
configure_pi_props

log "=== Zygisk Module Installation Complete ==="
