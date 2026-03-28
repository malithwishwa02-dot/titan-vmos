#!/usr/bin/env python3
"""
Titan V12 — 90-Day Device Provisioning CLI
Creates a Cuttlefish device with 90-day aging via genesis pipeline
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

# Add core to path
sys.path.insert(0, '/opt/titan-v11.3-device')
sys.path.insert(0, '/opt/titan-v11.3-device/core')
os.chdir('/opt/titan-v11.3-device')

# Import core modules
from device_manager import DeviceManager, CreateDeviceRequest
from android_profile_forge import AndroidProfileForge
from profile_injector import ProfileInjector
from workflow_engine import WorkflowEngine
from device_presets import DEVICE_PRESETS, CARRIERS, LOCATIONS
from json_logger import setup_json_logging
import logging

# Setup logging
setup_json_logging()
logger = logging.getLogger("provision_cli")

class ProvisionCLI:
    """CLI for provisioning 90-day devices"""
    
    def __init__(self):
        self.device_manager = DeviceManager()
        self.forge = AndroidProfileForge()
        self.injector = ProfileInjector()
        self.workflow = WorkflowEngine()
    
    def list_presets(self):
        """List available device presets"""
        print("\n" + "="*80)
        print("AVAILABLE DEVICE PRESETS")
        print("="*80 + "\n")
        
        for name, preset in DEVICE_PRESETS.items():
            print(f"  {name:30} — {preset.brand} {preset.model}")
        
        print(f"\nTotal: {len(DEVICE_PRESETS)} presets")
        print("="*80 + "\n")
    
    def list_carriers(self):
        """List available carriers"""
        print("\n" + "="*80)
        print("AVAILABLE CARRIERS")
        print("="*80 + "\n")
        
        for code, carrier in CARRIERS.items():
            print(f"  {code:30} — {carrier.name}")
        
        print(f"\nTotal: {len(CARRIERS)} carriers")
        print("="*80 + "\n")
    
    def list_locations(self):
        """List available locations"""
        print("\n" + "="*80)
        print("AVAILABLE LOCATIONS")
        print("="*80 + "\n")
        
        for code, location in LOCATIONS.items():
            print(f"  {code:20} — {location.city}, {location.country}")
        
        print(f"\nTotal: {len(LOCATIONS)} locations")
        print("="*80 + "\n")
    
    def create_and_provision_device(self, model="samsung_s25_ultra", country="US", 
                                     carrier="tmobile_us", location="nyc", age_days=90,
                                     persona_name="Default User", persona_email=None,
                                     persona_phone=None, disable_adb=False):
        """Create device and provision via genesis pipeline"""
        import asyncio
        
        print("\n" + "="*80)
        print("TITAN V12 — 90-DAY DEVICE PROVISIONING")
        print("="*80 + "\n")
        
        try:
            # Step 1: Create device (async call)
            print("[1/5] Creating Cuttlefish device...")
            
            req = CreateDeviceRequest(
                model=model,
                country=country,
                carrier=carrier,
                android_version="14",
                screen_width=1440,
                screen_height=3120,
                dpi=480,
                memory_mb=4096,
                cpus=4,
                gpu_mode="auto"
            )
            
            # Run async method in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            device = loop.run_until_complete(self.device_manager.create_device(req))
            loop.close()
            
            device_id = device.instance_id
            print(f"    ✅ Device created: {device_id}")
            print(f"    State: {device.state}")
            print(f"    ADB Target: {device.adb_target}")
            
            # Step 2: Wait for device to be ready
            print("\n[2/5] Waiting for device to boot...")
            max_wait = 300  # 5 minutes
            for attempt in range(max_wait // 5):
                device = self.device_manager.get_device(device_id)
                if device and device.state in ["ready", "patched"]:
                    print(f"    ✅ Device ready after {attempt * 5} seconds")
                    break
                print(f"    ⏳ State: {device.state if device else 'unknown'}... (waiting {(attempt+1)*5}s)")
                time.sleep(5)
            else:
                print(f"    ❌ Device did not boot after {max_wait}s")
                return False
            
            # Step 3: Forge 90-day profile
            print(f"\n[3/5] Forging 90-day profile...")
            profile = self.forge.forge(
                persona_name=persona_name,
                persona_email=persona_email or f"{persona_name.lower().replace(' ', '.')}@example.com",
                persona_phone=persona_phone or "+1234567890",
                country=country,
                archetype="professional",
                age_days=age_days,
                carrier=carrier,
                location=location,
                device_model=model
            )
            
            profile_summary = {
                "contacts": len(profile.get("contacts", [])),
                "call_logs": len(profile.get("call_logs", [])),
                "sms_messages": len(profile.get("sms_messages", [])),
                "chrome_history": len(profile.get("chrome_history", [])),
                "wifi": len(profile.get("wifi", [])),
                "installed_apps": len(profile.get("installed_apps", [])),
            }
            
            print(f"    ✅ Profile forged with:")
            for key, count in profile_summary.items():
                print(f"       • {key}: {count}")
            
            # Step 4: Inject profile into device
            print(f"\n[4/5] Injecting profile into device {device_id}...")
            print(f"       Age: {age_days} days")
            print(f"       Model: {model}")
            print(f"       Carrier: {carrier}")
            print(f"       Location: {location}")
            
            try:
                # Inject profile directly
                injection_result = self.injector.inject_full_profile(profile, None)
                print(f"    ✅ Profile injection result: {injection_result}")
            except Exception as e:
                print(f"    ❌ Injection failed: {e}")
                return False
            
            # Step 5: Report completion
            print(f"\n[5/5] Device provisioning complete!")
            
            # Final status
            print("\n" + "="*80)
            print("DEVICE PROVISIONING COMPLETE")
            print("="*80)
            print(f"\nDevice ID: {device_id}")
            print(f"Model: {model}")
            print(f"Age: {age_days} days")
            print(f"Persona: {persona_name}")
            print(f"Email: {profile.get('email', 'N/A')}")
            print(f"Phone: {profile.get('phone', 'N/A')}")
            print(f"ADB Target: {device.adb_target}\n")
            
            # Save device info to file
            os.makedirs("/opt/titan/data/devices", exist_ok=True)
            info = {
                "device_id": device_id,
                "model": model,
                "age_days": age_days,
                "persona": {
                    "name": persona_name,
                    "email": profile.get('email'),
                    "phone": profile.get('phone'),
                },
                "adb_target": device.adb_target,
                "created_at": datetime.now().isoformat(),
            }
            
            with open(f"/opt/titan/data/devices/{device_id}_info.json", "w") as f:
                json.dump(info, f, indent=2)
            
            print(f"Device info saved to: /opt/titan/data/devices/{device_id}_info.json")
            print("="*80 + "\n")
            
            return True
            
        except Exception as e:
            logger.error(f"Provisioning failed: {e}", exc_info=True)
            print(f"\n❌ Error: {e}")
            return False
    
    def run_cli(self):
        """Run interactive CLI"""
        parser = argparse.ArgumentParser(
            description="Titan V12 Device Provisioning CLI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Create 90-day device with defaults
  python provision_90day_device.py provision

  # Create with custom persona
  python provision_90day_device.py provision \\
    --persona-name "John Smith" \\
    --model samsung_s25_ultra \\
    --age-days 90

  # List available options
  python provision_90day_device.py list-presets
  python provision_90day_device.py list-carriers
  python provision_90day_device.py list-locations
            """
        )
        
        subparsers = parser.add_subparsers(dest="command", help="Command")
        
        # Provision command
        prov = subparsers.add_parser("provision", help="Create and provision a device")
        prov.add_argument("--model", default="samsung_s25_ultra", help="Device model")
        prov.add_argument("--country", default="US", help="Country code")
        prov.add_argument("--carrier", default="tmobile_us", help="Carrier code")
        prov.add_argument("--location", default="nyc", help="Location code")
        prov.add_argument("--age-days", type=int, default=90, help="Device age in days")
        prov.add_argument("--persona-name", default="Test User", help="Persona name")
        prov.add_argument("--persona-email", help="Persona email (auto-generated if not provided)")
        prov.add_argument("--persona-phone", help="Persona phone (auto-generated if not provided)")
        prov.add_argument("--disable-adb", action="store_true", help="Disable ADB after provisioning")
        
        # List commands
        subparsers.add_parser("list-presets", help="List device presets")
        subparsers.add_parser("list-carriers", help="List carriers")
        subparsers.add_parser("list-locations", help="List locations")
        
        args = parser.parse_args()
        
        if args.command == "provision":
            success = self.create_and_provision_device(
                model=args.model,
                country=args.country,
                carrier=args.carrier,
                location=args.location,
                age_days=args.age_days,
                persona_name=args.persona_name,
                persona_email=args.persona_email,
                persona_phone=args.persona_phone,
                disable_adb=args.disable_adb
            )
            sys.exit(0 if success else 1)
        
        elif args.command == "list-presets":
            self.list_presets()
        
        elif args.command == "list-carriers":
            self.list_carriers()
        
        elif args.command == "list-locations":
            self.list_locations()
        
        else:
            parser.print_help()

def main():
    cli = ProvisionCLI()
    cli.run_cli()

if __name__ == "__main__":
    main()
