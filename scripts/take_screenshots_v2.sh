#!/usr/bin/env bash
set -euo pipefail

ADB="adb -s 127.0.0.1:6520"
OUT="/opt/titan-v11.3-device/reports/final-verification"
DEVICE_TMP="/data/local/tmp"

mkdir -p "$OUT"

# Capture function: takes screenshot via compound shell to avoid timing issues
capture() {
    local name="$1"
    local remote="${DEVICE_TMP}/sc_${name}.png"
    
    $ADB shell "screencap -p ${remote}" 2>/dev/null || true
    sleep 1
    $ADB pull "${remote}" "${OUT}/${name}.png" 2>/dev/null || true
    
    local size
    size=$(stat -c%s "${OUT}/${name}.png" 2>/dev/null || echo 0)
    if [ "$size" -gt 40000 ]; then
        echo "  OK    ${name}: ${size} bytes"
    else
        echo "  SMALL ${name}: ${size} bytes"
    fi
    $ADB shell "rm -f ${remote}" 2>/dev/null || true
}

echo "=== TITAN FINAL SCREENSHOT SESSION ==="

# Step 0: Apply display settings
echo "[SETUP] Applying display settings..."
$ADB shell "settings put system screen_off_timeout 2147483647" 2>/dev/null || true
$ADB shell "settings put global stay_on_while_plugged_in 7" 2>/dev/null || true
$ADB shell "svc power stayon true" 2>/dev/null || true
$ADB shell "settings put global window_animation_scale 0" 2>/dev/null || true
$ADB shell "settings put global transition_animation_scale 0" 2>/dev/null || true  
$ADB shell "settings put global animator_duration_scale 0" 2>/dev/null || true

# Unlock
echo "[SETUP] Unlocking..."
$ADB shell "input keyevent KEYCODE_WAKEUP" 2>/dev/null || true
sleep 3
$ADB shell "input swipe 540 1800 540 400 300" 2>/dev/null || true
sleep 3
$ADB shell "input keyevent KEYCODE_HOME" 2>/dev/null || true
sleep 15
echo "[SETUP] Ready."

# 1. Home screen
echo "[1/16] Home screen..."
$ADB shell "input keyevent KEYCODE_HOME" 2>/dev/null || true
sleep 10
capture "01_home_screen"

# 2. About Phone  
echo "[2/16] About Phone..."
$ADB shell "am start -a android.settings.DEVICE_INFO_SETTINGS" 2>/dev/null || true
sleep 20
$ADB shell "input swipe 540 400 540 1800 300" 2>/dev/null || true
sleep 5
capture "02_about_phone"

# 3. About Phone - scroll down
echo "[3/16] About Phone scrolled..."
$ADB shell "input swipe 540 1800 540 400 500" 2>/dev/null || true
sleep 5
$ADB shell "input swipe 540 1800 540 400 500" 2>/dev/null || true
sleep 5
capture "03_about_phone_scroll"

# 4. Accounts
echo "[4/16] Accounts..."
$ADB shell "am start -a android.settings.SYNC_SETTINGS" 2>/dev/null || true
sleep 20
capture "04_accounts"

# 5. WiFi / Internet
echo "[5/16] WiFi / Internet..."
$ADB shell "am start -a android.settings.WIFI_SETTINGS" 2>/dev/null || true
sleep 20
capture "05_wifi"

# 6. SIM / Carrier
echo "[6/16] SIM / Carrier..."
$ADB shell "am start -n com.android.settings/.Settings\\\$MobileNetworkListActivity" 2>/dev/null || true
sleep 20
capture "06_sim_network"

# 7. NFC & Payments
echo "[7/16] NFC & Payments..."
$ADB shell "am start -a android.settings.NFC_SETTINGS" 2>/dev/null || true
sleep 20
capture "07_nfc"

# 8. Chrome
echo "[8/16] Chrome..."
$ADB shell "am start -n com.android.chrome/com.google.android.apps.chrome.Main" 2>/dev/null || true
sleep 20
capture "08_chrome"

# 9. Gallery / Files
echo "[9/16] Gallery..."
$ADB shell "am start -a android.intent.action.VIEW -t image/* -d file:///sdcard/DCIM" 2>/dev/null || true
sleep 20
capture "09_gallery"

# 10. Storage
echo "[10/16] Storage..."
$ADB shell "am start -a android.settings.INTERNAL_STORAGE_SETTINGS" 2>/dev/null || true
sleep 20
capture "10_storage"

# 11. Battery
echo "[11/16] Battery..."
$ADB shell "am start -a android.intent.action.POWER_USAGE_SUMMARY" 2>/dev/null || true
sleep 20
capture "11_battery"

# 12. Date & Time
echo "[12/16] Date & Time..."
$ADB shell "am start -a android.settings.DATE_SETTINGS" 2>/dev/null || true
sleep 20
capture "12_datetime"

# 13. Language
echo "[13/16] Language..."
$ADB shell "am start -a android.settings.LOCALE_SETTINGS" 2>/dev/null || true
sleep 20
capture "13_language"

# 14. Security
echo "[14/16] Security..."
$ADB shell "am start -a android.settings.SECURITY_SETTINGS" 2>/dev/null || true
sleep 20
capture "14_security"

# 15. Dialer (call logs)
echo "[15/16] Dialer..."
$ADB shell "am start -a android.intent.action.DIAL" 2>/dev/null || true
sleep 20
capture "15_dialer"

# 16. Messaging/SMS
echo "[16/16] Messaging..."
$ADB shell "am start -n com.android.messaging/.ui.conversationlist.ConversationListActivity" 2>/dev/null || true
sleep 20
capture "16_messaging"

echo ""
echo "=== FINAL RESULTS ==="
good=0
bad=0
for f in "$OUT"/0[1-9]_*.png "$OUT"/1[0-6]_*.png; do
    [ -f "$f" ] || continue
    size=$(stat -c%s "$f")
    name=$(basename "$f")
    if [ "$size" -gt 40000 ]; then
        echo "  OK    $name ($size bytes)"
        good=$((good+1))
    else
        echo "  SMALL $name ($size bytes)"
        bad=$((bad+1))
    fi
done
echo ""
echo "Good: $good  |  Needs retake: $bad"
echo "DONE"
