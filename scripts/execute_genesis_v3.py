#!/usr/bin/env python3
"""
TITAN-X: GENESIS PIPELINE V3 MASTER EXECUTOR

5-phase pipeline:
  1. Identity Fabrication  (AndroidProfileForge)
  2. System Injection      (ProfileInjector)
  3. Wallet Provisioning   (WalletProvisioner — zero-auth)
  4. Provincial Layering   (AppDataForger — V3 bypass configs)
  5. Traffic Warm-up       (DeviceAgent — browse/YouTube)
"""
import os
import sys
import argparse
import logging

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from typing import Dict, Any, List, Optional
from core.android_profile_forge import AndroidProfileForge
from core.profile_injector import ProfileInjector
from core.wallet_provisioner import WalletProvisioner
from core.app_data_forger import AppDataForger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] TITAN: %(message)s",
)
logger = logging.getLogger("titan.genesis-v3")

# ── Provincial Constants ────────────────────────────────────────────
PROVINCE_CONFIG: Dict[str, Dict[str, Any]] = {
    "US": {
        "carrier": "tmobile_us",
        "location": "nyc",
        "targets": [
            "com.coinbase.android",
            "com.amazon.mShop.android.shopping",
            "com.chase.sig.android",
            "com.venmo",
            "com.paypal.android.p2pmobile",
        ],
    },
    "GB": {
        "carrier": "ee_uk",
        "location": "london",
        "targets": [
            "com.binance.dev",
            "com.amazon.mShop.android.shopping",
            "com.ebay.mobile",
            "com.monzo.android",
            "com.revolut.revolut",
        ],
    },
}


def execute_pipeline(
    adb_target: str,
    country: str,
    age_days: int,
    persona_name: str,
    persona_email: str,
    persona_phone: str,
    archetype: str,
    device_model: str,
    cc_number: Optional[str] = None,
    cc_exp_month: Optional[int] = None,
    cc_exp_year: Optional[int] = None,
    cc_cvv: Optional[str] = None,
    cc_holder: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full Genesis V3 pipeline. Returns summary dict."""

    prov = PROVINCE_CONFIG.get(country.upper())
    if not prov:
        raise ValueError(f"Unsupported country '{country}'. Supported: {list(PROVINCE_CONFIG)}")

    results: Dict[str, Any] = {"country": country, "adb_target": adb_target}

    # ── Phase 1: Identity Fabrication ──────────────────────────────
    logger.info("Phase 1 — Forging identity (The Soul)...")
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=persona_name,
        persona_email=persona_email,
        persona_phone=persona_phone,
        country=country,
        archetype=archetype,
        age_days=age_days,
        carrier=prov["carrier"],
        location=prov["location"],
        device_model=device_model,
    )
    profile_id = profile.get("uuid", "unknown")
    logger.info(f"Phase 1 — Identity forged: {profile_id} ({country})")
    results["profile_id"] = profile_id

    # ── Phase 2: System Injection ──────────────────────────────────
    logger.info("Phase 2 — Injecting foundation (System)...")
    injector = ProfileInjector(adb_target=adb_target)
    inj_result = injector.inject_full_profile(profile)
    if not inj_result.success:
        logger.error(f"Phase 2 — Injection FAILED: {inj_result.errors}")
        results["injection"] = "FAILED"
        return results
    logger.info(f"Phase 2 — Injection OK, trust={inj_result.trust_score}")
    results["injection"] = "OK"
    results["trust_score_post_inject"] = inj_result.trust_score

    # ── Phase 3: Wallet Provisioning (Zero-Auth) ───────────────────
    if cc_number:
        logger.info(f"Phase 3 — Provisioning wallet (Zero-Auth), card ...{cc_number[-4:]}")
        wp = WalletProvisioner(adb_target=adb_target)
        wp_result = wp.provision_card(
            card_number=cc_number,
            exp_month=cc_exp_month or 12,
            exp_year=cc_exp_year or 2029,
            cardholder=cc_holder or persona_name,
            cvv=cc_cvv or "",
            persona_email=persona_email,
            persona_name=persona_name,
            country=country,
            zero_auth=True,
        )
        wp_ok = sum([
            getattr(wp_result, "google_pay_ok", False),
            getattr(wp_result, "play_store_ok", False),
            getattr(wp_result, "chrome_autofill_ok", False),
            getattr(wp_result, "gms_billing_ok", False),
        ])
        logger.info(f"Phase 3 — Wallet done: {wp_ok}/4 subsystems OK")
        results["wallet"] = f"{wp_ok}/4"
    else:
        logger.info("Phase 3 — Wallet skipped (no card data)")
        results["wallet"] = "skipped"

    # ── Phase 4: Provincial Layering (App V3 Bypass) ───────────────
    targets: List[str] = prov["targets"]
    logger.info(f"Phase 4 — Provincial layering: {len(targets)} targets for {country}")
    app_forger = AppDataForger(adb_target=adb_target)
    app_result = app_forger.forge_and_inject(
        installed_packages=targets,
        persona={
            "email": persona_email,
            "name": persona_name,
            "phone": persona_phone,
            "country": country,
        },
        play_purchases=profile.get("play_purchases"),
        app_installs=profile.get("app_installs"),
    )
    logger.info(f"Phase 4 — Provincial layering: {app_result.injected}/{app_result.total} apps OK")
    results["provincial"] = f"{app_result.injected}/{app_result.total}"

    # ── Phase 5: Traffic Warm-up ───────────────────────────────────
    logger.info("Phase 5 — Traffic warm-up (The Mask)...")
    try:
        from core.device_agent import DeviceAgent
        agent = DeviceAgent(adb_target=adb_target)
        warmup_tasks = ["aging_browse", "aging_youtube"]
        for task_name in warmup_tasks:
            logger.info(f"Phase 5 — Running warm-up task: {task_name}")
            agent.start_task(task_name)
        results["warmup"] = "OK"
    except Exception as exc:
        logger.warning(f"Phase 5 — Warm-up failed (non-fatal): {exc}")
        results["warmup"] = f"FAILED: {exc}"

    logger.info("GENESIS PIPELINE V3 COMPLETE — device READY.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="TITAN-X Genesis Pipeline V3 Executor")
    parser.add_argument("--adb-target", default="127.0.0.1:6520", help="ADB target (host:port)")
    parser.add_argument("--country", default="US", choices=["US", "GB"], help="Provincial target")
    parser.add_argument("--age-days", type=int, default=180, help="Profile age in days")
    parser.add_argument("--name", default="Alex Mercer", help="Persona full name")
    parser.add_argument("--email", default="alex.mercer@gmail.com", help="Persona email")
    parser.add_argument("--phone", default="+12125551234", help="Persona phone")
    parser.add_argument("--archetype", default="professional",
                        choices=["professional", "student", "night_shift", "retiree", "gamer"])
    parser.add_argument("--device-model", default="samsung_s25_ultra", help="Device preset name")
    parser.add_argument("--cc-number", default=None, help="Credit card number for wallet")
    parser.add_argument("--cc-exp-month", type=int, default=None, help="CC expiry month")
    parser.add_argument("--cc-exp-year", type=int, default=None, help="CC expiry year")
    parser.add_argument("--cc-cvv", default=None, help="CC CVV")
    parser.add_argument("--cc-holder", default=None, help="CC cardholder (defaults to persona name)")

    args = parser.parse_args()

    result = execute_pipeline(
        adb_target=args.adb_target,
        country=args.country,
        age_days=args.age_days,
        persona_name=args.name,
        persona_email=args.email,
        persona_phone=args.phone,
        archetype=args.archetype,
        device_model=args.device_model,
        cc_number=args.cc_number,
        cc_exp_month=args.cc_exp_month,
        cc_exp_year=args.cc_exp_year,
        cc_cvv=args.cc_cvv,
        cc_holder=args.cc_holder,
    )

    logger.info(f"Pipeline result: {result}")


if __name__ == "__main__":
    main()
