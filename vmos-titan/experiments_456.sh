#!/bin/bash
# VMOS Cloud Device Experiments - Batch 4-6 (31-60)

PAD="ACP2509244LGV1MV"
API="http://localhost:8082/api/vmos/instances/${PAD}/shell"
LOG="/tmp/vmos_experiments_b456.log"
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
  echo "[EXP-${num}] ${title}: $(echo "$OUTPUT" | head -1 | cut -c1-100)"
}

# ═══════════════════════════════════════════════════════════════
# BATCH 4: Package & App Manipulation (31-40)
# ═══════════════════════════════════════════════════════════════
echo "── BATCH 4: Package & App Manipulation ──"

run_exp 031 "Installed 3rd-party packages" \
  'pm list packages -3 2>/dev/null | wc -l; echo "---LIST---"; pm list packages -3 2>/dev/null'

run_exp 032 "Install APK from /data/local/tmp" \
  'ls -la /data/local/tmp/*.apk 2>/dev/null; pm install --help 2>&1 | head -5; echo "---PM-PATH---"; pm path com.android.chrome 2>/dev/null'

run_exp 033 "pm disable/enable system apps" \
  'pm disable com.android.browser 2>&1; pm enable com.android.browser 2>&1; pm disable-user --user 0 com.android.calculator2 2>&1; pm enable com.android.calculator2 2>&1'

run_exp 034 "Force-stop and clear app data" \
  'am force-stop com.android.chrome 2>&1; echo "---"; pm clear com.android.settings 2>&1; echo "CLEAR_DONE"'

run_exp 035 "am broadcast capabilities" \
  'am broadcast -a android.intent.action.BOOT_COMPLETED 2>&1 | head -3; echo "---"; am broadcast -a com.android.vending.INSTALL_REFERRER 2>&1 | head -3'

run_exp 036 "am start activities" \
  'am start -n com.android.settings/.Settings 2>&1 | head -3; echo "---"; am start -a android.settings.ACCESSIBILITY_SETTINGS 2>&1 | head -3'

run_exp 037 "cmd package operations" \
  'cmd package list features 2>/dev/null | head -15'

run_exp 038 "dumpsys package chrome" \
  'dumpsys package com.android.chrome 2>/dev/null | grep -iE "version|install|sign|cert|sharedUser" | head -15'

run_exp 039 "App SharedPrefs direct write" \
  'mkdir -p /data/data/com.android.chrome/shared_prefs 2>/dev/null; echo "<map><string name=\"test_key\">test_val</string></map>" > /data/data/com.android.chrome/shared_prefs/test_inject.xml 2>&1; ls -la /data/data/com.android.chrome/shared_prefs/test_inject.xml 2>/dev/null; cat /data/data/com.android.chrome/shared_prefs/test_inject.xml 2>/dev/null; rm /data/data/com.android.chrome/shared_prefs/test_inject.xml 2>/dev/null'

run_exp 040 "KeyStore & Credential storage" \
  'ls -la /data/misc/keystore/ 2>/dev/null | head -10; ls -la /data/misc/keychain/ 2>/dev/null; keystore_cli_v2 --help 2>&1 | head -5'

# ═══════════════════════════════════════════════════════════════
# BATCH 5: System Services & Binder (41-50)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 5: System Services & Binder ──"

run_exp 041 "List all system services" \
  'service list 2>/dev/null | wc -l; echo "---KEY-SERVICES---"; service list 2>/dev/null | grep -iE "account|package|telephony|wifi|bluetooth|nfc|pay|wallet|keystore|attestation|device_policy|accessibility|input" | head -20'

run_exp 042 "Service call telephony" \
  'service call iphonesubinfo 1 2>&1 | head -5; echo "---"; service call phone 1 2>&1 | head -5'

run_exp 043 "Service call SurfaceFlinger (display)" \
  'service call SurfaceFlinger 1 2>&1 | head -3; dumpsys display 2>/dev/null | grep -iE "physicalDisplay|resolution|density|uniqueId" | head -10'

run_exp 044 "Input injection capabilities" \
  'input keyevent 82 2>&1; echo "EXIT=$?"; input tap 500 500 2>&1; echo "TAP=$?"; input swipe 100 500 400 500 2>&1; echo "SWIPE=$?"; input text "hello" 2>&1; echo "TEXT=$?"'

run_exp 045 "Activity Manager state" \
  'dumpsys activity top 2>/dev/null | head -15'

run_exp 046 "Window manager info" \
  'dumpsys window displays 2>/dev/null | head -15; wm size 2>&1; wm density 2>&1'

run_exp 047 "Settings.System writable values" \
  'settings list system 2>/dev/null | head -20'

run_exp 048 "Settings.Global writable values" \
  'settings list global 2>/dev/null | grep -iE "adb|debug|install|develop|wifi|airplane|nfc|bluetooth|usb" | head -20'

run_exp 049 "Settings.Secure manipulation" \
  'settings put secure location_mode 3 2>&1; settings get secure location_mode 2>&1; echo "---"; settings put secure enabled_accessibility_services com.example/com.example.Service 2>&1; settings get secure enabled_accessibility_services 2>&1; settings put secure enabled_accessibility_services "" 2>&1'

run_exp 050 "cmd overlay list" \
  'cmd overlay list 2>/dev/null | head -20; echo "---"; cmd overlay --help 2>&1 | head -10'

# ═══════════════════════════════════════════════════════════════
# BATCH 6: Filesystem & Mount Points (51-60)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 6: Filesystem & Mounts ──"

run_exp 051 "All mount points" \
  'mount 2>/dev/null | grep -vE "loop|tmpfs|proc|sysfs|debugfs|tracefs|fuse" | head -20'

run_exp 052 "/data partition details" \
  'df -h /data 2>/dev/null; echo "---"; ls -la /data/ 2>/dev/null | head -15'

run_exp 053 "writable directories" \
  'for d in /data/local/tmp /data/data /data/system /data/misc /data/user /sdcard /storage; do touch "$d/.test_write" 2>/dev/null && echo "WRITABLE: $d" && rm "$d/.test_write" || echo "READONLY: $d"; done'

run_exp 054 "Overlay filesystem (OverlayFS)" \
  'mount | grep overlay 2>/dev/null | head -5; cat /proc/filesystems 2>/dev/null | grep overlay'

run_exp 055 "tmpfs mounts & RAM disk" \
  'mount | grep tmpfs | head -10; df -h /dev/shm 2>/dev/null; ls -la /dev/shm/ 2>/dev/null | head -5'

run_exp 056 "/proc interesting files" \
  'cat /proc/version 2>/dev/null; echo "---"; cat /proc/cmdline 2>/dev/null; echo "---MODULES---"; lsmod 2>/dev/null | head -10'

run_exp 057 "Loop device capabilities" \
  'losetup -a 2>/dev/null | head -5; echo "---"; ls /dev/loop* 2>/dev/null | head -5; echo "---MKNOD---"; mknod --help 2>&1 | head -3'

run_exp 058 "bind mount test" \
  'mkdir -p /data/local/tmp/bind_test 2>/dev/null; echo "TEST_CONTENT" > /data/local/tmp/bind_test/test.txt 2>/dev/null; mount --bind /data/local/tmp/bind_test /data/local/tmp/bind_target 2>&1; ls /data/local/tmp/bind_target/ 2>/dev/null; umount /data/local/tmp/bind_target 2>/dev/null; rm -rf /data/local/tmp/bind_test /data/local/tmp/bind_target 2>/dev/null'

run_exp 059 "Android APEX modules" \
  'ls /apex/ 2>/dev/null | head -20; echo "---COUNT---"; ls /apex/ 2>/dev/null | wc -l'

run_exp 060 "System certificates directory" \
  'ls /system/etc/security/cacerts/ 2>/dev/null | wc -l; echo "---SAMPLE---"; ls /system/etc/security/cacerts/ 2>/dev/null | head -5; echo "---USER-CERTS---"; ls /data/misc/user/0/cacerts-added/ 2>/dev/null'

echo ""
echo "── Batch 4-6 complete (31-60) ──"
