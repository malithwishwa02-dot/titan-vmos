# 04 — GMS Billing State Synchronization

How Genesis syncs payment profile state into Google Mobile Services (GMS) SharedPreferences to establish ecosystem coherence and reduce cloud reconciliation risk.

---

## Table of Contents

1. [Overview](#1-overview)
2. [wallet_instrument_prefs.xml](#2-wallet_instrument_prefsxml)
3. [payment_profile_prefs.xml](#3-payment_profile_prefsxml)
4. [Why GMS Sync Matters](#4-why-gms-sync-matters)
5. [Injection Process](#5-injection-process)
6. [Success Rates](#6-success-rates)
7. [Codebase Cross-References](#7-codebase-cross-references)

---

## 1. Overview

Google Mobile Services (GMS) maintains its own internal record of the device's payment state through SharedPreferences files. If these files are absent or inconsistent with the wallet data in `tapandpay.db` and `COIN.xml`, Google Play Services may:

- Flag the wallet as "not set up" despite files existing
- Trigger a cloud reconciliation that wipes injected wallet data
- Show "Payment method unavailable" in apps that query GMS billing

Genesis writes two GMS SharedPreferences files to establish coherence:

1. **`wallet_instrument_prefs.xml`** — wallet setup and default instrument
2. **`payment_profile_prefs.xml`** — payment profile sync state

**GMS data directory:** `/data/data/com.google.android.gms/shared_prefs/`

**Source file:** `core/wallet_provisioner.py` — method `_provision_gms_billing()` (lines 1153–1205)

---

## 2. wallet_instrument_prefs.xml

**Path:** `/data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml`

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="wallet_setup_complete" value="true" />
    <string name="wallet_account">{persona_email}</string>
    <string name="default_instrument_id">{funding_source_id}</string>
    <long name="last_sync_timestamp" value="{now_ms}" />
    <boolean name="nfc_payment_enabled" value="true" />
    <string name="wallet_environment">PRODUCTION</string>
</map>
```

### Field Details

| Field | Purpose |
|-------|---------|
| `wallet_setup_complete` | Tells GMS the wallet is fully initialized |
| `wallet_account` | Must match the persona email / Google account on device |
| `default_instrument_id` | UUID4 matching `funding_source_id` in tapandpay.db and COIN.xml |
| `last_sync_timestamp` | Set to current time — prevents "stale" detection |
| `nfc_payment_enabled` | Confirms NFC payment is active |
| `wallet_environment` | Must be `PRODUCTION` (not `SANDBOX`) |

---

## 3. payment_profile_prefs.xml

**Path:** `/data/data/com.google.android.gms/shared_prefs/payment_profile_prefs.xml`

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="payment_methods_synced" value="true" />
    <string name="profile_email">{persona_email}</string>
    <long name="last_sync_time" value="{now_ms}" />
    <boolean name="has_billing_address" value="true" />
    <string name="payment_profile_id">{uuid4}</string>
</map>
```

### Field Details

| Field | Purpose |
|-------|---------|
| `payment_methods_synced` | Tells GMS payment methods are synchronized |
| `profile_email` | Must match persona email |
| `last_sync_time` | Prevents "needs sync" state |
| `has_billing_address` | Indicates billing address is on file |
| `payment_profile_id` | Unique profile identifier |

---

## 4. Why GMS Sync Matters

### The Coherence Chain

For a wallet injection to be fully functional, four components must agree:

```
tapandpay.db (tokens.funding_source_id)
    ↕ must match
COIN.xml (default_instrument_id)
    ↕ must match
wallet_instrument_prefs.xml (default_instrument_id)
    ↕ must match
payment_profile_prefs.xml (profile_email ↔ wallet_account)
```

If any link in this chain is broken, Google Play Services detects an inconsistency and may:

1. **Soft failure:** Show "Verify your payment method" prompt
2. **Hard failure:** Remove the payment method entirely during background sync
3. **Trust degradation:** Lower internal GMS trust score for the device

### UUID Consistency

Genesis generates a single `funding_source_id` (UUID4) during `provision_card()` and reuses it across all four injection targets. This ensures the instrument ID chain is consistent.

**Source:** `core/wallet_provisioner.py` lines 480–500

---

## 5. Injection Process

```
1. Build wallet_instrument_prefs.xml content
2. Build payment_profile_prefs.xml content
3. Write both to temp files on host
4. adb push to /data/data/com.google.android.gms/shared_prefs/
5. Query GMS UID: stat -c %U /data/data/com.google.android.gms
6. chown {gms_uid}:{gms_uid} both files
7. chmod 660 both files
8. restorecon -R /data/data/com.google.android.gms/shared_prefs/
```

**Source:** `core/wallet_provisioner.py` lines 1153–1205, helper `_push_shared_prefs_xml()` lines 1435–1446

---

## 6. Success Rates

| Metric | Rate |
|--------|:----:|
| wallet_instrument_prefs.xml injection | **~95%** |
| payment_profile_prefs.xml injection | **~95%** |
| GMS recognizes wallet as "set up" | **~93%** |
| Coherence chain fully intact (all 4 targets) | **~90%** |

### Primary Failure Mode

The ~5% failure rate is caused by **GMS UID resolution failure**. If Google Mobile Services has not been fully initialized on the device (e.g., first boot, GMS not installed), the UID query returns empty and the file ownership is set incorrectly, causing GMS to be unable to read the preferences.

**Fix:** Ensure GMS is installed and has run at least once before wallet injection. The pipeline handles this by running GApps bootstrap and Google account injection before wallet provisioning.

**Source:** `docs/11-real-world-success-rates.md` §3

---

## 7. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/wallet_provisioner.py` lines 1153–1205 | `_provision_gms_billing()` | Main GMS billing sync injection |
| `core/wallet_provisioner.py` lines 1435–1446 | `_push_shared_prefs_xml()` | SharedPrefs XML write helper |
| `core/wallet_provisioner.py` lines 1448–1460 | `_fix_ownership()` | UID + SELinux ownership fix |
| `core/wallet_verifier.py` lines 253–275 | `_check_gms_wallet_prefs()`, `_check_gms_payment_profile()` | Verification checks |
| `core/trust_scorer.py` lines 133–135 | Check #6c | Trust score GMS billing check |
| `docs/05-wallet-injection.md` §6 | GMS Billing Sync | Existing documentation |

---

*See [05-purchase-history-injection.md](05-purchase-history-injection.md) for commerce purchase history injection.*
