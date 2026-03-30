---
name: genesis-engine
description: "Use when: working on the Genesis engine, pipeline phases, VMOS Cloud APIs, device provisioning, device scoring, Google Pay injection, wallet injection, purchase validation, stealth operations, trust scoring, payment history forging, zero-auth OTP bypass, 3DS strategy, Chrome autofill, GMS billing, or any Genesis pipeline development."
---

# Genesis Engine & VMOS Titan Development Skill

This skill provides mandatory background knowledge and constraints for developing on the Genesis Pipeline across all three engine implementations.

---

## 1. Three Engine Implementations

### 1A. Electron App — `vmos-titan/main.js` (3786 lines)
- Built-in Node.js HTTP server on port 8082
- 12 pipeline phases (0–11), runs against VMOS Cloud API
- HMAC-SHA256 signing via `_vmosSign()`, `vmosPost()`, `vmosGet()`
- Genesis jobs stored in `_genesisJobs` Map (in-memory)
- Entry: `_runGenesisJob(jobId, ak, sk)` — fully self-contained
- Validator: `vmos-titan/validators.js` (317 lines) — Luhn CC check, E.164 phone, email, SSRF proxy filter, SQL sanitization
- Device presets table: `DEVICE_PRESETS` with `samsung_s24`, `pixel_8_pro`, etc.
- Supported countries: US, GB, DE, FR, CA, AU (with per-country carrier/location/merchant configs)

### 1B. VMOS Python Engine — `core/vmos_genesis_engine.py` (1829 lines)
- 11-phase async pipeline: `VMOSGenesisEngine.run_pipeline(cfg)`
- Uses `VMOSCloudClient` from `core/vmos_cloud_api.py`
- ADB via `async_adb_cmd` + task polling (`_sh()`, `_sh_ok()` helpers)
- Router: `server/routers/vmos_genesis.py` (`/api/vmos-genesis/*`)
- PipelineConfig dataclass mirrors PipelineBody

### 1C. Unified Local Engine — `core/unified_genesis_engine.py` (1482 lines)
- 16-phase pipeline for Cuttlefish VMs (local ADB)
- Uses all core modules: AnomalyPatcher (26 phases), WalletProvisioner, ProfileInjector, SensorSimulator, ImmuneWatchdog
- Router: `server/routers/unified_genesis.py` (`/api/unified-genesis/*`)
- GenesisConfig with sub-configs: PersonaConfig, PaymentConfig, GoogleConfig, DeviceConfig, AgingConfig, ExecutionOptions
- Country profiles for US/GB/DE/FR/CA/AU with popular apps, banks, merchants

---

## 2. VMOS Cloud API Strict Constraints (CRITICAL)

The VMOS Cloud API is extremely fragile. **ANY violation of these rules will brick devices and cause 2/100 scoring failures.**

### NEVER-USE APIs (Cause Device Reboot)
- **`updatePadAndroidProp`**: Queues background tasks → device restart (status=12) → all shell commands fail → 2/100 score
- **`replacePad`**: Always triggers device restart even with `wipeData: 0`

### Safe Method: Shell via `syncCmd`
- `resetprop` for `ro.*` properties, `setprop` for `persist.*` properties
- Only works when `padStatus=10` (Running)
- Returns empty string `""` on ANY failure (silent failure — E-07)
- **4KB character limit** per `syncCmd` request (E-08) — split into ~4 batches of ~16 props each
- Use echo markers for success verification: `echo PHASE1_OK`

### Safe APIs (No Reboot)
`updateSIM`, `gpsInjectInfo`, `updateTimeZone`, `updateLanguage`, `syncCmd`, `updateContacts`, `addPhoneRecord`, `setKeepAliveApp`, `setHideAccessibilityAppList`, `switchRoot`, `updatePadProperties`, `infos`, `restart`, `setProxy`, `resetGAID`, `setWifiList`, `injectPicture`, `simulateSendSms`

### Instance Status Codes
| Code | State | Action |
|------|-------|--------|
| 10 | Running | Safe to operate |
| 11 | Booting | **DO NOT restart** — causes 11↔14 loop (E-09) |
| 12 | Resetting | Wait 15-30 min, no action needed |
| 14 | Stopped | Send ONE restart, wait for 11→10 |

### API Signature Constants (E-11)
```
VMOS_HOST    = 'api.vmoscloud.com'
VMOS_SERVICE = 'armcloud-paas'      ← NOT 'vcpcloud'
VMOS_CT      = 'application/json;charset=UTF-8'  ← no space, uppercase UTF
VMOS_SH      = 'content-type;host;x-content-sha256;x-date'  ← alphabetical
```

### 404 Endpoints (Do Not Exist — E-10)
`shutdown`, `boot`, `stop`, `start`, `startPad`, `powerOn`, `powerOff`, `rebootPad`, `recoverPad`, `resetPad`, `forceStart`, `forceRestart`, `cancelTask`, `padDetails` — use `/infos` + search instead

---

## 3. Pipeline Phase Map (All Engines)

### main.js (Electron — 12 Phases)
| Phase | Name | Key Operations |
|-------|------|----------------|
| 0 | Pre-Flight | `/infos` status check, boot poll, shell+resetprop verify |
| 1 | Wipe + Identity | Shell data wipe, 4-batch resetprop (~65 props), SIM API, GPS API |
| 2 | Stealth Patch | Identity reinforcement, root hiding, prop scrub, proc sterilization, boot alignment |
| 3 | Network/Proxy | SOCKS5/HTTP proxy via API, SSRF validation, checkIP verify |
| 4 | Forge Profile | `AndroidProfileForge.forge()` via Python subprocess, or inline generation |
| 5 | Google Account | accounts_ce/de.db SQLite, GMS device_registration, GSF gservices, Play Store finsky, Chrome Preferences, Gmail/YouTube/Maps prefs |
| 6 | Inject | Contacts (content insert), call logs, SMS, WiFi (API), Chrome cookies/history (sqlite3), autofill, UsageStats aging, gallery (injectPicture API), battery, GAID reset |
| 7 | Wallet/GPay | tapandpay.db (5 tables), COIN.xml (6 zero-auth flags), Chrome credit_cards, GMS billing prefs, NFC prefs, bank SMS, purchase history bridge |
| 8 | Provincial | Per-app SharedPrefs (country-specific targets) |
| 9 | Post-Harden | Kiwi preferences, media scan, app restart cycle, contacts fix |
| 10 | Attestation | Keybox check, verified boot state, build type, qemu exposure |
| 11 | Trust Audit | 16-check scoring (max 100), grade A+/A/B+/B/C/D/F |

### vmos_genesis_engine.py (Python — 11 Phases)
Same structure as main.js phases 0–10 (no separate wipe+identity split)

### unified_genesis_engine.py (Local — 16 Phases)
| Phase | Name | Unique to Local |
|-------|------|------------------|
| 0 | Pre-Flight Check | ADB connectivity validation |
| 1 | Factory Wipe | |
| 2 | Stealth Patch | Full 26-phase AnomalyPatcher (103+ vectors) |
| 3 | Network Config | IPv6 kill + tun2socks/redsocks/global proxy/VPN app cascade |
| 4 | Forge Profile | |
| 5 | Payment History | PaymentHistoryForge + PurchaseHistoryBridge |
| 6 | Google Account | GoogleAccountInjector (8 targets, 12 OAuth scope tokens) |
| 7 | Profile Inject | ProfileInjector (SQLite batch) |
| 8 | Wallet Provision | WalletProvisioner (5 subsystems) |
| 9 | App Bypass | Provincial layering (AppDataForger) |
| 10 | Browser Harden | Kiwi/Chrome sign-in markers |
| 11 | Play Integrity | PlayIntegritySpoofer (BASIC/DEVICE/STRONG tiers) |
| 12 | Sensor Warmup | SensorSimulator OADEV-coupled noise |
| 13 | Immune Watchdog | Honeypot deploy, process cloaking |
| 14 | Trust Audit | TrustScorer (14 checks, max 100) |
| 15 | Final Verify | Complete verification report |

---

## 4. Wallet Injection Architecture (5 Subsystems)

Genesis injects payment data directly via filesystem without triggering Google/TSP/bank authentication (Zero-Auth mode). This works because Android trusts filesystem data within the app sandbox — there are no row-level signatures in `tapandpay.db`.

### Subsystem 1: Google Pay — `tapandpay.db` (5 Tables)
Injected into BOTH paths:
- `/data/data/com.google.android.gms/databases/tapandpay.db`
- `/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db`

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `token_metadata` | dpan, last_four, network, token_ref, display_name, is_default, token_state, provisioning_status, expiry | Primary card display |
| `tokens` | token_data, pan_last_four, network_id, token_state | Token data record |
| `emv_metadata` | dpan, luk_seed, atc, derivation_type | EMV contactless params |
| `transaction_history` | transaction_id, amount_cents, merchant_name, timestamp_ms, dpan, status | 5-15 past transactions |
| `payment_instrument` | instrument_id, display_name, network, last_four, is_active | Instrument registration |

**DPAN generation**: Use TSP-assigned Token BIN ranges, NOT random digits:
- Visa: 489537-489539, 440066-440067
- Mastercard: 530060-530065
- Amex: 374800-374801
- Discover: 601156-601157

**LUK derivation**: 3-stage HMAC-SHA256 chain: `MDK = SHA256("TITAN-MK-{DPAN}")` → `UDK = HMAC(MDK, dpan+atc)` → `LUK = UDK[:32]`

**Ownership fix**: Must `chown` to the app's UID (`stat -c '%u:%g' /data/data/com.google.android.gms/`) and `restorecon -R`.

### Subsystem 2: Play Store — `COIN.xml` (6 Zero-Auth Flags)
Path: `/data/data/com.google.android.gms/shared_prefs/COIN.xml`

**All 6 flags are REQUIRED for zero-auth purchasing:**
```xml
<boolean name="has_payment_methods" value="true" />
<string name="default_instrument_id">instrument_1</string>
<boolean name="wallet_enabled" value="true" />
<boolean name="purchase_requires_auth" value="false" />
<boolean name="one_touch_enabled" value="true" />
<boolean name="biometric_payment_enabled" value="true" />
<string name="auth_token">{64-char-hex}</string>
```
Without `purchase_requires_auth=false`, Play Store purchases prompt for Google password. Without `one_touch_enabled`, confirmation dialog appears.

### Subsystem 3: Chrome Autofill — `Web Data` SQLite
Path: `/data/data/com.android.chrome/app_chrome/Default/Web Data` (and Kiwi browser equivalent)
- `credit_cards` table: `card_number_encrypted` must be `NULL` (cannot inject encrypted — Android Keystore bound)
- ~85% visibility rate (user enters card number on first checkout)

### Subsystem 4: GMS Billing State
- `wallet_instrument_prefs.xml`: wallet_setup_complete, active_instrument_id, network, last4, added_timestamp
- `payment_profile_prefs.xml`: payment_methods_synced, payment_profile_email, payment_profile_active

### Subsystem 5: NFC + Bank SMS
- NFC: `settings put secure nfc_on 1`, `nfc_payment_foreground 1`, `nfc_on_prefs.xml` in wallet app
- Bank SMS: Inject 3-5 transaction alert messages from real issuer short codes (Chase=33789, BofA=73981, CapOne=227462, Citi=95686, Amex=26297, Discover=347268)

### Cloud Sync Defense (5-Layer)
After wallet injection, block Google from overwriting data:
1. `am force-stop` target apps
2. `appops set RUN_IN_BACKGROUND deny`
3. `iptables` UID-based block (local pipeline)
4. `iptables-save` persistence
5. GMS targeted sync blocking for `payments.google.com`

---

## 5. Purchase History Bridge — Cross-Store Coherence

The `PurchaseHistoryBridge` generates temporal coherence between wallet transactions and browser activity. Without this, anti-fraud SDKs (ThreatMetrix, Sardine, Sift) detect incoherent purchase signals.

**Generates:**
- Chrome commerce cookies (Amazon `session-id`, Walmart `auth`, eBay `nonsession`, etc.)
- Chrome purchase confirmation URLs (`amazon.com/order/{id}`, `walmart.com/order/{id}`)
- Temporal correlation: cookie creation times align with tapandpay transaction timestamps
- Merchant database: 7 merchants with name, domain, cookies, amount ranges

---

## 6. Trust Scoring

### Local Pipeline (trust_scorer.py — 14 checks, max raw 108, scaled to 100)
```
Google Account (15) · Chrome Cookies (10) · Chrome History (10) ·
Wallet/Payment (10) · Contacts (8) · Call Logs (8) · SMS (8) ·
Gallery (8) · Autofill (7) · WiFi (5) · App Installs (5) ·
GMS Prefs (5) · Device Props (3) · Behavioral Depth (3)
```
Plus Life-Path Coherence Score (0-10 bonus): 5 cross-dimensional checks including purchases↔cookies (20% weight)

### VMOS Engine (inline — 16 checks, max 100)
```
Accounts (12) · Cookies (8) · History (8) · tapandpay (8) ·
Contacts≥5 (7) · Calls≥10 (7) · SMS≥5 (6) · UsageStats (5) ·
Autofill (4) · PlayStore prefs (6) · Kiwi configured (4) ·
GMS Registration (5) · GSF ID (5) · WiFi (5) · Build Type (5) ·
No VMOS Leak (5)
```

### Grades
A+ ≥95, A ≥90, B+ ≥80, B ≥70, C ≥60, D ≥50, F <50

### WalletVerifier (13 checks — local pipeline only)
tapandpay exists (dual-path) · Token count ≥1 · Token status · NFC prefs · COIN.xml payment method · COIN.xml auth disabled · Chrome Web Data · GMS wallet synced · GMS payment profile · Keybox loaded · GSF fingerprint · tapandpay ownership · System NFC enabled

---

## 7. Google Account Injection (8 Targets)

| # | Target | Path | What |
|---|--------|------|------|
| 1 | accounts_ce.db | `/data/system_ce/0/accounts_ce.db` | Account name, type `com.google`, OAuth tokens, GAIA ID |
| 2 | accounts_de.db | `/data/system_de/0/accounts_de.db` | Device-encrypted account entry |
| 3 | GMS shared_prefs | `com.google.android.gms/shared_prefs/device_registration.xml` | Device registered timestamp, android_id |
| 4 | GSF shared_prefs | `com.google.android.gsf/shared_prefs/gservices.xml` | GSF android_id, registration timestamp |
| 5 | Play Store | `com.android.vending/shared_prefs/finsky.xml` | signed_in_account, setup_complete |
| 6 | Chrome Preferences | `{browser}/app_chrome/Default/Preferences` | account_info JSON, sync state |
| 7 | Gmail | `com.google.android.gm/shared_prefs/account_prefs.xml` | signed_in_account |
| 8 | YouTube/Maps | `com.google.android.youtube`, `.apps.maps` | Account preference |

**Critical**: `accounts_ce.db` must have correct `PRAGMA user_version = 10` for Android 14, or `system_server` will crash and recreate it empty. **Ownership**: Must be `system:system` (1000:1000) with `chmod 600`.

---

## 8. Stealth Operations

### AnomalyPatcher (26+ Phases — Local Only)
identity → telephony → anti_emulator → build_verification → rasp_evasion → gpu_graphics → battery → location → media_history → network → gms_integrity → keybox_attestation → gsf_alignment → sensors → bluetooth → proc_sterilize → camera → nfc_storage → wifi_scan → selinux → storage_encryption → process_stealth → audio → kinematic_input → kernel_hardening → persistence → oem_props → default_config → usagestats → media_storage → adb_concealment

### VMOS Stealth (Shell-Only — 10 Sub-Phases)
1a. Android props (4 batches via resetprop) · 1b. SIM (API) · 1c. GPS (API) · 1d. TZ+Lang · 1e. Root hiding (su bind-mount, Magisk hide) · 1f. Cloud/emulator prop scrub (delete ro.vmos.*, ro.kernel.qemu, etc.) · 1g. Proc sterilization (/dev/.sc bind-mounts) · 1h. Boot fingerprint alignment · 1i. NFC enable · 1j. VMOS artifact scrub

### Proc Sterilization
- `/proc/cmdline`: sed-scrub cuttlefish/vsoc/virtio/goldfish/qemu/vmos/redroid/armcloud → bind-mount from `/dev/.sc/cmdline`
- `/proc/mounts`: grep -v emulator keywords → bind-mount
- `/proc/1/cgroup`: Replace with `0::/` → bind-mount

---

## 9. Profile Forge (AndroidProfileForge)

Generates complete persona data with circadian-weighted timestamps:

| Data Type | Typical Count (120d) | Circadian Pattern |
|-----------|---------------------|-------------------|
| Contacts | 268+ | — |
| Call logs | 368+ | Peak 9am, 12pm, 6pm |
| SMS messages | 180+ | Peak 10am-2pm |
| Chrome history | 5,099+ | 7am-midnight |
| Chrome cookies | 72+ | Follows history |
| Gallery photos | 312+ | 10am-6pm |
| WiFi networks | 24+ | — |
| Play purchases | 21+ | Evening bias |

Archetypes: professional (9-5 peaks), student (late morning/evening), retired (daytime spread)

---

## 10. Key Source Files

| File | Lines | Role |
|------|-------|------|
| `vmos-titan/main.js` | 3786 | Electron app + built-in API server + Genesis runner |
| `vmos-titan/validators.js` | 317 | Input validation (Luhn, E.164, SSRF, SQL sanitize) |
| `core/vmos_genesis_engine.py` | 1829 | VMOS Cloud pipeline (11 phases) |
| `core/unified_genesis_engine.py` | 1482 | Local Cuttlefish pipeline (16 phases) |
| `core/anomaly_patcher.py` | 3555 | 26-phase stealth patcher (103+ vectors) |
| `core/wallet_provisioner.py` | 1585 | 5-subsystem wallet injection |
| `core/wallet_verifier.py` | 339 | 13-check post-wallet verification |
| `core/purchase_history_bridge.py` | 368 | Chrome commerce cookie/history coherence |
| `core/android_profile_forge.py` | 2201 | Persona generation with circadian weighting |
| `core/profile_injector.py` | 2022 | 8-phase SQLite batch injection |
| `core/google_account_injector.py` | 723 | 8-target Google account injection |
| `core/trust_scorer.py` | 436 | 14-check trust scoring (0–100) |
| `core/workflow_engine.py` | 900 | V12 device aging orchestrator |
| `core/vmos_cloud_api.py` | 858 | Async VMOS Cloud API client |
| `core/vmos_edge_api.py` | 848 | VMOS Edge Container+Control client |
| `core/device_presets.py` | — | Samsung/Pixel/generic device fingerprints |
| `server/routers/unified_genesis.py` | 572 | `/api/unified-genesis/*` |
| `server/routers/vmos_genesis.py` | 196 | `/api/vmos-genesis/*` |
| `server/routers/provision.py` | 1187 | `/api/genesis/*` (V12 pipeline) |

### Reference Documentation
- `purchase-validation/` — 11 docs covering all 5 wallet subsystems
- `purchase-validation/GENESIS-CC-INJECTION-RESEARCH.md` — Deep technical analysis of why zero-auth works
- `GENESIS-PIPELINE-TECHNICAL-REPORT.md` — Full pipeline technical analysis
- `GENESIS-VMOSPRO-TECHNICAL-ANALYSIS.md` — Gap analysis: 23 gaps between local/VMOS engines
- `VMOS-API-ERRORS-AND-DEBUGGING-LOG.md` — 12 documented API errors with fixes

---

## 11. Hardware-Blocked Limitations

These **cannot be fixed** in software:
- **Play Integrity STRONG**: Requires physical TEE (RKA proxy to hardware device)
- **NFC contactless payments**: No physical antenna (tapandpay.db appears in UI only)
- **Samsung Pay**: Knox TEE e-fuse barrier
- **Real OAuth tokens**: Requires actual Google auth flow (filesystem tokens are synthetic)
- **Real EMV session keys**: Requires TSP integration (synthetic keys for display only)
- **Chrome card_number_encrypted**: Android Keystore encryption (NULL column — user enters on first checkout)

---

## 12. Development Rules

1. **Shell-only for props** — NEVER use `updatePadAndroidProp` or `replacePad`
2. **4KB batch limit** — Split resetprop commands into 4 batches with echo markers
3. **No artificial delays** — `vmosPost` has 30s hardcoded timeout (120s max with E-06 fix)
4. **Echo markers** — Every shell command must end with `echo PHASE_NAME_OK` for success verification
5. **Dual-path wallet** — Always inject tapandpay.db into BOTH GMS and walletnfcrel paths
6. **Ownership after injection** — `chown` to app UID + `restorecon -R` after all SQLite/SharedPrefs writes
7. **Post-injection app restart** — Force-stop then restart target apps so they pick up injected data
8. **UUID coherence** — instrument_id must match across tapandpay.db, COIN.xml, wallet_instrument_prefs, and payment_profile_prefs
9. **Read `purchase-validation/*`** — Always check these docs before modifying wallet/payment code
10. **Validate with WalletVerifier** — Run 7-point (VMOS) or 13-check (local) verification after wallet injection
