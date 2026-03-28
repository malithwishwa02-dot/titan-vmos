# Titan V12 — Technical Documentation

Complete reference documentation for the Titan V12 Advanced Android Cloud Device Platform.

**V12 Major Changes:**
- `/proc` bind mount guards for Cuttlefish (prevents app crashes)
- GPU property safelist (preserves `angle`/`vsoc_x86_64`)
- Quick repatch (30s vs 200s full patch)
- Cloud sync mitigation (W-3) for wallet persistence
- Provincial Injection Protocol (8-phase robust injection)
- SQLite batch injection (20× faster than content provider)

---

## Document Index

| File | Title | Description |
|------|-------|-------------|
| [00-overview.md](00-overview.md) | Platform Overview | Architecture, infrastructure, service map, V12 major changes |
| [01-device-manager.md](01-device-manager.md) | Device Manager | Cuttlefish VM lifecycle, `auto_patch`, `quick_repatch` endpoints |
| [02-anomaly-patcher.md](02-anomaly-patcher.md) | Anomaly Patcher | 26 phases, 156+ vectors, `/proc` guards, GPU safelist |
| [03-genesis-pipeline.md](03-genesis-pipeline.md) | Genesis Pipeline | Forge→inject→verify, V12 pipeline hang fixes |
| [04-profile-injector.md](04-profile-injector.md) | Profile Injector | SQLite batch injection, provider health checks |
| [05-wallet-injection.md](05-wallet-injection.md) | Wallet Injection | Cloud sync mitigation (W-3), boot script persistence |
| [06-ai-agent.md](06-ai-agent.md) | AI Device Agent | See-Think-Act loop, model hierarchy, TouchSimulator |
| [07-titan-console.md](07-titan-console.md) | Titan Console | Tab-to-tab navigation, screen wake, quick repatch polling |
| [08-intelligence-tools.md](08-intelligence-tools.md) | Intelligence Tools | OSINT, Cerberus BIN, WebCheckEngine, 3DS strategy |
| [09-network-kyc.md](09-network-kyc.md) | Network & KYC | VPN, deepfake pipeline, V4L2→virtio camera, KYC bypass |
| [10-training-pipeline.md](10-training-pipeline.md) | Training Pipeline | Demo recording, trajectory logging, LoRA fine-tune workflow |
| [11-real-world-success-rates.md](11-real-world-success-rates.md) | Success Rates | Empirical rates: patcher, genesis, wallet, Play Integrity |
| [provincial-injection-protocol.md](provincial-injection-protocol.md) | Provincial Injection | 8-phase robust injection protocol for contacts/calls/SMS |

---

## Quick Start Reference

```bash
# API base
https://72.62.72.48/

# Key paths
/opt/titan-v11.3-device/   # Codebase
/opt/titan/data/           # Runtime data (profiles, devices, trajectories)
/opt/titan/data/keybox.xml # Hardware keybox (Play Integrity Strong)

# V12 quick commands
curl -X POST https://72.62.72.48/api/devices -d '{"model":"samsung_s24","auto_patch":false}'
curl -X POST https://72.62.72.48/api/devices/dev-xxx/quick-repatch
curl https://72.62.72.48/api/devices/dev-xxx/needs-repatch
```

## Core Modules (V12)

```
core/
├── device_manager.py               # Cuttlefish VM management
├── device_presets.py               # 20+ device identities
├── anomaly_patcher.py              # 26-phase stealth patcher (V12: /proc guards, GPU safelist)
├── android_profile_forge.py        # Genesis profile generator
├── profile_injector.py             # ADB injection (V12: SQLite batch)
├── provincial_injection_protocol.py # V12: 8-phase robust injection
├── wallet_provisioner.py           # Google Pay + cloud sync mitigation
├── wallet_verifier.py              # 13-check wallet verification
├── google_account_injector.py      # Google account injection
├── device_agent.py                 # AI See-Think-Act agent
├── touch_simulator.py              # Human-like ADB touch
├── sensor_simulator.py             # OADEV-based IMU noise
├── screen_analyzer.py              # Screenshot-to-LLM analysis
├── gapps_bootstrap.py              # GApps installer
└── workflow_engine.py              # Pipeline orchestrator

server/routers/
├── devices.py                      # VM lifecycle, auto_patch param
├── stealth.py                       # quick_repatch, needs_repatch endpoints
├── provision.py                     # Pipeline with age_days=1
└── ...
```

## V12 API Changes

| Endpoint | Change |
|----------|--------|
| `POST /api/devices` | Added `auto_patch: bool = false` parameter |
| `POST /api/devices/{id}/quick-repatch` | **New** — 30s incremental patch |
| `GET /api/devices/{id}/needs-repatch` | **New** — Check if device lost patches |
| `POST /api/stealth/{id}/patch` | Now returns `job_id` for polling |
| `GET /api/stealth/{id}/patch-status/{job_id}` | **New** — Poll patch progress |

## See Also

- [V12 Upgrade Plan](v12-upgrade-plan.md) — Detailed migration guide
- [ADR/001-cuttlefish-over-redroid.md](adr/001-cuttlefish-over-redroid.md) — Architecture decision record
- [cuttlefish-training-replan.md](cuttlefish-training-replan.md) — Cuttlefish-specific training notes
