# End-to-End Tests

E2E tests require a live Cuttlefish Android VM with ADB access.
They are **not** run in CI — only on development/staging VPS instances.

## Running E2E tests

```bash
# Requires: running CVD, ADB connected, Titan API on :8080
python scripts/full_console_test.py          # All 12 API tabs
python scripts/test_e2e_pipeline.py          # Forge→inject→patch→audit→wallet
python scripts/e2e_90day_test.py             # 90-day profile lifecycle
python scripts/test_us_injection.py          # Full US bundle injection
```

## Prerequisites

- Linux host with KVM + Cuttlefish host tools
- Running CVD instance (`launch_cvd`)
- ADB connection to `127.0.0.1:6520`
- Titan API server running on port 8080
- GApps bootstrapped on the device
