#!/bin/bash
# VMOS Cloud Device Experiments - Batch 7-10 (61-100)

PAD="ACP2509244LGV1MV"
API="http://localhost:8082/api/vmos/instances/${PAD}/shell"
LOG="/tmp/vmos_experiments_b7890.log"
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
# BATCH 7: Network & Crypto (61-70)
# ═══════════════════════════════════════════════════════════════
echo "── BATCH 7: Network & Crypto ──"

run_exp 061 "Network interfaces & IP" \
  'ip addr show 2>/dev/null | grep -E "inet |link/ether|state" | head -15'

run_exp 062 "iptables rules" \
  'iptables -L -n 2>/dev/null | head -20; echo "---NAT---"; iptables -t nat -L -n 2>/dev/null | head -10'

run_exp 063 "DNS configuration" \
  'getprop net.dns1 2>/dev/null; getprop net.dns2 2>/dev/null; cat /etc/resolv.conf 2>/dev/null; nslookup google.com 2>&1 | head -5'

run_exp 064 "Outbound connectivity test" \
  'curl -sI https://www.google.com 2>&1 | head -5; echo "---"; ping -c 1 -W 3 8.8.8.8 2>&1 | head -3'

run_exp 065 "Open TCP/UDP ports" \
  'cat /proc/net/tcp 2>/dev/null | wc -l; echo "---TCP---"; cat /proc/net/tcp 2>/dev/null | awk "NR>1{print \$2}" | head -10; echo "---UDP---"; cat /proc/net/udp 2>/dev/null | awk "NR>1{print \$2}" | head -10'

run_exp 066 "VPN/Tunnel interfaces" \
  'ip tunnel show 2>&1; ip link show type wireguard 2>&1; ls /dev/tun 2>/dev/null; cat /dev/net/tun 2>&1 | head -1'

run_exp 067 "SSL/TLS certificate inspection" \
  'openssl version 2>/dev/null; echo "---"; ls /system/etc/security/cacerts/ 2>/dev/null | wc -l; echo "---USER-CA---"; ls /data/misc/user/0/cacerts-added/ 2>/dev/null | wc -l'

run_exp 068 "Network security config" \
  'cat /data/data/com.android.chrome/res/xml/network_security_config.xml 2>/dev/null; echo "---"; find /data/data/com.android.chrome/ -name "network_security*" 2>/dev/null'

run_exp 069 "Proxy settings" \
  'settings get global http_proxy 2>/dev/null; settings get global global_http_proxy_host 2>/dev/null; getprop http.proxyHost 2>/dev/null; getprop http.proxyPort 2>/dev/null'

run_exp 070 "NFC capabilities" \
  'dumpsys nfc 2>/dev/null | head -20; echo "---"; settings get secure nfc_payment_default_component 2>/dev/null'

# ═══════════════════════════════════════════════════════════════
# BATCH 8: Content Providers & DBs (71-80)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 8: Content Providers & DBs ──"

run_exp 071 "All content providers" \
  'dumpsys package providers 2>/dev/null | grep -iE "ContentProvider|authority=" | head -30'

run_exp 072 "Direct DB access - all .db files" \
  'find /data/data /data/system /data/system_ce /data/system_de -name "*.db" -type f 2>/dev/null | wc -l; echo "---TOP-DBs---"; find /data/data /data/system -name "*.db" -type f 2>/dev/null | head -30'

run_exp 073 "Telephony provider DB" \
  'ls -la /data/user_de/0/com.android.providers.telephony/databases/ 2>/dev/null; echo "---"; ls -la /data/data/com.android.providers.telephony/databases/ 2>/dev/null'

run_exp 074 "Settings provider DB" \
  'ls -la /data/system/users/0/settings_* 2>/dev/null; echo "---"; ls -la /data/data/com.android.providers.settings/databases/ 2>/dev/null'

run_exp 075 "GMS databases listing" \
  'ls -la /data/data/com.google.android.gms/databases/ 2>/dev/null | head -20'

run_exp 076 "Account Manager DB direct" \
  'ls -la /data/system_ce/0/accounts_ce.db* 2>/dev/null; echo "---"; ls -la /data/system_de/0/accounts_de.db* 2>/dev/null'

run_exp 077 "Content query - settings.global" \
  'content query --uri content://settings/global --projection name:value 2>/dev/null | grep -iE "device_name|bluetooth_name|wifi" | head -10'

run_exp 078 "Google Play Services version & state" \
  'dumpsys package com.google.android.gms 2>/dev/null | grep -iE "versionCode|versionName|firstInstall|lastUpdate" | head -5'

run_exp 079 "Play Store databases" \
  'ls -la /data/data/com.android.vending/databases/ 2>/dev/null | head -15'

run_exp 080 "SharedPrefs directory listing" \
  'ls -la /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null | wc -l; echo "---TOP---"; ls -la /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null | tail -20'

# ═══════════════════════════════════════════════════════════════
# BATCH 9: Kernel & Hardware Identity (81-90)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 9: Kernel & Hardware ──"

run_exp 081 "Kernel version & build" \
  'uname -a 2>/dev/null; echo "---"; cat /proc/version 2>/dev/null'

run_exp 082 "CPU info" \
  'cat /proc/cpuinfo 2>/dev/null | grep -iE "processor|model|hardware|features|cpu part" | head -15'

run_exp 083 "Memory info" \
  'cat /proc/meminfo 2>/dev/null | head -10'

run_exp 084 "Build properties (all dangerous)" \
  'getprop | grep -iE "ro\.build\.|ro\.product\.|ro\.hardware\.|ro\.board\.|ro\.bootimage\." | head -30'

run_exp 085 "VMOS-specific properties" \
  'getprop | grep -iE "vmos|vmware|virtual|qemu|goldfish|emulator|genymotion|bluestacks|nox" | head -20'

run_exp 086 "Verify boot state" \
  'getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getprop ro.boot.warranty_bit; getprop ro.boot.vbmeta.device_state; getprop vendor.boot.vbmeta.device_state 2>/dev/null; getprop ro.boot.veritymode'

run_exp 087 "Hardware attestation keybox" \
  'ls -la /data/adb/ 2>/dev/null; ls -la /vendor/etc/keybox*.* 2>/dev/null; ls -la /system/etc/security/keybox*.* 2>/dev/null; getprop persist.titan.keybox.loaded 2>/dev/null; getprop ro.hardware.keystore 2>/dev/null'

run_exp 088 "GPU & display info" \
  'getprop ro.hardware.egl 2>/dev/null; getprop ro.hardware.vulkan 2>/dev/null; dumpsys SurfaceFlinger 2>/dev/null | grep -iE "GPU|driver|vendor|version" | head -10'

run_exp 089 "Sensor information" \
  'dumpsys sensorservice 2>/dev/null | grep -iE "handle|name|vendor|type" | head -20'

run_exp 090 "Bluetooth identity" \
  'dumpsys bluetooth_manager 2>/dev/null | grep -iE "address|name|state|mode" | head -10; settings get secure bluetooth_name 2>/dev/null; settings get secure bluetooth_address 2>/dev/null'

# ═══════════════════════════════════════════════════════════════
# BATCH 10: Advanced Genesis Techniques (91-100)
# ═══════════════════════════════════════════════════════════════
echo ""
echo "── BATCH 10: Advanced Genesis Techniques ──"

run_exp 091 "SafetyNet/Play Integrity properties" \
  'getprop | grep -iE "safetynet|integrity|cts|profile|attestation" | head -15; echo "---"; dumpsys attestation_verification 2>/dev/null | head -15'

run_exp 092 "dex2oat injection (pre-compiled code)" \
  'which dex2oat 2>/dev/null; ls -la /apex/com.android.art/bin/dex2oat* 2>/dev/null; echo "---"; getprop dalvik.vm.dex2oat-Xms; getprop dalvik.vm.dex2oat-threads'

run_exp 093 "Accessibility service injection" \
  'settings get secure enabled_accessibility_services 2>/dev/null; echo "---INSTALLED---"; pm list packages 2>/dev/null | grep -iE "accessib" | head -5; echo "---"; dumpsys accessibility 2>/dev/null | grep "Service\[" | head -10'

run_exp 094 "Device admin injection" \
  'dpm set-active-admin --help 2>&1 | head -5; echo "---"; dpm list-owners 2>&1; echo "---"; dumpsys device_policy 2>/dev/null | grep -iE "admin|owner|profile" | head -10'

run_exp 095 "Process injection (app_process)" \
  'which app_process 2>/dev/null; which app_process64 2>/dev/null; ls -la /system/bin/app_process* 2>/dev/null; echo "---"; CLASSPATH=/system/framework/am.jar app_process /system/bin com.android.commands.am.Am version 2>&1 | head -3'

run_exp 096 "Screencap/screenrecord" \
  'which screencap 2>/dev/null; which screenrecord 2>/dev/null; screencap -p /data/local/tmp/test_screen.png 2>&1; ls -la /data/local/tmp/test_screen.png 2>/dev/null; rm /data/local/tmp/test_screen.png 2>/dev/null'

run_exp 097 "cmd notification capabilities" \
  'cmd notification list 2>/dev/null | head -10; echo "---POST---"; cmd notification post -t "Test" "Hello from genesis" test_tag 2>&1'

run_exp 098 "Logcat as fingerprint source" \
  'logcat -d -t 5 -b main 2>/dev/null | head -10; echo "---SYSTEM---"; logcat -d -t 3 -b system 2>/dev/null | head -5'

run_exp 099 "Media/downloads databases" \
  'ls -la /data/data/com.android.providers.media.module/databases/ 2>/dev/null; echo "---DOWNLOADS---"; ls -la /data/data/com.android.providers.downloads/databases/ 2>/dev/null'

run_exp 100 "Backup/restore agent capabilities" \
  'dumpsys backup 2>/dev/null | head -15; echo "---"; bmgr list transports 2>&1 | head -5; echo "---ENABLED---"; bmgr enabled 2>&1'

echo ""
echo "── ALL 100 EXPERIMENTS COMPLETE ──"
echo "Full log: /tmp/vmos_experiments_b7890.log"
