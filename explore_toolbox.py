#!/usr/bin/env python3
"""Batch explore Tool Box features - navigate, screenshot, pull."""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from core.vmos_cloud_api import VMOSCloudClient
from dotenv import load_dotenv
load_dotenv()

DEVICE = "ACP2509244LGV1MV"

async def adb(client, cmd):
    task = await client.async_adb_cmd(DEVICE, cmd)
    tid = task.get("data", {}).get("taskId")
    if not tid:
        return ""
    for _ in range(20):
        await asyncio.sleep(1.5)
        r = await client.get_async_task_result(tid)
        d = r.get("data", {})
        if d.get("status") == 2:
            return d.get("content", "")
        if d.get("status") == 3:
            return f"FAILED: {d}"
    return "TIMEOUT"

async def pull_screenshot(client, remote, local):
    """Pull a screenshot from device to local file."""
    result = await adb(client, f"cat {remote} | base64")
    if result and not result.startswith("FAILED") and result != "TIMEOUT":
        import base64
        data = base64.b64decode(result.strip())
        with open(local, 'wb') as f:
            f.write(data)
        print(f"  Saved {local} ({len(data)} bytes)")
        return True
    else:
        print(f"  Failed to pull {remote}: {result[:100] if result else 'empty'}")
        return False

async def tap_and_screenshot(client, x, y, name, remote_path, local_path, wait=1.5):
    print(f"\n>> Tapping {name} at ({x}, {y})...")
    await adb(client, f"input tap {x} {y}")
    await asyncio.sleep(wait)
    await adb(client, f"screencap -p {remote_path}")
    await pull_screenshot(client, remote_path, local_path)

async def go_back(client):
    await adb(client, "input tap 60 90")
    await asyncio.sleep(1)

async def main():
    client = VMOSCloudClient()
    
    # First pull the process_keepalive screenshot we already took
    print("== Pulling existing process_keepalive screenshot ==")
    await pull_screenshot(client, "/sdcard/process_keepalive.png", "/tmp/tb_process_keepalive.jpg")
    
    # Go back to main
    print("\n== Going back to main ==")
    await go_back(client)
    await asyncio.sleep(1)
    
    # Features to explore with their coordinates from UIAutomator dump
    features = [
        # (x, y, name, filename) - coordinates from UIAutomator bounds
        (651, 1215, "Hide App Processes", "hide_app_processes"),
        (873, 1215, "App Auto-Start", "app_auto_start"),
        (184, 1498, "Memory Monitoring", "memory_monitoring"),
        (361, 1498, "Virtual Location", "virtual_location"),
        (539, 1498, "Scheduled Reboot", "scheduled_reboot"),
        (717, 1477, "App Proxy", "app_proxy"),
        (895, 1498, "Upload File", "upload_file"),
    ]
    
    for x, y, name, fname in features:
        await tap_and_screenshot(client, x, y, name, 
                                f"/sdcard/tb_{fname}.png", 
                                f"/tmp/tb_{fname}.jpg")
        await go_back(client)
    
    # Scroll down to Toolbox section and explore those features
    print("\n== Scrolling down to Toolbox section ==")
    await adb(client, "input swipe 540 1800 540 800 500")
    await asyncio.sleep(1)
    
    # Take screenshot of scrolled view
    await adb(client, "screencap -p /sdcard/tb_scrolled.png")
    await pull_screenshot(client, "/sdcard/tb_scrolled.png", "/tmp/tb_scrolled.jpg")
    
    # Get UIAutomator dump for scrolled view
    print("\n== Getting UIAutomator dump for scrolled positions ==")
    dump = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(f"UIAutomator scrolled:\n{dump}")
    
    # Now explore Toolbox section features
    toolbox_features = [
        (213, 2260, "Change Device Model", "change_device_model"),
        (447, 2260, "Modify Resolution", "modify_resolution"),  
        (681, 2260, "Add Doppelganger", "add_doppelganger"),
        (915, 2260, "One-Click New Phone", "one_click_new_phone"),
    ]
    
    # These coordinates may have shifted after scroll, use dump to find them
    # For now try tapping based on the dump
    for x, y, name, fname in toolbox_features:
        await tap_and_screenshot(client, x, y, name,
                                f"/sdcard/tb_{fname}.png",
                                f"/tmp/tb_{fname}.jpg")
        # Some features might open dialogs, try back
        await go_back(client)
        await asyncio.sleep(0.5)
    
    # Camera Injection Configuration
    print("\n== Scrolling to Camera Injection ==")
    await adb(client, "input swipe 540 1800 540 600 500")
    await asyncio.sleep(1)
    await adb(client, "screencap -p /sdcard/tb_bottom.png")
    await pull_screenshot(client, "/sdcard/tb_bottom.png", "/tmp/tb_bottom.jpg")
    
    # Get UI dump for bottom section
    dump2 = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(f"UIAutomator bottom:\n{dump2}")
    
    # About Expansion Tool
    print("\n== Scrolling to About ==")
    await adb(client, "input swipe 540 1800 540 400 500")
    await asyncio.sleep(1)
    
    # Look for About Expansion Tool and tap it
    dump3 = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(f"UIAutomator about area:\n{dump3}")
    
    await client.close()
    print("\n== Done ==")

asyncio.run(main())
