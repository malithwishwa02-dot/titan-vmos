#!/usr/bin/env bash
# ====================================================================
#  TITAN — Real Device ADB Connection Helper
#  READ-ONLY — no modifications made to your device
#
#  Handles: carrier-locked phones, MDM-managed devices, Samsung Knox,
#           OEM-locked bootloaders, blocked developer options
# ====================================================================
#
#  USAGE:
#    bash scripts/connect_real_device.sh           # interactive wizard
#    bash scripts/connect_real_device.sh pair      # Android 11+ wireless pairing
#    bash scripts/connect_real_device.sh usb       # USB cable
#    bash scripts/connect_real_device.sh <ip>      # WiFi direct connect
#    bash scripts/connect_real_device.sh diagnose  # diagnose what's blocking ADB
#
# ─────────────────────────────────────────────────────────────────────
#  HOW TO ENABLE DEVELOPER OPTIONS (CARRIER-LOCKED DEVICES)
# ─────────────────────────────────────────────────────────────────────
#
#  STANDARD (all Android):
#    Settings → About Phone → tap "Build Number" 7 times quickly
#    → Enter PIN if prompted
#    → "You are now a developer!"
#    Settings → Developer Options → USB Debugging ON
#
#  SAMSUNG (Galaxy S/A/Note — even carrier-locked):
#    Settings → About Phone → Software Information → tap "Build Number" x7
#    If blocked: Settings → General Management → Reset → Reset Settings
#    (does NOT factory reset, just clears MDM-set restrictions)
#
#  PIXEL / GOOGLE (carrier unlocked by default):
#    Settings → About Phone → tap "Build Number" x7
#
#  ONEPLUS (T-Mobile/AT&T carrier):
#    Settings → About Device → tap "Build Number" x7
#    THEN: Settings → Developer Options → OEM Unlocking ON first
#
#  MOTOROLA (carrier):
#    Settings → About Phone → Software Info → tap "Build Number" x7
#    Carrier unlocked via: motorola.com/unlockbootloader
#
#  T-MOBILE / METRO MDM BLOCK:
#    If Dev Options is grayed out → Settings → Biometrics → Device Admin Apps
#    Disable all admin apps first, THEN enable Dev Options
#
#  AT&T / CRICKET MDM:
#    Settings → Security → Device Administrators → remove all
#    Then: adb shell pm uninstall -k --user 0 com.att.mobileclientplatform
#    (only works if some ADB access already available)
#
#  VERIZON MDM:
#    Verizon Business devices: IT admin must disable MDM policy remotely
#    Personal Verizon phones: Dev Options is normally accessible
#
#  SAMSUNG KNOX (enterprise-enrolled):
#    Knox cannot be bypassed without IT admin credentials
#    Alternative: request MDM unenrollment via IT department
#    WORKAROUND: Wireless Debugging (Android 11+) sometimes bypasses Knox ADB block
#
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${BLUE}[CONNECT]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
err()  { echo -e "${RED}[ ERR  ]${NC} $*"; }
info() { echo -e "${CYAN}[ INFO ]${NC} $*"; }
step() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }

SERVER_IP="51.68.33.34"
ADB_PORT=5555

# ── helpers ──────────────────────────────────────────────────────────

wait_for_device() {
    local target="$1"
    log "Waiting for device $target to come online (max 30s)..."
    for i in $(seq 1 30); do
        state=$(adb -s "$target" get-state 2>/dev/null || true)
        if [[ "$state" == "device" ]]; then
            ok "Device $target is online!"
            return 0
        fi
        sleep 1
        printf "."
    done
    echo ""
    err "Device did not come online within 30 seconds."
    return 1
}

check_connected_devices() {
    log "Currently connected devices:"
    adb devices -l 2>/dev/null
    echo ""
}

# ── mode: USB ────────────────────────────────────────────────────────

connect_usb() {
    log "USB Mode — checking for USB-connected device..."
    adb kill-server 2>/dev/null; adb start-server 2>/dev/null
    DEVICES=$(adb devices 2>/dev/null | grep -v "List of" | grep "device$" | awk '{print $1}')
    if [[ -z "$DEVICES" ]]; then
        err "No USB device found."
        echo ""
        echo "  Make sure:"
        echo "  • USB cable is connected"
        echo "  • USB Debugging is enabled in Developer Options"
        echo "  • You tapped 'Allow' on the phone when prompted"
        exit 1
    fi
    DEVICE=$(echo "$DEVICES" | head -1)
    ok "USB device found: $DEVICE"
    echo "$DEVICE" > /tmp/titan_device_target.txt
    adb -s "$DEVICE" devices -l
}

# ── mode: PAIR (Android 11+) ─────────────────────────────────────────

connect_pair() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Android 11+ Wireless Pairing"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  On your phone:"
    echo "  1. Settings → Developer Options → Wireless Debugging"
    echo "  2. Tap 'Pair device with pairing code'"
    echo "  3. Note the IP:PORT and 6-digit code shown"
    echo ""
    read -r -p "  Enter pairing IP:PORT (e.g. 192.168.1.5:37489): " PAIR_ADDR
    read -r -p "  Enter 6-digit pairing code: " PAIR_CODE
    echo ""
    log "Pairing with $PAIR_ADDR ..."
    adb pair "$PAIR_ADDR" "$PAIR_CODE"
    echo ""
    read -r -p "  Now enter the CONNECT IP:PORT from Wireless Debugging screen: " CONN_ADDR
    log "Connecting to $CONN_ADDR ..."
    adb connect "$CONN_ADDR"
    sleep 3
    DEVICE="$CONN_ADDR"
    echo "$DEVICE" > /tmp/titan_device_target.txt
    wait_for_device "$DEVICE"
}

# ── mode: WiFi direct (legacy — Android 10 and below) ───────────────

connect_wifi() {
    local DEVICE_IP="${1:-}"
    if [[ -z "$DEVICE_IP" ]]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  WiFi ADB Connection (requires USB first, or Wireless Debugging)"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        read -r -p "  Enter your phone's IP address: " DEVICE_IP
    fi
    log "Connecting to $DEVICE_IP:$ADB_PORT ..."
    adb connect "$DEVICE_IP:$ADB_PORT"
    sleep 3
    DEVICE="$DEVICE_IP:$ADB_PORT"
    echo "$DEVICE" > /tmp/titan_device_target.txt
    wait_for_device "$DEVICE"
}

# ── mode: DIAGNOSE what's blocking ADB ──────────────────────────────

diagnose_adb_block() {
    step "ADB Block Diagnostics"
    echo ""
    echo "  This tool helps identify WHY your device won't connect via ADB."
    echo ""
    read -r -p "  What is your device brand? (samsung/pixel/oneplus/motorola/other): " BRAND
    read -r -p "  What carrier is it locked to? (tmobile/att/verizon/cricket/other/none): " CARRIER
    read -r -p "  Android version (e.g. 13, 14, 15): " ANDROID_VER
    read -r -p "  Is Developer Options visible in Settings? (yes/no/grayed): " DEV_OPT
    read -r -p "  Is USB Debugging enabled? (yes/no/option_missing): " USB_DBG
    echo ""
    step "Diagnosis Results"
    echo ""

    # Samsung + Knox
    if [[ "${BRAND,,}" == "samsung" ]]; then
        info "Samsung device detected."
        if [[ "${CARRIER,,}" == "att" || "${CARRIER,,}" == "cricket" ]]; then
            warn "AT&T/Cricket Samsung devices often have MDM preinstalled."
            echo "  → Settings → Biometrics & Security → Device Admin Apps"
            echo "  → Disable all admin apps, then re-check Developer Options"
            echo "  → Or: Settings → General Management → Reset → Reset Settings (safe, no data loss)"
        fi
        if [[ "${DEV_OPT,,}" == "grayed" ]]; then
            warn "Developer Options is grayed out — MDM policy is active."
            echo "  OPTION 1: Settings → General Management → Reset → Reset Settings"
            echo "            (clears MDM restrictions without factory reset)"
            echo "  OPTION 2: Samsung Wireless Debugging (bypasses Knox in some cases):"
            echo "            Settings → Developer Options → Wireless Debugging"
            echo "            (may need to call carrier to request MDM removal)"
        fi
        echo ""
        echo "  Knox Integrity Check: if 'Knox warranty bit' is 0x1, kernel is unmodified"
        echo "  Samsung ADB path: Settings → Developer Options → USB Debugging"
        echo "  Samsung OEM Unlock: Settings → Developer Options → OEM Unlocking"
        echo "  Note: OEM unlock requires carrier permission on T-Mobile/AT&T devices"
    fi

    # T-Mobile MDM
    if [[ "${CARRIER,,}" == "tmobile" ]]; then
        warn "T-Mobile often pre-installs MDM on business/JUMP plans."
        echo "  → Check: Settings → Apps → see 'T-Mobile Device Management' or 'SOTI MobiControl'"
        echo "  → Personal T-Mobile phones: Developer Options is usually accessible"
        echo "  → Business JUMP phones: MDM must be removed by T-Mobile IT/Business account"
        echo ""
        echo "  WIRELESS DEBUGGING BYPASS (Android 11+):"
        echo "  Even if USB Debugging is blocked by MDM, Wireless Debugging may work:"
        echo "  Settings → Developer Options → Wireless Debugging → Pair with pairing code"
    fi

    # AT&T MDM
    if [[ "${CARRIER,,}" == "att" ]]; then
        warn "AT&T MCP (Mobile Client Platform) is common on AT&T devices."
        echo "  → Package: com.att.mobileclientplatform"
        echo "  → Disabling requires some form of ADB access first — chicken & egg problem"
        echo "  → BEST APPROACH: Use Wireless Debugging (Android 11+) to get initial access,"
        echo "    then run: adb shell pm disable-user --user 0 com.att.mobileclientplatform"
    fi

    # Verizon
    if [[ "${CARRIER,,}" == "verizon" ]]; then
        info "Verizon personal phones: Developer Options is normally not blocked."
        info "Verizon Business/government phones may have MDM."
        echo "  → Check: Settings → Apps → 'Verizon Business DM' or 'MobileIron'"
        echo "  → Personal Verizon: just enable Developer Options normally"
    fi

    # Dev Options missing
    if [[ "${DEV_OPT,,}" == "no" || "${DEV_OPT,,}" == "option_missing" ]]; then
        err "Developer Options not visible — need to unlock it first:"
        echo "  1. Settings → About Phone"
        echo "  2. Look for: 'Build Number', 'Software Version', or 'Software Info'"
        echo "  3. Tap it EXACTLY 7 times quickly"
        echo "  4. Enter PIN/password if prompted"
        echo "  5. 'You are now a developer!' message should appear"
        echo "  6. Go back to main Settings — Developer Options should now appear"
        echo ""
        echo "  ON SAMSUNG specifically:"
        echo "  Settings → About Phone → Software Information → Build Number (x7)"
    fi

    echo ""
    step "Universal Workarounds (try in order)"
    echo ""
    echo "  1. WIRELESS DEBUGGING (Android 11+) — bypasses most carrier blocks:"
    echo "     Settings → Developer Options → Wireless Debugging → ON"
    echo "     Then: run this script with 'pair' argument"
    echo ""
    echo "  2. SCRCPY/ADB-WIFI via USB first:"
    echo "     a) Connect USB cable"
    echo "     b) adb tcpip 5555       (run on server)"
    echo "     c) Disconnect USB"
    echo "     d) bash connect_real_device.sh <phone-ip>"
    echo ""
    echo "  3. FACTORY RESET + fresh setup:"
    echo "     If MDM was auto-enrolled at setup, reset factory and skip auto-enrollment"
    echo "     (for Google MDM: at setup screen, don't sign in to work/corporate account)"
    echo ""
    echo "  4. CARRIER UNLOCK REQUEST:"
    echo "     Most carriers unlock devices after 30-60 days of active use"
    echo "     Call carrier to request ADB/developer unlock for personal use"
    echo ""
    echo "  Run 'bash connect_real_device.sh pair' once you have Wireless Debugging active"
}

# ── firewall: open ADB port ──────────────────────────────────────────

open_firewall() {
    log "Opening ADB port $ADB_PORT on this server (for inbound connections)..."
    if command -v ufw &>/dev/null; then
        ufw allow "$ADB_PORT"/tcp 2>/dev/null && ok "UFW: port $ADB_PORT opened"
    fi
    iptables -I INPUT -p tcp --dport "$ADB_PORT" -j ACCEPT 2>/dev/null && ok "iptables: port $ADB_PORT opened" || true
    ok "Server is listening on $SERVER_IP:$ADB_PORT"
}

# ── MAIN ─────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  TITAN — Real Device Connection"
echo "  Server: $SERVER_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

MODE="${1:-auto}"

case "$MODE" in
    pair)
        connect_pair
        ;;
    usb)
        connect_usb
        ;;
    diagnose)
        diagnose_adb_block
        exit 0
        ;;
    auto|*)
        if [[ "$MODE" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+ ]]; then
            connect_wifi "$MODE"
        else
            echo "  Choose connection method:"
            echo "    1) WiFi (enter phone IP)       — Android 10 and below"
            echo "    2) Wireless Pairing            — Android 11+ (recommended, bypasses some carrier blocks)"
            echo "    3) USB cable"
            echo "    4) Diagnose ADB block          — if nothing works, start here"
            echo ""
            read -r -p "  Choice [1/2/3/4]: " CHOICE
            case "$CHOICE" in
                1) connect_wifi ;;
                2) connect_pair ;;
                3) connect_usb ;;
                4) diagnose_adb_block; exit 0 ;;
                *) err "Invalid choice"; exit 1 ;;
            esac
        fi
        ;;
esac

# Final verification
echo ""
check_connected_devices
TARGET=$(cat /tmp/titan_device_target.txt 2>/dev/null || echo "")
if [[ -n "$TARGET" ]]; then
    MODEL=$(adb -s "$TARGET" shell getprop ro.product.model 2>/dev/null || echo "unknown")
    ANDROID=$(adb -s "$TARGET" shell getprop ro.build.version.release 2>/dev/null || echo "unknown")
    ok "Connected: $MODEL (Android $ANDROID)"
    echo ""
    echo "  Device target saved to: /tmp/titan_device_target.txt"
    echo "  Run analysis:  python3 scripts/analyze_real_device.py"
    echo "  Quick scan:    python3 scripts/analyze_real_device.py --quick"
fi
