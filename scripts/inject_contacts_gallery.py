#!/usr/bin/env python3
"""Inject contacts and gallery into device from profile TITAN-600A897C."""
import json
import subprocess
import os
import sys
import time

ADB = "/opt/titan/cuttlefish/cf/bin/adb"
TARGET = "0.0.0.0:6520"
PROFILE_PATH = "/opt/titan/data/profiles/TITAN-600A897C.json"

def adb_shell(cmd, timeout=30):
    """Run ADB shell command and return output."""
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
    """Push file to device."""
    try:
        r = subprocess.run(
            [ADB, "-s", TARGET, "push", local, remote],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception as e:
        return f"[ERROR: {e}]"

def inject_contacts(contacts):
    """Inject contacts via content provider."""
    print(f"\n=== Injecting {len(contacts)} contacts ===")
    success = 0
    for i, contact in enumerate(contacts):
        name = contact.get("name", "Unknown")
        phone = contact.get("phone", "")
        email = contact.get("email", "")
        
        # Insert raw contact
        raw_id = adb_shell(
            "content insert --uri content://com.android.contacts/raw_contacts "
            "--bind account_type:s:local --bind account_name:s:Phone && "
            "content query --uri content://com.android.contacts/raw_contacts "
            "--projection _id --sort \"_id DESC LIMIT 1\""
        )
        
        # Parse the raw contact ID
        rid = None
        if "Row:" in raw_id:
            for part in raw_id.split(","):
                if "_id=" in part:
                    rid = part.split("=")[-1].strip()
                    break
        
        if not rid:
            # Try alternative: just get max ID
            rid_out = adb_shell(
                "content query --uri content://com.android.contacts/raw_contacts "
                "--projection _id --sort \"_id DESC LIMIT 1\""
            )
            if "Row:" in rid_out:
                for part in rid_out.split(","):
                    if "_id=" in part:
                        rid = part.split("=")[-1].strip()
                        break
        
        if not rid:
            print(f"  [{i+1}] FAIL: Could not get raw_contact ID for {name}")
            continue
        
        # Insert display name
        adb_shell(
            f"content insert --uri content://com.android.contacts/data "
            f"--bind raw_contact_id:i:{rid} "
            f"--bind mimetype:s:vnd.android.cursor.item/name "
            f"--bind data1:s:\"{name}\""
        )
        
        # Insert phone number
        if phone:
            adb_shell(
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{rid} "
                f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                f"--bind data1:s:\"{phone}\" "
                f"--bind data2:i:2"
            )
        
        # Insert email
        if email:
            adb_shell(
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{rid} "
                f"--bind mimetype:s:vnd.android.cursor.item/email_v2 "
                f"--bind data1:s:\"{email}\" "
                f"--bind data2:i:1"
            )
        
        success += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(contacts)}] injected...")
    
    print(f"  Contacts injected: {success}/{len(contacts)}")
    return success

def inject_gallery(gallery_paths):
    """Push gallery photos to device."""
    print(f"\n=== Injecting {len(gallery_paths)} gallery photos ===")
    
    # Create DCIM directories
    adb_shell("mkdir -p /sdcard/DCIM/Camera /sdcard/Pictures")
    
    success = 0
    for i, path in enumerate(gallery_paths):
        if os.path.exists(path):
            fname = os.path.basename(path)
            result = adb_push(path, f"/sdcard/DCIM/Camera/{fname}")
            if "ERROR" not in result and "error" not in result.lower():
                success += 1
            else:
                print(f"  Push failed for {fname}: {result}")
        else:
            print(f"  File not found: {path}")
    
    # Trigger media scan
    if success > 0:
        adb_shell(
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            "-d file:///sdcard/DCIM/Camera/"
        )
        # Also use media scanner
        adb_shell(
            "content call --uri content://media/none/fs_operation "
            "--method scan_volume --arg external_primary 2>/dev/null || true"
        )
    
    print(f"  Gallery photos pushed: {success}/{len(gallery_paths)}")
    return success


def main():
    print("Loading profile...")
    with open(PROFILE_PATH) as f:
        profile = json.load(f)
    
    contacts = profile.get("contacts", [])
    gallery_paths = profile.get("gallery_paths", [])
    
    print(f"Profile: {profile.get('profile_id', 'unknown')}")
    print(f"Contacts in profile: {len(contacts)}")
    print(f"Gallery paths in profile: {len(gallery_paths)}")
    
    # Check device is responsive
    boot = adb_shell("getprop sys.boot_completed")
    print(f"Device boot_completed: {boot}")
    if boot != "1":
        print("ERROR: Device not fully booted!")
        sys.exit(1)
    
    # Inject contacts
    if contacts:
        inject_contacts(contacts)
    
    # Inject gallery
    if gallery_paths:
        inject_gallery(gallery_paths)
    else:
        # Check for forge gallery directory
        forge_dir = "/opt/titan/data/forge_gallery"
        if os.path.exists(forge_dir):
            photos = [os.path.join(forge_dir, f) for f in os.listdir(forge_dir) if f.endswith(('.jpg', '.jpeg', '.png'))]
            if photos:
                print(f"\nFound {len(photos)} photos in {forge_dir}")
                inject_gallery(photos)
    
    # Final count verification
    time.sleep(2)
    contact_count = adb_shell(
        "content query --uri content://com.android.contacts/raw_contacts "
        "--projection _id 2>&1 | grep -c 'Row:'"
    )
    print(f"\n=== RESULT ===")
    print(f"Contacts on device: {contact_count}")
    
    gallery_count = adb_shell("ls /sdcard/DCIM/Camera/ 2>/dev/null | wc -l")
    print(f"Gallery photos on device: {gallery_count}")


if __name__ == "__main__":
    main()
