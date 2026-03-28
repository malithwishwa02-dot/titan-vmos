# 08 — Verification & Trust Scoring

How Genesis verifies wallet injection success and computes trust scores that include wallet/payment checks. Covers the 13-check WalletVerifier, 14-check trust scorer, Life-Path Coherence Score, and BIN database validation.

---

## Table of Contents

1. [WalletVerifier — 13-Check Deep Verification](#1-walletverifier--13-check-deep-verification)
2. [Verification Report Structure](#2-verification-report-structure)
3. [Trust Scorer — Wallet Checks](#3-trust-scorer--wallet-checks)
4. [Life-Path Coherence Score](#4-life-path-coherence-score)
5. [BIN Database Validation](#5-bin-database-validation)
6. [Cerberus Card Validator](#6-cerberus-card-validator)
7. [Success Rate Analysis](#7-success-rate-analysis)
8. [Codebase Cross-References](#8-codebase-cross-references)

---

## 1. WalletVerifier — 13-Check Deep Verification

`WalletVerifier` (`core/wallet_verifier.py`) performs deep post-injection verification of the wallet state on a device. It checks all four injection targets plus ecosystem coherence.

### The 13 Checks

| # | Check Name | What It Verifies | Remediation if Failed |
|:-:|-----------|-----------------|----------------------|
| 1 | `tapandpay_db_exists` | tapandpay.db file present (primary + fallback paths) | Re-run WalletProvisioner |
| 2 | `tapandpay_token_count` | ≥1 token in `tokens` table | No tokens injected — check card data |
| 3 | `token_provisioning_status` | `token_metadata.provisioning_status = 'PROVISIONED'` | token_metadata INSERT failed |
| 4 | `nfc_prefs_enabled` | `nfc_on_prefs.xml` has `nfc_enabled=true` | Re-run Google Pay provisioning |
| 5 | `coin_xml_payment_method` | `COIN.xml` has `has_payment_method=true` | Re-run Play Store provisioning |
| 6 | `coin_auth_disabled` | `COIN.xml` has `purchase_requires_auth=false` | Update COIN.xml |
| 7 | `chrome_webdata_exists` | Chrome `Web Data` file exists | Re-run Chrome autofill provisioning |
| 8 | `gms_wallet_synced` | `wallet_setup_complete=true` in GMS prefs | Re-run GMS billing sync |
| 9 | `gms_payment_profile_synced` | `payment_methods_synced=true` | Re-run GMS billing sync |
| 10 | `keybox_loaded` | `persist.titan.keybox.loaded=1` property set | Place keybox.xml and re-run patcher |
| 11 | `gsf_fingerprint_aligned` | `CheckinService.xml` exists with `deviceId` | Re-run Phase 11c (GSF alignment) |
| 12 | `tapandpay_ownership` | tapandpay.db owner matches wallet app UID | Fix `chown` + `restorecon` |
| 13 | `system_nfc_enabled` | `settings get secure nfc_on = 1` | `settings put secure nfc_on 1` |

### Dual-Path Check (GAP-P11)

For check #1, the verifier checks **both** paths because different GMS versions store `tapandpay.db` in different packages:

```python
# Primary: Google Wallet app
/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db

# Fallback: GMS
/data/data/com.google.android.gms/databases/tapandpay.db
```

If either path has the database, the check passes.

### Helper Methods

| Method | Purpose |
|--------|---------|
| `_sh(cmd)` | Execute ADB shell command on target device |
| `_query_db(db_path, sql)` | Execute SQLite query on a remote database via ADB |
| `_check_file_exists(path)` | Check if file exists on device |
| `_read_shared_prefs(path, key)` | Read a specific key from a SharedPreferences XML file |

**Source:** `core/wallet_verifier.py` lines 42–142

---

## 2. Verification Report Structure

### WalletVerificationReport Dataclass

```python
@dataclass
class WalletVerificationReport:
    device_target: str
    timestamp: float
    score: int            # 0–100
    grade: str            # A+, A, B, C, F
    passed: int           # Number of checks passed
    total: int            # Total checks (13)
    samsung_pay: str      # Explanation of Samsung Pay limitation
    checks: List[WalletCheck]
```

### WalletCheck Dataclass

```python
@dataclass
class WalletCheck:
    name: str             # Check identifier
    passed: bool          # Pass/fail
    detail: str           # What was found
    remediation: str      # How to fix if failed
```

### Grade Scale

| Score | Grade |
|:-----:|:-----:|
| 95–100 | A+ |
| 85–94 | A |
| 70–84 | B |
| 50–69 | C |
| 0–49 | F |

### Scoring Formula

```python
score = int((passed / total) * 100)
# Bonus: +5 if keybox is loaded
if keybox_loaded:
    score = min(100, score + 5)
```

### Example Report

```json
{
    "device_target": "127.0.0.1:6520",
    "timestamp": 1710384000.0,
    "score": 92,
    "grade": "A",
    "passed": 12,
    "total": 13,
    "samsung_pay": "Samsung Pay is NOT supported on Cuttlefish or any rooted device...",
    "checks": [
        {"name": "tapandpay_db_exists", "passed": true,
         "detail": "Found: /data/data/.../tapandpay.db", "remediation": ""},
        {"name": "keybox_loaded", "passed": false,
         "detail": "Keybox NOT loaded",
         "remediation": "Place keybox.xml at /opt/titan/data/keybox.xml and re-run anomaly patcher"}
    ]
}
```

### Typical Scores

| Configuration | Score Range | Grade |
|--------------|:----------:|:-----:|
| Full injection + keybox | 95–100 | A+ |
| Full injection, no keybox | 77–84 | B–B+ |
| Partial injection (3/4 targets) | 62–77 | C–B |
| Failed injection | 0–49 | F |

**Source:** `core/wallet_verifier.py` lines 10–40, 88–142

---

## 3. Trust Scorer — Wallet Checks

The `compute_trust_score()` function (`core/trust_scorer.py`) runs 14 weighted checks via ADB. Two of these directly verify wallet/payment state:

### Check #6: Google Pay Wallet (Weight: 8%)

```python
# Check 6: Google Pay wallet
try:
    tap_db = _sh(target, "ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null")
    if not tap_db:
        tap_db = _sh(target, "ls /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null")

    if tap_db:
        token_count = _sh(target, "sqlite3 ... 'SELECT COUNT(*) FROM tokens'")
        if int(token_count) > 0:
            score += 6  # tapandpay.db with tokens
        # Check keybox
        kb = _sh(target, "getprop persist.titan.keybox.loaded")
        if kb.strip() == "1":
            score += 2  # Keybox bonus
```

**Sub-checks:**
- tapandpay.db exists: +3
- Token count ≥ 1: +3
- Keybox loaded: +2

### Check #13: Chrome Autofill (Weight: 4%)

```python
# Check 13: Autofill data
try:
    webdata = _sh(target, f"ls {browser_data}/Default/'Web Data' 2>/dev/null")
    if webdata:
        cc_count = _sh(target,
            f"sqlite3 {browser_data}/Default/'Web Data' "
            "'SELECT COUNT(*) FROM credit_cards'")
        if int(cc_count) > 0:
            score += 4  # Autofill cards present
```

### All 14 Trust Checks (with wallet context)

| # | Check | Weight | Wallet-Related |
|:-:|-------|:------:|:--------------:|
| 1 | Google account present | 10% | ❌ |
| 2 | Contacts (≥5) | 8% | ❌ |
| 3 | Chrome cookies | 8% | ❌ |
| 4 | Chrome history | 8% | ❌ |
| 5 | Gallery photos | 6% | ❌ |
| 6 | **Google Pay wallet** | **8%** | **✅** |
| 7 | Play Store library | 6% | ❌ |
| 8 | WiFi networks | 6% | ❌ |
| 9 | SMS messages | 6% | ❌ |
| 10 | Call logs | 6% | ❌ |
| 11 | App shared preferences | 8% | ❌ |
| 12 | Chrome sign-in | 8% | ❌ |
| 13 | **Autofill data** | **4%** | **✅** |
| 14 | GSM/SIM alignment | 8% | ❌ |

**Total wallet weight: 12% of trust score**

**Source:** `core/trust_scorer.py` lines 37–210

---

## 4. Life-Path Coherence Score

The `compute_lifepath_score()` function verifies temporal and relational consistency across all profile data, including wallet/purchase data.

### Coherence Checks

| Check | What It Validates | Weight |
|-------|------------------|:------:|
| Email ↔ History | Email domain appears in Chrome history | 20% |
| Maps ↔ WiFi | Visited locations appear in WiFi networks | 20% |
| Contacts ↔ Calls | Phone numbers in contacts appear in call logs | 20% |
| **Purchases ↔ Cookies** | **Merchant domains in purchase history appear in cookies** | **20%** |
| Temporal Consistency | Data timestamps span profile age period correctly | 20% |

### Purchase ↔ Cookie Coherence (20%)

This check validates that commerce purchase URLs in Chrome history have corresponding session cookies:

```python
# Simplified logic from trust_scorer.py
purchase_domains = extract_domains_from_history(
    filter=["amazon.com", "walmart.com", "bestbuy.com", ...])
cookie_domains = extract_domains_from_cookies()

overlap = purchase_domains & cookie_domains
coherence = len(overlap) / max(len(purchase_domains), 1)
# coherence > 0.5 → full credit
```

### Coherence Impact on Anti-Fraud

| Profile Coherence | Sift Risk Level | Riskified Score |
|:-----------------:|:---------------:|:---------------:|
| No coherence (random data) | HIGH | 85/100 |
| Partial coherence (50%) | MEDIUM | 55/100 |
| Full coherence (>80%) | LOW | 30/100 |

**Source:** `core/trust_scorer.py` lines 220–436

---

## 5. BIN Database Validation

The `BINDatabase` class (`core/bin_database.py`) validates card numbers and enriches them with issuer data. It's used by `WalletProvisioner` to detect the card network and issuer before injection.

### Static BIN Data (60+ Entries)

```python
STATIC_BIN_DATA = {
    "411111": {"network": "Visa", "type": "Credit", "bank": "Chase", "country": "US"},
    "453201": {"network": "Visa", "type": "Credit", "bank": "Chase", "country": "US"},
    "550000": {"network": "Mastercard", "type": "Credit", "bank": "Citibank", "country": "US"},
    "341111": {"network": "Amex", "type": "Credit", "bank": "American Express", "country": "US"},
    # ... 60+ entries covering US, UK, EU issuers
}
```

### Lookup Methods

| Method | Returns |
|--------|---------|
| `lookup(card_number)` | BIN record (network, bank, country, type) |
| `full_lookup(card_number)` | Complete card info (BIN + Luhn + network + prepaid/commercial) |
| `is_valid_luhn(card_number)` | True/False Luhn validation |
| `detect_network(card_number)` | Network name (Visa, Mastercard, etc.) |
| `is_prepaid(card_number)` | True/False prepaid detection |
| `is_commercial(card_number)` | True/False commercial card detection |
| `get_issuer_bank(card_number)` | Bank name string |
| `get_country(card_number)` | Country code |

### Luhn Algorithm Implementation

```python
@staticmethod
def is_valid_luhn(card_number: str) -> bool:
    """Validate card number using Luhn algorithm."""
    digits = [int(d) for d in card_number]
    digits.reverse()
    checksum = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0
```

### External Data Loading

The BIN database supports loading external BIN data from JSON files:

```python
bin_db = BINDatabase()
bin_db.load_external_data("/path/to/bins.json")
```

External data format:
```json
{
    "541156": {"network": "Mastercard", "type": "Debit", "bank": "Wells Fargo", "country": "US"},
    ...
}
```

**Source:** `core/bin_database.py` lines 1–315

---

## 6. Cerberus Card Validator

The Cerberus validator (`server/routers/cerberus.py`) provides API-level card validation combining BIN lookup, Luhn check, expiry validation, and risk assessment.

### Validation Pipeline

```
Card input → Parse format → Luhn check → BIN lookup → Expiry check → CVV format → Risk assess
```

### Input Formats

```
4111111111111111|12|2028|123           # Pipe-delimited
4111111111111111 12 2028 123           # Space-delimited
{"number": "4111111111111111", ...}    # JSON object
4111111111111111|12|2028|123|John Doe  # With cardholder
```

### Risk Assessment

Cerberus enriches the validation with risk intelligence:

```json
{
    "risk": {
        "3ds_version": "2.0",
        "challenge_rate": "low",
        "velocity_risk": "unknown",
        "recommended_device": "pixel_9_pro"
    }
}
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/cerberus/validate` | Single card validation + BIN enrichment |
| `POST` | `/api/cerberus/batch` | Multi-card batch validation |
| `POST` | `/api/cerberus/bin` | BIN lookup only (no card number needed) |

**Source:** `server/routers/cerberus.py`, `docs/08-intelligence-tools.md` §3–4

---

## 7. Success Rate Analysis

### WalletVerifier 13-Check Pass Rates

| Check | Pass Rate | Failure Cause |
|-------|:---------:|--------------|
| `tapandpay_db_exists` | 100% | |
| `tapandpay_token_count` | 100% | |
| `token_provisioning_status` | 100% | |
| `nfc_prefs_enabled` | 100% | |
| `coin_xml_payment_method` | 99% | |
| `coin_auth_disabled` | 99% | |
| `chrome_webdata_exists` | 99% | |
| `gms_wallet_synced` | 95% | GMS UID resolution |
| `gms_payment_profile_synced` | 95% | GMS UID resolution |
| `keybox_loaded` | 100% if file present | 0% if absent |
| `gsf_fingerprint_aligned` | 95% | GMS not installed |
| `tapandpay_ownership` | 98% | UID mismatch on fresh GMS |
| `system_nfc_enabled` | 100% | |

### Trust Score Achievement Distribution

| Target Grade | Achievability (with keybox) |
|:------------:|:---------------------------:|
| A+ (≥90) | ~87% |
| A (≥80) | ~95% |
| B (≥65) | ~99% |
| C (≥50) | ~100% |

### Transaction Activation Rates

| Scenario | Rate |
|----------|:----:|
| NFC tap (Play Integrity Device) | ~88% |
| NFC tap (Play Integrity Strong) | ~72% |
| Play Store in-app (zero-auth) | ~95% |
| Chrome autofill visible | ~85% |
| Chrome one-click checkout | ~40% |

**Source:** `docs/11-real-world-success-rates.md` §2–3

---

## 8. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/wallet_verifier.py` lines 1–340 | Full file | 13-check wallet verification |
| `core/wallet_verifier.py` lines 10–40 | Dataclasses | WalletVerificationReport, WalletCheck |
| `core/wallet_verifier.py` lines 88–142 | `verify()` | Main verification method |
| `core/trust_scorer.py` lines 37–210 | `compute_trust_score()` | 14-check trust scoring |
| `core/trust_scorer.py` lines 125–145 | Check #6 | Google Pay wallet check |
| `core/trust_scorer.py` lines 197–203 | Check #13 | Chrome autofill check |
| `core/trust_scorer.py` lines 220–436 | `compute_lifepath_score()` | Life-Path Coherence Score |
| `core/trust_scorer.py` lines 322–334 | Coherence #4 | Purchases ↔ Cookies |
| `core/bin_database.py` lines 1–315 | Full file | BIN database + Luhn validation |
| `server/routers/cerberus.py` | Full file | Cerberus card validator API |
| `server/routers/stealth.py` | `wallet-verify` endpoint | API for wallet verification |
| `docs/05-wallet-injection.md` §11 | Verification docs | Existing verification documentation |
| `docs/08-intelligence-tools.md` §3–4 | Cerberus + BIN | Intelligence tools docs |
| `docs/11-real-world-success-rates.md` §2–3 | Success rates | Empirical rate data |

---

*See [09-codebase-cross-reference.md](09-codebase-cross-reference.md) for the complete file/function/endpoint map.*
