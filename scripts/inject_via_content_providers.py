#!/usr/bin/env python3
"""
On-device injection via Android Content Providers.

Instead of ADB push (which creates root:root ownership → crashes),
this script uses `content insert` commands that run through the
Android content provider framework with correct UID ownership.

NO ROOT NEEDED for: contacts, call logs, SMS
ROOT NEEDED for:    accounts_de/ce (sqlite3 direct), Chrome data (push)

Usage:
    python3 scripts/inject_via_content_providers.py [--profile TITAN-XXXX] [--target 0.0.0.0:6520]
"""

import json
import os
import sys
import glob
import time
import subprocess
import shlex
import argparse
import tempfile

ADB_TARGET = os.environ.get("TITAN_ADB_TARGET", "0.0.0.0:6520")
PROFILE_DIR = "/opt/titan/data/profiles"


def adb_shell(target: str, cmd: str, timeout: int = 15) -> str:
    """Run ADB shell command, return stdout."""
    try:
        r = subprocess.run(
            f'adb -s {target} shell {shlex.quote(cmd)}',
            shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


def adb_shell_raw(target: str, cmd: str, timeout: int = 15) -> tuple:
    """Run ADB shell returning (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            f'adb -s {target} shell {shlex.quote(cmd)}',
            shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def escape_content_val(s: str) -> str:
    """Escape a string for content insert --bind value.
    Single quotes in values need careful escaping for adb shell."""
    if not s:
        return ""
    return s.replace("'", "'\\''").replace('"', '\\"')


# ─── CONTACTS (NO ROOT) ──────────────────────────────────────────────

def inject_contacts(target: str, contacts: list) -> int:
    """Inject contacts via content://com.android.contacts provider.
    Runs as shell user — provider handles UID correctly."""
    count = 0
    for c in contacts:
        name = c.get("name", "")
        phone = c.get("phone", "")
        email = c.get("email", "")
        if not name:
            continue

        # Step 1: Insert raw_contact
        rc, out, _ = adb_shell_raw(target,
            'content insert --uri content://com.android.contacts/raw_contacts '
            '--bind account_type:s: --bind account_name:s:')
        if rc != 0:
            continue

        # Get the raw_contact_id from the URI returned
        # Format: "Uri: content://com.android.contacts/raw_contacts/N"
        raw_id = None
        for line in out.split('\n'):
            if 'raw_contacts/' in line:
                raw_id = line.rsplit('/', 1)[-1].strip()
                break
        if not raw_id:
            # Try getting the last inserted ID
            _, last_out, _ = adb_shell_raw(target,
                'content query --uri content://com.android.contacts/raw_contacts '
                '--projection _id --sort "_id DESC LIMIT 1"')
            if '_id=' in last_out:
                raw_id = last_out.split('_id=')[1].split(',')[0].strip()
        if not raw_id:
            continue

        # Step 2: Insert display name
        esc_name = escape_content_val(name)
        adb_shell(target,
            f'content insert --uri content://com.android.contacts/data '
            f'--bind raw_contact_id:i:{raw_id} '
            f'--bind mimetype:s:vnd.android.cursor.item/name '
            f"--bind data1:s:'{esc_name}'")

        # Step 3: Insert phone number
        if phone:
            esc_phone = escape_content_val(phone)
            adb_shell(target,
                f'content insert --uri content://com.android.contacts/data '
                f'--bind raw_contact_id:i:{raw_id} '
                f'--bind mimetype:s:vnd.android.cursor.item/phone_v2 '
                f"--bind data1:s:'{esc_phone}' "
                f'--bind data2:i:2')

        # Step 4: Insert email
        if email:
            esc_email = escape_content_val(email)
            adb_shell(target,
                f'content insert --uri content://com.android.contacts/data '
                f'--bind raw_contact_id:i:{raw_id} '
                f'--bind mimetype:s:vnd.android.cursor.item/email_v2 '
                f"--bind data1:s:'{esc_email}' "
                f'--bind data2:i:1')

        count += 1
        if count % 10 == 0:
            print(f"  Contacts: {count}/{len(contacts)}")

    return count


# ─── CALL LOGS (NO ROOT) ─────────────────────────────────────────────

def inject_call_logs(target: str, call_logs: list) -> int:
    """Inject call logs via content://call_log/calls provider.
    No root needed — provider runs as correct UID."""
    count = 0
    for log in call_logs:
        number = log.get("number", "")
        call_type = log.get("type", 1)  # 1=incoming, 2=outgoing, 3=missed
        duration = log.get("duration", 0)
        date_ms = log.get("date", int(time.time() * 1000))

        if not number:
            continue

        esc_num = escape_content_val(number)
        rc, _, _ = adb_shell_raw(target,
            f'content insert --uri content://call_log/calls '
            f"--bind number:s:'{esc_num}' "
            f'--bind date:l:{date_ms} '
            f'--bind duration:i:{duration} '
            f'--bind type:i:{call_type} '
            f'--bind new:i:0')

        if rc == 0:
            count += 1
        if count % 50 == 0 and count > 0:
            print(f"  Call logs: {count}/{len(call_logs)}")

    return count


# ─── SMS (NO ROOT) ───────────────────────────────────────────────────

def inject_sms(target: str, messages: list) -> int:
    """Inject SMS via content://sms provider.
    No root needed — provider runs as correct UID."""
    count = 0
    for msg in messages:
        address = msg.get("address", "")
        body = msg.get("body", "")
        msg_type = msg.get("type", 1)  # 1=inbox, 2=sent
        date_ms = msg.get("date", int(time.time() * 1000))

        if not address or not body:
            continue

        esc_addr = escape_content_val(address)
        esc_body = escape_content_val(body)
        rc, _, _ = adb_shell_raw(target,
            f'content insert --uri content://sms '
            f"--bind address:s:'{esc_addr}' "
            f"--bind body:s:'{esc_body}' "
            f'--bind type:i:{msg_type} '
            f'--bind date:l:{date_ms} '
            f'--bind read:i:1 '
            f'--bind seen:i:1')

        if rc == 0:
            count += 1
        if count % 20 == 0 and count > 0:
            print(f"  SMS: {count}/{len(messages)}")

    return count


# ─── ACCOUNTS DB (ROOT NEEDED — sqlite3 on device) ──────────────────

def fix_accounts_de_schema(target: str) -> bool:
    """Ensure accounts_de.db has all required tables.
    ROOT NEEDED: system_de is only writable by root/system."""
    sql = """
CREATE TABLE IF NOT EXISTS grants (
    accounts_id INTEGER NOT NULL,
    auth_token_type TEXT NOT NULL DEFAULT '',
    uid INTEGER NOT NULL,
    UNIQUE (accounts_id, auth_token_type, uid)
);
CREATE TABLE IF NOT EXISTS visibility (
    accounts_id INTEGER NOT NULL,
    _package TEXT NOT NULL,
    value INTEGER,
    UNIQUE (accounts_id, _package)
);
CREATE TABLE IF NOT EXISTS authtokens (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    accounts_id INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    authtoken TEXT,
    UNIQUE (accounts_id, type)
);
CREATE TABLE IF NOT EXISTS extras (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    accounts_id INTEGER NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    value TEXT,
    UNIQUE (accounts_id, key)
);
CREATE TABLE IF NOT EXISTS shared_accounts (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    UNIQUE(name, type)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT
);
PRAGMA user_version = 3;
"""
    out = adb_shell(target,
        f"sqlite3 /data/system_de/0/accounts_de.db '{sql}'",
        timeout=10)
    tables = adb_shell(target,
        "sqlite3 /data/system_de/0/accounts_de.db '.tables'")
    print(f"  accounts_de tables: {tables}")
    return "grants" in tables and "visibility" in tables


def fix_accounts_ce_schema(target: str) -> bool:
    """Ensure accounts_ce.db has grants + shared_accounts.
    ROOT NEEDED: system_ce is only writable by root/system."""
    sql = """
CREATE TABLE IF NOT EXISTS grants (
    accounts_id INTEGER NOT NULL,
    auth_token_type TEXT NOT NULL DEFAULT '',
    uid INTEGER NOT NULL,
    UNIQUE (accounts_id, auth_token_type, uid)
);
CREATE TABLE IF NOT EXISTS shared_accounts (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    UNIQUE(name, type)
);
"""
    adb_shell(target,
        f"sqlite3 /data/system_ce/0/accounts_ce.db '{sql}'",
        timeout=10)
    tables = adb_shell(target,
        "sqlite3 /data/system_ce/0/accounts_ce.db '.tables'")
    print(f"  accounts_ce tables: {tables}")
    return "grants" in tables


# ─── CALLLOG/CONTACTS OWNERSHIP FIX (ROOT) ──────────────────────────

def fix_contacts_db_ownership(target: str) -> None:
    """Fix calllog.db ownership if still radio:radio.
    ROOT NEEDED for chown."""
    uid = adb_shell(target,
        "stat -c %U /data/data/com.android.providers.contacts 2>/dev/null")
    if not uid:
        uid = "u0_a19"

    db_dir = "/data/data/com.android.providers.contacts/databases"
    for db in ["calllog.db", "calllog.db-journal",
               "contacts2.db", "contacts2.db-shm", "contacts2.db-wal"]:
        path = f"{db_dir}/{db}"
        current = adb_shell(target, f"stat -c %U {path} 2>/dev/null")
        if current and current != uid:
            adb_shell(target, f"chown {uid}:{uid} {path}")
            adb_shell(target, f"chmod 660 {path}")
            print(f"  Fixed {db}: {current} → {uid}")

    adb_shell(target, f"restorecon -R {db_dir} 2>/dev/null")


# ─── MAIN ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Inject profile via content providers")
    parser.add_argument("--profile", help="Profile ID (e.g., TITAN-9871A3F9)")
    parser.add_argument("--target", default=ADB_TARGET, help="ADB target")
    parser.add_argument("--skip-contacts", action="store_true")
    parser.add_argument("--skip-calls", action="store_true")
    parser.add_argument("--skip-sms", action="store_true")
    parser.add_argument("--skip-accounts", action="store_true")
    args = parser.parse_args()

    target = args.target

    # Find profile
    if args.profile:
        profile_path = os.path.join(PROFILE_DIR, f"{args.profile}.json")
    else:
        profiles = sorted(
            glob.glob(os.path.join(PROFILE_DIR, "TITAN-*.json")),
            key=os.path.getmtime, reverse=True
        )
        if not profiles:
            print("ERROR: No profiles found")
            sys.exit(1)
        profile_path = profiles[0]

    print(f"Loading profile: {profile_path}")
    with open(profile_path) as f:
        profile = json.load(f)

    uuid = profile.get("uuid", "unknown")
    print(f"Profile: {uuid}")
    print(f"  Contacts: {len(profile.get('contacts', []))}")
    print(f"  Call logs: {len(profile.get('call_logs', []))}")
    print(f"  SMS: {len(profile.get('sms', []))}")

    # Verify device is booted
    boot = adb_shell(target, "getprop sys.boot_completed")
    if boot != "1":
        print("ERROR: Device not booted")
        sys.exit(1)

    print("\n═══ PHASE 1: Fix accounts schemas (ROOT) ═══")
    if not args.skip_accounts:
        fix_accounts_de_schema(target)
        fix_accounts_ce_schema(target)
    else:
        print("  Skipped")

    print("\n═══ PHASE 2: Fix DB ownership (ROOT) ═══")
    fix_contacts_db_ownership(target)

    print("\n═══ PHASE 3: Inject contacts (NO ROOT) ═══")
    if not args.skip_contacts:
        contacts = profile.get("contacts", [])
        if contacts:
            n = inject_contacts(target, contacts)
            print(f"  Done: {n} contacts injected via content provider")
        else:
            print("  No contacts in profile")
    else:
        print("  Skipped")

    print("\n═══ PHASE 4: Inject call logs (NO ROOT) ═══")
    if not args.skip_calls:
        calls = profile.get("call_logs", [])
        if calls:
            n = inject_call_logs(target, calls)
            print(f"  Done: {n} call logs injected via content provider")
        else:
            print("  No call logs in profile")
    else:
        print("  Skipped")

    print("\n═══ PHASE 5: Inject SMS (NO ROOT) ═══")
    if not args.skip_sms:
        sms = profile.get("sms", [])
        if sms:
            n = inject_sms(target, sms)
            print(f"  Done: {n} SMS injected via content provider")
        else:
            print("  No SMS in profile")
    else:
        print("  Skipped")

    print("\n═══ PHASE 6: Verify ═══")
    # Verify counts via content query
    contacts_out = adb_shell(target,
        "content query --uri content://com.android.contacts/contacts --projection _id 2>/dev/null | wc -l")
    calls_out = adb_shell(target,
        "content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l")
    sms_out = adb_shell(target,
        "content query --uri content://sms --projection _id 2>/dev/null | wc -l")

    print(f"  Contacts on device: {contacts_out}")
    print(f"  Call logs on device: {calls_out}")
    print(f"  SMS on device: {sms_out}")

    # Check ownership after injection
    print("\n═══ PHASE 7: Post-injection ownership check ═══")
    for db in ["calllog.db", "contacts2.db"]:
        owner = adb_shell(target,
            f"stat -c '%U:%G' /data/data/com.android.providers.contacts/databases/{db} 2>/dev/null")
        print(f"  {db}: {owner}")

    mmssms = adb_shell(target,
        "stat -c '%U:%G' /data/data/com.android.providers.telephony/databases/mmssms.db 2>/dev/null")
    print(f"  mmssms.db: {mmssms}")

    print("\n═══ COMPLETE ═══")
    crash_count = adb_shell(target,
        "logcat -d 2>/dev/null | grep -c 'FATAL EXCEPTION'")
    print(f"  Crash count: {crash_count}")


if __name__ == "__main__":
    main()
