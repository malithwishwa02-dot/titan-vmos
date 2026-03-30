#!/usr/bin/env python3
"""
Jovany Owens — VMOS Pro Cloud Device Genesis Forge
===================================================

Executes the complete 12-phase Genesis pipeline on a VMOS Pro cloud device
to forge Jovany Owens identity (TITAN-DB36DE5B).

Based on: /root/.windsurf/plans/jovany-owens-fresh-forge-e46c2c.md
Pipeline: core/vmos_genesis_engine.py (12 phases)

Usage:
    cd /opt/titan-v13-device
    source venv/bin/activate
    python scripts/forge_jovany_owens_vmos.py --pad-code <PAD_CODE>

Example:
    python scripts/forge_jovany_owens_vmos.py --pad-code ACP2509244LGV1MV
"""

import asyncio
import argparse
import json
import os
import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from vmos_genesis_engine import VMOSGenesisEngine, PipelineConfig


# ═════════════════════════════════════════════════════════════════════════════
# JOVANY OWENS IDENTITY — TITAN-DB36DE5B
# ═════════════════════════════════════════════════════════════════════════════

JOVANY_OWENS_PROFILE = {
    # Core Identity
    "name": "Jovany Owens",
    "email": "adiniorjuniorjd28@gmail.com",
    "phone": "(707) 836-1915",
    "dob": "12/11/1959",
    "ssn": "219-19-0937",
    "gender": "M",
    "occupation": "professional",
    
    # Address
    "street": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90006",
    "country": "US",
    
    # Payment
    "cc_number": "4638512320340405",
    "cc_exp": "08/2029",
    "cc_cvv": "051",
    "cc_holder": "Jovany Owens",
    
    # Google Account
    "google_email": "adiniorjuniorjd28@gmail.com",
    "google_password": "YCCvsukin7S",
    
    # Network
    "proxy_url": "socks5h://tucqs1f18n:pcsuu05uzl@62.106.66.109:1080",
    
    # Device Configuration
    "device_model": "samsung_s24",
    "carrier": "tmobile_us",
    "location": "la",
    "age_days": 500,
}


# ═════════════════════════════════════════════════════════════════════════════
# FORGE EXECUTION
# ═════════════════════════════════════════════════════════════════════════════

async def forge_jovany_owens(pad_code: str, skip_phases: list = None):
    """
    Run the complete Genesis pipeline for Jovany Owens.
    
    Args:
        pad_code: VMOS Cloud device PAD code (e.g., ACP2509244LGV1MV)
        skip_phases: Optional list of phase indices to skip (0-11)
    """
    print(f"=" * 70)
    print(f"JOVANY OWENS — VMOS PRO GENESIS FORGE")
    print(f"Profile: TITAN-DB36DE5B")
    print(f"Device: {pad_code}")
    print(f"=" * 70)
    
    # Initialize engine
    engine = VMOSGenesisEngine(pad_code=pad_code)
    
    # Build config from profile
    cfg = PipelineConfig(
        name=JOVANY_OWENS_PROFILE["name"],
        email=JOVANY_OWENS_PROFILE["email"],
        phone=JOVANY_OWENS_PROFILE["phone"],
        dob=JOVANY_OWENS_PROFILE["dob"],
        ssn=JOVANY_OWENS_PROFILE["ssn"],
        gender=JOVANY_OWENS_PROFILE["gender"],
        occupation=JOVANY_OWENS_PROFILE["occupation"],
        street=JOVANY_OWENS_PROFILE["street"],
        city=JOVANY_OWENS_PROFILE["city"],
        state=JOVANY_OWENS_PROFILE["state"],
        zip=JOVANY_OWENS_PROFILE["zip"],
        country=JOVANY_OWENS_PROFILE["country"],
        cc_number=JOVANY_OWENS_PROFILE["cc_number"],
        cc_exp=JOVANY_OWENS_PROFILE["cc_exp"],
        cc_cvv=JOVANY_OWENS_PROFILE["cc_cvv"],
        cc_holder=JOVANY_OWENS_PROFILE["cc_holder"],
        google_email=JOVANY_OWENS_PROFILE["google_email"],
        google_password=JOVANY_OWENS_PROFILE["google_password"],
        proxy_url=JOVANY_OWENS_PROFILE["proxy_url"],
        device_model=JOVANY_OWENS_PROFILE["device_model"],
        carrier=JOVANY_OWENS_PROFILE["carrier"],
        location=JOVANY_OWENS_PROFILE["location"],
        age_days=JOVANY_OWENS_PROFILE["age_days"],
        # Skip options
        skip_wipe=0 in (skip_phases or []),
        skip_patch=1 in (skip_phases or []),
        skip_proxy=2 in (skip_phases or []),
    )
    
    # Progress callback
    def on_update(result):
        print(f"\n[Phase {result.phases[-1].phase}] {result.phases[-1].name}: {result.phases[-1].status}")
        if result.phases[-1].notes:
            print(f"  Notes: {result.phases[-1].notes}")
    
    # Run pipeline
    print("\n[INIT] Starting 12-phase Genesis pipeline...")
    print(f"[CONFIG] Device: {cfg.device_model}, Carrier: {cfg.carrier}, Age: {cfg.age_days} days")
    print(f"[CONFIG] Proxy: {cfg.proxy_url[:50]}...")
    print(f"[CONFIG] Card: ****{cfg.cc_number[-4:]} ({cfg.cc_holder})")
    print()
    
    try:
        result = await engine.run_pipeline(
            cfg=cfg,
            job_id=f"jovany-{pad_code[:8]}",
            on_update=on_update,
        )
        
        # Print final results
        print("\n" + "=" * 70)
        print("FORGE COMPLETE")
        print("=" * 70)
        print(f"Job ID: {result.job_id}")
        print(f"Profile ID: {result.profile_id}")
        print(f"Trust Score: {result.trust_score}/100 (Grade {result.grade})")
        print(f"Duration: {result.completed_at - result.started_at:.0f}s")
        print(f"\nPhase Summary:")
        for ph in result.phases:
            status_icon = "✓" if ph.status == "done" else "⚠" if ph.status == "warn" else "✗"
            print(f"  {status_icon} Phase {ph.phase}: {ph.name} = {ph.status}")
        
        # Print log excerpt
        print(f"\nLast 10 Log Entries:")
        for line in result.log[-10:]:
            print(f"  > {line}")
        
        # Save report
        report_path = Path(f"/opt/titan/data/reports/jovany-{pad_code}-{result.grade}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(engine.result_dict(), f, indent=2)
        print(f"\nReport saved: {report_path}")
        
        return result
        
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")
        raise


# ═════════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ═════════════════════════════════════════════════════════════════════════════

async def verify_device(pad_code: str):
    """Quick verification of device state after forge."""
    from vmos_cloud_module import VMOSCloudBridge
    
    print(f"\n{'=' * 70}")
    print(f"VERIFICATION — {pad_code}")
    print(f"{'=' * 70}")
    
    bridge = VMOSCloudBridge()
    
    # Get device properties
    print("\n[1] Device Properties:")
    props = await bridge.get_android_props(pad_code)
    key_props = [
        "ro.product.model", "ro.product.brand", "ro.build.fingerprint",
        "ro.serialno", "gsm.sim.operator.alpha", "gsm.sim.operator.numeric"
    ]
    for prop in key_props:
        val = props.get(prop, "?")
        print(f"  {prop}: {val}")
    
    # Screenshot
    print("\n[2] Screenshot:")
    ss = await bridge.screenshot(pad_code)
    if ss.get("code") == 200:
        ss_url = ss.get("data", [{}])[0].get("imageUrl", "N/A")
        print(f"  URL: {ss_url[:80]}...")
    
    # Check account injection
    print("\n[3] Account Check:")
    accounts = await bridge.get_accounts(pad_code)
    if accounts.get("code") == 200:
        acct_data = accounts.get("data", [])
        print(f"  Accounts: {len(acct_data)}")
        for a in acct_data:
            print(f"    - {a.get('name', '?')} ({a.get('type', '?')})")
    
    print("\n[4] Verification Complete.")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Forge Jovany Owens identity on VMOS Pro cloud device"
    )
    parser.add_argument(
        "--pad-code", "-p",
        required=True,
        help="VMOS Cloud device PAD code (e.g., ACP2509244LGV1MV)"
    )
    parser.add_argument(
        "--verify", "-v",
        action="store_true",
        help="Run verification only (skip forge)"
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        type=int,
        help="Phase indices to skip (0=wipe, 1=stealth, 2=proxy, etc.)"
    )
    parser.add_argument(
        "--env",
        default="/opt/titan-v13-device/.env",
        help="Path to .env file with VMOS credentials"
    )
    
    args = parser.parse_args()
    
    # Load environment
    if Path(args.env).exists():
        print(f"[INIT] Loading environment from {args.env}")
        # Set for the VMOS modules to read
        os.environ.setdefault("VMOS_API_KEY", "")
        os.environ.setdefault("VMOS_API_SECRET", "")
        os.environ.setdefault("VMOS_API_HOST", "api.vmoscloud.com")
    
    # Execute
    if args.verify:
        asyncio.run(verify_device(args.pad_code))
    else:
        result = asyncio.run(forge_jovany_owens(args.pad_code, args.skip))
        
        # Exit code based on trust score
        if result.trust_score >= 80:
            print("\n[SUCCESS] Forge achieved A-grade (≥80/100)")
            sys.exit(0)
        elif result.trust_score >= 60:
            print("\n[WARNING] Forge achieved C-grade (60-79/100)")
            sys.exit(1)
        else:
            print("\n[FAILURE] Forge below acceptable threshold (<60/100)")
            sys.exit(2)


if __name__ == "__main__":
    main()
