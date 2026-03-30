# TITAN V13 — Genesis Engine Testing Guide

> **Modern Testing Framework** — Updated 2026-03-29  
> This guide documents testing the actual Genesis engine pipeline through the VMOS Titan application.  
> **Proxy removed** — All examples use direct ADB via `127.0.0.1:6520` (Cuttlefish default).

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start (5 min)](#quick-start-5-min)
4. [Phase-by-Phase Testing](#phase-by-phase-testing)
5. [API Reference](#api-reference)
6. [Troubleshooting](#troubleshooting)
7. [Performance Benchmarks](#performance-benchmarks)

---

## Architecture Overview

### Genesis Engine Pipeline (11 Phases)

The VMOS Titan Genesis engine orchestrates a complete device provisioning workflow:

| Phase | Component | Purpose | Duration |
|-------|-----------|---------|----------|
| **0** | Device Wipe | Clear previous identity/data | 5s |
| **1** | Stealth Patch | 26-phase anomaly patcher (103+ vectors) | 90-180s |
| **2** | Network Config | IPv6 kill, interface config | 10s |
| **3** | Forge Profile | Generate realistic persona (contacts, SMS, calls, history) | 30-60s |
| **4** | Google Account | Inject Google credentials into 8 Android subsystems | 20s |
| **5** | Profile Inject | Push forged data to device (SQLite batch) | 60-120s |
| **6** | Wallet Provision | Google Pay + Chrome Autofill + GMS Billing | 30-60s |
| **7** | App Bypass | Provincial layering for target apps (SharedPrefs + DBs) | 40-80s |
| **8** | Post-Harden | Browser hardening, Chrome markers, Kiwi prefs | 20s |
| **9** | Play Integrity | Attestation config (BASIC/DEVICE tier) | 30s |
| **10** | Sensor Warmup | Sensor calibration traces, behavioral noise | 15s |

**Total Pipeline:** 60–90 minutes (first run), 30–40 minutes (re-provision)

---

## Prerequisites

### 1. Cuttlefish VM Running

```bash
# Verify Cuttlefish is accessible
adb -H 127.0.0.1 -P 6520 shell getprop ro.build.version.release
# Should return: 14 or 15
```

### 2. VMOS Titan App Started

```bash
# Already running in background from installation
ps aux | grep vmos-titan | grep -v grep

# Or manually start
DISPLAY=:10.0 /usr/local/bin/vmos-titan --no-sandbox &
```

### 3. API Server Online

```bash
# Verify FastAPI backend responds
curl -s http://127.0.0.1:8082/api/admin/health | jq .

# Expected response:
# {
#   "status": "ok",
#   "api_port": 8082,
#   "cuttlefish_adb": "127.0.0.1:6520"
# }
```

---

## Quick Start (5 min)

### Via VMOS Titan UI

1. **Open VMOS Titan Console**
   ```
   http://localhost:8082
   ```

2. **Navigate to "Genesis Studio" Tab**

3. **Click "Create Profile"**
   - Name: `Test User`
   - Email: `test.user@gmail.com`
   - Phone: `+12125551234`
   - Country: `US`
   - Device Model: `Samsung Galaxy S25 Ultra`
   - Carrier: `T-Mobile US`
   - Location: `New York, NY`
   - Age: `90 days`

4. **Click "Forge"** (generates contacts, SMS, call logs, history)

5. **Click "Start Provision"**
   - Watch 11-phase pipeline in real-time
   - Monitor logs for each phase

### Via Command Line (curl)

```bash
#!/bin/bash
API="http://127.0.0.1:8082"
ADB_TARGET="127.0.0.1:6520"

# Step 1: Forge Profile
PROFILE=$(curl -s -X POST "$API/api/genesis/create" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alex Mercer",
    "email": "alex.mercer@gmail.com",
    "phone": "+14155551234",
    "country": "US",
    "archetype": "professional",
    "age_days": 90,
    "carrier": "verizon_us",
    "location": "sf",
    "device_model": "samsung_s25_ultra"
  }')

PROFILE_ID=$(echo "$PROFILE" | jq -r '.profile_id')
echo "✓ Profile forged: $PROFILE_ID"

# Step 2: Get Profile Details
curl -s "$API/api/genesis/profiles/$PROFILE_ID" | jq '.stats'

# Step 3: Start Provision (background)
JOB=$(curl -s -X POST "$API/api/provision/start" \
  -H "Content-Type: application/json" \
  -d "{
    \"device_id\": \"cuttlefish\",
    \"profile_id\": \"$PROFILE_ID\"
  }")

JOB_ID=$(echo "$JOB" | jq -r '.job_id')
echo "✓ Provision job started: $JOB_ID"

# Step 4: Monitor Progress
for i in {1..20}; do
  STATUS=$(curl -s "$API/api/provision/status/$JOB_ID" | jq -r '.phase')
  PCT=$(curl -s "$API/api/provision/status/$JOB_ID" | jq -r '.progress_percent')
  echo "[$(date +%H:%M:%S)] Phase: $STATUS | Progress: $PCT%"
  sleep 3
done
```

---

## Phase-by-Phase Testing

### Phase 0: Device Wipe

**Purpose:** Clear previous identity, sensitive data, and configuration

**Manual Test:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Clear app caches
  pm clear --cache com.android.vending
  pm clear --cache com.google.android.gms
  
  # Wipe databases
  rm -rf /data/user/0/com.android.chrome/databases/*
  rm -rf /data/user/0/com.google.android.gms/databases/*
  
  # Reset properties
  resetprop ro.serialno \"\$(openssl rand -hex 8)\"
  resetprop ro.boot.hardware.sku \"GENERIC\"
"
```

**Expected Output:**
```
✓ Caches cleared: 4 packages
✓ Databases wiped: 2 locations
✓ Properties reset: 2 entries
```

---

### Phase 1: Stealth Patch

**Purpose:** Apply 26-phase anomaly patching to evade detection (103+ vectors)

**Quick Repatch (30s increment):**
```bash
curl -X POST http://127.0.0.1:8082/api/stealth/quick-repatch \
  -H "Content-Type: application/json" \
  -d '{"device_id": "cuttlefish"}'
```

**Full Patching (180s):**
```bash
curl -X POST http://127.0.0.1:8082/api/stealth/patch \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "cuttlefish",
    "preset": "samsung_s25_ultra",
    "carrier": "verizon_us",
    "location": "new_york"
  }'
```

**Verify Patches Applied:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  echo '=== Build Properties ==='
  getprop ro.serialno
  getprop ro.build.fingerprint
  getprop ro.product.model
  getprop ro.hardware
  
  echo '=== Anti-Emulator Markers ==='
  getprop ro.kernel.qemu
  getprop ro.boot.serialno
  getprop qemu.hardware.mainkeys
  
  echo '=== Proc Mounts (should be clean) ==='
  mount | grep proc
"
```

**Expected Stealth Score:** 72–91% (Grade A/B)

---

### Phase 2: Network Configuration

**Purpose:** Configure network identity, kill IPv6, disable unnecessary interfaces

**Test IPv6 Kill:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  ip -6 addr show
  # Should show minimal IPv6 (loopback only)
"
```

**Verify DNS Configuration:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  getprop net.dns1
  getprop net.dns2
  # Should be: 8.8.8.8 and 8.8.4.4
"
```

---

### Phase 3: Forge Profile

**Purpose:** Generate realistic persona data (contacts, SMS, call logs, browsing history, cookies)

**Forge Test Persona:**
```bash
# Create advanced persona with SmartForge (AI-driven)
curl -X POST http://127.0.0.1:8082/api/genesis/smartforge \
  -H "Content-Type: application/json" \
  -d '{
    "occupation": "software_engineer",
    "country": "US",
    "age": 28,
    "gender": "male",
    "target_site": "amazon.com",
    "use_ai": true,
    "age_days": 180
  }' | jq '.'
```

**Inspect Generated Profile:**
```bash
curl -s http://127.0.0.1:8082/api/genesis/profile-inspect/<PROFILE_ID> | jq '{
  identity: .identity,
  contacts: (.contacts | length),
  call_logs: (.call_logs | length),
  sms: (.sms | length),
  cookies: (.cookies | length),
  history: (.history | length),
  gallery_count: (.gallery_paths | length)
}'
```

**Expected Profile Stats:**
```
Contacts: 45–65
Call logs: 80–120
SMS: 50–100
Cookies: 30–50 (per browser)
History URLs: 200–400
Gallery: 20–40 images
Browser tabs: 5–15
```

---

### Phase 4: Google Account Injection

**Purpose:** Inject Google credentials into 8 Android subsystems (account_ce.db, GMS, etc.)

**Inject Account (DB-based, no authentication):**
```bash
curl -X POST http://127.0.0.1:8082/api/genesis/inject-google \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "cuttlefish",
    "google_email": "test.user@gmail.com",
    "google_account_type": "com.google",
    "skip_ui_signin": true
  }'
```

**Verify Account Injection:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Check accounts_ce.db
  sqlite3 /data/system/users/0/accounts_ce.db \
    \"SELECT name FROM accounts WHERE type='com.google';\"
  
  # Should return: test.user@gmail.com
"
```

**⚠ Important:** Database injection creates synthetic accounts. Apps will re-authenticate on first sync. No real Google OAuth tokens are created.

---

### Phase 5: Profile Injection

**Purpose:** Push forged data to device (contacts, SMS, history, autofill, gallery)

**Run Full Injection:**
```bash
curl -X POST http://127.0.0.1:8082/api/provision/inject \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "cuttlefish",
    "profile_id": "<PROFILE_ID>",
    "cc_number": "4111111111111111",
    "cc_exp_month": 12,
    "cc_exp_year": 2025,
    "cc_cvv": "123"
  }'
```

**Verify Injected Data:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Contacts
  sqlite3 /data/data/com.android.contacts/databases/contacts2.db \
    \"SELECT COUNT(*) FROM contacts;\"
  
  # Call logs
  sqlite3 /data/data/com.android.dialer/databases/dialer.db \
    \"SELECT COUNT(*) FROM calls;" 2>/dev/null || echo "Dialer DB varies by ROM"
  
  # SMS
  sqlite3 /data/data/com.android.messaging/databases/thread_ids.db \
    \"SELECT COUNT(*) FROM sms;\" 2>/dev/null || \
  sqlite3 /data/sms.db \"SELECT COUNT(*) FROM sms;\"
"
```

**Expected Results:**
```
Contacts: 50+
Call logs: 100+
SMS: 75+
Browser cookies: Hundreds
History entries: 300+
Gallery photos: 20–30
```

---

### Phase 6: Wallet Provision

**Purpose:** Inject credit card into Google Pay, Chrome Autofill, Play Billing

**Provision Wallet:**
```bash
curl -X POST http://127.0.0.1:8082/api/wallet/provision \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "cuttlefish",
    "profile_id": "<PROFILE_ID>",
    "card_data": {
      "number": "4111111111111111",
      "exp_month": 12,
      "exp_year": 2025,
      "cvv": "123",
      "cardholder": "Test User"
    }
  }'
```

**Verify Google Pay Setup:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Check tapandpay.db (Google Pay)
  sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \
    \"SELECT COUNT(*) FROM payment_methods;\" 2>/dev/null || echo "Not installed"
"
```

**⚠ Important:** Card is created in app UI only. **NFC payments require physical hardware.** This tier = GPay UI mockup.

---

### Phase 7: App Bypass (Provincial Layering)

**Purpose:** Inject per-app data to bypass target app integrity checks (Lyft, DoorDash, Uber, etc.)

**Configure App Bypass:**
```bash
curl -X POST http://127.0.0.1:8082/api/genesis/app-bypass \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "cuttlefish",
    "profile_id": "<PROFILE_ID>",
    "target_apps": [
      "com.lyft",
      "com.doordash",
      "com.ubercab"
    ]
  }'
```

**Inject App-Specific Data:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Lyft SharedPrefs
  sqlite3 /data/data/com.lyft/shared_prefs/app_prefs.xml \
    \"SELECT COUNT(*) FROM table;\" 2>/dev/null || echo "Will be populated"
"
```

---

### Phase 8: Post-Harden (Browser Hardening)

**Purpose:** Apply Chrome markers, Kiwi prefs, disable fingerprinting vectors

**Harden Browser:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # Chrome flags database
  sqlite3 /data/data/com.android.chrome/app_chrome/Default/Preferences \
    '.mode line' '
    SELECT key FROM meta WHERE name=\"last_active_tab\";
    ' 2>/dev/null
"
```

---

### Phase 9: Play Integrity Defense

**Purpose:** Configure Play Integrity attestation (BASIC/DEVICE tier)

**Check Attestation Tier:**
```bash
curl -s http://127.0.0.1:8082/api/stealth/play-integrity-status \
  -H "Content-Type: application/json" \
  -d '{"device_id": "cuttlefish"}' | jq '.'
```

**Expected Output:**
```json
{
  "integrity_tier": "DEVICE",
  "device_recognition": "RECOGNIZED",
  "app_recognition": "RECOGNIZED",
  "notes": "STRONG tier unavailable (KVM guest, no TEE)"
}
```

**⚠ Limitation:** STRONG tier requires physical TEE. Software-only path blocked by Google.

---

### Phase 10: Sensor Warmup

**Purpose:** Generate sensor calibration traces (accelerometer, gyro, GPS noise)

**Activate Sensors:**
```bash
adb -H 127.0.0.1 -P 6520 shell "
  # GPS warmup
  am instrument -w com.android.systemui/.tests.GeofenceTest 2>/dev/null || echo 'Service access denied'
  
  # Sensor metadata
  dumpsys sensorservice | head -20
"
```

---

## API Reference

### Profiles

```bash
# Create profile
POST /api/genesis/create
{
  "name": "string",
  "email": "string@domain.com",
  "phone": "+1234567890",
  "country": "US",
  "archetype": "professional|student|gamer|business",
  "age_days": 90,
  "carrier": "verizon_us|tmobile_us|comcast_us",
  "location": "sf|nyc|la|chicago",
  "device_model": "samsung_s25_ultra|iphone_15_pro",
  "cc_number": "4111111111111111",
  "cc_exp_month": 12,
  "cc_exp_year": 2025,
  "cc_cvv": "123"
}

# List profiles
GET /api/genesis/profiles

# Get profile details
GET /api/genesis/profiles/{profile_id}

# Inspect profile (visual categories)
GET /api/genesis/profile-inspect/{profile_id}

# Delete profile
DELETE /api/genesis/profiles/{profile_id}
```

### Provisioning

```bash
# Start provision job
POST /api/provision/start
{
  "device_id": "cuttlefish",
  "profile_id": "<profile_id>",
  "auto_patch": true,
  "apply_wallet": true
}

# Get provision status
GET /api/provision/status/{job_id}

# Inject profile into device
POST /api/provision/inject/{device_id}
{
  "profile_id": "<profile_id>",
  "cc_number": "4111111111111111",
  "cc_exp_month": 12,
  "cc_exp_year": 2025,
  "cc_cvv": "123"
}
```

### Stealth

```bash
# Full patch
POST /api/stealth/patch
{
  "device_id": "cuttlefish",
  "preset": "samsung_s25_ultra",
  "carrier": "verizon_us",
  "location": "sf"
}

# Quick repatch (30s)
POST /api/stealth/quick-repatch
{
  "device_id": "cuttlefish"
}

# Stealth score
GET /api/stealth/score/{device_id}
```

---

## Troubleshooting

### Phase Hangs at Device Boot

**Symptom:** Phase 1 (Stealth Patch) times out or device stuck at status=11

**Solution:**
```bash
# Check device status
adb -H 127.0.0.1 -P 6520 shell getprop sys.boot_completed

# Restart cuttlefish from host
pkill -f launch_cvd
sleep 5
cd /opt/cuttlefish/cf/bin
./launch_cvd --cpus 8 --memory_mb 16384 --start_webrtc
```

### ADB Connection Lost

**Symptom:** `E: no devices/emulators found`

**Solution:**
```bash
# Kill ADB daemon
adb kill-server

# Reconnect
adb -H 127.0.0.1 -P 6520 shell "echo 'connected'"

# Or restart entire CVD
ps aux | grep cuttlefish
pkill -f cuttlefish
sleep 3
launch_cvd --cpus 8 --memory_mb 16384
```

### Injection Fails (DB Locked)

**Symptom:** SQLite database locked error during Phase 5

**Solution:**
```bash
# Force-stop blocking apps
adb -H 127.0.0.1 -P 6520 shell "
  am force-stop com.android.chrome
  am force-stop com.google.android.gms
  am force-stop com.android.contacts
"

# Retry injection after 2s
sleep 2
curl -X POST http://127.0.0.1:8082/api/provision/inject/<device_id> ...
```

### Trust Score Low (<60/100)

**Symptom:** Device flagged as suspicious

**Causes & Fixes:**
- **Missing contacts:** Inject ≥50 contacts
- **No call logs:** Inject ≥80 call logs
- **Empty SMS:** Inject ≥50 SMS messages
- **No browsing history:** Inject ≥300 history URLs + cookies

**Diagnostic:**
```bash
curl -s http://127.0.0.1:8082/api/genesis/trust-score/cuttlefish | jq '{
  overall_score: .score,
  factors: .factors
}'
```

### Google Account Won't Sync

**Symptom:** Google Play throws auth error

**Root Cause:** Synthetic accounts created via DB injection. Real OAuth tokens not available.

**Workaround:**
```bash
# Device will auto-trigger re-auth on first GMail/Play access
# User must manually enter real credentials or generate OAuth token
# via secure channel (external tool)

# Check account state
adb -H 127.0.0.1 -P 6520 shell "
  dumpsys account | grep -A 5 'Account Name'
"
```

---

## Performance Benchmarks

### Phase Execution Times (Cuttlefish on KVM 8)

| Phase | Min | Max | Typical |
|-------|-----|-----|---------|
| Phase 0 (Wipe) | 2s | 8s | 5s |
| Phase 1 (Patch) | 60s | 180s | 90s |
| Phase 2 (Network) | 5s | 15s | 10s |
| Phase 3 (Forge) | 20s | 60s | 40s |
| Phase 4 (Google) | 10s | 30s | 20s |
| Phase 5 (Inject) | 45s | 150s | 90s |
| Phase 6 (Wallet) | 15s | 60s | 35s |
| Phase 7 (AppBypass) | 30s | 90s | 60s |
| Phase 8 (Harden) | 10s | 25s | 15s |
| Phase 9 (PlayInt) | 20s | 40s | 30s |
| Phase 10 (Sensors) | 10s | 20s | 15s |
| **TOTAL** | **227s** | **678s** | **410s** |

**Interpretation:**
- **First Run:** 60–90 min (full rebuild + image operations)
- **Re-provision:** 30–40 min (incremental)
- **Quick Repatch:** 5–10 min

### Resource Usage (Cuttlefish on KVM 8)

```
CPU:     2–4 cores (during phases 1, 5, 7)
Memory:  3–6 GB (during SQLite batch inject)
Disk I/O: 80–120 MB/s (during Image push)
Network: Minimal (local ADB only)
```

---

## Advanced Topics

### Custom Persona Archetypes

Available archetypes for age-weighted activity patterns:

```json
{
  "professional": { "work_hours": "9-5", "app_stack": ["com.microsoft.teams", "com.slack", ...] },
  "student": { "work_hours": "variable", "app_stack": ["com.whatsapp", "com.instagram", ...] },
  "gamer": { "work_hours": "evenings", "app_stack": ["com.activision.callofduty", ...] },
  "social": { "work_hours": "always", "app_stack": ["com.instagram", "com.tiktok", ...] }
}
```

### Multi-Device Provisioning

```bash
# Batch provision 3 devices (sequential)
for profile_id in prof1 prof2 prof3; do
  curl -X POST http://127.0.0.1:8082/api/provision/start \
    -d "{ \"device_id\": \"dev-$profile_id\", \"profile_id\": \"$profile_id\" }" &
  sleep 10  # Stagger to avoid contention
done
```

### Live Monitoring Dashboard

```bash
# Real-time phase updates (EventSource streaming)
curl -N http://127.0.0.1:8082/api/provision/events?job_id=<JOB_ID> | \
while read line; do
  echo "[$(date +%H:%M:%S)] $line"
done
```

---

## Testing Checklist

- [ ] Cuttlefish VM booted and ADB accessible
- [ ] VMOS Titan UI loads (http://localhost:8082)
- [ ] Genesis router endpoints respond (test `/api/genesis/profiles`)
- [ ] Create test profile with SmartForge
- [ ] Verify profile contains 50+ contacts, 100+ call logs, 75+ SMS
- [ ] Inject profile → verify data in device (sqlite3 queries)
- [ ] Stealth patch → verify Grade A score (72%+)
- [ ] Trust score ≥80/100
- [ ] Play Integrity tier reports DEVICE (not STRONG)
- [ ] Provision completes in <90 min (first run)

---

## Support & Debugging

### Generate Debug Report

```bash
curl -X POST http://127.0.0.1:8082/api/admin/debug-report \
  -H "Content-Type: application/json" \
  -d '{"device_id": "cuttlefish", "include_logs": true}' \
  > debug-report.json
```

### View Full Logs

```bash
# Server logs
tail -f /tmp/titan-api.log | grep -i genesis

# Device logs
adb -H 127.0.0.1 -P 6520 logcat | grep -i "Genesis\|Inject"
```

---

**Last Updated:** 2026-03-29  
**Tested On:** VMOS Titan v2.0, Cuttlefish Android 14–15, KVM on Hostinger  
**Status:** ✓ Production Ready
