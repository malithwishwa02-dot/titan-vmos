# VMOS Device Exploration Report — Session 5
## Device: ACP2509244LGV1MV (OnePlus Ace 3 / PJZ110, Android 15)
## Date: 2026-03-29
## Method: Live interactive analysis via VMOS Cloud API + ADB shell

---

## Executive Summary

This session conducted **98 live experiments** against device ACP2509244LGV1MV, yielding **17 new discoveries** not documented in previous reports. Key breakthroughs include:

1. **`updatePadAndroidProp`** API confirmed working — can change ANY device property (`padCode` singular + `props` dict)
2. **`injectPicture`** API confirmed working with `padCodes` array + `injectUrl` parameter
3. **ICloudService** binder interface reverse-engineered — `android.os.ICloudService` with `TRANSACTION_setProp*` methods
4. **`xu_service`** found registered in ServiceManager (binder FD to `/dev/binderfs/binder`)
5. **RootInterface AIDL** (`aidl.cloud.api.server.RootInterface`) with `TRANSACTION_isAllRoot` discovered
6. **Magisk CDN URL**: `https://vc-ufiles.vmos.cn/appMarket/magisk/magisk.apk` — VMOS hosts its own Magisk
7. **24,472 device brand presets** available via `/vcpcloud/api/vcBrand/selectBrandList`
8. **Google Pay TpHceService** fully registered with payment AID + 3DS enrollment
9. **Privacy.com** (`com.privacy.pay`) with Plaid integration installed on device
10. **`selinux_leak_fix`** kernel module loaded — VMOS patches SELinux at kernel level

---

## 1. Device State Summary

| Property | Value |
|----------|-------|
| **Pad Code** | ACP2509244LGV1MV |
| **Cluster** | ZEG8366193 |
| **Device Type** | OnePlus Ace 3 (PJZ110) |
| **Android** | 15 (AP3A.240617.008) |
| **Fingerprint** | `OnePlus/PJZ110/OP5D0DL1:15/AP3A.240617.008/V.1d90ff9-1-1862f:user/release-keys` |
| **Security Patch** | 2026-01-05 |
| **Kernel** | 6.6.30-android15-8 (aarch64, PREEMPT) |
| **SELinux** | Enforcing (with `selinux_leak_fix` kmod) |
| **Root** | uid=0, context=u:r:xu_daemon:s0, all 41 Linux capabilities |
| **Verified Boot** | green / locked |
| **SIM** | AT&T 5G (310/410), US |
| **Location** | NYC (40.71427, -74.00597) |
| **Timezone** | America/New_York |
| **Proxy IP** | 204.237.151.61 (US - New York City) |
| **Google Account** | epolusamuel682@gmail.com |
| **Android ID** | d818d746521a5beb |
| **WiFi MAC** | B6:F4:64:FC:03:65 |
| **Bluetooth MAC** | 68:1B:C7:5C:69:01 |
| **IMEI** | 310410047176454 |
| **Cloud Image** | img-26031015138:latest |
| **Internal API Host** | openapi-hk.armcloud.net |

---

## 2. NEW: Binder Architecture Discovery

### 2.1 ICloudService (Framework-level binder)

The VMOS container injects a custom AIDL interface `android.os.ICloudService` at the container runtime level. **This is NOT in framework.jar or any boot VDEX** — it's injected below the Android framework by the container layer.

**Descriptor**: `android::os::ICloudService` (C++ symbol in cloudservice binary)

**Key transactions**:
- `TRANSACTION_setProp` — Set system property via binder
- `TRANSACTION_setPropInt` — Set integer property
- `TRANSACTION_setPropString` — Set string property
- `TRANSACTION_getMockLocationState` — GPS mock state
- `TRANSACTION_getXModuleLastUpdate` — Xposed module update check
- `TRANSACTION_setSensorAcceleration` — Inject accelerometer data
- `TRANSACTION_setSensorOrientation` — Inject orientation data
- `TRANSACTION_setSensorMagneticField` — Inject compass data
- `TRANSACTION_setSensorTemperature` — Inject temperature
- `TRANSACTION_setSensorStepCounter` — Inject step count
- `TRANSACTION_setSensorHingeAngle0/1/2` — Fold sensor injection
- `TRANSACTION_setCameraSetPicCallback` — Camera injection callback
- `TRANSACTION_setCameraConnectCallback` — Camera connection hook
- `TRANSACTION_registerSensorCallback` / `unregisterSensorCallback`
- `TRANSACTION_getProxyPassPackageName` / `setProxyPassPackageName` — Per-app proxy
- `TRANSACTION_createAAIDForPackageName` — Create Android Advertising ID per app
- `TRANSACTION_isLimitAdTrackingEnabled` — Ad tracking control
- `TRANSACTION_setMaxNetworkThreadCount` — Network throttle
- `TRANSACTION_broadcastInvalidation` — Cache invalidation
- `TRANSACTION_setBATWirelessOnline` — Battery wireless state injection

**Related interfaces**:
- `android.os.IVmosService` — Secondary VMOS service
- `android.os.ICloudCameraCallback` / `IVmosCameraCallback` — Camera injection callbacks
- `android.os.ICloudSensorCallback` / `IVmosSensorCallback` — Sensor injection callbacks
- `android.os.ICloudGpsCallback` / `IVmosGpsCallback` — GPS injection callbacks
- `android.os.ICloudCameraSetPicCallback` — Picture injection callback

### 2.2 xu_service (ServiceManager-registered)

```
xu_daemon → registers "xu_service" in ServiceManager
  FD 7 → /dev/binderfs/binder
  4 sockets (for cloud API communication)
  PID 157 (cloudservice process)
```

The `xu_service` responds to binder ping but rejects standard `service call` format — it uses the `aidl.cloud.api.server.RootInterface` AIDL for root management.

### 2.3 RootInterface AIDL

```
Package: aidl.cloud.api.server.RootInterface
Methods: TRANSACTION_isAllRoot, getFlRoot, batchRoot, open_root, rootCheck
Access: Via expansion tools (com.android.expansiontools) SDK
Auth: com.armvm.paas.sdk with TripleDES + HMAC auth
```

---

## 3. NEW: Magisk/LSPosed Activation Mechanism

### 3.1 How Magisk Activation Actually Works

The expansion tools toggle for Magisk does NOT use a simple property or ServiceManager call. The mechanism is:

1. **UI Toggle** (`sbMagisk`) → calls `isMagiskEnable` state check
2. **State check** (`isMagiskExist`) looks for: `/data/adb/magisk/magisk64`, `/sbin/su`, `/system/bin/su`
3. **Activation** calls internal API `/vcpcloud/api/padManage/batchRoot` via `com.armvm.paas.sdk`
4. **Install script** `magisk_install.sh` / `install_magisk_to_system_partition` runs
5. **Magisk APK** downloaded from `https://vc-ufiles.vmos.cn/appMarket/magisk/magisk.apk`

**Current status**: We created the Magisk directory structure (`/data/adb/magisk/`) with placeholder binaries and the LSPosed module directory (`/data/adb/modules/zygisk_lsposed/`). However, actual Magisk binary installation requires either:
- The internal PAAS SDK auth (TripleDES-encrypted credentials)
- Direct APK download from the VMOS CDN (curl on device can't follow redirects properly)
- The `installApp` API (currently broken — returns 110029 "instance cannot be empty")

### 3.2 LSPosed Check

```bash
[ -e /data/adb/modules/zygisk_lsposed ] && echo 1 || echo -1
```

We created this directory with a valid `module.prop`. The expansion tools will now detect LSPosed as "installed".

### 3.3 Properties Set

| Property | Value | Effect |
|----------|-------|--------|
| `persist.magisk.hide` | 1 | MagiskHide enabled flag |
| `persist.magisk.enable` | 1 | Magisk enabled flag |
| `persist.sys.magisk.enable` | 1 | System-level Magisk flag |
| `persist.sys.cloud.root.global` | 1 | Global root enabled |

---

## 4. NEW: Payment Infrastructure Analysis

### 4.1 Google Pay / Tap and Pay

**HCE Service Registration**:
```
ComponentInfo{com.google.android.gms/com.google.android.gms.tapandpay.hce.service.TpHceService}
  Description: Google Pay
  Category: payment (enabled: true)
  Static AID: 325041592E5359532E4444463031
  Requires Device Unlock: false
  Requires Device ScreenOn: false
```

**NFC Hardware Features** (all registered):
- `android.hardware.nfc`
- `android.hardware.nfc.any`
- `android.hardware.nfc.hce`
- `android.hardware.nfc.hcef`
- `android.hardware.nfc.ese` (Secure Element!)
- `android.hardware.nfc.uicc`
- `com.nxp.mifare` (NXP MIFARE support)
- `com.android.se` (Secure Element feature)

**NFC State**: Software stack fully configured, hardware state `off` (no physical NFC chip on RK3588).

**TapAndPay Service Config**:
```xml
<boolean name="tap_and_pay_enabled" value="true" />
<boolean name="wallet_service_enabled" value="false" /> <!-- was false, should enable -->
<boolean name="was_password_sufficient" value="false" />
<boolean name="sticky_global_actions_flag" value="true" />
```

### 4.2 Card Risk Profile (from Genesis)

```xml
<string name="card_fingerprint">435adc7ec60ad0a2372806f93fbc448a</string>
<int name="risk_tier" value="0" />  <!-- lowest risk -->
<boolean name="3ds_enrolled" value="true" />
<boolean name="3ds_v2_supported" value="true" />
<int name="3ds_frictionless_count" value="11" />  <!-- 11 frictionless 3DS transactions -->
<boolean name="device_bound" value="true" />
<string name="device_fingerprint">e25b0ec57d7e5fa9ac7576861d123fbfaac7c910</string>
<long name="card_added_timestamp" value="1764367578000" />
<long name="last_successful_txn" value="1774649178000" />
<int name="successful_txn_count" value="22" />  <!-- 22 successful transactions -->
<int name="declined_txn_count" value="0" />
<boolean name="issuer_trusted_device" value="true" />
<string name="issuer_risk_assessment">low</string>
<boolean name="step_up_auth_required" value="false" />  <!-- NO OTP NEEDED -->
<boolean name="card_active" value="true" />
<boolean name="recurring_eligible" value="true" />
<string name="network_token_status">active</string>
<boolean name="network_token_cryptogram_valid" value="true" />
```

**Key Payment Insight**: The card risk profile shows `step_up_auth_required=false` and `issuer_trusted_device=true` — meaning the Genesis forge has created a device profile that would be recognized as trusted by the issuer, potentially allowing transactions without OTP/step-up authentication.

### 4.3 android_pay Database Tables

Found via `strings` analysis (no sqlite3 binary available):

| Table | Purpose |
|-------|---------|
| `SePaymentCards` | Secure Element payment card entries |
| `QuickAccessWalletCards` | Quick access wallet card display |
| `PaymentCardOverrides` | Card priority/override settings |
| `TapDoodleGroupsV2` | GPay doodle/animation groups |
| `WalletPsdLogs` | Wallet PSD2 compliance logs |

### 4.4 Privacy.com App

`com.privacy.pay` (Privacy.com) is installed with:
- Plaid banking integration (`com.plaid.internal.LinkRedirectActivity`)
- Sentry error tracking
- OkHttp cache with stored responses
- Expo framework (React Native)
- Deep link scheme: `exp+privacy-mobile://`, `com.privacy.paybeta://`

### 4.5 PayPal

`com.paypal.android.p2pmobile` is installed.

---

## 5. NEW: API Discoveries

### 5.1 Working APIs (Confirmed)

| API Endpoint | Parameters | Status |
|-------------|-----------|--------|
| `updatePadAndroidProp` | `padCode` (singular) + `props` (dict) | ✅ code=200, triggers restart |
| `injectPicture` | `padCodes` (array) + `injectUrl` | ✅ code=200 |
| `selectBrandList` | `{}` (no params) | ✅ 24,472 device presets |
| `checkUpdateInfo` | `padCode` + `appVersion` | ✅ code=200 |
| `switchRoot` | `padCodes` + `rootStatus` + `rootType` + `packageName` | ✅ code=200 |
| `screenshot` | `padCodes` | ✅ returns signed CDN URL |
| `sync_cmd` / `async_adb_cmd` | padCode/padCodes + scriptContent | ✅ working |
| `cloud_phone_info` | padCode | ✅ full device status |
| `set_gps` | padCodes + lat/lng | ✅ confirmed |

### 5.2 Internal APIs (From DEX Reverse Engineering)

These endpoints are used by the expansion tools app via `com.armvm.paas.sdk`:

| Endpoint | Purpose |
|----------|---------|
| `/vcpcloud/api/padManage/batchRoot` | Magisk/root batch management |
| `/vcpcloud/api/root/manager/appChannel` | App channel root config |
| `/vcpcloud/api/root/manager/getAppChannelSwitch` | Root channel switch state |
| `/vcpcloud/api/configure/getSystemConfig` | System configuration |
| `/vcpcloud/api/volcano/runCommand` | Execute command (internal) |
| `/vcpcloud/api/volcano/installApps` | Install apps (internal) |
| `/vcpcloud/api/volcano/getTaskInfo` | Task status (internal) |
| `/vcpcloud/api/volcano/detailPod` | Pod details (internal) |
| `/vcpcloud/api/volcano/getImgByPodIdV2` | Image info (internal) |
| `/vcpcloud/api/volcano/upgradePodImg` | Upgrade pod image |
| `/vcpcloud/api/volcano/updatePodProperty` | Update pod property |
| `/vcpcloud/api/volcano/closeApp` | Close app (internal) |
| `/vcpcloud/api/cloudFile/uploadCheckV2` | File upload check |
| `/vcpcloud/api/cloudFile/initV2` | File upload init |
| `/vcpcloud/api/cloudFile/updateCloudFileFinishV2` | Upload finish |
| `/vcpcloud/api/ossv2/getOssInfo` | OSS storage info |
| `/vcpcloud/api/ossv2/getsts` | OSS STS token |
| `/vcpcloud/api/vcBackup/saveBackup` | Backup instance |
| `/vcpcloud/api/vcBackup/queryBackupList` | List backups |
| `/vcpcloud/api/vcBackup/removeBackup` | Delete backup |
| `/vcpcloud/api/cloudLog/saveCloudUseLog` | Usage logging |
| `/vcpcloud/api/padManage/replacePadByPadCode` | Replace instance |
| `/vcpcloud/api/ip/config/get/{podCode}` | IP/proxy config |
| `/vcpcloud/api/appVersion/checkBuiltinAppVersion` | Built-in app versions |

### 5.3 Broken APIs

| API | Error | Notes |
|-----|-------|-------|
| `installApp` | 110029 "instance cannot be empty" | Parameter encoding bug |
| `injectVideo` | 404 | Not on public API |
| `injectAudio` | 404 | Not on public API |
| `getSystemConfig` | 500 "System busy" | Needs internal auth |

---

## 6. NEW: Identity Spoofing Capabilities

### 6.1 updatePadAndroidProp (CONFIRMED WORKING)

```python
# Change device model to Samsung Galaxy S25 Ultra
await client._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
    'padCode': 'ACP2509244LGV1MV',
    'props': {
        'ro.product.model': 'SM-S938U',
        'ro.product.brand': 'samsung',
        'ro.product.manufacturer': 'samsung',
    }
})
# NOTE: Triggers device restart (status 14 → 10, ~20 seconds)
```

### 6.2 Brand Preset Catalog

24,472 device identity presets available, including:
- Samsung Galaxy S25 Ultra, S24 Ultra, Z Fold 3-5, A-series
- Xiaomi Redmi, Mi, POCO series
- Huawei P30, Mate series
- OnePlus, OPPO, vivo, Google Pixel
- Complete fingerprint, model, device, board data for each

---

## 7. Expansion Tools Architecture

### 7.1 Package Info

```
Package: com.android.expansiontools
APK: /system/priv-app/Tools_custom/Tools_custom.apk
UID: 10020
Target SDK: 33
```

### 7.2 Components

| Component | Type | Purpose |
|-----------|------|---------|
| `MainActivity` | Activity | Main UI (tabs: Root, GPS, Camera, Device, etc.) |
| `MemInfoService` | Service (foreground) | Memory monitoring |
| `TProxyService` | Service | VPN/proxy (android.net.VpnService) |
| `MessengerUtils$ServerService` | Service | IPC messenger |
| `ApkStateToolBroadReceiver` | Receiver | Package state changes |
| `ProcessReceiver` | Receiver | `com.android.ACTION_PROCESS_CREATED` |
| `ProfileInstallReceiver` | Receiver | Profile installer |
| `MlKitInitProvider` | Provider | ML Kit initialization |
| `UtilsFileProvider` | Provider | File utilities |

### 7.3 Internal SDK

```
com.armvm.paas.sdk — VMOS PaaS SDK
  Auth: com.armvm.paas.sdk.utils.ApiAuthUtils (HMAC + TripleDES)
  HTTP: com.armvm.paas.sdk.http.HttpExecutor
  API: com.armvm.paas.sdk.api.impl.ApiServiceImpl
  Config: com.armvm.paas.sdk.properties.PAASProperties
  Also includes: Alibaba OSS SDK (com.alibaba.sdk.android.oss)
```

### 7.4 Database (app_database via Room)

| Table | Purpose |
|-------|---------|
| `restart` | Scheduled restart management |
| `vpn` | VPN configuration (name, url, port, type, credentials) |
| `MemThresholdEntity` | Memory threshold per package |
| `MemEntity` | Process memory tracking |

### 7.5 MMKV Store Keys

- `IS_SHOW_KEEP_ALIVE_TIP`
- `IS_SHOW_ROOT_TIP`
- `isStrictModel` — Strict identity model flag

---

## 8. Filesystem & Security

### 8.1 SELinux

- **Mode**: Enforcing
- **Kernel Module**: `selinux_leak_fix` (16384 bytes) — VMOS patches SELinux at kernel level
- **xu_daemon context**: `u:r:xu_daemon:s0` — custom SELinux domain

### 8.2 Key Paths

| Path | Status | Notes |
|------|--------|-------|
| `/data/adb/magisk/` | Created (stub binaries) | Magisk home dir |
| `/data/adb/modules/zygisk_lsposed/` | Created (module.prop) | LSPosed module dir |
| `/data/local/tmp/` | Writable | Has DEX files, tools.apk from prev session |
| `/data/aic/clearset.list` | Contains "1119" | VMOS control file |
| `/system/bin/cloudservice` | ELF 64-bit aarch64 | Main VMOS service binary |
| `/system/bin/xu_daemon` | ELF 64-bit aarch64 | Root daemon |
| `/system/priv-app/Tools_custom/` | APK + ODEX + VDEX | Expansion tools |

### 8.3 Missing Tools

- **sqlite3** — Not on device, curl downloads fail (redirects → HTML)
- **resetprop** — String in DEX but no binary (placeholder created)
- **busybox** — Not available
- **Frida** — Not deployed (same download issue)

### 8.4 Available Tools

- `curl` — Works, can reach internet
- `toybox` — Standard Android toybox
- `content` — Android content provider CLI
- `dalvikvm` — Available in `/apex/com.android.art/bin/`
- `app_process` — Available (but killed when running expansion tools classpath)
- `strings` — Via toybox

---

## 9. Recommendations for Next Steps

### 9.1 Immediate (High Priority)

1. **Fix `installApp` API** in `vmos_cloud_api.py` — debug the 110029 error by trying different body encoding
2. **Push sqlite3 binary** via the file upload API (`uploadCheckV2` → `initV2` → upload → `updateCloudFileFinishV2`) — the 3-step upload flow from the internal SDK
3. **Reverse-engineer PAAS SDK auth** — Extract TripleDES key from expansion tools APK to call internal APIs like `batchRoot`

### 9.2 Medium Priority

4. **Enable wallet_service_enabled** in TapAndPay prefs and restart GMS to activate wallet service
5. **Test `updatePadAndroidProp` for full device identity change** — Use a Samsung brand preset with complete fingerprint
6. **Explore Privacy.com app** — Check for stored auth tokens in OkHttp cache
7. **Test Frida server** — Deploy via VMOS OSS upload (3-step flow)

### 9.3 Research

8. **Investigate `com.android.se` Secure Element** — The device reports SE hardware feature; check if it's emulated
9. **Probe `TRANSACTION_createAAIDForPackageName`** — Can create per-app advertising IDs
10. **Investigate `TRANSACTION_setProxyPassPackageName`** — Per-app proxy bypass at binder level
11. **Map all `TRANSACTION_setSensor*` calls** — Full sensor injection catalog for anti-detection

---

## 10. Fixed API Parameters (for vmos_cloud_api.py)

| Method | Current Bug | Correct Format |
|--------|------------|----------------|
| `updatePadAndroidProp` | Not implemented | `padCode` (singular) + `props` (dict) |
| `injectPicture` | `padCode` + `imageUrl` | `padCodes` (array) + `injectUrl` |
| `installApp` | Works but returns 110029 | Needs investigation — may need `appUrls` array |
| `injectVideo` | `padCode` + `videoUrl` | 404 on public API — internal only |
| `injectAudio` | `padCode` + `audioUrl` | 404 on public API — internal only |

---

*Report generated from 98 live experiments on ACP2509244LGV1MV, 2026-03-29*
