#!/usr/bin/env python3
"""Inject contacts and gallery into device from profile TITAN-600A897C - v2."""
import json
import subprocess
import os
import sys
import time
import re

ADB = "/opt/titan/cuttlefish/cf/bin/adb"
TARGET = "0.0.0.0:6520"
PROFILE_PATH = "/opt/titan/data/profiles/TITAN-600A897C.json"

def adb_shell(cmd, timeout=30):
    try:
        r = subprocess.run(
            [ADB, "-s", TARGET, "shell", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as e:
        return f"[ERROR: {e}]"

def adb_push(local, remote, timeout=30):
    try:
        r = subprocess.run(
            [ADB, "-s", TARGET, "push", local, remote],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0
    except Exception:
        return False

def inject_contact_simple(name, phone, email=""):
    """Inject a single contact using separate content provider calls."""
    # Insert raw contact
    adb_shell("content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s:local --bind account_name:s:Phone")
    
    # Get the last inserted raw_contact ID
    out = adb_shell("content query --uri content://com.android.contacts/raw_contacts --projection _id --sort \"_id DESC\" 2>&1 | head -1")
    
    # Parse ID from "Row: 0 _id=1"
    m = re.search(r'_id=(\d+)', out)
    if not m:
        return False
    rid = m.group(1)
    
    # Insert structured name
    safe_name = name.replace('"', '\\"').replace("'", "\\'")
    adb_shell(
        f'content insert --uri content://com.android.contacts/data '
        f'--bind raw_contact_id:i:{rid} '
        f'--bind mimetype:s:vnd.android.cursor.item/name '
        f'--bind data1:s:"{safe_name}"'
    )
    
    # Insert phone
    if phone:
        safe_phone = phone.replace('"', '')
        adb_shell(
            f'content insert --uri content://com.android.contacts/data '
            f'--bind raw_contact_id:i:{rid} '
            f'--bind mimetype:s:vnd.android.cursor.item/phone_v2 '
            f'--bind data1:s:"{safe_phone}" '
            f'--bind data2:i:2'
        )
    
    # Insert email
    if email:
        safe_email = email.replace('"', '')
        adb_shell(
            f'content insert --uri content://com.android.contacts/data '
            f'--bind raw_contact_id:i:{rid} '
            f'--bind mimetype:s:vnd.android.cursor.item/email_v2 '
            f'--bind data1:s:"{safe_email}" '
            f'--bind data2:i:1'
        )
    
    return True

def generate_vcf(contacts):
    """Generate VCF file from contacts list."""
    vcf_lines = []
    for c in contacts:
        name = c.get("name", "Unknown")
        phone = c.get("phone", "")
        email = c.get("email", "")
        parts = name.split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
        
        vcf_lines.append("BEGIN:VCARD")
        vcf_lines.append("VERSION:3.0")
        vcf_lines.append(f"FN:{name}")
        vcf_lines.append(f"N:{last};{first};;;")
        if phone:
            vcf_lines.append(f"TEL;TYPE=CELL:{phone}")
        if email:
            vcf_lines.append(f"EMAIL;TYPE=HOME:{email}")
        vcf_lines.append("END:VCARD")
    
    return "\n".join(vcf_lines)


def main():
    print("Loading profile...")
    with open(PROFILE_PATH) as f:
        profile = json.load(f)
    
    contacts = profile.get("contacts", [])
    gallery_paths = profile.get("gallery_paths", [])
    
    print(f"Contacts: {len(contacts)}, Gallery: {len(gallery_paths)}")
    
    boot = adb_shell("getprop sys.boot_completed")
    print(f"boot_completed: {boot}")
    if boot != "1":
        print("ERROR: Device not booted!")
        sys.exit(1)
    
    # === CONTACTS VIA VCF ===
    print(f"\n=== Injecting {len(contacts)} contacts via VCF ===")
    vcf_content = generate_vcf(contacts)
    vcf_path = "/tmp/titan_contacts.vcf"
    with open(vcf_path, "w") as f:
        f.write(vcf_content)
    
    # Push VCF to device
    subprocess.run([ADB, "-s", TARGET, "push", vcf_path, "/sdcard/contacts.vcf"], 
                   capture_output=True, timeout=30)
    
    # Try direct content provider method contact by contact
    success = 0
    for i, c in enumerate(contacts):
        name = c.get("name", "Unknown")
        phone = c.get("phone", "")
        email = c.get("email", "")
        
        ok = inject_contact_simple(name, phone, email)
        if ok:
            success += 1
        else:
            print(f"  FAIL: {name}")
        
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(contacts)}]...")
    
    print(f"  Contacts injected: {success}/{len(contacts)}")
    
    # === GALLERY ===
    print(f"\n=== Injecting gallery photos ===")
    adb_shell("mkdir -p /sdcard/DCIM/Camera /sdcard/Pictures")
    
    pushed = 0
    for i, path in enumerate(gallery_paths):
        if os.path.exists(path):
            fname = os.path.basename(path)
            if adb_push(path, f"/sdcard/DCIM/Camera/{fname}"):
                pushed += 1
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(gallery_paths)}] pushed {pushed}...")
    
    if pushed == 0:
        # Try forge gallery directory
        forge_dir = "/opt/titan/data/forge_gallery"
        if os.path.isdir(forge_dir):
            photos = [os.path.join(forge_dir, f) for f in os.listdir(forge_dir) 
                      if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            print(f"  Trying {len(photos)} photos from {forge_dir}...")
            for p in photos:
                if adb_push(p, f"/sdcard/DCIM/Camera/{os.path.basename(p)}"):
                    pushed += 1
    
    # Trigger media scan
    if pushed > 0:
        adb_shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Camera/")
    
    print(f"  Gallery pushed: {pushed}")
    
    # === VERIFY ===
    time.sleep(2)
    cc = adb_shell("content query --uri content://com.android.contacts/raw_contacts --projection _id 2>&1 | grep -c Row")
    gc = adb_shell("ls /sdcard/DCIM/Camera/ 2>/dev/null | wc -l")
    print(f"\n=== FINAL ===")
    print(f"Contacts on device: {cc}")
    print(f"Gallery files: {gc}")


if __name__ == "__main__":
    main()
