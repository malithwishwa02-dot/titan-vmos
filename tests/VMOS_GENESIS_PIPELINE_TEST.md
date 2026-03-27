# VMOS Cloud Genesis Pipeline — Complete Test & Verification

**Date**: March 27, 2026  
**Target Device**: `ACP2509244LGV1MV`  
**Target Trust Score**: 95%+  
**Goal**: Google Pay visible with card data, complete persona injection

---

## Test Subject Profile

| Field | Value |
|-------|-------|
| **Name** | Jovany OWENS |
| **Email** | adiniorjuniorjd28@gmail.com |
| **Password** | YCCvsukin7S |
| **Phone** | (707) 836-1915 |
| **DOB** | 12/11/1959 |
| **SSN** | 219-19-0937 |
| **Address** | 1866 W 11th St, Los Angeles, CA 90006 |
| **Location** | Los Angeles, CA |

## Credit Card

| Field | Value |
|-------|-------|
| **Number** | 4638 5123 2034 0405 |
| **Type** | Visa |
| **Exp** | 08/2029 |
| **CVV** | 051 |
| **Cardholder** | Jovany Owens |

## VMOS Cloud Credentials

| Field | Value |
|-------|-------|
| **Access Key** | BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi |
| **Secret Key** | Q2SgcSwEfuwoedY0cijp6Mce |
| **Pad Code** | ACP2509244LGV1MV |

---

## Pipeline Architecture (11 Phases)

```
╔════════════════════════════════════════════════════════════════════════╗
║                    VMOS GENESIS PIPELINE                               ║
╠════════════════════════════════════════════════════════════════════════╣
║  Phase 0:  WIPE            │ Clear previous persona data              ║
║  Phase 1:  STEALTH PATCH   │ Device fingerprint + root hiding         ║
║  Phase 2:  NETWORK/PROXY   │ Configure proxy (optional)               ║
║  Phase 3:  FORGE PROFILE   │ Generate identity with temporal depth    ║
║  Phase 4:  GOOGLE ACCOUNT  │ Inject into accounts_ce/de.db + GMS     ║
║  Phase 5:  INJECT          │ Contacts, calls, SMS, Chrome, WiFi       ║
║  Phase 6:  WALLET/GPAY     │ Card injection into Chrome + tapandpay   ║
║  Phase 7:  PROVINCIAL      │ App-specific SharedPreferences           ║
║  Phase 8:  POST-HARDEN     │ Kiwi prefs, media scan                   ║
║  Phase 9:  ATTESTATION     │ Verify keybox, verified boot, build type ║
║  Phase 10: TRUST AUDIT     │ Score calculation (target: 95%+)         ║
╚════════════════════════════════════════════════════════════════════════╝
```

---

## Trust Score Breakdown (Max 100)

| Component | Points | Requirement |
|-----------|--------|-------------|
| Google Account | 15 | accounts_ce.db has 1+ account |
| Chrome Cookies | 10 | 10+ cookies with age spread |
| Chrome History | 10 | 20+ URLs with temporal distribution |
| Wallet/GPay | 10 | tapandpay.db token_metadata has entry |
| Contacts | 8 | 5+ contacts in contacts2.db |
| Call Logs | 8 | 10+ call log entries |
| SMS | 8 | 5+ SMS threads |
| Gallery Photos | 8 | 3+ EXIF-tagged photos in DCIM |
| Autofill Data | 7 | Chrome Web Data has autofill profile |
| WiFi Networks | 5 | 3+ saved networks |
| App Install Dates | 5 | Backdated to age_days |
| GMS Prefs | 5 | device_registration.xml populated |
| Device Props | 3 | Brand/model/fingerprint coherent |
| Behavioral Depth | 3 | UsageStats populated |

**Grade Scale**: A+ ≥95, A ≥85, B ≥70, C ≥50, F <50

---

## Pre-Flight Device Analysis

### Current State (Before Pipeline)
```
Instance: ACP2509244LGV1MV
Status: Running (10)
Third-party Apps: PayPal, Chime, Bybit, TransferWise, Google Docs
Accounts DB: EMPTY ❌
Contacts: 1 ❌ (needs 5+)
Call Logs: 1 ❌ (needs 10+)
SMS: 1 ❌ (needs 5+)
Chrome Data: NO_CHROME ❌
Wallet DB: NO_WALLET ❌
UsageStats: EMPTY ❌
```

### Target State (After Pipeline)
```
Accounts DB: 1 Google account ✓
Contacts: 30+ ✓
Call Logs: 80+ ✓
SMS: 30+ ✓
Chrome Cookies: 30+ ✓
Chrome History: 50+ ✓
Wallet tapandpay.db: 1 tokenized card ✓
UsageStats: 40+ entries over 120 days ✓
Trust Score: 95%+ ✓
```

---

## Pipeline Execution Steps

### Step 1: Configure Environment
```bash
cd /opt/titan-v13-device
source venv/bin/activate
export PYTHONPATH=core:server
export VMOS_CLOUD_AK="BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
export VMOS_CLOUD_SK="Q2SgcSwEfuwoedY0cijp6Mce"
```

### Step 2: Run Genesis Pipeline
```bash
python tests/run_vmos_genesis_pipeline.py
```

### Step 3: Verify Results
```bash
python tests/verify_vmos_trust_score.py
```

---

## Verification Checks

### V1: Google Account Injection
```sql
-- On device via ADB
sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;"
-- Expected: adiniorjuniorjd28@gmail.com|com.google
```

### V2: Contacts Count
```bash
content query --uri content://com.android.contacts/raw_contacts --projection _id | wc -l
# Expected: 30+
```

### V3: Call Logs
```bash
content query --uri content://call_log/calls --projection _id | wc -l
# Expected: 80+
```

### V4: SMS Messages
```bash
content query --uri content://sms --projection _id | wc -l
# Expected: 30+
```

### V5: Chrome Cookies
```sql
sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies "SELECT COUNT(*) FROM cookies;"
-- Expected: 30+
```

### V6: Chrome History
```sql
sqlite3 /data/data/com.android.chrome/app_chrome/Default/History "SELECT COUNT(*) FROM urls;"
-- Expected: 50+
```

### V7: Google Pay / Wallet
```sql
sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db "SELECT * FROM token_metadata;"
-- Expected: 1 row with last_four=0405, network=1 (Visa)
```

### V8: UsageStats
```bash
ls /data/system/usagestats/0/daily/ | wc -l
# Expected: 1+
```

### V9: Attestation Checks
```bash
getprop ro.boot.verifiedbootstate   # Expected: green
getprop ro.build.type                # Expected: user
getprop ro.debuggable                # Expected: 0
```

### V10: Trust Score Calculation
```
Account (15) + Cookies (10) + History (10) + Wallet (10) + 
Contacts (8) + Calls (8) + SMS (8) + UsageStats (5) + 
WiFi (5) + Props (3) + Battery (3) + AppAge (5) = 95+
```

---

## Gmail Login Procedure (Manual/Agent)

### Option A: Manual Login via VMOS Web Console
1. Open VMOS Cloud web dashboard
2. Navigate to instance ACP2509244LGV1MV
3. Open Play Store app
4. Click "Sign In" → Use existing account
5. Enter: `adiniorjuniorjd28@gmail.com`
6. Enter password: `YCCvsukin7S`
7. Complete 2FA if prompted (phone: 707-836-1915)
8. Accept Terms of Service
9. Verify login success

### Option B: Automated via Agent + Touch Simulation
```python
# See: core/device_agent.py for See→Think→Act loop
# Uses VMOS API touch simulation with humanized input
```

---

## Google Pay Setup Procedure

### Pre-requisites
- Google Account logged in ✓
- Play Integrity BASIC/DEVICE passing ✓
- Chrome with autofill data ✓
- tapandpay.db populated ✓

### Manual Steps
1. Open Google Wallet app
2. Tap "Add payment method"
3. Select "Credit or debit card"
4. Card should auto-fill from Chrome autofill
5. Verify card details match:
   - Number: 4638 5123 2034 0405
   - Exp: 08/2029
   - CVV: 051
6. Complete Yellow Path verification (SMS OTP to 707-836-1915)
7. Card appears in GPay with last 4: **0405**

### Expected Wallet State
```
tapandpay.db token_metadata:
  id: 1
  dpan: 5XXXXXXXXXXXXXX (tokenized)
  last_four: 0405
  network: 1 (Visa)
  token_state: 3 (active)
  is_default: 1
```

---

## Troubleshooting

### Issue: Account Injection Failed
```bash
# Check DB ownership
ls -la /data/system_ce/0/accounts_ce.db
# Should be: system:system (1000:1000)

# Fix ownership
chown system:system /data/system_ce/0/accounts_ce.db
chmod 600 /data/system_ce/0/accounts_ce.db
```

### Issue: Chrome Cookies Not Persisting
```bash
# Check Chrome is stopped
am force-stop com.android.chrome

# Re-inject then restart
# See Phase 5e in genesis engine
```

### Issue: Wallet DB Missing
```bash
# Create directory if missing
mkdir -p /data/data/com.google.android.gms/databases
chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) /data/data/com.google.android.gms/databases

# Re-run Phase 6
```

### Issue: Trust Score Below 95%
```bash
# Run audit to see what's missing
python tests/verify_vmos_trust_score.py --detailed
```

---

## API Endpoints for Pipeline Control

### Start Pipeline
```
POST /api/genesis/vmos/start
{
  "pad_code": "ACP2509244LGV1MV",
  "profile": {
    "name": "Jovany OWENS",
    "email": "adiniorjuniorjd28@gmail.com",
    "phone": "+17078361915",
    "dob": "1959-12-11",
    "street": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90006",
    "country": "US",
    "age_days": 120,
    "device_model": "samsung_s24",
    "carrier": "tmobile_us",
    "location": "la"
  },
  "card": {
    "number": "4638512320340405",
    "exp": "08/2029",
    "cvv": "051",
    "holder": "Jovany Owens"
  },
  "proxy_url": "",
  "skip_wipe": false
}
```

### Check Status
```
GET /api/genesis/vmos/status/{job_id}
```

### Get Trust Score
```
GET /api/genesis/vmos/trust/{pad_code}
```

---

## Connected Components

### Core Modules Used
| Module | Purpose |
|--------|---------|
| `vmos_cloud_api.py` | HMAC-SHA256 authenticated API client |
| `vmos_genesis_engine.py` | 11-phase pipeline orchestrator |
| `android_profile_forge.py` | Identity generation with temporal depth |
| `device_presets.py` | Samsung/Pixel fingerprint presets |

### Orphan Scripts (attic/) — Status
| Script | Status | Action |
|--------|--------|--------|
| `_patch_and_inject.py` | Standalone | Integrated into genesis engine |
| `test_vmos_pipeline.py` | Standalone | Updated to use vmos_genesis_engine |
| `vmos_anomaly_scan.py` | Standalone | Connect to forensic_monitor |
| `vmos_auto_patch.py` | Standalone | Merged into anomaly_patcher |

---

## Next Steps

1. **Execute Pipeline**: Run `run_vmos_genesis_pipeline.py`
2. **Manual Gmail Login**: Use VMOS web console or agent
3. **Google Pay Setup**: Add card via Yellow Path
4. **Verification**: Run trust score verification
5. **Documentation**: Update results in this file

---

## Execution Log Template

```
Pipeline Execution: [DATE]
─────────────────────────────
Phase 0 (Wipe):       [ ] done  [ ] skipped  [ ] failed
Phase 1 (Stealth):    [ ] done  [ ] skipped  [ ] failed
Phase 2 (Network):    [ ] done  [ ] skipped  [ ] failed
Phase 3 (Forge):      [ ] done  [ ] skipped  [ ] failed
Phase 4 (Google):     [ ] done  [ ] skipped  [ ] failed
Phase 5 (Inject):     [ ] done  [ ] skipped  [ ] failed
Phase 6 (Wallet):     [ ] done  [ ] skipped  [ ] failed
Phase 7 (Provincial): [ ] done  [ ] skipped  [ ] failed
Phase 8 (PostHarden): [ ] done  [ ] skipped  [ ] failed
Phase 9 (Attestation):[ ] done  [ ] skipped  [ ] failed
Phase 10 (Trust):     [ ] done  [ ] skipped  [ ] failed

Final Trust Score: ___/100
Grade: ___
Gmail Login: [ ] Completed  [ ] Pending
Google Pay: [ ] Visible  [ ] Card Added  [ ] Pending
```

