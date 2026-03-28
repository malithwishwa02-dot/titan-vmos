#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
DEB="$DIST_DIR/titan-vmospro-standalone_0.1.0_amd64.deb"
EXE="$DIST_DIR/titan-vmospro-standalone-setup.exe"

test -f "$DEB" || { echo "missing artifact: $DEB"; exit 1; }
test -f "$EXE" || { echo "missing artifact: $EXE"; exit 1; }

echo "Artifacts verified:"
echo " - $DEB"
echo " - $EXE"
