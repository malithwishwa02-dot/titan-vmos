#!/usr/bin/env python3
"""
Titan — Real Device Read-Only Analyzer
=======================================
Connects to a real Android phone via ADB and performs a comprehensive
forensic scan. ZERO modifications — purely reads data from the device.

Usage:
    python3 scripts/analyze_real_device.py                 # auto-detect device
    python3 scripts/analyze_real_device.py --device <ip:port>
    python3 scripts/analyze_real_device.py --quick         # 60-second fast scan
    python3 scripts/analyze_real_device.py --output report.json

Scans:
    • Hardware identity (model, IMEI, serial, baseband, bootloader)
    • Android build & security patch level
    • Carrier lock status & SIM info
    • MDM / Device Admin policy detection
    • Installed apps (user + system flagged)
    • Root / Magisk / Frida detection
    • Play Integrity readiness assessment
    • Network interfaces, proxy, DNS
    • Storage & partition map
    • Security config (SELinux, verified boot, encryption)
    • Sensor inventory
    • Running processes & services
    • Account presence (Google, etc.)
    • Battery & hardware health
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any


# ─────────────────────────────────────────────────────────────────────
#  ADB helpers (read-only — no shell writes)
# ─────────────────────────────────────────────────────────────────────

def adb(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    """Run an ADB command. Returns (success, output)."""
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {e}"


def shell(target: str, cmd: str, timeout: int = 10) -> str:
    """Run a shell command on device. Returns stdout or empty string."""
    ok, out = adb(target, f'shell "{cmd}"', timeout=timeout)
    return out if ok else ""


def getprop(target: str, prop: str) -> str:
    """Get a single Android property."""
    return shell(target, f"getprop {prop}").strip()


def getprop_all(target: str) -> Dict[str, str]:
    """Get all Android properties as a dict."""
    ok, out = adb(target, "shell getprop")
    props = {}
    if ok:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("[") and "]: [" in line:
                try:
                    key = line.split("]: [")[0].lstrip("[")
                    val = line.split("]: [")[1].rstrip("]")
                    props[key] = val
                except Exception:
                    pass
    return props


def find_device() -> Optional[str]:
    """Auto-detect the connected ADB device (skips emulators/Cuttlefish)."""
    try:
        r = subprocess.run("adb devices -l", shell=True, capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "\tdevice" in line and "emulator" not in line and "0.0.0.0:6520" not in line:
                target = line.split()[0]
                return target
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────
#  Scan modules — each returns a dict, ZERO writes
# ─────────────────────────────────────────────────────────────────────

def scan_hardware_identity(target: str, props: Dict) -> Dict:
    """Scan hardware identity: model, IMEI, serial, baseband, CPU."""
    print("  [1/16] Hardware identity...")
    
    imei1 = shell(target, "service call iphonesubinfo 1 | awk -F\"'\" 'NR>1{print $2}' | tr -d '\\n. '")
    # fallback via getprop
    if not imei1 or len(imei1) < 10:
        imei1 = getprop(target, "persist.radio.imei")
    
    return {
        "manufacturer":     props.get("ro.product.manufacturer", ""),
        "brand":            props.get("ro.product.brand", ""),
        "model":            props.get("ro.product.model", ""),
        "device":           props.get("ro.product.device", ""),
        "name":             props.get("ro.product.name", ""),
        "hardware":         props.get("ro.hardware", ""),
        "board":            props.get("ro.product.board", ""),
        "soc":              props.get("ro.soc.model", props.get("ro.hardware.chipname", "")),
        "serial":           shell(target, "getprop ro.serialno") or shell(target, "settings get global android_id"),
        "android_id":       shell(target, "settings get secure android_id"),
        "imei_1":           imei1,
        "baseband":         props.get("gsm.version.baseband", props.get("ro.baseband", "")),
        "bootloader":       props.get("ro.bootloader", ""),
        "cpu_abi":          props.get("ro.product.cpu.abi", ""),
        "cpu_abi2":         props.get("ro.product.cpu.abi2", ""),
        "ram_bytes":        shell(target, "cat /proc/meminfo | grep MemTotal"),
        "cpu_info":         shell(target, "cat /proc/cpuinfo | grep 'Hardware\\|model name\\|Processor' | head -3"),
        "gpu_renderer":     shell(target, "dumpsys SurfaceFlinger | grep GLES | head -3"),
    }


def scan_build_info(target: str, props: Dict) -> Dict:
    """Scan build and OS version info."""
    print("  [2/16] Build & OS info...")
    return {
        "android_version":          props.get("ro.build.version.release", ""),
        "android_sdk":              props.get("ro.build.version.sdk", ""),
        "build_fingerprint":        props.get("ro.build.fingerprint", ""),
        "build_description":        props.get("ro.build.description", ""),
        "build_type":               props.get("ro.build.type", ""),
        "build_tags":               props.get("ro.build.tags", ""),
        "build_id":                 props.get("ro.build.id", ""),
        "build_date":               props.get("ro.build.date", ""),
        "debuggable":               props.get("ro.debuggable", ""),
        "security_patch":           props.get("ro.build.version.security_patch", ""),
        "kernel_version":           shell(target, "uname -r"),
        "kernel_full":              shell(target, "uname -a"),
        "incremental":              props.get("ro.build.version.incremental", ""),
        "codename":                 props.get("ro.build.version.codename", ""),
        "uptime":                   shell(target, "uptime"),
    }


def scan_carrier_sim(target: str, props: Dict) -> Dict:
    """Scan SIM, carrier, and device lock status."""
    print("  [3/16] Carrier & SIM...")
    
    sim_state     = shell(target, "getprop gsm.sim.state")
    operator_name = shell(target, "getprop gsm.operator.alpha")
    mcc_mnc       = shell(target, "getprop gsm.operator.numeric")
    sim_operator  = shell(target, "getprop gsm.sim.operator.alpha")
    
    # Check for carrier lock indicators
    cf_lock   = shell(target, "getprop ro.carrier")
    oem_lock  = shell(target, "getprop ro.oem_unlock_supported")
    fl_lock   = shell(target, "getprop ro.boot.flash.locked")
    vb_state  = shell(target, "getprop ro.boot.verifiedbootstate")
    boot_lock = shell(target, "getprop sys.oem_unlock_allowed")
    
    return {
        "sim_state":            sim_state,
        "operator_name":        operator_name,
        "operator_mcc_mnc":     mcc_mnc,
        "sim_operator":         sim_operator,
        "sim_iccid":            shell(target, "getprop gsm.sim.operator.numeric"),
        "carrier_config":       cf_lock,
        "oem_unlock_supported": oem_lock,
        "flash_locked":         fl_lock,
        "verified_boot_state":  vb_state,
        "oem_unlock_allowed":   boot_lock,
        "telephony_type":       shell(target, "getprop telephony.lteOnGsmDevice"),
        "dual_sim":             shell(target, "getprop persist.radio.multisim.config"),
        "phone_number":         shell(target, "getprop gsm.sim.operator.numeric") or
                                shell(target, "service call iphonesubinfo 13 2>/dev/null | head -5"),
        # Carrier lock assessment
        "carrier_lock_indicators": {
            "flash_locked_1":       fl_lock == "1",
            "vb_not_green":         vb_state != "green",
            "oem_unlock_unsupported": oem_lock == "0",
            "carrier_set":          bool(cf_lock and cf_lock not in ("", "unknown", "wifi-only")),
        }
    }


def scan_mdm_policy(target: str) -> Dict:
    """Detect MDM / Device Admin policies installed."""
    print("  [4/16] MDM & device admin policy...")
    
    # Read device_policies.xml (requires adb — not root needed on most devices)
    dp_xml = shell(target, "cat /data/system/device_policies.xml 2>/dev/null | head -50")
    
    # Check device admin apps via dumpsys
    dm_dump = shell(target, "dumpsys device_policy 2>/dev/null | head -80", timeout=15)
    
    # Known MDM package names
    mdm_packages = {
        "com.att.mobileclientplatform":         "AT&T MCP",
        "com.tmobile.pr.adapt":                 "T-Mobile MDM",
        "com.google.android.apps.work.clouddpc": "Google Cloud Device Policy",
        "com.microsoft.intune":                  "Microsoft Intune",
        "com.mobileiron":                        "MobileIron",
        "com.soti.mobicontrol":                  "SOTI MobiControl",
        "com.air-watch.androidagent":            "VMware AirWatch",
        "com.samsung.android.knox.containeragent": "Samsung Knox Container",
        "com.samsung.klmsagent":                 "Samsung KLMS Agent",
        "com.verizon.mdm":                       "Verizon MDM",
        "com.airwatch.androidagent":             "AirWatch",
        "com.sophos.msx":                        "Sophos Mobile",
        "com.blackberry.bbm.platform":           "BlackBerry UEM",
        "com.citrix.cwc.enterprise":             "Citrix XenMobile",
    }
    
    ok, pkg_out = adb(target, "shell pm list packages 2>/dev/null")
    installed_pkgs = set(line.replace("package:", "").strip() for line in (pkg_out or "").splitlines())
    
    found_mdm = {}
    for pkg, name in mdm_packages.items():
        if pkg in installed_pkgs:
            found_mdm[pkg] = name
    
    # Knox status
    knox_ver = getprop(target, "ro.knox.bitmask")
    warranty_void = getprop(target, "ro.boot.warranty_bit")
    
    return {
        "device_admin_apps":        found_mdm,
        "mdm_detected":             bool(found_mdm),
        "device_policy_summary":    dm_dump[:1000] if dm_dump else "no_access",
        "knox_version":             knox_ver,
        "knox_warranty_void":       warranty_void,
        "adb_enabled":              getprop(target, "persist.service.adb.enable") or
                                    shell(target, "settings get global adb_enabled"),
        "dev_options_enabled":      shell(target, "settings get global development_settings_enabled"),
        "install_non_market":       shell(target, "settings get secure install_non_market_apps"),
    }


def scan_root_detection(target: str) -> Dict:
    """Check for root, Magisk, Xposed, Frida indicators."""
    print("  [5/16] Root & modification detection...")
    
    root_paths = [
        "/system/bin/su", "/system/xbin/su", "/sbin/su",
        "/data/local/tmp/su", "/vendor/bin/su",
        "/system/app/Superuser.apk", "/system/app/SuperSU",
    ]
    magisk_paths = [
        "/sbin/.magisk", "/data/adb/magisk", "/data/adb/modules",
        "/sbin/magisk", "/system/app/MagiskManager",
        "/data/local/magisk.apk",
    ]
    frida_indicators = [
        "/data/local/tmp/frida-server",
        "/data/local/tmp/re.frida.server",
    ]
    
    def check_path(p: str) -> bool:
        r = shell(target, f"[ -e '{p}' ] && echo YES || echo NO")
        return r.strip() == "YES"
    
    su_found     = {p: check_path(p) for p in root_paths}
    magisk_found = {p: check_path(p) for p in magisk_paths}
    frida_found  = {p: check_path(p) for p in frida_indicators}
    
    # Check id — if not root this will say uid=2000(shell) or similar
    whoami = shell(target, "id")
    
    # Check for test-keys (unsigned build = custom ROM or rooted)
    build_tags = getprop(target, "ro.build.tags")
    
    # Busybox
    busybox = shell(target, "which busybox 2>/dev/null || echo NONE")
    
    # Magisk resetprop
    resetprop = shell(target, "which resetprop 2>/dev/null || echo NONE")
    
    return {
        "adb_uid":              whoami,
        "is_root":              "uid=0" in whoami,
        "build_tags":           build_tags,
        "test_keys_build":      "test-keys" in build_tags,
        "su_paths_found":       {k: v for k, v in su_found.items() if v},
        "magisk_paths_found":   {k: v for k, v in magisk_found.items() if v},
        "frida_paths_found":    {k: v for k, v in frida_found.items() if v},
        "busybox_present":      busybox != "NONE" and busybox,
        "resetprop_present":    resetprop != "NONE" and resetprop,
        "root_detected":        any(su_found.values()) or any(magisk_found.values()),
        "magisk_detected":      any(magisk_found.values()),
        "frida_detected":       any(frida_found.values()),
    }


def scan_security_config(target: str, props: Dict) -> Dict:
    """Scan SELinux, encryption, verified boot."""
    print("  [6/16] Security configuration...")
    
    selinux_enforce = shell(target, "getenforce 2>/dev/null || cat /sys/fs/selinux/enforce 2>/dev/null")
    encryption      = shell(target, "getprop ro.crypto.state")
    enc_type        = shell(target, "getprop ro.crypto.type")
    vb_state        = props.get("ro.boot.verifiedbootstate", "")
    vb_device       = props.get("ro.boot.vbmeta.device_state", "")
    
    return {
        "selinux_status":           selinux_enforce,
        "selinux_enforcing":        selinux_enforce.lower() == "enforcing",
        "encryption_state":         encryption,
        "encryption_type":          enc_type,
        "verified_boot_state":      vb_state,
        "vbmeta_device_state":      vb_device,
        "dm_verity":                props.get("ro.boot.veritymode", ""),
        "keystore_state":           shell(target, "getprop keystore.ready 2>/dev/null"),
        "gatekeeper_present":       bool(shell(target, "ls /vendor/lib64/hw/gatekeeper.*.so 2>/dev/null || ls /system/lib64/hw/gatekeeper*.so 2>/dev/null")),
        "strongbox_present":        props.get("ro.hardware.keystore_desede", "") or
                                    shell(target, "getprop ro.hardware.strongbox 2>/dev/null"),
        "tee_present":              bool(props.get("ro.hardware.keystore", "")),
        "lockscreen_type":          shell(target, "getprop ro.lockscreen.deviceHasKeyguard 2>/dev/null"),
    }


def scan_network(target: str) -> Dict:
    """Scan network interfaces, proxy, DNS."""
    print("  [7/16] Network configuration...")
    
    interfaces  = shell(target, "ip addr show 2>/dev/null | grep -E 'inet |^[0-9]+:' | head -30")
    wifi_info   = shell(target, "dumpsys wifi 2>/dev/null | grep -E 'mWifiInfo|SSID|BSSID|ip_address|link speed' | head -10", timeout=12)
    proxy_host  = shell(target, "settings get global http_proxy")
    dns1        = shell(target, "getprop net.dns1")
    dns2        = shell(target, "getprop net.dns2")
    wifi_dns1   = shell(target, "getprop dhcp.wlan0.dns1")
    
    # VPN check
    vpn_ifaces  = shell(target, "ip addr show tun0 2>/dev/null || ip addr show ppp0 2>/dev/null || echo NONE")
    
    # Private DNS (DoT)
    private_dns = shell(target, "settings get global private_dns_mode")
    private_dns_host = shell(target, "settings get global private_dns_specifier")
    
    return {
        "interfaces":           interfaces,
        "wifi_info":            wifi_info,
        "proxy":                proxy_host or "none",
        "dns1":                 dns1,
        "dns2":                 dns2,
        "wifi_dns1":            wifi_dns1,
        "vpn_detected":         "tun0" in vpn_ifaces or "ppp0" in vpn_ifaces,
        "vpn_interfaces":       vpn_ifaces if vpn_ifaces != "NONE" else "",
        "private_dns_mode":     private_dns,
        "private_dns_hostname": private_dns_host,
        "airplane_mode":        shell(target, "settings get global airplane_mode_on"),
        "mobile_data":          shell(target, "settings get global mobile_data"),
        "wifi_enabled":         shell(target, "settings get global wifi_on"),
    }


def scan_storage(target: str) -> Dict:
    """Scan storage partitions and filesystem usage."""
    print("  [8/16] Storage & partitions...")
    
    df_out      = shell(target, "df -h 2>/dev/null | head -25", timeout=15)
    mounts      = shell(target, "mount 2>/dev/null | grep -E '(ext4|f2fs|sdcardfs|fuse|tmpfs)' | head -20")
    partitions  = shell(target, "cat /proc/partitions 2>/dev/null | head -30")
    block_devs  = shell(target, "ls /dev/block/by-name/ 2>/dev/null | head -30")
    
    return {
        "filesystem_usage":     df_out,
        "key_mounts":           mounts,
        "partitions":           partitions,
        "named_partitions":     block_devs,
        "data_encryption":      shell(target, "getprop ro.crypto.state"),
        "adoptable_storage":    shell(target, "getprop ro.sdcardfs"),
    }


def scan_apps(target: str, quick: bool = False) -> Dict:
    """Scan installed apps — user apps and suspicious system apps."""
    print("  [9/16] Installed applications...")
    
    ok_user, user_pkgs = adb(target, "shell pm list packages -3 2>/dev/null")  # 3rd party only
    ok_sys,  sys_pkgs  = adb(target, "shell pm list packages -s 2>/dev/null")  # system only
    
    user_list = [l.replace("package:", "").strip() for l in (user_pkgs or "").splitlines() if l.startswith("package:")]
    sys_list  = [l.replace("package:", "").strip() for l in (sys_pkgs  or "").splitlines() if l.startswith("package:")]
    
    # Flag suspicious/notable packages
    flagged_packages = {
        # Payment / banking
        "com.google.android.apps.walletnfcrel": "Google Wallet",
        "com.android.vending":                  "Play Store",
        "com.paypal.android.p2pmobile":         "PayPal",
        "com.venmo":                             "Venmo",
        "com.squarecashapp":                    "Cash App",
        # MDM / spyware
        "com.android.devicemonitor":            "Device Monitor (suspicious)",
        "com.qualcomm.atfwd":                   "Qualcomm ATFWD Daemon",
        "com.android.carrierassets":            "Carrier Assets",
        "com.logging.lite":                     "Carrier Logging",
        # Security
        "com.codeaurora.ims":                   "IMS (call spoof risk)",
    }
    
    highlighted = {}
    all_user = set(user_list)
    all_sys  = set(sys_list)
    for pkg, label in flagged_packages.items():
        if pkg in all_user or pkg in all_sys:
            highlighted[pkg] = label
    
    result = {
        "user_app_count":       len(user_list),
        "system_app_count":     len(sys_list),
        "notable_apps":         highlighted,
        "user_apps":            sorted(user_list),
    }
    
    if not quick:
        result["system_apps"] = sorted(sys_list)
    
    return result


def scan_processes(target: str) -> Dict:
    """Scan running processes and services."""
    print("  [10/16] Running processes...")
    
    proc_list  = shell(target, "ps -A -o PID,USER,NAME 2>/dev/null | head -60", timeout=12)
    services   = shell(target, "service list 2>/dev/null | wc -l")
    
    # Check for suspicious processes
    suspicious = []
    for proc in ["frida-server", "xposed", "substrate", "magiskd", "supersu", "tincore"]:
        if shell(target, f"pgrep -f {proc} 2>/dev/null"):
            suspicious.append(proc)
    
    return {
        "process_list":         proc_list,
        "service_count":        services,
        "suspicious_processes": suspicious,
        "activity_manager":     shell(target, "dumpsys activity processes 2>/dev/null | grep 'com.*foreground' | head -10", timeout=12),
    }


def scan_accounts(target: str) -> Dict:
    """Detect presence of accounts (without reading sensitive data)."""
    print("  [11/16] Account presence...")
    
    # Just check if account data is present — NOT reading credentials
    acct_types = shell(target, "dumpsys account 2>/dev/null | grep 'Account {' | head -20", timeout=12)
    
    google_accts = []
    for line in acct_types.splitlines():
        if "com.google" in line or "@gmail" in line.lower() or "@google" in line.lower():
            # Only extract non-sensitive (account type presence)
            google_accts.append(line.strip())
    
    return {
        "account_types_present":    acct_types[:500] if acct_types else "no_access",
        "google_account_present":   bool(google_accts),
        "google_account_count":     len(google_accts),
        "accounts_db_readable":     bool(acct_types),
        "gsf_id":                   shell(target, "settings get secure android_id"),
    }


def scan_sensors(target: str) -> Dict:
    """Enumerate hardware sensors."""
    print("  [12/16] Sensor inventory...")
    
    sensors = shell(target, "dumpsys sensorservice 2>/dev/null | grep -A2 'Sensor List' | head -80", timeout=12)
    
    return {
        "sensor_dump":          sensors[:2000] if sensors else "no_access",
        "has_accelerometer":    "Accelerat" in sensors,
        "has_gyroscope":        "Gyroscope" in sensors or "gyro" in sensors.lower(),
        "has_gps":              bool(shell(target, "getprop ro.hardware.gps 2>/dev/null")),
        "has_nfc":              getprop(target, "ro.nfc.port") != "" or
                                bool(shell(target, "pm list features 2>/dev/null | grep 'android.hardware.nfc'")),
        "has_fingerprint":      bool(shell(target, "pm list features 2>/dev/null | grep 'fingerprint'")),
        "has_face_unlock":      bool(shell(target, "pm list features 2>/dev/null | grep 'face'")),
        "has_barometer":        "Pressure" in sensors or "Barometer" in sensors,
        "nfc_enabled":          shell(target, "settings get secure nfc_on 2>/dev/null") or
                                shell(target, "settings get global nfc_on 2>/dev/null"),
    }


def scan_battery(target: str) -> Dict:
    """Scan battery and charging status."""
    print("  [13/16] Battery & health...")
    
    batt = shell(target, "dumpsys battery 2>/dev/null | head -30", timeout=10)
    
    info = {"raw": batt}
    for line in (batt or "").splitlines():
        line = line.strip()
        if "level:" in line:
            try:
                info["level"] = int(line.split(":")[1].strip())
            except Exception:
                pass
        elif "status:" in line:
            info["status"] = line.split(":")[1].strip()
        elif "health:" in line:
            info["health"] = line.split(":")[1].strip()
        elif "AC powered:" in line:
            info["ac_powered"] = "true" in line.lower()
        elif "USB powered:" in line:
            info["usb_powered"] = "true" in line.lower()
        elif "temperature:" in line:
            try:
                temp_raw = int(line.split(":")[1].strip())
                info["temperature_celsius"] = temp_raw / 10.0
            except Exception:
                pass
    
    return info


def scan_bluetooth(target: str) -> Dict:
    """Scan Bluetooth configuration."""
    print("  [14/16] Bluetooth...")
    
    bt_dump = shell(target, "dumpsys bluetooth_manager 2>/dev/null | head -30", timeout=10)
    
    return {
        "bt_address":   getprop(target, "persist.bluetooth.bdaddr") or
                        shell(target, "settings get secure bluetooth_address"),
        "bt_name":      shell(target, "settings get secure bluetooth_name"),
        "bt_enabled":   shell(target, "settings get global bluetooth_on"),
        "bt_dump":      bt_dump[:500] if bt_dump else "",
    }


def scan_play_integrity_readiness(target: str, props: Dict) -> Dict:
    """Assess how likely this device is to pass Play Integrity checks."""
    print("  [15/16] Play Integrity readiness...")
    
    build_type     = props.get("ro.build.type", "")
    build_tags     = props.get("ro.build.tags", "")
    vb_state       = props.get("ro.boot.verifiedbootstate", "")
    debuggable     = props.get("ro.debuggable", "")
    test_keys      = "test-keys" in build_tags
    
    # Fingerprint check — does it look like an OEM release build?
    fingerprint    = props.get("ro.build.fingerprint", "")
    looks_stock    = (
        build_type == "user" and
        build_tags == "release-keys" and
        not test_keys and
        vb_state == "green" and
        debuggable == "0"
    )
    
    score = 0
    checks = {}
    
    checks["build_type_user"]        = build_type == "user";        score += 20 if checks["build_type_user"] else 0
    checks["release_keys"]           = build_tags == "release-keys"; score += 25 if checks["release_keys"] else 0
    checks["verified_boot_green"]    = vb_state == "green";          score += 25 if checks["verified_boot_green"] else 0
    checks["not_debuggable"]         = debuggable == "0";            score += 15 if checks["not_debuggable"] else 0
    checks["no_test_keys"]           = not test_keys;                score += 15 if checks["no_test_keys"] else 0
    
    # Likely tier
    if score >= 90:
        tier = "STRONG_POSSIBLE"
    elif score >= 70:
        tier = "DEVICE_LIKELY"
    elif score >= 50:
        tier = "BASIC_LIKELY"
    else:
        tier = "LIKELY_FAIL"
    
    return {
        "score":            score,
        "max_score":        100,
        "likely_tier":      tier,
        "looks_stock":      looks_stock,
        "checks":           checks,
        "fingerprint":      fingerprint,
        "build_type":       build_type,
        "build_tags":       build_tags,
        "verified_boot":    vb_state,
    }


def scan_device_flags(target: str, props: Dict) -> Dict:
    """Collect misc flags and behavioral indicators."""
    print("  [16/16] Device flags & misc settings...")
    
    return {
        "location_mode":        shell(target, "settings get secure location_mode"),
        "location_providers":   shell(target, "settings get secure location_providers_allowed"),
        "mock_location":        shell(target, "settings get secure mock_location"),
        "mock_location_app":    shell(target, "settings get secure allow_mock_location"),
        "accessibility_enabled": shell(target, "settings get secure accessibility_enabled"),
        "screen_resolution":    shell(target, "wm size 2>/dev/null"),
        "screen_density":       shell(target, "wm density 2>/dev/null"),
        "screen_on":            shell(target, "dumpsys power 2>/dev/null | grep 'Display Power' | head -2"),
        "timezone":             shell(target, "getprop persist.sys.timezone"),
        "language":             shell(target, "getprop persist.sys.locale || getprop ro.product.locale"),
        "data_roaming":         shell(target, "settings get global data_roaming"),
        "usb_config":           shell(target, "getprop sys.usb.config"),
        "charging_functions":   shell(target, "getprop sys.usb.state"),
        "gms_version":          getprop(target, "com.google.android.gms.versioncode") or
                                shell(target, "pm list packages --show-versioncode 2>/dev/null | grep 'com.google.android.gms:' | head -1"),
        "play_store_version":   shell(target, "pm list packages --show-versioncode 2>/dev/null | grep 'com.android.vending:' | head -1"),
    }


# ─────────────────────────────────────────────────────────────────────
#  Report generation
# ─────────────────────────────────────────────────────────────────────

def generate_report(data: Dict, target: str) -> None:
    """Print a human-readable analysis report."""
    hw   = data.get("hardware_identity", {})
    build = data.get("build_info", {})
    sim  = data.get("carrier_sim", {})
    mdm  = data.get("mdm_policy", {})
    root = data.get("root_detection", {})
    sec  = data.get("security_config", {})
    pi   = data.get("play_integrity_readiness", {})
    apps = data.get("apps", {})
    
    print("\n")
    print("═" * 70)
    print("  TITAN REAL DEVICE ANALYSIS REPORT")
    print(f"  Scanned: {data.get('scan_timestamp', '')}")
    print(f"  Target:  {target}")
    print("═" * 70)
    
    # ── Device identity ──
    print("\n  DEVICE IDENTITY")
    print("  " + "─" * 50)
    print(f"  Manufacturer  : {hw.get('manufacturer', '?')} ({hw.get('brand', '?')})")
    print(f"  Model         : {hw.get('model', '?')} ({hw.get('device', '?')})")
    print(f"  SoC           : {hw.get('soc', hw.get('hardware', '?'))}")
    print(f"  Serial        : {hw.get('serial', '?')}")
    print(f"  IMEI-1        : {hw.get('imei_1', 'no_access')}")
    print(f"  Android       : {build.get('android_version', '?')} (SDK {build.get('android_sdk', '?')})")
    print(f"  Security Patch: {build.get('security_patch', '?')}")
    print(f"  Build Type    : {build.get('build_type', '?')} / {build.get('build_tags', '?')}")
    print(f"  Kernel        : {build.get('kernel_version', '?')}")
    
    # ── Carrier / SIM ──
    print("\n  CARRIER & LOCK STATUS")
    print("  " + "─" * 50)
    print(f"  Operator      : {sim.get('operator_name', '?')} ({sim.get('operator_mcc_mnc', '?')})")
    print(f"  SIM State     : {sim.get('sim_state', '?')}")
    print(f"  Carrier Config: {sim.get('carrier_config', '?')}")
    print(f"  Flash Locked  : {sim.get('flash_locked', '?')}")
    print(f"  Verified Boot : {sim.get('verified_boot_state', '?')}")
    print(f"  OEM Unlock    : {sim.get('oem_unlock_supported', '?')}")
    
    lock_indicators = sim.get("carrier_lock_indicators", {})
    if any(lock_indicators.values()):
        locked_flags = [k for k, v in lock_indicators.items() if v]
        print(f"  ⚠  Lock flags : {', '.join(locked_flags)}")
    else:
        print(f"  ✓  No carrier lock indicators detected")
    
    # ── MDM ──
    print("\n  MDM / DEVICE ADMIN")
    print("  " + "─" * 50)
    if mdm.get("mdm_detected"):
        print(f"  ⚠  MDM DETECTED:")
        for pkg, name in mdm.get("device_admin_apps", {}).items():
            print(f"       {name}  ({pkg})")
        print(f"  ADB Enabled   : {mdm.get('adb_enabled', '?')}")
        print(f"  Dev Options   : {mdm.get('dev_options_enabled', '?')}")
        print()
        print("  CARRIER ADB UNLOCK ADVICE:")
        for pkg in mdm.get("device_admin_apps", {}).keys():
            if "att" in pkg or "cricket" in pkg.lower():
                print("  → AT&T: Settings → Biometrics → Device Admin Apps → disable all")
                print("    Then re-enable Developer Options, or use Wireless Debugging (Android 11+)")
            elif "tmobile" in pkg or "tmobile" in pkg.lower():
                print("  → T-Mobile: Personal phones — just enable Developer Options normally")
                print("    Business plans: contact T-Mobile IT for MDM removal")
            elif "intune" in pkg:
                print("  → Microsoft Intune: Contact your IT admin to remove MDM enrollment")
                print("    Work device: cannot bypass without admin credentials")
            elif "mobileiron" in pkg:
                print("  → MobileIron: IT admin must unenroll device remotely")
    else:
        print(f"  ✓  No MDM/Device Admin apps detected")
        print(f"  ADB Enabled   : {mdm.get('adb_enabled', '?')}")
    
    if mdm.get("knox_version"):
        print(f"  Knox Version  : {mdm.get('knox_version')}")
        if mdm.get("knox_warranty_void") == "1":
            print(f"  ⚠  Knox warranty bit is TRIPPED (kernel was modified at some point)")
    
    # ── Root ──
    print("\n  ROOT & MODIFICATION STATUS")
    print("  " + "─" * 50)
    print(f"  ADB UID       : {root.get('adb_uid', '?')}")
    print(f"  Is Root       : {'⚠  YES' if root.get('is_root') else '✓  NO (shell/user)'}")
    print(f"  Test Keys     : {'⚠  YES' if root.get('test_keys_build') else '✓  NO'}")
    print(f"  Root Detected : {'⚠  YES' if root.get('root_detected') else '✓  NO'}")
    print(f"  Magisk        : {'⚠  YES' if root.get('magisk_detected') else '✓  NO'}")
    print(f"  Frida         : {'⚠  YES' if root.get('frida_detected') else '✓  NO'}")
    
    if root.get("su_paths_found"):
        print(f"  su paths      : {list(root['su_paths_found'].keys())}")
    if root.get("magisk_paths_found"):
        print(f"  magisk paths  : {list(root['magisk_paths_found'].keys())}")
    
    # ── Security ──
    print("\n  SECURITY CONFIGURATION")
    print("  " + "─" * 50)
    print(f"  SELinux       : {sec.get('selinux_status', '?')}")
    print(f"  Encryption    : {sec.get('encryption_state', '?')} ({sec.get('encryption_type', '?')})")
    print(f"  TEE Present   : {'YES' if sec.get('tee_present') else 'NO'}")
    print(f"  StrongBox     : {sec.get('strongbox_present', 'NO')}")
    print(f"  Gatekeeper    : {'YES' if sec.get('gatekeeper_present') else 'NO'}")
    
    # ── Play Integrity ──
    print("\n  PLAY INTEGRITY ASSESSMENT")
    print("  " + "─" * 50)
    pi_score = pi.get("score", 0)
    bar = "█" * (pi_score // 10) + "░" * (10 - pi_score // 10)
    print(f"  Score: {pi_score}/100  [{bar}]  →  {pi.get('likely_tier', '?')}")
    print()
    for check, passed in pi.get("checks", {}).items():
        icon = "✓" if passed else "✗"
        print(f"  {icon}  {check.replace('_', ' ')}")
    
    if pi.get("likely_tier") == "LIKELY_FAIL":
        print()
        print("  ⚠  Device likely to FAIL Play Integrity due to:")
        if not pi.get("checks", {}).get("release_keys"):
            print("     - Build is NOT release-keys (custom ROM or modified)")
        if not pi.get("checks", {}).get("verified_boot_green"):
            print("     - Verified boot is not green (unlocked bootloader or root)")
    
    # ── Apps summary ──
    print("\n  APPLICATIONS")
    print("  " + "─" * 50)
    print(f"  User Apps     : {apps.get('user_app_count', '?')}")
    print(f"  System Apps   : {apps.get('system_app_count', '?')}")
    if apps.get("notable_apps"):
        print(f"  Notable Apps  :")
        for pkg, label in apps["notable_apps"].items():
            print(f"    • {label}  [{pkg}]")
    
    print("\n" + "═" * 70)
    print()


# ─────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Titan Real Device Analyzer — read-only")
    parser.add_argument("--device",  "-d", help="ADB target (e.g. 192.168.1.5:5555 or serial)", default=None)
    parser.add_argument("--quick",   "-q", action="store_true", help="Quick scan (skip heavy modules)")
    parser.add_argument("--output",  "-o", help="Save JSON report to file", default=None)
    parser.add_argument("--no-root-check", action="store_true", help="Skip root su path probing")
    args = parser.parse_args()
    
    print()
    print("━" * 70)
    print("  TITAN — Real Device Analyzer  (READ-ONLY)")
    print("━" * 70)
    print()
    
    # Resolve target
    target = args.device
    if not target:
        # Check saved target from connection script
        saved = "/tmp/titan_device_target.txt"
        if os.path.exists(saved):
            target = open(saved).read().strip()
            print(f"  Using saved target: {target}")
        else:
            target = find_device()
            if target:
                print(f"  Auto-detected device: {target}")
    
    if not target:
        print("  ERROR: No device connected.")
        print()
        print("  Connect first:")
        print("    bash scripts/connect_real_device.sh")
        print()
        print("  Or specify device:")
        print("    python3 scripts/analyze_real_device.py --device 192.168.1.5:5555")
        sys.exit(1)
    
    # Verify device is online
    ok, state = adb(target, "get-state")
    if not ok or state.strip() != "device":
        print(f"  ERROR: Device {target} is not in 'device' state (got: {state})")
        print("  Try: bash scripts/connect_real_device.sh")
        sys.exit(1)
    
    print(f"  Device online: {target}")
    print()
    print("  Starting scan (READ-ONLY — no changes made)...")
    print("  " + "─" * 50)
    
    t_start = time.time()
    
    # Fetch all props once (faster than individual getprop calls)
    print("  [0/16] Fetching device properties...")
    props = getprop_all(target)
    
    # Run scans
    data = {
        "scan_timestamp":           datetime.now().isoformat(),
        "scan_target":              target,
        "scan_duration_seconds":    0,
        "hardware_identity":        scan_hardware_identity(target, props),
        "build_info":               scan_build_info(target, props),
        "carrier_sim":              scan_carrier_sim(target, props),
        "mdm_policy":               scan_mdm_policy(target),
        "root_detection":           scan_root_detection(target) if not args.no_root_check else {"skipped": True},
        "security_config":          scan_security_config(target, props),
        "network":                  scan_network(target),
        "storage":                  scan_storage(target),
        "apps":                     scan_apps(target, quick=args.quick),
        "processes":                scan_processes(target),
        "accounts":                 scan_accounts(target),
        "sensors":                  scan_sensors(target),
        "battery":                  scan_battery(target),
        "bluetooth":                scan_bluetooth(target),
        "play_integrity_readiness": scan_play_integrity_readiness(target, props),
        "device_flags":             scan_device_flags(target, props),
        "raw_properties_count":     len(props),
    }
    
    data["scan_duration_seconds"] = round(time.time() - t_start, 1)
    
    # Print report
    generate_report(data, target)
    
    print(f"  Scan completed in {data['scan_duration_seconds']}s")
    print()
    
    # Save JSON
    output_path = args.output or f"/tmp/titan_device_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  Full JSON report saved: {output_path}")
    print()


if __name__ == "__main__":
    main()
