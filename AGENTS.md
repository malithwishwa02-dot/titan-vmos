# AGENTS.md - Titan V13

This guide provides essential knowledge for AI agents to be productive in the Titan V13 codebase.

## Architecture Overview

The Titan V13 platform is a sophisticated Android virtualization system. Its architecture consists of three main components:

1.  **FastAPI Backend (`server/`)**: A Python-based API that orchestrates the entire system. It manages device lifecycle, stealth patching, data injection, and more. Key file: `server/titan_api.py`.
2.  **Cuttlefish Android VMs**: KVM-based virtual machines that provide high-fidelity Android environments. Managed by `core/device_manager.py`.
3.  **Web Console (`console/`)**: An Alpine.js and Tailwind CSS single-page application for monitoring and controlling the device fleet.

The system is designed to run on a Linux (Ubuntu) host, typically on a Hostinger KVM VPS.

## Core Modules & Concepts

-   **`core/device_manager.py`**: The heart of the system, responsible for creating, configuring, and managing Cuttlefish VMs.
-   **`core/anomaly_patcher.py`**: A critical 26-phase module that applies stealth patches to VMs to evade detection. It masks virtualization artifacts and forges a realistic device identity.
-   **`core/android_profile_forge.py`**: The "Genesis Forge" creates realistic, aged user profiles with circadian-weighted activity patterns.
-   **`core/profile_injector.py`**: Injects the forged profiles into the Android VMs using a robust 8-phase protocol. It uses SQLite batch injection for performance.
-   **`core/device_agent.py`**: An AI agent that uses an LLM (Ollama) to perform tasks on the device using a "See-Think-Act" loop.

## Genesis V3 Nexus Modules

The V3 pipeline introduces real OAuth tokens, host-side DB building, and stochastic behavioral aging:

-   **`core/google_master_auth.py`**: Real OAuth token acquisition via gpsoauth master token flow (11 scopes). Uses app-specific passwords for 2FA accounts.
-   **`core/vmos_db_builder.py`**: Host-side SQLite DB construction (accounts_ce, tapandpay, library). Required because VMOS lacks sqlite3 binary.
-   **`core/vmos_file_pusher.py`**: Chunked base64 Bridge Protocol for VMOS file transfer within 4KB syncCmd limit.
-   **`core/wallet_injection.py`**: Google Pay 100% injection via filesystem — tapandpay.db + COIN.xml 8-flag zero-auth configuration.
-   **`core/sensor_noise_simulator.py`**: MEMS Allan Deviation noise with GPS-IMU EKF fusion for defeating kinematic RASP analysis.
-   **`core/stochastic_aging_engine.py`**: Poisson/Markov behavioral aging with 8 persona archetypes (professional, student, night_shift, retiree, freelancer, parent, gamer, traveler).
-   **`core/attestation_proxy.py`**: TEE simulation for Play Integrity DEVICE tier (STRONG remains hardware-blocked).
-   **`core/vmos_nexus_runner.py`**: 4-phase V3 Nexus pipeline orchestrator (Recon → Synthesis → Deploy → Validate).
-   **`core/vmos_genesis_v3.py`**: V3-specific genesis integration module.

### V3 Key Concepts
-   **TSP Token BIN ranges**: Visa 489537-489539, MC 530060-530063, Amex 374800-374801 — DPANs must use these, NOT the physical card's BIN.
-   **COIN.xml 8-flag**: All flags required for zero-auth: `purchase_requires_auth`, `require_purchase_auth`, `one_touch_enabled`, `biometric_payment_enabled`, `PAYMENTS_ZERO_AUTH_ENABLED`, `device_auth_not_required`, `skip_challenge_on_payment`, `frictionless_checkout_enabled`.
-   **accounts_ce.db**: `PRAGMA user_version=10` (Android 14), ownership `system:system` (1000:1000).
-   **tapandpay.db**: Must include `token_metadata` VIEW (`CREATE VIEW token_metadata AS SELECT * FROM tokens`).
-   **LUK derivation**: `MDK = SHA256("TITAN-MK-{DPAN}")` → `UDK = HMAC(MDK, dpan+atc)` → `LUK = UDK[:32]`.

## Development Workflow

-   **Testing**: Run tests using `python -m pytest tests/ -x`.
-   **Syntax Check**: `python -c "import ast; ast.parse(open('file.py').read())"`
-   **Deployment**: The project is deployed to a VPS using `scp` and a deployment script. See the `Quick Start` section in `README.md`.
-   **PYTHONPATH**: The `PYTHONPATH` is `core:server`, so modules in these directories can be imported directly.

## Project Conventions

-   **ADB Operations**: Always use `adb_utils.adb_shell()` or `adb_with_retry()` for executing ADB commands. Never use raw `subprocess`.
-   **Root Access**: Use `ensure_adb_root(target)` before any privileged ADB operations.
-   **Logging**: New core modules must use `json_logger` for structured logging.
-   **API Schemas**: Use Pydantic models from `core/models.py` for all API request and response schemas.
-   **API Routers**: New API routers should be placed in `server/routers/` and registered in `server/titan_api.py`.
-   **SELinux**: After pushing files to the device, always run `restorecon -R` to preserve SELinux contexts.

## Stealth & Evasion

-   The `anomaly_patcher.py` is central to the platform's stealth capabilities. It patches over 156 detection vectors.
-   The patcher runs in multiple phases, covering device identity, telephony, anti-emulator checks, and more.
-   **Play Integrity**: The platform can pass Basic and Device Integrity checks. Strong Integrity is hardware-blocked and cannot be passed in a virtual environment.

## Data Forging & Injection

-   The Genesis Forge (`android_profile_forge.py`) creates realistic user data, including contacts, call logs, and SMS messages.
-   Activity is weighted using a circadian rhythm to appear more human.
-   **V3 Stochastic Aging**: `stochastic_aging_engine.py` replaces static circadian with Poisson processes and Markov chains across 8 persona archetypes.
-   The `profile_injector.py` uses a robust 8-phase protocol for data injection, which is significantly faster and more reliable than the old `content insert` method.
-   **V3 Host-Side DB Building**: `vmos_db_builder.py` constructs SQLite databases on the host machine (accounts_ce.db, tapandpay.db, library.db) and pushes them via Bridge Protocol.

## Hardware & Real-World Limitations

Be aware of the following limitations, which are documented in `copilot-instructions.md`:

-   **Play Integrity STRONG**: Cannot be passed due to the lack of a physical TEE.
-   **NFC Payments**: The system can provision wallets, but actual NFC payments require physical hardware.
-   **Samsung Pay**: Not supported due to the Knox TEE e-fuse (Knox 0x1 = permanent).
-   **Real OAuth Tokens**: V3 uses `google_master_auth.py` (gpsoauth) for real server-validated tokens. Requires app-specific password for 2FA accounts.
-   **Chrome card_number_encrypted**: Android Keystore bound — must be NULL column; user enters manually.
-   **Stubbed Features**: Some features, like `kyc_core.py`, are stubs and not fully functional. Do not implement features that claim to work but don't.
-   **EMV Session Keys**: LUK derivation is local — real TSP integration required for actual payment authorization.

## VMOS Cloud Device Management

The platform also supports cloud Android instances via VMOS Cloud API.

-   **API Client**: `core/vmos_cloud_api.py` — async httpx with HMAC-SHA256 signing. Credentials from `.env` (`VMOS_CLOUD_AK`/`VMOS_CLOUD_SK`).
-   **Genesis Engine**: `core/vmos_genesis_engine.py` — 11-phase pipeline for cloud device identity provisioning.
-   **Expansion Tools**: `com.android.expansiontools` — system app on VMOS devices providing Root, GPS Mock, Magisk, LSPosed, Video/Image Injection toggles. Its UI **cannot** be dumped by UIAutomator.
-   **Key APIs**: `padCodes` (array) format for most endpoints. Image injection uses `injectUrl` parameter. Per-app root via `switchRoot` with `rootType=1` + `packageName`.
-   **Known Broken**: `simulate_click_humanized` (404), `instance_details` (404), `updatePadAndroidProp` (triggers restart), `replacePad` (always restarts).
-   **ADB Recovery**: When ADB commands return `status=-1`, use `instance_restart()`. Device transitions status 14→10 in ~20 seconds.
-   **Known Instances**: ACP250329ACQRPDV (new, Android 15), ACP2507296TM25XE (new, Android 15). Bricked: ACP2509244LGV1MV, ACP5CF4Z11Z67PQA.
-   **CRITICAL CRASH RULES**:
    -   **NEVER** `pm disable-user com.cloud.rtcgesture` — causes permanent status=11 (bricked, unrecoverable without reset)
    -   **NEVER** `pm disable-user com.android.expansiontools` — may brick the device
    -   **NEVER** mount tmpfs over `/system/priv-app/` — breaks PackageManagerService
    -   **NEVER** mass chmod on `/sys/block/` — 679 loop devices, sysfs is kernel read-only, timeout causes crash
    -   **NEVER** rapid-fire async_adb_cmd calls (<3s apart) — triggers 110031 cascade → status=14
    -   Space all ADB commands ≥3s apart; batch related commands into single shell strings
    -   VMOS `/system` is device-mapper (dm-6) protected — `remount rw` ALWAYS fails
-   **Safe Stealth**: tmpfs at `/dev/.sc`, bind-mount `/proc/cmdline`, `resetprop --delete`, `rmmod selinux_leak_fix`, iptables, process comm rename
-   **VMOS Architecture**: Devices are Linux namespace containers on Rockchip RK3588 ARM boards (NOT VMs/emulators)
-   **Property Namespaces**: Core IDs (`ro.sys.cloud.android_id`, `persist.sys.cloud.imeinum/iccidnum/imsinum`), DRM (`persist.sys.cloud.drm.id/puid`), GPU (`persist.sys.cloud.gpu.gl_vendor/gl_renderer/gl_version`), WiFi (`persist.sys.cloud.wifi.ssid/mac/ip/gateway/dns1`), Cellular (`persist.sys.cloud.cellinfo` hex: type 9=5G NR), Proxy (`ro.sys.cloud.proxy.mode/type/data`), Environment (`persist.sys.cloud.battery.capacity/level`, `boottime.offset`, `ro.sys.cloud.rand_pics`, `persist.sys.cloud.pm.install_source`)
-   **Sensor Simulation**: `persist.sys.cloud.sensor.tpl_dp` points to UTF-8 data file (up to 1GB) with sequential sensor readings + `delay:N` commands. Supports accelerometer, gyroscope, magnetometer, proximity, light, pressure, temperature, humidity, step-counter, heart-rate, hinge-angle (foldable)
-   **Xposed/LSPosed Hooks**: `apmt patch add -n <name> -p <package> -f <path>` — entry class `androidx.app.Entry`; app-level via `appMain`, system-level via `systemMain` (target package `"android"`, reboot required)
-   **Hardware Tiers**: V08 ($4.99/mo, 4GB), V06 ($6.99/mo, 5.4GB), V04 ($8.99/mo, 8GB), V03 ($10.99/mo, 10.7GB), Premium Real ($13.99/mo, 12GB), Real Device Test ($0.20/min)
-   **Client SDKs**: Android (`armcloudsdkv3:1.1.4`, Maven `maven.vmos.cn`), Web H5 (`armcloud-rtc` npm), Windows PC (C++ DLL)

