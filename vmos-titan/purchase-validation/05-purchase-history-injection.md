# 05 — Purchase History Injection

How Genesis injects realistic commerce purchase history into the device, including Chrome browsing history, commerce cookies, email receipts, order notifications, and correlated wallet transactions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Purchase History Bridge](#2-purchase-history-bridge)
3. [Chrome History Entries](#3-chrome-history-entries)
4. [Chrome Commerce Cookies](#4-chrome-commerce-cookies)
5. [Order Notifications](#5-order-notifications)
6. [Email Receipt Injection](#6-email-receipt-injection)
7. [Wallet Transaction History](#7-wallet-transaction-history)
8. [Bank SMS Notifications](#8-bank-sms-notifications)
9. [Transaction-Profile Correlation (V12)](#9-transaction-profile-correlation-v12)
10. [Merchant Database](#10-merchant-database)
11. [How It Fits in the Pipeline](#11-how-it-fits-in-the-pipeline)
12. [Codebase Cross-References](#12-codebase-cross-references)

---

## 1. Overview

A real device with an active payment card will have traces of purchases across multiple data stores:

| Data Store | What It Contains |
|-----------|-----------------|
| Chrome History | Product pages, order confirmations, cart pages |
| Chrome Cookies | Commerce session cookies (amazon, walmart, etc.) |
| Notifications | "Order confirmed", "Your delivery is on the way" |
| Gmail/Email | Receipt emails from merchants |
| tapandpay.db `transaction_history` | NFC/contactless transaction records |
| SMS inbox | Bank transaction alerts ("$42.50 at Starbucks") |

Genesis injects all of these to create a coherent purchase footprint. The purchase history is cross-validated by the Life-Path Coherence Score (trust scorer check #4: Purchases ↔ Cookies) and contributes to behavioral analytics evasion.

---

## 2. Purchase History Bridge

The `PurchaseHistoryBridge` module (`core/purchase_history_bridge.py`) is the primary generator for commerce purchase artifacts. It produces:

```python
def generate_android_purchase_history(
    persona_name: str,
    persona_email: str,
    country: str = "US",
    age_days: int = 90,
    card_last4: str = "4242",
    card_network: str = "visa",
    purchase_categories: List[str] = None,
    num_purchases: int = 0,        # auto: age_days // 15
) -> Dict[str, Any]:
    """Returns:
      - purchases: Raw purchase records
      - chrome_history: URLs for Chrome History DB
      - chrome_cookies: Commerce cookies for Chrome Cookies DB
      - notifications: Order notification entries
      - email_receipts: Gmail receipt entries
      - purchase_summary: Stats for trust scoring
    """
```

### Purchase Generation Logic

- **Number of purchases:** `max(3, age_days // 15)` — roughly 1 purchase every 2 weeks
- **Merchant selection:** Based on `purchase_categories` or random from merchant pool
- **Timestamps:** Distributed over the profile age period with randomized hours
- **Amounts:** Realistic per-merchant ranges (e.g., Starbucks $3–8, Amazon $10–250)
- **Order IDs:** Merchant-specific format (e.g., `114-XXXXXXX-XXXX` for Amazon)
- **Status:** Delivered (if >7 days old), Shipped (if >1 day), Confirmed (recent)

**Source:** `core/purchase_history_bridge.py` lines 116–296

---

## 3. Chrome History Entries

For each purchase, three Chrome History entries are generated:

### 1. Product Page Visit (before purchase)

```json
{
    "url": "https://www.amazon.com/product/a1b2c3d4e5f6",
    "title": "Anker USB-C Hub - Amazon.com",
    "visit_time": 1710300000,
    "visit_count": 3
}
```

### 2. Cart Page

```json
{
    "url": "https://www.amazon.com/cart",
    "title": "Shopping Cart - Amazon.com",
    "visit_time": 1710300300,
    "visit_count": 1
}
```

### 3. Order Confirmation Page

```json
{
    "url": "https://www.amazon.com/order/114-7654321-1234",
    "title": "Order 114-7654321-1234 - Amazon.com",
    "visit_time": 1710300600,
    "visit_count": 2
}
```

These entries are injected into Chrome's `History` SQLite database by the profile injector.

**Source:** `core/purchase_history_bridge.py` lines 186–209

---

## 4. Chrome Commerce Cookies

For each unique merchant domain, commerce session cookies are generated:

```json
{
    "host": ".amazon.com",
    "name": "session-id",
    "value": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    "path": "/",
    "creation_utc": 13350000000000000,
    "expires_utc": 13380000000000000,
    "last_access_utc": 13355000000000000,
    "is_secure": 1,
    "is_httponly": 1,
    "samesite": 0
}
```

### Merchant-Specific Cookie Names

| Merchant | Cookies |
|----------|---------|
| Amazon | `session-id`, `ubid-main`, `session-token`, `csm-hit` |
| Walmart | `auth`, `cart-item-count`, `CRT` |
| Best Buy | `UID`, `SID`, `CTX` |
| Target | `visitorId`, `TealeafAkaSid` |
| eBay | `ebay`, `dp1`, `nonsession` |
| Nike | `NIKE_COMMERCE_COUNTRY`, `anonymousId` |

Cookies use Chrome's internal timestamp format: `(unix_epoch × 1,000,000) + 11644473600000000` (Windows FILETIME offset).

**Source:** `core/purchase_history_bridge.py` lines 211–234

---

## 5. Order Notifications

For each purchase, notification entries are generated:

```json
{
    "package": "com.android.chrome",
    "title": "Order Confirmation - Amazon.com",
    "text": "Order #114-7654321-1234 for $35.99 confirmed",
    "timestamp": 1710300600000,
    "category": "email"
}
```

For delivered orders, an additional delivery notification is generated:

```json
{
    "package": "com.android.chrome",
    "title": "Delivery Update - Amazon.com",
    "text": "Your order #114-7654321-1234 has been delivered",
    "timestamp": 1710800000000,
    "category": "email"
}
```

**Source:** `core/purchase_history_bridge.py` lines 236–253

---

## 6. Email Receipt Injection

Email receipts are generated for Gmail injection:

```json
{
    "from": "noreply@amazon.com",
    "to": "persona@gmail.com",
    "subject": "Your Amazon.com order #114-7654321-1234 is confirmed",
    "merchant": "Amazon.com",
    "amount": "$35.99",
    "timestamp": 1710300600,
    "read": true
}
```

These feed into the profile's email data and are cross-validated by the Life-Path Coherence Score (purchases ↔ cookies coherence check).

**Source:** `core/purchase_history_bridge.py` lines 255–274

---

## 7. Wallet Transaction History

Separate from the commerce purchase history, Genesis also injects NFC/contactless transaction records directly into `tapandpay.db`'s `transaction_history` table:

```sql
INSERT INTO transaction_history (
    token_id, merchant_name, merchant_category_code,
    amount_micros, currency_code, transaction_type,
    transaction_status, timestamp_ms
) VALUES (
    1, 'Starbucks', 5814,
    4250000, 'USD', 'CONTACTLESS',
    'COMPLETED', 1710300600000
);
```

### Merchant MCC Codes

| Merchant | MCC | Amount Range |
|----------|:---:|:------------:|
| Starbucks | 5814 | $3.00–$8.00 |
| Target | 5331 | $15.00–$80.00 |
| Walmart | 5411 | $20.00–$150.00 |
| Amazon | 5942 | $10.00–$250.00 |
| McDonald's | 5814 | $5.00–$15.00 |
| Costco | 5411 | $50.00–$300.00 |
| Chipotle | 5812 | $8.00–$18.00 |
| CVS Pharmacy | 5912 | $5.00–$50.00 |

5–15 transaction records are generated per card, backdated across the profile age period.

**Source:** `core/wallet_provisioner.py` lines 1510–1584

### Reading Back Transactions (API)

The `GET /api/genesis/wallet-transactions/{device_id}` endpoint reads back injected transactions from the device:

```python
card_raw = adb_shell(dev.adb_target,
    "sqlite3 .../tapandpay.db "
    "'SELECT dpan_last_four, fpan_last4, card_description, issuer_name, "
    "expiry_month, expiry_year, status, token_type, created_timestamp, "
    "last_used_timestamp FROM tokens ORDER BY id DESC LIMIT 1'")

tx_raw = adb_shell(dev.adb_target,
    "sqlite3 .../tapandpay.db "
    "'SELECT merchant_name, merchant_category_code, amount_micros, "
    "currency_code, transaction_type, transaction_status, timestamp_ms "
    "FROM transaction_history ORDER BY timestamp_ms DESC LIMIT 30'")
```

**Source:** `server/routers/genesis.py` lines 402–470

---

## 8. Bank SMS Notifications

Genesis injects realistic bank transaction SMS messages into the device's SMS inbox to simulate the bank alerts that real cardholders receive:

```python
def _inject_card_sms(self, last4, issuer, network_info, result, currency="USD"):
    """Inject bank notification SMS for card transactions."""
```

### SMS Templates

Multiple SMS formats are generated:

- `"CHASE ALERT: $42.50 charge at STARBUCKS on Visa ending 4242. Reply STOP to opt out."`
- `"Purchase of $42.50 at STARBUCKS approved on your Visa •4242. 03/14 2:30 PM"`
- `"Visa •4242: Auth $42.50 at STARBUCKS. Avail bal: $4,231.00"`

SMS messages are inserted via Android's content provider:

```bash
content insert --uri content://sms/inbox \
    --bind address:s:"72166" \
    --bind body:s:"CHASE ALERT: $42.50 charge at STARBUCKS..." \
    --bind date:l:1710300600000 \
    --bind read:i:1 \
    --bind type:i:1
```

Fallback for Cuttlefish (which may not have the SMS content provider): direct SQLite insert into `mmssms.db`.

**Source:** `core/wallet_provisioner.py` lines 1285–1399

---

## 9. Transaction-Profile Correlation (V12)

V12 introduced `correlate_transactions_with_profile()` which generates transaction history that cross-references with other profile data:

### Correlation Sources

| Source | Correlation Rule |
|--------|-----------------|
| **Maps navigation history** | If profile has Maps navigation to "Starbucks", generate a transaction at Starbucks ±30 min after arrival |
| **Email receipts** | If profile has email receipt from Amazon for $35.99, generate matching transaction |
| **Chrome browsing history** | Product page visits at merchant domains generate correlated transactions |

### Example Correlation

```
Maps: Navigate to "Target" at 2:00 PM → Transaction: $47.50 at Target at 2:35 PM
Email: Receipt from amazon.com $129.99 → Transaction: $129.99 at Amazon (same day)
```

This dramatically improves the Life-Path Coherence Score (trust scorer check #4).

**Source:** `core/wallet_provisioner.py` lines 1510–1584

---

## 10. Merchant Database

### Built-in Merchants (Fallback)

| Domain | Name | Sample Items |
|--------|------|-------------|
| amazon.com | Amazon.com | Anker USB-C Hub ($35.99), Kindle ($139.99), Backpack ($29.99) |
| walmart.com | Walmart | Paper Towels ($15.97), onn. 32" TV ($98.00) |
| bestbuy.com | Best Buy | Fire TV ($249.99), microSD ($24.99), JBL Speaker ($99.99) |
| target.com | Target | Throw Blanket ($25.00), Kids T-Shirt ($8.00) |
| ebay.com | eBay | Refurbished iPhone ($649.00), Arduino Kit ($34.99) |
| nike.com | Nike | Air Max 90 ($130.00), Dri-FIT Shirt ($35.00) |

### Category-to-Merchant Mapping

When `purchase_categories` are provided (from SmartForge AI persona):

| Category | Merchants |
|----------|----------|
| electronics | amazon.com, bestbuy.com, newegg.com |
| clothing | fashionnova.com, nike.com, zara.com, asos.com, shein.com |
| groceries | walmart.com, target.com, instacart.com |
| gaming | steampowered.com, g2a.com, eneba.com |
| food_delivery | doordash.com, ubereats.com |
| streaming_subscriptions | spotify.com, netflix.com |

### Order ID Formats

| Merchant | Format | Example |
|----------|--------|---------|
| Amazon | `114-XXXXXXX-XXXX` | `114-3847291-5823` |
| Walmart | `WM-XXXXXXX-XXXX` | `WM-9283741-2837` |
| Best Buy | `BBY01-XXXXXXX-XXXX` | `BBY01-7382910-4829` |
| Target | `TGT-XXXXXXX-XXXX` | `TGT-2839471-8392` |
| eBay | `EB-XXXXXXX-XXXX` | `EB-4829371-2938` |

**Source:** `core/purchase_history_bridge.py` lines 62–109, 298–361

---

## 11. How It Fits in the Pipeline

### Profile Injector Integration

The profile injector calls purchase history injection at Phase 5.5:

```python
# Phase 5.5: Purchase history (commerce cookies + browsing)
def _inject_purchase_history(self, profile):
    from purchase_history_bridge import generate_android_purchase_history
    ph = generate_android_purchase_history(
        persona_name=profile.get("persona_name"),
        persona_email=profile.get("persona_email"),
        country=profile.get("country", "US"),
        age_days=profile.get("age_days", 90),
        card_last4=card_last4,
        card_network=card_network,
        purchase_categories=purchase_cats,
    )
    # Inject Chrome history entries
    # Inject Chrome cookies
    # Inject notifications
```

**Source:** `core/profile_injector.py` lines 442–493

### Pipeline Phase 6 Integration

The provision pipeline also calls purchase history bridge directly:

```python
# Phase 6: Wallet Provision
from purchase_history_bridge import PurchaseHistoryBridge
phb = PurchaseHistoryBridge(adb_target=adb_target)
phb_result = phb.inject(
    profile_data=profile_data,
    card_last4=body.cc_number[-4:],
)
```

**Source:** `server/routers/provision.py` lines 741–751

---

## 12. Codebase Cross-References

| File | Section | Description |
|------|---------|-------------|
| `core/purchase_history_bridge.py` lines 116–296 | `generate_android_purchase_history()` | Main purchase history generator |
| `core/purchase_history_bridge.py` lines 62–109 | `_FALLBACK_MERCHANTS` | Built-in merchant database |
| `core/purchase_history_bridge.py` lines 298–361 | Merchant helpers | Merchant selection, order ID generation |
| `core/wallet_provisioner.py` lines 1285–1399 | `_inject_card_sms()` | Bank SMS notification injection |
| `core/wallet_provisioner.py` lines 1510–1584 | `correlate_transactions_with_profile()` | V12 transaction-profile correlation |
| `core/profile_injector.py` lines 442–493 | `_inject_purchase_history()` | Profile injector integration |
| `core/profile_injector.py` lines 494–540 | `_inject_payment_history()` | Payment transaction history |
| `server/routers/genesis.py` lines 402–470 | `genesis_wallet_transactions()` | API to read back transactions |
| `server/routers/provision.py` lines 741–751 | Pipeline Phase 6 | Pipeline purchase history bridge |
| `core/trust_scorer.py` lines 322–334 | Check #4 | Purchases ↔ Cookies coherence |

---

*See [06-zero-auth-otp-bypass.md](06-zero-auth-otp-bypass.md) for the complete OTP bypass mechanism.*
