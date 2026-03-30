#!/usr/bin/env python3
"""
Titan — Server-Side Phone Scan Reader
Reads scan results from Windows PowerShell scanner via RDP clipboard or shared folder.

Usage:
    python3 scripts/read_phone_scan.py                # auto-find from RDP clipboard
    python3 scripts/read_phone_scan.py --file scan.json
    python3 scripts/read_phone_scan.py --clipboard     # paste JSON from clipboard
    python3 scripts/read_phone_scan.py --watch         # watch for scan files in thinclient_drives
"""

import argparse
import json
import os
import sys
from datetime import datetime


def read_from_clipboard():
    """Read JSON from xclip/xsel clipboard (pasted from Windows RDP)."""
    import subprocess
    for cmd in ["xclip -selection clipboard -o", "xsel --clipboard --output"]:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                return json.loads(r.stdout)
        except Exception:
            continue
    return None


def find_scan_files():
    """Look for scan JSON files in common locations."""
    search_paths = [
        "/root/thinclient_drives/",
        "/tmp/",
        "/root/Desktop/",
        os.path.expanduser("~/"),
    ]
    found = []
    for base in search_paths:
        if os.path.exists(base):
            try:
                for f in os.listdir(base):
                    if f.startswith("phone_scan_") and f.endswith(".json"):
                        found.append(os.path.join(base, f))
            except (PermissionError, OSError):
                pass
    # Also check recursively in thinclient
    try:
        for root, dirs, files in os.walk("/root/thinclient_drives/", followlinks=False):
            for f in files:
                if f.startswith("phone_scan_") and f.endswith(".json"):
                    found.append(os.path.join(root, f))
    except Exception:
        pass
    return sorted(found, key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)


def display_report(data: dict) -> None:
    """Display the scan report in a readable format."""
    sections = data.get("sections", {})
    
    print()
    print("=" * 70)
    print("  TITAN — REAL DEVICE ANALYSIS (from Windows scan)")
    print(f"  Scanned: {data.get('scan_timestamp', 'unknown')}")
    print(f"  Method:  {data.get('scan_method', 'unknown')}")
    print("=" * 70)
    
    # Assessment
    assess = sections.get("assessment", {})
    if assess:
        print("\n  DEVICE STATUS")
        print("  " + "-" * 50)
        detected = assess.get("phone_detected", False)
        print(f"  Phone Detected   : {'YES' if detected else 'NO'}")
        print(f"  Phone Name       : {assess.get('phone_name', '?')}")
        print(f"  MTP Accessible   : {'YES' if assess.get('mtp_accessible') else 'NO'}")
        print(f"  ADB Working      : {'YES' if assess.get('adb_working') else 'BLOCKED'}")
        print(f"  Carrier Lock     : {'LIKELY' if assess.get('carrier_lock_likely') else 'NOT DETECTED'}")
    
    # USB Descriptors — device identity
    usb_desc = sections.get("usb_descriptors", {})
    if usb_desc:
        print("\n  DEVICE IDENTITY (from USB)")
        print("  " + "-" * 50)
        for key, desc in usb_desc.items():
            print(f"  Vendor     : {desc.get('vendor', '?')}")
            print(f"  VID:PID    : {key}")
            print(f"  USB Serial : {desc.get('serial', '?')}")
            print(f"  Name       : {desc.get('friendly', '?')}")
    
    # Device identity from PnP
    dev_id = sections.get("device_identity", {})
    if dev_id:
        print("\n  DEVICE PROPERTIES (from Windows Device Manager)")
        print("  " + "-" * 50)
        for inst_id, props in dev_id.items():
            for key, val in props.items():
                short_key = key.replace("DEVPKEY_Device_", "")
                print(f"  {short_key:25s}: {val}")
    
    # Hardware details
    hw = sections.get("hardware_details", {})
    if hw:
        serial = hw.get("serial_from_registry", "")
        friendly = hw.get("friendly_from_registry", "")
        if serial or friendly:
            print(f"\n  Registry Serial  : {serial}")
            print(f"  Registry Name    : {friendly}")
        wmi = hw.get("wmi_usb", [])
        if wmi:
            print("\n  WMI USB DEVICES")
            print("  " + "-" * 50)
            for dev in wmi:
                print(f"  {dev.get('name', '?')} — {dev.get('manufacturer', '?')} [{dev.get('device_id', '')[:50]}]")
    
    # MTP Storage
    mtp = sections.get("mtp_storage", {})
    if mtp and mtp.get("accessible"):
        print(f"\n  MTP PHONE STORAGE: {mtp.get('phone_name', '?')} / {mtp.get('storage_name', '?')}")
        print("  " + "-" * 50)
        
        folders = mtp.get("top_folders", [])
        if folders:
            print("  Top-level folders:")
            for f in folders:
                size = f.get("size_bytes", 0)
                if isinstance(size, (int, float)):
                    if size > 1_000_000:
                        size_str = f"{size/1_000_000:.1f} MB"
                    elif size > 1000:
                        size_str = f"{size/1000:.1f} KB"
                    else:
                        size_str = f"{size} B"
                else:
                    size_str = str(size)
                print(f"    {f.get('name', '?'):30s}  {size_str:>12s}  {f.get('type', '')}")
        
        stats = mtp.get("file_stats", {})
        if stats:
            print("\n  File counts by directory:")
            for dirname, info in stats.items():
                files = info.get("file_count", 0)
                subs = info.get("subfolder_count", 0)
                print(f"    {dirname:20s}: {files:>5d} files, {subs:>3d} subfolders")
            
            # Show sample files
            for dirname, info in stats.items():
                samples = info.get("sample_files", [])
                if samples:
                    print(f"\n  Sample files in {dirname}:")
                    for sf in samples[:3]:
                        print(f"    {sf.get('name', '?')}  ({sf.get('modified', '')})")
    
    # ADB Status
    adb = sections.get("adb_status", {})
    if adb:
        print("\n  ADB STATUS")
        print("  " + "-" * 50)
        print(f"  ADB Installed    : {'YES' if adb.get('adb_installed') else 'NO'}")
        if adb.get("adb_installed"):
            print(f"  ADB Path         : {adb.get('adb_path', '?')}")
        print(f"  Device Visible   : {'YES' if adb.get('adb_can_see') else 'NO'}")
        print(f"  Authorized       : {'YES' if adb.get('adb_authorized') else 'NO'}")
        if adb.get("adb_blocked_reason"):
            print(f"  Block Reason     : {adb.get('adb_blocked_reason')}")
        if adb.get("adb_raw_output"):
            print(f"  Raw Output       : {adb['adb_raw_output'][:200]}")
    
    # Drivers
    drivers = sections.get("android_drivers", {})
    if drivers:
        drv_list = drivers.get("drivers", [])
        if drv_list:
            print("\n  ANDROID DRIVERS")
            print("  " + "-" * 50)
            for d in drv_list:
                signed = "signed" if d.get("signed") else "UNSIGNED"
                print(f"  {d.get('device', '?'):40s} {d.get('vendor', ''):15s} v{d.get('version', '?')} [{signed}]")
        
        if drivers.get("adb_interface_visible"):
            print(f"\n  ADB Interface    : {drivers.get('adb_interface_name', '?')} ({drivers.get('adb_interface_status', '?')})")
    
    # Network (USB tethering check)
    net = sections.get("windows_network", {})
    if net:
        if net.get("usb_tethering_detected"):
            print("\n  USB TETHERING DETECTED")
            print("  " + "-" * 50)
            print(f"  Tethering IPs: {net.get('tethering_ip', [])}")
    
    # USB Events
    events = sections.get("usb_history", {})
    if events:
        conns = events.get("recent_connections", [])
        setup = events.get("setup_log_matches", [])
        if conns or setup:
            print("\n  USB CONNECTION HISTORY")
            print("  " + "-" * 50)
            for ev in (conns or [])[:5]:
                print(f"  [{ev.get('time', '')}] {ev.get('message', '')[:100]}")
            for line in (setup or [])[:5]:
                print(f"  {line[:100]}")
    
    # Recommendations
    recs = assess.get("recommendations", [])
    if recs:
        print("\n  RECOMMENDATIONS")
        print("  " + "-" * 50)
        for r in recs:
            print(f"  > {r}")
    
    # Carrier lock analysis
    print("\n  CARRIER LOCK ANALYSIS")
    print("  " + "-" * 50)
    if assess.get("carrier_lock_likely"):
        print("  STATUS: CARRIER-LOCKED (ADB blocked by carrier/MDM)")
        print()
        print("  OPTIONS TO GAIN ADB ACCESS:")
        print("  1. Wireless Debugging (Android 11+) — bypasses most carrier blocks:")
        print("     Settings > Developer Options > Wireless Debugging > ON")
        print("     Then pair from server: bash scripts/connect_real_device.sh pair")
        print()
        print("  2. Remove Device Admin apps:")
        print("     Settings > Security > Device Admin Apps > disable all")
        print("     Then re-enable Developer Options")
        print()
        print("  3. Reset settings (NOT factory reset):")
        print("     Settings > General Management > Reset > Reset Settings")
        print("     This clears MDM restrictions without erasing data")
        print()
        print("  4. Contact carrier for unlock (after payment plan fulfilled)")
    elif assess.get("adb_working"):
        print("  STATUS: UNLOCKED — ADB is working")
        print("  You can now run the full ADB scanner:")
        print("  python3 scripts/analyze_real_device.py")
    else:
        print("  STATUS: UNKNOWN — could not determine lock status definitively")
    
    print()
    print("=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(description="Read phone scan results from Windows")
    parser.add_argument("--file", "-f", help="Path to scan JSON file")
    parser.add_argument("--clipboard", "-c", action="store_true", help="Read from clipboard")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch for new scan files")
    parser.add_argument("--paste", "-p", action="store_true", help="Prompt to paste JSON manually")
    args = parser.parse_args()
    
    data = None
    
    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    
    elif args.clipboard:
        data = read_from_clipboard()
        if not data:
            print("No valid JSON found in clipboard.")
            print("Copy the contents of C:\\TitanScan\\phone_scan_*.json on Windows, then try again.")
            sys.exit(1)
    
    elif args.paste:
        print("Paste the JSON content below, then press Ctrl+D (Linux) or Ctrl+Z (Windows):")
        print("-" * 40)
        try:
            raw = sys.stdin.read()
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyboardInterrupt):
            print("Invalid JSON or interrupted.")
            sys.exit(1)
    
    else:
        # Auto-find
        found = find_scan_files()
        if found:
            print(f"Found scan file: {found[0]}")
            with open(found[0]) as f:
                data = json.load(f)
        else:
            # Try clipboard
            data = read_from_clipboard()
            if not data:
                print()
                print("No scan results found.")
                print()
                print("HOW TO GET SCAN RESULTS TO THIS SERVER:")
                print("-" * 50)
                print()
                print("Option 1: Run scanner on Windows, copy results via RDP clipboard:")
                print("  1. On Windows: Open PowerShell as Admin")
                print("  2. Run: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass")
                print("  3. Run: .\\windows_phone_scanner.ps1")
                print("  4. Open C:\\TitanScan\\phone_scan_*.json")
                print("  5. Select All (Ctrl+A), Copy (Ctrl+C)")
                print("  6. On Linux server: python3 scripts/read_phone_scan.py --paste")
                print("     Then paste (Ctrl+V) and press Ctrl+D")
                print()
                print("Option 2: Download the .ps1 from server and run on Windows:")
                print(f"  File: scripts/windows_phone_scanner.ps1")
                print()
                sys.exit(1)
    
    if data:
        display_report(data)
        # Save locally
        out = f"/tmp/phone_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Saved: {out}")


if __name__ == "__main__":
    main()
