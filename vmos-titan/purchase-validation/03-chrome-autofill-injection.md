# 03 — Chrome Autofill Card Injection

How Genesis injects credit card metadata into Chrome's (or Kiwi Browser's) Web Data SQLite database so the card appears as an autofill suggestion on web checkout forms.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Target Database & Path](#2-target-database--path)
3. [credit_cards Table Schema](#3-credit_cards-table-schema)
4. [Injection Process](#4-injection-process)
5. [Card Number Encryption Limitation](#5-card-number-encryption-limitation)
6. [Address Autofill Co-Injection](#6-address-autofill-co-injection)
7. [Success Rates](#7-success-rates)
8. [Codebase Cross-References](#8-codebase-cross-references)

---

## 1. Overview

Chrome stores saved credit cards in a SQLite database called `Web Data` under the browser's Default profile directory. Genesis creates or modifies this database to insert card records with the cardholder name, expiry, and card nickname. The card then appears in Chrome's autofill dropdown when the user visits a checkout page.

**Limitation:** Chrome encrypts the actual card number using the Android OS Keystore. Genesis cannot replicate this encryption, so the `card_number_encrypted` blob is left empty. The card still appears in autofill UI (showing issuer + last 4 digits) but Chrome will prompt for CVV on first use.

**Source file:** `core/wallet_provisioner.py` — method `_provision_chrome_autofill()` (lines 959–1151)

---

## 2. Target Database & Path

**Chrome path:**
```
/data/data/com.android.chrome/app_chrome/Default/Web Data
```

**Kiwi Browser path (Cuttlefish fallback):**
```
/data/data/com.kiwibrowser.browser/app_chrome/Default/Web Data
```

Genesis auto-detects which browser is installed using `pm path` checks. On Cuttlefish VMs, Chrome often can't install (244MB exceeds the binder pipe limit), so Kiwi Browser is used as a drop-in Chromium replacement.

**Browser detection source:** `core/wallet_provisioner.py` and `core/trust_scorer.py` lines 15–33 (`_resolve_browser_data_path()`)

---

## 3. credit_cards Table Schema

```sql
CREATE TABLE IF NOT EXISTS credit_cards (
    guid                    TEXT PRIMARY KEY,     -- UUID4
    name_on_card            TEXT,                 -- Cardholder name
    expiration_month        INTEGER,              -- 1-12
    expiration_year         INTEGER,              -- 4-digit year
    card_number_encrypted   BLOB,                 -- Empty (cannot encrypt)
    date_modified           INTEGER,              -- Unix timestamp (backdated)
    origin                  TEXT,                 -- "https://pay.google.com"
    use_count               INTEGER DEFAULT 3,    -- Simulated usage count
    use_date                INTEGER,              -- Last use timestamp
    billing_address_id      TEXT,                 -- Links to autofill_profiles
    nickname                TEXT                  -- "Visa •••• 4242"
);
```

### Injected Values

| Field | Value | Notes |
|-------|-------|-------|
| `guid` | `uuid4()` | Unique card identifier |
| `name_on_card` | Cardholder name from card data | Matches persona name |
| `expiration_month` | Card expiry month | 1–12 |
| `expiration_year` | Card expiry year | 4-digit |
| `card_number_encrypted` | Empty BLOB (`b''`) | Cannot replicate OS Keystore encryption |
| `date_modified` | Backdated timestamp | `now - random(7..60 days)` |
| `origin` | `https://pay.google.com` | Makes it appear Google-synced |
| `use_count` | 3–8 (random) | Simulates prior usage |
| `use_date` | Recent timestamp | `now - random(0..7 days)` |
| `billing_address_id` | UUID4 | Links to address record |
| `nickname` | `"{Network} •••• {last4}"` | e.g., "Visa •••• 4242" |

---

## 4. Injection Process

```
1. am force-stop {browser_package}                    ← prevent DB locks
2. adb pull "Web Data" from device (if exists) OR create new SQLite DB
3. CREATE TABLE credit_cards (if not exists)
4. CREATE TABLE autofill_profiles (if not exists)
5. INSERT card record with metadata (empty encrypted number)
6. INSERT address autofill record (persona address)
7. adb push "Web Data" → device browser Default directory
8. Query browser UID: stat -c %U /data/data/{browser_pkg}
9. chown {uid}:{uid} "Web Data"
10. chmod 660 "Web Data"
11. restorecon -R {browser_data_path}
```

**Source:** `core/wallet_provisioner.py` lines 959–1151

---

## 5. Card Number Encryption Limitation

Chrome uses the Android Keystore system to encrypt saved card numbers. The encryption key is:
- Bound to the device hardware (TEE)
- Tied to the specific Chrome installation
- Not extractable via ADB or root access

**Consequence:** Genesis writes an empty `card_number_encrypted` blob. This means:

| Behavior | Status |
|----------|--------|
| Card appears in Chrome autofill dropdown | ✅ Yes (shows issuer + last 4) |
| Card name/expiry auto-filled | ✅ Yes |
| Full card number auto-filled | ❌ No (encrypted field empty) |
| CVV auto-filled | ❌ No (never stored by Chrome) |
| Chrome prompts for card number on first use | ✅ Yes (user must re-enter) |

**Practical impact:** The card appears as a "saved" card in Chrome settings and in autofill suggestions. On checkout, Chrome will show the card as a suggestion but will prompt the user to enter the full card number and CVV. This is adequate for trust scoring (the card appears to be saved) but not for fully automated one-click checkout.

---

## 6. Address Autofill Co-Injection

Genesis also injects an address record linked to the card's `billing_address_id`:

```sql
CREATE TABLE IF NOT EXISTS autofill_profiles (
    guid                TEXT PRIMARY KEY,
    company_name        TEXT DEFAULT '',
    street_address      TEXT,
    dependent_locality  TEXT DEFAULT '',
    city                TEXT,
    state               TEXT,
    zipcode             TEXT,
    sorting_code        TEXT DEFAULT '',
    country_code        TEXT,        -- "US", "GB"
    date_modified       INTEGER,
    origin              TEXT,
    language_code       TEXT,        -- "en-US"
    use_count           INTEGER DEFAULT 2,
    use_date            INTEGER
);

CREATE TABLE IF NOT EXISTS autofill_profile_names (
    guid            TEXT,
    first_name      TEXT,
    middle_name     TEXT DEFAULT '',
    last_name       TEXT,
    full_name       TEXT
);

CREATE TABLE IF NOT EXISTS autofill_profile_emails (
    guid    TEXT,
    email   TEXT
);

CREATE TABLE IF NOT EXISTS autofill_profile_phones (
    guid    TEXT,
    number  TEXT
);
```

This ensures that when Chrome autofill triggers on a checkout form, both the card and the billing address are suggested together, creating a coherent autofill experience.

**Source:** `core/wallet_provisioner.py` lines 1050–1151

---

## 7. Success Rates

| Metric | Rate |
|--------|:----:|
| Web Data file injection | **~99%** |
| Card visible in Chrome autofill UI | **~85%** |
| Card + address suggested on checkout forms | **~80%** |
| One-click checkout (no re-entry needed) | **~40%** |
| Trust score credit (autofill check passes) | **~99%** |

### Why "Visible in UI" is Only ~85%

Chrome's autofill system has internal validation that may refuse to display cards with empty encrypted number blobs on some Chrome versions. Kiwi Browser (Chromium-based) is more permissive and shows the card ~95% of the time.

**Source:** `docs/11-real-world-success-rates.md` §3

---

## 8. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/wallet_provisioner.py` lines 959–1151 | `_provision_chrome_autofill()` | Main Chrome autofill injection |
| `core/wallet_verifier.py` lines 241–251 | `_check_chrome_webdata()` | Verifies Web Data exists |
| `core/trust_scorer.py` lines 197–203 | Check #13 `autofill` | Trust score autofill check |
| `core/trust_scorer.py` lines 15–33 | `_resolve_browser_data_path()` | Chrome vs Kiwi detection |
| `core/purchase_history_bridge.py` lines 211–234 | Chrome cookies | Commerce cookies injected alongside |
| `core/profile_injector.py` lines 306–331 | `_inject_wallet()` | Calls WalletProvisioner |
| `docs/05-wallet-injection.md` §5 | Chrome Autofill docs | Existing documentation |

---

*See [04-gms-billing-sync.md](04-gms-billing-sync.md) for GMS ecosystem billing state synchronization.*
