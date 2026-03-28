# 06 — Zero-Auth & OTP Bypass Architecture

How Genesis enables purchases without OTP, first-time authentication, 3D Secure challenges, or biometric prompts across all payment targets.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What Is Zero-Auth](#2-what-is-zero-auth)
3. [Play Store Zero-Auth (COIN.xml)](#3-play-store-zero-auth-coinxml)
4. [Google Pay NFC (No-Prompt Tap)](#4-google-pay-nfc-no-prompt-tap)
5. [3D Secure / OTP at Merchant Level](#5-3d-secure--otp-at-merchant-level)
6. [OTP Auto-Detection (Device SMS)](#6-otp-auto-detection-device-sms)
7. [Provincial Injection Protocol](#7-provincial-injection-protocol)
8. [Play Integrity & Attestation](#8-play-integrity--attestation)
9. [Keybox Role in Payment Authentication](#9-keybox-role-in-payment-authentication)
10. [End-to-End Zero-Auth Flow](#10-end-to-end-zero-auth-flow)
11. [Success Rates by Scenario](#11-success-rates-by-scenario)
12. [Codebase Cross-References](#12-codebase-cross-references)

---

## 1. Overview

"Zero-auth" in Genesis means configuring the device so that payment transactions proceed without requiring any interactive authentication step from the user. This involves multiple layers:

| Layer | What It Bypasses | Method |
|-------|-----------------|--------|
| **Play Store billing** | Google account password prompt | `purchase_requires_auth=false` in COIN.xml |
| **Play Store biometric** | Fingerprint/face prompt | `biometric_payment_enabled=true` in COIN.xml |
| **Play Store one-touch** | Confirmation dialog | `one_touch_enabled=true` in COIN.xml |
| **Google Pay NFC** | Screen lock / tap prompt | NFC prefs + Play Integrity attestation |
| **3D Secure (issuer)** | OTP / challenge from card issuer | Cannot bypass — issuer-controlled |
| **Merchant fraud check** | Risk-based authentication | Trust score + behavioral profile |

**Key distinction:** Genesis can bypass **device-side** authentication (Play Store, Google Pay app settings) but **cannot bypass issuer-side** authentication (3D Secure OTP from the bank). The 3DS challenge rate depends on the card's BIN, the merchant's risk threshold, and the device's behavioral profile.

### The Fundamental Mechanism: Filesystem Injection Bypasses the Entire Tokenization Chain

When a real user adds a card to Google Pay via the app UI, the flow is:

```
User → Google Pay UI → Google servers → TSP (Visa VTS / MC MDES) → Issuing Bank → OTP sent
   → User enters OTP → Bank approves → TSP generates DPAN → Token stored in tapandpay.db
```

**Every step in this chain involves server-side authentication.** The OTP is the issuing bank confirming the real cardholder authorized tokenization.

Genesis **does not interact with Google servers, the TSP, or the issuing bank at any point.** Instead, it writes directly to the Android filesystem with ADB root access:

```
Genesis (ADB root) → Creates tapandpay.db with pre-built token records (DPAN, metadata, EMV keys)
                   → Pushes DB to /data/data/com.google.android.apps.walletnfcrel/databases/
                   → Sets correct UID ownership (chown) + SELinux context (restorecon)
                   → Google Pay reads DB on next launch → sees valid token → displays card
```

**There is no OTP because there is no server-side tokenization request.** Genesis fabricates the end result (the tokenized card record in the local database) without going through the process that would trigger OTP verification.

### Why Google Pay Trusts the Injected Data

Android's security model gives each app exclusive access to its private data directory (`/data/data/<package>/`). Google Pay assumes that any data in its own private SQLite database was written by its own code through the legitimate provisioning flow. **There is no cryptographic signature or integrity check on individual database rows.** The trust boundary is Linux filesystem permissions — not cryptographic verification. With root access, this boundary is completely bypassed.

For the full technical explanation of client-side and server-side trust, see [GENESIS-CC-INJECTION-RESEARCH.md](GENESIS-CC-INJECTION-RESEARCH.md) Sections 3 and 4.

---

## 2. What Is Zero-Auth

### Device-Side Authentication (Bypassable)

These are authentication checks enforced by the Android device or Google Play Services:

1. **Play Store purchase password** — Google account password before in-app purchase
2. **Play Store biometric** — Fingerprint/face before purchase
3. **NFC payment confirmation** — Screen lock / tap confirmation before NFC pay
4. **Google account re-verification** — "Verify it's you" prompt

Genesis bypasses all of these by writing the correct SharedPreferences flags and auth tokens.

### Issuer-Side Authentication (Not Bypassable by Device)

These are authentication checks enforced by the card-issuing bank:

1. **3D Secure 2.0 challenge** — OTP sent to cardholder's phone
2. **3D Secure 2.0 frictionless** — Risk-based, no challenge (if device looks trusted)
3. **First-time card verification** — Initial card use requires CVV or OTP
4. **Velocity-based challenges** — Too many transactions trigger re-auth

Genesis cannot bypass these directly, but it **reduces the probability of being challenged** by:
- Maintaining a high trust score (device looks legitimate)
- Injecting purchase history (device has prior transaction evidence)
- Using behavioral warm-up sessions (agent browses before purchase)

---

## 3. Play Store Zero-Auth (COIN.xml)

### Flags Injected

When `zero_auth=True` is passed to `WalletProvisioner.provision_card()`:

```python
prefs["purchase_requires_auth"] = "false"      # No password prompt
prefs["require_purchase_auth"] = "false"        # Redundant safety flag
prefs["auth_token"] = secrets.token_hex(32)     # Pre-generated 64-char auth token
prefs["one_touch_enabled"] = "true"             # One-tap purchasing
prefs["biometric_payment_enabled"] = "true"     # Marks biometric as configured
```

### Effect on Purchase Flow

**Without zero-auth (normal Android):**
```
User taps "Buy" → Play Store shows "Verify with Google password" → User enters password → Purchase proceeds
```

**With zero-auth (Genesis):**
```
User taps "Buy" → Purchase proceeds immediately
```

### Where Zero-Auth Is Enabled by Default

| Entry Point | Zero-Auth Default |
|------------|:-----------------:|
| `WalletProvisioner.provision_card(zero_auth=True)` | Explicit |
| Pipeline Phase 6 (`provision.py`) | **Always True** |
| Provincial Injection Protocol | **Always True** |
| `ProfileInjector._inject_wallet()` | Uses caller's setting |
| `wallet_core.provision_card()` | Parameter passthrough |

**Source:** `core/wallet_provisioner.py` lines 900–940, `server/routers/provision.py` line 727

---

## 4. Google Pay NFC (No-Prompt Tap)

For NFC contactless payments, Google Pay requires:

1. **Screen must be on** (but not necessarily unlocked, depending on settings)
2. **NFC must be enabled** at system level
3. **Google Wallet must be set as default NFC payment app**
4. **Play Integrity must pass** at Device level or higher

Genesis configures all of these:

```bash
# System NFC
settings put secure nfc_on 1
settings put secure nfc_payment_foreground 1

# NFC prefs (SharedPreferences)
nfc_on_prefs.xml: nfc_enabled=true, tap_and_pay_enabled=true
default_settings.xml: nfc_payment_default_set=true

# Play Integrity
Anomaly patcher Phase 11b: Keybox injection
Anomaly patcher Phase 11c: GSF alignment
```

### NFC Payment Flow After Genesis

```
Device near terminal → NFC detects → Google Wallet activated →
DPAN transmitted → TSP maps DPAN to FPAN → Issuer authorizes →
(If 3DS required: challenge sent to phone) → Payment complete
```

**Source:** `core/wallet_provisioner.py` lines 780–856

---

## 5. 3D Secure / OTP at Merchant Level

### How 3DS Works

When a card is used for an online purchase, the merchant's payment processor may invoke 3D Secure:

```
Checkout → Payment processor → 3DS server → Issuer decides:
  ├── Frictionless (no challenge): Device looks trusted → Approve
  └── Challenge: Send OTP to cardholder phone → Wait for entry
```

### Genesis's Role in 3DS

Genesis **cannot intercept or bypass** the 3DS OTP sent by the issuing bank. However, it influences the **issuer's risk decision** to favor frictionless authentication:

| Signal | How Genesis Helps | Impact on Challenge Rate |
|--------|------------------|:----------------------:|
| Device fingerprint consistency | Anomaly patcher makes device look real | ↓ Challenge rate |
| IP reputation | Residential proxy via ProxyRouter | ↓ Challenge rate |
| Purchase history | Injected commerce history shows prior purchases | ↓ Challenge rate |
| Billing address match | Profile address matches card billing | ↓ Challenge rate |
| Browser fingerprint | Kiwi/Chrome with real cookies and history | ↓ Challenge rate |
| Session warmup | AI agent browses before purchase | ↓ Challenge rate |

### 3DS Challenge Rates by BIN (from Intelligence Tools)

| Issuer | Network | Typical Challenge Rate |
|--------|---------|:---------------------:|
| Chase | Visa | ~15% (low) |
| Bank of America | Visa | ~20% (low) |
| Capital One | Visa/MC | ~25% (medium-low) |
| Citibank | Visa/MC | ~30% (medium) |
| Wells Fargo | Visa | ~20% (low) |
| HSBC | MC | ~35% (medium) |
| Amex (direct) | Amex | ~40% (medium-high) |

**Source:** `docs/08-intelligence-tools.md` §9 (3DS Strategy Advisor)

---

## 6. OTP Auto-Detection (Device SMS)

When a 3DS or Google verification OTP is sent to the device, Genesis can auto-detect it via the `/api/genesis/request-otp` endpoint:

```python
@router.post("/request-otp")
async def genesis_request_otp(body: OtpRequestBody):
    # Read latest SMS from device
    sms_out = adb_shell("127.0.0.1:6520",
        "content query --uri content://sms/inbox "
        "--projection body --sort 'date DESC' | head -5")

    # Try Google format: G-XXXXXX
    code_match = re.search(r'G-(\d{6})', sms_out)
    if code_match:
        return {"otp": code_match.group(1), "source": "device_sms"}

    # Try generic 6-digit code
    code_match = re.search(r'\b(\d{6})\b', sms_out)
    if code_match:
        return {"otp": code_match.group(1), "source": "device_sms"}

    # No OTP found — manual entry required
    return {"otp": None, "source": "manual",
            "message": f"Enter OTP sent to {body.phone} manually"}
```

### OTP Detection Patterns

| Pattern | Source |
|---------|--------|
| `G-XXXXXX` | Google account verification |
| `\b\d{6}\b` | Generic 6-digit OTP (bank, 2FA) |

### Limitation

OTP auto-detection only works if the OTP is sent **to the device's phone number**. If the real cardholder's phone receives the OTP, Genesis cannot intercept it. The `real_phone` parameter in the pipeline allows specifying the phone number for OTP forwarding setups.

**Source:** `server/routers/genesis.py` lines 253–290

---

## 7. Provincial Injection Protocol

The Provincial Injection Protocol (`provincial_injection_protocol.py`) is a standalone script that implements the complete zero-auth payment injection for a specific region (US or GB):

### Steps

```
[1/5] FORGE REGIONAL IDENTITY
      → AndroidProfileForge with region-specific settings

[2/5] INJECT BASE PROFILE
      → ProfileInjector.inject_full_profile(card_data=config["card"])

[3/5] INJECT WALLET (ZERO-AUTH MODE)
      → WalletProvisioner.provision_card(zero_auth=True)  ← CRITICAL

[4/5] INJECT PROVINCIAL APP DATA
      → AppDataForger with region-specific apps (Chase, PayPal, Venmo, etc.)

[5/5] VERIFY INJECTION
      → Check COIN.xml, tapandpay.db, NFC status
```

### Regional App Targets

**US Region:**
- com.chase.sig.android (Chase Mobile)
- com.paypal.android.p2pmobile (PayPal)
- com.venmo (Venmo)
- com.squareup.cash (Cash App)
- com.amazon.mShop.android.shopping (Amazon)
- com.coinbase.android (Coinbase)

**GB Region:**
- com.monzo.android (Monzo)
- com.revolut.revolut (Revolut)
- com.paypal.android.p2pmobile (PayPal UK)
- com.amazon.mShop.android.shopping (Amazon UK)
- com.binance.dev (Binance)

### API Endpoint

```
POST /api/genesis/provincial-inject/{device_id}
Body: {"region": "US"}
```

**Source:** `provincial_injection_protocol.py` lines 84–190, `server/routers/provision.py` lines 936–964

---

## 8. Play Integrity & Attestation

Google Pay NFC requires Play Integrity attestation to process payments. The attestation level determines which merchants/terminals will accept the transaction:

### Attestation Tiers

| Tier | What It Proves | Pass Rate | NFC Payment |
|------|---------------|:---------:|:-----------:|
| **Basic** | Not obviously compromised | 100% | ❌ Not sufficient |
| **Device** | Real device fingerprint | ~95% | ✅ Most merchants |
| **Strong** | Hardware TEE attestation | ~72-80% | ✅ All merchants |

### Genesis 3-Tier Attestation Strategy

The anomaly patcher Phase 11b (`anomaly_patcher.py` lines 1272-1464) implements a cascading strategy:

**Tier 1: Remote Key Attestation (RKA) Proxy** — Best
- Proxies attestation requests through encrypted TLS 1.3 tunnel to a physical Android device with real TEE
- Physical device generates genuine hardware certificate chain signed by Google's ECDSA P-384 root
- **Immune** to keybox revocation and RKP migration
- Passes STRONG tier every time
- Env: `TITAN_RKA_HOST` (e.g., `192.168.1.50:9443`)

**Tier 2: TEESimulator** — Good
- Zygisk module hooks Binder IPC to keystore2 daemon
- Generates self-consistent virtual EC P-384 keys in memory
- Dynamic key management (not static, avoids revocation)
- Module path: `/data/adb/modules/teesimulator/`
- Env: `TITAN_TEESIM_ENABLED=1`

**Tier 3: Static Keybox** — Fallback
- Validates and pushes `keybox.xml` via `KeyboxManager`
- Pushes to 3 device paths (TrickyStore, PIF, module)
- Checks against Google's attestation CRL at `https://android.googleapis.com/attestation/status`
- **Warning:** Google aggressively revokes leaked keyboxes; RKP migration (April 2026) makes static keyboxes unreliable for Android 13+

Additional steps:
- **Phase 11c (GSF):** Align GSF fingerprint with device identity
- **Boot persistence:** Props survive reboot via `99-titan-patch.sh`

**Source:** `core/anomaly_patcher.py` lines 1272-1531, `core/keybox_manager.py`

---

## 9. Keybox Role in Payment Authentication

### Why Keybox Matters

The hardware keybox (`keybox.xml`) is the cryptographic credential that enables Play Integrity Strong attestation. Without it:

- **Google Pay NFC:** Works for ~85% of merchants (Device tier sufficient)
- **Google Pay NFC at strict merchants:** Fails (Strong tier required)
- **Play Store in-app purchases:** Still works (doesn't require Strong)

### Keybox Lifecycle

| Keybox Age | Strong Pass Rate |
|------------|:----------------:|
| Fresh (<30 days) | ~85% |
| Recent (30–90 days) | ~78% |
| Aged (90–180 days) | ~65% |
| Revoked by Google | 0% |

**Recommendation:** Rotate keyboxes every 60 days. Place at `/opt/titan/data/keybox.xml`.

**Source:** `core/wallet_verifier.py` lines 277–305, `docs/05-wallet-injection.md` §9

---

## 10. End-to-End Zero-Auth Flow

### Complete Flow: Play Store In-App Purchase (Zero-Auth)

```
1. Genesis Pipeline Phase 6: WalletProvisioner.provision_card(zero_auth=True)
   → COIN.xml written with purchase_requires_auth=false
   → tapandpay.db created with DPAN + token
   → GMS billing prefs synced
   → NFC enabled

2. User opens Play Store app → taps "Buy $4.99"

3. Play Store checks COIN.xml:
   → has_payment_method=true ✓
   → purchase_requires_auth=false ✓
   → auth_token present ✓
   → Skips password/biometric prompt

4. Play Store sends purchase request to Google server:
   → account_name matches device Google account ✓
   → default_instrument_id points to funding_source_id ✓
   → billing_supported=true ✓

5. Google server processes:
   → If 3DS not required (most Play Store): Approve immediately
   → If 3DS required (rare for Play Store): Send OTP to cardholder

6. Purchase complete. No interactive auth required.
```

### Complete Flow: NFC Contactless Payment

```
1. Genesis injection:
   → tapandpay.db with DPAN + EMV session keys
   → NFC prefs enabled
   → Keybox loaded (for Strong attestation)

2. Device held near NFC terminal

3. Google Wallet activates:
   → Reads tokens from tapandpay.db
   → Transmits DPAN via NFC HCE (Host Card Emulation)

4. Terminal receives DPAN → sends to acquirer → TSP → issuer

5. Issuer checks:
   → Play Integrity attestation (Device or Strong required)
   → Transaction risk score
   → If low risk: Approve (frictionless)
   → If high risk: Decline or request 3DS

6. Payment result returned to terminal
```

---

## 11. Success Rates by Scenario

| Scenario | Zero-Auth Success Rate | Limiting Factor |
|----------|:---------------------:|----------------|
| Play Store in-app purchase | **~95%** | COIN.xml injection + sync blocking |
| Play Store app purchase | **~93%** | Same as above |
| Play Store subscription | **~93%** | Same, but some require re-auth |
| NFC tap (Play Integrity Device) | **~88%** | Requires correct fingerprint + GSF |
| NFC tap (Play Integrity Strong) | **~72%** | Requires valid non-revoked keybox |
| Chrome web checkout (autofill) | **~40%** | CVV re-prompt required |
| In-app purchase (3rd party billing) | **~70-85%** | Varies by merchant 3DS config |

**Source:** `docs/11-real-world-success-rates.md` §3

---

## 12. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/wallet_provisioner.py` lines 900–940 | `_provision_play_store()` zero-auth section | COIN.xml zero-auth flags |
| `core/wallet_provisioner.py` lines 355–575 | `provision_card(zero_auth=)` | Entry point with zero_auth parameter |
| `server/routers/genesis.py` lines 253–290 | `genesis_request_otp()` | OTP auto-detection from device SMS |
| `server/routers/provision.py` line 727 | Pipeline Phase 6 | `zero_auth=True` default |
| `server/routers/provision.py` lines 936–964 | `genesis_provincial_inject()` | Provincial zero-auth injection |
| `provincial_injection_protocol.py` lines 124–137 | Step 3 | `zero_auth=True` wallet pass |
| `wallet/wallet_core.py` lines 20–43 | `provision_card()` | Convenience wrapper with `zero_auth` |
| `core/wallet_verifier.py` lines 227–239 | `_check_coin_auth()` | Verifies auth is disabled |
| `docs/05-wallet-injection.md` §2, §4 | Cloud sync + COIN.xml | Existing documentation |
| `docs/08-intelligence-tools.md` §9 | 3DS Strategy Advisor | 3DS bypass strategy intelligence |
| `docs/11-real-world-success-rates.md` §3, §4 | Wallet + PI rates | Empirical success rates |

---

*See [07-pipeline-integration.md](07-pipeline-integration.md) for how wallet injection integrates into the full Genesis pipeline.*
