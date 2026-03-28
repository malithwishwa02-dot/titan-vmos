#!/usr/bin/env python3
"""
Titan V11.3 — Post-Pipeline Repair: Wallet + Content Provider Restart
Fixes:
  1. Runs WalletProvisioner.provision_card() directly (Phase 6 failed due to stale bytecache)
  2. Restarts ContentProviders so contacts/SMS/call_logs are visible via content:// queries
  3. Re-verifies all data counts
"""

import json
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, "/opt/titan-v11.3-device/core")
sys.path.insert(0, "/opt/titan-v11.3-device/server")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("titan.repair")

ADB = "127.0.0.1:6520"


def sh(cmd: str, timeout: int = 30) -> str:
    r = subprocess.run(f'adb -s {ADB} shell "{cmd}"', shell=True, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def adb_push(local: str, remote: str) -> bool:
    r = subprocess.run(f"adb -s {ADB} push {local} {remote}", shell=True, capture_output=True, timeout=30)
    return r.returncode == 0


def main():
    log.info("=" * 60)
    log.info("POST-PIPELINE REPAIR — Wallet + Data Visibility")
    log.info("=" * 60)

    # ── 1. WALLET PROVISIONING ─────────────────────────────────────
    log.info("")
    log.info("[WALLET] Running WalletProvisioner.provision_card()...")
    try:
        from wallet_provisioner import WalletProvisioner
        wp = WalletProvisioner(adb_target=ADB)
        result = wp.provision_card(
            card_number="4638512320340405",
            exp_month=8,
            exp_year=2029,
            cardholder="Jovany Owens",
            cvv="051",
            persona_email="adiniorjuniorjd28@gmail.com",
            persona_name="Jovany Owens",
            zero_auth=True,
            country="US",
        )
        log.info(f"  Google Pay:     {getattr(result, 'google_pay_ok', '?')}")
        log.info(f"  Play Store:     {getattr(result, 'play_store_ok', '?')}")
        log.info(f"  Chrome Autofill:{getattr(result, 'chrome_autofill_ok', '?')}")
        log.info(f"  GMS Billing:    {getattr(result, 'gms_billing_ok', '?')}")
        log.info(f"  DPAN:           {getattr(result, 'dpan', '?')}")

        # Fix tapandpay.db ownership
        log.info("[WALLET] Fixing tapandpay.db ownership...")
        wallet_uid = sh("stat -c '%U' /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
        if wallet_uid and wallet_uid != "root":
            sh(f"chown -R {wallet_uid}:{wallet_uid} /data/data/com.google.android.apps.walletnfcrel/databases/")
            sh("restorecon -R /data/data/com.google.android.apps.walletnfcrel/databases/ 2>/dev/null")
            log.info(f"  ✓ Ownership set to {wallet_uid}")
        else:
            # Find UID from packages.list
            uid_line = sh("grep com.google.android.apps.walletnfcrel /data/system/packages.list 2>/dev/null")
            if uid_line:
                parts = uid_line.split()
                if len(parts) >= 2:
                    uid = parts[1]
                    sh(f"chown -R {uid}:{uid} /data/data/com.google.android.apps.walletnfcrel/databases/")
                    sh("restorecon -R /data/data/com.google.android.apps.walletnfcrel/databases/ 2>/dev/null")
                    log.info(f"  ✓ Ownership set to UID {uid}")

    except Exception as e:
        log.error(f"  Wallet provisioning failed: {e}")
        import traceback
        traceback.print_exc()

    # ── 2. CONTENT PROVIDER RESTART ────────────────────────────────
    log.info("")
    log.info("[FIX] Restarting ContentProviders for data visibility...")

    # Force stop and restart providers so they re-read pushed SQLite DBs
    providers = [
        "com.android.providers.contacts",
        "com.android.providers.telephony",
        "com.android.providers.media",
        "com.android.providers.calendar",
    ]
    for pkg in providers:
        sh(f"am force-stop {pkg} 2>/dev/null")
        time.sleep(0.5)

    # Trigger contacts re-read
    sh("am broadcast -a android.provider.Contacts.CONTACTS_DATABASE_CREATED 2>/dev/null")
    # Trigger media scanner
    sh("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/ 2>/dev/null")
    sh("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///data/media/0/DCIM/ 2>/dev/null")
    # Force GMS restart to pick up account changes
    sh("am force-stop com.google.android.gms 2>/dev/null")
    time.sleep(2)

    log.info("  ✓ ContentProviders restarted")

    # ── 3. RE-VERIFY DATA COUNTS ──────────────────────────────────
    log.info("")
    log.info("[VERIFY] Data counts after repair...")
    time.sleep(3)

    checks = {
        "Contacts": "content query --uri content://com.android.contacts/contacts --projection _id 2>/dev/null | grep -c 'Row:'",
        "SMS": "content query --uri content://sms --projection _id 2>/dev/null | grep -c 'Row:'",
        "Call Logs": "content query --uri content://call_log/calls --projection _id 2>/dev/null | grep -c 'Row:'",
        "Gallery (DCIM)": "find /sdcard/DCIM /data/media/0/DCIM -name '*.jpg' 2>/dev/null | wc -l",
        "Google Account": "dumpsys account 2>/dev/null | grep -c 'Account {name='",
        "WiFi SSIDs": "cat /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null | grep -c 'SSID'",
        "Wallet DB": "ls -la /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null && echo EXISTS || echo MISSING",
        "Wallet tokens": "sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 'SELECT COUNT(*) FROM tokens;' 2>/dev/null",
        "Chrome Cookies": "ls -la /data/data/com.kiwibrowser.browser/app_chrome/Default/Cookies 2>/dev/null && echo EXISTS || echo MISSING",
        "Chrome History": "ls -la /data/data/com.kiwibrowser.browser/app_chrome/Default/History 2>/dev/null && echo EXISTS || echo MISSING",
        "Play Store lib": "ls -la /data/data/com.android.vending/databases/library.db 2>/dev/null && echo EXISTS || echo MISSING",
    }

    for label, cmd in checks.items():
        val = sh(cmd)
        log.info(f"  {label}: {val}")

    # ── 4. IDENTITY VERIFICATION ──────────────────────────────────
    log.info("")
    log.info("[VERIFY] Samsung S24 identity props...")
    props = [
        "ro.product.model", "ro.product.brand", "ro.product.manufacturer",
        "ro.build.fingerprint", "ro.kernel.qemu", "ro.hardware.virtual",
        "ro.secure", "ro.build.type", "ro.boot.verifiedbootstate",
        "ro.boot.flash.locked", "persist.sys.timezone",
        "gsm.operator.alpha", "gsm.sim.state",
        "ro.build.display.id", "ro.build.tags",
    ]
    for p in props:
        v = sh(f"getprop {p}")
        log.info(f"  {p} = {v}")

    # ── 5. WALLET DEEP VERIFY ─────────────────────────────────────
    log.info("")
    log.info("[VERIFY] Wallet deep check...")
    try:
        from wallet_verifier import WalletVerifier
        wv = WalletVerifier(adb_target=ADB)
        report = wv.verify()
        log.info(f"  Wallet Score: {report.score}/100  ({report.passed}/{report.total} checks)")
        for chk in report.checks:
            icon = "✓" if chk.get("passed") else "✗"
            log.info(f"  {icon} {chk['name']}: {chk.get('detail','')}")
    except Exception as e:
        log.warning(f"  Wallet verify failed: {e}")

    # ── 6. TRUST SCORE ────────────────────────────────────────────
    log.info("")
    log.info("[VERIFY] Final trust score...")
    try:
        from trust_scorer import compute_trust_score
        # Load the forged profile
        profiles_dir = "/opt/titan/data/profiles"
        profile_data = {}
        for f in sorted(os.listdir(profiles_dir), key=lambda x: os.path.getmtime(os.path.join(profiles_dir, x)), reverse=True):
            if f.endswith(".json"):
                with open(os.path.join(profiles_dir, f)) as fp:
                    profile_data = json.load(fp)
                log.info(f"  Using profile: {f}")
                break

        result = compute_trust_score(ADB, profile_data=profile_data)
        trust_score = result.get("trust_score", 0)
        grade = result.get("grade", "?")
        log.info(f"  Trust Score: {trust_score}/100 ({grade})")
        for k, v in result.get("checks", {}).items():
            passed = False
            if isinstance(v, dict):
                passed = v.get("present", False) or v.get("valid", False) or v.get("ok", False) or v.get("count", 0) >= 3
            elif isinstance(v, bool):
                passed = v
            icon = "✓" if passed else "✗"
            log.info(f"  {icon} {k}: {v}")
    except Exception as e:
        log.warning(f"  Trust score failed: {e}")

    log.info("")
    log.info("=" * 60)
    log.info("REPAIR COMPLETE.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
