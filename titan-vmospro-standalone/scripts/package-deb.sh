#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
PKG_DIR="$DIST_DIR/deb_pkg"
OUT_DEB="$DIST_DIR/titan-vmospro-standalone_0.1.0_amd64.deb"

"$ROOT_DIR/scripts/build.sh"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN" "$PKG_DIR/usr/local/bin"

cp "$ROOT_DIR/packaging/deb/control" "$PKG_DIR/DEBIAN/control"
cp "$ROOT_DIR/packaging/deb/postinst" "$PKG_DIR/DEBIAN/postinst"
cp "$ROOT_DIR/packaging/deb/prerm" "$PKG_DIR/DEBIAN/prerm"
chmod 0755 "$PKG_DIR/DEBIAN/postinst" "$PKG_DIR/DEBIAN/prerm"

cp "$DIST_DIR/linux/titan-vmospro-standalone" "$PKG_DIR/usr/local/bin/titan-vmospro-standalone"
chmod 0755 "$PKG_DIR/usr/local/bin/titan-vmospro-standalone"

dpkg-deb --build "$PKG_DIR" "$OUT_DEB"
echo "Debian package created: $OUT_DEB"
