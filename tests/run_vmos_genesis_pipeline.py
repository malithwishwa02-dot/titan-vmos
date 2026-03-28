#!/usr/bin/env python3
"""
VMOS Genesis Pipeline Execution Script
======================================
Executes the full 11-phase Genesis pipeline for VMOS Cloud devices.

Usage:
    python tests/run_vmos_genesis_pipeline.py [--pad PAD_CODE] [--skip-wipe] [--proxy URL]
    
Example:
    python tests/run_vmos_genesis_pipeline.py --pad ACP2509244LGV1MV
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project paths
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Validate required credentials from environment
if not os.environ.get("VMOS_CLOUD_AK") or not os.environ.get("VMOS_CLOUD_SK"):
    print("ERROR: VMOS_CLOUD_AK and VMOS_CLOUD_SK must be set in environment or .env file")
    print("Example:")
    print("  export VMOS_CLOUD_AK='your-access-key'")
    print("  export VMOS_CLOUD_SK='your-secret-key'")
    sys.exit(1)

from vmos_cloud_api import VMOSCloudClient
from vmos_genesis_engine import VMOSGenesisEngine, PipelineConfig

# ═══════════════════════════════════════════════════════════════════════════
# TEST SUBJECT DATA
# ═══════════════════════════════════════════════════════════════════════════

TEST_PROFILE = {
    # Identity
    "name": "Jovany OWENS",
    "email": "adiniorjuniorjd28@gmail.com",
    "phone": "+17078361915",
    "dob": "12/11/1959",
    "ssn": "219-19-0937",
    
    # Address
    "street": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90006",
    "country": "US",
    
    # Card
    "cc_number": "4638512320340405",
    "cc_exp": "08/2029",
    "cc_cvv": "051",
    "cc_holder": "Jovany Owens",
    
    # Google Account
    "google_email": "adiniorjuniorjd28@gmail.com",
    "google_password": "YCCvsukin7S",
    "real_phone": "+17078361915",
    
    # Device settings
    "device_model": "same_device_modelvmospro",
    "carrier": "tmobile_us",
    "location": "la",
    "age_days": 120,
}


def print_header():
    print("=" * 80)
    print("VMOS GENESIS PIPELINE EXECUTION")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Target Profile: {TEST_PROFILE['name']} <{TEST_PROFILE['email']}>")
    print(f"Device Model: {TEST_PROFILE['device_model']}")
    print(f"Location: {TEST_PROFILE['location']}")
    print(f"Age Days: {TEST_PROFILE['age_days']}")
    print("=" * 80)


def on_pipeline_update(result):
    """Callback for live pipeline updates."""
    # Find the latest running phase
    for phase in result.phases:
        if phase.status == "running":
            print(f"  ► Phase {phase.phase}: {phase.name} - {phase.status}")
            break


async def run_pipeline(pad_code: str, skip_wipe: bool = False, proxy_url: str = ""):
    """Execute the full Genesis pipeline."""
    print_header()
    
    print(f"\n[INIT] Connecting to VMOS Cloud...")
    print(f"  Pad Code: {pad_code}")
    
    # Create client and engine
    client = VMOSCloudClient()
    engine = VMOSGenesisEngine(pad_code, client=client)
    
    # Build config
    cfg = PipelineConfig(
        # Identity
        name=TEST_PROFILE["name"],
        email=TEST_PROFILE["email"],
        phone=TEST_PROFILE["phone"],
        dob=TEST_PROFILE["dob"],
        ssn=TEST_PROFILE["ssn"],
        
        # Address
        street=TEST_PROFILE["street"],
        city=TEST_PROFILE["city"],
        state=TEST_PROFILE["state"],
        zip=TEST_PROFILE["zip"],
        country=TEST_PROFILE["country"],
        
        # Card
        cc_number=TEST_PROFILE["cc_number"],
        cc_exp=TEST_PROFILE["cc_exp"],
        cc_cvv=TEST_PROFILE["cc_cvv"],
        cc_holder=TEST_PROFILE["cc_holder"],
        
        # Google
        google_email=TEST_PROFILE["google_email"],
        google_password=TEST_PROFILE["google_password"],
        real_phone=TEST_PROFILE["real_phone"],
        
        # Device
        device_model=TEST_PROFILE["device_model"],
        carrier=TEST_PROFILE["carrier"],
        location=TEST_PROFILE["location"],
        age_days=TEST_PROFILE["age_days"],
        
        # Options
        proxy_url=proxy_url,
        skip_wipe=skip_wipe,
        skip_patch=False,
    )
    
    print(f"\n[START] Running 11-phase pipeline...")
    print("-" * 60)
    
    # Run pipeline
    result = await engine.run_pipeline(cfg, on_update=on_pipeline_update)
    
    print("-" * 60)
    print("\n[RESULTS]")
    
    # Print phase results
    print("\nPhase Results:")
    for phase in result.phases:
        status_icon = {
            "done": "✓",
            "skipped": "○",
            "warn": "⚠",
            "failed": "✗",
        }.get(phase.status, "?")
        print(f"  {status_icon} Phase {phase.phase:2d}: {phase.name:20s} [{phase.status:8s}] {phase.notes[:50]}")
    
    print(f"\nTrust Score: {result.trust_score}/100 (Grade: {result.grade})")
    print(f"Profile ID: {result.profile_id}")
    print(f"Duration: {result.completed_at - result.started_at:.0f}s")
    
    # Save results
    results_dir = Path(__file__).parent.parent / "reports"
    results_dir.mkdir(exist_ok=True)
    results_file = results_dir / f"genesis_result_{pad_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(results_file, "w") as f:
        json.dump(engine.result_dict(), f, indent=2)
    print(f"\nResults saved: {results_file}")
    
    # Print verification commands
    print("\n" + "=" * 60)
    print("VERIFICATION COMMANDS (run on device via ADB):")
    print("=" * 60)
    print("""
# 1. Check Google Account
sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;"

# 2. Check Contacts
content query --uri content://com.android.contacts/raw_contacts --projection _id | wc -l

# 3. Check Call Logs
content query --uri content://call_log/calls --projection _id | wc -l

# 4. Check SMS
content query --uri content://sms --projection _id | wc -l

# 5. Check Chrome Cookies
sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies "SELECT COUNT(*) FROM cookies;"

# 6. Check Chrome History
sqlite3 /data/data/com.android.chrome/app_chrome/Default/History "SELECT COUNT(*) FROM urls;"

# 7. Check Wallet/GPay
sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db "SELECT * FROM token_metadata;"

# 8. Check UsageStats
ls /data/system/usagestats/0/daily/
""")
    
    # Final status
    if result.trust_score >= 95:
        print("\n✅ SUCCESS: Trust score 95%+ achieved!")
        print("   Next: Manual Gmail login + Google Pay card addition")
    elif result.trust_score >= 85:
        print("\n⚠️  PARTIAL: Trust score 85%+ achieved")
        print("   Some components may need manual verification")
    else:
        print("\n❌ BELOW TARGET: Trust score below 85%")
        print("   Review phase failures and re-run affected phases")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description="Run VMOS Genesis Pipeline")
    parser.add_argument("--pad", default="ACP2509244LGV1MV", help="VMOS pad_code")
    parser.add_argument("--skip-wipe", action="store_true", help="Skip Phase 0 (wipe)")
    parser.add_argument("--proxy", default="", help="Proxy URL (socks5://user:pass@host:port)")
    args = parser.parse_args()
    
    try:
        result = await run_pipeline(args.pad, args.skip_wipe, args.proxy)
        sys.exit(0 if result.trust_score >= 85 else 1)
    except KeyboardInterrupt:
        print("\n[ABORTED] Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

