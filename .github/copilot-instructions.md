# Titan V13 — Copilot Instructions

## Environment Facts
- **OS**: Linux (Ubuntu), developer connects via RDP — NOT headless
- **Display**: Always live on RDP session (DISPLAY=:10.0), screens are real
- **Python**: 3.11+ in `/opt/titan-v13-device/venv/`
- **PYTHONPATH**: `core:server` (both directories are importable)
- **API**: FastAPI on port 8080 via uvicorn
- **Device**: Cuttlefish Android VM (ADB on 0.0.0.0:6520)
- **LLM**: Ollama (GPU :11435, CPU fallback :11434)

## Coding Rules

### Python
- Use `adb_utils.adb_shell()` / `adb_with_retry()` for all ADB operations — never raw `subprocess`
- Use `ensure_adb_root(target)` before any privileged operation
- All new core modules must use `json_logger` for structured logging
- Use Pydantic models from `models.py` for API request/response schemas
- New routers go in `server/routers/`, register in `titan_api.py`
- Use `@dataclass` for internal state, Pydantic for API boundaries

### Agent (device_agent.py)
- Agent runs on a REAL screen (RDP) — never treat as headless
- NEVER skip a failing step — retry, analyze root cause, patch approach, then continue
- Every failure must be recorded as a `FailureVector` in session memory
- Screen capture, LLM queries, and action execution must all retry (min 3 attempts)
- Task templates must have `"realism"` tag: `achievable`, `requires_otp`, `requires_captcha`, `requires_payment`
- Auto-dismiss permission dialogs and crash/ANR dialogs before LLM processing
- Only mark operations as "achievable" if they work without external verification (OTP, CAPTCHA, bank auth)

### Real-World Accuracy Rules
- Do NOT implement stub code that claims to work but doesn't — mark it clearly
- If a feature requires hardware TEE, physical SIM, or real bank auth, say so in code comments
- Wallet/payment injection populates DB structure but does NOT create real payment capability
- Play Integrity STRONG tier requires RKA proxy to physical device — no software-only path
- Account injection seeds DB but tokens are synthetic — apps will re-auth on first sync
- NFC HCE generates APDU commands but there is no NFC hardware socket

### ADB & Android
- Always `restorecon -R` after pushing files to preserve SELinux contexts
- After system partition writes: `mount -o remount,ro /system`
- Use `resetprop` (via `libmagisk64.so`) for `ro.*` properties, never `setprop`
- Check file ownership after SQLite injection: `system:system` (1000:1000) for account DBs

### Testing
- Tests in `tests/` directory, run with `python -m pytest tests/ -x`
- Syntax check: `python -c "import ast; ast.parse(open('file.py').read())"`
- Import check: Set PYTHONPATH then import the module

## Module Status Reference

### WORKING (production-ready)
- `adb_utils.py` — ADB command execution with retry, root
- `touch_simulator.py` — Fitts's Law human-like input via ADB (325 lines)
- `screen_analyzer.py` — Screenshot + UIAutomator XML + OCR parsing (369 lines)
- `sensor_simulator.py` — OADEV noise-coupled accelerometer/gyro with GPS-IMU fusion (499 lines)
- `device_manager.py` — Cuttlefish VM lifecycle, port allocation, SQLite state (1,115 lines)
- `anomaly_patcher.py` — 30-phase stealth patcher, 103+ detection vectors, all real ADB (3,581 lines)
- `profile_injector.py` — Identity data injection via ADB into 8+ Android subsystems (2,022 lines)
- `android_profile_forge.py` — Complete persona generation with temporal depth (2,201 lines)
- `forensic_monitor.py` — 44-vector forensic audit with weighted risk scoring (458 lines)
- `trust_scorer.py` — 14-check trust scoring (0–100 scale)
- `task_verifier.py` — Post-task verification
- `trajectory_logger.py` — Training data recording
- `device_agent.py` — See→Think→Act loop, 40 templates with realism tags, failure analysis (1,386 lines)
- `immune_watchdog.py` — Honeypot deploy, path/prop hardening, process cloaking, port lockdown (654 lines)
- `device_recovery.py` — Health monitoring and auto-recovery (330 lines)
- `ghost_sim.py` — Virtual SIM/modem with cell tower DB, signal fluctuation daemon (400 lines)
- `payment_history_forge.py` — Realistic transaction history with circadian patterns (422 lines)
- `app_data_forger.py` — Per-app SharedPreferences/database forging (478 lines)
- `three_ds_strategy.py` — 3DS challenge prediction, BIN-based advisory engine (326 lines)

### PARTIAL (working core, hardware-limited features)
- `play_integrity_spoofer.py` — BASIC/DEVICE tiers work, STRONG tier needs RKA hardware proxy (472 lines)
- `google_account_injector.py` — DB injection into 8 targets works, tokens are synthetic (apps re-auth) (723 lines)
- `wallet_provisioner.py` — Full DB injection works (cards appear in GPay UI), NFC payments need real keybox (1,583 lines)
- `hce_bridge.py` — APDU application layer correct, needs NFC hardware for contactless (458 lines)
- `network_shield.py` — iptables rules + domain blocking work, host-side only (270 lines)
- `keybox_manager.py` — Keybox validation/install/CRL-check works, real keyboxes must be externally sourced (493 lines)

### STUB (framework exists, core feature non-functional)
- `kyc_core.py` — Provider detection works, camera injection and liveness bypass are placeholders (370 lines)

### HARDWARE-BLOCKED (cannot be software-fixed)
- Play Integrity STRONG tier — requires RKA proxy to physical device TEE
- NFC contactless payments — requires physical NFC antenna/controller
- Samsung Pay — Knox TEE e-fuse barrier
- Real Google OAuth tokens — requires actual Google authentication flow
- Real EMV session keys — requires TSP (Token Service Provider) integration with issuer
