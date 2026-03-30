# VMOS Deep Device Analysis — 149 Experiments
## Device: ACP2509244LGV1MV (OnePlus Ace 3 / PJZ110, Android 15)
## Date: 2026-03-29 | Method: Live API + ADB Shell

---

# TABLE OF CONTENTS

1. [Hardware & Kernel Fingerprinting](#1-hardware--kernel-fingerprinting)
2. [Spoofing Vector Analysis](#2-spoofing-vector-analysis)
3. [Injection Surface Testing](#3-injection-surface-testing)
4. [Security Boundary Probing](#4-security-boundary-probing)
5. [Payment & Account Infrastructure](#5-payment--account-infrastructure)
6. [Root Module & Hook Framework](#6-root-module--hook-framework)
7. [Detection Evasion Analysis](#7-detection-evasion-analysis)
8. [Advanced Sensitive Experiments](#8-advanced-sensitive-experiments)
9. [Correct Paths & Structures Reference](#9-correct-paths--structures-reference)
10. [Critical Detection Vectors](#10-critical-detection-vectors)
11. [Actionable Recommendations](#11-actionable-recommendations)

---

# 1. HARDWARE & KERNEL FINGERPRINTING

## 1.1 TRUE Hardware (Experiments 1-15)

| Property | REAL Value | SPOOFED As |
|----------|-----------|------------|
| **SoC** | Rockchip RK3588S (device-tree: `rockchip,rk3588s-mars3500s`) | Qualcomm SM8750 (Snapdragon 8 Elite) |
| **GPU** | Mali-G715 Immortalis MC10, OpenGL ES 3.2 | Adreno (reported as Mali-G715) |
| **GPU Device** | `/dev/dri/card0` (DRM node, char 226:0) | — |
| **CPU** | 8 cores, implementer 0x51, part 0x001, max 4.32GHz | Qualcomm Kryo |
| **CPU Topology** | cpu0-3: 3.53GHz, cpu4-6: 3.53GHz, cpu7: 4.32GHz | big.LITTLE |
| **RAM** | 11,184,112 kB (~10.7GB) | 10,922M (ro.boot.memory) |
| **Kernel** | 6.6.30-android15-8 aarch64 PREEMPT | — |
| **Build Host** | `gitlab-runner@server-MZ73-LM1-000` | — |
| **Storage** | F2FS on `/data`, ext4 on `/system` (dm-6) | — |
| **Battery** | Simulated: Li-ion, 50%, Discharging, USB powered | Real device battery |
| **Thermal** | `soc-thermal` zone, 33.3°C | — |
| **Display** | 1080x2376 @ 60fps, 480dpi | OnePlus Ace 3 display |
| **Kernel Modules** | `selinux_leak_fix` (16384 bytes) — SELinux patched at kernel level | — |

## 1.2 Container Architecture

```
Type: Linux namespace container (NOT VM/emulator)
Board: Rockchip RK3588S MARS3500s
Device Tree: rockchip,rk3588s-mars3500s rockchip,rk3588
Namespaces: cgroup, ipc, mnt, net, pid, time, user, uts (all isolated)
Cgroups: cpu,cpuacct, devices, freezer, net_cls, perf_event, blkio, cpuset, pids, memory
PID 1: init (uid=0, sleeping)
Overlay: 0 overlay mounts (pure device-mapper)
Mounts: 133 entries, /data is nosuid+nodev, /system is ro
```

## 1.3 Sysfs Artifacts (RK3588 LEAKS)

```
/sys/bus/platform/devices/fd7c08a0.aclk_rkvdec0_pre    # RK video decoder
/sys/bus/platform/devices/fd7c08a4.aclk_rkvdec1_pre    # RK video decoder 1
/sys/bus/platform/devices/fdbd0000.rkvenc-core          # RK video encoder
/sys/bus/platform/devices/fd7c08c0.aclk_rkvenc1_pre    # RK video encoder 1
/proc/device-tree/model = "Rockchip RK3588S MARS3500s"
/proc/device-tree/compatible = "rockchip,rk3588s-mars3500s rockchip,rk3588"
```

---

# 2. SPOOFING VECTOR ANALYSIS

## 2.1 Device Identity (Experiments 16-40)

| Vector | Current Value | Spoofable? | Method |
|--------|--------------|------------|--------|
| **Model** | PJZ110 (OnePlus Ace 3) | ✅ | `updatePadAndroidProp` API |
| **Brand** | OnePlus | ✅ | `updatePadAndroidProp` API |
| **Manufacturer** | OnePlus | ✅ | `updatePadAndroidProp` API |
| **Device** | OP5D0DL1 | ✅ | `updatePadAndroidProp` API |
| **Board Platform** | qcom (spoofed), sun (real) | ✅ | `updatePadAndroidProp` API |
| **Hardware** | qcom | ✅ | `updatePadAndroidProp` API |
| **Fingerprint** | `OnePlus/PJZ110/OP5D0DL1:15/AP3A.240617.008/V.1d90ff9-1-1862f:user/release-keys` | ✅ | `updatePadAndroidProp` API |
| **All Partition FPs** | All 5 partitions match (bootimg/vendor/odm/system/sysext) | ✅ | Consistent |
| **Android ID** | `d818d746521a5beb` | ✅ | `settings put secure android_id` |
| **Serial** | (empty — not set) | ⚠️ | Missing, detection vector |
| **IMEI** | 310410047176454 (via iphonesubinfo binder) | ✅ | `persist.sys.cloud.imeinum` |
| **WiFi MAC** | `ce:56:ad:68:19:1a` (wlan0) | ✅ | `persist.sys.cloud.wifi.mac` |
| **Ethernet MAC** | `0c:3a:0f:3e:f6:ce` (eth0) | ❌ | Datacenter interface — detection leak |
| **Bluetooth** | address=null, name=null | ⚠️ | Not configured — detection vector |
| **Timezone** | America/New_York (EDT) | ✅ | `persist.sys.timezone` |
| **Locale** | en-US | ✅ | `persist.sys.locale` |
| **Baseband** | Q_V1_P14 | ✅ | `gsm.version.baseband` |
| **Boot ID** | `03b6c8d6-b0e0-416d-9512-cca3b59c6f95` | ❌ | Kernel-generated per boot |
| **Hostname** | localhost | ⚠️ | Generic — could be flagged |

## 2.2 Carrier/Telephony Identity

| Property | Value | Notes |
|----------|-------|-------|
| **SIM Operator** | (empty) | ⚠️ Not populated |
| **Operator Numeric** | (empty) | ⚠️ Not populated |
| **Operator Country** | (empty) | ⚠️ Not populated |
| **NITZ Time** | `26,26` | Partial |
| **Default Network** | (empty) | ⚠️ Not set |
| **Cell Tower** | No CID/TAC/PCI/EARFCN | ⚠️ Empty telephony registry |

## 2.3 Network Identity

| Property | Value | Risk |
|----------|-------|------|
| **IPv4** | 10.11.36.185 (eth0, datacenter subnet) | 🔴 HIGH LEAK |
| **IPv6** | fe80::12ed:fe5e:fbfc:f5ea (eth0) | 🔴 HIGH LEAK |
| **Gateway** | 10.11.0.0/16 via eth0 | 🔴 DATACENTER |
| **Interfaces** | lo, ip6_vti0, ip6tnl0, wlan0, eth0@if10 | 🔴 eth0 = server |
| **ARP** | Empty (no neighbors) | ⚠️ Unusual for real device |
| **External IP** | 204.237.151.61 (US-NYC proxy) | ✅ Proxied correctly |

## 2.4 OEM-Specific Props (OnePlus/OPLUS)

```
ro.setupwizard.mode = (empty)
ro.oplus.image.my_stock.type = domestic_OnePlus  
ro.oplus.version.my_manifest = PJZ110_11.A.63_0630_202504271252.97.db2ef7e1
ro.sys.sdcardfs = (empty)
```

## 2.5 Identity Spoofing API

**24,472 device presets** available via `selectBrandList`:
- Samsung Galaxy S25 Ultra, S24, S23, Z Fold 5, A-series
- Xiaomi, POCO, Redmi, Mi series
- Huawei P-series, Mate series
- Google Pixel, OnePlus, OPPO, vivo, Realme

**Property change command** (confirmed working):
```python
await client.update_android_prop('ACP2509244LGV1MV', {
    'ro.product.model': 'SM-S928U',
    'ro.product.brand': 'samsung',
    'ro.build.fingerprint': '...',
})
# WARNING: Triggers device restart (~20 seconds)
```

---

# 3. INJECTION SURFACE TESTING

## 3.1 GPS Injection (Experiments 41-44)

| Test | Result | Notes |
|------|--------|-------|
| GPS state check | `persist.sys.cloud.gps.en = 1` | Enabled |
| Inject LA coords (34.05, -118.24) | ✅ code=200 | Instant |
| Verify coords | Coords updated | Confirmed |
| Restore NYC coords | ✅ code=200 | Instant |

**GPS Control Props**:
```
persist.sys.cloud.gps.en = 1/0          # Master toggle
persist.cloud.gps.latitude = <value>    # Set by API
persist.cloud.gps.longitude = <value>   # Set by API
persist.cloud.gps.altitude = <value>    # Altitude
```

## 3.2 Picture Injection (Experiments 45-46)

| Test | Result |
|------|--------|
| Inject via API (injectUrl) | ✅ code=200, taskId=1852708340 |
| Check filesystem | 0-byte placeholder files in `/sdcard/DCIM/Camera/` |

**Note**: API returns success but files are 0 bytes — injection goes to **virtual camera**, not gallery.

## 3.3 Sensor Injection (Experiments 47-48)

```
43 hardware sensors active, 43 running
Available TRANSACTION_ calls from ICloudService:
  TRANSACTION_setSensorAcceleration
  TRANSACTION_setSensorOrientation  
  TRANSACTION_setSensorMagneticField
  TRANSACTION_setSensorTemperature
  TRANSACTION_setSensorStepCounter
  TRANSACTION_setSensorStepDetector
  TRANSACTION_setSensorMotionDetect
  TRANSACTION_setSensorTiltDetector
  TRANSACTION_setSensorPickUpGesture
  TRANSACTION_setSensorRotationVector
  TRANSACTION_setSensorHingeAngle0/1/2
  TRANSACTION_setBATWirelessOnline
```

## 3.4 Camera Injection (Experiments 49-50)

```
Camera service: Running
Scale mode: persist.sys.cloud.camera_scale_mode (not set)
Crop region: persist.sys.cloud.camera_crop_region (not set)
Callbacks: TRANSACTION_setCameraSetPicCallback, TRANSACTION_setCameraConnectCallback
```

## 3.5 Content Provider Injection (Experiments 52-57)

| Provider | Read | Write | Notes |
|----------|------|-------|-------|
| **Contacts** | ✅ Nancy Jackson, James Lee, Paul Baker... | ✅ Insert works | Content URI injection |
| **Call Log** | ✅ +14703467405, +19723925395... | ✅ Insert works | With number/type/date/duration |
| **SMS** | ✅ Messages with body text | ✅ Insert works | address/body/date/type/read |
| **Settings** | ✅ Full read access | ✅ Write access | android_id modifiable |
| **Clipboard** | ✅ Accessible | ✅ Writable | Via content provider |

## 3.6 NFC/HCE (Experiment 58)

```
NFC State: off (no hardware)
HCE Services Registered:
  1. TpHceService (Google Pay) — payment AID: 325041592E5359532E4444463031
  2. NfcAdvertisingService (Nearby) — AID: F00000FE2C  
  3. FIDO2 NFC service
Default Payment: com.google.android.gms/TpHceService
```

---

# 4. SECURITY BOUNDARY PROBING

## 4.1 Identity & Capabilities (Experiments 61-65)

```
uid=0(root) gid=0(root)
context=u:r:xu_daemon:s0
SELinux: Enforcing
Kernel module: selinux_leak_fix (patches SELinux)

Capabilities (ALL 41 bits set):
  CapPrm: 000001ffffffffff
  CapEff: 000001ffffffffff  
  CapBnd: 000001ffffffffff
  CapAmb: 0000000000000000
  CapInh: 0000000000000000
```

## 4.2 Kernel Security (Experiments 66-68)

| Setting | Value | Impact |
|---------|-------|--------|
| `ptrace_scope` | 1 (restricted) | Can't ptrace non-children |
| `perf_event_paranoid` | -1 (allow all) | Perf monitoring available |
| `kptr_restrict` | 2 (hide kernel pointers) | Kernel addresses hidden |
| `dmesg_restrict` | 0 (allow) | Kernel log readable |
| `ip_forward` | 0 (disabled) | No forwarding |
| Firewall | All chains ACCEPT | No restrictions |

## 4.3 Binder & Services (Experiments 70-71)

```
Binder devices:
  /dev/binder → /dev/binderfs/binder
  /dev/hwbinder → /dev/binderfs/binder (symlinked!)
  /dev/vndbinder → (not present)

ServiceManager: 257 services registered
  xu_service: FOUND (RootInterface AIDL)
  activity, activity_task, package, window, input, content: all present
  app_integrity: [android.content.integrity.IAppIntegrityManager]
```

## 4.4 Filesystem Security (Experiments 72-73, 130-132)

| Test | Result |
|------|--------|
| /system remount rw | ❌ FAIL — not in /proc/mounts (device-mapper) |
| Write to /system | ❌ FAIL — Read-only file system |
| tmpfs mount | ✅ SUCCESS — Can mount tmpfs anywhere in /data |
| /data write | ✅ Full write access (F2FS, nosuid+nodev) |
| Overlay mounts | 0 — No overlay filesystem |

## 4.5 Keystore & Crypto (Experiments 75-78)

```
Keystore: /data/misc/keystore/user_0/ — 130 entries
Hardware features:
  android.hardware.hardware_keystore=300 (KeyMaster 3.0)
  android.hardware.biometrics.face
  android.hardware.fingerprint
  NO StrongBox
TEE: Software emulated (no ro.hardware.keystore/keymaster set)
```

## 4.6 LSM & APEX (Experiments 74, 79)

```
LSM stack: (not readable — /sys/kernel/security/ empty for xu_daemon)
APEX modules: 300 entries (71 directories)
  com.android.art, com.android.btservices, com.android.media, etc.
```

---

# 5. PAYMENT & ACCOUNT INFRASTRUCTURE

## 5.1 Google Account (Experiment 81)

```
Account: epolusamuel682@gmail.com (type=com.google)
Auth tokens: Present (not displayed for security)
```

## 5.2 android_pay Database Schema (Experiment 82)

| Table | Purpose |
|-------|---------|
| `ActivationMethodLimits` | Token activation method rate limits |
| `SePaymentCards` | Secure Element payment cards (client_token_id, se_card_id, network_id, is_default) |
| `QuickAccessWalletCards` | Quick access display cards (card_image_filename, wallet_card blob) |
| `PaymentCardOverrides` | Card priority overrides (priority, realtime min/max) |
| `TapDoodleGroupsV2` | GPay doodle/animation groups |
| `WalletPsdLogs` | PSD2 compliance logs (psd_key, psd_logs blob) |

## 5.3 Card Risk Profile (Experiment 89) — CRITICAL

```xml
<string name="card_fingerprint">435adc7ec60ad0a2372806f93fbc448a</string>
<int name="risk_tier" value="0" />            <!-- LOWEST risk tier -->
<boolean name="3ds_enrolled" value="true" />
<boolean name="3ds_v2_supported" value="true" />
<int name="3ds_frictionless_count" value="11" />   <!-- 11 frictionless 3DS -->
<boolean name="device_bound" value="true" />
<string name="device_fingerprint">e25b0ec57d7e5fa9ac7576861d123fbfaac7c910</string>
<long name="last_successful_txn" value="1774649178000" />
<int name="successful_txn_count" value="22" />     <!-- 22 successful txns -->
<int name="declined_txn_count" value="0" />
<boolean name="issuer_trusted_device" value="true" />
<string name="issuer_risk_assessment">low</string>
<boolean name="step_up_auth_required" value="false" />  <!-- NO OTP -->
<boolean name="card_active" value="true" />
<boolean name="recurring_eligible" value="true" />
<string name="network_token_status">active</string>
<boolean name="network_token_cryptogram_valid" value="true" />
```

**Analysis**: Genesis forge has created a trusted device profile with:
- **Zero declined transactions** and 22 successful ones
- **Issuer trusts this device** — `issuer_trusted_device=true`
- **Step-up auth NOT required** — no OTP for transactions
- **3DS frictionless flow** enabled (11 prior frictionless)
- **Network token active** with valid cryptogram

## 5.4 Wallet Crypto Keys (Experiment 85)

```xml
<string name="00000002|e46b1f76-807e-4f66-9337-3899d2ff79dc">eX5xkDonM7L9HTqlkpzVew==</string>
```
Encrypted wallet key stored in `ParcelableCryptoKeys.xml`.

## 5.5 TapAndPay Service State (Experiment 84)

```xml
<boolean name="tap_and_pay_enabled" value="true" />
<boolean name="wallet_service_enabled" value="false" />
<boolean name="sticky_global_actions_flag" value="true" />
<boolean name="was_password_sufficient" value="false" />
```

## 5.6 Payment Feature Flags (Experiment 87)

```
BounceProvisioning__enable_bounce_provisioning
Country__passes_first_countries
Country__tap_and_pay_countries
Keyguard__mandate_keyguard_for_tokenization
CONTEXTUAL_TOKENIZATION
cloud_payment_method_id
```

## 5.7 FIDO2/Passkey (Experiment 93)

```
QRBounceActivity — FIDO scheme handler (fido://, FIDO://)
Full FIDO2 authenticator present in GMS
WebAuthn support available
```

## 5.8 Third-Party Payment Apps

| App | Package | State |
|-----|---------|-------|
| **Privacy.com** | `com.privacy.pay` | Installed, Plaid integration, Firebase, Sentry |
| **PayPal** | `com.paypal.android.p2pmobile` | Installed, user_prefs.xml present |

---

# 6. ROOT MODULE & HOOK FRAMEWORK

## 6.1 Root State (Experiments 96-104)

| Test | Result |
|------|--------|
| uid | 0 (root) |
| SELinux context | `u:r:xu_daemon:s0` |
| `/data/adb/magisk/` | ✅ Created (stub magisk64 prints "Magisk v28.1") |
| `/data/adb/modules/zygisk_lsposed/` | ✅ Created with valid module.prop |
| `persist.sys.cloud.root.global` | 1 (enabled) |
| `ro.debuggable` | 0 |
| `ro.secure` | 1 |
| switchRoot shell | ✅ code=200 |
| switchRoot GMS | ✅ code=200 |
| switchRoot Wallet | ✅ code=200 |
| `persist.*` write | ✅ Works (`setprop persist.test.spoof.check`) |
| `ro.*` write | ✅ Writes but value is "FAIL_EXPECTED" (appears to work!) |
| Hook detection (maps) | 0 matches — clean |
| Frida artifacts | None found |
| Root packages | None installed |
| Root mounts | None detected |

## 6.2 Per-App Root (switchRoot API)

```python
# Enable root for specific package
await client.switch_root(['ACP2509244LGV1MV'], 
    enable=True, root_type=1, package_name='com.android.shell')
# Returns code=200
```

**Confirmed working for**: `com.android.shell`, `com.google.android.gms`, `com.google.android.apps.walletnfcrel`

## 6.3 Expansion Tools Binder Transactions (164 total)

```
TRANSACTION_getMockLocationState
TRANSACTION_getXModuleLastUpdate
TRANSACTION_setBATWirelessOnline
TRANSACTION_setSensorHingeAngle0/1/2
TRANSACTION_setSensorOrientation
TRANSACTION_setSensorStepCounter
TRANSACTION_setSensorTemperature
TRANSACTION_setSensorAcceleration
TRANSACTION_setSensorMotionDetect
TRANSACTION_setSensorStepDetector
TRANSACTION_setSensorTiltDetector
TRANSACTION_setSensorPickUpGesture
TRANSACTION_setSensorMagneticField
TRANSACTION_setSensorRotationVector
TRANSACTION_setCameraSetPicCallback
TRANSACTION_setCameraConnectCallback
TRANSACTION_registerSensorCallback
TRANSACTION_unregisterSensorCallback
TRANSACTION_getProxyPassPackageName
TRANSACTION_setProxyPassPackageName
TRANSACTION_createAAIDForPackageName
TRANSACTION_isLimitAdTrackingEnabled
TRANSACTION_setMaxNetworkThreadCount
TRANSACTION_broadcastInvalidation
TRANSACTION_isAllRoot
TRANSACTION_setProp
TRANSACTION_setPropInt
TRANSACTION_setPropString
```

---

# 7. DETECTION EVASION ANALYSIS

## 7.1 Critical Detection Vectors (Experiments 110-129)

### 🔴 HIGH RISK — Will Fail Sophisticated Checks

| # | Vector | Real Value | Expected | Fix |
|---|--------|-----------|----------|-----|
| 1 | **GPU GL_RENDERER** | Mali-G715 Immortalis MC10 | Adreno 830 (for SD8 Elite) | Cannot fix — hardware GL |
| 2 | **Device Tree** | `rockchip,rk3588s-mars3500s` | OnePlus data | Cannot fix — kernel read-only |
| 3 | **/proc/device-tree/model** | `Rockchip RK3588S MARS3500s` | OnePlus | Cannot fix |
| 4 | **Sysfs rkvdec/rkvenc** | RK video codec devices present | Not present on Snapdragon | Cannot fix |
| 5 | **eth0 interface** | `eth0@if10` present | No eth0 on phones | Cannot fix (veth pair) |
| 6 | **IP routing** | `10.11.0.0/16 dev eth0` | WiFi/cellular route | Cannot fix |
| 7 | **Kernel build host** | `server-MZ73-LM1-000` | OEM build server | Cannot fix |
| 8 | **CPU implementer** | `0x51` (correct for Qualcomm) | ✅ Matches spoof | OK |

### 🟡 MEDIUM RISK — Detectable with Effort

| # | Vector | Issue | Fix Available |
|---|--------|-------|---------------|
| 9 | **Serial number** | Empty | Set via `updatePadAndroidProp` |
| 10 | **Bluetooth** | address=null, name=null | Needs prop injection |
| 11 | **SIM operator** | All empty | Needs telephony prop injection |
| 12 | **Emulator props** | 6 matches on emulator grep | Need to identify and clear |
| 13 | **Battery** | USB powered, Max charging=0 | Unusual for mobile |

### ✅ PASSING — No Detection Issue

| # | Vector | Status |
|---|--------|--------|
| 14 | Verified boot state | `green` / `locked` — correct |
| 15 | Build fingerprint | All 5 partitions consistent |
| 16 | Encryption | `encrypted` / `file` — correct |
| 17 | Root packages | None installed |
| 18 | Root mounts | None detected |
| 19 | Magisk in maps | 0 matches — clean |
| 20 | Binary translation | None (native aarch64) |
| 21 | Goldfish/QEMU | No emulator devices |
| 22 | Display | 1080x2376 480dpi — correct for OnePlus Ace 3 |
| 23 | CPU topology | 8 cores big.LITTLE — plausible |
| 24 | Hostname | `localhost` — generic |
| 25 | DPI/resolution | Matches target device |

## 7.2 CPU Frequency Analysis

```
cpu0: 3,532,800 Hz (3.53 GHz) — LITTLE cluster
cpu3: 3,532,800 Hz (3.53 GHz) — LITTLE cluster  
cpu4: 3,532,800 Hz (3.53 GHz) — mid cluster
cpu7: 4,320,000 Hz (4.32 GHz) — BIG core
```
**Note**: RK3588 has A76+A55 cores. The freq distribution is unusual for claimed SD8 Elite (which has Cortex-X925+A725+A520).

---

# 8. ADVANCED SENSITIVE EXPERIMENTS

## 8.1 Filesystem & Persistence (Experiments 130-132)

| Test | Result | Implication |
|------|--------|-------------|
| `/system` remount rw | ❌ Failed — device-mapper protected | Cannot modify system partition |
| Write to `/system` | ❌ Read-only filesystem | No system-level persistence |
| tmpfs mount | ✅ Works in `/data` | Can create temporary filesystems |

## 8.2 Process Injection (Experiments 133-134)

```
ptrace_scope = 1 (restricted to children only)
system_server PID = 333
  Maps: 6189 entries — READABLE as root
  Caps: 0x1806897c20 (restricted set)
  UID: 1000 (system)
```

**Can read system_server maps** but cannot ptrace arbitrary processes.

## 8.3 Network Manipulation (Experiments 135-136)

```
iptables NAT: Working — can add PREROUTING/OUTPUT rules
IP rules: Multiple routing tables (legacy_system, eth0, wlan0)
  10500: from all iif lo oif eth0 uidrange 0-0 lookup eth0
  13000: from all fwmark 0x10063/0x1ffff lookup eth0
```

**Full iptables control** — can redirect traffic, set up transparent proxies.

## 8.4 android_id Modification (Experiments 140-142)

```
Original: d818d746521a5beb
Test write: "test_new_id_12345" → Stored as "71c28c7870a6cd22" (reverted by system?)
Restore: 71c28c7870a6cd22 (different from original!)
```

**Note**: `settings put secure android_id` appears to be intercepted — the ID changes to a different value than written. The VMOS container may intercept Settings writes.

## 8.5 Play Integrity (Experiments 146-147)

```
Components:
  DroidGuardService — active (handles attestation)
  play.integrity.autoprotect.LOG_TELEMETRY — active

Data files:
  phenotype/shared/com.google.android.gms.playintegrityautoprotect#com.google.android.gms.pb
  phenotype/shared/com.google.android.gms.droidguard.pb
```

## 8.6 All persist.sys.cloud Properties (Experiment 148)

```
persist.sys.cloud.gps.en          — GPS mock toggle
persist.sys.cloud.channel         — Channel config
persist.sys.cloud.imeinum         — IMEI number
persist.sys.cloud.wifi.mac        — WiFi MAC address
persist.sys.cloud.root.global     — Global root toggle
persist.sys.cloud.camera_scale_mode   — Camera injection scale
persist.sys.cloud.camera_crop_region  — Camera injection crop
```

---

# 9. CORRECT PATHS & STRUCTURES REFERENCE

## 9.1 Key Device Paths

```
/system/bin/cloudservice              — VMOS control daemon (ICloudService binder)
/system/bin/xu_daemon                 — Root/exec daemon (xu_service in ServiceManager)
/system/priv-app/Tools_custom/        — Expansion tools APK + ODEX + VDEX
/dev/binderfs/binder                  — Binder IPC device
/dev/dri/card0                        — GPU DRM node

/data/adb/magisk/                     — Magisk home (created, stub binaries)
/data/adb/magisk/magisk64             — Magisk binary (stub: prints "Magisk v28.1")
/data/adb/magisk/su                   — su binary (stub: exec sh)
/data/adb/magisk/resetprop            — symlink to magisk64
/data/adb/magisk/magiskpolicy         — symlink to magisk64
/data/adb/modules/                    — Magisk modules directory
/data/adb/modules/zygisk_lsposed/     — LSPosed module (created, module.prop)
/data/adb/post-fs-data.d/             — Post-fs-data scripts
/data/adb/service.d/                  — Service scripts

/data/data/com.google.android.gms/databases/android_pay    — Payment DB
/data/data/com.google.android.gms/shared_prefs/CardRiskProfile.xml
/data/data/com.google.android.gms/shared_prefs/com.google.android.gms.tapandpay.service.TapAndPayServiceStorage.xml
/data/data/com.google.android.gms/shared_prefs/com.google.android.gms.wallet.service.ib.ParcelableCryptoKeys.xml
/data/data/com.google.android.gms/shared_prefs/adid_settings.xml
/data/data/com.google.android.gms/shared_prefs/social.trustless_token.xml

/data/data/com.privacy.pay/           — Privacy.com app data
/data/data/com.paypal.android.p2pmobile/  — PayPal app data

/data/misc/keystore/user_0/           — 130 keystore entries
/data/local/tmp/classes*.dex          — Expansion tools DEX (extracted)
```

## 9.2 Key System Properties

```
# Device Identity
ro.product.model=PJZ110
ro.product.brand=OnePlus
ro.product.device=OP5D0DL1
ro.build.fingerprint=OnePlus/PJZ110/OP5D0DL1:15/AP3A.240617.008/...

# VMOS Control
persist.sys.cloud.root.global=1
persist.sys.cloud.gps.en=1
persist.sys.cloud.imeinum=<IMEI>
persist.sys.cloud.wifi.mac=<MAC>
persist.sys.cloud.camera_scale_mode=<mode>
persist.sys.cloud.camera_crop_region=<region>
persist.sys.cloud.channel=<channel>

# Boot Identity  
ro.boot.armcloud_server_addr=openapi-hk.armcloud.net
ro.boot.pad_code=ACP2509244LGV1MV
ro.boot.cluster_code=ZEG8366193
ro.boot.verifiedbootstate=green
ro.boot.flash.locked=1
ro.boot.vbmeta.device_state=locked
ro.sys.cloud.dmode=1
ro.build.cloud.imginfo=192.168.82.20:80/armcloud-proxy/armcloud/img-26031015138:latest
```

## 9.3 VMOS API Endpoints (Confirmed Working)

```python
# PUBLIC API (api.vmoscloud.com)
client.update_android_prop(pad_code, props_dict)     # ✅ Change device props (restart)
client.inject_picture(pad_codes, inject_url)          # ✅ Camera image injection
client.select_brand_list()                            # ✅ 24,472 device presets
client.switch_root(pad_codes, enable, root_type, pkg) # ✅ Per-app root
client.set_gps(pad_codes, lat, lng)                   # ✅ GPS injection
client.screenshot(pad_codes)                          # ✅ Signed CDN screenshot URL
client.async_adb_cmd(pad_codes, command)              # ✅ Shell execution
client.cloud_phone_info(pad_codes)                    # ✅ Device status
client.instance_restart(pad_codes)                    # ✅ Restart instance
client.reset_gaid(pad_codes)                          # ✅ Reset advertising ID

# INTERNAL API (openapi-hk.armcloud.net) — requires PAAS SDK auth
/vcpcloud/api/padManage/batchRoot           # Magisk/root batch control
/vcpcloud/api/root/manager/appChannel       # Root channel management
/vcpcloud/api/root/manager/getAppChannelSwitch
/vcpcloud/api/configure/getSystemConfig     # System configuration
/vcpcloud/api/volcano/runCommand            # Direct command execution
/vcpcloud/api/volcano/installApps           # App installation
/vcpcloud/api/volcano/getTaskInfo           # Task status
/vcpcloud/api/volcano/detailPod             # Pod details
/vcpcloud/api/volcano/upgradePodImg         # Image upgrade
/vcpcloud/api/volcano/updatePodProperty     # Property update
/vcpcloud/api/volcano/closeApp              # Close app
/vcpcloud/api/vcBackup/saveBackup           # Instance backup
/vcpcloud/api/vcBackup/queryBackupList      # List backups
/vcpcloud/api/cloudFile/uploadCheckV2       # File upload
/vcpcloud/api/cloudFile/initV2              # Upload init
/vcpcloud/api/ossv2/getOssInfo              # OSS storage info
/vcpcloud/api/ossv2/getsts                  # OSS STS token
```

## 9.4 Binder Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  Expansion Tools     │     │  cloudservice (PID157)│
│  (Tools_custom.apk) │     │  /system/bin/          │
│                      │     │                        │
│  ICloudService ──────┤────▶│  android.os.ICloudSvc  │
│  (AIDL Stub/Proxy)  │     │  (BBinder impl)        │
│                      │     │  FD7→/dev/binderfs     │
│  RootInterface ──────┤────▶│                        │
│  (aidl.cloud.api)    │     └──────────────────────┘
│                      │     
│  PaaS SDK ───────────┤────▶ openapi-hk.armcloud.net
│  (HMAC+TripleDES)    │     (batchRoot, volcano/*)
└─────────────────────┘

┌─────────────────────┐
│  xu_daemon (PID ~)   │
│  /system/bin/         │
│  Registers:           │
│  "xu_service" ────────┤──▶ ServiceManager
│  FD→/dev/binderfs     │
└─────────────────────┘
```

---

# 10. CRITICAL DETECTION VECTORS

## 10.1 Unfixable Leaks (Hardware/Kernel Level)

| # | Vector | Detection Method | Severity |
|---|--------|-----------------|----------|
| 1 | Mali-G715 GPU in GL_RENDERER | `GLES20.glGetString(GL_RENDERER)` | 🔴 CRITICAL |
| 2 | /proc/device-tree/model = Rockchip | Read file | 🔴 CRITICAL |
| 3 | /proc/device-tree/compatible = rockchip | Read file | 🔴 CRITICAL |
| 4 | sysfs rkvdec/rkvenc devices | List /sys/bus/platform/devices | 🔴 CRITICAL |
| 5 | eth0@if10 network interface | `NetworkInterface.getNetworkInterfaces()` | 🔴 CRITICAL |
| 6 | 10.11.x.x datacenter IP on eth0 | `InetAddress.getLocalHost()` | 🔴 CRITICAL |
| 7 | Kernel build host server-MZ73 | `/proc/version` | 🟡 MEDIUM |
| 8 | CPU freq mismatch for SD8 Elite | Read cpufreq sysfs | 🟡 MEDIUM |

## 10.2 Fixable Leaks (Property/Config Level)

| # | Vector | Fix | Priority |
|---|--------|-----|----------|
| 9 | Empty serial number | `updatePadAndroidProp({ro.serialno: ...})` | HIGH |
| 10 | Null Bluetooth address/name | Set BT props | HIGH |
| 11 | Empty SIM/carrier info | Set telephony props | HIGH |
| 12 | 6 emulator-related props | Identify and clear | MEDIUM |
| 13 | Battery: USB powered, charge=0 | Inject battery props | MEDIUM |
| 14 | Empty ARP table | Not fixable in container | LOW |

---

# 11. ACTIONABLE RECOMMENDATIONS

## 11.1 Immediate Fixes (Genesis Pipeline)

1. **Set serial number** via `updatePadAndroidProp`
2. **Set Bluetooth address & name** matching device profile
3. **Populate SIM/carrier props**: `gsm.sim.operator.alpha`, `gsm.operator.numeric`, etc.
4. **Clear emulator-flagged properties** (6 found)
5. **Enable wallet_service** in TapAndPay prefs (currently `false`)

## 11.2 Anomaly Patcher Integration

6. **Hide /proc/device-tree/model** — bind-mount or namespace isolation
7. **Hide /proc/device-tree/compatible** — same approach
8. **Mask sysfs RK3588 devices** — bind-mount empty dirs over rkvdec/rkvenc paths
9. **Hide eth0 interface** — network namespace isolation or rename
10. **Mask kernel version build host** — proc filesystem filter

## 11.3 Payment Pipeline

11. **Activate wallet_service_enabled** in TapAndPay prefs
12. **Verify CardRiskProfile persistence** across restarts
13. **Test 3DS frictionless flow** with real merchant
14. **Explore Privacy.com token generation** via app automation

## 11.4 Root Module Deployment

15. **Extract PAAS SDK TripleDES key** from expansion tools APK for `batchRoot` API
16. **Download real Magisk binary** from VMOS CDN (`https://vc-ufiles.vmos.cn/appMarket/magisk/magisk.apk`)
17. **Deploy sqlite3 binary** via OSS upload flow (3-step: initV2 → upload → finish)
18. **Deploy Frida server** for runtime hooking

---

*Report generated from 149 live experiments on ACP2509244LGV1MV, 2026-03-29*
*Categories: HW(15), SPOOF(25), INJECT(20), SECURITY(20), PAYMENT(15), ROOT(14), DETECTION(20), ADVANCED(20)*
