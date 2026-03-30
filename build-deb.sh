#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Titan VMOS — Production .deb Package Builder
#
# Assembles the titan-vmos Debian package with FULL Cuttlefish Android 14
# pre-integration: VM images, CVD host tools, GApps APKs, Magisk/Zygisk
# modules, keybox, and all core/server/console code.
#
# Usage:
#   ./build-deb.sh                     # Full pre-configured (~4-6 GB)
#   ./build-deb.sh --code-only         # Code only, no images (~5 MB)
#   ./build-deb.sh --skip-image-build  # Bundle existing local images
#   ./build-deb.sh --local-images      # Use images from CVD_IMAGES_DIR
#
# Output: dist/titan-vmos_13.0.0_amd64.deb
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}"
VERSION="13.0.0"
PACKAGE="titan-vmos"
ARCH="amd64"
INSTALL_PREFIX="/opt/titan"

STAGING="${SRC_DIR}/dist/.staging"
DEB_OUT="${SRC_DIR}/dist/${PACKAGE}_${VERSION}_${ARCH}.deb"

CODE_ONLY=0
SKIP_IMAGE_BUILD=0
USE_LOCAL_IMAGES=0

# Default paths for local Cuttlefish installation
LOCAL_CVD_IMAGES="${CVD_IMAGES_DIR:-/opt/titan/cuttlefish/images}"
LOCAL_CVD_HOST="${CVD_BIN_DIR:-/opt/titan/cuttlefish/cf/bin}"
LOCAL_CVD_HOST_BASE="$(dirname "${LOCAL_CVD_HOST}")"
LOCAL_GAPPS="${TITAN_DATA:-/opt/titan/data}/gapps"
LOCAL_KEYBOX="${TITAN_DATA:-/opt/titan/data}/keybox.xml"
LOCAL_KEYBOX_DIR="${TITAN_DATA:-/opt/titan/data}/keybox"

for arg in "$@"; do
    case "$arg" in
        --code-only)         CODE_ONLY=1 ;;
        --skip-image-build)  SKIP_IMAGE_BUILD=1; USE_LOCAL_IMAGES=1 ;;
        --local-images)      USE_LOCAL_IMAGES=1 ;;
        --help|-h)
            echo "Usage: $0 [--code-only] [--skip-image-build] [--local-images]"
            echo "  --code-only          Build code-only package (~5 MB, no images)"
            echo "  --skip-image-build   Bundle existing local images without rebuilding"
            echo "  --local-images       Use images from CVD_IMAGES_DIR directly"
            exit 0
            ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

BUILD_START=$(date +%s)
echo "═══════════════════════════════════════════════════════════"
echo "  Titan VMOS V${VERSION} — .deb Package Builder"
echo "  Mode: $(if [[ $CODE_ONLY -eq 1 ]]; then echo 'CODE-ONLY'; else echo 'FULL PRE-CONFIGURED'; fi)"
echo "  Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "═══════════════════════════════════════════════════════════"

# ─── Clean staging ────────────────────────────────────────────────────
rm -rf "${STAGING}"
mkdir -p "${STAGING}/DEBIAN"
mkdir -p "${STAGING}${INSTALL_PREFIX}"
mkdir -p "${SRC_DIR}/dist"

# ═══════════════════════════════════════════════════════════════════════
# STEP 0: Build/acquire Cuttlefish images
# ═══════════════════════════════════════════════════════════════════════
IMAGE_TARBALL="/opt/titan/images/titan-android14-cf-x86_64.tar.gz"

if [[ $CODE_ONLY -eq 0 ]]; then
    # Try to detect local images first
    if [[ $USE_LOCAL_IMAGES -eq 1 ]] || [[ $SKIP_IMAGE_BUILD -eq 1 ]]; then
        echo ""
        echo "[0/10] Detecting local Cuttlefish images..."

        # Verify local images exist
        if [[ -f "${LOCAL_CVD_IMAGES}/boot.img" ]] || [[ -f "${LOCAL_CVD_IMAGES}/super.img" ]]; then
            echo "  ✓ Found VM images at: ${LOCAL_CVD_IMAGES}"
            echo "    Images: $(ls -1 "${LOCAL_CVD_IMAGES}"/*.img 2>/dev/null | wc -l) .img files"
            echo "    Size:   $(du -sh "${LOCAL_CVD_IMAGES}" | awk '{print $1}')"
        else
            echo "  ✗ No images found at ${LOCAL_CVD_IMAGES}"
            echo "    Set CVD_IMAGES_DIR or use --code-only"
            exit 1
        fi

        # Verify host tools
        if [[ -f "${LOCAL_CVD_HOST}/launch_cvd" ]] || [[ -f "${LOCAL_CVD_HOST}/cvd_internal_start" ]]; then
            echo "  ✓ Found CVD host tools at: ${LOCAL_CVD_HOST}"
        else
            echo "  ✗ CVD host tools not found at ${LOCAL_CVD_HOST}"
            echo "    Set CVD_BIN_DIR or install cuttlefish-common"
            exit 1
        fi
    elif [[ $SKIP_IMAGE_BUILD -eq 0 ]]; then
        echo ""
        echo "[0/10] Building Android 14 images (GApps + Magisk + Zygisk)..."
        if [[ -f "${SRC_DIR}/build/build-image.sh" ]]; then
            bash "${SRC_DIR}/build/build-image.sh" --local "${LOCAL_CVD_IMAGES}" || {
                echo ""
                echo "WARNING: Image build failed. Falling back to local image bundling."
                USE_LOCAL_IMAGES=1
            }
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 1: DEBIAN control files
# ═══════════════════════════════════════════════════════════════════════
echo "[1/10] Writing DEBIAN control files..."

cp "${SRC_DIR}/debian/control"   "${STAGING}/DEBIAN/control"
cp "${SRC_DIR}/debian/preinst"   "${STAGING}/DEBIAN/preinst"
cp "${SRC_DIR}/debian/postinst"  "${STAGING}/DEBIAN/postinst"
cp "${SRC_DIR}/debian/prerm"     "${STAGING}/DEBIAN/prerm"
cp "${SRC_DIR}/debian/postrm"    "${STAGING}/DEBIAN/postrm"
cp "${SRC_DIR}/debian/conffiles" "${STAGING}/DEBIAN/conffiles"

chmod 755 "${STAGING}/DEBIAN/preinst"
chmod 755 "${STAGING}/DEBIAN/postinst"
chmod 755 "${STAGING}/DEBIAN/prerm"
chmod 755 "${STAGING}/DEBIAN/postrm"
chmod 644 "${STAGING}/DEBIAN/control"
chmod 644 "${STAGING}/DEBIAN/conffiles"

# ═══════════════════════════════════════════════════════════════════════
# STEP 2: Core application files → /opt/titan/
# ═══════════════════════════════════════════════════════════════════════
echo "[2/10] Copying core application..."

# Python vmos_titan package (core + api)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='_deprecated' \
    "${SRC_DIR}/vmos-titan/vmos_titan/" "${STAGING}${INSTALL_PREFIX}/vmos_titan/"

# Wallet module
if [[ -d "${SRC_DIR}/wallet" ]]; then
    rsync -a --exclude='__pycache__' --exclude='*.pyc' \
        "${SRC_DIR}/wallet/" "${STAGING}${INSTALL_PREFIX}/wallet/"
fi

# FastAPI server (kept for backward compat - points to vmos_titan/api)
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='_deprecated' \
    "${SRC_DIR}/vmos-titan/vmos_titan/api/" "${STAGING}${INSTALL_PREFIX}/server/"

# Web console
rsync -a --exclude='*.bak' --exclude='*.bak2' --exclude='node_modules' \
    "${SRC_DIR}/vmos-titan/console/" "${STAGING}${INSTALL_PREFIX}/console/"

# Build scripts
rsync -a "${SRC_DIR}/build/" "${STAGING}${INSTALL_PREFIX}/build/"
chmod +x "${STAGING}${INSTALL_PREFIX}/build/"*.sh 2>/dev/null || true

# Cuttlefish config templates
rsync -a "${SRC_DIR}/cuttlefish/" "${STAGING}${INSTALL_PREFIX}/cuttlefish_templates/"

# Project metadata
for f in pyproject.toml requirements.txt README.md CHANGELOG.md AGENTS.md; do
    [[ -f "${SRC_DIR}/${f}" ]] && cp "${SRC_DIR}/${f}" "${STAGING}${INSTALL_PREFIX}/"
done

# .env.example (template — postinst seeds .env from this)
[[ -f "${SRC_DIR}/.env.example" ]] && cp "${SRC_DIR}/.env.example" "${STAGING}${INSTALL_PREFIX}/"

# ═══════════════════════════════════════════════════════════════════════
# STEP 3: Scripts, Desktop
# ═══════════════════════════════════════════════════════════════════════
echo "[3/10] Copying scripts and desktop configs..."

# Deployment/setup scripts
mkdir -p "${STAGING}${INSTALL_PREFIX}/scripts"
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='_deprecated' \
    "${SRC_DIR}/scripts/" "${STAGING}${INSTALL_PREFIX}/scripts/"
chmod +x "${STAGING}${INSTALL_PREFIX}/scripts/"*.sh 2>/dev/null || true

# Desktop (Electron — optional)
if [[ -d "${SRC_DIR}/desktop" ]]; then
    mkdir -p "${STAGING}${INSTALL_PREFIX}/desktop"
    for f in main.js preload.js package.json start.sh setup.html titan-console.desktop; do
        [[ -f "${SRC_DIR}/desktop/${f}" ]] && cp "${SRC_DIR}/desktop/${f}" "${STAGING}${INSTALL_PREFIX}/desktop/"
    done
    [[ -d "${SRC_DIR}/desktop/assets" ]] && \
        rsync -a "${SRC_DIR}/desktop/assets/" "${STAGING}${INSTALL_PREFIX}/desktop/assets/"
fi

# Documentation
if [[ -d "${SRC_DIR}/docs" ]]; then
    rsync -a "${SRC_DIR}/docs/" "${STAGING}${INSTALL_PREFIX}/docs/"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 4: CLI tools → /usr/bin/
# ═══════════════════════════════════════════════════════════════════════
echo "[4/10] Installing CLI tools..."

mkdir -p "${STAGING}/usr/bin"
cp "${SRC_DIR}/bin/titan-vmos" "${STAGING}/usr/bin/titan-vmos"
chmod 755 "${STAGING}/usr/bin/titan-vmos"

mkdir -p "${STAGING}${INSTALL_PREFIX}/bin"
for cli_tool in titan-keybox titan-console; do
    if [[ -f "${SRC_DIR}/bin/${cli_tool}" ]]; then
        cp "${SRC_DIR}/bin/${cli_tool}" "${STAGING}${INSTALL_PREFIX}/bin/${cli_tool}"
        chmod 755 "${STAGING}${INSTALL_PREFIX}/bin/${cli_tool}"
        ln -sf "${INSTALL_PREFIX}/bin/${cli_tool}" "${STAGING}/usr/bin/${cli_tool}"
    fi
done

# ═══════════════════════════════════════════════════════════════════════
# STEP 5: System configs (systemd, kernel modules)
# ═══════════════════════════════════════════════════════════════════════
echo "[5/10] Installing systemd services and kernel configs..."

mkdir -p "${STAGING}/etc/systemd/system"
for unit in titan-api.service titan-scrcpy.service titan-nginx.service titan-recovery.service; do
    if [[ -f "${SRC_DIR}/debian/${unit}" ]]; then
        cp "${SRC_DIR}/debian/${unit}" "${STAGING}/etc/systemd/system/${unit}"
        chmod 644 "${STAGING}/etc/systemd/system/${unit}"
    fi
done

mkdir -p "${STAGING}/etc/modules-load.d"
mkdir -p "${STAGING}/etc/modprobe.d"
cp "${SRC_DIR}/debian/titan-vmos.modules-load.conf" "${STAGING}/etc/modules-load.d/titan-vmos.conf"
cp "${SRC_DIR}/debian/titan-vmos.modprobe.conf"     "${STAGING}/etc/modprobe.d/titan-vmos.conf"
chmod 644 "${STAGING}/etc/modules-load.d/titan-vmos.conf"
chmod 644 "${STAGING}/etc/modprobe.d/titan-vmos.conf"

# ═══════════════════════════════════════════════════════════════════════
# STEP 6: Bundle Cuttlefish VM images + CVD host tools (full mode)
# ═══════════════════════════════════════════════════════════════════════
if [[ $CODE_ONLY -eq 0 ]]; then
    echo "[6/10] Bundling Cuttlefish Android 14 VM images + CVD host tools..."

    # ─── 6a: VM images ────────────────────────────────────────────
    mkdir -p "${STAGING}${INSTALL_PREFIX}/cuttlefish/images"

    if [[ -f "$IMAGE_TARBALL" ]] && [[ $USE_LOCAL_IMAGES -eq 0 ]]; then
        # Use pre-built tarball (from build-image.sh)
        mkdir -p "${STAGING}${INSTALL_PREFIX}/images"
        cp "$IMAGE_TARBALL" "${STAGING}${INSTALL_PREFIX}/images/"
        echo "  Bundled image archive: $(du -sh "$IMAGE_TARBALL" | awk '{print $1}')"
    else
        # Bundle directly from local Cuttlefish images dir
        echo "  Bundling local VM images from ${LOCAL_CVD_IMAGES}..."
        find "${LOCAL_CVD_IMAGES}" -maxdepth 1 \
            \( -name "*.img" -o -name "*.txt" -o -name "*.json" -o -name "bootloader" \) \
            ! -name "*.lock" ! -name "*_raw.img" ! -name "userdata.img" \
            -exec cp -a {} "${STAGING}${INSTALL_PREFIX}/cuttlefish/images/" \;
        IMG_COUNT=$(ls -1 "${STAGING}${INSTALL_PREFIX}/cuttlefish/images/"*.img 2>/dev/null | wc -l)
        IMG_SIZE=$(du -sh "${STAGING}${INSTALL_PREFIX}/cuttlefish/images/" | awk '{print $1}')
        echo "  Bundled ${IMG_COUNT} VM images (${IMG_SIZE})"
    fi

    # ─── 6b: CVD host tools (launch_cvd, stop_cvd, etc.) ─────────
    # Only bundle essential host tool directories — not runtime artifacts
    echo "  Bundling CVD host tools from ${LOCAL_CVD_HOST_BASE}..."
    mkdir -p "${STAGING}${INSTALL_PREFIX}/cuttlefish/cf"
    # Copy only the required subdirectories (bin, lib64, etc, usr, framework, i18n, nativetest64)
    for subdir in bin lib64 etc usr framework com.android.i18n nativetest64; do
        if [[ -d "${LOCAL_CVD_HOST_BASE}/${subdir}" ]]; then
            cp -a "${LOCAL_CVD_HOST_BASE}/${subdir}" "${STAGING}${INSTALL_PREFIX}/cuttlefish/cf/"
        fi
    done
    chmod +x "${STAGING}${INSTALL_PREFIX}/cuttlefish/cf/bin"/* 2>/dev/null || true
    HOST_SIZE=$(du -sh "${STAGING}${INSTALL_PREFIX}/cuttlefish/cf/" | awk '{print $1}')
    echo "  CVD host tools bundled (${HOST_SIZE})"

    # ─── 6c: Cuttlefish init.d scripts (in-VM boot patches) ──────
    if [[ -d "${SRC_DIR}/cuttlefish/init.d" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/cuttlefish_templates/init.d"
        cp -a "${SRC_DIR}/cuttlefish/init.d/"* "${STAGING}${INSTALL_PREFIX}/cuttlefish_templates/init.d/" 2>/dev/null || true
    fi

    # ─── 6d: Cuttlefish launch config template ───────────────────
    if [[ -f "${SRC_DIR}/cuttlefish/launch_config_template.json" ]]; then
        cp "${SRC_DIR}/cuttlefish/launch_config_template.json" \
           "${STAGING}${INSTALL_PREFIX}/cuttlefish_templates/"
    fi
else
    echo "[6/10] Skipping images (--code-only mode)"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 7: Bundle GApps APKs
# ═══════════════════════════════════════════════════════════════════════
if [[ $CODE_ONLY -eq 0 ]]; then
    echo "[7/10] Bundling GApps APKs..."
    mkdir -p "${STAGING}${INSTALL_PREFIX}/data/gapps"

    if [[ -d "$LOCAL_GAPPS" ]] && [[ -n "$(ls -A "$LOCAL_GAPPS"/*.apk 2>/dev/null)" ]]; then
        # Copy only real APKs (skip 0-byte files)
        for apk in "$LOCAL_GAPPS"/*.apk; do
            if [[ -s "$apk" ]]; then
                cp "$apk" "${STAGING}${INSTALL_PREFIX}/data/gapps/"
            fi
        done
        APK_COUNT=$(ls -1 "${STAGING}${INSTALL_PREFIX}/data/gapps/"*.apk 2>/dev/null | wc -l)
        APK_SIZE=$(du -sh "${STAGING}${INSTALL_PREFIX}/data/gapps/" | awk '{print $1}')
        echo "  Bundled ${APK_COUNT} GApps APKs (${APK_SIZE})"
    else
        echo "  No GApps APKs found at $LOCAL_GAPPS"
        echo "  GApps will be auto-downloaded at runtime by gapps_bootstrap.py"
    fi

    # Also bundle .xapk if present
    if [[ -n "$(ls -A "$LOCAL_GAPPS"/*.xapk 2>/dev/null)" ]]; then
        for xapk in "$LOCAL_GAPPS"/*.xapk; do
            if [[ -s "$xapk" ]]; then
                cp "$xapk" "${STAGING}${INSTALL_PREFIX}/data/gapps/"
            fi
        done
        echo "  Also bundled $(ls -1 "${STAGING}${INSTALL_PREFIX}/data/gapps/"*.xapk 2>/dev/null | wc -l) .xapk files"
    fi
else
    echo "[7/10] Skipping GApps (--code-only mode)"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 8: Bundle keybox + Zygisk module cache
# ═══════════════════════════════════════════════════════════════════════
if [[ $CODE_ONLY -eq 0 ]]; then
    echo "[8/10] Bundling keybox and Zygisk module cache..."

    # Keybox (PRIVATE BUILD ONLY — never in public packages)
    if [[ -f "$LOCAL_KEYBOX" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/data/keybox"
        cp "$LOCAL_KEYBOX" "${STAGING}${INSTALL_PREFIX}/data/keybox/"
        echo "  ✓ Bundled keybox.xml (PRIVATE BUILD)"
    elif [[ -d "$LOCAL_KEYBOX_DIR" ]] && [[ -n "$(ls -A "$LOCAL_KEYBOX_DIR" 2>/dev/null)" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/data/keybox"
        cp -a "$LOCAL_KEYBOX_DIR"/* "${STAGING}${INSTALL_PREFIX}/data/keybox/" 2>/dev/null || true
        echo "  ✓ Bundled keybox directory"
    else
        echo "  No keybox found (will need manual installation)"
    fi

    # Pre-cached Magisk binary for resetprop
    MAGISK_CACHE="/opt/titan/cache/magisk"
    if [[ -d "$MAGISK_CACHE" ]] && [[ -n "$(ls -A "$MAGISK_CACHE" 2>/dev/null)" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/cache/magisk"
        cp -a "$MAGISK_CACHE"/* "${STAGING}${INSTALL_PREFIX}/cache/magisk/" 2>/dev/null || true
        echo "  ✓ Bundled Magisk binary cache"
    fi

    # Pre-cached Zygisk modules
    ZYGISK_CACHE="/opt/titan/cache/modules"
    if [[ -d "$ZYGISK_CACHE" ]] && [[ -n "$(ls -A "$ZYGISK_CACHE" 2>/dev/null)" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/cache/modules"
        cp -a "$ZYGISK_CACHE"/* "${STAGING}${INSTALL_PREFIX}/cache/modules/" 2>/dev/null || true
        echo "  ✓ Bundled Zygisk module cache"
    fi

    # Data overlay (if TrickyStore/PIF pre-installed)
    DATA_OVERLAY="/opt/titan/data/zygisk_overlay"
    if [[ -d "$DATA_OVERLAY" ]] && [[ -n "$(ls -A "$DATA_OVERLAY" 2>/dev/null)" ]]; then
        mkdir -p "${STAGING}${INSTALL_PREFIX}/data/zygisk_overlay"
        cp -a "$DATA_OVERLAY"/* "${STAGING}${INSTALL_PREFIX}/data/zygisk_overlay/" 2>/dev/null || true
        echo "  ✓ Bundled Zygisk data overlay"
    fi
else
    echo "[8/10] Skipping keybox/Zygisk (--code-only mode)"
fi

# ═══════════════════════════════════════════════════════════════════════
# STEP 9: Create package metadata + build manifest
# ═══════════════════════════════════════════════════════════════════════
echo "[9/10] Creating build manifest..."

# Generate build-info.json embedded in the package
cat > "${STAGING}${INSTALL_PREFIX}/build-info.json" << BUILDJSON
{
    "package": "${PACKAGE}",
    "version": "${VERSION}",
    "arch": "${ARCH}",
    "build_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "build_host": "$(hostname)",
    "android_version": "14",
    "api_level": 34,
    "cuttlefish_backend": "KVM",
    "max_concurrent_vms": 8,
    "components": {
        "fastapi": "0.115.6",
        "uvicorn": "0.34.0",
        "magisk": "v28.1",
        "tricky_store": "v2.1.0",
        "pif": "v17.2",
        "cuttlefish_tools": "$(ls "${LOCAL_CVD_HOST}/launch_cvd" 2>/dev/null && echo "bundled" || echo "missing")"
    },
    "bundled": {
        "vm_images": $(if [[ $CODE_ONLY -eq 0 ]]; then echo "true"; else echo "false"; fi),
        "cvd_host_tools": $(if [[ $CODE_ONLY -eq 0 ]]; then echo "true"; else echo "false"; fi),
        "gapps_apks": $(if [[ -d "${STAGING}${INSTALL_PREFIX}/data/gapps" ]]; then echo "true"; else echo "false"; fi),
        "keybox": $(if [[ -f "${STAGING}${INSTALL_PREFIX}/data/keybox/keybox.xml" ]]; then echo "true"; else echo "false"; fi)
    },
    "routers": 18,
    "patch_phases": 28,
    "stealth_vectors": 103,
    "device_presets": 30,
    "carriers": 11,
    "locations": 11
}
BUILDJSON

# ═══════════════════════════════════════════════════════════════════════
# STEP 10: Finalize and build .deb
# ═══════════════════════════════════════════════════════════════════════
echo "[10/10] Finalizing and building .deb package..."

# Compute actual installed size (in KB)
INSTALLED_SIZE=$(du -sk "${STAGING}" | awk '{print $1}')
sed -i "s/^Installed-Size:.*/Installed-Size: ${INSTALLED_SIZE}/" "${STAGING}/DEBIAN/control"
# Update version in control file
sed -i "s/^Version:.*/Version: ${VERSION}/" "${STAGING}/DEBIAN/control"

# Strip __pycache__ that may have snuck in
find "${STAGING}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "${STAGING}" -name '*.pyc' -delete 2>/dev/null || true
# Remove .git directories if any
find "${STAGING}" -type d -name '.git' -exec rm -rf {} + 2>/dev/null || true
# Remove test files from production package
find "${STAGING}" -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true
find "${STAGING}" -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
# Remove lock files
find "${STAGING}" -name "*.lock" -delete 2>/dev/null || true

# Fix permissions
find "${STAGING}" -type d -exec chmod 755 {} +
find "${STAGING}" -type f -exec chmod 644 {} +
# Re-set executables
chmod 755 "${STAGING}/DEBIAN/preinst" "${STAGING}/DEBIAN/postinst"
chmod 755 "${STAGING}/DEBIAN/prerm" "${STAGING}/DEBIAN/postrm"
chmod 755 "${STAGING}/usr/bin/titan-vmos"
find "${STAGING}${INSTALL_PREFIX}/bin" -type f -exec chmod 755 {} + 2>/dev/null || true
find "${STAGING}${INSTALL_PREFIX}/build" -name '*.sh' -exec chmod 755 {} + 2>/dev/null || true
find "${STAGING}${INSTALL_PREFIX}/scripts" -name '*.sh' -exec chmod 755 {} + 2>/dev/null || true
# CVD host binaries must be executable
find "${STAGING}${INSTALL_PREFIX}/cuttlefish/cf/bin" -type f -exec chmod 755 {} + 2>/dev/null || true

echo "  Building .deb package (this may take a minute for large images)..."
dpkg-deb -Zgzip -z1 --build --root-owner-group "${STAGING}" "${DEB_OUT}"

BUILD_END=$(date +%s)
BUILD_SECS=$((BUILD_END - BUILD_START))

# Cleanup staging
rm -rf "${STAGING}"

# ═══════════════════════════════════════════════════════════════════════
# BUILD REPORT
# ═══════════════════════════════════════════════════════════════════════
SIZE_MB=$(du -sm "${DEB_OUT}" | awk '{print $1}')
SIZE_HUMAN=$(du -sh "${DEB_OUT}" | awk '{print $1}')
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  BUILD COMPLETE — Titan VMOS V${VERSION}"
echo ""
echo "  Package:  ${DEB_OUT}"
echo "  Size:     ${SIZE_HUMAN} (${SIZE_MB} MB)"
echo "  Version:  ${VERSION}"
echo "  Mode:     $(if [[ $CODE_ONLY -eq 1 ]]; then echo 'CODE-ONLY'; else echo 'FULL PRE-CONFIGURED'; fi)"
echo "  Built in: ${BUILD_SECS}s"
echo ""
echo "  Contents:"
echo "    vmos_titan/ — Unified Python package (core + api modules)"
echo "    server/     — FastAPI + 18 routers + middleware (symlinked from vmos_titan/api)"
echo "    console/    — Web console SPA"
echo "    wallet/     — Payment provisioning bridge"
if [[ $CODE_ONLY -eq 0 ]]; then
echo "    cuttlefish/ — Android 14 VM images + CVD host tools"
echo "    data/gapps/ — GApps APKs (GMS, Play Store, Chrome, YouTube, Wallet)"
echo "    data/keybox/— Hardware attestation keybox"
fi
echo ""
echo "  Install:  sudo dpkg -i ${DEB_OUT}"
echo "  Fix deps: sudo apt-get install -f"
echo ""
if [[ $CODE_ONLY -eq 0 ]] && [[ $SIZE_MB -gt 100 ]]; then
    echo "  ✓ FULL PRE-CONFIGURED — VM boots immediately after install"
    echo "    → titan-vmos start"
    echo "    → titan-vmos create-device"
    echo "    → https://localhost (console)"
else
    echo "  ⚠ CODE-ONLY — run 'titan-vmos setup-cuttlefish' after install"
fi
echo "═══════════════════════════════════════════════════════════"
