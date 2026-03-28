#!/usr/bin/env bash
# V4 Screenshot Script — Display-aware, Jovany Owens post-patch
ADB="adb -s 127.0.0.1:6520"
SS_DIR="/opt/titan-v11.3-device/reports/app-screenshots-v2"
mkdir -p "$SS_DIR"

cap() {
  local NAME=$1 DELAY=${2:-2}
  sleep "$DELAY"
  $ADB shell screencap -p /sdcard/ss.png
  $ADB pull /sdcard/ss.png "$SS_DIR/$NAME.png" 2>&1 | tail -1
  local SZ
  SZ=$(stat -c%s "$SS_DIR/$NAME.png" 2>/dev/null || echo 0)
  echo "[CAP] $NAME (${SZ} bytes)"
}

echo "=== SCREENSHOT SESSION V4 ==="
MODEL=$($ADB shell getprop ro.product.model 2>/dev/null || echo "unknown")
echo "Device: $MODEL"

# CRITICAL: Wake display + keep on during capture
$ADB shell input keyevent KEYCODE_WAKEUP
sleep 0.5
$ADB shell input keyevent KEYCODE_WAKEUP
$ADB shell settings put system screen_off_timeout 600000
$ADB shell settings put global stay_on_while_plugged_in 3
$ADB shell input keyevent KEYCODE_MENU
sleep 1

# 01 Home screen
$ADB shell input keyevent KEYCODE_HOME
cap "01_home_screen" 2

# 02 About phone
$ADB shell am start -a android.settings.DEVICE_INFO_SETTINGS
cap "02_about_phone" 4

# 03 Scroll for IMEI
$ADB shell input swipe 540 1400 540 600 300
sleep 1
$ADB shell input swipe 540 1400 540 600 300
cap "03_about_scrolled_imei" 2

# 04 Network & Internet
$ADB shell am start -a android.settings.WIRELESS_SETTINGS
cap "04_network" 3

# 05 NFC/Payments
$ADB shell am start -a android.settings.NFC_SETTINGS
cap "05_nfc" 3

# 06 Battery
$ADB shell am start -a android.intent.action.POWER_USAGE_SUMMARY
cap "06_battery" 3

# 07 Storage
$ADB shell am start -a android.settings.INTERNAL_STORAGE_SETTINGS
cap "07_storage" 3

# 08 Accounts
$ADB shell am start -a android.settings.SYNC_SETTINGS
cap "08_accounts" 3

# 09 Gallery
$ADB shell am start -a android.intent.action.VIEW -t "image/*" 2>/dev/null || true
cap "09_gallery" 4

# 10 Dialer (recent calls)
$ADB shell am start -a android.intent.action.DIAL
cap "10_dialer_calls" 4

# 11 Messages
$ADB shell am start -a android.intent.action.MAIN -c android.intent.category.APP_MESSAGING
sleep 1
$ADB shell input keyevent KEYCODE_BACK 2>/dev/null || true
cap "11_messages_sms" 3

# 12 Date & Time
$ADB shell am start -a android.settings.DATE_SETTINGS
cap "12_datetime_tz" 3

# 13 Language
$ADB shell am start -a android.settings.LOCALE_SETTINGS
cap "13_language" 3

# 14 Security
$ADB shell am start -a android.settings.SECURITY_SETTINGS
cap "14_security" 3

# 15 Google Wallet
$ADB shell am start -n com.google.android.apps.walletnfcrel/.MainWalletActivity 2>/dev/null || \
  $ADB shell am start -a android.intent.action.VIEW -d "payment://" 2>/dev/null || true
cap "15_google_wallet" 5

# 16 Play Store
$ADB shell am start -n com.android.vending/.AssetBrowserActivity 2>/dev/null || true
cap "16_play_store" 5

# 17 WiFi
$ADB shell am start -a android.settings.WIFI_SETTINGS
cap "17_wifi" 3

# 18 SIM/Carrier
$ADB shell am start -a android.settings.NETWORK_OPERATOR_SETTINGS
cap "18_sim_carrier" 3

# 19 Build info (About, scrolled)
$ADB shell am start -a android.settings.DEVICE_INFO_SETTINGS
sleep 2
$ADB shell input swipe 540 1600 540 400 400
cap "19_build_info" 2

# 20 Google Account detail
$ADB shell am start -a android.settings.SYNC_SETTINGS
sleep 2
$ADB shell input tap 540 400
cap "20_google_account" 3

# 21 About phone final
$ADB shell am start -a android.settings.DEVICE_INFO_SETTINGS
cap "21_about_final" 4

# 22 Home final
$ADB shell input keyevent KEYCODE_HOME
cap "22_home_final" 2

echo ""
COUNT=$(ls "$SS_DIR/"*.png 2>/dev/null | wc -l)
echo "=== CAPTURE COMPLETE === $COUNT screenshots in $SS_DIR"
