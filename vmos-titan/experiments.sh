#!/bin/bash
# VMOS Cloud Device Experiment Runner
# Sends shell commands via the HTTP API and logs results

PAD="ACP2509244LGV1MV"
API="http://localhost:8082/api/vmos/instances/${PAD}/shell"
LOG="/tmp/vmos_experiments.log"
> "$LOG"

run_exp() {
  local num="$1"
  local title="$2"
  local cmd="$3"
  
  echo "=== EXP-${num}: ${title} ===" >> "$LOG"
  RESULT=$(curl -s -X POST "$API" \
    -H 'Content-Type: application/json' \
    -d "{\"command\": $(echo "$cmd" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))')}" 2>/dev/null)
  OUTPUT=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('output','ERROR: '+str(d)))" 2>/dev/null)
  echo "$OUTPUT" >> "$LOG"
  echo "" >> "$LOG"
  echo "[EXP-${num}] ${title}: $(echo "$OUTPUT" | head -1 | cut -c1-80)"
}

echo "Starting VMOS Cloud Experiments on device ${PAD}..."
echo "Log file: ${LOG}"
echo ""

# ═══════════════════════════════════════════════════════════════
# BATCH 1: Root / su / Shell Capabilities (1-10)
# ═══════════════════════════════════════════════════════════════
echo "── BATCH 1: Root / su / Shell ──"

run_exp 001 "Who am I (uid/gid)" \
  'id; whoami 2>/dev/null; echo "SHELL=$SHELL"'

run_exp 002 "su binary location & capabilities" \
  'which su 2>/dev/null; ls -la $(which su 2>/dev/null) 2>/dev/null; su -c id 2>&1; su 0 id 2>&1; su root id 2>&1'

run_exp 003 "Available shells" \
  'ls -la /system/bin/sh /system/bin/bash /system/xbin/bash /data/local/tmp/bash /system/bin/mksh 2>/dev/null; cat /etc/shells 2>/dev/null'

run_exp 004 "Toybox/busybox capabilities" \
  'toybox --help 2>&1 | head -5; echo "---TOYBOX-CMDS---"; toybox 2>&1 | tr " " "\n" | wc -l; echo "---BUSYBOX---"; which busybox 2>/dev/null; busybox --list 2>/dev/null | head -5'

run_exp 005 "Superuser apps installed" \
  'pm list packages 2>/dev/null | grep -iE "supersu|magisk|superuser|kingu|kingoroot|oneclick|kingroot|topjohnwu|phh" || echo "NONE"'

run_exp 006 "Root filesystem writable?" \
  'mount | grep " / " | head -1; touch /system/test_write 2>&1; rm /system/test_write 2>/dev/null; echo "---"; mount -o remount,rw / 2>&1; touch /system/test_write2 2>&1; rm /system/test_write2 2>/dev/null'

run_exp 007 "/system mount status" \
  'mount | grep /system; ls -la /system/xbin/ 2>/dev/null | head -10'

run_exp 008 "Process capabilities (capget)" \
  'cat /proc/self/status | grep -iE "Cap|Uid|Gid|Seccomp|NoNewPrivs"'

run_exp 009 "nsenter / unshare available?" \
  'which nsenter 2>/dev/null; which unshare 2>/dev/null; nsenter --help 2>&1 | head -3; unshare --help 2>&1 | head -3'

run_exp 010 "setuid binaries on device" \
  'find /system /vendor -perm -4000 -type f 2>/dev/null | head -20'

# ═══════════════════════════════════════════════════════════════
# BATCH 2: Frida / Hooking Frameworks (11-20)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 2: Frida / Hooking ──"

run_exp 011 "Frida server on device" \
  'which frida-server 2>/dev/null; ls -la /data/local/tmp/frida* 2>/dev/null; ps -A 2>/dev/null | grep -i frida; find / -name "frida*" -type f 2>/dev/null | head -10'

run_exp 012 "ptrace capabilities" \
  'cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null; echo "---"; strace -p 1 -c 2>&1 | head -5'

run_exp 013 "Xposed/LSposed/EdXposed presence" \
  'pm list packages 2>/dev/null | grep -iE "xposed|lsposed|edxposed|riru|zygisk"; ls -la /data/adb/modules/ 2>/dev/null; ls -la /data/adb/lspd/ 2>/dev/null'

run_exp 014 "Magisk modules dir & zygisk" \
  'ls -la /data/adb/ 2>/dev/null; ls -la /data/adb/modules/ 2>/dev/null; ls -la /data/adb/magisk/ 2>/dev/null; getprop persist.sys.safemode 2>/dev/null'

run_exp 015 "/proc/self/maps - loaded libraries" \
  'cat /proc/self/maps 2>/dev/null | grep -iE "frida|xposed|substrate|inject|hook" | head -10; echo "---ALL_LIBS---"; cat /proc/self/maps | grep "\.so" | awk "{print \$NF}" | sort -u | tail -20'

run_exp 016 "LD_PRELOAD injection test" \
  'echo $LD_PRELOAD; echo "---"; ls /system/lib64/lib*.so 2>/dev/null | head -10; LD_PRELOAD=/system/lib64/liblog.so id 2>&1'

run_exp 017 "Debuggable apps" \
  'pm list packages -3 2>/dev/null | head -10; echo "---"; for pkg in com.android.chrome com.google.android.gms com.android.vending; do echo "$pkg: $(run-as $pkg id 2>&1)"; done'

run_exp 018 "JDWP (Java Debug) ports" \
  'cat /proc/net/tcp 2>/dev/null | head -5; echo "---"; getprop ro.debuggable; getprop dalvik.vm.jdwp.enabled 2>/dev/null'

run_exp 019 "Android Debug Bridge status" \
  'getprop service.adb.root; getprop persist.adb.tcp.port; getprop service.adb.tcp.port; getprop ro.adb.secure; getprop sys.usb.config'

run_exp 020 "Dalvik/ART vm properties" \
  'getprop | grep -iE "dalvik|art|dex2oat|jit" | head -15'

# ═══════════════════════════════════════════════════════════════
# BATCH 3: Permission & SELinux (21-30)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 3: Permissions & SELinux ──"

run_exp 021 "SELinux status & mode" \
  'getenforce 2>/dev/null; cat /sys/fs/selinux/enforce 2>/dev/null; sestatus 2>/dev/null; ls -la /sys/fs/selinux/ 2>/dev/null | head -5'

run_exp 022 "SELinux context of current process" \
  'cat /proc/self/attr/current 2>/dev/null; echo "---"; id -Z 2>/dev/null; ps -AZ 2>/dev/null | head -5'

run_exp 023 "Can we set SELinux permissive?" \
  'setenforce 0 2>&1; getenforce 2>/dev/null; setenforce 1 2>&1; getenforce 2>/dev/null'

run_exp 024 "sepolicy / security contexts" \
  'ls -la /sepolicy /vendor/etc/selinux/ /system/etc/selinux/ 2>/dev/null | head -10; cat /sys/fs/selinux/context 2>/dev/null | head -5'

run_exp 025 "Android permissions list" \
  'pm list permissions -g -d 2>/dev/null | head -30'

run_exp 026 "Grant runtime permissions programmatically" \
  'pm grant com.android.chrome android.permission.CAMERA 2>&1; pm grant com.android.chrome android.permission.READ_CONTACTS 2>&1; pm grant com.android.chrome android.permission.ACCESS_FINE_LOCATION 2>&1; echo "---"; dumpsys package com.android.chrome 2>/dev/null | grep "android.permission.CAMERA" | head -2'

run_exp 027 "Device admin & device owner" \
  'dpm list-owners 2>&1; dumpsys device_policy 2>/dev/null | head -10'

run_exp 028 "AppOps (permission manager)" \
  'appops get com.android.chrome 2>/dev/null | head -15; echo "---CAMERA---"; appops set com.android.chrome CAMERA allow 2>&1'

run_exp 029 "Package installer permissions" \
  'pm list packages -i 2>/dev/null | head -10; echo "---"; settings get secure install_non_market_apps 2>/dev/null; settings get global verifier_verify_adb_installs 2>/dev/null'

run_exp 030 "Profile/user management" \
  'pm list users 2>&1; pm get-max-users 2>&1; pm create-user test_profile 2>&1'

echo ""
echo "── Batch 1-3 complete (30/100) ──"
echo ""
