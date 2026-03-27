#!/usr/bin/env python3
"""
Titan V13 — Genesis Continuation Script
========================================
Picks up AFTER stealth patch + pre-patch injections are done.
Runs the remaining workflow:

  STEP 1: Proxy ON
  STEP 2: ── MANUAL ── Visual Google sign-in (Play Store)
  STEP 3: Proxy OFF → ── MANUAL ── Download apps
  STEP 4: Proxy ON
  STEP 5: ROOT: Full profile injection (contacts, calls, SMS,
          cookies, history, gallery, autofill, maps, wallet,
          samsung health, sensors, timestamps, purchase history)
  STEP 6: Ownership fix
  STEP 7: Trust audit
  STEP 8: Proxy must remain ON
  STEP 9: Re-run anomaly patch (final)

ROOT NEEDED:
  - Step 5 (all ProfileInjector methods use adb root + sqlite pull/push)
  - Step 9 (anomaly patcher uses resetprop + proc mounts)

ROOT NOT NEEDED:
  - Step 1-4 (proxy settings + visual sign-in + app downloads)
  - Step 6 (just chown - but actually needs root too)

Usage:
    cd /opt/titan-v13-device
    source venv/bin/activate
    python3 scripts/genesis_continue.py
"""

import json
import os
import sys
import time
import subprocess

sys.path.insert(0, "/opt/titan-v13-device/core")
sys.path.insert(0, "/opt/titan-v13-device/server")

ADB_TARGET = "0.0.0.0:6520"
PROFILE_PATH = "/opt/titan/data/profiles/TITAN-8016A103.json"

PERSONA = {
    "name": "Jovany OWENS",
    "email": "adiniorjuniorjd28@gmail.com",
    "password": "YCCvsukin7S",
    "phone": "7078361915",
    "device_model": "samsung_s24",
    "carrier": "tmobile_us",
    "location": "la",
    "age_days": 180,
    "country": "US",
    "cc_number": "4638512320340405",
    "cc_exp_month": 8,
    "cc_exp_year": 2029,
    "cc_cvv": "051",
    "cc_holder": "Jovany OWENS",
}

PROXY_HOST = "31.59.20.176"
PROXY_PORT = "6754"
PROXY_USER = "sektmjln"
PROXY_PASS = "p1spgxdygwhu"


def adb(cmd, timeout=60):
    try:
        r = subprocess.run(
            f"adb -s {ADB_TARGET} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def sh(cmd, timeout=60):
    ok, out = adb(f'shell "{cmd}"', timeout=timeout)
    return out


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def proxy_on():
    log("  Proxy ON → {PROXY_HOST}:{PROXY_PORT}")
    sh(f"settings put global http_proxy {PROXY_HOST}:{PROXY_PORT}")
    sh(f"settings put global global_http_proxy_host {PROXY_HOST}")
    sh(f"settings put global global_http_proxy_port {PROXY_PORT}")
    sh(f"settings put global global_http_proxy_username {PROXY_USER}")
    sh(f"settings put global global_http_proxy_password {PROXY_PASS}")
    time.sleep(2)
    verify = sh("settings get global http_proxy")
    log(f"  Proxy verified: {verify}")


def proxy_off():
    log("  Proxy OFF")
    sh("settings put global http_proxy :0")
    sh("settings delete global global_http_proxy_host")
    sh("settings delete global global_http_proxy_port")
    sh("settings delete global global_http_proxy_username")
    sh("settings delete global global_http_proxy_password")
    time.sleep(1)


def fix_calllog_ownership():
    sh("chown u0_a19:u0_a19 /data/data/com.android.providers.contacts/databases/calllog.db*")
    sh("chmod 660 /data/data/com.android.providers.contacts/databases/calllog.db*")


def fix_all_ownership():
    log("  Fixing all file ownership...")
    fixes = [
        ("com.android.providers.contacts", "/data/data/com.android.providers.contacts/databases/*"),
        ("com.android.providers.telephony", "/data/data/com.android.providers.telephony/databases/*"),
    ]
    # Discover browser
    for pkg in ["com.android.chrome", "com.kiwibrowser.browser", "com.chrome.beta"]:
        result = sh(f"pm path {pkg} 2>/dev/null")
        if result and "package:" in result:
            fixes.append((pkg, f"/data/data/{pkg}/app_chrome/Default/*"))
            break
    # Wallet
    wallet = sh("pm path com.google.android.apps.walletnfcrel 2>/dev/null")
    if wallet and "package:" in wallet:
        fixes.append(("com.google.android.apps.walletnfcrel",
                      "/data/data/com.google.android.apps.walletnfcrel/databases/*"))
    # Maps
    maps = sh("pm path com.google.android.apps.maps 2>/dev/null")
    if maps and "package:" in maps:
        fixes.append(("com.google.android.apps.maps",
                      "/data/data/com.google.android.apps.maps/databases/*"))

    for pkg, pattern in fixes:
        uid = sh(f"stat -c %U /data/data/{pkg} 2>/dev/null")
        if uid and uid != "root" and uid.strip():
            sh(f"chown {uid}:{uid} {pattern} 2>/dev/null")
            sh(f"chmod 660 {pattern} 2>/dev/null")
            sh(f"restorecon -R /data/data/{pkg} 2>/dev/null")
            log(f"    {pkg} → {uid}")

    # Always fix calllog
    fix_calllog_ownership()
    log(f"    calllog.db → u0_a19")


def main():
    log("╔══════════════════════════════════════════════════════════╗")
    log("║  TITAN V13 — GENESIS CONTINUATION                       ║")
    log("║  Profile: TITAN-8016A103 (Jovany OWENS)                  ║")
    log("║  State: Patch done, pre-patch injections done            ║")
    log("╠══════════════════════════════════════════════════════════╣")
    log("║  REMAINING STEPS:                                        ║")
    log("║  1. Proxy ON                                             ║")
    log("║  2. Visual Google sign-in (MANUAL)                       ║")
    log("║  3. Proxy OFF → download apps (MANUAL)                   ║")
    log("║  4. Proxy ON                                             ║")
    log("║  5. ROOT: Full profile injection via ProfileInjector     ║")
    log("║  6. Ownership fix                                        ║")
    log("║  7. Trust audit                                          ║")
    log("║  8. Proxy stays ON                                       ║")
    log("║  9. Re-run anomaly patch (final)                         ║")
    log("╚══════════════════════════════════════════════════════════╝")

    start = time.time()

    # Load profile
    log("Loading profile...")
    with open(PROFILE_PATH) as f:
        profile = json.load(f)
    log(f"  Profile: {profile.get('id', 'TITAN-8016A103')}")
    log(f"  Contacts: {len(profile.get('contacts',[]))} | Calls: {len(profile.get('call_logs',[]))}")
    log(f"  Cookies: {len(profile.get('cookies',[]))} | History: {len(profile.get('history',[]))}")
    log(f"  Gallery: {len(profile.get('gallery_paths',[]))} | SMS: {len(profile.get('sms',[]))}")
    log(f"  Maps: {len(profile.get('maps_history',[]))} | Payments: {len(profile.get('payment_history',[]))}")

    # Keep screen on
    sh("svc power stayon true")
    sh("settings put system screen_off_timeout 2147483647")

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: PROXY ON
    # No root needed — uses `settings put global`
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 1: PROXY ON ═══")
    proxy_on()

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: VISUAL GOOGLE SIGN-IN (MANUAL)
    # No root needed — user signs in through Play Store UI
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 2: VISUAL GOOGLE SIGN-IN ═══")
    log("┌─────────────────────────────────────────────────────┐")
    log(f"│  Open Play Store and sign in with:                  │")
    log(f"│  Email: {PERSONA['email']}")
    log(f"│  Password: {PERSONA['password']}")
    log(f"│  Proxy is ON — all traffic routes through proxy     │")
    log("└─────────────────────────────────────────────────────┘")
    input("  >>> Press ENTER when Google sign-in is complete... ")

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: PROXY OFF → DOWNLOAD APPS (MANUAL)
    # No root needed — user downloads from Play Store
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 3: PROXY OFF → DOWNLOAD APPS ═══")
    proxy_off()
    log("┌─────────────────────────────────────────────────────┐")
    log("│  Download these apps from Play Store:               │")
    log("│  REQUIRED: Chrome, Google Wallet/Pay                │")
    log("│  OPTIONAL: Maps, Gmail, YouTube, Photos             │")
    log("│  Proxy is OFF — faster downloads                    │")
    log("└─────────────────────────────────────────────────────┘")
    input("  >>> Press ENTER when app downloads are complete... ")

    # ═══════════════════════════════════════════════════════════════
    # STEP 4: PROXY ON
    # No root needed
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 4: PROXY ON ═══")
    proxy_on()

    # ═══════════════════════════════════════════════════════════════
    # STEP 5: ROOT — FULL PROFILE INJECTION
    # ━━ ROOT REQUIRED ━━
    # ProfileInjector uses adb root + sqlite3 pull/push for ALL ops.
    # ADB root works on userdebug even after stealth patch.
    # The patch only hid su from ON-DEVICE apps (RASP/RootBeer).
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 5: ROOT — FULL PROFILE INJECTION ═══")
    log("  [ROOT] adb root — needed for sqlite DB pull/push operations")
    adb("root")
    time.sleep(3)

    from profile_injector import ProfileInjector

    card_data = {
        "number": PERSONA["cc_number"],
        "exp_month": PERSONA["cc_exp_month"],
        "exp_year": PERSONA["cc_exp_year"],
        "cardholder": PERSONA["cc_holder"],
        "cvv": PERSONA["cc_cvv"],
    }

    log("  Running ProfileInjector.inject_full_profile()...")
    log("  This handles ALL data injection with proper ownership:")
    log("    - Contacts (sqlite pull/push → contacts2.db)")
    log("    - Call logs (sqlite pull/push → calllog.db)")
    log("    - SMS (sqlite pull/push → mmssms.db)")
    log("    - Chrome cookies (sqlite pull/push → Cookies db)")
    log("    - Chrome history (sqlite pull/push → History db)")
    log("    - Chrome local storage (sqlite → localstorage.db)")
    log("    - Chrome autofill (sqlite pull/push → Web Data)")
    log("    - Gallery photos (EXIF JPEG gen → /sdcard/DCIM/)")
    log("    - Google account (DE+CE databases)")
    log("    - Wallet/GPay (tapandpay.db + Chrome autofill)")
    log("    - App SharedPrefs (GMS, Play Store)")
    log("    - Play purchases (usagestats)")
    log("    - Purchase history (commerce cookies)")
    log("    - Payment history (transaction records)")
    log("    - WiFi networks (WifiConfigStore.xml)")
    log("    - App usage stats (cmd usagestats)")
    log("    - Maps history (gmm_storage.db)")
    log("    - Samsung Health (steps/sleep)")
    log("    - Sensor traces (persist props)")
    log("    - Timestamp backdating (touch -t)")

    injector = ProfileInjector(adb_target=ADB_TARGET)
    result = injector.inject_full_profile(profile, card_data=card_data)

    log(f"  Injection complete:")
    log(f"    Contacts: {result.contacts_injected}")
    log(f"    Calls: {result.call_logs_injected}")
    log(f"    SMS: {result.sms_injected}")
    log(f"    Cookies: {result.cookies_injected}")
    log(f"    History: {result.history_injected}")
    log(f"    Photos: {result.photos_injected}")
    log(f"    Autofill: {result.autofill_injected}")
    log(f"    LocalStorage: {result.localstorage_injected}")
    log(f"    Trust score: {result.trust_score}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 6: OWNERSHIP FIX (safety net)
    # ━━ ROOT REQUIRED ━━ (chown needs root)
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 6: OWNERSHIP FIX ═══")
    log("  [ROOT] Fixing file ownership for all injected databases")
    fix_all_ownership()

    # ═══════════════════════════════════════════════════════════════
    # STEP 7: TRUST AUDIT
    # ━━ ROOT REQUIRED ━━ (reads /data/ paths)
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 7: TRUST AUDIT ═══")
    try:
        from trust_scorer import compute_trust_score
        score = compute_trust_score(ADB_TARGET)
        total = score.get("total", 0)
        grade = score.get("grade", "?")
        log(f"  Trust: {total}/100 ({grade})")
        if score.get("breakdown"):
            for k, v in score["breakdown"].items():
                log(f"    {k}: {v}")
    except Exception as e:
        log(f"  Trust audit error: {e}")
        total = 0

    # ═══════════════════════════════════════════════════════════════
    # STEP 8: PROXY STAYS ON
    # No root needed
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 8: ENSURE PROXY ON ═══")
    proxy_on()
    log("  Proxy is ON and will remain ON")

    # ═══════════════════════════════════════════════════════════════
    # STEP 9: RE-RUN ANOMALY PATCH (FINAL)
    # ━━ ROOT REQUIRED ━━ (resetprop, proc mounts, su hiding)
    # Re-runs stealth patch to cover any artifacts left by
    # injection operations (new files, prop changes, proc entries).
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ STEP 9: RE-RUN ANOMALY PATCH (FINAL) ═══")
    log("  [ROOT] Re-patching to cover injection artifacts")
    log("  This re-hides: su binary, proc mounts, cuttlefish")
    log("  processes, emulator props, Magisk traces...")
    log("  Expected duration: 3-8 minutes")

    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=ADB_TARGET)
    patch_result = patcher.full_patch(
        preset_name=PERSONA["device_model"],
        carrier_name=PERSONA["carrier"],
        location_name=PERSONA["location"],
        age_days=PERSONA["age_days"],
    )

    # Use correct attribute names (passed/total, NOT phases_passed/total_phases)
    passed = getattr(patch_result, "passed", 0)
    total_p = getattr(patch_result, "total", 0)
    score_p = getattr(patch_result, "score", 0)
    elapsed_p = getattr(patch_result, "elapsed_sec", 0)
    log(f"  Patch result: {score_p}% ({passed}/{total_p}) in {elapsed_p:.0f}s")

    # Fix calllog ownership one last time (patch may have touched it)
    fix_calllog_ownership()

    # ═══════════════════════════════════════════════════════════════
    # FINAL VERIFICATION
    # ═══════════════════════════════════════════════════════════════
    log("")
    log("═══ FINAL VERIFICATION ═══")
    checks = {
        "boot_complete": sh("getprop sys.boot_completed"),
        "fingerprint": sh("getprop ro.build.fingerprint"),
        "model": sh("getprop ro.product.model"),
        "debuggable": sh("getprop ro.debuggable"),
        "secure": sh("getprop ro.secure"),
        "contacts": sh("content query --uri content://com.android.contacts/contacts 2>/dev/null | wc -l"),
        "call_logs": sh("content query --uri content://call_log/calls 2>/dev/null | wc -l"),
        "sms": sh("content query --uri content://sms 2>/dev/null | wc -l"),
        "google_acct": sh("sqlite3 /data/system_de/0/accounts_de.db 'SELECT name FROM accounts' 2>/dev/null"),
        "proxy": sh("settings get global http_proxy"),
        "calllog_owner": sh("stat -c %U /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null"),
    }

    for k, v in checks.items():
        ok = "✓" if v and v != "0" and "radio" not in str(v) else "✗"
        log(f"  {ok} {k}: {v}")

    elapsed = int(time.time() - start)
    log("")
    log(f"═══ GENESIS CONTINUATION COMPLETE in {elapsed}s ═══")
    log(f"  Trust: {total}/100")
    log(f"  Patch: {score_p}%")
    log(f"  Proxy: ON (must remain on)")


if __name__ == "__main__":
    main()
