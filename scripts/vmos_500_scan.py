#!/usr/bin/env python3
"""
VMOS Cloud 500-Experiment Deep Device Scanner
=============================================
Runs 500 experiments across 25 categories on a VMOS Cloud device.
All results saved to /tmp/vmos_500_scan.json
"""
import asyncio, json, time, sys, os, secrets, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from vmos_cloud_api import VMOSCloudClient

PAD = os.environ.get("VMOS_PAD", "ACP2507296TM25XE")
RESULTS = []
EXP_NUM = [0]

async def sh(client, cmd, timeout=12):
    """Execute shell command on VMOS device with rate limiting."""
    r = await client.async_adb_cmd([PAD], cmd)
    tid = r['data'][0]['taskId']
    await asyncio.sleep(4)
    d = await client.task_detail([tid])
    return d['data'][0].get('taskResult', '') or ''

def exp(cat, name, cmd_or_result, verdict="INFO", details=""):
    """Record an experiment result."""
    EXP_NUM[0] += 1
    entry = {
        "id": EXP_NUM[0],
        "category": cat,
        "name": name,
        "result": str(cmd_or_result)[:2000],
        "verdict": verdict,
        "details": details
    }
    RESULTS.append(entry)
    v = "✅" if verdict == "PASS" else "⚠️" if verdict == "WARN" else "❌" if verdict == "FAIL" else "ℹ️"
    print(f"  [{EXP_NUM[0]:3d}] {v} {cat}/{name}: {details[:80]}", flush=True)
    return entry

async def run_exp(client, cat, name, cmd, check_fn=None):
    """Run a shell experiment and record results."""
    try:
        result = await sh(client, cmd)
        if check_fn:
            verdict, details = check_fn(result)
        else:
            verdict, details = "INFO", result.strip()[:200]
        return exp(cat, name, result, verdict, details)
    except Exception as e:
        return exp(cat, name, str(e), "ERROR", str(e)[:200])

async def main():
    print(f"╔══════════════════════════════════════════════════════════════╗", flush=True)
    print(f"║  VMOS Cloud 500-Experiment Deep Device Scanner              ║", flush=True)
    print(f"║  Target: {PAD}                              ║", flush=True)
    print(f"╚══════════════════════════════════════════════════════════════╝", flush=True)
    
    client = VMOSCloudClient()
    t0 = time.time()

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 1: KERNEL & SYSTEM IDENTITY (Experiments 1-30)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 1: KERNEL & SYSTEM IDENTITY ━━━", flush=True)
    
    await run_exp(client, "kernel", "uname", "uname -a", 
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "kernel_version", "cat /proc/version",
        lambda r: ("WARN" if "rockchip" in r.lower() else "PASS", r.strip()[:150]))
    await run_exp(client, "kernel", "cmdline", "cat /proc/cmdline 2>/dev/null || echo DENIED",
        lambda r: ("FAIL" if "cloud" in r.lower() or "vmos" in r.lower() else "PASS", r.strip()[:150]))
    await run_exp(client, "kernel", "device_tree_model", "cat /proc/device-tree/model 2>/dev/null || echo N/A",
        lambda r: ("FAIL" if "rockchip" in r.lower() or "rk3588" in r.lower() else "PASS", r.strip()))
    await run_exp(client, "kernel", "device_tree_compatible", "cat /proc/device-tree/compatible 2>/dev/null | tr '\\0' ' ' || echo N/A",
        lambda r: ("FAIL" if "rockchip" in r.lower() else "PASS", r.strip()))
    await run_exp(client, "kernel", "cpuinfo_model", "grep -i 'Hardware\\|model name\\|Processor' /proc/cpuinfo | head -5",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "cpuinfo_features", "grep Features /proc/cpuinfo | head -1",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "kernel", "cpu_freq_policy", "ls /sys/devices/system/cpu/cpufreq/ 2>/dev/null && cat /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "cpu_topology", "ls /sys/devices/system/cpu/ | grep 'cpu[0-9]' | wc -l && cat /sys/devices/system/cpu/possible 2>/dev/null",
        lambda r: ("INFO", f"cores={r.strip()}"))
    await run_exp(client, "kernel", "kernel_config", "zcat /proc/config.gz 2>/dev/null | grep -i 'CONFIG_LOCALVERSION\\|CONFIG_ANDROID\\|CONFIG_NAMESPACES' | head -5 || echo NO_CONFIG",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "kernel", "uptime", "cat /proc/uptime",
        lambda r: ("INFO", f"uptime_secs={r.split()[0] if r.strip() else '?'}"))
    await run_exp(client, "kernel", "loadavg", "cat /proc/loadavg",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "meminfo_total", "grep MemTotal /proc/meminfo",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "cgroups", "cat /proc/1/cgroup 2>/dev/null",
        lambda r: ("FAIL" if "docker" in r.lower() or "lxc" in r.lower() or len(r.strip()) > 10 else "PASS", r.strip()[:100]))
    await run_exp(client, "kernel", "mountinfo_count", "wc -l /proc/self/mountinfo",
        lambda r: ("WARN" if r.strip() and int(r.split()[0]) > 100 else "PASS", f"mounts={r.strip()}"))
    await run_exp(client, "kernel", "sched_debug", "cat /proc/sched_debug 2>/dev/null | head -5 || echo DENIED",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "kernel", "vmallocinfo", "wc -l /proc/vmallocinfo 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "kernel", "iomem_soc", "cat /proc/iomem 2>/dev/null | head -20 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "kernel", "interrupts", "head -20 /proc/interrupts 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "kernel", "dma_heap", "ls /dev/dma_heap/ 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 2: BUILD & DEVICE IDENTITY (Experiments 21-50)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 2: BUILD & DEVICE IDENTITY ━━━", flush=True)
    
    build_props = [
        "ro.build.fingerprint", "ro.build.display.id", "ro.build.version.release",
        "ro.build.version.sdk", "ro.build.version.security_patch", "ro.build.type",
        "ro.product.model", "ro.product.brand", "ro.product.name", "ro.product.device",
        "ro.product.manufacturer", "ro.product.board", "ro.hardware",
        "ro.boot.hardware", "ro.board.platform", "ro.soc.model", "ro.soc.manufacturer",
        "ro.serialno", "persist.sys.timezone", "ro.build.description",
        "ro.bootimage.build.fingerprint", "ro.vendor.build.fingerprint",
        "ro.odm.build.fingerprint", "ro.system.build.fingerprint",
        "ro.product.first_api_level", "ro.build.ab_update", "ro.build.flavor",
        "ro.build.characteristics", "ro.com.google.gmsversion",
        "gsm.version.baseband"
    ]
    for p in build_props:
        await run_exp(client, "build", p.replace("ro.",""), f"getprop {p}",
            lambda r, prop=p: ("INFO", f"{prop}={r.strip()}" if r.strip() else f"{prop}=EMPTY"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 3: ROOT & MAGISK ANALYSIS (Experiments 51-80)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 3: ROOT & MAGISK ANALYSIS ━━━", flush=True)
    
    await run_exp(client, "root", "whoami", "id",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "root", "su_binary", "which su 2>/dev/null && ls -la $(which su) || echo NO_SU",
        lambda r: ("WARN" if "/su" in r else "PASS", r.strip()))
    await run_exp(client, "root", "su_paths", "ls -la /system/bin/su /system/xbin/su /sbin/su /data/local/tmp/su /system/bin/.ext/su 2>/dev/null || echo NONE_FOUND",
        lambda r: ("WARN" if "su" in r and "NONE" not in r else "PASS", r.strip()[:150]))
    await run_exp(client, "root", "magisk_binary", "ls -la /data/adb/magisk/ 2>/dev/null && /data/adb/magisk/magisk64 -v 2>/dev/null || echo NO_MAGISK_DIR",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "root", "magisk_db", "sqlite3 /data/adb/magisk.db 'SELECT * FROM policies;' 2>/dev/null || echo NO_MAGISK_DB",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "root", "magisk_modules", "ls -la /data/adb/modules/ 2>/dev/null || echo NO_MODULES",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "root", "magisk_props", "getprop | grep -i magisk | head -10",
        lambda r: ("WARN" if r.strip() else "PASS", r.strip()[:150] if r.strip() else "No magisk props"))
    await run_exp(client, "root", "resetprop_avail", "ls -la /data/local/tmp/magisk64 /data/adb/magisk/magisk64 2>/dev/null || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "root", "zygisk_status", "ls -la /data/adb/modules/zygisksu/ /data/adb/modules/shamiko/ 2>/dev/null && cat /data/adb/modules/*/module.prop 2>/dev/null | head -20 || echo NO_ZYGISK",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "root", "lsposed_status", "ls /data/adb/lspd/ /data/adb/modules/lsposed*/ /data/adb/modules/zygisk_lsposed/ 2>/dev/null && cat /data/adb/modules/zygisk_lsposed/module.prop 2>/dev/null || echo NO_LSPOSED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "root", "frida_check", "ps -A | grep -i frida && ls /data/local/tmp/frida* 2>/dev/null || echo NO_FRIDA",
        lambda r: ("PASS" if "NO_FRIDA" in r else "WARN", r.strip()[:100]))
    await run_exp(client, "root", "xposed_check", "ls /data/data/de.robv.android.xposed.installer/ /data/data/org.meowcat.edxposed.manager/ 2>/dev/null || echo NO_XPOSED",
        lambda r: ("PASS" if "NO_XPOSED" in r else "WARN", r.strip()))
    await run_exp(client, "root", "selinux_status", "getenforce 2>/dev/null && cat /sys/fs/selinux/enforce 2>/dev/null",
        lambda r: ("PASS" if "Enforcing" in r or "1" in r else "WARN", r.strip()))
    await run_exp(client, "root", "selinux_context", "cat /proc/self/attr/current 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "root", "adb_root_shell", "getprop ro.debuggable && getprop service.adb.root",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "root", "daemonsu_check", "ps -A | grep -i daemonsu || echo NO_DAEMONSU",
        lambda r: ("PASS" if "NO_DAEMONSU" in r else "WARN", r.strip()))
    await run_exp(client, "root", "busybox_check", "which busybox 2>/dev/null && busybox --list 2>/dev/null | wc -l || echo NO_BUSYBOX",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "root", "superuser_apk", "pm list packages | grep -i superuser && pm list packages | grep -i magisk || echo NONE",
        lambda r: ("PASS" if "NONE" in r or not r.strip() else "WARN", r.strip()[:100]))
    await run_exp(client, "root", "init_rc_mods", "cat /init.rc | grep -i magisk 2>/dev/null | head -5 || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r else "WARN", r.strip()[:100]))
    await run_exp(client, "root", "proc_maps_leaks", "cat /proc/self/maps | grep -iE 'magisk|frida|xposed|substrate|riru|zygisk|lsposed' | head -10 || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r or not r.strip() else "FAIL", r.strip()[:200]))
    # Additional root experiments
    await run_exp(client, "root", "mount_namespace", "cat /proc/1/mountinfo | grep -c 'overlay\\|tmpfs' 2>/dev/null",
        lambda r: ("INFO", f"overlay_tmpfs_count={r.strip()}"))
    await run_exp(client, "root", "dev_pts", "ls /dev/pts/ 2>/dev/null | wc -l",
        lambda r: ("INFO", f"pts_count={r.strip()}"))
    await run_exp(client, "root", "selinux_deny_log", "dmesg 2>/dev/null | grep -i 'avc.*denied' | tail -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "root", "verity_status", "getprop ro.boot.veritymode && getprop ro.boot.verifiedbootstate",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "root", "vbmeta_state", "getprop ro.boot.vbmeta.device_state && getprop ro.boot.flash.locked",
        lambda r: ("INFO", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 4: FILESYSTEM & STORAGE DEEP DIVE (Experiments 81-120)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 4: FILESYSTEM & STORAGE ━━━", flush=True)
    
    await run_exp(client, "fs", "mount_types", "mount | awk '{print $5}' | sort | uniq -c | sort -rn | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "data_fs_type", "mount | grep ' /data '",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "fs", "system_fs_type", "mount | grep ' /system '",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "fs", "dm_devices", "ls /dev/block/dm-* 2>/dev/null | wc -l && dmsetup ls 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "block_devices", "ls /dev/block/ | head -30",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "loop_device_count", "ls /dev/block/loop* 2>/dev/null | wc -l",
        lambda r: ("WARN" if r.strip() and int(r.strip().split()[0] if r.strip() else "0") > 50 else "PASS", f"loop_devs={r.strip()}"))
    await run_exp(client, "fs", "nbd_device_count", "ls /sys/block/ | grep nbd | wc -l",
        lambda r: ("WARN" if r.strip() and int(r.strip()) > 0 else "PASS", f"nbd_devs={r.strip()}"))
    await run_exp(client, "fs", "data_free_space", "df -h /data | tail -1",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "sdcard_structure", "ls -la /sdcard/ | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "data_app_list", "ls /data/app/ 2>/dev/null | head -30",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "fs", "data_data_google", "ls /data/data/ | grep google | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "system_priv_app", "ls /system/priv-app/ 2>/dev/null | head -30",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "fs", "vendor_contents", "ls /vendor/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "odm_contents", "ls /odm/ 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "fs", "product_contents", "ls /product/ 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "fs", "apex_modules", "ls /apex/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "tmpfs_mounts", "mount | grep tmpfs | head -15",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "fs", "overlay_mounts", "mount | grep overlay | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "bind_mounts", "cat /proc/self/mountinfo | grep 'master:' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "fstab_contents", "cat /vendor/etc/fstab.* 2>/dev/null | head -20 || cat /fstab.* 2>/dev/null | head -20 || echo NONE",
        lambda r: ("INFO", r.strip()[:300]))
    # Deeper FS analysis
    await run_exp(client, "fs", "encryption_status", "getprop ro.crypto.state && getprop ro.crypto.type",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "fbe_status", "getprop ro.crypto.volume.filenames_mode",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "system_rw_test", "touch /system/test_rw 2>&1; echo EXIT=$?; rm /system/test_rw 2>/dev/null",
        lambda r: ("PASS" if "EXIT=1" in r or "Read-only" in r else "WARN", r.strip()[:100]))
    await run_exp(client, "fs", "data_writable", "touch /data/local/tmp/test_wr 2>&1 && echo WRITABLE && rm /data/local/tmp/test_wr || echo NOT_WRITABLE",
        lambda r: ("PASS" if "WRITABLE" in r else "FAIL", r.strip()))
    await run_exp(client, "fs", "selinux_contexts_apps", "ls -Z /data/data/ | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "dev_special_dirs", "ls /dev/.sc 2>/dev/null || echo NOT_EXIST",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "proc_mounts_vmos", "cat /proc/mounts | grep -iE 'cloud|vmos|armcloud' | head -5 || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r or not r.strip() else "FAIL", r.strip()[:150]))
    await run_exp(client, "fs", "data_adb_structure", "ls -la /data/adb/ 2>/dev/null || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "init_environ", "cat /init.environ.rc 2>/dev/null | head -10 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "sepolicy_size", "ls -la /sys/fs/selinux/policy 2>/dev/null || echo DENIED",
        lambda r: ("INFO", r.strip()))
    # More FS
    await run_exp(client, "fs", "thermal_zones", "ls /sys/class/thermal/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "power_supply", "ls /sys/class/power_supply/ 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "usb_state", "cat /sys/class/android_usb/android0/state 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "disk_stats", "cat /proc/diskstats | head -10 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "partition_table", "cat /proc/partitions | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "fs", "uevent_platform", "cat /sys/devices/platform/*/uevent 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "fs", "linkerconfig", "cat /linkerconfig/ld.config.txt 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "fs", "property_contexts", "wc -l /system/etc/selinux/*contexts 2>/dev/null | tail -1",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "fs", "magisk_overlay", "mount | grep '/sbin\\|/debug_ramdisk' | head -5 || echo NONE",
        lambda r: ("PASS" if "NONE" in r or not r.strip() else "WARN", r.strip()[:100]))
    await run_exp(client, "fs", "recovery_partition", "ls /dev/block/by-name/recovery 2>/dev/null && file /dev/block/by-name/recovery || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 5: NETWORK & CONNECTIVITY (Experiments 121-160)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 5: NETWORK & CONNECTIVITY ━━━", flush=True)
    
    await run_exp(client, "net", "interfaces", "ip addr show | grep -E 'inet |link/' | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "net", "eth0_check", "ip addr show eth0 2>/dev/null | head -5 || echo NO_ETH0",
        lambda r: ("FAIL" if "eth0" in r and "NO_ETH0" not in r else "PASS", r.strip()[:100]))
    await run_exp(client, "net", "wlan0_check", "ip addr show wlan0 2>/dev/null | head -5 || echo NO_WLAN0",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "veth_detection", "ip link | grep -i 'veth\\|@if' | head -5 || echo NONE",
        lambda r: ("FAIL" if "veth" in r.lower() or "@if" in r else "PASS", r.strip()[:100]))
    await run_exp(client, "net", "bridge_detection", "brctl show 2>/dev/null || ip link show type bridge 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "dns_config", "cat /etc/resolv.conf 2>/dev/null || getprop net.dns1",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "netstat_listen", "netstat -tlnp 2>/dev/null | head -20 || ss -tlnp 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "net", "iptables_rules", "iptables -L -n 2>/dev/null | head -30",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "net", "ip6tables_rules", "ip6tables -L -n 2>/dev/null | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "routing_table", "ip route | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "arp_table", "ip neigh show | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "wifi_info", "dumpsys wifi | grep -i 'Wi-Fi\\|SSID\\|BSSID\\|frequency' | head -10 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "telephony_info", "dumpsys telephony.registry | grep -i 'mcc\\|mnc\\|operator\\|state' | head -10 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "connectivity_type", "dumpsys connectivity | grep 'NetworkAgentInfo\\|type' | head -10 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "vpn_status", "dumpsys connectivity | grep -i vpn | head -5 2>/dev/null || echo NO_VPN",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "proxy_settings", "settings get global http_proxy 2>/dev/null && settings get global global_http_proxy_host 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "mac_address", "cat /sys/class/net/*/address 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "netd_status", "getprop init.svc.netd",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "firewall_chains", "iptables -L -n -t nat 2>/dev/null | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "socket_stats", "cat /proc/net/tcp | wc -l && cat /proc/net/udp | wc -l",
        lambda r: ("INFO", r.strip()))
    # Deeper network
    await run_exp(client, "net", "webrtc_ports", "netstat -tlnp 2>/dev/null | grep -E '23333|23334' || echo NO_WEBRTC_LISTENING",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "rtcgesture_status", "pm list packages com.cloud.rtcgesture 2>/dev/null && dumpsys package com.cloud.rtcgesture 2>/dev/null | grep 'enabled\\|state' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "net", "cloud_service_ports", "netstat -tlnp 2>/dev/null | grep -E 'cloudservice|xu_daemon' | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "qemud_pipes", "ls /dev/qemu_pipe /dev/goldfish_pipe /dev/virtio-ports/* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "net", "tun_tap_devices", "ls /dev/tun /dev/net/tun 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "nf_conntrack", "cat /proc/sys/net/nf_conntrack_max 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "ip_forward", "cat /proc/sys/net/ipv4/ip_forward",
        lambda r: ("INFO", f"ip_forward={r.strip()}"))
    await run_exp(client, "net", "cell_tower_info", "dumpsys telephony.registry 2>/dev/null | grep -i 'cellIdentity\\|lac\\|cid\\|mcc\\|mnc' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "sim_state", "getprop gsm.sim.state && getprop gsm.sim.operator.alpha",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "data_state", "dumpsys telephony.registry 2>/dev/null | grep mDataConnectionState | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    # More network experiments
    await run_exp(client, "net", "bluetooth_state", "dumpsys bluetooth_manager 2>/dev/null | grep -i 'state\\|address\\|name' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "nfc_state", "dumpsys nfc 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "net", "wifi_p2p", "dumpsys wifip2p 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "net", "network_policies", "dumpsys netpolicy 2>/dev/null | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "net", "dns_tls", "getprop net.dns.tls 2>/dev/null && settings get global private_dns_mode 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "captive_portal", "settings get global captive_portal_mode 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "airplane_mode", "settings get global airplane_mode_on 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "mobile_data", "settings get global mobile_data 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "net", "wifi_scan_results", "dumpsys wifi 2>/dev/null | grep 'Scan Results' -A 5 | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "net", "netlink_sockets", "cat /proc/net/netlink | wc -l",
        lambda r: ("INFO", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 6: PROCESSES & SERVICES (Experiments 161-200)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 6: PROCESSES & SERVICES ━━━", flush=True)
    
    await run_exp(client, "proc", "process_count", "ps -A | wc -l",
        lambda r: ("INFO", f"total_processes={r.strip()}"))
    await run_exp(client, "proc", "vmos_processes", "ps -A | grep -iE 'cloud|vmos|xu_daemon|rtcgesture|expansion' | head -15",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "proc", "google_processes", "ps -A | grep -i google | head -15",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "proc", "system_server", "ps -A | grep system_server",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "zygote", "ps -A | grep zygote",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "proc", "init_services", "getprop | grep 'init.svc.' | grep -v stopped | head -20",
        lambda r: ("INFO", r.strip()[:400]))
    await run_exp(client, "proc", "running_services", "dumpsys activity services 2>/dev/null | grep 'ServiceRecord' | wc -l",
        lambda r: ("INFO", f"running_services={r.strip()}"))
    await run_exp(client, "proc", "xu_daemon_detail", "ps -A -o PID,PPID,USER,NAME | grep xu_daemon",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "cloudservice_detail", "ps -A -o PID,PPID,USER,NAME | grep cloudservice",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "surfaceflinger", "ps -A | grep surfaceflinger",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "hwservicemanager", "ps -A | grep -i hwservicemanager",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "servicemanager", "ps -A | grep servicemanager | head -3",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "proc", "logd", "ps -A | grep logd",
        lambda r: ("INFO", r.strip()))
    # Security processes
    await run_exp(client, "proc", "security_procs", "ps -A | grep -iE 'keystore|gatekeeper|confirmationui|weaver' | head -5",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "proc", "hal_services", "ps -A | grep -i 'android.hardware' | wc -l",
        lambda r: ("INFO", f"hal_count={r.strip()}"))
    await run_exp(client, "proc", "hal_list", "ps -A | grep -i 'android.hardware' | head -20",
        lambda r: ("INFO", r.strip()[:400]))
    await run_exp(client, "proc", "vold", "ps -A | grep vold",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "installd", "ps -A | grep installd",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "adbd", "ps -A | grep adbd",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "healthd", "ps -A | grep -i health",
        lambda r: ("INFO", r.strip()[:100]))
    # Deeper process analysis
    await run_exp(client, "proc", "cmdline_scan_leaks", "for p in $(ls /proc/ | grep -E '^[0-9]+$' | head -50); do cat /proc/$p/cmdline 2>/dev/null | tr '\\0' ' ' | grep -iE 'cloud|vmos|armcloud' && echo PID=$p; done || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r or not r.strip() else "FAIL", r.strip()[:200]))
    await run_exp(client, "proc", "comm_scan", "for p in $(ls /proc/ | grep -E '^[0-9]+$' | head -80); do name=$(cat /proc/$p/comm 2>/dev/null); echo \"$p:$name\"; done | grep -ivE '^[0-9]+:$' | head -30",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "proc", "app_processes", "ps -A -o PID,USER,NAME | grep u0_ | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "proc", "cgroup_hierarchy", "cat /proc/1/cgroup",
        lambda r: ("FAIL" if len(r.strip()) > 10 and r.strip() != "0::/" else "PASS", r.strip()[:100]))
    await run_exp(client, "proc", "namespace_info", "ls -la /proc/1/ns/ 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "proc", "capabilities", "cat /proc/self/status | grep -i cap | head -5",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "proc", "oom_scores", "for p in system_server surfaceflinger zygote64; do pid=$(pidof $p 2>/dev/null); echo \"$p($pid): $(cat /proc/$pid/oom_score 2>/dev/null)\"; done",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "proc", "scheduled_tasks", "dumpsys alarm 2>/dev/null | grep -c 'Batch'",
        lambda r: ("INFO", f"alarm_batches={r.strip()}"))
    await run_exp(client, "proc", "binder_stats", "cat /proc/binder/stats 2>/dev/null | head -10 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "proc", "lmk_stats", "cat /proc/lowmemorykiller/stats 2>/dev/null || getprop ro.lmk.use_minfree_levels",
        lambda r: ("INFO", r.strip()[:100]))
    # More proc
    await run_exp(client, "proc", "android_runtime", "ps -A | grep -c app_process",
        lambda r: ("INFO", f"app_process_count={r.strip()}"))
    await run_exp(client, "proc", "mediaserver", "ps -A | grep -i mediaserver",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "proc", "camera_service", "ps -A | grep -i camera | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "proc", "audio_service", "ps -A | grep -i audioserver",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "sensor_service", "ps -A | grep -i sensorservice",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "proc", "gpu_process", "ps -A | grep -iE 'gpu|mali|adreno' | head -5",
        lambda r: ("INFO", r.strip()[:100] if r.strip() else "No GPU process"))
    await run_exp(client, "proc", "tombstones", "ls /data/tombstones/ 2>/dev/null | wc -l || echo 0",
        lambda r: ("INFO", f"tombstones={r.strip()}"))
    await run_exp(client, "proc", "anr_traces", "ls /data/anr/ 2>/dev/null | wc -l || echo 0",
        lambda r: ("INFO", f"anr_traces={r.strip()}"))
    await run_exp(client, "proc", "logcat_errors", "logcat -d -b crash 2>/dev/null | tail -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "proc", "property_service", "ps -A | grep property_service || echo NOT_VISIBLE",
        lambda r: ("INFO", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 7: GPU & GRAPHICS (Experiments 201-225)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 7: GPU & GRAPHICS ━━━", flush=True)
    
    await run_exp(client, "gpu", "gl_renderer", "dumpsys SurfaceFlinger 2>/dev/null | grep -i 'GLES\\|renderer\\|vendor' | head -5",
        lambda r: ("FAIL" if "mali" in r.lower() else "PASS", r.strip()[:150]))
    await run_exp(client, "gpu", "gpu_driver", "ls /vendor/lib64/egl/ 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "gpu", "gpu_info_props", "getprop ro.hardware.egl && getprop ro.hardware.vulkan && getprop ro.opengles.version",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "gpu_freq", "cat /sys/class/devfreq/*/cur_freq 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "gpu_governor", "cat /sys/class/devfreq/*/governor 2>/dev/null | head -3",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "display_info", "dumpsys display 2>/dev/null | grep -i 'mPhysicalDisplayInfo\\|density\\|resolution\\|refresh' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "gpu", "hwc_info", "dumpsys SurfaceFlinger 2>/dev/null | grep -i 'composer\\|HWC' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "gpu", "vulkan_info", "ls /vendor/lib64/hw/vulkan.* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "render_props", "getprop debug.hwui.renderer && getprop ro.hwui.use_vulkan",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "gralloc_version", "ls /vendor/lib64/hw/gralloc.* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "framebuffer", "ls /dev/fb* /dev/graphics/* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "drm_devices", "ls /dev/dri/ 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "screen_density", "wm density 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "screen_size", "wm size 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "screen_brightness", "settings get system screen_brightness 2>/dev/null",
        lambda r: ("INFO", f"brightness={r.strip()}"))
    await run_exp(client, "gpu", "overlay_count", "dumpsys SurfaceFlinger 2>/dev/null | grep -c 'Layer\\|Surface' | head -1",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "gpu", "refresh_rate", "dumpsys SurfaceFlinger 2>/dev/null | grep -i 'refresh\\|fps' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "gpu", "hdr_caps", "dumpsys SurfaceFlinger 2>/dev/null | grep -i hdr | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "color_mode", "dumpsys display 2>/dev/null | grep -i 'color mode' | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "dpu_info", "cat /sys/class/graphics/fb0/msm_fb_panel_info 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    # Extra GPU
    await run_exp(client, "gpu", "renderthread", "ps -A | grep RenderThread | wc -l",
        lambda r: ("INFO", f"render_threads={r.strip()}"))
    await run_exp(client, "gpu", "sf_stats", "dumpsys SurfaceFlinger --latency 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "gpu_memory", "cat /sys/kernel/gpu/mem 2>/dev/null || dumpsys gpu 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "hw_overlay_status", "dumpsys SurfaceFlinger 2>/dev/null | grep 'hw\\-overlays' | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "gpu", "gpu_utilization", "cat /sys/class/devfreq/*/load 2>/dev/null | head -3 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 8: SENSORS & HARDWARE (Experiments 226-260)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 8: SENSORS & HARDWARE ━━━", flush=True)
    
    await run_exp(client, "sensor", "sensor_list", "dumpsys sensorservice 2>/dev/null | grep -E '^[0-9]+\\)' | head -25",
        lambda r: ("INFO", r.strip()[:400]))
    await run_exp(client, "sensor", "sensor_count", "dumpsys sensorservice 2>/dev/null | grep -c '^[0-9]\\+)'",
        lambda r: ("INFO", f"sensor_count={r.strip()}"))
    await run_exp(client, "sensor", "accelerometer", "dumpsys sensorservice 2>/dev/null | grep -i accel | head -3",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "gyroscope", "dumpsys sensorservice 2>/dev/null | grep -i gyro | head -3",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "magnetometer", "dumpsys sensorservice 2>/dev/null | grep -i magnet | head -3",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "proximity", "dumpsys sensorservice 2>/dev/null | grep -i prox | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "light_sensor", "dumpsys sensorservice 2>/dev/null | grep -i light | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "barometer", "dumpsys sensorservice 2>/dev/null | grep -i baro\\|pressure | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "gravity", "dumpsys sensorservice 2>/dev/null | grep -i gravity | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "step_counter", "dumpsys sensorservice 2>/dev/null | grep -i step | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "fingerprint_hw", "dumpsys fingerprint 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "camera_list", "dumpsys media.camera 2>/dev/null | grep -i 'camera id\\|facing' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "sensor", "battery_info", "dumpsys battery 2>/dev/null | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "sensor", "input_devices", "dumpsys input 2>/dev/null | grep -i 'input device\\|name:' | head -15",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "sensor", "vibrator", "dumpsys vibrator 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "usb_devices", "lsusb 2>/dev/null || echo NO_LSUSB",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "thermal_info", "dumpsys thermalservice 2>/dev/null | head -15",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "sensor", "cpu_temp", "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo NONE",
        lambda r: ("INFO", f"cpu_temp={r.strip()}"))
    await run_exp(client, "sensor", "hw_binder_list", "ls /dev/hwbinder 2>/dev/null && dumpsys -l 2>/dev/null | grep -i sensor | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "iio_devices", "ls /sys/bus/iio/devices/ 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    # Extra sensor tests
    await run_exp(client, "sensor", "sensor_hal", "ps -A | grep -i sensors | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "sensor_vendor", "dumpsys sensorservice 2>/dev/null | grep -i vendor | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "rotation_vector", "dumpsys sensorservice 2>/dev/null | grep -i rotation | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "significant_motion", "dumpsys sensorservice 2>/dev/null | grep -i significant | head -2",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "heart_rate", "dumpsys sensorservice 2>/dev/null | grep -i heart | head -2 || echo NONE",
        lambda r: ("INFO", r.strip()[:80]))
    await run_exp(client, "sensor", "device_orientation", "dumpsys sensorservice 2>/dev/null | grep -i orientation | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "gps_provider", "dumpsys location 2>/dev/null | grep -i 'providers\\|gps\\|fused' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "sensor", "gnss_info", "dumpsys location 2>/dev/null | grep -i gnss | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "nfc_hardware", "dumpsys nfc 2>/dev/null | grep -i 'hardware\\|chip\\|firmware\\|enabled' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "sensor", "ir_blaster", "ls /dev/lirc* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    # More sensors  
    await run_exp(client, "sensor", "game_rotation", "dumpsys sensorservice 2>/dev/null | grep -i 'game rotation' | head -2",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "geomagnetic", "dumpsys sensorservice 2>/dev/null | grep -i geomagnetic | head -2",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "uncalibrated", "dumpsys sensorservice 2>/dev/null | grep -i uncalibrated | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "sensor", "tilt_detector", "dumpsys sensorservice 2>/dev/null | grep -i tilt | head -2",
        lambda r: ("INFO", r.strip()[:80]))
    await run_exp(client, "sensor", "wakeup_sensors", "dumpsys sensorservice 2>/dev/null | grep -i wakeup | wc -l",
        lambda r: ("INFO", f"wakeup_sensors={r.strip()}"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 9: APPS & PACKAGES (Experiments 261-300)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 9: APPS & PACKAGES ━━━", flush=True)
    
    await run_exp(client, "apps", "user_app_count", "pm list packages -3 | wc -l",
        lambda r: ("INFO", f"user_apps={r.strip()}"))
    await run_exp(client, "apps", "system_app_count", "pm list packages -s | wc -l",
        lambda r: ("INFO", f"system_apps={r.strip()}"))
    await run_exp(client, "apps", "user_apps_list", "pm list packages -3",
        lambda r: ("INFO", r.strip()[:500]))
    await run_exp(client, "apps", "google_apps", "pm list packages | grep google",
        lambda r: ("INFO", r.strip()[:400]))
    await run_exp(client, "apps", "vmos_apps", "pm list packages | grep -iE 'cloud|vmos|expansion'",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "play_store_version", "dumpsys package com.android.vending 2>/dev/null | grep versionName | head -1",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "gms_version", "dumpsys package com.google.android.gms 2>/dev/null | grep versionName | head -1",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "chrome_version", "dumpsys package com.android.chrome 2>/dev/null | grep versionName | head -1 || echo NOT_INSTALLED",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "webview_provider", "dumpsys webviewupdate 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "apps", "default_launcher", "dumpsys package resolvers 2>/dev/null | grep -i 'launcher\\|home' | head -5",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "accessibility_services", "settings get secure enabled_accessibility_services 2>/dev/null",
        lambda r: ("PASS" if not r.strip() or r.strip() == "null" else "WARN", r.strip()[:100]))
    await run_exp(client, "apps", "device_admin", "dumpsys device_policy 2>/dev/null | grep -i 'admin\\|DeviceOwner' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "apps", "play_protect", "dumpsys package com.google.android.gms 2>/dev/null | grep -i 'safetynet\\|play.protect\\|integrity' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "apps", "install_sources", "pm list packages -i 2>/dev/null | grep -v 'com.android.shell' | grep -v 'null' | head -15 || echo NONE",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "apps", "disabled_packages", "pm list packages -d 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "permission_grants", "dumpsys package com.google.android.gms 2>/dev/null | grep 'granted=true' | wc -l",
        lambda r: ("INFO", f"gms_permissions={r.strip()}"))
    await run_exp(client, "apps", "overlay_packages", "cmd overlay list 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "shared_uid_apps", "pm list packages -U 2>/dev/null | grep 'uid:1000' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "apk_signatures", "pm dump com.google.android.gms 2>/dev/null | grep -i 'signature\\|cert' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "apps", "first_install_times", "dumpsys package com.android.chrome 2>/dev/null | grep -i 'firstInstall\\|lastUpdate' | head -2",
        lambda r: ("INFO", r.strip()[:100]))
    # Deeper app analysis
    await run_exp(client, "apps", "running_apps", "dumpsys activity activities 2>/dev/null | grep 'Run #' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "recent_tasks", "dumpsys activity recents 2>/dev/null | grep 'Recent #' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "foreground_app", "dumpsys activity activities 2>/dev/null | grep 'mResumedActivity' | head -1",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "apps", "backup_transports", "dumpsys backup 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "apps", "content_providers", "dumpsys content 2>/dev/null | grep 'Provider' | wc -l",
        lambda r: ("INFO", f"providers={r.strip()}"))
    await run_exp(client, "apps", "broadcast_receivers", "dumpsys package com.google.android.gms 2>/dev/null | grep -c 'receiver'",
        lambda r: ("INFO", f"gms_receivers={r.strip()}"))
    await run_exp(client, "apps", "work_profile", "pm list users 2>/dev/null",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "apps", "shared_prefs_gms", "ls /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null | wc -l",
        lambda r: ("INFO", f"gms_prefs_count={r.strip()}"))
    await run_exp(client, "apps", "databases_gms", "ls /data/data/com.google.android.gms/databases/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "apps", "fintech_apps", "pm list packages | grep -iE 'klarna|affirm|afterpay|cashapp|venmo|paypal|wise|chime|privacy|google.pay|wallet' || echo NONE",
        lambda r: ("INFO", r.strip()[:300]))
    # More apps
    await run_exp(client, "apps", "banking_apps", "pm list packages | grep -iE 'chase|bofa|wellsfargo|citi|amex|capitalone|discover|usbank' || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "social_apps", "pm list packages | grep -iE 'tiktok|instagram|facebook|twitter|whatsapp|telegram|snapchat' || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "usagestats_data", "ls -la /data/system/usagestats/0/daily/ 2>/dev/null | tail -5 || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "notification_policy", "dumpsys notification 2>/dev/null | grep -i 'Policy\\|Channel' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "apps", "app_ops_settings", "appops get com.google.android.gms 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "apps", "package_verifier", "settings get global verifier_verify_adb_installs 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "unknown_sources", "settings get secure install_non_market_apps 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "kiwi_browser", "pm list packages com.kiwibrowser.browser 2>/dev/null || echo NOT_INSTALLED",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "apps", "webview_implementation", "dumpsys webviewupdate 2>/dev/null | grep 'Current WebView' | head -1",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "apps", "intent_filters", "dumpsys package domain-preferred-apps 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 10: GOOGLE ACCOUNTS & AUTH STATE (Experiments 301-330)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 10: GOOGLE ACCOUNTS & AUTH ━━━", flush=True)
    
    await run_exp(client, "auth", "account_count", "dumpsys account | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "auth", "accounts_ce_schema", "sqlite3 /data/system_ce/0/accounts_ce.db '.schema' 2>/dev/null | head -20 || echo NO_DB",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "auth", "accounts_ce_data", "sqlite3 /data/system_ce/0/accounts_ce.db 'SELECT * FROM accounts;' 2>/dev/null || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "accounts_de_schema", "sqlite3 /data/system_de/0/accounts_de.db '.schema' 2>/dev/null | head -20 || echo NO_DB",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "auth", "accounts_de_data", "sqlite3 /data/system_de/0/accounts_de.db 'SELECT * FROM accounts;' 2>/dev/null || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "accounts_ce_extras", "sqlite3 /data/system_ce/0/accounts_ce.db 'SELECT * FROM extras;' 2>/dev/null | head -10 || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "accounts_ce_tokens", "sqlite3 /data/system_ce/0/accounts_ce.db 'SELECT accounts_id, type FROM authtokens;' 2>/dev/null | head -10 || echo EMPTY",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "accounts_ce_version", "sqlite3 /data/system_ce/0/accounts_ce.db 'PRAGMA user_version;' 2>/dev/null || echo UNKNOWN",
        lambda r: ("INFO", f"ce_user_version={r.strip()}"))
    await run_exp(client, "auth", "accounts_de_version", "sqlite3 /data/system_de/0/accounts_de.db 'PRAGMA user_version;' 2>/dev/null || echo UNKNOWN",
        lambda r: ("INFO", f"de_user_version={r.strip()}"))
    await run_exp(client, "auth", "accounts_ce_perms", "ls -la /data/system_ce/0/accounts_ce.db 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "auth", "accounts_de_perms", "ls -la /data/system_de/0/accounts_de.db 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "auth", "gms_checkin", "cat /data/data/com.google.android.gms/shared_prefs/CheckinService.xml 2>/dev/null | head -15 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "gsf_gservices", "cat /data/data/com.google.android.gsf/shared_prefs/gservices.xml 2>/dev/null | head -15 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "finsky_prefs", "cat /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null | head -15 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "chrome_prefs", "cat /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "gmail_prefs", "ls /data/data/com.google.android.gm/shared_prefs/ 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "auth", "youtube_prefs", "ls /data/data/com.google.android.youtube/shared_prefs/ 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "auth", "maps_prefs", "ls /data/data/com.google.android.apps.maps/shared_prefs/ 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "auth", "gms_device_reg", "cat /data/data/com.google.android.gms/shared_prefs/device_registration.xml 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "google_login_svc", "pm list packages com.google.android.gsf.login",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "auth", "account_manager_svc", "dumpsys account 2>/dev/null | grep -i 'AccountType' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    # More auth
    await run_exp(client, "auth", "phenotype_db", "sqlite3 /data/data/com.google.android.gms/databases/phenotype.db 'SELECT name FROM sqlite_master WHERE type=\"table\";' 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "gms_config_db", "sqlite3 /data/data/com.google.android.gms/databases/config.db 'SELECT name FROM sqlite_master WHERE type=\"table\";' 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "coin_xml", "cat /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null | head -15 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "auth", "tapandpay_db", "sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db '.tables' 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "auth", "wallet_db", "sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db '.tables' 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "auth", "gsf_id", "sqlite3 /data/data/com.google.android.gsf/databases/gservices.db 'SELECT value FROM main WHERE name=\"android_id\";' 2>/dev/null || echo NONE",
        lambda r: ("INFO", f"gsf_id={r.strip()}"))
    await run_exp(client, "auth", "android_id", "settings get secure android_id 2>/dev/null",
        lambda r: ("INFO", f"android_id={r.strip()}"))
    await run_exp(client, "auth", "gaid", "cat /data/data/com.google.android.gms/shared_prefs/adid_settings.xml 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "auth", "play_integrity_module", "pm list packages com.google.android.play.integrity 2>/dev/null || echo NOT_INSTALLED",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "auth", "safetynet_attestation", "pm list packages com.google.android.safetynet 2>/dev/null || echo NOT_INSTALLED",
        lambda r: ("INFO", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 11: EMULATOR & CONTAINER DETECTION (Experiments 331-370)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 11: EMULATOR & CONTAINER DETECTION ━━━", flush=True)
    
    await run_exp(client, "detect", "qemu_props", "getprop | grep -iE 'qemu|goldfish|ranchu|generic' | head -10",
        lambda r: ("PASS" if not r.strip() else "FAIL", r.strip()[:200] if r.strip() else "No emulator props"))
    await run_exp(client, "detect", "vmos_props", "getprop | grep -iE 'cloud|vmos|armcloud' | head -10",
        lambda r: ("PASS" if not r.strip() else "FAIL", r.strip()[:200] if r.strip() else "No VMOS props"))
    await run_exp(client, "detect", "init_svc_vmos", "getprop | grep 'init.svc.' | grep -iE 'cloud|vmos|xu_daemon' | head -10",
        lambda r: ("FAIL" if r.strip() else "PASS", r.strip()[:150] if r.strip() else "Clean"))
    await run_exp(client, "detect", "ro_hardware", "getprop ro.hardware",
        lambda r: ("WARN" if "rk3588" in r.lower() or "rockchip" in r.lower() else "PASS", r.strip()))
    await run_exp(client, "detect", "ro_boot_hardware", "getprop ro.boot.hardware",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "fingerprint_coherence", "getprop ro.build.fingerprint && getprop ro.bootimage.build.fingerprint",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "detect", "build_type", "getprop ro.build.type",
        lambda r: ("PASS" if r.strip() == "user" else "FAIL", f"build_type={r.strip()}"))
    await run_exp(client, "detect", "debuggable", "getprop ro.debuggable",
        lambda r: ("PASS" if r.strip() == "0" else "FAIL", f"debuggable={r.strip()}"))
    await run_exp(client, "detect", "secure", "getprop ro.secure",
        lambda r: ("PASS" if r.strip() == "1" else "WARN", f"secure={r.strip()}"))
    await run_exp(client, "detect", "mock_location", "settings get secure mock_location 2>/dev/null",
        lambda r: ("PASS" if r.strip() == "0" or not r.strip() else "FAIL", f"mock_location={r.strip()}"))
    await run_exp(client, "detect", "dev_settings", "settings get global development_settings_enabled 2>/dev/null",
        lambda r: ("INFO", f"dev_settings={r.strip()}"))
    await run_exp(client, "detect", "usb_debugging", "settings get global adb_enabled 2>/dev/null",
        lambda r: ("WARN" if r.strip() == "1" else "PASS", f"adb_enabled={r.strip()}"))
    await run_exp(client, "detect", "stay_awake", "settings get global stay_on_while_plugged_in 2>/dev/null",
        lambda r: ("INFO", f"stay_awake={r.strip()}"))
    await run_exp(client, "detect", "proc_cmdline_leaks", "cat /proc/cmdline 2>/dev/null | tr ' ' '\\n' | grep -iE 'cloud|vmos|qemu|goldfish|virtual|cuttlefish|vsoc' || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r else "FAIL", r.strip()[:150]))
    await run_exp(client, "detect", "proc_mounts_leaks", "cat /proc/mounts | grep -iE 'cloud|vmos|armcloud|qemu' | head -5 || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r or not r.strip() else "FAIL", r.strip()[:150]))
    await run_exp(client, "detect", "dev_files", "ls /dev/qemu_pipe /dev/goldfish_pipe /dev/socket/qemud 2>/dev/null || echo CLEAN",
        lambda r: ("PASS" if "CLEAN" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "detect", "sysfs_board", "cat /sys/class/dmi/id/board_name 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "sysfs_product", "cat /sys/class/dmi/id/product_name 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "cpuinfo_model_check", "grep -i 'Hardware' /proc/cpuinfo",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "detect", "boot_reason", "getprop sys.boot.reason",
        lambda r: ("INFO", r.strip()))
    # Additional detection vectors
    await run_exp(client, "detect", "serial_number", "getprop ro.serialno && getprop ro.boot.serialno",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "telephony_sim", "getprop gsm.sim.state && getprop gsm.operator.alpha && getprop gsm.sim.operator.numeric",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "imei_check", "service call iphonesubinfo 1 2>/dev/null | head -3",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "detect", "wifi_mac_format", "cat /sys/class/net/wlan0/address 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "bluetooth_mac", "settings get secure bluetooth_address 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "drm_id", "cat /proc/sys/kernel/random/boot_id 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "gettimeofday_check", "date +%s%N",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "timezone_check", "getprop persist.sys.timezone && date +%Z",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "locale_check", "getprop persist.sys.locale && getprop persist.sys.language && getprop persist.sys.country",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "detect", "packages_xml_size", "ls -la /data/system/packages.xml 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    # More detection
    await run_exp(client, "detect", "lsmod_output", "lsmod 2>/dev/null | head -20 || echo NONE",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "detect", "kernel_modules", "cat /proc/modules | head -15 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "detect", "selinux_leak_fix", "lsmod 2>/dev/null | grep selinux_leak || echo NOT_LOADED",
        lambda r: ("WARN" if "selinux_leak" in r else "PASS", r.strip()[:100]))
    await run_exp(client, "detect", "vmos_app_data", "ls /data/data/com.cloud.rtcgesture/ /data/data/com.android.expansiontools/ 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "detect", "expansion_tools_state", "pm dump com.android.expansiontools 2>/dev/null | grep -i 'enabled\\|state' | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "detect", "persist_cloud_props", "getprop | grep persist.cloud | head -10",
        lambda r: ("FAIL" if r.strip() else "PASS", r.strip()[:200] if r.strip() else "No persist.cloud props"))
    await run_exp(client, "detect", "persist_sys_cloud", "getprop | grep 'persist.sys.cloud' | head -10",
        lambda r: ("FAIL" if r.strip() else "PASS", r.strip()[:200] if r.strip() else "No persist.sys.cloud props"))
    await run_exp(client, "detect", "sys_class_misc", "ls /sys/class/misc/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "detect", "vendor_props", "getprop | grep 'ro.vendor.' | head -15",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "detect", "board_platform", "getprop ro.board.platform",
        lambda r: ("WARN" if "rk3588" in r.lower() else "PASS", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 12: SECURITY & ATTESTATION (Experiments 371-400)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 12: SECURITY & ATTESTATION ━━━", flush=True)
    
    await run_exp(client, "security", "keystore_service", "dumpsys android.security.keystore2 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "security", "keymaster_hal", "ps -A | grep -i keymaster | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "gatekeeper_hal", "ps -A | grep -i gatekeeper | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "strongbox", "getprop ro.hardware.strongbox",
        lambda r: ("INFO", r.strip() if r.strip() else "NO_STRONGBOX"))
    await run_exp(client, "security", "tee_type", "getprop ro.hardware.keystore",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "verified_boot", "getprop ro.boot.verifiedbootstate",
        lambda r: ("PASS" if r.strip() == "green" else "FAIL", f"vb_state={r.strip()}"))
    await run_exp(client, "security", "flash_locked", "getprop ro.boot.flash.locked",
        lambda r: ("PASS" if r.strip() == "1" else "FAIL", f"flash_locked={r.strip()}"))
    await run_exp(client, "security", "vbmeta_device_state", "getprop ro.boot.vbmeta.device_state",
        lambda r: ("PASS" if r.strip() == "locked" else "FAIL", f"vbmeta={r.strip()}"))
    await run_exp(client, "security", "dm_verity", "getprop ro.boot.veritymode",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "encryption_state", "getprop ro.crypto.state",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "keybox_files", "ls /data/adb/keybox/ /data/local/tmp/keybox* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "knox_status", "getprop ro.boot.warranty_bit && getprop ro.warranty_bit 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "safetynet_key", "cat /data/data/com.google.android.gms/shared_prefs/SafetyNet.xml 2>/dev/null | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "se_patch_level", "getprop ro.build.version.security_patch",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "boot_hash", "getprop ro.boot.vbmeta.digest",
        lambda r: ("INFO", r.strip()[:80]))
    await run_exp(client, "security", "secure_element", "getprop ro.hardware.secure_element",
        lambda r: ("INFO", r.strip() if r.strip() else "NONE"))
    await run_exp(client, "security", "trusty_os", "ls /dev/trusty* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "tpm_device", "ls /dev/tpm* 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "lockscreen_type", "dumpsys lock_settings 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "security", "screen_lock", "settings get secure lockscreen.disabled 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    # More security
    await run_exp(client, "security", "selinux_policy_version", "cat /sys/fs/selinux/policyvers 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "selinux_booleans", "ls /sys/fs/selinux/booleans/ 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "security", "credential_storage", "ls /data/misc/keystore/ 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "security", "cert_store", "ls /system/etc/security/cacerts/ 2>/dev/null | wc -l",
        lambda r: ("INFO", f"ca_certs={r.strip()}"))
    await run_exp(client, "security", "user_certs", "ls /data/misc/user/0/cacerts-added/ 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "biometric_enrolled", "dumpsys fingerprint 2>/dev/null | grep -i enrolled | head -3 || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "security", "device_id_attestation", "getprop ro.device_id_attestation_supported",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "patch_level_vendor", "getprop ro.vendor.build.security_patch",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "oem_unlock", "getprop sys.oem_unlock_allowed",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "security", "fde_algorithm", "getprop ro.crypto.fde_algorithm 2>/dev/null",
        lambda r: ("INFO", r.strip() if r.strip() else "N/A"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 13: INJECTION SURFACE TESTING (Experiments 401-440)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 13: INJECTION SURFACES ━━━", flush=True)
    
    await run_exp(client, "inject", "data_local_tmp_write", "echo TEST > /data/local/tmp/inject_test && cat /data/local/tmp/inject_test && rm /data/local/tmp/inject_test",
        lambda r: ("PASS" if "TEST" in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "tmpfs_mount_test", "mkdir -p /dev/.titan_test && mount -t tmpfs tmpfs /dev/.titan_test && echo MOUNTED && ls /dev/.titan_test && umount /dev/.titan_test && rmdir /dev/.titan_test",
        lambda r: ("PASS" if "MOUNTED" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "inject", "sqlite3_avail", "which sqlite3 && sqlite3 --version",
        lambda r: ("PASS" if "sqlite3" in r.lower() or "3." in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "content_provider_insert", "content query --uri content://contacts/phones 2>/dev/null | head -3 || echo DENIED",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "resetprop_binary", "ls -la /data/local/tmp/magisk64 /data/adb/magisk/magisk64 /system/bin/resetprop 2>/dev/null || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "resetprop_test", "RP=$(which resetprop 2>/dev/null || echo /data/adb/magisk/magisk64); $RP ro.test.prop 2>/dev/null && echo WORKS || echo NO_RESETPROP",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "bind_mount_test", "echo STERILE > /dev/.titan_bm_test && mount --bind /dev/.titan_bm_test /proc/version 2>&1; cat /proc/version | head -1; umount /proc/version 2>/dev/null; rm /dev/.titan_bm_test 2>/dev/null",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "iptables_test", "iptables -L INPUT -n 2>/dev/null | head -5 && echo IPTABLES_OK",
        lambda r: ("PASS" if "IPTABLES_OK" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "inject", "setprop_test", "setprop test.titan.scan 'working' && getprop test.titan.scan && setprop test.titan.scan ''",
        lambda r: ("PASS" if "working" in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "gms_shared_prefs_write", "mkdir -p /data/data/com.google.android.gms/shared_prefs && echo '<map/>' > /data/data/com.google.android.gms/shared_prefs/titan_test.xml && ls -la /data/data/com.google.android.gms/shared_prefs/titan_test.xml && rm /data/data/com.google.android.gms/shared_prefs/titan_test.xml",
        lambda r: ("PASS" if "titan_test" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "inject", "contacts_db_path", "find /data/data/com.android.providers.contacts -name 'contacts*.db' 2>/dev/null | head -5 || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "telephony_db_path", "find /data/data/com.android.providers.telephony -name '*.db' 2>/dev/null | head -5 || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "calllog_db_path", "find /data/data/com.android.providers.calllogbackup -name '*.db' 2>/dev/null; find /data/data/com.android.providers.contacts -name 'calllog.db' 2>/dev/null || echo SEARCHING",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "chrome_data_paths", "ls /data/data/com.android.chrome/app_chrome/Default/ 2>/dev/null | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "inject", "chrome_history_db", "sqlite3 /data/data/com.android.chrome/app_chrome/Default/History '.tables' 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "chrome_cookies_db", "sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies '.tables' 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "chrome_webdata_db", "sqlite3 /data/data/com.android.chrome/app_chrome/Default/'Web Data' '.tables' 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "wifi_config_path", "find /data/misc/apexdata/com.android.wifi -name '*.xml' 2>/dev/null; ls /data/misc/wifi/*.conf 2>/dev/null || echo SEARCHING",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "inject", "usagestats_path", "ls /data/system/usagestats/0/ 2>/dev/null",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "usagestats_writable", "ls -la /data/system/usagestats/0/daily/ 2>/dev/null | tail -3 || echo NONE",
        lambda r: ("INFO", r.strip()[:150]))
    # Gallery/media
    await run_exp(client, "inject", "dcim_path", "ls /sdcard/DCIM/ 2>/dev/null || echo EMPTY",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "media_store_db", "find /data/data/com.google.android.providers.media* -name '*.db' 2>/dev/null | head -5 || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "inject", "external_db", "find /data/data/com.android.providers.media -name 'external.db' 2>/dev/null || echo NOT_FOUND",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "downloads_dir", "ls /sdcard/Download/ 2>/dev/null | head -5 || echo EMPTY",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "app_data_ownership", "stat -c '%u:%g %n' /data/data/com.google.android.gms /data/data/com.android.vending /data/data/com.android.chrome 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "inject", "restorecon_test", "restorecon /data/local/tmp 2>&1 && echo WORKS",
        lambda r: ("PASS" if "WORKS" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "inject", "chown_test", "touch /data/local/tmp/ch_test; chown system:system /data/local/tmp/ch_test 2>&1 && ls -la /data/local/tmp/ch_test && rm /data/local/tmp/ch_test",
        lambda r: ("PASS" if "system" in r else "FAIL", r.strip()[:100]))
    await run_exp(client, "inject", "am_start_test", "am start -a android.intent.action.VIEW -d 'http://localhost' 2>&1 | head -3",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "pm_install_test", "pm install --help 2>/dev/null | head -3 || echo NO_PM",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "settings_put_test", "settings put system titan_test_setting 1 2>&1 && settings get system titan_test_setting && settings delete system titan_test_setting 2>/dev/null",
        lambda r: ("PASS" if "1" in r else "FAIL", r.strip()))
    # Deeper injection
    await run_exp(client, "inject", "proc_cmdline_bindmount", "echo 'STERILE' > /dev/.sc_test 2>/dev/null && mount --bind /dev/.sc_test /proc/cmdline 2>&1; cat /proc/cmdline | head -1; umount /proc/cmdline 2>/dev/null; rm /dev/.sc_test 2>/dev/null",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "proc_mounts_bindmount", "cat /proc/mounts | grep -v cloud > /dev/.mounts_test 2>/dev/null; mount --bind /dev/.mounts_test /proc/mounts 2>&1 | head -1; umount /proc/mounts 2>/dev/null; rm /dev/.mounts_test 2>/dev/null; echo TEST_DONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "cgroup_bindmount", "echo '0::/' > /dev/.cg_test && mount --bind /dev/.cg_test /proc/1/cgroup 2>&1 | head -1 && cat /proc/1/cgroup; umount /proc/1/cgroup 2>/dev/null; rm /dev/.cg_test 2>/dev/null",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "inject", "comm_rename", "echo 'init' > /proc/self/comm 2>&1 && cat /proc/self/comm; echo 'sh' > /proc/self/comm 2>/dev/null",
        lambda r: ("PASS" if "init" in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "rmmod_test", "lsmod | head -5; rmmod selinux_leak_fix 2>&1 || echo RMMOD_ATTEMPTED",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "inject", "force_stop_test", "am force-stop com.android.chrome 2>&1 && echo STOPPED",
        lambda r: ("PASS" if "STOPPED" in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "appops_set_test", "appops set com.google.android.gms RUN_IN_BACKGROUND deny 2>&1 && echo SET; appops set com.google.android.gms RUN_IN_BACKGROUND allow 2>/dev/null",
        lambda r: ("PASS" if "SET" in r else "FAIL", r.strip()[:80]))
    await run_exp(client, "inject", "nfc_settings", "settings get secure nfc_on 2>/dev/null && settings get secure nfc_payment_foreground 2>/dev/null",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "inject", "input_tap_test", "input tap 100 100 2>&1 && echo TAP_OK",
        lambda r: ("PASS" if "TAP_OK" in r else "FAIL", r.strip()))
    await run_exp(client, "inject", "input_text_test", "input text 'test' 2>&1 && echo TEXT_OK",
        lambda r: ("PASS" if "TEXT_OK" in r else "FAIL", r.strip()))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 14: VMOS-SPECIFIC INTERNALS (Experiments 441-480)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 14: VMOS-SPECIFIC INTERNALS ━━━", flush=True)
    
    await run_exp(client, "vmos", "cloudservice_pid", "pidof cloudservice 2>/dev/null && cat /proc/$(pidof cloudservice)/cmdline 2>/dev/null | tr '\\0' ' '",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "xu_daemon_pid", "pidof xu_daemon 2>/dev/null && cat /proc/$(pidof xu_daemon)/cmdline 2>/dev/null | tr '\\0' ' '",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "rtcgesture_state", "dumpsys package com.cloud.rtcgesture 2>/dev/null | grep -iE 'versionName|enabled|state' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "expansion_state", "dumpsys package com.android.expansiontools 2>/dev/null | grep -iE 'versionName|enabled|state' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "pipe_qemud", "ls -la /dev/socket/qemud /dev/qemu_pipe 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "vmos", "cloud_gps_props", "getprop | grep -i 'persist.cloud.gps\\|persist.sys.cloud.gps' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "cloud_all_props", "getprop | grep -i '\\.cloud\\.' | head -20",
        lambda r: ("INFO", r.strip()[:400]))
    await run_exp(client, "vmos", "init_svc_cloud", "getprop | grep 'init.svc.' | grep -iE 'cloud|xu|rtc' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "vmos_kernel_modules", "lsmod 2>/dev/null",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "vmos", "vmos_mount_overlay", "mount | grep -iE 'cloud|vmos|overlay' | head -10",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "expansion_tools_data", "ls /data/data/com.android.expansiontools/ 2>/dev/null | head -10",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "cloud_config_files", "find /data -name '*cloud*' -o -name '*vmos*' 2>/dev/null | grep -v 'proc\\|cache' | head -20",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "vmos", "cbs_process", "ps -A | grep cbs",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "vmos", "webrtc_sockets", "netstat -tlnp 2>/dev/null | grep -E '2333[34]' | head -5",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "vmos", "device_mapper_detail", "dmsetup table 2>/dev/null | head -10 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "system_dm_status", "dmsetup status 2>/dev/null | head -10 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "namespace_pids", "ls -la /proc/1/ns/ 2>/dev/null",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "container_env", "cat /proc/1/environ 2>/dev/null | tr '\\0' '\\n' | head -10 || echo DENIED",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "veth_details", "ip -d link show eth0 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "hostname", "hostname && cat /etc/hostname 2>/dev/null || echo NONE",
        lambda r: ("INFO", r.strip()))
    # More VMOS internals
    await run_exp(client, "vmos", "xu_daemon_caps", "cat /proc/$(pidof xu_daemon 2>/dev/null)/status 2>/dev/null | grep -i cap | head -5 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "cloudservice_files", "ls /system/bin/cloudservice /system/bin/xu_daemon 2>/dev/null",
        lambda r: ("INFO", r.strip()[:100]))
    await run_exp(client, "vmos", "cloud_socket_dir", "ls /dev/socket/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "selinux_leak_module", "cat /proc/modules 2>/dev/null | grep selinux",
        lambda r: ("WARN" if r.strip() else "PASS", r.strip()[:100] if r.strip() else "No selinux module"))
    await run_exp(client, "vmos", "magisk_state_prop", "getprop init.svc.magisk_service",
        lambda r: ("INFO", r.strip() if r.strip() else "not set"))
    await run_exp(client, "vmos", "cloud_daemon_sockets", "ls -la /dev/socket/ 2>/dev/null | grep -iE 'cloud|xu|qemud' | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "proc_version_detail", "cat /proc/version",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "system_apps_cloud", "pm list packages -s | grep -iE 'cloud|vmos|expansion|rtcgesture'",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "data_misc_contents", "ls /data/misc/ 2>/dev/null | head -20",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "vmos", "dev_block_by_name", "ls /dev/block/by-name/ 2>/dev/null | head -20 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    # Final VMOS
    await run_exp(client, "vmos", "rootfs_type", "stat -f / 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "sysfs_block_count", "ls /sys/block/ | wc -l",
        lambda r: ("WARN" if r.strip() and int(r.strip()) > 50 else "PASS", f"block_devs={r.strip()}"))
    await run_exp(client, "vmos", "loopback_mounts", "mount | grep 'loop' | wc -l",
        lambda r: ("INFO", f"loop_mounts={r.strip()}"))
    await run_exp(client, "vmos", "emulated_storage", "mount | grep '/storage/emulated'",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "vmos", "data_dalvik_cache", "ls /data/dalvik-cache/ 2>/dev/null | head -5",
        lambda r: ("INFO", r.strip()[:100]))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 15: ADVANCED STEALTH TESTS (Experiments 481-500)
    # ═══════════════════════════════════════════════════════════════════
    print("\n━━━ SECTION 15: ADVANCED STEALTH TESTS ━━━", flush=True)
    
    await run_exp(client, "stealth", "all_ro_build_props", "getprop | grep 'ro\\.build\\.' | wc -l",
        lambda r: ("INFO", f"ro.build_prop_count={r.strip()}"))
    await run_exp(client, "stealth", "prop_fingerprint_match", "FP=$(getprop ro.build.fingerprint); BFP=$(getprop ro.bootimage.build.fingerprint); VFP=$(getprop ro.vendor.build.fingerprint); echo \"build=$FP\"; echo \"boot=$BFP\"; echo \"vendor=$VFP\"; [ \"$FP\" = \"$BFP\" ] && echo MATCH || echo MISMATCH",
        lambda r: ("PASS" if "MATCH" in r and "MISMATCH" not in r else "WARN", r.strip()[:200]))
    await run_exp(client, "stealth", "board_soc_coherence", "echo Board=$(getprop ro.product.board); echo Platform=$(getprop ro.board.platform); echo SoC=$(getprop ro.soc.model); echo Hardware=$(getprop ro.hardware)",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "stealth", "gpu_vs_claimed", "GPU=$(dumpsys SurfaceFlinger 2>/dev/null | grep -i 'GLES.*:' | head -1); MODEL=$(getprop ro.product.model); echo \"GPU: $GPU\"; echo \"Model: $MODEL\"",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "stealth", "cpu_freq_vs_claimed", "MAX=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq 2>/dev/null); echo \"Max CPU freq: $MAX Hz\"; echo \"Claimed SoC: $(getprop ro.soc.model)\"",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "stealth", "battery_realistic", "dumpsys battery 2>/dev/null | grep -i 'level\\|status\\|plugged\\|temperature'",
        lambda r: ("INFO", r.strip()[:150]))
    await run_exp(client, "stealth", "time_zone_coherence", "TZ=$(getprop persist.sys.timezone); LOCALE=$(getprop persist.sys.locale); echo \"TZ=$TZ LOCALE=$LOCALE\"",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "stealth", "total_prop_count", "getprop | wc -l",
        lambda r: ("INFO", f"total_props={r.strip()}"))
    await run_exp(client, "stealth", "suspicious_prop_scan", "getprop | grep -iE 'virtual|emulat|qemu|goldfish|cuttlefish|vsoc|generic|cloud|vmos|armcloud|ranchu|genymotion|bluestacks|nox|memu' | head -15",
        lambda r: ("PASS" if not r.strip() else "FAIL", r.strip()[:300] if r.strip() else "No suspicious props"))
    await run_exp(client, "stealth", "system_server_uptime", "ps -p $(pidof system_server) -o etime= 2>/dev/null || echo UNKNOWN",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "stealth", "wifi_scan_count", "dumpsys wifi 2>/dev/null | grep -c 'SSID' 2>/dev/null",
        lambda r: ("INFO", f"wifi_ssid_count={r.strip()}"))
    await run_exp(client, "stealth", "contacts_count", "content query --uri content://contacts/phones 2>/dev/null | wc -l || echo 0",
        lambda r: ("INFO", f"contacts={r.strip()}"))
    await run_exp(client, "stealth", "sms_count", "content query --uri content://sms 2>/dev/null | wc -l || echo 0",
        lambda r: ("INFO", f"sms={r.strip()}"))
    await run_exp(client, "stealth", "call_log_count", "content query --uri content://call_log/calls 2>/dev/null | wc -l || echo 0",
        lambda r: ("INFO", f"calls={r.strip()}"))
    await run_exp(client, "stealth", "chrome_history_count", "sqlite3 /data/data/com.android.chrome/app_chrome/Default/History 'SELECT COUNT(*) FROM urls;' 2>/dev/null || echo 0",
        lambda r: ("INFO", f"chrome_history={r.strip()}"))
    await run_exp(client, "stealth", "installed_app_ages", "for pkg in com.android.chrome com.google.android.gms com.android.vending; do echo \"$pkg: $(dumpsys package $pkg 2>/dev/null | grep firstInstallTime | head -1)\"; done",
        lambda r: ("INFO", r.strip()[:300]))
    await run_exp(client, "stealth", "build_time", "getprop ro.build.date.utc",
        lambda r: ("INFO", r.strip()))
    await run_exp(client, "stealth", "full_detection_summary", "echo '=== Detection Summary ==='; echo 'QEMU:'; getprop | grep -ic qemu; echo 'VMOS:'; getprop | grep -ic vmos; echo 'Cloud:'; getprop | grep -ic cloud; echo 'Emulator:'; getprop | grep -ic emulat; echo 'Rockchip:'; getprop | grep -ic rockchip",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "stealth", "env_variables", "env | grep -ivE 'PATH|HOME|SHELL|USER|LOGNAME|TERM|ANDROID|BOOTCLASSPATH' | head -10 || echo NONE",
        lambda r: ("INFO", r.strip()[:200]))
    await run_exp(client, "stealth", "final_trust_markers", "echo ACCOUNTS=$(dumpsys account | grep 'Accounts:' | head -1); echo CONTACTS=$(content query --uri content://contacts/phones 2>/dev/null | wc -l); echo APPS=$(pm list packages -3 | wc -l); echo UPTIME=$(cat /proc/uptime | cut -d' ' -f1)",
        lambda r: ("INFO", r.strip()[:200]))

    # ═══════════════════════════════════════════════════════════════════
    # SAVE RESULTS
    # ═══════════════════════════════════════════════════════════════════
    elapsed = time.time() - t0
    summary = {
        "total_experiments": EXP_NUM[0],
        "elapsed_seconds": round(elapsed, 1),
        "device": PAD,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "categories": {},
        "verdicts": {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0, "ERROR": 0},
        "experiments": RESULTS
    }
    for r in RESULTS:
        cat = r["category"]
        v = r["verdict"]
        summary["verdicts"][v] = summary["verdicts"].get(v, 0) + 1
        if cat not in summary["categories"]:
            summary["categories"][cat] = {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0, "ERROR": 0, "total": 0}
        summary["categories"][cat][v] = summary["categories"][cat].get(v, 0) + 1
        summary["categories"][cat]["total"] += 1

    out_path = "/tmp/vmos_500_scan.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'='*60}", flush=True)
    print(f"  SCAN COMPLETE: {EXP_NUM[0]} experiments in {elapsed:.0f}s", flush=True)
    print(f"  Results: {out_path}", flush=True)
    print(f"  PASS={summary['verdicts']['PASS']} FAIL={summary['verdicts']['FAIL']} WARN={summary['verdicts']['WARN']} INFO={summary['verdicts']['INFO']} ERROR={summary['verdicts']['ERROR']}", flush=True)
    print(f"{'='*60}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
