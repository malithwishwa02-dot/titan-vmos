---
name: genesis-engine
description: "Use when: working on the Genesis engine, pipeline phases, VMOS Cloud APIs, device provisioning, device scoring, Google Pay injection, wallet injection, purchase validation, or stealth operations."
---

# Genesis Engine & VMOS Titan Development Skill

This skill provides mandatory background knowledge and constraints for developing on the Genesis Pipeline in the Titan V13 workspace (`main.js`).

## 1. VMOS Cloud API Strict Constraints (CRITICAL)

The VMOS Cloud API is extremely fragile. **ANY violation of these rules will brick devices and cause 2/100 scoring failures.**

*   **NEVER USE `updatePadAndroidProp`**: It queues background tasks that trigger device restarts (`status=12`), breaking subsequent shell commands and scoring.
*   **NEVER USE `replacePad`**: It always triggers a device restart (even with `wipeData: 0`).
*   **Shell Commands (`syncCmd`)**: Are the ONLY safe way to inject props. Use `resetprop`/`setprop` in large batched shell scripts.
    *   Shell only works when `padStatus=10` (Running).
    *   Returns empty string on any failure, rebooting, or if `padStatus` is 11, 12, or 14.
*   **Safe APIs (No reboot)**: `updateSIM`, `gpsInjectInfo`, `updateTimeZone`, `updateLanguage`, `syncCmd`, `updateContacts`, `addPhoneRecord`, `setKeepAliveApp`, `setHideAccessibilityAppList`, `switchRoot`, `updatePadProperties`, `infos`, `restart`.
*   **Status Codes**: `10`=Running, `11`=Booting, `12`=Resetting, `14`=Stopped. To recover from 14: `restart` exactly once, wait patiently for 11->10.

## 2. API Request Signature Rules

*   Must use explicit VMOS headers:
    *   `VMOS_HOST = 'api.vmoscloud.com'`
    *   `VMOS_SERVICE = 'armcloud-paas'` (NOT 'vcpcloud')
    *   `VMOS_CT = 'application/json;charset=UTF-8'` (Uppercase UTF-8, no spaces)
    *   `VMOS_SH = 'content-type;host;x-content-sha256;x-date'` (Alphabetical order)
*   Database transfers via `syncCmd` over ADB must be base64 chunked (as implemented in `_createAndTransferDb`).

## 3. Pipeline Phases (main.js Titan V13)

When extending the pipeline, map your changes to the correct phase:
*   **Phase 0**: Readiness Check & Boot Management.
*   **Phase 1**: Identity Injection (Baseband, Model, Build, Network props via `resetprop` batches).
*   **Phase 2**: Stealth Operations (Root switch, Magisk hide, Xposed config).
*   **Phase 3**: Network Proxy & VPN configuration.
*   **Phase 4/5**: Profile & Account injection (Google Accounts, GMS sync).
*   **Phase 6**: App Data Injection & Forging. Includes Contacts, SMS, Media DB, Downloads, Usage Stats, and Browser Cookies.
*   **Phase 7/8/9**: Purchase Validation & Wallet Injection (Google Pay `tapandpay.db`, Play Store `COIN.xml`, Chrome Web Data Autofill, GMS billing state sync).
*   **Phase 10**: Final Attestation & Snapshot.
*   **Phase 11**: Scoring (36 checks across Identity, System, Browser, Communication, Activity, Payment, Trust). Target score is 100.

## 4. Wallet & Purchase Validation Capabilities

Genesis injects tokens directly without UI automation (Zero-Auth mode):
*   **Google Pay**: `tapandpay.db` receives TSP-assigned Token BIN DPANs (e.g. `489537`), LUK+ARQC EMV keys, and synthetic transaction history.
*   **Play Store**: Inject `COIN.xml` to bypass first-time OTP/auth prompts.
*   **Chrome Autofill**: Inject credit cards via SQLite directly into Web Data base.
*   **GMS Billing**: Sync state via `wallet_instrument_prefs.xml` and `payment_profile_prefs.xml`.

When requested to update wallet capabilities, always check `purchase-validation/*` markdown files for the architecture.

## 5. Development Workflow

1.  Keep changes contained to batched shell commands where possible.
2.  Do not add artificial delays that could cause `vpost` timeouts (hardcoded 30s max).
3.  Check application execution success by parsing the output of the echo marker (e.g., `echo SUCCESS_PHASE_1`).
