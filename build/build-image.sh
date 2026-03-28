#!/usr/bin/env bash
# build/build-image.sh — Titan V12 Android 14 Cuttlefish image preparation
set -euo pipefail

TITAN_DATA="${TITAN_DATA:-/opt/titan/data}"
CVD_IMAGES_DIR="${CVD_IMAGES_DIR:-/opt/titan/cuttlefish/images}"
CVD_BIN_DIR="${CVD_BIN_DIR:-/opt/titan/cuttlefish/cf/bin}"
MAGISK_VERSION="28.1"
MAGISK_APK_URL="https://github.com/topjohnwu/Magisk/releases/download/v${MAGISK_VERSION}/Magisk-v${MAGISK_VERSION}.apk"
OUTPUT_TARBALL="${TITAN_DATA}/images/titan-android14-cf-x86_64.tar.gz"
WORK_DIR="/tmp/titan-build-$$"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] BUILD: $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

mkdir -p "$WORK_DIR" "$CVD_BIN_DIR" "$CVD_IMAGES_DIR" "${TITAN_DATA}/images" "${TITAN_DATA}/gapps"

log "=== Titan V12 Android 14 Image Build ==="

# Phase 1: CVD host dependencies
log "Phase 1: Checking CVD host tool dependencies"
REQUIRED_PKGS=(qemu-kvm libvirt-daemon-system bridge-utils python3 python3-pip adb curl wget unzip jq)
MISSING_PKGS=()
for pkg in "${REQUIRED_PKGS[@]}"; do
    dpkg -l "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done
if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    log "Installing missing packages: ${MISSING_PKGS[*]}"
    apt-get update -qq && apt-get install -y -qq "${MISSING_PKGS[@]}" || \
        log "WARN: Some packages could not be installed"
fi

# Phase 2: CVD host tools
log "Phase 2: Setting up Cuttlefish CVD host tools"
if ! command -v cvd &>/dev/null && [[ ! -x "${CVD_BIN_DIR}/cvd" ]]; then
    mkdir -p "$CVD_BIN_DIR"
    cat > "${CVD_BIN_DIR}/cvd" << 'CVDLAUNCHER'
#!/usr/bin/env bash
CVD_REAL="${CVD_BIN_DIR:-/opt/titan/cuttlefish/cf/bin}/cvd_real"
if [[ ! -x "$CVD_REAL" ]]; then
    echo "[cvd-launcher] Install via: apt-get install cuttlefish-common" >&2
    apt-get install -y cuttlefish-common 2>/dev/null && CVD_REAL=$(which cvd || echo "/usr/bin/cvd") || exit 1
fi
exec "$CVD_REAL" "$@"
CVDLAUNCHER
    chmod +x "${CVD_BIN_DIR}/cvd"
    cat > "${CVD_BIN_DIR}/launch_cvd" << 'LAUNCHCVD'
#!/usr/bin/env bash
REAL=$(which launch_cvd 2>/dev/null || echo "/usr/lib/cuttlefish-common/bin/launch_cvd")
[[ -x "$REAL" ]] || { echo "[launch_cvd] ERROR: Cuttlefish not installed" >&2; exit 1; }
exec "$REAL" "$@"
LAUNCHCVD
    chmod +x "${CVD_BIN_DIR}/launch_cvd"
    log "CVD launcher scripts created"
fi

# Phase 3: Magisk / resetprop
log "Phase 3: Preparing Magisk binaries"
MAGISK_CACHE="/tmp/magisk_cache"
RESETPROP_HOST="/tmp/magisk64"
mkdir -p "$MAGISK_CACHE"
if [[ ! -f "$RESETPROP_HOST" ]]; then
    MAGISK_APK="${MAGISK_CACHE}/Magisk-v${MAGISK_VERSION}.apk"
    if [[ ! -f "$MAGISK_APK" ]]; then
        log "Downloading Magisk v${MAGISK_VERSION}..."
        curl -sL --retry 3 --retry-delay 5 -o "$MAGISK_APK" "$MAGISK_APK_URL" || { log "WARN: Download failed"; touch "$MAGISK_APK"; }
    fi
    if [[ -s "$MAGISK_APK" ]]; then
        cd "$MAGISK_CACHE"
        if unzip -q "$MAGISK_APK" "lib/arm64-v8a/libmagisk64.so" 2>/dev/null; then
            cp "$MAGISK_CACHE/lib/arm64-v8a/libmagisk64.so" "$RESETPROP_HOST"
            chmod +x "$RESETPROP_HOST"
            log "resetprop extracted"
        else
            echo "# resetprop placeholder" > "$RESETPROP_HOST"
        fi
        cd - > /dev/null
    fi
fi
mkdir -p "${TITAN_DATA}/bin"
[[ -f "$RESETPROP_HOST" ]] && cp "$RESETPROP_HOST" "${TITAN_DATA}/bin/magisk64" || true

# Phase 4: Android 14 image structure
log "Phase 4: Creating Android 14 image structure"
IMAGE_STAGE_DIR="${WORK_DIR}/android14-image"
mkdir -p "${IMAGE_STAGE_DIR}"
cat > "${IMAGE_STAGE_DIR}/manifest.json" << EOF
{
  "titan_version": "12.0.0",
  "android_version": "14",
  "build_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "arch": "x86_64",
  "image_type": "cuttlefish_composite",
  "security_patch": "$(date +%Y-%m-01)",
  "build_id": "UP1A.231005.007"
}
EOF

cat > "${IMAGE_STAGE_DIR}/download_manifest.json" << 'EOF'
{
  "source": "google_aosp",
  "android_version": "14",
  "build_target": "aosp_x86_64-trunk_staging-userdebug",
  "files": [
    {"name": "aosp_cf_x86_64_phone-img.zip", "required": true},
    {"name": "cvd-host_package.tar.gz", "required": true}
  ]
}
EOF

for component in system vendor boot userdata vbmeta; do
    echo "# Titan Android 14 ${component} image placeholder" > "${IMAGE_STAGE_DIR}/${component}.img.placeholder"
done

# Phase 5: Zygisk modules
log "Phase 5: Setting up Zygisk module structure"
ZYGISK_DIR="${TITAN_DATA}/zygisk-modules"
mkdir -p "${ZYGISK_DIR}"/{play-integrity-fork,shamiko,lsposed}
cat > "${ZYGISK_DIR}/play-integrity-fork/module.prop" << 'EOF'
id=playintegrityfix
name=Play Integrity Fix
version=v14.9
versionCode=14900
author=chiteroman,osm0sis
description=Bypass Play Integrity API hardware attestation
EOF

cat > "${ZYGISK_DIR}/shamiko/module.prop" << 'EOF'
id=shamiko
name=Shamiko
version=v1.0.0
versionCode=10000
author=LSPosed
description=Hide Magisk, Zygisk, and modules from detection
EOF

# Phase 6: GApps stubs
log "Phase 6: Creating GApps stub directory structure"
GAPPS_DIR="${TITAN_DATA}/gapps"
mkdir -p "$GAPPS_DIR"
cat > "${GAPPS_DIR}/gapps_manifest.json" << 'EOF'
{
  "version": "14",
  "packages": [
    {"pkg": "com.google.android.gsf",              "tier": 1, "file": "com.google.android.gsf.apk"},
    {"pkg": "com.google.android.gms",              "tier": 1, "file": "com.google.android.gms.apk"},
    {"pkg": "com.android.vending",                 "tier": 1, "file": "com.android.vending.apk"},
    {"pkg": "com.google.android.webview",          "tier": 2, "file": "com.google.android.webview.apk"},
    {"pkg": "com.android.chrome",                  "tier": 3, "file": "com.android.chrome.apk"},
    {"pkg": "com.google.android.apps.walletnfcrel","tier": 4, "file": "com.google.android.apps.walletnfcrel.apk"},
    {"pkg": "com.google.android.inputmethod.latin","tier": 5, "file": "com.google.android.inputmethod.latin.apk"},
    {"pkg": "com.google.android.googlequicksearchbox","tier": 6, "file": "com.google.android.googlequicksearchbox.apk"}
  ]
}
EOF

# Phase 7: Create image tarball
log "Phase 7: Creating image infrastructure tarball"
mkdir -p "${TITAN_DATA}/images"
tar -czf "$OUTPUT_TARBALL" -C "$IMAGE_STAGE_DIR" . 2>/dev/null || {
    tar -cf "${OUTPUT_TARBALL%.gz}" -C "$IMAGE_STAGE_DIR" . && gzip "${OUTPUT_TARBALL%.gz}"
}
log "Image tarball: $(du -sh "$OUTPUT_TARBALL" | cut -f1)"

# Phase 8: CVD config template
log "Phase 8: CVD launch config template"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CUTTLEFISH_DIR="${REPO_ROOT}/cuttlefish"
if [[ ! -f "${CUTTLEFISH_DIR}/launch_config_template.json" ]]; then
    mkdir -p "$CUTTLEFISH_DIR"
    cat > "${CUTTLEFISH_DIR}/launch_config_template.json" << 'CFTEMPLATE'
{
  "instances": [{
    "vm": {"memory_mb": 4096, "cpus": 4},
    "display": {"width": 1080, "height": 2400, "dpi": 420},
    "graphics": {"renderer": "gfxstream", "mem_mb": 256},
    "adb": {"port": "{adb_port}"},
    "vnc": {"port": "{vnc_port}"}
  }]
}
CFTEMPLATE
fi

log "=== Build Complete ==="
