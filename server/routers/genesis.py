"""
Titan V11.3 — Genesis Router
/api/genesis/* — Profile forge, smartforge, profiles CRUD, trust score
Provision/inject/age-device endpoints are in provision.py.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_dm
from device_manager import DeviceManager
from android_profile_forge import AndroidProfileForge

router = APIRouter(prefix="/api/genesis", tags=["genesis"])
logger = logging.getLogger("titan.genesis")

dm: DeviceManager = None
_forge = AndroidProfileForge()


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class GenesisCreateBody(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    country: str = "US"
    archetype: str = "professional"
    age_days: int = 90
    carrier: str = "tmobile_us"
    location: str = "nyc"
    device_model: str = "samsung_s25_ultra"
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    install_wallets: bool = True
    pre_login: bool = True
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""


class SmartForgeBody(BaseModel):
    occupation: str = "software_engineer"
    country: str = "US"
    age: int = 30
    gender: str = "auto"
    target_site: str = "amazon.com"
    use_ai: bool = False
    age_days: int = 0
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""


def _profiles_dir() -> Path:
    d = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/create")
async def genesis_create(body: GenesisCreateBody):
    """Forge a complete Android device profile. All fields derived from persona inputs."""
    try:
        # Build persona address from user inputs
        persona_address = None
        
        street = body.street or ''
        city = body.city or ''
        state = body.state or ''
        zip_code = body.zip or ''
        
        # Build address dict if any address field provided
        if street or city or state or zip_code:
            persona_address = {
                "address": street,
                "city": city,
                "state": state,
                "zip": zip_code,
                "country": body.country,
            }
        
        # If cardholder provided but no address, try to derive from location
        if body.cc_cardholder and not persona_address:
            from device_presets import LOCATIONS
            loc_config = LOCATIONS.get(body.location, {})
            if loc_config:
                persona_address = {
                    "address": "",  # Will be generated
                    "city": loc_config.get("city", ""),
                    "state": loc_config.get("state", ""),
                    "zip": loc_config.get("zip", ""),
                    "country": body.country,
                }

        profile = _forge.forge(
            persona_name=body.name, persona_email=body.email, persona_phone=body.phone,
            country=body.country, archetype=body.archetype, age_days=body.age_days,
            carrier=body.carrier, location=body.location, device_model=body.device_model,
            persona_address=persona_address,
        )
        pf = _profiles_dir() / f"{profile['id']}.json"
        pf.write_text(json.dumps(profile))
        return {
            "profile_id": profile["id"],
            "stats": profile["stats"],
            "persona": {"name": profile["persona_name"], "email": profile["persona_email"], "phone": profile["persona_phone"]},
        }
    except Exception as e:
        logger.exception("Genesis forge failed")
        raise HTTPException(500, str(e))


@router.get("/profiles")
async def genesis_list():
    """List all forged profiles."""
    profiles = []
    for f in sorted(_profiles_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            profiles.append({
                "id": data.get("id", f.stem), "persona_name": data.get("persona_name", ""),
                "persona_email": data.get("persona_email", ""), "country": data.get("country", ""),
                "archetype": data.get("archetype", ""), "age_days": data.get("age_days", 0),
                "device_model": data.get("device_model", ""), "created_at": data.get("created_at", ""),
                "stats": data.get("stats", {}),
            })
        except Exception as e:
            logger.warning(f"Failed to read profile {f.name}: {e}")
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/profiles/{profile_id}")
async def genesis_get(profile_id: str):
    pf = _profiles_dir() / f"{profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, "Profile not found")
    return json.loads(pf.read_text())


@router.delete("/profiles/{profile_id}")
async def genesis_delete(profile_id: str):
    pf = _profiles_dir() / f"{profile_id}.json"
    if pf.exists():
        pf.unlink()
    return {"deleted": profile_id}


@router.get("/trust-score/{device_id}")
async def genesis_trust_score(device_id: str, device_mgr: DeviceManager = Depends(get_dm)):
    """Compute trust score for a device based on injected data presence."""
    dev = device_mgr.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    from trust_scorer import compute_trust_score
    result = compute_trust_score(dev.adb_target)
    result["device_id"] = device_id
    return result


@router.post("/smartforge")
async def genesis_smartforge(body: SmartForgeBody):
    """AI-powered SmartForge: persona-driven forge with ALL fields from user inputs."""
    try:
        from smartforge_bridge import smartforge_for_android

        override = {}
        for field_name in ["name", "email", "phone", "dob", "street", "city", "state", "zip", "card_number", "card_exp", "card_cvv"]:
            val = getattr(body, field_name, "")
            if val:
                override[field_name] = val

        android_config = smartforge_for_android(
            occupation=body.occupation, country=body.country, age=body.age,
            gender=body.gender, target_site=body.target_site, use_ai=body.use_ai,
            identity_override=override if override else None, age_days=body.age_days,
        )

        # Build persona_address from resolved SmartForge config
        persona_address = None
        if android_config.get("street"):
            persona_address = {
                "address": android_config["street"],
                "city": android_config.get("city", ""),
                "state": android_config.get("state", ""),
                "zip": android_config.get("zip", ""),
                "country": android_config.get("country", "US"),
            }

        profile = _forge.forge(
            persona_name=android_config["persona_name"], persona_email=android_config["persona_email"],
            persona_phone=android_config["persona_phone"], country=android_config["country"],
            archetype=android_config["archetype"], age_days=android_config["age_days"],
            carrier=android_config["carrier"], location=android_config["location"],
            device_model=android_config["device_model"],
            persona_address=persona_address,
            persona_area_code=android_config.get("persona_area_code", ""),
            city_area_codes=android_config.get("city_area_codes", []),
        )

        profile["smartforge_config"] = android_config.get("smartforge_config", {})
        profile["browsing_sites"] = android_config.get("browsing_sites", [])
        profile["cookie_sites"] = android_config.get("cookie_sites", [])
        profile["purchase_categories"] = android_config.get("purchase_categories", [])
        profile["social_platforms"] = android_config.get("social_platforms", [])

        return {
            "profile_id": profile["id"], "stats": profile["stats"],
            "persona": {
                "name": android_config["persona_name"], "email": android_config["persona_email"],
                "phone": android_config["persona_phone"], "occupation": android_config["occupation"],
                "age": android_config["age"], "country": android_config["country"],
                "device_model": android_config["device_model"],
            },
            "smartforge": {
                "ai_enriched": android_config.get("ai_enriched", False),
                "osint_enriched": android_config.get("osint_enriched", False),
                "age_days": android_config["age_days"],
                "has_card": android_config.get("card_data") is not None,
                "carrier": android_config["carrier"],
                "locale": android_config.get("locale", ""),
                "timezone": android_config.get("timezone", ""),
            },
            "card_data": android_config.get("card_data"),
        }
    except Exception as e:
        logger.exception("SmartForge failed")
        raise HTTPException(500, str(e))


class OtpRequestBody(BaseModel):
    phone: str = ""


@router.post("/request-otp")
async def genesis_request_otp(body: OtpRequestBody):
    """Request OTP for Google account verification.
    
    The OTP is sent by Google to the real phone number during sign-in.
    This endpoint checks if an OTP has been received on the device
    (via SMS forwarding or notification interception).
    In most cases the user enters the OTP manually from their real phone.
    """
    if not body.phone:
        raise HTTPException(400, "Phone number required")
    
    # Check if device has received any recent OTP via SMS
    # This works if SMS forwarding is set up to the device
    try:
        import re
        from adb_utils import adb_shell
        # Try to read recent SMS for Google verification code
        sms_out = adb_shell(
            "127.0.0.1:6520",
            "content query --uri content://sms/inbox --projection body "
            "--sort \"date DESC\" 2>/dev/null | head -5"
        )
        if sms_out:
            code_match = re.search(r'G-(\d{6})', sms_out)
            if code_match:
                return {"otp": code_match.group(1), "source": "device_sms"}
            code_match = re.search(r'\b(\d{6})\b', sms_out)
            if code_match:
                return {"otp": code_match.group(1), "source": "device_sms"}
    except Exception as e:
        logger.debug(f"OTP auto-detect failed: {e}")
    
    return {"otp": None, "source": "manual", "message": f"Enter OTP sent to {body.phone} manually"}


@router.get("/profile-inspect/{profile_id}")
async def genesis_profile_inspect(profile_id: str):
    """Return rich visual inspection data for a forged profile.
    
    Structures all profile data into visual-friendly categories for the
    Genesis Studio Inspector tab: identity, contacts, call logs, SMS,
    cookies, browser history, gallery, wallet, purchase history,
    app installs, WiFi networks, notifications, email receipts, etc.
    """
    pf = _profiles_dir() / f"{profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, "Profile not found")
    data = json.loads(pf.read_text())

    # Build structured inspection response
    persona = {
        "name": data.get("persona_name", ""),
        "email": data.get("persona_email", ""),
        "phone": data.get("persona_phone", ""),
        "country": data.get("country", ""),
        "archetype": data.get("archetype", ""),
        "age_days": data.get("age_days", 0),
        "device_model": data.get("device_model", ""),
        "carrier": data.get("carrier", ""),
        "location": data.get("location", ""),
        "created_at": data.get("created_at", ""),
        "address": data.get("persona_address", {}),
    }

    contacts = data.get("contacts", [])
    call_logs = data.get("call_logs", [])
    sms_messages = data.get("sms", [])
    
    # Chrome data
    chrome = data.get("chrome_data", {})
    cookies = chrome.get("cookies", data.get("cookies", []))
    history = chrome.get("history", data.get("history", data.get("browser_history", [])))
    local_storage = chrome.get("local_storage", data.get("local_storage", {}))

    # Gallery — normalize to list of dicts
    raw_gallery = data.get("gallery", data.get("gallery_paths", []))
    gallery = []
    if isinstance(raw_gallery, list):
        for item in raw_gallery:
            if isinstance(item, dict):
                gallery.append(item)
            elif isinstance(item, str):
                import os.path
                gallery.append({
                    "filename": os.path.basename(item),
                    "path": item,
                })
    
    
    # Purchase & wallet
    play_purchases = data.get("play_purchases", [])
    payment_history = data.get("payment_history", [])
    email_receipts = data.get("email_receipts", [])
    
    # App installs
    app_installs = data.get("app_installs", [])
    
    # WiFi networks
    wifi_networks = data.get("wifi_networks", [])
    
    # Notifications
    notifications = data.get("notifications", [])
    
    # App usage
    app_usage = data.get("app_usage_stats", [])
    
    # Maps history
    maps_history = data.get("maps_history", {})
    
    stats = data.get("stats", {})

    return {
        "profile_id": profile_id,
        "persona": persona,
        "stats": stats,
        "contacts": contacts[:50],  # Limit for UI
        "contacts_total": len(contacts),
        "call_logs": call_logs[:50],
        "call_logs_total": len(call_logs),
        "sms": sms_messages[:50],
        "sms_total": len(sms_messages),
        "cookies": cookies[:80],
        "cookies_total": len(cookies) if isinstance(cookies, list) else 0,
        "browser_history": history[:80],
        "history_total": len(history) if isinstance(history, list) else 0,
        "local_storage": local_storage,
        "gallery": gallery[:30],
        "gallery_total": len(gallery) if isinstance(gallery, list) else 0,
        "play_purchases": play_purchases[:40],
        "play_purchases_total": len(play_purchases) if isinstance(play_purchases, list) else 0,
        "payment_history": payment_history[:30],
        "email_receipts": email_receipts[:20],
        "app_installs": app_installs[:50],
        "app_installs_total": len(app_installs) if isinstance(app_installs, list) else 0,
        "wifi_networks": wifi_networks[:20],
        "notifications": notifications[:30],
        "app_usage": app_usage[:30],
        "maps_history": {
            "searches": (maps_history.get("searches", []))[:20],
            "navigation": (maps_history.get("navigation", []))[:20],
        } if isinstance(maps_history, dict) else {},
    }


@router.get("/wallet-transactions/{device_id}")
async def genesis_wallet_transactions(device_id: str):
    """Retrieve wallet transaction history from device tapandpay.db."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    
    transactions = []
    card_info = {}
    try:
        from adb_utils import adb_shell
        
        # Get card info
        card_raw = adb_shell(
            dev.adb_target,
            "sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db "
            "'SELECT dpan_last_four, fpan_last4, card_description, issuer_name, "
            "expiry_month, expiry_year, status, token_type, created_timestamp, "
            "last_used_timestamp FROM tokens ORDER BY id DESC LIMIT 1' 2>/dev/null",
            timeout=10,
        )
        if card_raw.strip():
            parts = card_raw.strip().split("|")
            if len(parts) >= 8:
                card_info = {
                    "dpan_last4": parts[0],
                    "fpan_last4": parts[1],
                    "description": parts[2],
                    "issuer": parts[3],
                    "exp_month": parts[4],
                    "exp_year": parts[5],
                    "status": "ACTIVE" if parts[6] == "1" else "INACTIVE",
                    "token_type": parts[7],
                    "created": parts[8] if len(parts) > 8 else "",
                    "last_used": parts[9] if len(parts) > 9 else "",
                }
        
        # Get transactions
        tx_raw = adb_shell(
            dev.adb_target,
            "sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db "
            "'SELECT merchant_name, merchant_category_code, amount_micros, currency_code, "
            "transaction_type, transaction_status, timestamp_ms FROM transaction_history "
            "ORDER BY timestamp_ms DESC LIMIT 30' 2>/dev/null",
            timeout=10,
        )
        if tx_raw.strip():
            for line in tx_raw.strip().split("\n"):
                parts = line.split("|")
                if len(parts) >= 6:
                    amount_micros = int(parts[2]) if parts[2].isdigit() else 0
                    transactions.append({
                        "merchant": parts[0],
                        "mcc": parts[1],
                        "amount": f"{amount_micros / 1000000:.2f}",
                        "currency": parts[3],
                        "type": parts[4],
                        "status": parts[5],
                        "timestamp_ms": parts[6] if len(parts) > 6 else "",
                    })
    except Exception as e:
        logger.warning(f"Wallet transaction read failed: {e}")
    
    return {
        "device_id": device_id,
        "card": card_info,
        "transactions": transactions,
        "transaction_count": len(transactions),
    }


@router.get("/occupations")
async def genesis_occupations():
    from smartforge_bridge import get_occupations
    return {"occupations": get_occupations()}


@router.get("/countries")
async def genesis_countries():
    from smartforge_bridge import get_countries
    return {"countries": get_countries()}


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED FORGE — Merges Smart Forge + OSINT + Proxy into single flow
# ═══════════════════════════════════════════════════════════════════════

class UnifiedForgeBody(BaseModel):
    """Single request body for the merged forge tab."""
    # Mode (smart = AI-driven, manual = manual entry)
    mode: str = "smart"

    # Smart Forge inputs (AI-driven)
    occupation: str = "auto"
    country: str = "US"
    age: int = 28
    gender: str = "auto"
    target_site: str = ""
    use_ai: bool = True
    age_days: int = 90

    # Identity override (manual fields — takes priority)
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    ssn: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""

    # Card data
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""
    card_holder: str = ""

    # OSINT enrichment
    run_osint: bool = False
    osint_name: str = ""
    osint_email: str = ""
    osint_username: str = ""
    osint_phone: str = ""
    osint_domain: str = ""

    # Proxy config (socks5://user:pass@host:port)
    proxy_url: str = ""

    # Google account pre-injection
    google_email: str = ""
    google_password: str = ""
    real_phone: str = ""
    otp_code: str = ""

    # Device target
    device_id: str = ""
    device_model: str = "samsung_s25_ultra"
    carrier: str = "tmobile_us"
    location: str = "nyc"

    # Pipeline control
    inject: bool = False
    full_provision: bool = False


@router.get("/osint-status")
async def genesis_osint_status():
    """Return available OSINT tools and their install status."""
    try:
        from osint_orchestrator import OSINTOrchestrator
        orch = OSINTOrchestrator()
        status = orch.get_status()
        installed = [k for k, v in status.items() if v.get("installed")]
        missing = [k for k, v in status.items() if not v.get("installed")]
        return {"installed": installed, "missing": missing, "tools": status, "available": True}
    except Exception:
        return {"installed": [], "missing": ["sherlock", "maigret", "holehe"], "tools": {}, "available": False}


@router.post("/unified-forge")
async def genesis_unified_forge(body: UnifiedForgeBody):
    """Unified forge: AI SmartForge + OSINT enrichment + optional provision.

    Merges Smart Forge, manual identity, OSINT recon, proxy config, and
    device injection into a single atomic operation.
    """
    steps_log = []

    try:
        # ── Step 1: OSINT Recon (if requested) ─────────────────────────
        osint_data = None
        if body.run_osint and any([body.osint_name, body.osint_email,
                                   body.osint_username, body.osint_phone,
                                   body.osint_domain]):
            steps_log.append("Running OSINT recon...")
            try:
                from osint_orchestrator import OSINTOrchestrator
                orch = OSINTOrchestrator(
                    proxy=body.proxy_url if body.proxy_url else "",
                    timeout=45,
                )
                osint_result = orch.run(
                    name=body.osint_name,
                    email=body.osint_email,
                    username=body.osint_username,
                    phone=body.osint_phone,
                    domain=body.osint_domain,
                )
                osint_data = osint_result.to_dict()
                steps_log.append(
                    f"OSINT complete: {osint_data['total_hits']} hits, "
                    f"tools={osint_data['tools_run']}"
                )
            except Exception as e:
                steps_log.append(f"OSINT error (non-fatal): {e}")
                logger.warning(f"OSINT recon failed: {e}")

        # ── Step 2: SmartForge profile generation ──────────────────────
        steps_log.append("Running SmartForge...")
        from smartforge_bridge import smartforge_for_android

        override = {}
        for field_name in ["name", "email", "phone", "dob", "street", "city",
                           "state", "zip", "card_number", "card_exp", "card_cvv"]:
            val = getattr(body, field_name, "")
            if val:
                override[field_name] = val

        android_config = smartforge_for_android(
            occupation=body.occupation, country=body.country, age=body.age,
            gender=body.gender, target_site=body.target_site, use_ai=body.use_ai,
            identity_override=override if override else None, age_days=body.age_days,
        )

        # Merge OSINT enrichment into config
        if osint_data and osint_data.get("enrichment"):
            enrich = osint_data["enrichment"]
            if enrich.get("social_platforms"):
                existing = android_config.get("social_platforms", [])
                merged = list(dict.fromkeys(existing + enrich["social_platforms"]))
                android_config["social_platforms"] = merged
            android_config["osint_enriched"] = enrich.get("osint_enriched", False)

        steps_log.append(
            f"SmartForge: {android_config['persona_name']} "
            f"({android_config['occupation']}, {android_config['country']}, "
            f"age={android_config['age']})"
        )

        # ── Step 3: Forge complete profile ─────────────────────────────
        steps_log.append("Forging profile data...")
        persona_address = None
        if android_config.get("street"):
            persona_address = {
                "address": android_config["street"],
                "city": android_config.get("city", ""),
                "state": android_config.get("state", ""),
                "zip": android_config.get("zip", ""),
                "country": android_config.get("country", "US"),
            }

        profile = _forge.forge(
            persona_name=android_config["persona_name"],
            persona_email=android_config["persona_email"],
            persona_phone=android_config["persona_phone"],
            country=android_config["country"],
            archetype=android_config["archetype"],
            age_days=android_config["age_days"],
            carrier=android_config["carrier"],
            location=android_config["location"],
            device_model=android_config["device_model"],
            persona_address=persona_address,
            persona_area_code=android_config.get("persona_area_code", ""),
            city_area_codes=android_config.get("city_area_codes", []),
        )

        profile["smartforge_config"] = android_config.get("smartforge_config", {})
        profile["browsing_sites"] = android_config.get("browsing_sites", [])
        profile["cookie_sites"] = android_config.get("cookie_sites", [])
        profile["purchase_categories"] = android_config.get("purchase_categories", [])
        profile["social_platforms"] = android_config.get("social_platforms", [])
        if osint_data:
            profile["osint_data"] = osint_data

        # Save profile
        pf = _profiles_dir() / f"{profile['id']}.json"
        pf.write_text(json.dumps(profile))

        steps_log.append(
            f"Profile {profile['id']} created: "
            f"C:{profile['stats']['contacts']} "
            f"Calls:{profile['stats']['call_logs']} "
            f"SMS:{profile['stats']['sms']} "
            f"Cook:{profile['stats']['cookies']}"
        )

        # ── Step 4: Proxy test (if provided) ───────────────────────────
        proxy_status = None
        if body.proxy_url:
            steps_log.append("Testing proxy...")
            try:
                import httpx
                with httpx.Client(proxies=body.proxy_url, timeout=10) as client:
                    r = client.get("https://httpbin.org/ip")
                    proxy_status = {
                        "reachable": True,
                        "ip": r.json().get("origin", ""),
                        "proxy_url": body.proxy_url,
                    }
                steps_log.append(f"Proxy OK: {proxy_status['ip']}")
            except Exception as e:
                proxy_status = {"reachable": False, "error": str(e)}
                steps_log.append(f"Proxy test failed: {e}")

        # Build response
        response = {
            "profile": {
                "profile_id": profile["id"],
                "stats": profile["stats"],
                "persona": {
                    "name": android_config["persona_name"],
                    "email": android_config["persona_email"],
                    "phone": android_config["persona_phone"],
                    "occupation": android_config["occupation"],
                    "age": android_config["age"],
                    "dob": android_config.get("dob", ""),
                    "country": android_config["country"],
                    "device_model": android_config["device_model"],
                    "carrier": android_config["carrier"],
                    "location": android_config["location"],
                },
                "trust_score": None,
            },
            "smartforge": {
                "ai_enriched": android_config.get("ai_enriched", False),
                "osint_enriched": android_config.get("osint_enriched", False),
                "age_days": android_config["age_days"],
                "has_card": android_config.get("card_data") is not None,
                "locale": android_config.get("locale", ""),
                "timezone": android_config.get("timezone", ""),
            },
            "osint": osint_data,
            "proxy": proxy_status,
            "steps_log": steps_log,
        }

        return response

    except Exception as e:
        logger.exception("Unified forge failed")
        steps_log.append(f"FATAL: {e}")
        raise HTTPException(500, {"error": str(e), "steps_log": steps_log})




