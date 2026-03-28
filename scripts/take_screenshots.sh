#!/usr/bin/env bash
set -euo pipefail

ADB="adb -s 127.0.0.1:6520"
OUT="/opt/titan-v11.3-device/reports/final-verification"
WAIT=12  # seconds to wait for SwiftShader rendering

mkdir -p "$OUT"

capture() {
    local name="$1"
    local remote="/sdcard/sc_${name}.png"
    
    # Touch to force compositor redraw
    $ADB shell "input tap 540 1200" 2>/dev/null || true
    sleep 2
    
    $ADB shell "screencap -p ${remote}" 2>/dev/null
    $ADB pull "${remote}" "${OUT}/${name}.png" 2>/dev/null
    local size
    size=$(stat -c%s "${OUT}/${name}.png" 2>/dev/null || echo 0)
    echo "  ${name}: ${size} bytes"
    $ADB shell "rm -f ${remote}" 2>/dev/null || true
}

echo "=== TITAN SCREENSHOT SESSION ==="
echo "Ensuring display stays on..."
$ADB shell "settings put system screen_off_timeout 2147483647" 2>/dev/null
$ADB shell "settings put global stay_on_while_plugged_in 7" 2>/dev/null
$ADB shell "svc power stayon true" 2>/dev/null
$ADB shell "input keyevent KEYCODE_WAKEUP" 2>/dev/null
sleep 2
$ADB shell "input swipe 540 1800 540 400 300" 2>/dev/null
sleep 2

# Verify awake
WAKE=$($ADB shell "dumpsys power | grep mWakefulness" 2>/dev/null)
echo "Power: $WAKE"

# 1. Home screen
echo "[1/14] Home screen..."
$ADB shell "input keyevent KEYCODE_HOME" 2>/dev/null
sleep $WAIT
capture "01_home_screen"

# 2. About Phone  
echo "[2/14] About Phone..."
$ADB shell "am start -a android.settings.DEVICE_INFO_SETTINGS" 2>/dev/null
sleep $WAIT
# Scroll up to top
$ADB shell "input swipe 540 400 540 1800 300" 2>/dev/null
sleep 3
capture "02_about_phone"

# 3. About Phone - scroll down for build info
echo "[3/14] About Phone (scrolled)..."
$ADB shell "input swipe 540 1800 540 400 500" 2>/dev/null
sleep 5
$ADB shell "input swipe 540 1800 540 400 500" 2>/dev/null  
sleep 5
capture "03_about_phone_scroll"

# 4. Accounts  
echo "[4/14] Accounts..."
$ADB shell "am start -a android.settings.SYNC_SETTINGS" 2>/dev/null
sleep $WAIT
capture "04_accounts"

# 5. WiFi / Internet
echo "[5/14] WiFi / Internet..."
$ADB shell "am start -a android.settings.WIFI_SETTINGS" 2>/dev/null
sleep $WAIT
capture "05_wifi"

# 6. SIM / Network
echo "[6/14] SIM / Network..."
$ADB shell "am start -n com.android.settings/.Settings\\\$MobileNetworkListActivity" 2>/dev/null
sleep $WAIT
capture "06_sim_network"

# 7. NFC & Payments
echo "[7/14] NFC & Payments..."
$ADB shell "am start -a android.settings.NFC_SETTINGS" 2>/dev/null
sleep $WAIT
capture "07_nfc"

# 8. Chrome
echo "[8/14] Chrome..."
$ADB shell "am start -n com.android.chrome/com.google.android.apps.chrome.Main" 2>/dev/null
sleep $WAIT
# Tap address bar area to show URL info
$ADB shell "input tap 540 200" 2>/dev/null
sleep 5
capture "08_chrome"

# 9. Gallery / Photos
echo "[9/14] Gallery..."
$ADB shell "am start -a android.intent.action.VIEW -t image/* -d content://media/external/images/media" 2>/dev/null
sleep $WAIT
capture "09_gallery"

# 10. Storage
echo "[10/14] Storage..."
$ADB shell "am start -a android.settings.INTERNAL_STORAGE_SETTINGS" 2>/dev/null
sleep $WAIT
capture "10_storage"

# 11. Battery
echo "[11/14] Battery..."
$ADB shell "am start -a android.intent.action.POWER_USAGE_SUMMARY" 2>/dev/null
sleep $WAIT
capture "11_battery"

# 12. Date & Time
echo "[12/14] Date & Time..."
$ADB shell "am start -a android.settings.DATE_SETTINGS" 2>/dev/null
sleep $WAIT
capture "12_datetime"

# 13. Language
echo "[13/14] Language..."
$ADB shell "am start -a android.settings.LOCALE_SETTINGS" 2>/dev/null
sleep $WAIT
capture "13_language"

# 14. Security
echo "[14/14] Security..."
$ADB shell "am start -a android.settings.SECURITY_SETTINGS" 2>/dev/null
sleep $WAIT
capture "14_security"

echo ""
echo "=== RESULTS ==="
echo "All screenshots in: $OUT"
ls -la "$OUT"/*.png 2>/dev/null | awk '{printf "  %-40s %s bytes\n", $NF, $5}'
echo ""
echo "=== SIZE CHECK ==="
for f in "$OUT"/0*.png "$OUT"/1*.png; do
    [ -f "$f" ] || continue
    size=$(stat -c%s "$f")
    name=$(basename "$f")
    if [ "$size" -gt 40000 ]; then
        echo "  OK    $name ($size bytes)"
    else
        echo "  SMALL $name ($size bytes)"
    fi
done
echo ""
echo "DONE"
