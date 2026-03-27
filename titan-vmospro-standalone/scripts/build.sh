#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

mkdir -p "$DIST_DIR/linux" "$DIST_DIR/windows"

pushd "$ROOT_DIR" >/dev/null
go test ./...
GOOS=linux GOARCH=amd64 go build -o "$DIST_DIR/linux/titan-vmospro-standalone" ./app
GOOS=windows GOARCH=amd64 go build -o "$DIST_DIR/windows/titan-vmospro-standalone.exe" ./app
popd >/dev/null

echo "Build complete under $DIST_DIR"
