#!/usr/bin/env python3
"""Inject contacts directly into contacts2.db SQLite database."""
import json
import subprocess
import os
import sys
import time

ADB = "/opt/titan/cuttlefish/cf/bin/adb"
TARGET = "0.0.0.0:6520"
PROFILE_PATH = "/opt/titan/data/profiles/TITAN-600A897C.json"
CONTACTS_DB = "/data/data/com.android.providers.contacts/databases/contacts2.db"

def adb_shell(cmd, timeout=30):
    try:
        r = subprocess.run([ADB, "-s", TARGET, "shell", cmd],
                         capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

def adb_push(local, remote, timeout=30):
    try:
        r = subprocess.run([ADB, "-s", TARGET, "push", local, remote],
                         capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except:
        return False

def sqlite_exec(db, sql, timeout=15):
    """Execute SQL on device database via sqlite3."""
    # Escape single quotes in SQL
    escaped = sql.replace("'", "'\"'\"'")
    return adb_shell(f"sqlite3 {db} '{escaped}'", timeout=timeout)

def main():
    print("Loading profile...")
    with open(PROFILE_PATH) as f:
        profile = json.load(f)
    
    contacts = profile.get("contacts", [])
    gallery_paths = profile.get("gallery_paths", [])
    print(f"Contacts: {len(contacts)}, Gallery: {len(gallery_paths)}")
    
    # Verify boot
    boot = adb_shell("getprop sys.boot_completed")
    print(f"boot_completed: {boot}")
    
    # First ensure the contacts provider process is stopped so we can write to DB safely
    adb_shell("am force-stop com.android.providers.contacts")
    time.sleep(1)
    
    # Get mimetype IDs
    mimetypes = sqlite_exec(CONTACTS_DB, "SELECT _id, mimetype FROM mimetypes")
    mime_map = {}
    for line in mimetypes.split('\n'):
        if '|' in line:
            parts = line.split('|')
            mime_map[parts[1]] = int(parts[0])
    
    print(f"Mime types: {mime_map}")
    
    # Ensure we have the needed mimetypes
    needed = {
        'vnd.android.cursor.item/name': None,
        'vnd.android.cursor.item/phone_v2': None,
        'vnd.android.cursor.item/email_v2': None,
    }
    
    for mt in needed:
        if mt in mime_map:
            needed[mt] = mime_map[mt]
        else:
            # Insert missing mimetype
            sqlite_exec(CONTACTS_DB, f"INSERT INTO mimetypes (mimetype) VALUES ('{mt}')")
            result = sqlite_exec(CONTACTS_DB, f"SELECT _id FROM mimetypes WHERE mimetype='{mt}'")
            needed[mt] = int(result.strip())
    
    name_mime = needed['vnd.android.cursor.item/name']
    phone_mime = needed['vnd.android.cursor.item/phone_v2']
    email_mime = needed['vnd.android.cursor.item/email_v2']
    
    print(f"name_mime={name_mime}, phone_mime={phone_mime}, email_mime={email_mime}")
    
    # Ensure account exists
    acct = sqlite_exec(CONTACTS_DB, "SELECT _id FROM accounts LIMIT 1")
    if not acct.strip():
        sqlite_exec(CONTACTS_DB, "INSERT INTO accounts (_id, account_name, account_type) VALUES (1, 'Phone', 'local')")
        acct_id = 1
    else:
        acct_id = int(acct.strip())
    print(f"Account ID: {acct_id}")
    
    # Build SQL for batch insert
    print(f"\n=== Injecting {len(contacts)} contacts ===")
    
    # Build a SQL script file for efficiency
    sql_lines = []
    sql_lines.append("BEGIN TRANSACTION;")
    
    for i, contact in enumerate(contacts):
        name = contact.get("name", "Unknown").replace("'", "''")
        phone = contact.get("phone", "").replace("'", "''")
        email = contact.get("email", "").replace("'", "''")
        
        # Split name for sort key
        parts = name.split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
        display_alt = f"{last}, {first}" if last else first
        
        rid = i + 1  # raw_contact_id starting from 1
        cid = i + 1  # contact_id
        
        # Insert raw_contact
        sql_lines.append(
            f"INSERT INTO raw_contacts (_id, account_id, display_name, display_name_alt, "
            f"display_name_source, version, aggregation_needed) "
            f"VALUES ({rid}, {acct_id}, '{name}', '{display_alt}', 40, 1, 1);"
        )
        
        # Insert contact
        sql_lines.append(
            f"INSERT OR IGNORE INTO contacts (_id, name_raw_contact_id, "
            f"times_contacted, last_time_contacted, starred, pinned, has_phone_number) "
            f"VALUES ({cid}, {rid}, 0, 0, 0, 0, {1 if phone else 0});"
        )
        
        # Link raw_contact to contact
        sql_lines.append(
            f"UPDATE raw_contacts SET contact_id={cid} WHERE _id={rid};"
        )
        
        # Insert name data
        sql_lines.append(
            f"INSERT INTO data (mimetype_id, raw_contact_id, is_primary, is_super_primary, "
            f"data1, data2, data3) "
            f"VALUES ({name_mime}, {rid}, 1, 1, '{name}', '{first}', '{last}');"
        )
        
        # Insert phone
        if phone:
            sql_lines.append(
                f"INSERT INTO data (mimetype_id, raw_contact_id, is_primary, is_super_primary, "
                f"data1, data2) "
                f"VALUES ({phone_mime}, {rid}, 1, 1, '{phone}', 2);"
            )
        
        # Insert email
        if email:
            sql_lines.append(
                f"INSERT INTO data (mimetype_id, raw_contact_id, is_primary, is_super_primary, "
                f"data1, data2) "
                f"VALUES ({email_mime}, {rid}, 0, 0, '{email}', 1);"
            )
    
    sql_lines.append("COMMIT;")
    
    # Write SQL script to temp file and push to device
    sql_script = "\n".join(sql_lines)
    local_sql = "/tmp/inject_contacts.sql"
    with open(local_sql, "w") as f:
        f.write(sql_script)
    
    print(f"SQL script: {len(sql_lines)} statements")
    
    # Push and execute
    adb_push(local_sql, "/data/local/tmp/inject_contacts.sql")
    result = adb_shell(f"sqlite3 {CONTACTS_DB} < /data/local/tmp/inject_contacts.sql 2>&1")
    if result:
        print(f"SQL result: {result[:500]}")
    
    # Fix ownership
    adb_shell(f"chown u0_a19:u0_a19 {CONTACTS_DB}")
    adb_shell(f"chown u0_a19:u0_a19 {CONTACTS_DB}-journal 2>/dev/null")
    
    # Verify
    count = sqlite_exec(CONTACTS_DB, "SELECT COUNT(*) FROM raw_contacts")
    print(f"Contacts in DB: {count}")
    
    # === GALLERY ===
    print(f"\n=== Injecting gallery ===")
    adb_shell("mkdir -p /sdcard/DCIM/Camera /sdcard/Pictures")
    
    pushed = 0
    for i, path in enumerate(gallery_paths):
        if os.path.exists(path):
            fname = os.path.basename(path)
            if adb_push(path, f"/sdcard/DCIM/Camera/{fname}"):
                pushed += 1
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(gallery_paths)}] pushed: {pushed}")
    
    if pushed == 0:
        forge_dir = "/opt/titan/data/forge_gallery"
        if os.path.isdir(forge_dir):
            photos = [os.path.join(forge_dir, f) for f in os.listdir(forge_dir)
                      if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            print(f"  Trying {len(photos)} from forge_gallery/...")
            for p in photos:
                if adb_push(p, f"/sdcard/DCIM/Camera/{os.path.basename(p)}"):
                    pushed += 1
    
    if pushed > 0:
        adb_shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Camera/")
    
    print(f"  Gallery pushed: {pushed}")
    
    gc = adb_shell("ls /sdcard/DCIM/Camera/ 2>/dev/null | wc -l")
    print(f"\n=== FINAL ===")
    print(f"Contacts in DB: {count}")
    print(f"Gallery files: {gc}")

if __name__ == "__main__":
    main()
