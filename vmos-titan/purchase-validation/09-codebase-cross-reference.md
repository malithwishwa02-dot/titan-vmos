# 09 — Codebase Cross-Reference

Complete file, function, class, and API endpoint map for all payment, wallet, and purchase-related code in the Titan V11.3 codebase.

---

## Table of Contents

1. [Core Modules](#1-core-modules)
2. [Server Routers (API)](#2-server-routers-api)
3. [Standalone Scripts](#3-standalone-scripts)
4. [Wallet Module](#4-wallet-module)
5. [Documentation](#5-documentation)
6. [Tests](#6-tests)
7. [Infrastructure](#7-infrastructure)
8. [Data Flow Diagram](#8-data-flow-diagram)
9. [Function Call Graph](#9-function-call-graph)
10. [API Endpoint Summary](#10-api-endpoint-summary)

---

## 1. Core Modules

### core/wallet_provisioner.py

The central wallet injection engine. ~1600 lines.

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 67–85 | `CARD_NETWORKS` | Card network prefix mapping |
| 85–100 | `ISSUER_MAP` | BIN → issuer mapping (60+ entries) |
| 103–185 | `__init__()` | WalletProvisioner initialization |
| 187–226 | `generate_dpan()` | DPAN (Device PAN) generation with Luhn |
| 228–234 | `_luhn_checksum()` | Luhn check digit calculator |
| 236–307 | `generate_emv_session()` | EMV session key (LUK + ARQC) generation |
| 309–353 | `_derive_luk()`, `_generate_arqc()` | EMV cryptogram helpers |
| 355–575 | `provision_card()` | **Main entry point** — orchestrates all 4 targets |
| 578–856 | `_provision_google_pay()` | Target 1: tapandpay.db injection |
| 859–957 | `_provision_play_store()` | Target 2: COIN.xml injection (zero-auth) |
| 959–1151 | `_provision_chrome_autofill()` | Target 3: Chrome Web Data injection |
| 1153–1205 | `_provision_gms_billing()` | Target 4: GMS billing prefs injection |
| 1207–1283 | `_verify_wallet_injection()` | 7-point quick post-check |
| 1285–1399 | `_inject_card_sms()` | Bank notification SMS injection |
| 1401–1408 | `_build_shared_prefs_xml()` | SharedPrefs XML builder |
| 1410–1433 | `_build_coin_xml()` | COIN.xml XML builder |
| 1435–1446 | `_push_shared_prefs_xml()` | ADB push + ownership fix for SharedPrefs |
| 1448–1460 | `_fix_ownership()` | chown + chmod + restorecon |
| 1461–1508 | `rotate_dpan()` | V12: DPAN rotation |
| 1510–1584 | `correlate_transactions_with_profile()` | V12: Transaction-profile correlation |

### core/wallet_verifier.py

13-check deep wallet verification. ~340 lines.

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 10–22 | `WalletCheck` dataclass | Per-check result structure |
| 24–40 | `WalletVerificationReport` dataclass | Full report structure |
| 42–86 | `__init__()` | WalletVerifier initialization |
| 88–142 | `verify()` | **Main entry** — runs all 13 checks |
| 144–160 | `_check_tapandpay_exists()` | Check #1: tapandpay.db exists (dual path) |
| 162–175 | `_check_tapandpay_tokens()` | Check #2: Token count ≥ 1 |
| 177–190 | `_check_token_status()` | Check #3: Provisioning status |
| 192–210 | `_check_nfc_prefs()` | Check #4: NFC prefs enabled |
| 213–227 | `_check_coin_xml()` | Check #5: COIN.xml payment method |
| 229–239 | `_check_coin_auth()` | Check #6: Auth disabled (zero-auth) |
| 241–251 | `_check_chrome_webdata()` | Check #7: Chrome Web Data exists |
| 253–265 | `_check_gms_wallet_prefs()` | Check #8: GMS wallet synced |
| 267–275 | `_check_gms_payment_profile()` | Check #9: GMS payment profile |
| 277–305 | `_check_keybox()` | Check #10: Keybox loaded |
| 307–318 | `_check_gsf_alignment()` | Check #11: GSF fingerprint aligned |
| 320–330 | `_check_tapandpay_ownership()` | Check #12: File ownership correct |
| 332–340 | `_check_system_nfc()` | Check #13: System NFC enabled |

### core/purchase_history_bridge.py

Commerce purchase history generator. ~369 lines.

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 15–60 | `PurchaseHistoryBridge` class | Main bridge class |
| 62–109 | `_FALLBACK_MERCHANTS` | Built-in merchant database |
| 111–115 | Constants | Cookie format, timestamp helpers |
| 116–184 | `_generate_purchases()` | Raw purchase record generation |
| 186–209 | `_to_chrome_history()` | Convert purchases to Chrome history entries |
| 211–234 | `_to_chrome_cookies()` | Convert to Chrome commerce cookies |
| 236–253 | `_to_notifications()` | Convert to order notification entries |
| 255–274 | `_to_email_receipts()` | Convert to email receipt entries |
| 276–296 | `generate_android_purchase_history()` | **Main entry** — generates all artifacts |
| 298–340 | `_select_merchants()` | Category-to-merchant mapping |
| 342–361 | `_generate_order_id()` | Merchant-specific order ID format |
| 363–369 | `_to_purchase_summary()` | Stats for trust scoring |

### core/bin_database.py

BIN (Bank Identification Number) lookup. ~315 lines.

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 10–52 | `BINDatabase` class init | Initialization + external data loading |
| 55–122 | `STATIC_BIN_DATA` | 60+ static BIN records (US/UK/EU) |
| 124–133 | `NETWORK_PREFIXES` | Card network detection prefixes |
| 135–160 | `lookup()` | BIN record lookup |
| 162–190 | `full_lookup()` | Complete card info (BIN + validation) |
| 192–220 | `_detect_network()` | Card network from prefix |
| 222–240 | `is_prepaid()` | Prepaid card detection |
| 242–258 | `is_commercial()` | Commercial/corporate card detection |
| 260–275 | `get_issuer_bank()` | Issuer bank name |
| 277–290 | `get_country()` | Issuing country code |
| 292–315 | `is_valid_luhn()` | Luhn algorithm validation |

### core/trust_scorer.py

Trust score computation. ~436 lines.

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 15–33 | `_resolve_browser_data_path()` | Chrome vs Kiwi browser detection |
| 35–36 | Constants | Weight definitions |
| 37–210 | `compute_trust_score()` | **14-check trust scorer** |
| 125–145 | Check #6 | Google Pay wallet + keybox |
| 197–203 | Check #13 | Chrome autofill data |
| 220–240 | `compute_lifepath_score()` | **Life-Path Coherence Score** |
| 242–270 | Coherence #1 | Email ↔ History |
| 272–295 | Coherence #2 | Maps ↔ WiFi |
| 297–320 | Coherence #3 | Contacts ↔ Calls |
| 322–334 | Coherence #4 | **Purchases ↔ Cookies** |
| 336–370 | Coherence #5 | Temporal consistency |
| 372–436 | Helper functions | Domain extraction, timestamp analysis |

### core/profile_injector.py

Profile injection orchestrator. Wallet-related sections:

| Line Range | Function/Method | Description |
|:----------:|----------------|-------------|
| 87–122 | `InjectionResult` dataclass | Includes `wallet_ok`, `play_purchases_ok` |
| 142–231 | `inject_full_profile()` | Main injection method (calls wallet) |
| 182–184 | Phase 3 call | `self._inject_wallet(profile, card_data)` |
| 189–191 | Phase 5 call | `self._inject_play_purchases(profile)` |
| 192–193 | Phase 5.5 call | `self._inject_purchase_history(profile)` |
| 195–197 | Phase 5.5.1 call | `self._inject_payment_history(profile, card_data)` |
| 304–331 | `_inject_wallet()` | Calls WalletProvisioner.provision_card() |
| 375–440 | `_inject_play_purchases()` | Play Store purchases + usage stats |
| 442–493 | `_inject_purchase_history()` | PurchaseHistoryBridge integration |
| 494–540 | `_inject_payment_history()` | Wallet transaction history |

---

## 2. Server Routers (API)

### server/routers/provision.py

Pipeline and injection endpoints. Wallet-related sections:

| Line Range | Function/Endpoint | Description |
|:----------:|------------------|-------------|
| 39–85 | `FullProvisionBody` | Request model with CC fields |
| 300–350 | `POST /full-provision/{id}` | Full pipeline endpoint |
| 530–650 | `phases` array | Pipeline phase definitions |
| 710–759 | Phase 6 | Wallet/GPay provisioning |
| 760–790 | Phase 7 | Provincial layering |
| 870–935 | Phase 10 | Trust audit + wallet verify |
| 936–964 | `POST /provincial-inject/{id}` | Provincial zero-auth injection |
| 965–1000 | `GET /wallet-status/{id}` | Quick wallet status |

### server/routers/genesis.py

Genesis-specific endpoints:

| Line Range | Function/Endpoint | Description |
|:----------:|------------------|-------------|
| 100–155 | `POST /inject/{id}` | Profile inject (includes wallet) |
| 200–250 | `GET /trust-score/{id}` | Trust score computation |
| 253–290 | `POST /request-otp` | OTP auto-detection from SMS |
| 402–470 | `GET /wallet-transactions/{id}` | Read back wallet transactions |

### server/routers/stealth.py

Stealth and verification endpoints:

| Line Range | Function/Endpoint | Description |
|:----------:|------------------|-------------|
| varies | `GET /wallet-verify/{id}` | 13-check wallet deep verification |

### server/routers/cerberus.py

Card validation endpoints:

| Line Range | Function/Endpoint | Description |
|:----------:|------------------|-------------|
| varies | `POST /validate` | Single card validation + BIN |
| varies | `POST /batch` | Multi-card batch validation |
| varies | `POST /bin` | BIN lookup only |

### server/routers/intel.py

Intelligence endpoints:

| Line Range | Function/Endpoint | Description |
|:----------:|------------------|-------------|
| varies | `POST /3ds-strategy` | Card-specific 3DS bypass strategy |
| varies | `POST /copilot` | AI intelligence query |

---

## 3. Standalone Scripts

### provincial_injection_protocol.py

Root-level standalone script for regional zero-auth injection.

| Line Range | Function | Description |
|:----------:|---------|-------------|
| 18–82 | `REGIONAL_CONFIGS` | US and GB region configs (apps, cards, locale) |
| 84–190 | `forge_regional_profile()` | 5-step provincial injection orchestrator |
| 124–137 | Step 3 | `WalletProvisioner.provision_card(zero_auth=True)` |
| 192–237 | `if __name__` | CLI entry point |

---

## 4. Wallet Module

### wallet/wallet_core.py

Convenience wrapper for wallet operations.

| Line Range | Function | Description |
|:----------:|---------|-------------|
| 1–18 | Imports | WalletProvisioner, WalletVerifier |
| 20–43 | `provision_card()` | Wrapper with `zero_auth` parameter passthrough |
| 45–55 | `verify_wallet()` | Wrapper for WalletVerifier.verify() |

### wallet/__init__.py

Module exports.

---

## 5. Documentation

| File | Payment-Related Content |
|------|------------------------|
| `docs/05-wallet-injection.md` | Primary wallet injection documentation (632 lines) |
| `docs/08-intelligence-tools.md` | Cerberus validator, BIN database, 3DS strategy (560 lines) |
| `docs/11-real-world-success-rates.md` | Wallet, NFC, Play Store success rates (529 lines) |
| `docs/04-profile-injector.md` | Profile injection including wallet phases |
| `docs/03-genesis-pipeline.md` | Pipeline phases including wallet |
| `docs/00-overview.md` | Architecture overview |
| `docs/provincial-injection-protocol.md` | Provincial injection protocol |

---

## 6. Tests

| File | Description |
|------|-------------|
| `tests/e2e/README.md` | E2E test workflow (includes wallet verification) |
| `tests/e2e/genesis_studio_test_suite_jovany_owens.md` | Full genesis test with wallet |
| `test_jovany.py` | Jovany Owens profile test (includes CC data) |

---

## 7. Infrastructure

| File | Purpose |
|------|---------|
| `cuttlefish/init.d/99-titan-patch.sh` | Boot persistence script (wallet sync blocking) |
| `cuttlefish/launch_config_template.json` | VM launch config (includes NFC) |

---

## 8. Data Flow Diagram

```
                    ┌─────────────────────────┐
                    │   API Request (CC data)  │
                    │   POST /full-provision   │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │  provision.py Pipeline   │
                    │  _run_pipeline_job()     │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
    │ Phase 5:      │  │ Phase 6:    │  │ Phase 7:    │
    │ ProfileInject │  │ Wallet/GPay │  │ Provincial  │
    │ (includes     │  │ (pipeline)  │  │ Layering    │
    │  wallet)      │  │             │  │             │
    └───────┬───────┘  └──────┬──────┘  └──────┬──────┘
            │                 │                 │
    ┌───────▼───────┐  ┌─────▼───────┐  ┌──────▼──────┐
    │ wallet_       │  │ wallet_     │  │ app_data_   │
    │ provisioner   │  │ provisioner │  │ forger      │
    │ .py           │  │ .py         │  │ .py         │
    └───────┬───────┘  └─────┬───────┘  └─────────────┘
            │                │
    ┌───────┴────────────────┘
    │
    ├──► tapandpay.db (Google Pay)
    ├──► COIN.xml (Play Store billing)
    ├──► Web Data (Chrome autofill)
    ├──► wallet_instrument_prefs.xml (GMS)
    ├──► payment_profile_prefs.xml (GMS)
    ├──► nfc_on_prefs.xml (NFC)
    └──► default_settings.xml (NFC)

    ┌───────────────────────────┐
    │ purchase_history_bridge   │
    │ .py                       │
    └───────┬───────────────────┘
            │
    ├──► Chrome History (commerce URLs)
    ├──► Chrome Cookies (commerce sessions)
    ├──► Notifications (order confirmations)
    └──► Email receipts

    ┌───────────────────────────┐
    │ Phase 10: Trust Audit     │
    └───────┬───────────────────┘
            │
    ├──► trust_scorer.py (14 checks, wallet = #6 + #13)
    ├──► wallet_verifier.py (13 checks)
    └──► lifepath_score (purchases ↔ cookies coherence)
```

---

## 9. Function Call Graph

### provision_card() Call Chain

```
WalletProvisioner.provision_card()
  ├── generate_dpan()
  │     └── _luhn_checksum()
  ├── generate_emv_session()
  │     ├── _derive_luk()
  │     └── _generate_arqc()
  ├── _provision_google_pay()
  │     ├── sqlite3 CREATE TABLE tokens, token_metadata, session_keys, ...
  │     ├── INSERT token record
  │     ├── INSERT token_metadata
  │     ├── INSERT session_keys
  │     ├── INSERT transaction_history
  │     ├── adb push tapandpay.db
  │     ├── _fix_ownership()
  │     └── _push_shared_prefs_xml() × 2 (nfc_on_prefs, default_settings)
  ├── _provision_play_store()
  │     ├── _build_coin_xml()
  │     ├── _push_shared_prefs_xml()
  │     └── iptables DROP (if zero_auth)
  ├── _provision_chrome_autofill()
  │     ├── sqlite3 CREATE TABLE credit_cards, autofill_profiles, ...
  │     ├── INSERT credit_cards
  │     ├── INSERT autofill_profiles
  │     ├── adb push Web Data
  │     └── _fix_ownership()
  ├── _provision_gms_billing()
  │     ├── _push_shared_prefs_xml() (wallet_instrument_prefs)
  │     └── _push_shared_prefs_xml() (payment_profile_prefs)
  ├── _verify_wallet_injection()
  │     └── 7 quick checks
  └── _inject_card_sms()
        └── content insert (SMS inbox) × N
```

### verify() Call Chain

```
WalletVerifier.verify()
  ├── _check_tapandpay_exists()      → _sh("ls ...")
  ├── _check_tapandpay_tokens()      → _query_db("SELECT COUNT(*)")
  ├── _check_token_status()          → _query_db("SELECT provisioning_status")
  ├── _check_nfc_prefs()             → _read_shared_prefs()
  ├── _check_coin_xml()              → _read_shared_prefs()
  ├── _check_coin_auth()             → _read_shared_prefs()
  ├── _check_chrome_webdata()        → _sh("ls ...")
  ├── _check_gms_wallet_prefs()      → _read_shared_prefs()
  ├── _check_gms_payment_profile()   → _read_shared_prefs()
  ├── _check_keybox()                → _sh("getprop persist.titan.keybox.loaded")
  ├── _check_gsf_alignment()         → _sh("ls CheckinService.xml")
  ├── _check_tapandpay_ownership()   → _sh("stat -c %U")
  └── _check_system_nfc()            → _sh("settings get secure nfc_on")
```

---

## 10. API Endpoint Summary

### Wallet Injection & Management

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/api/genesis/inject/{device_id}` | `genesis.inject()` | Full profile inject including wallet |
| `POST` | `/api/genesis/full-provision/{device_id}` | `provision.full_provision()` | Complete pipeline (all phases) |
| `POST` | `/api/genesis/provincial-inject/{device_id}` | `provision.provincial_inject()` | Regional zero-auth injection |
| `GET` | `/api/genesis/wallet-status/{device_id}` | `provision.wallet_status()` | Quick wallet status |

### Verification & Trust

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `GET` | `/api/stealth/{device_id}/wallet-verify` | `stealth.wallet_verify()` | 13-check deep verification |
| `GET` | `/api/genesis/trust-score/{device_id}` | `genesis.trust_score()` | Trust score (includes wallet) |
| `GET` | `/api/genesis/wallet-transactions/{device_id}` | `genesis.wallet_transactions()` | Read back transactions |

### Card Validation & Intelligence

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/api/cerberus/validate` | `cerberus.validate()` | Single card validation + BIN |
| `POST` | `/api/cerberus/batch` | `cerberus.batch()` | Multi-card batch validation |
| `POST` | `/api/cerberus/bin` | `cerberus.bin_lookup()` | BIN lookup only |
| `POST` | `/api/intel/3ds-strategy` | `intel.threed_strategy()` | 3DS bypass strategy |

### OTP & Authentication

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/api/genesis/request-otp` | `genesis.request_otp()` | OTP auto-detection from device SMS |

### Pipeline Job Management

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `GET` | `/api/genesis/provision-status/{job_id}` | `provision.provision_status()` | Poll pipeline job status |

---

*This cross-reference covers all wallet, payment, purchase, and card validation code in the Titan V11.3 codebase as of the current version.*
