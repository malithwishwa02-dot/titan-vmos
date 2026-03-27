# Titan VMOS Pro Standalone

Standalone Go app scaffold for Titan Console + VMOS Pro workflows.

## Scope

- Isolated under `titan-vmospro-standalone/`
- No imports from the existing app/server/desktop/debian/build trees
- Dedicated scripts, packaging metadata, and CI workflow

## Quickstart

```bash
cd /opt/titan-v13-device/titan-vmospro-standalone
go test ./...
bash scripts/build.sh
```

## Configuration

Set credentials through service calls in `internal/vmos/service.go`:

- `APIKey`
- `APISecret`
- `BaseURL` (defaults to `https://api.vmoscloud.com`)

Credentials are encrypted at rest to:

`~/.config/titan-vmospro-standalone/credentials.enc`

Use `TITAN_VMOS_MASTER_KEY` to provide your own encryption seed.

## Genesis + Pipeline

`internal/genesis` orchestrates Titan session + step execution.
`internal/pipeline` provides explicit typed stub adapters for unresolved/orphan endpoints via `ErrEndpointNotImplemented`.

## Packaging

- Debian: `bash scripts/package-deb.sh`
- Windows placeholder installer: `bash scripts/package-windows.sh`

Verify release artifacts:

```bash
bash scripts/verify-artifacts.sh
```
