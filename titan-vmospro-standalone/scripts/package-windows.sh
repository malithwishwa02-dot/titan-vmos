#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
OUT_EXE="$DIST_DIR/titan-vmospro-standalone-setup.exe"

"$ROOT_DIR/scripts/build.sh"

cp "$DIST_DIR/windows/titan-vmospro-standalone.exe" "$OUT_EXE"
echo "Windows installer placeholder created: $OUT_EXE"
echo "NSIS config available at: $ROOT_DIR/packaging/windows/installer.nsi"
