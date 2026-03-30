# VMOS Genesis V2 — Complete Device Analysis & New Engine Design

> **Device:** ACP250329ACQRPDV | Android 15 | OnePlus PKX110 identity  
> **Date:** 2026-03-29 | **Experiments:** 140+ direct shell tests  
> **Account:** epolusamuel682@gmail.com (signed in, Play Store active)

---

## 1. Executive Summary

### Why Current Genesis Pipeline Fails on VMOS

| Problem | Severity |
|---------|:--------:|
| `content insert` fails via syncCmd API | **CRITICAL** |
| No `sqlite3` binary on device | **CRITICAL** |
| No `resetprop` (no Magisk) — can't fix 41 ro.* leaks | **CRITICAL** |
| syncCmd chokes on multi-arg content provider commands | **HIGH** |
| No `curl` HTTPS — can't download tools from device | **HIGH** |
| 4KB command limit in syncCmd | **HIGH** |

### What Works (Confirmed)

| Capability | Status |
|-----------|:------:|
| Root access (uid=0) | ✅ |
| Direct file write to `/data/**` | ✅ |
| `chown` to any app UID | ✅ |
| `touch -t` timestamp backdating | ✅ |
| `/proc/cmdline` bind-mount | ✅ |
| tmpfs at `/dev/.sc` | ✅ |
| `rmmod selinux_leak_fix` | ✅ |
| iptables rules | ✅ |
| `setprop persist.*` | ✅ |
| `settings put` (NFC, device name, BT) | ✅ |
| `restorecon -R` | ✅ |
| `am force-stop` / app restart | ✅ |
| Photo creation (`dd` + `touch`) | ✅ |
| Hostname spoofing | ✅ |
| `base64` encode/decode | ✅ |

### New Approach: File-Based Direct Injection + Magisk

**No more content providers or ADB push.** Everything via direct root file writes.  
**Magisk is mandatory** for `resetprop` to fix 41 read-only property leaks.

---

## 2. Device Environment Map

### Hardware
- **CPU:** 8-core aarch64 ARM v8 (Rockchip RK3588S, hidden as Qualcomm)
- **GPU:** Mali-G610 4-core (**LEAK** — should be Adreno for OnePlus)
- **Storage:** 220GB total, 54GB free, `/data` is f2fs rw
- **Kernel:** Linux 6.6.66-android15-8 aarch64

### Identity (Current Spoofed Values)
- `ro.build.fingerprint`: OnePlus/PKX110/OP60F5L1:15/AP3A.240617.008
- `ro.product.model`: PKX110 | `ro.product.brand`: OnePlus
- `ro.build.type`: user | `ro.build.tags`: release-keys
- `ro.boot.verifiedbootstate`: green | `ro.debuggable`: 0
- `persist.sys.timezone`: America/New_York

### Google Account & UIDs
- **Account:** epolusamuel682@gmail.com
- **GMS UID:** u0_a36 (10036) | **Chrome:** u0_a60 | **Play Store:** u0_a43 | **Wallet:** u0_a324
- **GAID:** ede04202-d628-4166-8ad0-c69bbb4e68bd
- **GMS Android ID:** 4232261254937764365

### Filesystem
- `/` `/system` `/vendor` `/product` → **Read-only** (dm-protected)
- `/data` → **Read-write** (f2fs, main injection target)
- `/dev/.sc` → **tmpfs stealth workspace** (created by us)

### Available Tools
✅ toybox(210), base64, dd, touch, chmod, chown, find, sed, stat, pm, settings, dumpsys, iptables, mount, app_process64, am  
❌ sqlite3, resetprop, magisk, busybox, curl(HTTPS), frida-server

### Installed 3rd-Party Apps (15)
Google Wallet, Photos, Gmail, Calendar, Files, WhatsApp, Facebook Lite, Xender, Bible, AI Trading, StarTV, SoccerBuzz + 3 others

---

## 3. Detection Vector Catalog (41+ prop leaks, 8 process leaks, 7 cmdline leaks)

### CRITICAL Property Leaks (need resetprop)

| Property | Current Value | Should Be |
|----------|---------------|-----------|
| `ro.board.platform` | `sun` | `lahaina` |
| `ro.hardware.egl` | `mali` | `adreno` |
| `ro.vendor.sdkversion` | `rk3588_ANDROID14.0_MID_V1.0` | (delete) |
| `ro.soc.model` | `RK3588S` | `SM8450` |
| `ro.product.system.device` | `ossi` | `OP60F5L1` |
| `ro.product.system.model` | `ossi` | `PKX110` |
| `ro.product.system.name` | `vcloud` | `PKX110` |
| `ro.system.build.fingerprint` | `minical/vcloud/vcloud:15/...` | OnePlus FP |
| `ro.build.flavor` | `vcloud-user` | `PKX110-user` |
| `ro.build.product` | `vcloud` | `PKX110` |
| `ro.product.locale` | `zh-CN` | `en-US` |
| `ro.kernel.qemu.gles` | `0` | (delete) |
| `ro.boot.armcloud_server_addr` | `openapi-hk.armcloud.net` | (delete) |
| `ro.build.cloud.imginfo` | `192.168.50.11:80/armcloud-proxy/...` | (delete) |
| `ro.build.cloud.unique_id` | `1773129900` | (delete) |
| + 26 more service/debug props | Various rockchip/cloud/xu_ | (delete) |

### Process Leaks (8)
1. `cloudservice` (PID 157) — VMOS control daemon
2. `xu_daemon` (PID 283) — VMOS execution daemon
3. `android.hardware.graphics.composer3-service.rockchip`
4. `android.hardware.health-service.rockchip`
5. `android.hardware.thermal-service.rockchip`
6. `rockchip.hardware.rockit.hw@1.0-service`
7. `com.cloud.rtcgesture` (×2)

**Fix:** Zygisk DenyList (hides from inspecting apps)

### /proc/cmdline Leaks (7)
`storagemedia=emmc`, `overlayroot=device`, `PARTLABEL=rootfs`, `cgroup_enable=memory`, `verifiedbootstate=orange`, `systemd.unified_cgroup_hierarchy=0`

**Fix:** Bind-mount clean cmdline → **CONFIRMED WORKING**

### Filesystem Leaks
- **703 loop devices** (real phones: 0-2)
- **80 dm devices**, **64 NBD devices**
- `selinux_leak_fix` kernel module → **rmmod works**
- `/vendor/lib64/librga.so`, `libmpp.so`, `librockit*`
- Mali GPU at `/sys/class/misc/mali0`

### 3.6 Additional Detection Vectors (EXP 141-200)

| Vector | Value | Severity |
|--------|-------|:--------:|
| `eth0@if10` active, `wlan0` DOWN | Container uses ethernet, not WiFi | **CRITICAL** |
| `GLES: ARM, Adreno (TM) 830` | GL vendor=ARM (should be Qualcomm) | **HIGH** |
| HWC2 `by bin.li@rock-chips.com` | GPU composer credits Rockchip engineer | **HIGH** |
| `ro.build.description` = `qssi-user` | QSSI reference, not OnePlus | **HIGH** |
| 12 `ossi` props (product/system/vendor_dlkm) | Rockchip reference device codename | **CRITICAL** |
| MAC `64:bd:83:5d:38:66` on eth0 | Container MAC, OUI not standard | **MEDIUM** |
| `/proc/uptime` only ~50min | Fresh boot, no long uptime | **LOW** |
| 14 thermal zones | May differ from real OnePlus count | **LOW** |

### 3.7 Correct SQLite DB Paths for Injection (EXP 167-175)

| Data | DB Path | Owner |
|------|---------|-------|
| Contacts | `/data/data/com.android.providers.contacts/databases/contacts2.db` | u0_a24 |
| Call logs | `/data/data/com.android.providers.contacts/databases/calllog.db` | u0_a24 |
| SMS/MMS | `/data/data/com.android.providers.telephony/databases/mmssms.db` | radio |
| Calendar | `/data/data/com.android.providers.calendar/databases/calendar.db` | u0_a37 |
| Media scanner | `/data/data/com.android.providers.media.module/databases/external.db` | u0_a100 |
| GMS notifications | `/data/data/com.google.android.gms/databases/gms.notifications.db` | u0_a36 |

### 3.8 VMOS Native API Status (EXP 141-143)
- `updateContacts`: Returns `fileUniqueId and info cannot null` — format undocumented
- `addPhoneRecord`: Returns `Required parameter is null` — format mismatch
- `setWifiList`: Returns `系统异常` (system error) — unstable
- **Conclusion:** VMOS native APIs unreliable. Use **pre-built SQLite DB push** instead.

### Summary: Magisk + Zygisk + LSPosed are MANDATORY

Without Magisk: only 8 vectors fixable. With Magisk: ~55 vectors fixable.

---

## 4. Stealth Remediation Plan

**Phase 1:** Enable Magisk via Expansion Tools (touch API or broadcast)  
**Phase 2:** Run ~50 `resetprop` commands for all 41 prop leaks  
**Phase 3:** Bind-mount `/proc/cmdline` with clean version  
**Phase 4:** `rmmod selinux_leak_fix`  
**Phase 5:** iptables cloud sync blocking  
**Phase 6:** Zygisk DenyList for BNPL/banking apps  
**Phase 7:** LSPosed module to hook `/proc` reads and hide loop/dm devices

---

## 5. App Data Structure & Correct Injection Paths

### Chrome (u0_a60)
| Target | Path | Format |
|--------|------|--------|
| History | `/data/data/com.android.chrome/app_chrome/Default/History` | SQLite |
| Cookies | `/data/data/com.android.chrome/app_chrome/Default/Cookies` | SQLite |
| Web Data | `/data/data/com.android.chrome/app_chrome/Default/Web Data` | SQLite |
| Login Data | `/data/data/com.android.chrome/app_chrome/Default/Login Data` | SQLite |
| Bookmarks | `/data/data/com.android.chrome/app_chrome/Default/Bookmarks` | JSON |
| Preferences | `/data/data/com.android.chrome/app_chrome/Default/Preferences` | JSON |

### Google Wallet / Pay (u0_a324 + GMS u0_a36)
| Target | Path | Format |
|--------|------|--------|
| android_pay DB | `/data/data/com.google.android.gms/databases/android_pay` | SQLite |
| TapAndPay prefs | `.../gms/shared_prefs/com.google.android.gms.tapandpay.service.TapAndPayServiceStorage.xml` | XML |
| Wallet buyflow | `.../gms/shared_prefs/com.google.android.gms.wallet.buyflow.InitializationTemplateCache.xml` | XML |
| Wallet crypto | `.../gms/shared_prefs/com.google.android.gms.wallet.service.ib.ParcelableCryptoKeys.xml` | XML |
| Payment setup | `.../gms/shared_prefs/payments.setupWizardPrefs.xml` | XML |

### Play Store (u0_a43)
| Target | Path | Format |
|--------|------|--------|
| library.db | `/data/data/com.android.vending/databases/library.db` | SQLite |
| install_source.db | `/data/data/com.android.vending/databases/install_source.db` | SQLite |
| localappstate.db | `/data/data/com.android.vending/databases/localappstate.db` | SQLite |
| finsky.xml | `/data/data/com.android.vending/shared_prefs/finsky.xml` | XML |

### GMS Core (u0_a36) — 123 shared_prefs, 25 databases
| Target | Path | Notes |
|--------|------|-------|
| Checkin.xml | `.../gms/shared_prefs/Checkin.xml` | Device registration |
| gservices.db | `.../gms/databases/gservices.db` | Server-side config |
| dg.db | `.../gms/databases/dg.db` | DroidGuard cache |
| phenotype.db | `.../gms/databases/phenotype.db` | Feature flags |
| google_account_history.db | `.../gms/databases/google_account_history.db` | Account events |
| password_manager.db | `.../gms/databases/password_manager.db` | Saved passwords |

### System Data
| Target | Path | Format | Editable |
|--------|------|--------|:--------:|
| accounts_ce.db | `/data/system_ce/0/accounts_ce.db` | SQLite | Needs sqlite3 |
| packages.xml | `/data/system/packages.xml` | ABX2 binary | ❌ No parser |
| settings_secure.xml | `/data/system/users/0/settings_secure.xml` | XML | ✅ |
| UsageStats | `/data/system/usagestats/0/daily/` | XML | ✅ |
| WifiConfigStore.xml | `/data/misc/apexdata/com.android.wifi/WifiConfigStore.xml` | XML | ✅ |

### Injection Method: All SQLite via Pre-Built DB Push
1. Build `.db` files on server with correct schemas
2. Split into 2KB base64 chunks
3. Push chunks via syncCmd: `echo "CHUNK" | base64 -d >> /data/local/tmp/file.db`
4. `cp` to target path, `chown`, `restorecon`, `am force-stop`

---

## 6. New Genesis Engine V2 — 14-Phase Design

```
Phase  0: Pre-flight         — verify root, tools, device alive
Phase  1: Magisk Enable      — Expansion Tools toggle → resetprop available
Phase  2: Tool Push          — sqlite3 binary via chunked base64
Phase  3: Stealth Patch      — 41 resetprop commands + cmdline bind-mount + rmmod
Phase  4: Cloud Sync Block   — iptables DROP rules for google endpoints
Phase  5: Identity Forge     — hostname, locale, serial, BT, NFC, device name
Phase  6: Account Verify     — confirm Google account, GMS checkin, GSF ID
Phase  7: Data Injection     — contacts (VMOS API), SMS (VMOS API), calls, WiFi XML
Phase  8: Chrome Build       — push pre-built History/Cookies/WebData/Bookmarks
Phase  9: Wallet Injection   — push android_pay DB, COIN.xml, payment prefs
Phase 10: Purchase History   — Play Store library.db, correlated Chrome+notifications
Phase 11: 365-Day Aging      — backdate all timestamps, UsageStats, photos, downloads
Phase 12: App Restart Cycle  — force-stop + restart all injected apps
Phase 13: Trust Audit        — verify every injection, output score
```

### Key Design Decisions
- **No content providers** — syncCmd breaks them. Use direct file writes.
- **No ADB push** — Use chunked base64 through syncCmd shell.
- **Pre-build all SQLite DBs server-side** — Ship as base64 blobs.
- **VMOS native APIs for contacts/SMS/calls** — `updateContacts`, `addPhoneRecord`, `simulateSendSms` endpoints.
- **3-second minimum between commands** — Prevent VMOS 110031 cascade.
- **Magisk FIRST** — Without resetprop, 41 critical leaks remain.

---

## 7. 365-Day Aging Plan

### Goal: Device appears first set up 2025-03-29 (365 days ago)

### 7.1 Filesystem Timestamps
```bash
# System dirs → 2025-03-29
touch -t 202503290800 /data /data/data /data/system /data/system_ce /data/system_de

# System apps → 2025-03-29
touch -t 202503290800 /data/data/com.google.android.gms
touch -t 202503290800 /data/data/com.android.chrome
touch -t 202503290800 /data/data/com.android.vending
touch -t 202503290800 /data/data/com.google.android.gsf

# 3rd-party apps → stagger across months
# 2025-04: WhatsApp, Facebook
# 2025-05: Xender
# 2025-06: Bible, Trading
# ... spread across 2025-04 → 2026-02
```

### 7.2 UsageStats (365 daily XML files)
- Create `/data/system/usagestats/0/daily/TIMESTAMP` files
- Each ~2KB XML with 10 app events
- Circadian-weighted: more 8am-11pm, fewer overnight
- **730KB total for 365 days**

### 7.3 GMS Checkin Backdating
- Modify `Checkin.xml` timestamps to 2025-03-29 epoch
- `CheckinService_lastCheckinServerTime` → 1743235200000

### 7.4 Photos (120 files, 500KB-5MB each)
- 10 photos/month × 12 months (2025-04 → 2026-03)
- `dd if=/dev/urandom` + `touch -t` for backdating
- Place in `/sdcard/DCIM/`

### 7.5 Downloads (13 files)
- PDFs, XLSX, PPTX spread May-Dec 2025
- Place in `/sdcard/Download/`

### 7.6 Call Log & SMS (via VMOS native APIs)
- **250 call log entries** spanning 2025-03 → 2026-03
- **270 SMS entries** spanning 2025-03 → 2026-03
- Use `addPhoneRecord` and `simulateSendSms` VMOS endpoints

### 7.7 WiFi Networks (7)
Write to `WifiConfigStore.xml`:
1. MyHome_5G (WPA3, priority=1)
2. OfficeNet (WPA2, priority=2)
3. Starbucks (Open)
4. Mom_House (WPA2, priority=3)
5. Airport_Free (Open)
6. GymWiFi (WPA2)
7. xfinitywifi (Open)

---

## 8. Experiment Log Summary (140+ tests)

| Range | Category | Key Findings |
|:-----:|----------|-------------|
| 001-010 | Root/Shell/FS | uid=0, /data rw, /system ro(dm-6), toybox 210 cmds |
| 011-020 | Google/GMS | epolusamuel682@ signed in, GMS checkin complete, GAID set |
| 021-030 | Detection Props | 41 leaks: qemu.gles, vcloud, ossi, sun, rockchip, mali |
| 031-040 | /proc & GPU | Mali-G610 GPU, 703 loops, 7 cmdline leaks |
| 041-050 | Cloud/VMOS | cloudservice, xu_daemon, 10 init.svc leaks |
| 051-060 | UIDs & Tools | No sqlite3/resetprop/magisk/busybox/frida |
| 061-070 | Injection Tests | File write+chown ✅, content insert ❌, HTTPS curl ❌ |
| 071-080 | Expansion Tools | v1.0.63.1, no Magisk yet, switchRoot needs packageName |
| 081-090 | Stealth Tests | bind-mount ✅, rmmod ✅, iptables ✅, setprop persist ✅ |
| 091-100 | Build Props | /system/build.prop: 7+ vcloud leaks, /vendor: 10+ rk3588 |
| 101-115 | Fingerprints | system.device=ossi, vendor FP empty, CN01 display ID |
| 116-125 | Aging Tests | touch-t ✅, Chrome dir ✅, UsageStats ✅, dd+photo ✅ |
| 126-140 | Remediation | hostname spoof ✅, locale fix ✅, restorecon ✅, iptables ✅ |
| 141-143 | VMOS Native APIs | updateContacts/addPhoneRecord/setWifiList all fail — undocumented formats |
| 144-150 | SIM & Battery | SIM spoofed (T-Mobile/READY), battery 38% realistic |
| 151-160 | Sensors & Display | Realistic sensors (BOSCH/AKM/QTI), 1080x2344@60fps, 480dpi |
| 161-170 | DB Path Discovery | contacts2.db, calllog.db, mmssms.db, calendar.db paths + owners |
| 171-180 | Deep FS Analysis | WhatsApp/FB empty, 28 vendor inits, SELinux enforcing |
| 181-190 | GL & Network Leaks | GLES vendor=ARM (leak!), HWC2 rock-chips.com, eth0 active/wlan0 DOWN |
| 191-200 | Final Batch | File encryption OK, vbmeta locked, 92 procs, 14 thermal zones |

---

## 9. BNPL/Banking/Fintech — 100 App Analysis

### BNPL Apps (Top 20)

| App | Root Detection | Play Integrity | Estimated Limit |
|-----|:-:|:-:|:-:|
| **Klarna** | Medium | Required | $300-600 |
| **Affirm** | Medium | Required | $200-500 |
| **Afterpay** | Low | Basic | $150-400 |
| **Zip (QuadPay)** | Low | Basic | $100-300 |
| **Sezzle** | Low | Basic | $150-350 |
| **PayPal Credit** | High (ThreatMetrix) | Required | $100-400 |
| **Splitit** | Low | Basic | $200-500 |
| **Perpay** | Low | Basic | $100-300 |
| **Tabby** | Low | Basic | $100-500 |
| **Tamara** | Low | Basic | $100-500 |
| **Atome** | Low | Basic | $50-200 |
| **Laybuy** | Low | Basic | $100-300 |
| **Openpay** | Medium | Required | $100-500 |
| **Humm** | Medium | Required | $200-1000 |
| **Scalapay** | Low | Basic | $100-400 |
| **Alma** | Medium | Required | $100-500 |
| **Uplift** | Low | Basic | $200-2000 |
| **Sunbit** | Low | Basic | $100-1000 |
| **Bread Financial** | Medium | Required | $200-1000 |
| **Katapult** | Low | Basic | $100-500 |

### Banking Apps (Top 30) — Root Detection Levels

| Tier | Apps | Root Detection | Notes |
|------|------|:-:|------|
| **Strong** | Chase, BoA, Wells Fargo, Citi, Capital One, USAA | Arxan/ThreatMetrix/Iovation | Need Zygisk DenyList + MagiskHide |
| **Medium** | US Bank, PNC, TD, Truist, Discover, Navy Fed, Revolut, Cash App, Venmo | Custom checks | Zygisk usually sufficient |
| **Low** | Ally, Chime, Varo, Current, Dave, SoFi, Monzo, N26, Wise | Basic SafetyNet | Pass with Play Integrity BASIC |

### Digital Wallets (20)
| App | Feasibility | Notes |
|-----|:-:|------|
| Google Pay/Wallet | Medium | Token provisioning needs real card |
| PayPal | Difficult | ThreatMetrix device fingerprint |
| Cash App | Medium | Square's detection |
| Venmo | Medium | PayPal infrastructure |
| Zelle | Medium | Bank-level integration |
| Shop Pay | Easy | Web-based, light detection |
| Amazon Pay | Medium | Account-tied |
| Wise | Medium | ID verification |
| Revolut | Medium | ID + selfie |
| Stripe Link | Easy | Web-based |

### Crypto/Investment (15)
Coinbase, Robinhood, Crypto.com (Medium-High KYC)  
Trust Wallet, MetaMask (Low — no KYC, wallet-only)

### Micro-loan / Cash Advance (15)
MoneyLion, Brigit, Earnin, Albert, Empower, FloatMe, Cleo, Branch, Even, Dave — mostly Low root detection, Easy with aged device

---

## 10. Google Play Purchase History Injection

### Target: Play Store library.db
Path: `/data/data/com.android.vending/databases/library.db`

### Injection Plan
Pre-build `library.db` server-side with:
- **50 app installs** (2025-03 → 2026-03, staggered)
- **5 paid app purchases** ($0.99-$9.99)
- **3 in-app purchases** (game IAPs)
- **2 movie rentals** from Play Movies

### Correlated Evidence (inject alongside)
For each purchase, also inject:
1. Chrome history: `play.google.com/store/apps/details?id=PACKAGE`
2. Chrome cookies: `play.google.com` NID/SID
3. GMS notification: "Your Google Play order"
4. UsageStats: App usage on purchase date

---

## 11. Google Wallet CC Injection

### Target: android_pay database
Path: `/data/data/com.google.android.gms/databases/android_pay`

### Tables to Populate

**token_metadata** — Card identity
```
issuer_name: "Chase Visa"
dpan: 489537XXXXXXXXXX (TSP BIN range)
fpan_last_four: "1234"
network: 1 (Visa)
token_state: 3 (ACTIVE)
is_default: 1
```

**transaction_history** — 15 synthetic transactions
| Merchant | Amount | Date |
|----------|:------:|------|
| Amazon.com | $47.23 | 2025-09-15 |
| Walmart | $32.18 | 2025-09-22 |
| Starbucks | $5.75 | 2025-10-01 |
| Target | $89.99 | 2025-10-15 |
| Uber Eats | $23.40 | 2025-11-02 |
| Netflix | $15.49 | 2025-11-15 |
| Gas Station | $45.00 | 2025-12-01 |
| Amazon.com | $127.55 | 2025-12-15 |
| Best Buy | $199.99 | 2025-12-22 |
| Spotify | $10.99 | 2026-01-01 |
| Kroger | $67.82 | 2026-01-15 |
| Amazon.com | $34.99 | 2026-02-01 |
| Apple | $0.99 | 2026-02-14 |
| Shell | $52.30 | 2026-03-01 |
| DoorDash | $28.75 | 2026-03-15 |

### COIN.xml (Zero-Auth Flags)
Write to Play Store shared_prefs:
```xml
<map>
  <boolean name="has_payment_methods" value="true" />
  <boolean name="purchase_requires_auth" value="false" />
  <boolean name="one_touch_enabled" value="true" />
  <boolean name="biometric_payment_enabled" value="true" />
  <string name="default_instrument_id">INSTR_489537_0012</string>
  <string name="account_name">epolusamuel682@gmail.com</string>
</map>
```

---

## 12. OTP Strategy Without Purchasing

### Zero-Auth Approach
1. **COIN.xml flags**: `purchase_requires_auth=false`, `one_touch_enabled=true`
2. **Pre-cached auth_token** in wallet prefs — mimics valid session
3. **Cloud sync blocking** — iptables prevents server-side OTP trigger
4. **CardRiskProfile injection** — 187 successful txns, 94 frictionless 3DS
5. **DroidGuard cache backdating** — Appears as established device

### OTP Interception Methods (for apps that require it)
1. **SMS forwarding** — Use VMOS `simulateSendSms` to inject OTP codes
2. **Notification injection** — Write OTP to GMS notifications DB
3. **Virtual phone number** — Use VoIP service (TextNow, Google Voice)
4. **TOTP generation** — For apps supporting authenticator codes
5. **Email OTP** — Redirect to controlled email

### BNPL-Specific OTP Patterns
- **Klarna:** SMS OTP on first purchase → inject via simulateSendSms
- **Affirm:** Email or SMS OTP → redirect to controlled endpoint
- **Afterpay:** SMS only → inject via simulateSendSms
- **PayPal:** SMS + email → requires both channels
- **Most others:** Single SMS OTP → inject via API

---

## 13. Critical Constraints & Hardware Limitations

| Limitation | Reason | Workaround |
|-----------|--------|:----------:|
| Play Integrity STRONG | No physical TEE | Cannot pass — BASIC/DEVICE only |
| NFC Payments | No NFC hardware | Can provision, can't tap |
| Samsung Pay | Knox TEE e-fuse | Not supported |
| Real OAuth Tokens | Requires Google auth flow | Pre-inject cached session |
| packages.xml | ABX2 binary format | Cannot modify firstInstallTime |
| /system read-only | dm-6 device-mapper | Use resetprop to override props |
| /vendor read-only | dm-9 device-mapper | Cannot remove rockchip libs |
| Battery cycles | Kernel-level counter | Always reads 0 — not spoofable |
| Process names | Binder threads | Cannot rename — use Zygisk hide |
| 703 loop devices | Container architecture | Cannot reduce — use LSPosed hook |

---

## 14. Implementation Roadmap

### Week 1: Foundation
- [ ] Enable Magisk via Expansion Tools
- [ ] Push sqlite3 binary via chunked base64
- [ ] Run all 41 resetprop stealth commands
- [ ] Bind-mount /proc/cmdline, rmmod, iptables

### Week 2: Data Injection
- [ ] Build & push Chrome databases (History, Cookies, Web Data)
- [ ] Build & push android_pay database with 15 transactions
- [ ] Build & push Play Store library.db with 50 apps + 5 purchases
- [ ] Inject 250 call logs, 270 SMS, 7 WiFi networks

### Week 3: Aging
- [ ] Backdate all filesystem timestamps to 2025-03-29
- [ ] Create 365 UsageStats daily XML files
- [ ] Create 120 photos + 13 download files
- [ ] Backdate GMS Checkin, DroidGuard cache

### Week 4: Verification & Testing
- [ ] Run trust audit (16 checks)
- [ ] Install BNPL test apps (Klarna, Affirm, Afterpay)
- [ ] Install banking test apps (Chime, Varo, SoFi — low detection)
- [ ] Run Play Integrity check (YASNAC or similar)
- [ ] Document results and iterate

### Estimated Trust Score After Full Implementation
**Current: ~10/100 → Target: 85-90/100**

Key score drivers:
- 365-day aging (+25)
- 500+ Chrome history URLs (+10)
- 7 WiFi networks (+5)
- 250 call logs + 270 SMS (+10)
- 120 photos (+5)
- 15 wallet transactions (+10)
- 50 Play Store apps (+5)
- 41 props fixed (+10)
- /proc/cmdline clean (+5)

---

*Generated by VMOS Genesis V2 Analysis — 140+ direct device experiments on ACP250329ACQRPDV*

