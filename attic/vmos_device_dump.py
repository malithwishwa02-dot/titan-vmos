#!/usr/bin/env python3
"""
VMOS Cloud Device Dump Script
Connects to VMOS Cloud API and dumps comprehensive data from deployed devices.
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core", "_deprecated"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vmos-dump")

# VMOS Cloud credentials
VMOS_API_KEY = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
VMOS_API_SECRET = "Q2SgcSwEfuwoedY0cijp6Mce"
VMOS_API_HOST = "api.vmoscloud.com"

OUTPUT_DIR = Path("/opt/titan-v11.3-device/reports/vmos_dumps")


class VMOSDumper:
    def __init__(self):
        from vmos_cloud_bridge import VMOSCloudBridge
        self.bridge = VMOSCloudBridge(
            api_key=VMOS_API_KEY,
            api_secret=VMOS_API_SECRET,
            base_url=f"https://{VMOS_API_HOST}",
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def _save(self, pad_code: str, category: str, data):
        """Save data to JSON file."""
        fname = OUTPUT_DIR / f"vmos_dump_{pad_code}_{category}.json"
        with open(fname, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"  Saved: {fname.name}")

    async def list_devices(self):
        """Phase 1: List all VMOS Cloud instances."""
        logger.info("=" * 60)
        logger.info("PHASE 1: DEVICE ENUMERATION")
        logger.info("=" * 60)
        
        instances = await self.bridge.list_instances(page=1, rows=50)
        logger.info(f"Found {len(instances)} device(s):")
        
        devices = []
        for inst in instances:
            info = inst.to_dict()
            devices.append(info)
            logger.info(f"  - {info['pad_code']}: status={info['status']}, "
                       f"ip={info['device_ip']}, level={info['device_level']}")
        
        self._save("all", "instances", devices)
        return instances

    async def dump_device_properties(self, pad_code: str):
        """Dump device system properties."""
        logger.info(f"  Dumping device properties...")
        
        props = await self.bridge.get_instance_properties(pad_code)
        self._save(pad_code, "properties", props)
        
        # Also get full details
        details = await self.bridge.get_instance_details(pad_code)
        self._save(pad_code, "details", details)
        
        return props, details

    async def dump_build_props(self, pad_code: str):
        """Dump Android build properties via getprop."""
        logger.info(f"  Dumping build props via getprop...")
        
        result = await self.bridge.exec_shell(pad_code, "getprop")
        if result.ok:
            props = {}
            for line in (result.result or "").split("\n"):
                if "]: [" in line:
                    try:
                        key = line.split("]: [")[0].replace("[", "").strip()
                        val = line.split("]: [")[1].replace("]", "").strip()
                        props[key] = val
                    except:
                        pass
            self._save(pad_code, "build_props", props)
            return props
        else:
            logger.warning(f"  getprop failed: {result.error}")
            return {}

    async def dump_installed_apps(self, pad_code: str):
        """Dump list of installed apps."""
        logger.info(f"  Dumping installed apps...")
        
        apps = await self.bridge.list_apps(pad_code)
        self._save(pad_code, "apps", apps)
        logger.info(f"    Found {len(apps)} apps")
        return apps

    async def dump_screenshot(self, pad_code: str):
        """Get device screenshot."""
        logger.info(f"  Getting screenshot...")
        
        url = await self.bridge.screenshot(pad_code, fmt="png")
        if url:
            self._save(pad_code, "screenshot_url", {"url": url, "timestamp": datetime.now().isoformat()})
            logger.info(f"    Screenshot URL saved")
            return url
        else:
            logger.warning(f"    Screenshot failed")
            return None

    async def dump_contacts(self, pad_code: str):
        """Dump contacts via content provider."""
        logger.info(f"  Dumping contacts...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "content query --uri content://contacts/phones --projection display_name:data1"
        )
        contacts = []
        if result.ok and result.result:
            for line in result.result.split("\n"):
                if "display_name=" in line:
                    contacts.append(line.strip())
        self._save(pad_code, "contacts", {"raw": result.result, "count": len(contacts), "parsed": contacts})
        logger.info(f"    Found {len(contacts)} contacts")
        return contacts

    async def dump_call_logs(self, pad_code: str):
        """Dump call logs via content provider."""
        logger.info(f"  Dumping call logs...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "content query --uri content://call_log/calls --projection number:type:duration:date"
        )
        calls = []
        if result.ok and result.result:
            for line in result.result.split("\n"):
                if "number=" in line:
                    calls.append(line.strip())
        self._save(pad_code, "call_logs", {"raw": result.result, "count": len(calls), "parsed": calls})
        logger.info(f"    Found {len(calls)} call records")
        return calls

    async def dump_sms(self, pad_code: str):
        """Dump SMS messages."""
        logger.info(f"  Dumping SMS...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "content query --uri content://sms --projection address:body:date:type"
        )
        sms = []
        if result.ok and result.result:
            for line in result.result.split("\n"):
                if "address=" in line:
                    sms.append(line.strip())
        self._save(pad_code, "sms", {"raw": result.result, "count": len(sms), "parsed": sms})
        logger.info(f"    Found {len(sms)} SMS messages")
        return sms

    async def dump_chrome_data(self, pad_code: str):
        """Dump Chrome cookies and history."""
        logger.info(f"  Dumping Chrome data...")
        
        chrome_data = {}
        
        # Check if Chrome exists
        result = await self.bridge.exec_shell(pad_code, "ls /data/data/com.android.chrome/app_chrome/Default/ 2>/dev/null")
        if result.ok and result.result:
            chrome_data["files"] = result.result.strip().split("\n")
        
        # Cookies (just check existence, actual DB is binary)
        result = await self.bridge.exec_shell(
            pad_code, 
            "ls -la /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null"
        )
        chrome_data["cookies_exists"] = result.ok and "Cookies" in (result.result or "")
        
        # History URLs
        result = await self.bridge.exec_shell(
            pad_code,
            "sqlite3 /data/data/com.android.chrome/app_chrome/Default/History "
            "'SELECT url, title, visit_count FROM urls ORDER BY last_visit_time DESC LIMIT 50' 2>/dev/null"
        )
        if result.ok and result.result:
            chrome_data["history"] = result.result.strip().split("\n")
        
        self._save(pad_code, "chrome", chrome_data)
        return chrome_data

    async def dump_accounts(self, pad_code: str):
        """Dump Google accounts."""
        logger.info(f"  Dumping accounts...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "sqlite3 /data/system_ce/0/accounts_ce.db 'SELECT name, type FROM accounts' 2>/dev/null"
        )
        accounts = []
        if result.ok and result.result:
            accounts = result.result.strip().split("\n")
        self._save(pad_code, "accounts", {"raw": result.result, "accounts": accounts})
        logger.info(f"    Found {len(accounts)} accounts")
        return accounts

    async def dump_wallet(self, pad_code: str):
        """Dump Google Pay wallet data."""
        logger.info(f"  Dumping wallet/GPay data...")
        
        wallet_data = {}
        
        # Check tapandpay.db
        result = await self.bridge.exec_shell(
            pad_code,
            "sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db "
            "'SELECT * FROM tokens' 2>/dev/null"
        )
        if result.ok and result.result:
            wallet_data["tokens"] = result.result.strip()
        
        # Check NFC prefs
        result = await self.bridge.exec_shell(
            pad_code,
            "cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null"
        )
        if result.ok:
            wallet_data["nfc_prefs"] = result.result
        
        self._save(pad_code, "wallet", wallet_data)
        return wallet_data

    async def dump_wifi(self, pad_code: str):
        """Dump saved WiFi networks."""
        logger.info(f"  Dumping WiFi networks...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "cat /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"
        )
        wifi_data = {"raw": result.result if result.ok else None}
        self._save(pad_code, "wifi", wifi_data)
        return wifi_data

    async def dump_gallery(self, pad_code: str):
        """Dump gallery photo list."""
        logger.info(f"  Dumping gallery list...")
        
        result = await self.bridge.exec_shell(
            pad_code,
            "ls -la /sdcard/DCIM/Camera/ 2>/dev/null; ls -la /sdcard/Pictures/ 2>/dev/null"
        )
        files = []
        if result.ok and result.result:
            files = [l for l in result.result.strip().split("\n") if l.strip()]
        self._save(pad_code, "gallery", {"files": files, "count": len(files)})
        logger.info(f"    Found {len(files)} files")
        return files

    async def dump_device(self, pad_code: str):
        """Full dump for a single device."""
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"DUMPING DEVICE: {pad_code}")
        logger.info("=" * 60)
        
        results = {"pad_code": pad_code, "dump_time": datetime.now().isoformat()}
        
        # Phase 2: Device state
        logger.info("Phase 2: Device State")
        results["properties"], results["details"] = await self.dump_device_properties(pad_code)
        results["build_props"] = await self.dump_build_props(pad_code)
        results["apps"] = await self.dump_installed_apps(pad_code)
        results["screenshot"] = await self.dump_screenshot(pad_code)
        
        # Phase 3: User data
        logger.info("Phase 3: User Data")
        results["contacts"] = await self.dump_contacts(pad_code)
        results["call_logs"] = await self.dump_call_logs(pad_code)
        results["sms"] = await self.dump_sms(pad_code)
        results["chrome"] = await self.dump_chrome_data(pad_code)
        results["accounts"] = await self.dump_accounts(pad_code)
        results["wallet"] = await self.dump_wallet(pad_code)
        results["wifi"] = await self.dump_wifi(pad_code)
        results["gallery"] = await self.dump_gallery(pad_code)
        
        # Save summary
        self._save(pad_code, "summary", results)
        return results

    async def run(self):
        """Run full dump for all devices."""
        logger.info("VMOS Cloud Device Dump")
        logger.info(f"API Host: {VMOS_API_HOST}")
        logger.info(f"Output: {OUTPUT_DIR}")
        logger.info("")
        
        # Phase 1: List devices
        instances = await self.list_devices()
        
        if not instances:
            logger.error("No devices found!")
            return
        
        # Dump each device
        for inst in instances:
            pad_code = inst.pad_code
            await self.dump_device(pad_code)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"DUMP COMPLETE - {len(instances)} device(s)")
        logger.info(f"Output: {OUTPUT_DIR}")
        logger.info("=" * 60)


async def main():
    dumper = VMOSDumper()
    await dumper.run()


if __name__ == "__main__":
    asyncio.run(main())
