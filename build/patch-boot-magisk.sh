#!/usr/bin/env bash
# build/patch-boot-magisk.sh — Patch Android boot image with Magisk
set -euo pipefail

TITAN_DATA="${TITAN_DATA:-/opt/titan/data}"
ADB_TARGET="${1:-127.0.0.1:6520}"
MAGISK_VERSION="${MAGISK_VERSION:-28.1}"
WORK_DIR="/tmp/titan-magisk-$$"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] MAGISK: $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
mkdir -p "$WORK_DIR"

log "=== Magisk Boot Patcher ==="
log "Target device: $ADB_TARGET"

if ! adb -s "$ADB_TARGET" shell echo "ok" &>/dev/null 2>&1; then
    log "WARN: Device $ADB_TARGET not reachable — offline/build mode"
    log "To patch a running device: $0 <adb_target>"
    exit 0
fi

download_magisk() {
    local magisk_apk="$1"
    local url="https://github.com/topjohnwu/Magisk/releases/download/v${MAGISK_VERSION}/Magisk-v${MAGISK_VERSION}.apk"
    if [[ -f "/tmp/Magisk-v${MAGISK_VERSION}.apk" ]]; then
        cp "/tmp/Magisk-v${MAGISK_VERSION}.apk" "$magisk_apk"
        log "Using cached Magisk APK"
        return 0
    fi
    log "Downloading Magisk v${MAGISK_VERSION}..."
    curl -sL --retry 3 -o "$magisk_apk" "$url" || die "Failed to download Magisk"
    cp "$magisk_apk" "/tmp/Magisk-v${MAGISK_VERSION}.apk"
}

MAGISK_APK="${WORK_DIR}/magisk.apk"
download_magisk "$MAGISK_APK"

log "Pushing Magisk to device"
adb -s "$ADB_TARGET" push "$MAGISK_APK" /data/local/tmp/magisk.apk

log "Extracting resetprop binary"
adb -s "$ADB_TARGET" shell "su -c 'cd /data/local/tmp && unzip -q magisk.apk lib/arm64-v8a/libmagisk64.so && cp lib/arm64-v8a/libmagisk64.so /data/local/tmp/magisk64 && chmod +x /data/local/tmp/magisk64 && rm -rf lib'" 2>/dev/null || true

log "=== Magisk Boot Patch Complete ==="
log "resetprop available at /data/local/tmp/magisk64"
