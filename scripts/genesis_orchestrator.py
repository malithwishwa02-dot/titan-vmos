#!/usr/bin/env python3
"""
Titan V13 — Genesis Orchestrator (Smart Flow)
=============================================
Custom pipeline that follows the user's requested order:
  1. Wipe device clean
  2. Stealth patch (26 phases)
  3. Configure proxy FIRST
  4. Google Sign-in via visual AI agent (with proxy)
  5. Disable proxy for large app downloads
  6. Download apps from Play Store
  7. Re-enable proxy
  8. Inject profile data ON-DEVICE via content providers (no ADB push ownership issues)
  9. Inject Chrome data, WiFi, accounts (root required — with proper ownership fix)
  10. Setup Google Pay + card
  11. Verify everything

Usage:
    python3 scripts/genesis_orchestrator.py
"""

import json
import os
import sys
import time
import subprocess
import tempfile
import glob
import shlex

sys.path.insert(0, "/opt/titan-v13-device/core")
sys.path.insert(0, "/opt/titan-v13-device/server")

ADB_TARGET = "0.0.0.0:6520"
PROFILE_DIR = "/opt/titan/data/profiles"

# ── Persona ──────────────────────────────────────────────────────────
PERSONA = {
    "name": "Jovany OWENS",
    "email": "adiniorjuniorjd28@gmail.com",
    "password": "YCCvsukin7S",
    "phone": "7078361915",
    "dob": "1959-12-11",
    "ssn": "219-19-0937",
    "street": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90006",
    "country": "US",
    "gender": "male",
    "cc_number": "4638512320340405",
    "cc_exp": "08/2029",
    "cc_cvv": "051",
    "cc_holder": "Jovany OWENS",
    "proxy_url": "http://sektmjln:p1spgxdygwhu@31.59.20.176:6754",
    "device_model": "samsung_s24",
    "carrier": "tmobile_us",
    "location": "la",
    "age_days": 180,
}

# ═════════════════════════════════════════════════════════════════════
# ADB HELPERS
# ═════════════════════════════════════════════════════════════════════

def adb(cmd, timeout=30):
    """Run an ADB command, return (success, stdout)."""
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

def sh(cmd, timeout=30):
    """Run ADB shell command, return stdout."""
    ok, out = adb(f'shell "{cmd}"', timeout=timeout)
    return out if ok else ""

def sh_raw(cmd, timeout=30):
    """Run ADB shell command directly (no extra quoting)."""
    try:
        r = subprocess.run(
            f"adb -s {ADB_TARGET} shell {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except:
        return ""

def wait_boot(timeout=300):
    """Wait for device boot completion."""
    print("  Waiting for boot...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        val = sh("getprop sys.boot_completed")
        if val.strip() == "1":
            print(f" done ({int(time.time()-start)}s)")
            return True
        time.sleep(5)
        print(".", end="", flush=True)
    print(" TIMEOUT!")
    return False

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ═════════════════════════════════════════════════════════════════════
# PHASE 0: WIPE
# ═════════════════════════════════════════════════════════════════════

def phase_wipe():
    log("═══ PHASE 0: WIPE ═══")
    adb("root")
    time.sleep(2)
    
    wipe_cmds = [
        # Google accounts
        "rm -f /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db*",
        # Contacts + call log
        "rm -f /data/data/com.android.providers.contacts/databases/contacts2.db* "
        "/data/data/com.android.providers.contacts/databases/calllog.db* "
        "/data/data/com.android.providers.contacts/databases/profile.db*",
        # SMS
        "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "
        "'DELETE FROM sms; DELETE FROM threads;' 2>/dev/null",
        # Browser
        "rm -rf /data/data/com.kiwibrowser.browser/app_chrome/Default/* "
        "/data/data/com.android.chrome/app_chrome/Default/Cookies "
        "/data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null",
        # Gallery
        "rm -rf /sdcard/DCIM/* /sdcard/Pictures/* /data/media/0/DCIM/* 2>/dev/null",
        # Wallet
        "rm -f /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db* "
        "/data/data/com.google.android.apps.walletnfcrel/shared_prefs/*.xml 2>/dev/null",
        # WiFi + usage
        "rm -rf /data/system/usagestats/0/* "
        "/data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null",
    ]
    
    for cmd in wipe_cmds:
        sh(cmd)
    
    log("  Wipe complete")

# ═════════════════════════════════════════════════════════════════════
# PHASE 1: STEALTH PATCH (26 phases)
# ═════════════════════════════════════════════════════════════════════

def phase_stealth_patch():
    log("═══ PHASE 3: STEALTH PATCH (3-6 min) ═══")
    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=ADB_TARGET)
    result = patcher.full_patch(
        preset_name=PERSONA["device_model"],
        carrier_name=PERSONA["carrier"],
        location_name=PERSONA["location"],
        age_days=PERSONA["age_days"],
    )
    passed = getattr(result, "phases_passed", 0)
    total = getattr(result, "total_phases", 145)
    pct = int(passed / total * 100) if total else 0
    log(f"  Stealth: {pct}% ({passed}/{total})")
    return pct

# ═════════════════════════════════════════════════════════════════════
# PHASE 2: PROXY ON/OFF
# ═════════════════════════════════════════════════════════════════════

def proxy_on():
    """Configure HTTP proxy via Android global settings."""
    log("  Proxy ON → 31.59.20.176:6754")
    # Set global HTTP proxy (works for most apps including Play Store sign-in)
    sh("settings put global http_proxy 31.59.20.176:6754")
    sh("settings put global global_http_proxy_host 31.59.20.176")
    sh("settings put global global_http_proxy_port 6754")
    sh("settings put global global_http_proxy_username sektmjln")
    sh("settings put global global_http_proxy_password p1spgxdygwhu")
    time.sleep(2)
    # Verify
    proxy = sh("settings get global http_proxy")
    log(f"  Proxy set: {proxy}")

def proxy_off():
    """Remove proxy for direct downloads."""
    log("  Proxy OFF (direct connection)")
    sh("settings put global http_proxy :0")
    sh("settings delete global global_http_proxy_host")
    sh("settings delete global global_http_proxy_port")
    sh("settings delete global global_http_proxy_username")
    sh("settings delete global global_http_proxy_password")
    time.sleep(1)

# ═════════════════════════════════════════════════════════════════════
# PHASE 3: FORGE PROFILE
# ═════════════════════════════════════════════════════════════════════

def phase_forge_profile():
    log("═══ PHASE 3: FORGE PROFILE ═══")
    from android_profile_forge import AndroidProfileForge
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=PERSONA["name"],
        persona_email=PERSONA["email"],
        persona_phone=PERSONA["phone"],
        persona_address={
            "street": PERSONA["street"],
            "city": PERSONA["city"],
            "state": PERSONA["state"],
            "zip": PERSONA["zip"],
            "country": PERSONA["country"],
        },
        device_model=PERSONA["device_model"],
        carrier=PERSONA["carrier"],
        location=PERSONA["location"],
        age_days=PERSONA["age_days"],
        country=PERSONA["country"],
    )

    profile_id = profile.get("uuid", profile.get("id", "UNKNOWN"))
    profile_path = os.path.join(PROFILE_DIR, f"{profile_id}.json")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    log(f"  Profile: {profile_id}")
    log(f"  Contacts: {len(profile.get('contacts',[]))} | SMS: {len(profile.get('sms',[]))} | "
        f"Calls: {len(profile.get('call_logs',[]))} | Cookies: {len(profile.get('cookies',[]))}")
    return profile, profile_id

# ═════════════════════════════════════════════════════════════════════
# PHASE 4: GOOGLE ACCOUNT INJECTION (DB-level, 8 targets)
# ═════════════════════════════════════════════════════════════════════

def phase_google_inject():
    log("═══ PHASE 4: GOOGLE ACCOUNT INJECTION ═══")
    from google_account_injector import GoogleAccountInjector
    injector = GoogleAccountInjector(adb_target=ADB_TARGET)
    result = injector.inject_account(
        email=PERSONA["email"],
        display_name=PERSONA["name"],
    )
    ok = getattr(result, "accounts_de_ok", False) and getattr(result, "accounts_ce_ok", False)
    targets = getattr(result, "targets_ok", 0)
    log(f"  Google inject: {targets}/8 targets, DE={getattr(result,'accounts_de_ok','?')}, CE={getattr(result,'accounts_ce_ok','?')}")

    # POST-FIX: Ensure accounts_de.db has ALL required tables
    log("  Post-fix: ensuring accounts_de.db has all 8 tables...")
    fix_sql = """
CREATE TABLE IF NOT EXISTS grants (accounts_id INTEGER NOT NULL, auth_token_type TEXT NOT NULL DEFAULT '', uid INTEGER NOT NULL, UNIQUE (accounts_id, auth_token_type, uid));
CREATE TABLE IF NOT EXISTS visibility (accounts_id INTEGER NOT NULL, _package TEXT NOT NULL, value INTEGER, UNIQUE (accounts_id, _package));
CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, type TEXT NOT NULL DEFAULT '', authtoken TEXT, UNIQUE (accounts_id, type));
CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, key TEXT NOT NULL DEFAULT '', value TEXT, UNIQUE (accounts_id, key));
CREATE TABLE IF NOT EXISTS shared_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name, type));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY NOT NULL, value TEXT);
PRAGMA user_version = 3;
"""
    for line in fix_sql.strip().split("\n"):
        line = line.strip()
        if line:
            sh(f"sqlite3 /data/system_de/0/accounts_de.db '{line}'")

    # CE fix
    sh("sqlite3 /data/system_ce/0/accounts_ce.db 'CREATE TABLE IF NOT EXISTS grants (accounts_id INTEGER NOT NULL, auth_token_type TEXT NOT NULL DEFAULT \"\", uid INTEGER NOT NULL, UNIQUE (accounts_id, auth_token_type, uid));'")
    sh("sqlite3 /data/system_ce/0/accounts_ce.db 'CREATE TABLE IF NOT EXISTS shared_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name, type));'")

    # Verify
    tables = sh("sqlite3 /data/system_de/0/accounts_de.db '.tables'")
    log(f"  accounts_de tables: {tables}")
    return result

# ═════════════════════════════════════════════════════════════════════
# PHASE 5: ON-DEVICE CONTENT PROVIDER INJECTION (NO ROOT NEEDED)
# ═════════════════════════════════════════════════════════════════════

def inject_contacts_via_content(profile):
    """Inject contacts using content:// provider (runs as correct UID automatically)."""
    contacts = profile.get("contacts", [])
    if not contacts:
        log("  No contacts to inject")
        return 0

    log(f"  Injecting {len(contacts)} contacts via content provider...")
    count = 0
    for c in contacts:
        name = c.get("name", "").replace("'", "")
        phone = c.get("phone", "").replace("'", "")
        email_addr = c.get("email", "").replace("'", "")
        if not name:
            continue

        # Insert raw_contact
        rc_out = sh_raw(
            f"content insert --uri content://com.android.contacts/raw_contacts "
            f"--bind account_type:s:com.google --bind account_name:s:{PERSONA['email']}"
        )

        # Get the raw_contact_id from the last insert
        # Query for the latest raw_contact
        rc_id_out = sh_raw(
            "content query --uri content://com.android.contacts/raw_contacts "
            "--projection _id --sort '_id DESC' 2>/dev/null"
        )
        # Parse the _id from output like "Row: 0 _id=1"
        rc_id = None
        if rc_id_out:
            for line in rc_id_out.split("\n"):
                if "_id=" in line:
                    try:
                        rc_id = line.split("_id=")[1].split(",")[0].split()[0]
                    except:
                        pass
                    break

        if not rc_id:
            continue

        # Insert structured name
        if name:
            sh_raw(
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{rc_id} "
                f"--bind mimetype:s:vnd.android.cursor.item/name "
                f"--bind data1:s:'{shlex.quote(name)}'"
            )

        # Insert phone
        if phone:
            sh_raw(
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{rc_id} "
                f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                f"--bind data1:s:{phone} --bind data2:i:2"
            )

        # Insert email
        if email_addr:
            sh_raw(
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{rc_id} "
                f"--bind mimetype:s:vnd.android.cursor.item/email_v2 "
                f"--bind data1:s:{email_addr} --bind data2:i:1"
            )

        count += 1

    log(f"  Contacts injected: {count}")
    return count

def inject_call_logs_via_content(profile):
    """Inject call logs using content:// provider."""
    calls = profile.get("call_logs", [])
    if not calls:
        log("  No call logs to inject")
        return 0

    log(f"  Injecting {len(calls)} call logs via content provider...")
    count = 0
    for entry in calls:
        number = entry.get("number", "").replace("'", "")
        call_type = entry.get("type", 1)
        duration = entry.get("duration", 0)
        date_ms = entry.get("date", int(time.time() * 1000))

        sh_raw(
            f"content insert --uri content://call_log/calls "
            f"--bind number:s:{number} "
            f"--bind type:i:{call_type} "
            f"--bind date:l:{date_ms} "
            f"--bind duration:l:{duration} "
            f"--bind new:i:0"
        )
        count += 1

    log(f"  Call logs injected: {count}")
    return count

def inject_sms_via_content(profile):
    """Inject SMS using on-device sqlite3 batch (content insert has quoting issues with body text)."""
    messages = profile.get("sms", [])
    if not messages:
        log("  No SMS to inject")
        return 0

    log(f"  Injecting {len(messages)} SMS via on-device sqlite3 batch...")

    # Build SQL file with proper escaping
    sql_lines = [
        "CREATE TABLE IF NOT EXISTS sms ("
        "_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "address TEXT, body TEXT, type INTEGER DEFAULT 1, "
        "date INTEGER, read INTEGER DEFAULT 1, "
        "seen INTEGER DEFAULT 1, thread_id INTEGER DEFAULT 1);",
    ]
    count = 0
    for msg in messages[:500]:
        address = msg.get("address", "").replace("'", "''")
        body = msg.get("body", "")[:160].replace("'", "''")
        msg_type = msg.get("type", 1)
        date_ms = msg.get("date", int(time.time() * 1000))
        sql_lines.append(
            f"INSERT INTO sms(address, body, type, date, read, seen) "
            f"VALUES ('{address}', '{body}', {msg_type}, {date_ms}, 1, 1);"
        )
        count += 1

    # Write SQL file, push to device, execute
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
        f.write("\n".join(sql_lines))
        sql_path = f.name

    SMS_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
    adb(f"push {sql_path} /data/local/tmp/sms_batch.sql")
    sh(f"sqlite3 {SMS_DB} < /data/local/tmp/sms_batch.sql 2>/dev/null")
    sh("rm /data/local/tmp/sms_batch.sql")
    os.unlink(sql_path)

    # Fix ownership to telephony provider UID
    uid = sh("stat -c %U /data/data/com.android.providers.telephony 2>/dev/null")
    if uid and uid != "root":
        sh(f"chown {uid}:{uid} {SMS_DB}* 2>/dev/null")
        sh(f"chmod 660 {SMS_DB}* 2>/dev/null")
        sh(f"restorecon -R /data/data/com.android.providers.telephony/databases/ 2>/dev/null")

    log(f"  SMS injected: {count} (ownership → {uid})")
    return count

# ═════════════════════════════════════════════════════════════════════
# BROWSER DISCOVERY
# ═════════════════════════════════════════════════════════════════════

def discover_browser_package():
    """Find which browser is installed on device (Chrome, Kiwi, or webview shell)."""
    candidates = [
        "com.android.chrome",
        "com.kiwibrowser.browser",
        "com.chrome.beta",
        "com.chrome.dev",
        "org.chromium.webview_shell",
    ]
    for pkg in candidates:
        result = sh(f"pm path {pkg} 2>/dev/null")
        if result and "package:" in result:
            return pkg
    return None

# ═════════════════════════════════════════════════════════════════════
# PHASE 6: ROOT-REQUIRED INJECTIONS (Chrome, WiFi, Gallery, Autofill)
# Uses ProfileInjector's battle-tested methods for complex data
# ═════════════════════════════════════════════════════════════════════

def inject_root_required_data(profile):
    """Use ProfileInjector for Chrome, gallery, WiFi, autofill, app data, play purchases.
    These require root and have complex logic (EXIF building, DB schemas, ownership fixes)."""
    from profile_injector import ProfileInjector

    log("  Using ProfileInjector for Chrome/Gallery/WiFi/Autofill/AppData/PlayPurchases...")
    pi = ProfileInjector(adb_target=ADB_TARGET)

    # Ensure app data dirs exist
    pi._ensure_app_dirs()

    # Stop browser to avoid DB locks
    sh(f"am force-stop {pi._browser_pkg}")
    sh("am force-stop com.google.android.gms")
    time.sleep(1)

    # Chrome cookies + history
    cookies = profile.get("cookies", [])
    history = profile.get("history", [])
    log(f"  Injecting {len(cookies)} cookies, {len(history)} history entries...")
    pi._inject_cookies(cookies)
    pi._inject_history(history)

    # Local storage
    pi._inject_localstorage(profile.get("local_storage", {}))

    # Gallery (generates EXIF JPEGs if source files don't exist)
    gallery = profile.get("gallery_paths", [])
    log(f"  Injecting gallery ({len(gallery)} paths)...")
    pi._inject_gallery(gallery)

    # Autofill (name, email, phone, address into Chrome Web Data)
    autofill = profile.get("autofill", {})
    if autofill:
        log(f"  Injecting autofill data...")
        pi._inject_autofill(autofill)

    # Per-app SharedPrefs
    pi._inject_app_data(profile)

    # Play Store purchases
    purchases = profile.get("play_purchases", [])
    if purchases:
        log(f"  Injecting {len(purchases)} Play Store purchases...")
        pi._inject_play_purchases(profile)

    # WiFi networks
    wifi = profile.get("wifi_networks", [])
    if wifi:
        log(f"  Injecting {len(wifi)} WiFi networks...")
        pi._inject_wifi_networks(wifi)

    log(f"  ProfileInjector results: cookies={pi.result.cookies_injected}, "
        f"history={pi.result.history_injected}, photos={pi.result.photos_injected}, "
        f"autofill={pi.result.autofill_injected}")
    return pi.result

# ═════════════════════════════════════════════════════════════════════
# PHASE 7: WALLET / GOOGLE PAY
# ═════════════════════════════════════════════════════════════════════

def phase_wallet():
    log("═══ PHASE 7: GOOGLE PAY + WALLET ═══")
    try:
        from wallet_provisioner import WalletProvisioner
        wp = WalletProvisioner(adb_target=ADB_TARGET)

        exp = PERSONA["cc_exp"]
        if "/" in exp:
            parts = exp.split("/")
            exp_m = int(parts[0])
            exp_y = int(parts[1])
        else:
            exp_m = 8
            exp_y = 2029

        result = wp.provision_card(
            card_number=PERSONA["cc_number"],
            exp_month=exp_m,
            exp_year=exp_y,
            cardholder=PERSONA["cc_holder"],
            cvv=PERSONA["cc_cvv"],
            persona_email=PERSONA["email"],
            persona_name=PERSONA["name"],
            country="US",
            zero_auth=True,
        )

        # Fix wallet DB ownership
        wallet_uid = sh("stat -c '%U' /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
        if wallet_uid and wallet_uid != "root":
            sh(f"chown -R {wallet_uid}:{wallet_uid} /data/data/com.google.android.apps.walletnfcrel/databases/")
            sh("restorecon -R /data/data/com.google.android.apps.walletnfcrel/databases/ 2>/dev/null")

        gpay = getattr(result, "google_pay_ok", False)
        play = getattr(result, "play_store_ok", False)
        chrome = getattr(result, "chrome_autofill_ok", False)
        gms = getattr(result, "gms_billing_ok", False)
        log(f"  Wallet: GPay={gpay} Play={play} Chrome={chrome} GMS={gms}")
        return result
    except Exception as e:
        log(f"  Wallet FAILED: {e}")
        return None

# ═════════════════════════════════════════════════════════════════════
# PHASE 8: FIX OWNERSHIP (post-injection safety net)
# ═════════════════════════════════════════════════════════════════════

def fix_all_ownership():
    """Fix file ownership for all injected DBs using dynamic UID discovery."""
    log("  Fixing all file ownership...")

    # Static packages (always present)
    fixes = [
        ("com.android.providers.contacts", "/data/data/com.android.providers.contacts/databases/*"),
        ("com.android.providers.telephony", "/data/data/com.android.providers.telephony/databases/*"),
    ]

    # Dynamically discovered browser
    browser = discover_browser_package()
    if browser:
        chrome_dir = f"/data/data/{browser}/app_chrome/Default"
        if sh(f"ls {chrome_dir} 2>/dev/null"):
            fixes.append((browser, f"{chrome_dir}/*"))

    # Wallet if installed
    wallet_path = sh("pm path com.google.android.apps.walletnfcrel 2>/dev/null")
    if wallet_path and "package:" in wallet_path:
        fixes.append(("com.google.android.apps.walletnfcrel",
                      "/data/data/com.google.android.apps.walletnfcrel/databases/*"))

    for pkg, pattern in fixes:
        uid = sh(f"stat -c %U /data/data/{pkg} 2>/dev/null")
        if uid and uid != "root" and uid.strip():
            sh(f"chown {uid}:{uid} {pattern} 2>/dev/null")
            sh(f"chmod 660 {pattern} 2>/dev/null")
            sh(f"restorecon -R /data/data/{pkg} 2>/dev/null")
            log(f"    {pkg} → {uid}")

# ═════════════════════════════════════════════════════════════════════
# PHASE 9: TRUST SCORE
# ═════════════════════════════════════════════════════════════════════

def phase_trust_audit():
    log("═══ PHASE 9: TRUST AUDIT ═══")
    try:
        from trust_scorer import compute_trust_score
        score = compute_trust_score(ADB_TARGET)
        total = score.get("total", 0)
        grade = score.get("grade", "?")
        log(f"  Trust: {total}/100 ({grade})")
        if score.get("breakdown"):
            for k, v in score["breakdown"].items():
                log(f"    {k}: {v}")
        return total
    except Exception as e:
        log(f"  Trust audit failed: {e}")
        return 0

# ═════════════════════════════════════════════════════════════════════
# VERIFICATION
# ═════════════════════════════════════════════════════════════════════

def verify_all():
    log("═══ VERIFICATION ═══")

    checks = {
        "boot": sh("getprop sys.boot_completed"),
        "crashes": sh("logcat -d 2>/dev/null | grep -c 'FATAL EXCEPTION'"),
        "contacts": sh("content query --uri content://com.android.contacts/contacts 2>/dev/null | wc -l"),
        "call_logs": sh("content query --uri content://call_log/calls 2>/dev/null | wc -l"),
        "sms": sh("content query --uri content://sms 2>/dev/null | wc -l"),
        "accounts_de": sh("sqlite3 /data/system_de/0/accounts_de.db '.tables'"),
        "google_acct": sh("sqlite3 /data/system_de/0/accounts_de.db 'SELECT name FROM accounts'"),
        "calllog_owner": sh("ls -la /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null | awk '{print $3}'"),
        "contacts_owner": sh("ls -la /data/data/com.android.providers.contacts/databases/contacts2.db 2>/dev/null | awk '{print $3}'"),
    }

    for k, v in checks.items():
        status = "✓" if v and v != "0" and "radio" not in str(v) else "✗"
        log(f"  {status} {k}: {v}")

    return checks

# ═════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════

def main():
    log("╔══════════════════════════════════════════════════════════╗")
    log("║  TITAN V13 — GENESIS ORCHESTRATOR (SMART FLOW v2)       ║")
    log("║  Persona: Jovany OWENS                                   ║")
    log("║  Email: adiniorjuniorjd28@gmail.com                      ║")
    log("╠══════════════════════════════════════════════════════════╣")
    log("║  SEQUENCE:                                                ║")
    log("║  1. Wipe                                                  ║")
    log("║  2. ROOT: Accounts + SMS + WiFi + Purchases + calllog fix ║")
    log("║  3. Forge profile                                         ║")
    log("║  4. Stealth patch (hides root from RASP/apps)             ║")
    log("║  5. Reboot → proxy ON → Google sign-in (visual)          ║")
    log("║  6. Proxy OFF → download apps from Play Store             ║")
    log("║  7. Proxy ON → content-provider injection (contacts/calls)║")
    log("║  8. ROOT (adb root): Chrome + Gallery + Wallet injection  ║")
    log("║  9. Trust audit + verification                            ║")
    log("╚══════════════════════════════════════════════════════════╝")

    start = time.time()

    # ═══ PHASE 0: WIPE ═══
    phase_wipe()
    time.sleep(2)

    # ═══ PHASE 1: FORGE PROFILE (needed for injection data) ═══
    profile, profile_id = phase_forge_profile()

    # ═══ PHASE 2: PRE-PATCH ROOT INJECTIONS ═══
    # These need root AND must happen before stealth patch.
    # ADB root works on userdebug. After stealth patch, root is hidden
    # from on-device apps but adb root still works. However, it's cleaner
    # to do system-level DB writes before any anti-detection layers.
    log("═══ PHASE 2: PRE-PATCH ROOT INJECTIONS ═══")
    adb("root")
    time.sleep(2)

    # 2a: Google account into accounts_de.db / accounts_ce.db (system:system)
    phase_google_inject()

    # 2b: SMS into mmssms.db (radio:radio — telephony provider UID)
    inject_sms_via_content(profile)

    # 2c: WiFi networks into WifiConfigStore.xml (system:system)
    # Use ProfileInjector for WiFi — proper XML format
    from profile_injector import ProfileInjector
    pi = ProfileInjector(adb_target=ADB_TARGET)
    wifi = profile.get("wifi_networks", [])
    if wifi:
        log(f"  Injecting {len(wifi)} WiFi networks...")
        pi._inject_wifi_networks(wifi)

    # 2d: Play Store purchases into localappstate.db (u0_a110)
    purchases = profile.get("play_purchases", [])
    if purchases:
        log(f"  Injecting {len(purchases)} Play Store purchases...")
        pi._inject_play_purchases(profile)

    # 2e: Fix calllog.db ownership (radio:radio → u0_a19)
    # Cuttlefish creates calllog.db as radio:radio but contacts provider (u0_a19) can't read it
    log("  Fixing calllog.db ownership: radio → u0_a19...")
    sh("chown u0_a19:u0_a19 /data/data/com.android.providers.contacts/databases/calllog.db* 2>/dev/null")
    sh("chmod 660 /data/data/com.android.providers.contacts/databases/calllog.db* 2>/dev/null")
    owner_check = sh("stat -c %U /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null")
    log(f"  calllog.db owner: {owner_check}")

    # ═══ PHASE 3: STEALTH PATCH (26 phases, 3-6 min) ═══
    # Hides su binary, Magisk, emulator artifacts, proc mounts, etc.
    # ADB root still works after (userdebug build), but on-device
    # root detection (RootBeer, SafetyNet, MagiskDetector) will fail to find root.
    pct = phase_stealth_patch()

    # ═══ PHASE 4: REBOOT + PROXY ON ═══
    log("═══ PHASE 4: REBOOT + PROXY ═══")
    adb("reboot")
    time.sleep(5)
    wait_boot(timeout=300)
    time.sleep(15)  # Let services settle
    adb("root")
    time.sleep(2)

    # Fix calllog ownership again (reboot may recreate as radio:radio)
    sh("chown u0_a19:u0_a19 /data/data/com.android.providers.contacts/databases/calllog.db* 2>/dev/null")

    # Set proxy before any Google activity
    proxy_on()

    # ═══ PHASE 5: VISUAL GOOGLE SIGN-IN ═══
    log("")
    log("═══════════════════════════════════════════════════════")
    log("  ACTION: Sign into Google in Play Store")
    log(f"  Email: {PERSONA['email']}")
    log(f"  Password: {PERSONA['password']}")
    log("  Proxy is ON — sign in now through the Play Store app")
    log("═══════════════════════════════════════════════════════")
    log("")
    input("  Press ENTER when Google sign-in is complete...")

    # ═══ PHASE 6: PROXY OFF → DOWNLOAD APPS ═══
    log("═══ PHASE 6: PROXY OFF FOR DOWNLOADS ═══")
    proxy_off()

    log("")
    log("═══════════════════════════════════════════════════════")
    log("  ACTION: Download apps from Play Store")
    log("  Proxy is OFF — download large apps now")
    log("  REQUIRED: Chrome (or Kiwi), Google Wallet/Pay")
    log("  OPTIONAL: Maps, YouTube, Gmail, Photos, banking apps")
    log("═══════════════════════════════════════════════════════")
    log("")
    input("  Press ENTER when app downloads are complete...")

    # ═══ PHASE 7: PROXY ON → CONTENT PROVIDER INJECTION ═══
    log("═══ PHASE 7: PROXY ON + CONTENT PROVIDER INJECTION ═══")
    proxy_on()

    # These use content:// URIs — no root needed, correct UID automatically
    inject_contacts_via_content(profile)
    inject_call_logs_via_content(profile)

    # Gallery to /sdcard/ — world-writable, no root needed
    log("  Injecting gallery photos...")
    pi._inject_gallery(profile.get("gallery_paths", []))

    # ═══ PHASE 8: POST-DOWNLOAD ROOT INJECTIONS ═══
    # ADB root still works on userdebug even after stealth patch.
    # Now that Chrome/Wallet are installed from Play Store, we can
    # discover their dynamic UIDs and inject with correct ownership.
    log("═══ PHASE 8: POST-DOWNLOAD ROOT INJECTIONS ═══")
    adb("root")
    time.sleep(2)

    # Discover which browser is installed and inject Chrome data
    browser_pkg = discover_browser_package()
    if browser_pkg:
        log(f"  Browser found: {browser_pkg}")
        # Re-init ProfileInjector with fresh browser detection
        pi2 = ProfileInjector(adb_target=ADB_TARGET)
        log(f"  Browser data dir: {pi2._browser_data}")

        # Stop browser to avoid DB locks
        sh(f"am force-stop {browser_pkg}")
        time.sleep(1)

        # Inject cookies + history
        pi2._inject_cookies(profile.get("cookies", []))
        pi2._inject_history(profile.get("history", []))
        pi2._inject_localstorage(profile.get("local_storage", {}))
        pi2._inject_autofill(profile.get("autofill", {}))
    else:
        log("  ⚠ No browser found — skipping Chrome data injection")

    # Per-app SharedPrefs (GMS, Play Store, etc.)
    pi._inject_app_data(profile)

    # ═══ PHASE 9: WALLET / GOOGLE PAY ═══
    phase_wallet()

    # ═══ PHASE 10: FINAL OWNERSHIP FIX ═══
    fix_all_ownership()

    # Fix calllog ownership one last time
    sh("chown u0_a19:u0_a19 /data/data/com.android.providers.contacts/databases/calllog.db* 2>/dev/null")

    # ═══ PHASE 11: TRUST AUDIT ═══
    trust = phase_trust_audit()

    # ═══ VERIFICATION ═══
    verify_all()

    elapsed = int(time.time() - start)
    log(f"\n═══ GENESIS COMPLETE in {elapsed}s ═══")
    log(f"  Profile: {profile_id}")
    log(f"  Trust: {trust}/100")
    log(f"  Stealth: {pct}%")


if __name__ == "__main__":
    main()
