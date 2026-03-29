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

### Genesis V3 Nexus Pipeline
- **Real OAuth tokens**: Use `google_master_auth.py` (gpsoauth) for server-validated tokens — NOT synthetic `ya29.` fakes
- **Host-side DB building**: Use `vmos_db_builder.py` to build SQLite DBs on host (VMOS lacks sqlite3 binary)
- **Bridge Protocol**: Use `vmos_file_pusher.py` for chunked base64 file transfer (4KB syncCmd limit)
- **Wallet injection**: Use `wallet_injection.py` for 100% Google Pay injection via filesystem
- **DPAN generation**: Always use TSP Token BIN ranges (Visa: 489537-489539, MC: 530060-530063, Amex: 374800-374801)
- **COIN.xml**: Must include all 8 zero-auth flags including `PAYMENTS_ZERO_AUTH_ENABLED` and `frictionless_checkout_enabled`
- **Stochastic aging**: Use `stochastic_aging_engine.py` with Poisson processes and 8 persona archetypes
- **Sensor evasion**: Use `sensor_noise_simulator.py` for MEMS Allan Deviation noise + GPS-IMU EKF fusion
- **TEE simulation**: Use `attestation_proxy.py` for Play Integrity DEVICE tier (STRONG still hardware-blocked)
- **Pipeline runner**: Use `vmos_nexus_runner.py` for 4-phase orchestration (Recon → Synthesis → Deploy → Validate)

### Real-World Accuracy Rules
- Do NOT implement stub code that claims to work but doesn't — mark it clearly
- If a feature requires hardware TEE, physical SIM, or real bank auth, say so in code comments
- Wallet/payment injection populates DB structure but does NOT create real payment capability
- Play Integrity STRONG tier requires RKA proxy to physical device — no software-only path
- Google account injection with real OAuth tokens via gpsoauth master token flow
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
- `google_master_auth.py` — Real OAuth token acquisition via gpsoauth master token flow (11 scopes)
- `vmos_db_builder.py` — Host-side SQLite DB construction (accounts_ce, tapandpay, library)
- `vmos_file_pusher.py` — Chunked base64 Bridge Protocol for VMOS file transfer
- `wallet_injection.py` — Google Pay 100% injection via filesystem (tapandpay.db + COIN.xml 8-flag)
- `sensor_noise_simulator.py` — MEMS Allan Deviation noise with GPS-IMU EKF fusion
- `stochastic_aging_engine.py` — Poisson/Markov behavioral aging with 8 persona archetypes
- `attestation_proxy.py` — TEE simulation for Play Integrity DEVICE tier
- `vmos_nexus_runner.py` — 4-phase V3 Nexus pipeline orchestrator

### PARTIAL (working core, hardware-limited features)
- `play_integrity_spoofer.py` — BASIC/DEVICE tiers work, STRONG tier needs RKA hardware proxy (472 lines)
- `google_account_injector.py` — DB injection into 8 targets works; V3 uses real tokens via gpsoauth (723 lines)
- `wallet_provisioner.py` — Full DB injection works (cards appear in GPay UI), NFC payments need real keybox (1,583 lines)
- `hce_bridge.py` — APDU application layer correct, needs NFC hardware for contactless (458 lines)
- `network_shield.py` — iptables rules + domain blocking work, host-side only (270 lines)
- `keybox_manager.py` — Keybox validation/install/CRL-check works, real keyboxes must be externally sourced (493 lines)

### STUB (framework exists, core feature non-functional)
- `kyc_core.py` — Provider detection works, camera injection and liveness bypass are placeholders (370 lines)

### HARDWARE-BLOCKED (cannot be software-fixed)
- Play Integrity STRONG tier — requires RKA proxy to physical device TEE
- NFC contactless payments — requires physical NFC antenna/controller
- Samsung Pay — Knox TEE e-fuse barrier (Knox 0x1 = permanent)
- Real EMV session keys — requires TSP (Token Service Provider) integration with issuer
- Chrome `card_number_encrypted` — Android Keystore bound (NULL column, user enters manually)
- GPU identity (Mali-G715) — hardware GL, not spoofable without Zygisk GL hook
- `/proc/device-tree/` — kernel device-tree, immutable at runtime
- `packages.xml firstInstallTime` — ABX2 binary format, cannot be modified on-device

## VMOS Cloud Device Rules

### API Client (`core/vmos_cloud_api.py`)
- Use `VMOSCloudClient` (async httpx + HMAC-SHA256) for all VMOS Cloud operations
- Credentials: `VMOS_CLOUD_AK` / `VMOS_CLOUD_SK` from `.env`
- Always load env: `set -a && source .env && set +a` before Python API calls
- Client is async — wrap in `asyncio.run()` for CLI scripts

### Critical Parameter Rules
- Most VMOS APIs use `padCodes` (array of strings), NOT `padCode` (singular)
- Image injection: parameter is `injectUrl` — NOT `imageUrl`, `imgUrl`, or `picUrl`
- Audio injection: `padCodes` (array) + `audioUrl`
- Video injection: `padCodes` (array) + `videoUrl`
- Per-app root: `switchRoot` requires `rootType=1` + `packageName` — global root (`rootType=0`) is broken
- GPS injection: `set_gps([pad], lat, lng)` — verified working
- `sync_cmd` has 4KB limit and frequently times out — use `async_adb_cmd` + `task_detail` polling instead
- `updatePadProperties` works for dynamic property changes (no restart needed)

### Known Broken Endpoints (DO NOT USE)
- `simulate_click_humanized` → endpoint returns 404 (does not exist)
- `simulate_swipe_humanized` → endpoint likely returns 404
- `instance_details` (`/padDetails`) → returns 404, use `instance_list` (`/infos`) instead
- `updatePadAndroidProp` → triggers background restart, breaks all shell commands
- `replacePad` → always causes device restart even with `wipeData: 0`

### VMOS Crash Prevention Rules (CRITICAL)
- **NEVER** `pm disable-user com.cloud.rtcgesture` — it's the VMOS WebRTC control channel; disabling causes permanent status=11 (unrecoverable without full reset)
- **NEVER** `pm disable-user com.android.expansiontools` — VMOS management app; may brick the device
- **NEVER** mount tmpfs over `/system/priv-app/` — breaks Android PackageManagerService; causes crash
- **NEVER** mass chmod/operate on `/sys/block/` — 679 loop + 64 NBD devices; sysfs is kernel read-only; timeout causes crash
- **NEVER** rapid-fire async_adb_cmd calls (<3s apart) — triggers 110031 API flood → device goes status=14 (Abnormal)
- **NEVER** bind-mount over `/system/bin/cloudservice` or `/system/bin/xu_daemon` — breaks VMOS daemons
- VMOS `/system` is device-mapper (dm-6) protected — `mount -o remount,rw /system` ALWAYS fails
- Space ADB commands ≥3s apart; batch related commands into a single shell string
- After device reset: all injected data is lost (contacts, calls, SMS, aging, spoofing)

### Safe Stealth Techniques (confirmed working on VMOS)
- `tmpfs` staging at `/dev/.sc` (anonymous mount)
- `bind-mount` sterile files over `/proc/cmdline`, `/proc/mounts`, `/proc/1/cgroup`
- `resetprop --delete` for non-boot properties (init may restore `init.svc.*`)
- `resetprop <prop> ""` for boot-locked `ro.boot.*` properties (empties value)
- `rmmod selinux_leak_fix` (unloads VMOS kernel module)
- Process comm rename via `echo newname > /proc/PID/comm`
- Full iptables control for network filtering

### VMOS Device Behavior
- ADB commands can fail (status=-1) after heavy usage — `instance_restart()` fixes it
- After restart, device transitions status 14 → 10 in ~20 seconds
- `padStatus=10` means Running — only status=10 accepts shell commands
- Never restart from status=11 (causes 11↔14 boot loop) — wait up to 5 min for 11→10; if stuck >5 min, device is bricked (needs RESET)
- Status 14 (Abnormal) — safe to restart via `instance_restart()`
- 110031 API error — device ADB pipeline saturated; wait 30-60s before retrying
- Expansion tools (`com.android.expansiontools`) UI cannot be dumped by UIAutomator (0 nodes)
- Expansion tools toggles (Magisk, LSPosed, Video/Image Injection) do NOT respond to ADB taps or simulate_touch
- VMOS devices are Linux namespace containers on Rockchip RK3588 ARM boards (NOT VMs/emulators)
- Real GPU: Mali-G715 (spoofed as Adreno in build.prop only; GL_RENDERER still shows Mali)
- Real sensors: BMI26x accelerometer, AK0991x magnetometer (real MEMS, not emulated)

### VMOS Fingerprint Property Namespaces
- **Core IDs**: `ro.sys.cloud.android_id`, `persist.sys.cloud.imeinum`, `persist.sys.cloud.iccidnum`, `persist.sys.cloud.imsinum`
- **DRM**: `persist.sys.cloud.drm.id` (deviceUniqueId), `persist.sys.cloud.drm.puid` (provisioningUniqueId)
- **GPU**: `persist.sys.cloud.gpu.gl_vendor`, `persist.sys.cloud.gpu.gl_renderer`, `persist.sys.cloud.gpu.gl_version`
- **WiFi**: `persist.sys.cloud.wifi.ssid/mac/ip/gateway/dns1`
- **Cellular**: `persist.sys.cloud.cellinfo` (hex: `type,mcc,mnc,tac,cellid,narfcn,pci` — type 9 = 5G NR), `persist.sys.cloud.mobileinfo`, `persist.sys.cloud.phonenum`
- **Proxy**: `ro.sys.cloud.proxy.mode` (proxy=iptables, vpn=VpnService), `ro.sys.cloud.proxy.type/data`, bypass rules via `byPassPackageName1/byPassIpName1/byByPassDomain1`
- **Environment**: `persist.sys.cloud.battery.capacity/level`, `persist.sys.cloud.boottime.offset`, `ro.sys.cloud.boot_id`, `ro.sys.cloud.rand_pics` (auto gallery generation), `persist.sys.cloud.pm.install_source` (fake Play Store origin)
- **Sensors**: `persist.sys.cloud.sensor.tpl_dp` (path to sensor data file; UTF-8 text, up to 1GB, sequential readings + `delay:N` commands)
- **Xposed/LSPosed**: `apmt patch add -n <name> -p <package> -f <path>` — native plugin hooking framework; entry class `androidx.app.Entry`; system hooks target `"android"` package + reboot

### VMOS System Architecture
- `cloudservice` (PID 158): GPS data pipeline, camera notifications, uses `pipe:qemud:gps/camera`
- `xu_daemon` (PID 283): Root execution, PTY sessions, batch commands
- `com.cloud.rtcgesture`: WebRTC streaming (ports 23333/23334)
- GPS properties: `persist.cloud.gps.*` (cloudservice) vs `persist.sys.cloud.gps.en` (expansion tools toggle)

### Known VMOS Instances
| Pad Code | Device | OS | Notes |
|---|---|---|---|
| ACP250329ACQRPDV | (new replacement) | Android 15 | Active |
| ACP2507296TM25XE | (new replacement) | Android 15 | Active |
| ACP2509244LGV1MV | OnePlus Ace 3 (PJZ110) | Android 15 | BRICKED (status=11, pm disable rtcgesture) |
| ACP5CF4Z11Z67PQA | Samsung S24 Ultra | Android 15 | BRICKED (status=11, aggressive patching) |
| ACP251008CRDQZPF | Samsung Galaxy S24 Ultra | Android 15 | Unknown status |
