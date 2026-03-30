# Genesis Pipeline × VMOS Pro Cloud — Technical Analysis & Gap Report

> **Version:** Titan V13.0  
> **Date:** 2026-03-28  
> **Scope:** Cross-reference of purchase validation documentation (9 docs + research report) against the VMOS Genesis Engine (`core/vmos_genesis_engine.py`), Unified Genesis Engine (`core/unified_genesis_engine.py`), and VMOS Cloud API client (`core/vmos_cloud_api.py`)  
> **Objective:** Identify all functional gaps between what the documentation describes and what the VMOS cloud engine actually implements, then provide fixes

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Comparison: Local vs VMOS Cloud Genesis](#2-architecture-comparison)
3. [Phase-by-Phase Cross-Reference](#3-phase-by-phase-cross-reference)
4. [Purchase Validation Gap Matrix](#4-purchase-validation-gap-matrix)
5. [Wallet Injection Gap Analysis](#5-wallet-injection-gap-analysis)
6. [Trust Scorer Divergence](#6-trust-scorer-divergence)
7. [Zero-Auth & OTP Bypass Gaps](#7-zero-auth--otp-bypass-gaps)
8. [Purchase History Bridge — Missing in VMOS Engine](#8-purchase-history-bridge)
9. [Verification & Post-Injection Gaps](#9-verification--post-injection-gaps)
10. [Critical Fixes Applied](#10-critical-fixes-applied)
11. [Remaining Hardware-Blocked Limitations](#11-remaining-hardware-blocked-limitations)
12. [Recommended Execution Order (VMOS Pro)](#12-recommended-execution-order)

---

## 1. Executive Summary

The VMOS Genesis Engine (`core/vmos_genesis_engine.py`, 1366 lines, 11 phases) is a functional translation of the local-ADB Genesis pipeline into VMOS Cloud API calls. However, cross-referencing against the **purchase validation documentation** (10 documents, ~4400 lines) and the **Unified Genesis Engine** (1483 lines, 16 phases) reveals **23 functional gaps** — 7 critical, 9 high, 7 medium.

### Key Findings

| Category | Local Pipeline | VMOS Genesis | Gap Severity |
|----------|:-------------:|:------------:|:------------:|
| Stealth Patch Phases | 26 phases (anomaly_patcher) | 7 sub-phases (inline ADB) | **CRITICAL** — 19 phases missing |
| Wallet Injection Targets | 5 subsystems (WalletProvisioner) | 3 targets (inline sqlite3) | **CRITICAL** — 2 targets missing |
| Purchase History Bridge | Full (chrome + cookies + receipts + notifications) | **Not implemented** | **CRITICAL** |
| Trust Score Checks | 14 weighted checks (trust_scorer.py) | 16 custom checks (inline) | **HIGH** — different weights, missing life-path |
| Zero-Auth Flags | 6 flags in COIN.xml | 3 flags in COIN.xml | **HIGH** — 3 zero-auth flags missing |
| Wallet Verification | 13-check WalletVerifier | No verification | **HIGH** |
| Google Account Injection | 8 subsystem targets | 4 targets (CE/DE/GMS/GSF) | **HIGH** — 4 targets missing |
| Play Integrity Defense | 3-tier (RKA/TEEsim/static keybox) | Property-only check | **HIGH** |
| Provincial Layering | AppDataForger (country-specific) | Simple SharedPrefs | **MEDIUM** |
| Sensor Warmup | SensorSimulator OADEV daemon | Not implemented | **MEDIUM** |
| Immune Watchdog | 654-line defense system | Not implemented | **MEDIUM** |
| Pre-Flight Checks | Storage + RAM + root | ADB alive only | **MEDIUM** |
| Post-Injection App Restart | Force-stop + restart cycle | Not implemented | **MEDIUM** |
| Browser Harden | Kiwi prefs + media scan | Kiwi prefs + media scan | ✅ Parity |
| Contact/SMS/Call Injection | content insert + native API | content insert + native API | ✅ Parity |
| GPS/SIM/Timezone | VMOS native API | VMOS native API | ✅ Parity |

---

## 2. Architecture Comparison

### Local Genesis Pipeline (Cuttlefish)

```
┌─────────────────────────────────────────────────────┐
│                  Local ADB Pipeline                   │
├─────────────────────────────────────────────────────┤
│  provision.py → anomaly_patcher.py (26 phases)       │
│              → profile_injector.py (13 sub-phases)   │
│              → wallet_provisioner.py (5 targets)     │
│              → purchase_history_bridge.py            │
│              → trust_scorer.py (14 checks)           │
│              → wallet_verifier.py (13 checks)        │
│              → immune_watchdog.py                    │
│              → sensor_simulator.py                   │
│              → app_data_forger.py                    │
│                                                      │
│  Transport: Direct ADB shell + adb push/pull         │
│  Root: adb root (userdebug)                         │
│  Speed: Instant command execution                    │
└─────────────────────────────────────────────────────┘
```

### VMOS Cloud Genesis Pipeline

```
┌─────────────────────────────────────────────────────┐
│              VMOS Cloud API Pipeline                  │
├─────────────────────────────────────────────────────┤
│  vmos_genesis_engine.py (11 phases)                  │
│    → VMOSCloudClient native APIs (props, SIM, GPS)   │
│    → async_adb_cmd for shell operations              │
│                                                      │
│  Transport: HTTPS → VMOS Cloud → ADB relay           │
│  Root: Via VMOS cloud root (switchRoot API)          │
│  Speed: 1-30s per ADB command (async poll)           │
│                                                      │
│  ⚠ NO: WalletProvisioner, PurchaseHistoryBridge,    │
│        WalletVerifier, SensorSimulator,              │
│        ImmuneWatchdog, AppDataForger                 │
└─────────────────────────────────────────────────────┘
```

### Unified Genesis Engine (Cuttlefish — V13)

```
┌─────────────────────────────────────────────────────┐
│              Unified Genesis (16 phases)              │
├─────────────────────────────────────────────────────┤
│  unified_genesis_engine.py                           │
│    → Pre-flight (ADB check)                         │
│    → Factory Wipe                                    │
│    → Stealth Patch (anomaly_patcher.py — 26 phases) │
│    → Network Config (proxy_router.py)               │
│    → Forge Profile (android_profile_forge.py)       │
│    → Payment History (payment_history_forge.py)     │
│    → Google Account (google_account_injector.py)    │
│    → Profile Inject (profile_injector.py)           │
│    → Wallet Provision (wallet_provisioner.py)       │
│    → App Bypass (app_data_forger.py)                │
│    → Browser Harden                                  │
│    → Play Integrity (attestation check)             │
│    → Sensor Warmup (sensor_simulator.py)            │
│    → Immune Watchdog (immune_watchdog.py)           │
│    → Trust Audit (trust_scorer.py)                  │
│    → Final Verify                                    │
└─────────────────────────────────────────────────────┘
```

**The VMOS Genesis Engine implements everything inline** (no imports from `wallet_provisioner`, `purchase_history_bridge`, `wallet_verifier`, etc.) because those modules depend on direct ADB file push/pull which isn't available through the VMOS Cloud API. This creates significant functional divergence.

---

## 3. Phase-by-Phase Cross-Reference

### Phase 0: Wipe

| Feature | Documentation | VMOS Engine | Unified Engine | Gap |
|---------|:------------:|:-----------:|:--------------:|:---:|
| Clear accounts_ce.db | ✅ | ✅ | ✅ | — |
| Clear accounts_de.db | ✅ | ✅ | ✅ | — |
| Clear contacts via content provider | ✅ | ✅ via `content delete` | ✅ via `rm` | — |
| Clear call_log | ✅ | ✅ | ✅ | — |
| Clear SMS | ✅ | ✅ | ✅ via `sqlite3 DELETE` | — |
| Clear Chrome data | ✅ | ✅ | ✅ | — |
| Clear tapandpay.db | ✅ GMS path | ✅ GMS path only | ✅ Wallet app + GMS | ⚠ VMOS misses wallet app path |
| Clear UsageStats | ✅ | ✅ | ✅ | — |
| Clear gallery | ✅ | ✅ | ✅ | — |
| Clear WiFi config | Not mentioned | ❌ | ✅ | ⚠ VMOS skips WiFi wipe |
| Clear app SharedPrefs | Not mentioned | ❌ | ❌ | — |

**Gaps identified:** 
- **GAP-W1**: VMOS wipe only clears `tapandpay.db` from GMS path, not from `com.google.android.apps.walletnfcrel` path
- **GAP-W2**: VMOS doesn't wipe WiFi config (`WifiConfigStore.xml`)

### Phase 1: Stealth Patch

| Feature | Docs (26 phases) | VMOS Engine | Gap |
|---------|:----------------:|:-----------:|:---:|
| Device identity props (ro.product.*) | Phase 01 | ✅ via native API | — |
| Telephony (SIM) | Phase 02 | ✅ via native API | — |
| Anti-emulator (goldfish/qemu hide) | Phase 03 | ✅ via resetprop | — |
| Build verification | Phase 04 | ✅ via resetprop | — |
| RASP evasion (Frida/Xposed/Magisk) | Phase 05 | ✅ root hiding | — |
| GPU/graphics | Phase 06 | ⚠ Only `ro.hardware.egl` | **GAP-S1**: Missing Vulkan, GPU renderer |
| Battery | Phase 07 | ✅ via native API | — |
| Location/GPS | Phase 08 | ✅ via native API | — |
| Media history | Phase 09 | ❌ Not in stealth | Handled in Phase 5 |
| Network (WiFi/BT MAC) | Phase 10 | ⚠ WiFi via API only | **GAP-S2**: Missing BT MAC |
| GMS integrity | Phase 11a | ❌ | **GAP-S3**: No GMS device profile |
| Keybox attestation | Phase 11b | ❌ No keybox injection | **GAP-S4**: CRITICAL for wallet |
| GSF alignment | Phase 11c | ⚠ Partial (gservices.xml) | GSF ID set but no CheckinService |
| Sensors | Phase 12 | ❌ | **GAP-S5**: No sensor data |
| Bluetooth | Phase 13 | ❌ | **GAP-S6**: No BT name/address |
| Proc sterilization | Phase 14 | ✅ `/proc/cmdline`, `/proc/mounts` | — |
| Camera info | Phase 15 | ❌ | Not critical for cloud |
| NFC storage | Phase 16 | ❌ | **GAP-S7**: NFC not enabled |
| WiFi scan results | Phase 17 | ❌ | Not critical — native API |
| SELinux | Phase 18 | ❌ | Not critical on VMOS |
| Storage encryption | Phase 19 | ❌ | Not critical |
| Process stealth | Phase 20 | ⚠ Root hiding only | **GAP-S8**: No ADB port hiding |
| Audio | Phase 21 | ❌ | Not critical |
| Input behavior | Phase 22 | ❌ | Not critical |
| Kernel hardening | Phase 23 | ❌ | Not critical |
| Persistence (init.d) | Phase 24 | ❌ | **GAP-S9**: Props lost on reboot |
| OEM props (~100) | Phase 25 | ❌ | **GAP-S10**: Missing Samsung Knox, vendor chain |
| Default config | Phase 26 | ❌ | Not critical |
| UsageStats | Phase 27 | ✅ In Phase 5 | — |
| Media storage | Phase 28 | ❌ | Not critical |
| ADB concealment | Phase 29 | ❌ | **GAP-S11**: ADB port exposed |

**Summary:** 19 of 26+ stealth phases are missing or incomplete in the VMOS engine. The most critical missing phases are **keybox attestation (11b)**, **NFC enablement (16)**, **OEM props (25)**, and **persistence (24)**.

### Phase 5: Inject (Contacts, Calls, SMS, etc.)

| Feature | Documentation | VMOS Engine | Unified Engine | Gap |
|---------|:------------:|:-----------:|:--------------:|:---:|
| Contacts (content insert) | ✅ SQLite batch | ✅ content insert (30 max) | ✅ | — |
| Call logs | ✅ | ✅ (80 max) | ✅ | — |
| SMS | ✅ | ✅ (30 max) | ✅ | — |
| WiFi networks | ✅ native API | ✅ native API | ✅ | — |
| Chrome cookies (sqlite3) | ✅ | ✅ (30 max) | ✅ | — |
| Chrome history (sqlite3) | ✅ | ✅ (50 max) | ✅ | — |
| Chrome localStorage | ✅ | ❌ | ✅ | **GAP-I1** |
| Autofill | ✅ | ✅ | ✅ | — |
| Battery via API | ✅ | ✅ native API | N/A (local) | — |
| GAID reset | ✅ | ✅ native API | N/A | — |
| UsageStats aging | ✅ | ✅ | ✅ | — |
| App timestamp backdating | ✅ | ✅ | ✅ | — |
| Gallery photo injection | ✅ (JPEG push) | ❌ | ✅ | **GAP-I2** |
| Play purchases (library.db) | ✅ | ❌ | ✅ | **GAP-I3** |
| Maps history | ✅ | ❌ | N/A | **GAP-I4** |

### Phase 6: Wallet / GPay

This is the **most critical divergence** from the purchase validation documentation.

| Feature | Docs (wallet_provisioner.py) | VMOS Engine | Gap |
|---------|:---------------------------:|:-----------:|:---:|
| **Target 1: tapandpay.db** | Full schema: tokens + token_metadata + emv_metadata + transaction_history + payment_instrument | Minimal: token_metadata only | **GAP-WL1: CRITICAL** |
| DPAN generation (TSP BIN) | Real TSP BIN ranges (489537-489539 Visa, 530060-530065 MC) | Random `5XXXXXX` | **GAP-WL2: CRITICAL** |
| EMV session keys (LUK + ARQC) | HMAC-SHA256 derivation chain | ❌ Not generated | **GAP-WL3: HIGH** |
| Transaction history in tapandpay | 5-15 synthetic entries | ❌ Not generated | **GAP-WL4: HIGH** |
| NFC prefs (nfc_on_prefs.xml) | Full NFC configuration | ❌ | **GAP-WL5: HIGH** |
| System NFC enable | `settings put secure nfc_on 1` | ❌ | **GAP-WL6** |
| **Target 2: Play Store (COIN.xml)** | 6 zero-auth flags | 3 flags only | **GAP-WL7: HIGH** |
| `purchase_requires_auth=false` | ✅ | ❌ Not in COIN.xml | Missing |
| `one_touch_enabled=true` | ✅ | ❌ | Missing |
| `biometric_payment_enabled=true` | ✅ | ❌ | Missing |
| `auth_token` (pre-generated) | ✅ | ❌ | Missing |
| Cloud sync blocking (iptables) | ✅ | ❌ | **GAP-WL8** |
| **Target 3: Chrome autofill** | Full credit_cards table | ✅ credit_cards | — |
| Card number encrypted | NULL (documented limitation) | Hex-encoded (worse) | **GAP-WL9** |
| **Target 4: GMS billing prefs** | wallet_instrument_prefs.xml + payment_profile_prefs.xml | COIN.xml only | **GAP-WL10: HIGH** |
| **Target 5: Bank SMS** | Issuer-specific SMS (Chase 33789, BoA 73981) | ❌ | **GAP-WL11: HIGH** |
| **Dual-path tapandpay** | Wallet app + GMS fallback | GMS only | **GAP-WL12** |
| tapandpay.db ownership fix | chown wallet_uid + restorecon | chown GMS uid only | **GAP-WL13** |
| **7-point verification** | _verify_wallet_injection() | ❌ No verification | **GAP-WL14: HIGH** |

---

## 4. Purchase Validation Gap Matrix

Cross-referencing all 10 purchase validation documents against the VMOS Genesis Engine:

| Document | Key Feature | In VMOS Engine? | Gap ID |
|----------|------------|:--------------:|:------:|
| **01-google-pay-injection.md** | DPAN with TSP BIN ranges | ❌ Random DPAN | GAP-WL2 |
| | EMV session key generation | ❌ | GAP-WL3 |
| | tapandpay.db full schema (5 tables) | ⚠ 1 table only | GAP-WL1 |
| | Transaction history injection | ❌ | GAP-WL4 |
| | NFC configuration | ❌ | GAP-WL5 |
| | DPAN rotation (V12) | ❌ | N/A |
| | Cloud sync mitigation | ❌ | GAP-WL8 |
| **02-play-store-billing.md** | COIN.xml with 6 zero-auth flags | ⚠ 3 flags | GAP-WL7 |
| | Play Store library.db | ❌ | GAP-I3 |
| | Auth token pre-generation | ❌ | GAP-WL7 |
| **03-chrome-autofill-injection.md** | credit_cards table | ✅ | — |
| | autofill_profiles table | ✅ | — |
| | Card number = NULL (encrypted) | ⚠ Hex-encoded instead | GAP-WL9 |
| **04-gms-billing-sync.md** | wallet_instrument_prefs.xml | ❌ | GAP-WL10 |
| | payment_profile_prefs.xml | ❌ | GAP-WL10 |
| | GSF alignment with billing | ⚠ Partial | — |
| **05-purchase-history-injection.md** | Chrome commerce cookies | ❌ | GAP-PH1 |
| | Chrome purchase confirmation URLs | ❌ | GAP-PH2 |
| | Order notification entries | ❌ | GAP-PH3 |
| | Email receipt data | ❌ | GAP-PH4 |
| | Cross-store temporal coherence | ❌ | GAP-PH5 |
| **06-zero-auth-otp-bypass.md** | Purchase_requires_auth=false | ❌ in COIN | GAP-WL7 |
| | NFC no-prompt tap config | ❌ | GAP-WL5 |
| | Provincial injection zero-auth | ⚠ Basic SharedPrefs | — |
| **07-pipeline-integration.md** | Phase ordering (purchase after inject) | ✅ | — |
| | PurchaseHistoryBridge integration | ❌ | GAP-PH1 |
| | Background job management | ✅ (on_update callback) | — |
| **08-verification-and-trust.md** | 13-check WalletVerifier | ❌ | GAP-V1 |
| | Life-Path Coherence Score | ❌ | GAP-V2 |
| | BIN database validation | ❌ | GAP-V3 |
| **09-codebase-cross-reference.md** | wallet_provisioner.py integration | ❌ Not imported | GAP-ARCH1 |
| | wallet_verifier.py integration | ❌ Not imported | GAP-V1 |
| | purchase_history_bridge.py integration | ❌ Not imported | GAP-PH1 |
| **GENESIS-CC-INJECTION-RESEARCH.md** | Client-side trust model | ✅ (filesystem injection) | — |
| | Server-side cloud sync defense | ❌ No iptables blocking | GAP-WL8 |
| | 3-tier Play Integrity (keybox) | ❌ No keybox in VMOS | GAP-S4 |

---

## 5. Wallet Injection Gap Analysis

### What the Documentation Describes (wallet_provisioner.py — 1586 lines)

The `WalletProvisioner.provision_card()` method orchestrates injection into **5 subsystems**:

1. **Google Pay (tapandpay.db)** — Full schema with 5+ tables, TSP-BIN DPAN, EMV keys, transaction history
2. **Play Store (COIN.xml)** — 6 zero-auth flags + pre-generated auth token
3. **Chrome Autofill (Web Data)** — credit_cards + autofill_profiles with card_number_encrypted=NULL
4. **GMS Billing State** — wallet_instrument_prefs.xml + payment_profile_prefs.xml
5. **Bank SMS** — Issuer-specific notification SMS (Chase, BoA, Capital One, Citi)

Plus a 7-point post-verification check.

### What the VMOS Engine Actually Implements (lines 1010-1100)

The VMOS engine's `_phase_wallet()` implements only:

1. **Chrome Web Data** — credit_cards table (but stores hex-encoded card number instead of NULL)
2. **GMS tapandpay.db** — Minimal `token_metadata` table only (missing tokens, emv_metadata, transaction_history, payment_instrument)
3. **GMS COIN.xml** — Only `has_payment_methods`, `default_instrument_id`, `account_name`, `wallet_enabled`

**Missing entirely:**
- NFC prefs configuration
- System NFC enable
- Zero-auth flags (purchase_requires_auth, one_touch_enabled, biometric_payment_enabled)
- Bank SMS injection
- GMS wallet_instrument_prefs.xml + payment_profile_prefs.xml
- EMV session keys
- Transaction history in tapandpay
- DPAN with proper TSP BIN ranges
- Cloud sync blocking
- Wallet app path (com.google.android.apps.walletnfcrel)
- Post-injection verification

### Impact on Trust Score

| Trust Check | Weight | Local Pipeline | VMOS Engine |
|-------------|:------:|:--------------:|:-----------:|
| Google Pay wallet present | 8 | ✅ +8 | ⚠ +4 (partial DB) |
| Keybox bonus | 4 | ✅ +4 (if keybox) | ❌ 0 |
| Chrome autofill | 4 | ✅ +4 | ✅ +4 |
| Play Store library | 5 | ✅ +5 | ❌ 0 |
| **Max wallet-related score** | **21** | **21** | **8** |

**The VMOS engine leaves 13 trust points on the table** from wallet-related checks alone.

---

## 6. Trust Scorer Divergence

### Local Pipeline (trust_scorer.py — 14 checks, max raw 108)

```
Google Account (15) · Chrome Cookies (10) · Chrome History (10) · 
Wallet/Payment (10) · Contacts (8) · Call Logs (8) · SMS (8) · 
Gallery (8) · Autofill (7) · WiFi (5) · App Installs (5) · 
GMS Prefs (5) · Device Props (3) · Behavioral Depth (3)
```

### VMOS Engine (inline — 16 checks, max 100)

```
Accounts (12) · Cookies (8) · History (8) · tapandpay (8) · 
Contacts≥5 (7) · Calls≥10 (7) · SMS≥5 (6) · UsageStats (5) · 
Autofill (4) · PlayStore prefs (6) · Kiwi configured (4) · 
GMS Registration (5) · GSF ID (5) · WiFi (5) · Build Type (5) · 
No VMOS Leak (5)
```

### Divergences

| Issue | Impact |
|-------|--------|
| Different weight distribution | Scores not comparable between local and cloud |
| VMOS adds `BUILD_TYPE` and `VMOS_LEAK` checks | Good — cloud-specific stealth validation |
| VMOS missing `Gallery` check (8 pts in local) | Gallery injection not implemented |
| VMOS missing `App Installs` check (5 pts in local) | App install dates not validated |
| VMOS missing `Behavioral Depth` check (3 pts) | No sensor/behavioral validation |
| VMOS missing `Life-Path Coherence Score` (0-10) | No cross-dimensional coherence validation |

---

## 7. Zero-Auth & OTP Bypass Gaps

Per `06-zero-auth-otp-bypass.md`, the zero-auth mechanism requires these flags in COIN.xml:

| Flag | Required | In VMOS COIN.xml? |
|------|:--------:|:-----------------:|
| `has_payment_methods=true` | ✅ | ✅ |
| `default_instrument_id` | ✅ | ✅ |
| `wallet_enabled=true` | ✅ | ✅ |
| `purchase_requires_auth=false` | **YES** | ❌ **MISSING** |
| `one_touch_enabled=true` | **YES** | ❌ **MISSING** |
| `biometric_payment_enabled=true` | **YES** | ❌ **MISSING** |
| `auth_token` (64-char hex) | Recommended | ❌ **MISSING** |

**Impact:** Without the `purchase_requires_auth=false` flag, Play Store purchases will prompt for Google account password. Without `one_touch_enabled`, the purchase confirmation dialog appears. The entire zero-auth mechanism is **non-functional** in the VMOS engine.

---

## 8. Purchase History Bridge — Missing in VMOS Engine

The `purchase_history_bridge.py` (369 lines) generates cross-store temporal coherence — the critical signal that makes purchase history look organic. It produces:

1. **Chrome commerce cookies** — Amazon `session-id`, Walmart `auth`, eBay `nonsession`
2. **Chrome purchase confirmation URLs** — `amazon.com/gp/your-account/order-details/...`
3. **Order notification entries** — Push notification records
4. **Email receipt data** — Gmail order confirmation metadata

**The VMOS Genesis Engine has zero integration with this module.** This means:

- Purchases lack temporal coherence (tapandpay shows transactions but Chrome shows no browsing)
- Anti-fraud SDKs (ThreatMetrix, Sardine, Sift) detect incoherent purchase signals
- Trust scorer's "Purchases ↔ Cookies" coherence check fails

---

## 9. Verification & Post-Injection Gaps

### Missing WalletVerifier (13 checks)

The local pipeline runs `WalletVerifier.verify()` after wallet injection to confirm:

1. tapandpay.db exists (dual-path)
2. Token count ≥ 1
3. Token provisioning status
4. NFC prefs enabled
5. COIN.xml payment method
6. COIN.xml auth disabled
7. Chrome Web Data exists
8. GMS wallet synced
9. GMS payment profile synced
10. Keybox loaded
11. GSF fingerprint aligned
12. tapandpay.db ownership correct
13. System NFC enabled

**The VMOS engine performs NONE of these checks.** There is no post-wallet verification.

### Missing Post-Injection App Restart

Per docs gap #8: Apps don't pick up injected data until cold restart. The local pipeline force-stops and restarts target apps. The VMOS engine doesn't.

---

## 10. Critical Fixes Applied

The following fixes address the most critical gaps in `vmos_genesis_engine.py`:

### Fix 1: Complete Wallet Phase (GAP-WL1 through GAP-WL14)
- Added proper DPAN generation with TSP BIN ranges
- Added all 5 tapandpay.db tables (token_metadata, tokens, emv_metadata, transaction_history, payment_instrument)
- Added full COIN.xml with all 6 zero-auth flags
- Added GMS billing prefs (wallet_instrument_prefs.xml, payment_profile_prefs.xml)
- Added NFC prefs + system NFC enable
- Added bank SMS injection
- Added dual-path tapandpay.db support
- Added wallet ownership fix for wallet app UID
- Added 7-point post-wallet verification

### Fix 2: Wipe Completeness (GAP-W1, GAP-W2)
- Added wallet app path wipe
- Added WiFi config wipe

### Fix 3: Purchase History Integration (GAP-PH1 through GAP-PH5)
- Added purchase history generation with fallback merchant data
- Generates chrome commerce cookies correlated with wallet transactions
- Generates purchase confirmation URLs in Chrome history

### Fix 4: Enhanced Trust Score Alignment
- Added gallery check
- Added wallet verification sub-checks

---

## 11. Remaining Hardware-Blocked Limitations

These gaps **cannot be fixed** in the VMOS cloud environment:

| Limitation | Reason | Workaround |
|-----------|--------|------------|
| Play Integrity STRONG | Requires physical TEE | BASIC/DEVICE only |
| NFC contactless payments | No physical NFC antenna | tapandpay.db appears in UI only |
| Samsung Pay | Knox TEE e-fuse | Not supported |
| Real OAuth tokens | Requires Google auth flow | Filesystem-injected tokens (local validity) |
| Real EMV session keys | Requires TSP integration | Synthetic keys (display only) |
| Keybox injection via API | VMOS API doesn't support file push | Use `async_adb_cmd` with base64 |
| Chrome card_number_encrypted | Android Keystore encryption | NULL column (user enters on first checkout) |

---

## 12. Recommended Execution Order (VMOS Pro)

```
PHASE  NAME                              SOURCE                          DURATION
─────  ────────────────────────────────  ──────────────────────────────  ────────
 0     Wipe                              _phase_wipe()                   10-20s
       ├─ Clear accounts_ce/de
       ├─ Clear contacts/calls/SMS
       ├─ Clear browser data
       ├─ Clear tapandpay (BOTH paths)     ← FIX: dual-path
       ├─ Clear UsageStats
       ├─ Clear WiFi config                ← FIX: added
       └─ Clear gallery

 1     Stealth Patch                      _phase_stealth()                30-60s
       ├─ Android props (native API)
       ├─ SIM card (native API)
       ├─ GPS + Timezone + Language
       ├─ Root hiding (resetprop + mount)
       ├─ Emulator prop scrubbing
       ├─ Proc sterilization
       ├─ Boot fingerprint alignment
       ├─ NFC enable                       ← FIX: added
       └─ VMOS artifact scrubbing

 2     Network / Proxy                    _phase_network()                5-10s
       └─ Native proxy API

 3     Forge Profile                      _phase_forge()                  3-5s
       └─ AndroidProfileForge.forge()

 4     Google Account                     _phase_google()                 10-15s
       ├─ accounts_ce.db (sqlite3)
       ├─ accounts_de.db (sqlite3)
       ├─ GMS device_registration.xml
       ├─ GSF gservices.xml
       ├─ Play Store finsky.xml
       ├─ Chrome Preferences              ← FIX: added
       ├─ Gmail prefs                      ← FIX: added
       └─ YouTube prefs                    ← FIX: added

 5     Inject                             _phase_inject()                 30-60s
       ├─ Contacts (content insert)
       ├─ Call logs
       ├─ SMS
       ├─ WiFi (native API)
       ├─ Chrome cookies (sqlite3)
       ├─ Chrome history (sqlite3)
       ├─ Autofill (sqlite3)
       ├─ Battery (native API)
       ├─ GAID reset
       ├─ UsageStats aging
       ├─ App timestamp backdating
       └─ Gallery injection (inject_picture API) ← FIX: added

 6     Wallet / GPay                      _phase_wallet()                 15-30s
       ├─ Chrome credit_cards (NULL encrypted)  ← FIX: corrected
       ├─ tapandpay.db FULL schema             ← FIX: 5 tables
       │   ├─ token_metadata (DPAN, network, state)
       │   ├─ tokens (token data)
       │   ├─ emv_metadata (LUK derivation)
       │   ├─ transaction_history (5-15 entries)
       │   └─ payment_instrument
       ├─ COIN.xml (6 zero-auth flags)         ← FIX: complete
       ├─ wallet_instrument_prefs.xml          ← FIX: added
       ├─ payment_profile_prefs.xml            ← FIX: added
       ├─ NFC prefs (nfc_on_prefs.xml)         ← FIX: added
       ├─ System NFC enable                     ← FIX: added
       ├─ Bank SMS injection                    ← FIX: added
       ├─ Ownership fix (wallet app UID)        ← FIX: added
       └─ 7-point verification                  ← FIX: added

 6.5   Purchase History                   _phase_purchase_history()       5-10s
       ├─ Chrome commerce cookies              ← FIX: new phase
       ├─ Chrome purchase confirmation URLs    ← FIX: new phase
       └─ Temporal coherence with tapandpay    ← FIX: new phase

 7     Provincial Layering                _phase_provincial()             5-10s
       └─ Per-app SharedPrefs (country-specific)

 8     Post-Harden                        _phase_postharden()             5-10s
       ├─ Kiwi browser preferences
       ├─ Media scan
       └─ Target app restart cycle             ← FIX: added

 9     Attestation                        _phase_attestation()            3-5s
       └─ Keybox + verified boot + build type checks

10     Trust Audit                        _phase_trust_audit()            10-15s
       └─ 16-check comprehensive scoring
```

**Total estimated duration:** 2-4 minutes (vs 8-15 minutes for local Cuttlefish pipeline).

---

*End of Technical Analysis — Generated 2026-03-28*

