"""
Titan V13.0 — Unified Genesis Router
====================================
API endpoints for the unified Genesis Studio single-tab interface.

Endpoints:
    POST /api/unified-genesis/start        - Start unified genesis pipeline
    GET  /api/unified-genesis/status/{id}  - Get job status
    GET  /api/unified-genesis/phases       - Get pipeline phase definitions
    GET  /api/unified-genesis/countries    - Get supported countries
    GET  /api/unified-genesis/aging-levels - Get aging level configs
    POST /api/unified-genesis/calculate    - Calculate optimal profile params
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager, PERMANENT_DEVICE_ID
from unified_genesis_engine import (
    UnifiedGenesisEngine,
    GenesisConfig,
    calculate_optimal_aging_profile,
    get_pipeline_phases,
    get_supported_countries,
    get_aging_levels,
    get_purchase_frequencies,
    COUNTRY_PROFILES,
)

router = APIRouter(prefix="/api/unified-genesis", tags=["unified-genesis"])
logger = logging.getLogger("titan.unified-genesis-router")

dm: DeviceManager = None
_engine: UnifiedGenesisEngine = None


def init(device_manager: DeviceManager):
    """Initialize router with device manager."""
    global dm, _engine
    dm = device_manager
    _engine = UnifiedGenesisEngine(device_manager=dm)


# ═══════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════

class UnifiedGenesisRequest(BaseModel):
    """Complete unified genesis request body."""
    # Device
    device_id: str = ""
    
    # Identity
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    ssn: str = ""
    gender: str = "M"
    occupation: str = "professional"
    
    # Address
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    
    # Payment
    cc_number: str = ""
    cc_exp: str = ""  # MM/YYYY
    cc_cvv: str = ""
    cc_holder: str = ""
    
    # Google Account
    google_email: str = ""
    google_password: str = ""
    real_phone: str = ""
    otp_code: str = ""
    
    # Device Config
    device_model: str = "samsung_s24"
    carrier: str = "tmobile_us"
    location: str = "la"
    proxy_url: str = ""
    
    # Aging Config
    age_days: int = 90
    aging_level: str = "medium"
    purchase_frequency: str = "moderate"
    purchase_categories: List[str] = ["groceries", "restaurants", "online_shopping", "subscriptions"]
    browsing_intensity: str = "normal"
    social_activity: str = "moderate"
    app_usage: str = "normal"
    
    # Options
    skip_wipe: bool = False
    skip_patch: bool = False
    skip_wallet: bool = False
    skip_google: bool = False
    use_ai: bool = True
    run_trust_audit: bool = True
    run_attestation_check: bool = True
    enable_immune_watchdog: bool = True


class CalculateProfileRequest(BaseModel):
    """Request for optimal profile calculation."""
    country: str = "US"
    age_days: int = 90
    purchase_frequency: str = "moderate"
    occupation: str = "professional"


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/start")
async def unified_genesis_start(body: UnifiedGenesisRequest):
    """
    Start the unified genesis pipeline.
    
    This endpoint orchestrates all genesis operations in a single job:
    - Pre-flight ADB check
    - Factory wipe (optional)
    - Stealth patch (26 phases, 103+ vectors)
    - Network/proxy configuration
    - Profile forge (contacts, SMS, calls, browser data)
    - Payment history generation
    - Google account injection
    - Profile injection
    - Wallet provisioning (Google Pay, Chrome Autofill)
    - App bypass configuration
    - Browser hardening
    - Play Integrity defense
    - Sensor warmup
    - Immune watchdog
    - Trust audit (14 checks)
    - Final verification
    
    Returns job_id for polling status via /status/{job_id}
    """
    global _engine
    
    if not _engine:
        _engine = UnifiedGenesisEngine(device_manager=dm)
    
    # Get device
    device_id = body.device_id or PERMANENT_DEVICE_ID
    dev = dm.get_device(device_id) if dm else None
    
    if not dev:
        raise HTTPException(404, f"Device not found: {device_id}")
    
    # Basic input validation for sensitive fields
    body_dict = body.model_dump()
    
    # Sanitize credit card (basic format validation)
    if body_dict.get("cc_number"):
        cc = body_dict["cc_number"].replace(" ", "").replace("-", "")
        if not cc.isdigit() or len(cc) < 13 or len(cc) > 19:
            raise HTTPException(400, "Invalid credit card number format. Must be 13-19 digits.")
        body_dict["cc_number"] = cc
    
    # Validate age_days range
    if body_dict.get("age_days"):
        body_dict["age_days"] = max(1, min(900, body_dict["age_days"]))
    
    # Build config from validated request
    config = GenesisConfig.from_dict({
        "device_id": device_id,
        "adb_target": dev.adb_target,
        **body_dict
    })
    
    # Start genesis
    result = _engine.start(config)
    
    return {
        "status": "started",
        "job_id": result.job_id,
        "device_id": device_id,
        "poll_url": f"/api/unified-genesis/status/{result.job_id}",
        "phases_count": len(result.phases),
    }


@router.get("/status/{job_id}")
async def unified_genesis_status(job_id: str):
    """
    Get status of a unified genesis job.
    
    Returns:
    - status: pending | running | completed | failed
    - progress: 0-100 percentage
    - phases: list of phase statuses
    - trust_score: 0-100
    - trust_grade: A+, A, B, C, F
    - patch_score: 0-100
    - wallet_score: 0-100
    - log: recent log entries
    """
    global _engine
    
    if not _engine:
        raise HTTPException(404, "Engine not initialized")
    
    result = _engine.get_job(job_id)
    if not result:
        raise HTTPException(404, f"Job not found: {job_id}")
    
    return result.to_dict()


@router.get("/phases")
async def unified_genesis_phases():
    """
    Get pipeline phase definitions.
    
    Returns list of phases with id, name, and description.
    """
    return {
        "phases": get_pipeline_phases(),
        "total": len(get_pipeline_phases()),
    }


@router.get("/countries")
async def unified_genesis_countries():
    """
    Get supported countries with their configurations.
    
    Returns country codes with locale, timezone, currency,
    default carrier/location, and popular apps/merchants.
    """
    return {
        "countries": get_supported_countries(),
    }


@router.get("/aging-levels")
async def unified_genesis_aging_levels():
    """
    Get aging level configurations.
    
    Returns light/medium/heavy configurations with
    data volume ranges for each profile element.
    """
    return {
        "aging_levels": get_aging_levels(),
        "purchase_frequencies": get_purchase_frequencies(),
    }


@router.post("/calculate")
async def unified_genesis_calculate(body: CalculateProfileRequest):
    """
    Calculate optimal profile parameters based on country and age.
    
    This algorithm determines recommended data volumes, merchants,
    apps, and configuration based on:
    - Country (locale, timezone, popular services)
    - Target age (contacts, calls, SMS, browser data)
    - Purchase frequency (transaction density)
    - Occupation (archetype-specific patterns)
    
    Use this to preview what the genesis will produce before starting.
    """
    result = calculate_optimal_aging_profile(
        country=body.country,
        target_age_days=body.age_days,
        purchase_frequency=body.purchase_frequency,
        occupation=body.occupation,
    )
    
    return {
        "calculated_profile": result,
        "summary": {
            "aging_level": result["aging_level"],
            "estimated_contacts": f"{result['contacts_range'][0]}-{result['contacts_range'][1]}",
            "estimated_transactions": f"{result['transaction_range'][0]}-{result['transaction_range'][1]}",
            "recommended_apps": len(result["recommended_apps"]),
        }
    }


@router.get("/presets")
async def unified_genesis_presets():
    """
    Get predefined genesis presets for quick configuration.
    """
    return {
        "presets": [
            {
                "id": "us_standard_90d",
                "name": "US Standard 90-Day",
                "description": "Standard US persona with 90-day aging, moderate activity",
                "config": {
                    "country": "US",
                    "age_days": 90,
                    "aging_level": "medium",
                    "purchase_frequency": "moderate",
                    "device_model": "samsung_s24",
                    "carrier": "tmobile_us",
                    "location": "la",
                }
            },
            {
                "id": "us_heavy_365d",
                "name": "US Heavy 365-Day",
                "description": "Established US persona with 1-year history, high activity",
                "config": {
                    "country": "US",
                    "age_days": 365,
                    "aging_level": "heavy",
                    "purchase_frequency": "high",
                    "device_model": "pixel_9_pro",
                    "carrier": "verizon_us",
                    "location": "nyc",
                }
            },
            {
                "id": "uk_standard_90d",
                "name": "UK Standard 90-Day",
                "description": "Standard UK persona with 90-day aging",
                "config": {
                    "country": "GB",
                    "age_days": 90,
                    "aging_level": "medium",
                    "purchase_frequency": "moderate",
                    "device_model": "samsung_s25_ultra",
                    "carrier": "ee_uk",
                    "location": "london",
                }
            },
            {
                "id": "de_standard_90d",
                "name": "DE Standard 90-Day",
                "description": "Standard German persona with 90-day aging",
                "config": {
                    "country": "DE",
                    "age_days": 90,
                    "aging_level": "medium",
                    "purchase_frequency": "moderate",
                    "device_model": "samsung_s24",
                    "carrier": "vodafone_de",
                    "location": "berlin",
                }
            },
            {
                "id": "quick_30d",
                "name": "Quick 30-Day Setup",
                "description": "Fast light-weight persona for testing",
                "config": {
                    "country": "US",
                    "age_days": 30,
                    "aging_level": "light",
                    "purchase_frequency": "low",
                    "device_model": "pixel_8a",
                    "carrier": "att_us",
                    "location": "sf",
                }
            },
        ]
    }


@router.get("/algorithm")
async def unified_genesis_algorithm():
    """
    Get the complete algorithm documentation for the unified genesis pipeline.
    
    This describes all phases, their dependencies, and the overall flow.
    """
    return {
        "algorithm": {
            "name": "Unified Genesis Pipeline",
            "version": "1.0.0",
            "description": "Complete device aging and identity forging algorithm",
            "total_phases": 16,
            "estimated_duration": "5-15 minutes depending on options",
            
            "phases": [
                {
                    "id": 0,
                    "name": "Pre-Flight Check",
                    "description": "Validates ADB connectivity and device readiness",
                    "duration": "~5s",
                    "dependencies": [],
                    "can_skip": False,
                },
                {
                    "id": 1,
                    "name": "Factory Wipe",
                    "description": "Clears all previous persona artifacts (accounts, contacts, SMS, media, wallet)",
                    "duration": "~10s",
                    "dependencies": [0],
                    "can_skip": True,
                    "skip_option": "skip_wipe",
                },
                {
                    "id": 2,
                    "name": "Stealth Patch",
                    "description": "Applies 26-phase anomaly patching with 103+ detection vector fixes",
                    "duration": "3-6 minutes",
                    "dependencies": [0],
                    "can_skip": True,
                    "skip_option": "skip_patch",
                    "sub_phases": [
                        "identity", "telephony", "anti_emulator", "build_verification",
                        "rasp_evasion", "gpu_graphics", "battery", "location",
                        "media_history", "network", "gms_integrity", "keybox_attestation",
                        "gsf_alignment", "sensors", "bluetooth", "proc_sterilize",
                        "camera", "nfc_storage", "wifi_scan", "selinux",
                        "storage_encryption", "process_stealth", "audio",
                        "kinematic_input", "kernel_hardening", "persistence"
                    ]
                },
                {
                    "id": 3,
                    "name": "Network Config",
                    "description": "Configures IPv6 kill and SOCKS5 proxy if provided",
                    "duration": "~5s",
                    "dependencies": [0],
                    "can_skip": False,
                },
                {
                    "id": 4,
                    "name": "Forge Profile",
                    "description": "Generates complete persona data (contacts, SMS, calls, browser history/cookies, gallery, WiFi, apps)",
                    "duration": "~10s",
                    "dependencies": [3],
                    "can_skip": False,
                    "outputs": ["contacts", "call_logs", "sms", "chrome_history", "chrome_cookies", "gallery", "wifi_networks", "app_installs", "autofill"],
                },
                {
                    "id": 5,
                    "name": "Payment History",
                    "description": "Generates realistic transaction history with circadian patterns",
                    "duration": "~5s",
                    "dependencies": [4],
                    "can_skip": True,
                    "skip_condition": "No payment card provided",
                },
                {
                    "id": 6,
                    "name": "Google Account",
                    "description": "Injects Google account into 8 Android subsystems (CE/DE databases, GMS prefs, OAuth tokens)",
                    "duration": "~20s",
                    "dependencies": [4],
                    "can_skip": True,
                    "skip_option": "skip_google",
                },
                {
                    "id": 7,
                    "name": "Profile Inject",
                    "description": "Pushes all forged data to device via ADB (contacts, SMS, browser data, gallery)",
                    "duration": "~30s",
                    "dependencies": [4, 5, 6],
                    "can_skip": False,
                },
                {
                    "id": 8,
                    "name": "Wallet Provision",
                    "description": "Provisions Google Pay, Chrome Autofill, GMS Billing with card data",
                    "duration": "~15s",
                    "dependencies": [7],
                    "can_skip": True,
                    "skip_option": "skip_wallet",
                },
                {
                    "id": 9,
                    "name": "App Bypass",
                    "description": "Injects V3 app bypass configurations for target apps (SharedPrefs, databases)",
                    "duration": "~10s",
                    "dependencies": [7],
                    "can_skip": False,
                },
                {
                    "id": 10,
                    "name": "Browser Harden",
                    "description": "Writes Kiwi browser preferences and triggers media scanner",
                    "duration": "~5s",
                    "dependencies": [7],
                    "can_skip": False,
                },
                {
                    "id": 11,
                    "name": "Play Integrity",
                    "description": "Checks attestation state (keybox, verified boot, build type)",
                    "duration": "~5s",
                    "dependencies": [2],
                    "can_skip": False,
                },
                {
                    "id": 12,
                    "name": "Sensor Warmup",
                    "description": "Initializes OADEV-coupled sensor noise for realistic accelerometer/gyro data",
                    "duration": "~10s",
                    "dependencies": [2],
                    "can_skip": False,
                },
                {
                    "id": 13,
                    "name": "Immune Watchdog",
                    "description": "Deploys honeypot files, process cloaking, and port lockdown",
                    "duration": "~10s",
                    "dependencies": [2],
                    "can_skip": True,
                    "skip_option": "enable_immune_watchdog=false",
                },
                {
                    "id": 14,
                    "name": "Trust Audit",
                    "description": "Runs 14-check trust scoring (Google Account, Chrome, Wallet, Contacts, etc.)",
                    "duration": "~10s",
                    "dependencies": [7, 8],
                    "can_skip": True,
                    "skip_option": "run_trust_audit=false",
                    "checks": [
                        {"name": "google_account", "weight": 15},
                        {"name": "chrome_cookies", "weight": 10},
                        {"name": "chrome_history", "weight": 10},
                        {"name": "wallet_payment", "weight": 10},
                        {"name": "contacts", "weight": 8},
                        {"name": "call_logs", "weight": 8},
                        {"name": "sms_threads", "weight": 8},
                        {"name": "gallery_photos", "weight": 8},
                        {"name": "autofill_data", "weight": 7},
                        {"name": "wifi_networks", "weight": 5},
                        {"name": "app_install_dates", "weight": 5},
                        {"name": "gms_prefs", "weight": 5},
                        {"name": "device_props", "weight": 3},
                        {"name": "behavioral_depth", "weight": 3},
                    ]
                },
                {
                    "id": 15,
                    "name": "Final Verify",
                    "description": "Generates final report with all scores and verification status",
                    "duration": "~5s",
                    "dependencies": [14],
                    "can_skip": False,
                },
            ],
            
            "user_inputs": {
                "required": ["device_id"],
                "persona": ["name", "email", "phone", "dob", "ssn", "gender", "occupation"],
                "address": ["street", "city", "state", "zip", "country"],
                "payment": ["cc_number", "cc_exp", "cc_cvv", "cc_holder"],
                "google": ["google_email", "google_password", "real_phone", "otp_code"],
                "device": ["device_model", "carrier", "location", "proxy_url"],
                "aging": ["age_days", "aging_level", "purchase_frequency", "browsing_intensity", "social_activity", "app_usage"],
                "options": ["skip_wipe", "skip_patch", "skip_wallet", "skip_google", "use_ai", "run_trust_audit", "enable_immune_watchdog"],
            },
            
            "outputs": {
                "trust_score": "0-100 score based on 14 checks",
                "trust_grade": "A+ (≥95), A (≥85), B (≥70), C (≥50), F (<50)",
                "patch_score": "0-100% stealth score from anomaly patcher",
                "wallet_score": "0-100% based on 4 wallet subsystems",
                "attestation_ok": "Boolean Play Integrity readiness",
                "profile_id": "TITAN-XXXXXXXX profile identifier",
            }
        }
    }
