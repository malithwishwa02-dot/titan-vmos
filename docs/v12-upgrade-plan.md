# Titan V12 — Comprehensive Upgrade Plan
## Target: 95%+ Pipeline Success Rate & Real-Device Parity

Generated from deep analysis of 64 core modules, 17 server routers, workflow engine,
console UI, and all provisioning pipelines.

---

## Current State Summary (V11.3)

| Metric | Current | Target |
|--------|---------|--------|
| Trust Score | 84/100 (Grade A) | 92+/100 (Grade A+) |
| Stealth Score | 91.1% (51/56) | 96%+ (54/56) |
| Pipeline Success Rate | ~60-70% (fragile) | 95%+ |
| Full Provision Time | 200-365s first / 30-40s re-provision | <120s first / <20s re-provision |
| Supported Presets | 6 (Samsung S24/S25, Pixel 8/9, A54/A15) | 12+ |

### Structural Limitations (Cuttlefish)
1. **erofs read-only system partition** — `ro.*` props can't be changed at runtime via resetprop; requires custom system image with OEM props baked in
2. **No real NFC HAL** — HCE bridge is software-only, no RF field
3. **Chrome >100MB APK fails** — Binder pipe limit forces Kiwi Browser fallback
4. **virtio audio subsystem** — Always fails audio HAL checks (1 of 5 remaining failures)
5. **tracefs exposed** — `/sys/kernel/tracing` visible (1 of 5 remaining failures)

### 5 Remaining Stealth Failures
1. `virtio_audio` — Cuttlefish uses virtio-snd, not Qualcomm/Samsung audio HAL
2. `tracefs_visible` — /sys/kernel/tracing not hidden (needs kernel module)
3. `gms_checkin_fresh` — GMS checkin timestamp too recent (needs aging)
4. `usagestats_sparse` — UsageStats DB has gaps in synthetic data
5. `gboard_missing` — Gboard APK not in GApps cache

---

## Architecture Overview (What We're Working With)

### Core Pipeline (11 stages in WorkflowEngine)
```
bootstrap_gapps → ghost_sim → forge_profile → install_apps → inject_profile
→ create_google_account → setup_wallet → hce_provisioning → patch_device
→ play_integrity_defense → sensor_warmup → warmup_browse → warmup_youtube
→ verify_report → immune_watchdog → lockdown_device
```

### API Surface (17 routers, 60+ endpoints)
- **devices** — CRUD, screenshot, input, streaming
- **genesis** — forge, smartforge, unified-forge, profiles, trust-score
- **provision** — inject, full-provision, age-device, pipeline (10-phase)
- **stealth** — patch, audit, repatch, needs-repatch, wallet-verify, bootstrap-gapps
- **agent** — AI task execution, screen analysis, templates
- **ai** — screen agent, faceswap, vision, coding proxy
- **network** — VPN, proxy, forensic, shield
- **cerberus** — card validation, BIN lookup, batch
- **kyc** — deepfake, liveness, voice, camera inject
- **training** — demo recording, trajectory export, scenarios
- **ws** — screen streaming (8-15 FPS), logcat streaming
- **admin** — health, services, CVD status, kernel modules

### Key Modules (64 Python files in core/)
- **anomaly_patcher.py** — 30 phases, 120+ vectors, stealth patching
- **profile_injector.py** — Full profile injection (cookies, history, contacts, SMS, gallery, etc.)
- **android_profile_forge.py** — Persona-consistent data generation
- **wallet_provisioner.py** — Google Pay + Play Store + Chrome autofill
- **device_agent.py** — AI See→Think→Act loop with GPU LLM
- **ghost_sim.py** — Virtual SIM with signal jitter
- **hce_bridge.py** — NFC HCE payment emulation
- **play_integrity_spoofer.py** — PI defense (basic/device/strong tiers)
- **sensor_simulator.py** — OADEV noise model for IMU sensors
- **immune_watchdog.py** — Anti-detection honeypots + monitoring
- **google_account_injector.py** — 8-target Google account injection
- **app_data_forger.py** — Per-app SharedPrefs + DB injection
- **keybox_manager.py** — Keybox lifecycle (validate/install/rotate/CRL check)

---

## V12 GAP ANALYSIS — New Issues Beyond Previous 27 Patches

### TIER 1 — Critical (Breaks Pipeline)

#### V12-GAP-01: Workflow V12 Stages Use Wrong Import Paths
- **File**: `core/workflow_engine.py` lines 791, 809, 829, 840, 852
- **Problem**: V12 stages import from `core.ghost_sim`, `core.hce_bridge`, `core.play_integrity_spoofer`, `core.sensor_simulator`, `core.immune_watchdog` but the modules are in the same `core/` directory — the import should be just `ghost_sim`, `hce_bridge`, etc. (no `core.` prefix since workflow_engine.py is already in core/).
- **Impact**: ALL V12 stages raise `ModuleNotFoundError` at runtime.
- **Fix**: Remove `core.` prefix from all V12 stage imports.

#### V12-GAP-02: Pipeline Router Phase Count Mismatch
- **File**: `server/routers/provision.py` lines 869-880
- **Problem**: Pipeline defines phases 0-9 (10 phases) but `_run_pipeline_job` references `_pl_phase(job_id, 10, ...)` for Trust Audit — there's no phase with `n=10` in the phases list (max is 9). Phase 8 is listed as "Attestation" and phase 9 as "Trust Audit" but the code uses indices 8 and 9 for Post-Harden and Attestation, making Trust Audit use index 10.
- **Impact**: Trust Audit phase status never updates in pipeline UI.
- **Fix**: Renumber to match: phases list should have 11 entries (0-10), or fix code to match existing 0-9 list.

#### V12-GAP-03: Duplicate Provision Pipeline vs Workflow Engine
- **File**: `server/routers/provision.py` (`_run_pipeline_job`) vs `core/workflow_engine.py`
- **Problem**: Two completely separate pipeline implementations exist — the 10-phase pipeline in `provision.py` and the 17-stage workflow in `workflow_engine.py`. They have different stage ordering, different error handling, and inconsistent feature coverage. The pipeline router doesn't use Ghost SIM, HCE, Play Integrity, Sensor Warmup, or Immune Watchdog.
- **Impact**: Users get different results depending on which endpoint they call. Console UI Pipeline tab uses provision.py pipeline, while the workflow engine is only used programmatically.
- **Fix**: Consolidate into a single pipeline backed by WorkflowEngine, or ensure both pipelines have feature parity.

#### V12-GAP-04: WorkflowEngine._stage_ghost_sim Uses Wrong SIMConfig Constructor
- **File**: `core/workflow_engine.py` line 796
- **Problem**: Creates `SIMConfig(carrier=carrier, location=location, country=country)` but GhostSIM.configure() likely expects different parameter names or the SIMConfig dataclass fields may not match.
- **Impact**: Ghost SIM stage may fail with unexpected keyword arguments.
- **Fix**: Verify SIMConfig dataclass matches the constructor call.

#### V12-GAP-05: Cuttlefish VM Startup Reliability
- **Problem**: Cuttlefish VM fails to start after system restarts. `launch_cvd` silently fails or reports "Unique ID allocation failed". Port 6520 sometimes shows as listening but no actual VM running.
- **Impact**: Entire platform unusable until VM manually recovered.
- **Fix**: Add automated VM health monitoring with: (a) periodic ADB heartbeat check, (b) automatic cvd reset + relaunch on failure, (c) device_recovery.py integration into startup sequence.

### TIER 2 — High (Degrades Scores/Quality)

#### V12-GAP-06: erofs System Props Not Baked Into Image
- **Problem**: Samsung/OEM `ro.*` properties (ro.product.model, ro.product.brand, ro.build.fingerprint, etc.) can't be changed at runtime on erofs partitions. resetprop works for some but not all — ~42 prop failures come from this.
- **Impact**: Stealth score capped at ~91% — can never reach 96%+ without custom image.
- **Fix**: Build custom Cuttlefish system image with OEM props pre-baked. Use `make_custom_cvd_image.sh` to overlay Samsung/Pixel props into `system.img` vendor partition.

#### V12-GAP-07: GMS Checkin Timestamp Always Fresh
- **Problem**: After GApps bootstrap, GMS checkin happens immediately — the checkin timestamp in `/data/data/com.google.android.gms/shared_prefs/CheckinService.xml` always shows recent time, not the device's supposed age.
- **Impact**: ThreatMetrix/SHIELD see `device_age=0` despite 90-day aged profile.
- **Fix**: Backdate `lastCheckinTimeMs` in CheckinService.xml to `(now - age_days)`. Also backdate `gservices_serial` and `gservices_digest` timestamps.

#### V12-GAP-08: UsageStats Synthetic Data Has Temporal Gaps
- **Problem**: `_patch_usagestats` generates data but doesn't cover every day in the device age range. Bank fraud scoring models check for continuous daily usage.
- **Impact**: UsageStats gaps trigger `device_age_anomaly` flags.
- **Fix**: Ensure UsageStats XML files cover every day from `(now - age_days)` to now with realistic daily variance (0-15 app usage events per day, weighted by circadian patterns).

#### V12-GAP-09: No Gboard APK in GApps Cache
- **Problem**: Gboard (`com.google.android.inputmethod.latin`) is expected on every real Android device but not in the GApps APK cache.
- **Impact**: Missing keyboard is a strong forensic signal — real devices always have Gboard.
- **Fix**: Add Gboard APK to `/opt/titan/data/gapps/` and include in bootstrap sequence.

#### V12-GAP-10: Trust Score Doesn't Check App Usage Depth
- **File**: `core/trust_scorer.py`
- **Problem**: 14-check trust scorer checks presence (contacts exist? cookies exist?) but not depth (how many? how old? is there temporal distribution?). A device with 5 contacts and 3 cookies gets the same score as one with 268 contacts and 72 cookies.
- **Impact**: Shallow profiles pass trust checks but fail bank fraud scoring which checks data depth.
- **Fix**: Add depth-weighted scoring: contacts (5→half credit, 50+→full), cookies (10→half, 50+→full), history (100→half, 1000+→full), etc.

#### V12-GAP-11: No Calendar Data Injection
- **Problem**: Real devices have Google Calendar entries (appointments, birthdays, etc.). Currently no calendar data is forged or injected.
- **Impact**: Empty calendar is a forensic indicator for data depth analysis.
- **Fix**: Add calendar event generation to AndroidProfileForge and injection via content provider in ProfileInjector.

#### V12-GAP-12: No Notification History
- **Problem**: Real devices have notification_log entries in system settings. Currently empty.
- **Impact**: Missing notification history signals fresh device.
- **Fix**: Inject synthetic notification history into `/data/system/notification_log.db`.

### TIER 3 — Medium (Edge Cases / Robustness)

#### V12-GAP-13: Pipeline Job State Not Persisted
- **Problem**: Both `_provision_mgr` and workflow `_jobs` dict are in-memory. Server restart loses all job state.
- **Impact**: Users can't check job status after API restart.
- **Fix**: Persist to SQLite via `job_manager.py` with TTL-based cleanup.

#### V12-GAP-14: No Multi-Device Parallel Pipeline
- **Problem**: Each pipeline runs in a single thread. No mechanism to provision multiple devices simultaneously with resource-aware scheduling.
- **Impact**: Provisioning 8 devices takes 8x the time.
- **Fix**: Add thread pool with NUMA-aware CPU affinity for parallel provisioning (already have NUMA detection in DeviceManager).

#### V12-GAP-15: Workflow Engine Missing Error Recovery
- **Problem**: If a non-critical stage fails (e.g., sensor_warmup), the workflow continues but doesn't attempt recovery. No circuit breaker for flaky ADB connections.
- **Impact**: Transient ADB failures cause stage failures that could be recovered.
- **Fix**: Integrate `circuit_breaker.py` and `exponential_backoff.py` (both exist but unused in workflow_engine).

#### V12-GAP-16: Console UI Pipeline Tab Out of Sync with Backend
- **Problem**: Console UI pipeline tab hardcodes 10 phases matching provision.py pipeline, but workflow_engine has 17 stages. The UI can't display V12 stages.
- **Impact**: New V12 features invisible to users.
- **Fix**: Update console UI to dynamically render phases from API response instead of hardcoding.

#### V12-GAP-17: Device State Not Persisted Across Restarts
- **Problem**: `device_state_db.py` exists but `DeviceManager._load_state()` may not restore all device metadata (patch results, stealth scores, installed apps).
- **Impact**: After restart, devices show as "created" state even if fully provisioned.
- **Fix**: Ensure full state serialization in `_save_state()` including patch_result, stealth_score, installed_apps.

#### V12-GAP-18: No Automated Regression Testing
- **Problem**: `tests/` directory has skeleton files but minimal actual test coverage. No integration tests for the full pipeline.
- **Impact**: Code changes may break pipeline without detection.
- **Fix**: Add integration test suite that: (a) forges a profile, (b) validates JSON schema, (c) mocks ADB to test injection commands, (d) validates trust score calculation.

---

## V12 IMPLEMENTATION ROADMAP

### Phase 1 — Fix Critical V12 Stage Imports (Day 1)
**Target: Make V12 stages actually execute**

| Task | File | Effort |
|------|------|--------|
| Fix `core.` prefix imports in V12 stages | `workflow_engine.py` | 15 min |
| Fix pipeline phase numbering (0-10) | `provision.py` | 15 min |
| Verify SIMConfig constructor params | `workflow_engine.py` + `ghost_sim.py` | 30 min |
| Add Gboard APK to GApps bootstrap | `gapps_bootstrap.py` | 15 min |

### Phase 2 — Stealth Score: 91% → 96% (Day 2-3)
**Target: Fix 3 of 5 remaining stealth failures**

| Task | File | Effort |
|------|------|--------|
| Backdate GMS checkin timestamps | `anomaly_patcher.py` or `profile_injector.py` | 2 hrs |
| Dense UsageStats generation (every day) | `anomaly_patcher.py` | 3 hrs |
| Custom Cuttlefish image with OEM props | New build script | 8 hrs |

### Phase 3 — Trust Score: 84 → 92+ (Day 4-5)
**Target: Depth-weighted scoring + new data types**

| Task | File | Effort |
|------|------|--------|
| Depth-weighted trust scoring | `trust_scorer.py` | 2 hrs |
| Calendar data forge + inject | `android_profile_forge.py`, `profile_injector.py` | 3 hrs |
| Notification history injection | `profile_injector.py` | 2 hrs |
| GMS checkin timestamp aging | `profile_injector.py` | 1 hr |

### Phase 4 — Pipeline Consolidation (Day 6-8)
**Target: Single unified pipeline with 95%+ success**

| Task | File | Effort |
|------|------|--------|
| Unify provision.py pipeline with WorkflowEngine | Both files | 6 hrs |
| Integrate circuit_breaker + exponential_backoff | `workflow_engine.py` | 3 hrs |
| Persist job state to SQLite | `job_manager.py` | 2 hrs |
| Update console UI for dynamic phases | `console/index.html` | 4 hrs |
| Add VM health monitoring + auto-recovery | `device_recovery.py` | 4 hrs |

### Phase 5 — Testing & Hardening (Day 9-10)
**Target: Regression safety net**

| Task | File | Effort |
|------|------|--------|
| Integration test: forge → validate schema | `tests/` | 3 hrs |
| Integration test: inject command generation | `tests/` | 3 hrs |
| Integration test: trust score calculation | `tests/` | 2 hrs |
| E2E smoke test with mock ADB | `tests/e2e/` | 4 hrs |

---

## SUCCESS CRITERIA

### Pipeline Success Rate: 95%+
- [ ] V12 stages execute without import errors
- [ ] Pipeline completes all 10+ phases on healthy Cuttlefish VM
- [ ] Transient ADB failures auto-recover via circuit breaker
- [ ] Job state persists across API restarts

### Stealth Score: 96%+
- [ ] GMS checkin timestamp aged to match profile
- [ ] UsageStats covers every day in device age range
- [ ] Gboard installed via bootstrap
- [ ] Custom system image with OEM props (stretch goal — 98%+)

### Trust Score: 92+/100
- [ ] Depth-weighted scoring rewards rich profiles
- [ ] Calendar events injected
- [ ] Notification history present
- [ ] All 14 existing checks still pass

### Operational Reliability
- [ ] VM auto-recovery on crash/hang
- [ ] Parallel provisioning for multi-device
- [ ] Console UI reflects all pipeline stages
- [ ] Integration tests prevent regressions

---

## QUICK WINS (Can implement immediately)

1. **V12-GAP-01** — Fix import paths: `s/from core\./from /` in 5 lines of `workflow_engine.py`
2. **V12-GAP-02** — Add phase 10 to pipeline phases list in `provision.py`
3. **V12-GAP-09** — Download Gboard APK to `/opt/titan/data/gapps/`
4. **V12-GAP-07** — Backdate `lastCheckinTimeMs` in profile_injector post-injection
5. **V12-GAP-10** — Add depth multipliers to trust_scorer.py check weights
