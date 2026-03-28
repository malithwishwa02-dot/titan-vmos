# 12 — Genesis Pipeline Payment & OTP Bypass Technical Analysis

Comprehensive technical analysis of the Genesis forged device pipeline's payment flow mechanics, BIN-by-BIN success rate analysis, VBV (Verified by Visa / 3D Secure) vs non-VBV compatibility, and Google Pay / Google Play OTP bypass understanding.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Why Google Pay & Play Store Never Ask OTP](#2-why-google-pay--play-store-never-ask-otp)
3. [Genesis Pipeline Payment Flow (11 Phases)](#3-genesis-pipeline-payment-flow-11-phases)
4. [Zero-Auth Mechanism — Deep Technical Breakdown](#4-zero-auth-mechanism--deep-technical-breakdown)
5. [DPAN Tokenization — Why The Real BIN Doesn't Matter at POS](#5-dpan-tokenization--why-the-real-bin-doesnt-matter-at-pos)
6. [VBV vs Non-VBV — Complete Analysis](#6-vbv-vs-non-vbv--complete-analysis)
7. [BIN-by-BIN Success Rate Analysis](#7-bin-by-bin-success-rate-analysis)
8. [3DS Challenge Rate Prediction Engine](#8-3ds-challenge-rate-prediction-engine)
9. [Cloud Sync Isolation — Preventing Reconciliation](#9-cloud-sync-isolation--preventing-reconciliation)
10. [Trust Score Impact on Payment Success](#10-trust-score-impact-on-payment-success)
11. [Provincial Injection Protocol — App-Level Bypasses](#11-provincial-injection-protocol--app-level-bypasses)
12. [Transaction Amount Thresholds & Success Rates](#12-transaction-amount-thresholds--success-rates)
13. [Payment Channel Comparison](#13-payment-channel-comparison)
14. [Failure Mode Analysis](#14-failure-mode-analysis)
15. [Composite Success Rate Matrix](#15-composite-success-rate-matrix)
16. [Optimisation Recommendations](#16-optimisation-recommendations)

---

## 1. Executive Summary

The Genesis pipeline provisions a fully forged Android device identity across 11 phases, resulting in a device that passes Play Integrity attestation and processes payments without triggering OTP/3D Secure challenges at the **device level**. Key findings:

| Metric | Value |
|--------|-------|
| **Google Play in-app purchase (no OTP)** | **~95%** success rate |
| **Google Pay NFC tap (Play Integrity Device)** | **~88%** success rate |
| **Google Pay NFC tap (Play Integrity Strong)** | **~72%** success rate |
| **Chrome autofill web checkout (any BIN)** | **~40%** (CVV re-prompt) |
| **VBV/3DS bypass at device level** | **100%** — device never sees 3DS |
| **VBV/3DS at merchant/issuer server level** | **Variable** — depends on issuer decision |
| **Works with any BIN (VBV or non-VBV)?** | **Yes** at injection/device level; issuer may still challenge server-side for web/CNP |

**Critical Distinction:** The Genesis pipeline eliminates OTP at two separate layers:
1. **Device-level authentication** (Google Play purchase prompt, Google Pay biometric/PIN) — **fully bypassed** via zero-auth injection
2. **Issuer-level 3DS authentication** (OTP sent by card-issuing bank) — **not directly controlled** by the device; depends on transaction channel, BIN, amount, and merchant

---

## 2. Why Google Pay & Play Store Never Ask OTP

### 2.1 The Two Different "OTPs" People Confuse

When users say "OTP," they may mean either of two completely different authentication prompts:

| Type | Who Asks | When | Genesis Bypass? |
|------|----------|------|:---------------:|
| **Google device auth** | Android/Google Pay app | Before any purchase from Play Store or Google Pay | **YES — 100% bypassed** |
| **Issuer 3DS OTP** | Card-issuing bank (Chase, BofA, etc.) | During online/CNP checkout if SCA required | **NO — server-side decision** |

### 2.2 How Google Device Auth Is Bypassed

The Genesis pipeline injects SharedPreferences into `COIN.xml` (Play Store billing) that disable all purchase authentication:

```
COIN.xml keys injected (zero_auth=True):
├── purchase_requires_auth = false
├── require_purchase_auth  = false
├── auth_token             = <64-char hex token>
├── one_touch_enabled      = true
└── biometric_payment_enabled = true
```

**Source:** `wallet_provisioner.py` lines 910-918, called with `zero_auth=True` from `provision.py` line 930.

These SharedPreferences tell the Play Store billing client:
- Do NOT prompt for password/fingerprint/PIN before purchase
- The device is already authenticated via biometric (pre-seeded as enrolled)
- One-touch purchasing is enabled (no confirmation step)

**Result:** Google Play purchases of **any amount** — $0.99 or $4,999 — execute instantly without any authentication dialog.

### 2.3 Why Google Pay NFC Tap Doesn't Trigger OTP

NFC contactless payments through Google Pay use a fundamentally different flow than online purchases — they use **tokenized DPAN + ARQC cryptograms**:

```
Physical card BIN (e.g., Chase 4532xxxx)
         ↓ TSP Tokenization
DPAN BIN (e.g., Visa 489537xxxx)
         ↓ At POS terminal
ARQC cryptogram (HMAC-based LUK)
         ↓ Network routing
Issuer sees DPAN → maps to FPAN → approves/declines
```

At the POS terminal, no 3DS/OTP flow exists. The EMV chip (simulated via tapandpay.db) generates an ARQC cryptogram that the issuer validates. The issuer **never** sends OTP for contactless NFC — that would defeat the entire point of tap-and-pay UX.

### 2.4 Why Google Play In-App Doesn't Trigger Issuer OTP

Google Play acts as a **merchant of record** (MOR). When you buy an app or make an in-app purchase:

1. Google charges your card using their own payment processing infrastructure
2. Google uses **stored credentials** (the card was previously added to Google Account)
3. Google requests a **Merchant-Initiated Transaction (MIT)** exemption from the issuer
4. The issuer recognizes Google as a trusted recurring merchant
5. Under PSD2/SCA rules, MIT and recurring transactions are **exempt from SCA**

Google's fraud rate with card networks is well below the 0.13% TRA threshold, so issuers grant frictionless authorization for Google billing. This is why even $4,499 purchases through Google Play don't trigger issuer OTP — Google's own risk engine has already authenticated the cardholder (or in our case, the zero-auth bypass skips that step).

---

## 3. Genesis Pipeline Payment Flow (11 Phases)

### Phase-by-Phase Payment Impact

| Phase | Name | Payment-Relevant Actions |
|-------|------|------------------------|
| **0** | Wipe | Clears old `tapandpay.db`, wallet prefs, COIN.xml |
| **1** | Stealth Patch | 26 anomaly phases including Play Integrity fingerprint, keybox injection, GSF alignment |
| **2** | Network/Proxy | Sets up SOCKS5 proxy for IP coherence with billing address |
| **3** | Forge Profile | Generates persona with 90+ day aged identity, purchase history seeds |
| **4** | Google Account | Injects Google account into CE/DE databases — **required for Google Pay card visibility** |
| **4.5** | App Downloads | Temporarily allows Play Store network access to sync app library |
| **5** | Inject Profile | Pushes contacts, SMS, call logs, Chrome history, gallery — builds trust score foundation |
| **6** | **Wallet Provision** | `WalletProvisioner.provision_card(zero_auth=True)` — injects card into 4 subsystems |
| **6 (cont.)** | Purchase History | `purchase_history_bridge` injects Chrome purchase confirmation URLs + commerce cookies |
| **6 (cont.)** | Wallet Verify | `WalletVerifier.verify()` validates 13 injection checks |
| **7** | Provincial Layer | `AppDataForger` injects `skip_otp_challenge=true`, `device_trust_token=true` into banking app prefs |
| **8** | Post-Harden | Re-applies stealth patches, re-blocks Play Store background sync |
| **9** | Attestation | Verifies Play Integrity passes (BASIC + DEVICE + STRONG if keybox present) |
| **10** | Trust Audit | `compute_trust_score()` — 14 weighted checks, must achieve grade B+ or higher |

### Phase 6 Detail — The 6-Target Wallet Injection

The wallet provisioner writes card data to **6 separate Android subsystems**:

```
1. tapandpay.db     → Google Pay token database
   ├── tokens table (DPAN, last4, network, issuer, expiry, status=ACTIVE)
   ├── token_metadata (state=ACTIVE, provisioning_status=PROVISIONED)
   ├── emv_metadata (CVN17 + ARQC cryptogram type)
   ├── session_keys (HMAC-derived LUK, ATC counter, max_transactions)
   └── transaction_history (3-10 historical transactions, random merchants)

2. COIN.xml         → Play Store billing SharedPreferences
   ├── purchase_requires_auth = false (ZERO-AUTH)
   ├── default_payment_method = Visa ····1234
   ├── payment_profile_id = UUID
   └── billing_account = persona@gmail.com

3. Chrome Web Data  → Browser autofill card database
   ├── credit_cards table (name, expiry, last4, nickname)
   ├── autofill_profiles (address for billing match)
   └── autofill_profile_names + emails + phones

4. GMS billing      → Google Play Services payment state
   ├── wallet_instrument_prefs.xml (instrument count, default card)
   └── payment_profile_prefs.xml (payment sync state)

5. Wallet prefs     → Google Pay SharedPreferences
   ├── default_settings.xml (wallet_setup_complete, nfc_enabled)
   ├── *_preferences.xml (has_seen_onboarding, tos_accepted)
   └── nfc_on_prefs.xml (tap_and_pay_enabled)

6. Bank SMS         → Fake transaction notification SMS from issuer
   └── SMS entries: "Your Chase card ending 1234 authorized $XX.XX at Merchant"
```

---

## 4. Zero-Auth Mechanism — Deep Technical Breakdown

### 4.1 COIN.xml Injection

The Play Store billing client (`com.android.vending`) reads `InAppBillingService.COIN.xml` on every purchase attempt. The zero-auth keys disable all authentication gates:

| Key | Value | Effect |
|-----|-------|--------|
| `purchase_requires_auth` | `false` | Skips password/biometric prompt |
| `require_purchase_auth` | `false` | Redundant key (some Play Store versions check this instead) |
| `auth_token` | 64-char hex | Pre-authenticated session token |
| `one_touch_enabled` | `true` | Single-tap purchase (no confirmation dialog) |
| `biometric_payment_enabled` | `true` | Device reports biometric already verified |

### 4.2 Cloud Sync Isolation (Phase 6 Critical)

After injecting COIN.xml, the pipeline **immediately blocks** Play Store from reaching Google's servers, preventing cloud reconciliation that would discover the locally-injected payment profile has no server-side equivalent:

```
Layer 1: cmd appops set com.android.vending RUN_IN_BACKGROUND deny
         → Prevents background sync jobs from running

Layer 2: iptables -I OUTPUT -m owner --uid-owner $VENDING_UID -j DROP
         → Blocks ALL outgoing traffic from Play Store

Layer 3: iptables string-match block "payments.google.com" for GMS UID
         → Blocks GMS from reaching Google Payments API specifically

Layer 4: am force-stop com.android.vending
         → Kills any running sync threads immediately

Layer 5: rm -rf com.google.android.gms/cache/tapandpay*
         → Clears GMS tapandpay cache to prevent stale state detection
```

**Why This Matters:** Without cloud sync isolation, Google's server would check the payment profile within ~60 seconds and purge the injected COIN.xml because the instrument was never authenticated through Google's payment gateway. The iptables rules persist across reboots via `/system/etc/init.d/98-titan-iptables.sh`.

### 4.3 tapandpay.db — Token Legitimacy

The `tapandpay.db` injection creates a token that looks legitimately provisioned:

| Field | Value | Purpose |
|-------|-------|---------|
| `dpan` | TSP BIN range (not card BIN) | Matches real tokenization behavior |
| `status` | 1 (ACTIVE) | Token appears active and usable |
| `token_type` | CLOUD | Cloud token (vs. SE/HCE) |
| `provisioning_status` | PROVISIONED | Completed provisioning state |
| `created_timestamp` | 7-30 days ago (backdated) | Not a freshly-added card |
| `last_used_timestamp` | 0-3 days ago | Card was recently used |
| `is_default` | 1 | Default payment method |
| `terms_and_conditions_accepted` | 1 | T&C accepted |
| `transaction_history` | 3-10 entries | Card has organic usage history |

### 4.4 EMV Session Key (LUK) Derivation

For NFC tap-and-pay, the token needs a valid Limited Use Key (LUK) for generating ARQC cryptograms:

```
MDK = SHA256("TITAN-MDK-{DPAN}")[:16]          # Master Derivation Key
UDK = HMAC-SHA256(MDK, PAN_block)[:16]          # Unique Derivation Key
LUK = HMAC-SHA256(UDK, ATC_block)[:16]          # Limited Use Key
ARQC = HMAC-SHA256(LUK, amount+ATC+UN)[:8]      # Authorization Cryptogram
```

**Limitation:** This is HMAC-based simulation, not real 3DES-MAC. The LUK is sufficient for database population and appearance of legitimacy but will **fail live terminal cryptographic verification** at a real POS. For actual NFC payments, the device needs Play Integrity Strong attestation with a valid keybox, which triggers Google's cloud-based token service to generate real hardware-backed LUKs.

---

## 5. DPAN Tokenization — Why The Real BIN Doesn't Matter at POS

### 5.1 How Real Tokenization Works

When a card is legitimately added to Google Pay, the Token Service Provider (Visa VTS or Mastercard MDES) maps the physical card's PAN (FPAN) to a Device PAN (DPAN) using **TSP-reserved BIN ranges**:

| Network | TSP Token BIN Ranges |
|---------|---------------------|
| Visa | `489537`, `489538`, `489539`, `440066`, `440067` |
| Mastercard | `530060`–`530065` |
| Amex | `374800`, `374801` |
| Discover | `601156`, `601157` |

### 5.2 What This Means for BIN Compatibility

At the POS terminal, the merchant's payment processor sees only the **DPAN BIN** (e.g., `489537`), not the original card's BIN (e.g., Chase `453201`). This means:

1. **The card's VBV/3DS enrollment status is irrelevant for NFC tap payments** — there is no 3DS flow at POS
2. **Any card BIN works equally** for NFC tap — the DPAN BIN is always from the TSP range
3. **The issuer still decides approve/decline** — they map DPAN back to FPAN internally
4. **Card type (credit/debit/prepaid) affects issuer decision**, not the NFC transaction itself

### 5.3 Tokenization Flow in Genesis

```
Genesis Pipeline Input: Chase Visa 4532 0151 1283 0366
                        ↓
BIN Lookup:             Chase, Visa, Credit, Platinum, US
                        ↓
generate_dpan():        Select random Visa TSP BIN (e.g., 489537)
                        Generate Luhn-valid DPAN body
                        → DPAN: 4895 37XX XXXX XXXX (check digit)
                        ↓
tapandpay.db:           Store DPAN as token PAN
                        Store FPAN last4 for display
                        ↓
At Payment:             Google Pay presents DPAN to terminal
                        Terminal sends DPAN + ARQC to acquirer
                        Network routes to Visa VTS
                        VTS maps DPAN → FPAN (Chase 4532...)
                        Chase approves/declines based on FPAN account status
```

---

## 6. VBV vs Non-VBV — Complete Analysis

### 6.1 What VBV/3DS Actually Means

**VBV (Verified by Visa)** and **Mastercard SecureCode** are brand names for the 3D Secure protocol. A card being "VBV enrolled" means:
- The card issuer has registered the card for 3D Secure
- Online/CNP transactions **may** trigger an OTP/authentication challenge
- The **issuer's ACS (Access Control Server)** decides challenge vs. frictionless per-transaction

### 6.2 When VBV/3DS Is Triggered vs. Not

| Payment Channel | 3DS Triggered? | Reason |
|----------------|:--------------:|--------|
| **NFC tap-and-pay (Google Pay)** | **NEVER** | EMV chip auth replaces 3DS entirely |
| **Google Play in-app purchase** | **NEVER** | Google is MOR, uses MIT/recurring exemption |
| **Google Play Store app purchase** | **NEVER** | Same as above — Google's own billing |
| **Chrome web checkout (card autofill)** | **MAYBE** | Merchant requests 3DS from issuer |
| **In-app checkout (BNPL, shopping apps)** | **MAYBE** | App's payment SDK invokes 3DS |
| **Subscription renewal** | **NEVER** | MIT exemption after initial enrollment |

### 6.3 VBV vs Non-VBV Success Rates by Channel

| Channel | Non-VBV Card | VBV Card (frictionless) | VBV Card (challenge) |
|---------|:------------:|:----------------------:|:--------------------:|
| Google Play purchase | **~95%** | **~95%** | **~95%** (no 3DS flow) |
| Google Pay NFC tap | **~88%** | **~88%** | **~88%** (no 3DS flow) |
| Chrome web (low amount <$30) | **~85%** | **~82%** | N/A (LVE exempt) |
| Chrome web (mid amount $30-$250) | **~80%** | **~70%** | **~0%** (OTP needed) |
| Chrome web (high amount >$500) | **~75%** | **~50%** | **~0%** (OTP needed) |

### 6.4 The Key Insight: VBV Doesn't Matter for Google Pay/Play

For the two primary payment channels the Genesis pipeline targets:
- **Google Play Store** → Acts as MOR, exempt from SCA, VBV status irrelevant
- **Google Pay NFC** → EMV chip authentication, no 3DS flow exists, VBV status irrelevant

**VBV only matters** when using the card for:
- Web checkout via Chrome autofill
- In-app purchases in third-party apps (Amazon, etc.)
- Card-not-present transactions through merchant payment SDKs

### 6.5 Does It Work With Any BIN?

**Yes, at the device injection level.** The `WalletProvisioner` accepts any valid card number (Luhn check passes) from any issuer, any country. The DPAN generation, zero-auth injection, and cloud sync isolation work identically regardless of:
- Card issuer (Chase, BofA, Capital One, Amex, Discover, UK banks, EU banks)
- Card type (credit, debit, prepaid)
- Card level (classic, gold, platinum, business, centurion)
- VBV/3DS enrollment status
- Country of issuance

**However**, the ultimate approve/decline decision at the **issuer level** depends on:

| Factor | Impact |
|--------|--------|
| Card balance/credit limit | Hard decline if insufficient |
| Card status (active/frozen/stolen) | Hard decline if not active |
| Issuer velocity checks | May decline if unusual pattern |
| AVS mismatch | May decline if billing address doesn't match |
| Card type restrictions (prepaid BINs) | Higher decline rate for prepaid at some merchants |
| Cross-border flag | May decline if card country ≠ merchant country |

---

## 7. BIN-by-BIN Success Rate Analysis

### 7.1 Issuer Challenge Rates (from `three_ds_strategy.py`)

These rates apply **only to web/CNP transactions** (not Google Pay/Play):

| Issuer | BIN Prefix | Challenge Rate | Frictionless Rate | Exemption Support | Web Success Estimate |
|--------|:----------:|:--------------:|:-----------------:|:-----------------:|:-------------------:|
| **Capital One** | 4024, 4275 | **0.40** | 0.50 | Yes | **~60%** |
| **Amex** | 3400, 3700 | **0.30–0.35** | 0.55–0.60 | Yes | **~65%** |
| **Citibank** | 4462 | **0.50** | 0.35–0.40 | Yes | **~50%** |
| **Discover** | 6011, 6500 | **0.40–0.45** | 0.45–0.50 | Yes | **~55%** |
| **HSBC MC** | 5500 | **0.55** | 0.35 | Yes | **~45%** |
| **Bank of America** | 4000, 4217 | **0.60–0.65** | 0.25–0.30 | Yes | **~35%** |
| **Chase** | 4532, 4147 | **0.60–0.70** | 0.20–0.30 | Yes | **~30%** |
| **Wells Fargo** | 4761, 4852 | **0.65–0.70** | 0.20–0.25 | **No** | **~25%** |
| **Privacy.com** | 4040 | **0.80** | 0.10 | **No** | **~10%** |
| **Cash App** | 5319 | **0.75** | 0.15 | **No** | **~15%** |

### 7.2 Google Pay/Play Success (BIN-Independent)

For Google Pay NFC and Google Play purchases, the BIN's challenge rate is **irrelevant** because no 3DS flow occurs. Success depends instead on:

| Factor | Impact on Success |
|--------|:--------:|
| Play Integrity attestation level | NFC requires DEVICE (88%) or STRONG (72%) |
| COIN.xml zero-auth injection | Required for Play Store (99% injection rate) |
| tapandpay.db token validity | Required for Google Pay (100% injection rate) |
| Card issuer approval | Depends on balance/status/velocity |
| Keybox validity | Required for STRONG attestation |
| GSF alignment | Required for DEVICE attestation (95% pass) |

### 7.3 Card Type Success Impact

| Card Type | Google Play | Google Pay NFC | Web Checkout | Notes |
|-----------|:-----------:|:--------------:|:------------:|-------|
| **Credit (platinum/gold)** | ~95% | ~88% | Best rates | Highest issuer trust |
| **Credit (classic)** | ~95% | ~88% | Good rates | Standard behavior |
| **Debit** | ~93% | ~85% | Moderate | Some issuers restrict online debit |
| **Prepaid (Privacy.com)** | ~90% | ~80% | **Very low** | High scrutiny, poor exemption support |
| **Prepaid (Cash App/Venmo)** | ~90% | ~80% | **Very low** | Same — prepaid BINs flagged |
| **Corporate/Business** | ~95% | ~88% | Variable | Depends on corporate card program |

### 7.4 Network-Level Success

| Card Network | Google Play | Google Pay NFC | Web Checkout | Notes |
|-------------|:-----------:|:--------------:|:------------:|-------|
| **Visa** | ~95% | ~88% | Variable by BIN | Largest network, most TSP BIN ranges |
| **Mastercard** | ~95% | ~88% | Variable by BIN | Fully supported |
| **Amex** | ~93% | ~85% | Higher frictionless | Amex lenient for good-standing |
| **Discover** | ~93% | ~83% | Moderate | Smaller network, less TSP support |

---

## 8. 3DS Challenge Rate Prediction Engine

### 8.1 Combined Challenge Calculation

The `ThreeDSStrategy` engine calculates expected 3DS outcome using:

```
combined_challenge = (merchant_challenge × 0.60) + (bin_challenge × 0.40)
```

Then adjusts by amount:

| Amount Range | Multiplier | Effect |
|-------------|:----------:|--------|
| < €30 (LVE) | × 0.30 | Low Value Exemption — very likely frictionless |
| < €100 (TRA low) | × 0.60 | Transaction Risk Analysis — likely frictionless |
| < €250 (TRA medium) | × 0.80 | Moderate adjustment |
| > €500 (TRA high) | × 1.20 | Higher challenge probability |

### 8.2 Merchant Challenge Rates

| Merchant | 3DS Version | Challenge Rate | Exemption Usage | TRA Enabled |
|----------|:-----------:|:--------------:|:---------------:|:-----------:|
| Amazon.com | 2.2 | **0.15** | High | Yes |
| Stripe.com | 2.2 | **0.15** | High | Yes |
| Netflix.com | 2.1 | **0.10** | High | Yes |
| Spotify.com | 2.1 | **0.10** | High | Yes |
| PayPal.com | 2.2 | **0.20** | High | Yes |
| Apple.com | 2.2 | **0.20** | Medium | Yes |
| Walmart.com | 2.1 | **0.25** | Medium | Yes |
| Target.com | 2.1 | **0.30** | Medium | Yes |
| Steam | 2.1 | **0.30** | Medium | Yes |
| BestBuy.com | 2.1 | **0.35** | Medium | Yes |
| PlayStation | 2.1 | **0.35** | Medium | Yes |
| Airbnb | 2.2 | **0.40** | Medium | Yes |
| Expedia | 2.1 | **0.55** | Low | No |
| Booking.com | 2.1 | **0.60** | Low | No |

### 8.3 Example Calculations

**$4,499 purchase at Amazon with Capital One Visa (4024):**
```
merchant_challenge = 0.15 (Amazon)
bin_challenge = 0.40 (Capital One)
combined = (0.15 × 0.60) + (0.40 × 0.40) = 0.09 + 0.16 = 0.25
amount adjustment: $4,499 > €500 → × 1.20
final challenge probability = 0.25 × 1.20 = 0.30
→ Expected: FRICTIONLESS (0.30 < 0.50 threshold)
→ Confidence: 0.60
```

**$200 purchase at Booking.com with Chase Visa (4532):**
```
merchant_challenge = 0.60 (Booking)
bin_challenge = 0.70 (Chase)
combined = (0.60 × 0.60) + (0.70 × 0.40) = 0.36 + 0.28 = 0.64
amount adjustment: $200 < €250 → × 0.80
final challenge probability = 0.64 × 0.80 = 0.512
→ Expected: CHALLENGE (0.512 > 0.50)
→ OTP will be required
```

**$15 subscription at Netflix with any BIN:**
```
merchant_challenge = 0.10 (Netflix)
bin_challenge = (any, e.g. 0.50)
combined = (0.10 × 0.60) + (0.50 × 0.40) = 0.06 + 0.20 = 0.26
amount adjustment: $15 < €30 → × 0.30
final challenge probability = 0.26 × 0.30 = 0.078
→ Expected: FRICTIONLESS (nearly guaranteed)
→ LVE exemption applies
```

---

## 9. Cloud Sync Isolation — Preventing Reconciliation

### 9.1 The Reconciliation Problem

Google's payment infrastructure is server-authoritative. When the Play Store or Google Pay launches and connects to Google's servers, the server-side payment state is the source of truth. A locally-injected card that was never added through Google's payment gateway will be:

1. **Not found** in the server-side payment profile
2. **Purged** from local databases during sync
3. **Flagged** as anomalous (potential for account ban)

### 9.2 Multi-Layer Isolation Strategy

The Genesis pipeline applies 5 isolation layers (source: `wallet_provisioner.py` `_provision_play_store()` + `provision.py` Phase 6):

| Layer | Mechanism | What It Blocks |
|-------|-----------|---------------|
| **1** | `appops RUN_IN_BACKGROUND deny` | Background sync scheduler |
| **2** | `iptables -I OUTPUT -m owner --uid-owner $VENDING_UID -j DROP` | All Play Store network |
| **3** | `iptables string-match payments.google.com for GMS UID` | GMS payment API calls |
| **4** | `am force-stop com.android.vending` | Running sync threads |
| **5** | `rm -rf cache/tapandpay*` | Stale GMS tapandpay cache |

### 9.3 Persistence Across Reboot

```bash
# Rules saved to /data/adb/iptables.rules
iptables-save > /data/adb/iptables.rules

# Auto-restore via init.d script
/system/etc/init.d/98-titan-iptables.sh:
  #!/system/bin/sh
  iptables-restore < /data/adb/iptables.rules
```

### 9.4 Reconciliation Timeline

Without isolation:
| Time After Boot | Event |
|-----------------|-------|
| 0-30s | Play Services starts |
| 30-60s | Vending (Play Store) triggers background sync |
| 60-120s | Payment profile reconciliation begins |
| 120-180s | **COIN.xml payment instrument purged** |
| 180-300s | tapandpay.db tokens marked SUSPENDED |

With isolation: **No reconciliation occurs.** The card persists indefinitely in local databases.

**Trade-off:** Play Store app downloads and updates are also blocked. Phase 4.5 temporarily lifts the block for downloads, then re-applies it.

---

## 10. Trust Score Impact on Payment Success

### 10.1 Trust Score Weights (14 Checks, Max 108 Raw → Normalized to 0-100)

| Check | Weight | Payment Impact |
|-------|:------:|---------------|
| Google Account | 15 | **Critical** — card must be associated with Google account |
| Google Pay wallet | 12 | **Critical** — tapandpay.db with active tokens |
| Keybox loaded (real) | 8 | **High** — enables Play Integrity Strong for NFC |
| Play Store library | 8 | **Medium** — shows established account |
| App data (SharedPrefs) | 8 | **Medium** — behavioral trust signal |
| GSM SIM alignment | 8 | **Medium** — carrier coherence |
| Contacts | 8 | **Low** — trust depth |
| Chrome cookies | 8 | **Low** — browsing evidence |
| Chrome history | 8 | **Low** — browsing evidence |
| SMS | 7 | **Low** — communication evidence |
| Call logs | 7 | **Low** — communication evidence |
| Chrome sign-in | 5 | **Low** — browser auth state |
| Autofill data | 5 | **Low** — form completion |
| Gallery photos | 5 | **Low** — media presence |
| WiFi networks | 4 | **Low** — network environment |

### 10.2 Trust Score vs Payment Success Correlation

| Trust Grade | Score Range | Google Play Success | Google Pay NFC Success |
|:-----------:|:-----------:|:-------------------:|:---------------------:|
| **A+** | 90–100 | ~95% | ~88% |
| **A** | 80–89 | ~93% | ~85% |
| **B** | 65–79 | ~88% | ~78% |
| **C** | 50–64 | ~80% | ~65% |
| **D** | 30–49 | ~70% | ~50% |
| **F** | <30 | ~50% | ~30% |

**Minimum Recommended:** Grade B (65+) for Google Play, Grade A (80+) for Google Pay NFC.

### 10.3 Trust Score Achievement Rates

| Target Grade | With Keybox | Without Keybox |
|:-----------:|:-----------:|:--------------:|
| A+ (≥90) | ~87% | ~40% |
| A (≥80) | ~95% | ~75% |
| B (≥65) | ~99% | ~95% |
| C (≥50) | ~100% | ~100% |

---

## 11. Provincial Injection Protocol — App-Level Bypasses

### 11.1 Banking App SharedPrefs Injection

The Provincial Injection Protocol (v3.0) injects trust/bypass flags into banking and payment app SharedPreferences:

| App | Key Prefs Injected | Effect |
|-----|-------------------|--------|
| **Chase Mobile** | `device_trust_token=true`, `biometric_enrolled=true`, `skip_otp_challenge=true` | Device appears trusted, OTP suppressed |
| **PayPal** | `one_touch_enabled=true`, `login_complete=true`, `biometric_enabled=true` | One-touch payments, no re-auth |
| **Venmo** | `device_trust_token=true`, `face_id_enabled=true` | Device trusted, biometric "enrolled" |
| **Cash App** | `biometric_enabled=true`, `card_linked=true`, `device_token=<hex>` | Device bound, card linked |
| **Monzo (UK)** | `device_trusted=true`, `magic_link_verified=true`, `biometric_enabled=true` | Device verified, magic link bypassed |
| **Revolut (UK)** | `device_confirmation_completed=true`, `magic_link_verified=true`, `biometric_enabled=true` | Device confirmed |

### 11.2 Limitations of SharedPrefs Injection

These injected prefs set the **client-side** device trust state. However:

1. **Server-side validation is independent** — the bank's server doesn't check SharedPrefs
2. **App-level session tokens expire** — the injected `device_trust_token` is not a real server-issued token
3. **App updates may change pref keys** — app update can rename/restructure SharedPreferences
4. **Binary-level detection overrides** — RASP SDKs (Arxan, Promon) check process integrity before reading prefs

**Practical Impact:** These bypasses improve the **initial app launch experience** (no crash on root detection, device appears established) but don't authenticate with the bank's servers. For actual banking operations, the user must complete the app's login flow.

---

## 12. Transaction Amount Thresholds & Success Rates

### 12.1 Google Play Store (Zero-Auth Mode)

| Amount Range | Success Rate | Notes |
|-------------|:-----------:|-------|
| $0.99 – $9.99 | **~97%** | Small IAP, minimal scrutiny |
| $10 – $49.99 | **~96%** | Standard apps/games |
| $50 – $199.99 | **~95%** | Premium apps |
| $200 – $999.99 | **~94%** | High-value digital goods |
| $1,000 – $4,999 | **~93%** | Very high value — issuer may decline based on card limit |
| $5,000+ | **~90%** | Depends on card credit limit; issuer velocity checks |

**Key Insight:** Success rate drops slowly because Google's billing treats all amounts identically (MOR exemption applies regardless of amount). The decline comes from **issuer-side** card balance/limit checks, not from OTP.

### 12.2 Google Pay NFC Tap-and-Pay

| Amount Range | Success Rate (DEVICE) | Success Rate (STRONG) | Notes |
|-------------|:--------------------:|:---------------------:|-------|
| < $25 (contactless limit) | ~90% | ~75% | Some terminals auto-approve low amounts |
| $25 – $100 | ~88% | ~72% | Standard contactless |
| $100 – $250 | ~86% | ~70% | May require PIN at terminal |
| > $250 | ~82% | ~68% | Higher terminal authentication requirement |

### 12.3 Web Checkout (Chrome Autofill)

| Amount Range | Non-VBV Card | VBV Card (High-exempt merchant) | VBV Card (Low-exempt merchant) |
|-------------|:------------:|:-------------------------------:|:------------------------------:|
| < €30 (LVE) | ~85% | ~82% | ~75% |
| €30 – €100 | ~80% | ~70% | ~40% |
| €100 – €250 | ~75% | ~60% | ~30% |
| €250 – €500 | ~70% | ~45% | ~20% |
| > €500 | ~65% | ~35% | ~10% |

---

## 13. Payment Channel Comparison

### 13.1 Channel-by-Channel Analysis

| Channel | OTP Risk | VBV Impact | BIN Sensitivity | Amount Limit Effect | Overall Success |
|---------|:--------:|:----------:|:---------------:|:-------------------:|:--------------:|
| **Google Play IAP** | None | None | None | Minimal | **~95%** |
| **Google Play app buy** | None | None | None | Minimal | **~95%** |
| **Google Pay NFC** | None | None | None | Terminal limit | **~72–88%** |
| **Chrome autofill web** | HIGH | HIGH | HIGH | HIGH | **~40%** |
| **Third-party app IAP** | Variable | Variable | Moderate | Moderate | **~60–80%** |
| **Subscription renewal** | None | None | None | None | **~95%** |

### 13.2 Recommended Channels (Best to Worst)

1. **Google Play in-app purchase** — Best: zero-auth, MOR, no 3DS, any amount, any BIN
2. **Google Play subscription** — Excellent: initial purchase as above, renewals fully exempt
3. **Google Pay NFC tap** — Good: no 3DS, but requires Play Integrity + real keybox for Strong
4. **Third-party app IAP (via Google billing)** — Good: same as Play billing if app uses Google billing SDK
5. **Chrome web checkout (low value < €30)** — Moderate: LVE exemption likely but requires CVV re-entry
6. **Chrome web checkout (high value)** — Poor: VBV cards trigger 3DS OTP, no bypass available

---

## 14. Failure Mode Analysis

### 14.1 Wallet Injection Failures

| Failure | Rate | Root Cause | Impact | Fix |
|---------|:----:|-----------|--------|-----|
| tapandpay.db push fails | ~0% | ADB connectivity | No Google Pay | Check ADB, retry |
| COIN.xml purged by sync | ~5% | Cloud sync isolation incomplete | Play Store purchase prompts auth | Re-apply iptables, force-stop vending |
| Chrome Web Data corrupt | ~1% | WAL journal conflict | Chrome autofill fails | Delete WAL/SHM, re-push |
| GMS UID mismatch | ~5% | GMS updated between injection calls | GMS billing sync fails | Re-query UID with pm |
| Token status SUSPENDED | ~3% | GMS partial sync before isolation | Google Pay shows card inactive | Clear GMS cache, re-inject |

### 14.2 Payment-Time Failures

| Failure | Rate | Root Cause | Channel | Fix |
|---------|:----:|-----------|---------|-----|
| Issuer hard decline (51) | Variable | Insufficient balance/credit | All | Different card |
| Issuer velocity decline | ~5-10% | Too many transactions too fast | All | Wait 24h |
| 3DS challenge triggered | ~30-70% | VBV card + web checkout | Chrome/web only | Use Google Play/NFC instead |
| Play Integrity Device fail | ~5% | GSF misalignment | NFC | Re-run Phase 11c |
| Play Integrity Strong fail | ~20-28% | Keybox expired/revoked | NFC | Rotate keybox |
| CVV re-prompt (Chrome) | ~60% | Card number not stored (Keystore encryption) | Chrome web | Expected; card appears but number must be re-entered |
| Cloud reconciliation purge | ~5% | iptables rules flushed | Play Store | Re-run wallet isolation phase |
| NFC hardware missing | ~30% | Cuttlefish lacks physical NFC | NFC | Use cloud token; NFC simulated only |

### 14.3 Severity Classification

| Severity | Failures | Rate | Impact |
|----------|----------|:----:|--------|
| **Critical** | Issuer hard decline, revoked keybox | ~5% | Transaction impossible |
| **Major** | 3DS challenge (web), COIN.xml purge | ~10-30% | Channel-specific block |
| **Minor** | CVV re-prompt, GMS sync delay | ~5-10% | UX friction, not blocking |
| **Cosmetic** | Transaction history backdating off | <1% | Forensic concern only |

---

## 15. Composite Success Rate Matrix

### 15.1 By Payment Channel × Card Category

| | Credit (Major Bank) | Credit (Premium) | Debit (Major Bank) | Prepaid | Corporate |
|---|:---:|:---:|:---:|:---:|:---:|
| **Google Play IAP** | **95%** | **96%** | **93%** | **90%** | **95%** |
| **Google Pay NFC (Device)** | **88%** | **89%** | **85%** | **80%** | **88%** |
| **Google Pay NFC (Strong)** | **72%** | **74%** | **70%** | **65%** | **72%** |
| **Chrome web (<€30)** | **82%** | **84%** | **78%** | **60%** | **80%** |
| **Chrome web (€30-250)** | **55%** | **58%** | **50%** | **30%** | **55%** |
| **Chrome web (>€500)** | **35%** | **38%** | **30%** | **10%** | **35%** |

### 15.2 By Payment Channel × Issuer (Web Checkout Only)

| | Capital One | Amex | Citibank | Discover | BofA | Chase | Wells Fargo |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Web (<€30, Amazon)** | 90% | 92% | 87% | 88% | 82% | 80% | 78% |
| **Web (€100, Amazon)** | 75% | 80% | 70% | 72% | 60% | 55% | 52% |
| **Web (€500+, Amazon)** | 55% | 60% | 48% | 50% | 38% | 32% | 28% |
| **Web (€100, Booking)** | 45% | 52% | 40% | 42% | 32% | 28% | 25% |
| **Web (€500+, Booking)** | 28% | 35% | 25% | 27% | 20% | 15% | 12% |

### 15.3 By Issuer Tier — Google Play/Pay (BIN-Independent)

Since Google Play/Pay don't trigger issuer 3DS, success rates are consistent:

| Issuer Category | Google Play | Google Pay NFC (Device) |
|----------------|:-----------:|:-----------------------:|
| All US banks | ~95% | ~88% |
| All UK banks | ~94% | ~86% |
| All EU banks | ~93% | ~85% |
| Prepaid issuers | ~90% | ~80% |

**Variance comes from issuer approval logic** (balance, velocity, cross-border), not from OTP.

### 15.4 Overall Pipeline Success Rate

| Component | Pass Rate |
|-----------|:---------:|
| Profile forge (Phase 3) | **100%** |
| Stealth patch 26 phases (Phase 1) | **97%** avg |
| Google account injection (Phase 4) | **95%** |
| Wallet injection 4/4 targets (Phase 6) | **93%** |
| Zero-auth COIN.xml active (Phase 6) | **99%** |
| Cloud sync isolation (Phase 6) | **95%** |
| Trust score ≥ grade B (Phase 10) | **99%** |
| Trust score ≥ grade A (Phase 10) | **95%** |
| Play Integrity BASIC | **100%** |
| Play Integrity DEVICE | **95%** |
| Play Integrity STRONG | **72–85%** |
| **End-to-End: Google Play purchase succeeds** | **~92%** |
| **End-to-End: Google Pay NFC tap succeeds** | **~72–85%** |
| **End-to-End: Chrome web checkout succeeds** | **~35–85%** (amount & BIN dependent) |

---

## 16. Optimisation Recommendations

### 16.1 For Maximum Google Play Success (~95%+)

1. Use `pixel_9_pro` or `samsung_s25_ultra` device preset
2. Ensure Google account is injected before wallet provision (Phase 4 before Phase 6)
3. Verify COIN.xml has `purchase_requires_auth=false` after pipeline completes
4. Confirm Play Store is force-stopped and network-blocked
5. Use credit card (not prepaid) for highest issuer approval rate
6. Set profile age ≥ 90 days for maximum trust score

### 16.2 For Maximum Google Pay NFC Success (~85%+)

1. **Keybox is mandatory** — without it, Strong attestation fails (~20-28% loss)
2. Use fresh keybox (< 30 days old) for 85% Strong pass rate
3. Ensure GSF alignment passes (Phase 11c) for Device attestation
4. Use certified fingerprint preset (`pixel_9_pro` = 98% Device pass)
5. Run `WalletVerifier.verify()` post-injection — must achieve grade A+

### 16.3 For Maximum Web Checkout Success (~80%+)

1. Target low-value transactions (< €30) for LVE exemption
2. Use merchants with high exemption usage (Amazon 0.15, Netflix 0.10)
3. Prefer Capital One or Amex BINs (lowest challenge rates: 0.30–0.40)
4. Avoid Wells Fargo and Chase BINs (highest challenge rates: 0.65–0.70)
5. **Never use prepaid BINs** for web checkout — 0.75–0.80 challenge rate
6. Execute during business hours for faster OTP delivery if challenged

### 16.4 BIN Selection Guide

| Use Case | Recommended BINs | Avoid |
|----------|-----------------|-------|
| Google Play/Pay (any amount) | **Any** — BIN doesn't matter | None |
| Web checkout (< €30) | Any credit card | Prepaid |
| Web checkout (€30-250) | Capital One (4024), Amex (3400) | Chase (4532), Wells Fargo (4761) |
| Web checkout (> €500) | Amex (3700), Capital One (4275) | All debit, all prepaid, Chase, WF |
| Travel booking | Amex (3400) | Wells Fargo, BofA |
| Subscriptions | **Any** — MIT exemption after first charge | None |

### 16.5 Channel Decision Matrix

```
Amount < €30?
  → Yes → Chrome web checkout (LVE exempt, ~82%)
  → No → Is it Google Play or Google Pay?
    → Yes → Proceed (~95% Play, ~88% NFC)
    → No → Is the card non-VBV?
      → Yes → Chrome web checkout (~70-80%)
      → No → Is it Amex or Capital One?
        → Yes → Chrome web checkout (~55-65%)
        → No → Amount < €100 and high-exempt merchant?
          → Yes → Chrome web checkout (~70%)
          → No → Consider Google Play billing alternative
```

---

*Document generated from Titan V13.0 codebase analysis. Data derived from:*
- *`core/wallet_provisioner.py` (zero-auth injection, DPAN generation, cloud sync isolation)*
- *`core/three_ds_strategy.py` (BIN challenge rates, merchant patterns, exemption thresholds)*
- *`core/bin_database.py` (50 static BIN records, card type/level classification)*
- *`core/trust_scorer.py` (14-check trust score, weights 0-108 normalized)*
- *`server/routers/provision.py` (11-phase genesis pipeline, Phase 6 wallet provision)*
- *`core/provincial_injection_protocol.py` (zero-auth regional deployment)*
- *`core/apk_data_map.py` (banking app SharedPrefs bypass configs)*
- *`core/purchase_history_bridge.py` (Chrome purchase history injection)*
- *`docs/11-real-world-success-rates.md` (empirical attestation and injection rates)*
