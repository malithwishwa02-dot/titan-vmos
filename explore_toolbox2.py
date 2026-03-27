#!/usr/bin/env python3
"""Explore Tool Box features with rate-limit handling."""
import asyncio, sys, os, base64, time
sys.path.insert(0, os.path.dirname(__file__))

from core.vmos_cloud_api import VMOSCloudClient
from dotenv import load_dotenv
load_dotenv()

DEVICE = "ACP2509244LGV1MV"

async def adb(client, cmd, retries=5):
    """Run ADB command with rate-limit retry."""
    for attempt in range(retries):
        try:
            task = await client.async_adb_cmd(DEVICE, cmd)
            code = task.get("code")
            if code == 500:
                wait = 5 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                await asyncio.sleep(wait)
                continue
            tid = task.get("data", {}).get("taskId")
            if not tid:
                return ""
            for _ in range(30):
                await asyncio.sleep(2)
                r = await client.get_async_task_result(tid)
                d = r.get("data", {})
                if d.get("status") == 2:
                    return d.get("content", "")
                if d.get("status") == 3:
                    return f"FAILED: {d}"
            return "TIMEOUT"
        except Exception as e:
            print(f"    Error: {e}, retrying in 5s...")
            await asyncio.sleep(5)
    return ""

async def pull_png(client, remote, local):
    result = await adb(client, f"cat {remote} | base64")
    if result and not result.startswith("FAILED") and result != "TIMEOUT":
        data = base64.b64decode(result.strip())
        with open(local, 'wb') as f:
            f.write(data)
        print(f"  -> {local} ({len(data)} bytes)")
        return True
    return False

async def main():
    client = VMOSCloudClient()
    
    # Step 1: First go back to main screen (may still be on Root Management)
    print("=== Step 1: Navigate back to Tool Box main ===")
    await adb(client, "input keyevent KEYCODE_BACK")
    await asyncio.sleep(3)
    
    # Step 2: Take a screenshot to verify we're on main
    print("=== Step 2: Verify main screen ===")
    await adb(client, "screencap -p /sdcard/s_main.png")
    await asyncio.sleep(2)
    await pull_png(client, "/sdcard/s_main.png", "/tmp/tb_main_verify.jpg")
    await asyncio.sleep(3)
    
    # Step 3: Tap each feature, screenshot, go back
    features = [
        # Basic Tools row 1
        (429, 1215, "Process Keep-Alive"),
        (651, 1215, "Hide App Processes"),
        (873, 1215, "App Auto-Start"),
        # Row 2
        (184, 1498, "Memory Monitoring"),
        (361, 1498, "Virtual Location"),
        (539, 1498, "Scheduled Reboot"),
        (717, 1477, "App Proxy"),
        (895, 1498, "Upload File"),
    ]
    
    for i, (x, y, name) in enumerate(features):
        fname = name.lower().replace(" ", "_").replace("-", "_")
        print(f"\n=== [{i+1}/{len(features)}] {name} ({x},{y}) ===")
        
        # Tap
        await adb(client, f"input tap {x} {y}")
        await asyncio.sleep(3)
        
        # Screenshot  
        await adb(client, f"screencap -p /sdcard/s_{fname}.png")
        await asyncio.sleep(2)
        await pull_png(client, f"/sdcard/s_{fname}.png", f"/tmp/tb_{fname}.jpg")
        await asyncio.sleep(2)
        
        # Go back
        await adb(client, "input keyevent KEYCODE_BACK")
        await asyncio.sleep(3)
    
    # Step 4: Scroll down to see Toolbox section
    print("\n=== Scrolling to Toolbox section ===")
    await adb(client, "input swipe 540 1800 540 800 500")
    await asyncio.sleep(3)
    await adb(client, "screencap -p /sdcard/s_scrolled1.png")
    await asyncio.sleep(2)
    await pull_png(client, "/sdcard/s_scrolled1.png", "/tmp/tb_scrolled1.jpg")
    await asyncio.sleep(2)
    
    # Get UI dump to find new positions
    print("\n=== UIAutomator dump after scroll ===")
    dump = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(dump)
    await asyncio.sleep(3)
    
    # Step 5: Continue scrolling and screenshot each section
    print("\n=== Scrolling further ===")
    await adb(client, "input swipe 540 1800 540 600 500")
    await asyncio.sleep(3)
    await adb(client, "screencap -p /sdcard/s_scrolled2.png")
    await asyncio.sleep(2)
    await pull_png(client, "/sdcard/s_scrolled2.png", "/tmp/tb_scrolled2.jpg")
    await asyncio.sleep(2)
    
    dump2 = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(dump2)
    await asyncio.sleep(3)
    
    # Step 6: Scroll to very bottom
    print("\n=== Scrolling to bottom ===")
    await adb(client, "input swipe 540 1800 540 400 500")
    await asyncio.sleep(3)
    await adb(client, "screencap -p /sdcard/s_scrolled3.png")
    await asyncio.sleep(2)
    await pull_png(client, "/sdcard/s_scrolled3.png", "/tmp/tb_scrolled3.jpg")
    await asyncio.sleep(2)
    
    dump3 = await adb(client, "uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml | tr '>' '\\n' | sed -n 's/.*text=\"\\([^\"]*\\)\".*bounds=\"\\[\\([^]]*\\)\\]\\[\\([^]]*\\)\\]\".*/\\1 [\\2][\\3]/p'")
    print(dump3)
    
    print("\n=== DONE ===")

asyncio.run(main())
