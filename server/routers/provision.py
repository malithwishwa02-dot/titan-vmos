"""
Titan V12.0 — Full Provisioning Router
/api/genesis/* — Inject, full-provision, age-device, job status
Split from genesis.py to reduce file size and separate concerns.
"""

import asyncio
import functools
import json
import logging
import os
import threading
import time as _time_mod
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from device_manager import DeviceManager, PERMANENT_DEVICE_ID
from job_manager import inject_jobs as _inject_mgr, provision_jobs as _provision_mgr
from profile_injector import ProfileInjector

router = APIRouter(prefix="/api/genesis", tags=["genesis"])
logger = logging.getLogger("titan.provision")

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


def _profiles_dir() -> Path:
    d = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _attach_gallery(profile_data: dict):
    # Attach gallery paths to profile data if available.
    gallery_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "forge_gallery"
    if gallery_dir.exists():
        profile_data["gallery_paths"] = [str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]]


def _build_card_data(body, persona_name: str = "") -> Optional[dict]:
    """Build card_data dict from request body if cc_number is provided."""
    if not body.cc_number:
        return None
    return {
        "number": body.cc_number,
        "exp_month": body.cc_exp_month,
        "exp_year": body.cc_exp_year,
        "cvv": body.cc_cvv,
        "cardholder": body.cc_cardholder or persona_name,
    }


# ═══════════════════════════════════════════════════════════════════════
# INJECT
# ═══════════════════════════════════════════════════════════════════════

class GenesisInjectBody(BaseModel):
    profile_id: str = ""
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""


def _run_inject_job(job_id: str, adb_target: str, profile_data: dict,
                    card_data: dict, device_id: str, profile_id: str):
    """Background worker for profile injection (ADB path)."""
    try:
        injector = ProfileInjector(adb_target=adb_target)
        result = injector.inject_full_profile(profile_data, card_data=card_data)

        update = {
            "status": "completed", "trust_score": result.trust_score,
            "result": result.to_dict(), "completed_at": _time_mod.time(),
        }

        # Run wallet verification if card was injected (GAP-M1)
        if card_data and result.wallet_ok:
            try:
                from wallet_verifier import WalletVerifier
                wv = WalletVerifier(adb_target=adb_target)
                wallet_report = wv.verify()
                update["wallet_verification"] = wallet_report.to_dict()
                logger.info(f"Inject job {job_id} wallet verify: "
                            f"{wallet_report.passed}/{wallet_report.total} ({wallet_report.grade})")
            except Exception as we:
                logger.warning(f"Inject job {job_id} wallet verify failed: {we}")

        _inject_mgr.update(job_id, update)
        logger.info(f"Inject job {job_id} completed: trust={result.trust_score}")
    except Exception as e:
        _inject_mgr.update(job_id, {"status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Inject job {job_id} failed")


@router.post("/inject/{device_id}")
async def genesis_inject(device_id: str, body: GenesisInjectBody):
    """Inject forged profile into Android device via ADB (runs in background)."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())
    _attach_gallery(profile_data)
    card_data = _build_card_data(body, profile_data.get("persona_name", ""))

    job_id = str(_uuid.uuid4())[:8]
    _inject_mgr.create(job_id, {
        "status": "running", "device_id": device_id,
        "profile_id": body.profile_id, "started_at": _time_mod.time(),
    })

    t = threading.Thread(
        target=_run_inject_job,
        args=(job_id, dev.adb_target, profile_data, card_data, device_id, body.profile_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "inject_started", "job_id": job_id,
        "device_id": device_id, "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/inject-status/{job_id}",
    }


@router.get("/inject-status/{job_id}")
async def genesis_inject_status(job_id: str):
    """Poll injection job status."""
    job = _inject_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ═══════════════════════════════════════════════════════════════════════
# FULL PROVISION
# ═══════════════════════════════════════════════════════════════════════

class FullProvisionBody(BaseModel):
    profile_id: str
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    preset: str = ""       # optional override; defaults to profile's device_model
    lockdown: bool = False
    proxy_url: str = ""    # SOCKS5 proxy URL (e.g. socks5h://user:pass@host:port)
    google_email: str = ""     # Google account email for pre-injection sign-in
    google_password: str = ""  # Google account password
    real_phone: str = ""       # Real phone number for OTP verification (e.g. +14304314828)
    otp_code: str = ""         # Pre-supplied OTP code (if manually entered)


def _run_provision_job(job_id: str, adb_target: str, profile_data: dict,
                       card_data: Optional[dict], preset: str, lockdown: bool,
                       proxy_url: str = "", google_email: str = "",
                       google_password: str = "", real_phone: str = "",
                       otp_code: str = ""):
    """Background worker: inject -> proxy -> google sign-in -> patch -> GSM verify -> trust score."""
    from adb_utils import adb_shell

    try:
        # -- Step 1: Profile injection
        _provision_mgr.update(job_id, {"step": "inject", "step_n": 1})
        injector = ProfileInjector(adb_target=adb_target)
        inj_result = injector.inject_full_profile(profile_data, card_data=card_data)
        _provision_mgr.update(job_id, {"inject_trust": inj_result.trust_score})

        # -- Step 2: Proxy configuration (optional)
        _provision_mgr.update(job_id, {"step": "proxy", "step_n": 2})
        if proxy_url:
            try:
                from proxy_router import ProxyRouter
                router_inst = ProxyRouter(adb_target=adb_target)
                proxy_result = router_inst.configure_socks5(proxy_url)
                _provision_mgr.update(job_id, {"proxy": proxy_result.to_dict()})
                logger.info(f"Provision job {job_id}: proxy configured via {proxy_result.method or '?'}")
            except Exception as pe:
                logger.warning(f"Provision job {job_id}: proxy config failed: {pe}")
                _provision_mgr.update(job_id, {"proxy": {"error": str(pe)}})
        else:
            _provision_mgr.update(job_id, {"proxy": {"skipped": True}})

        # -- Step 3: Full patch (26 phases, 103+ vectors) — includes GApps bootstrap
        _provision_mgr.update(job_id, {"step": "patch", "step_n": 3})
        from anomaly_patcher import AnomalyPatcher
        carrier  = profile_data.get("carrier",      "tmobile_us")
        location = profile_data.get("location",     "nyc")
        model    = preset or profile_data.get("device_model", "samsung_s25_ultra")
        patcher  = AnomalyPatcher(adb_target=adb_target)
        # Use quick_repatch if config exists (skips Phase 9 media which inject already did)
        if patcher.get_saved_patch_config():
            logger.info(f"Provision job {job_id}: using quick_repatch (skipping Phase 9 media)")
            report = patcher.quick_repatch()
        else:
            logger.info(f"Provision job {job_id}: running full_patch with minimal age_days=1")
            report = patcher.full_patch(model, carrier, location, lockdown=lockdown, age_days=1)
        _provision_mgr.update(job_id, {
            "patch_score": report.score, "phases_passed": report.passed,
            "phases_total": report.total, "patch_results": report.results[:40],
        })

        # -- Step 4: Google Account Sign-In (optional, post-patch so GMS/GSF available)
        _provision_mgr.update(job_id, {"step": "google_signin", "step_n": 4})
        if google_email and google_password:
            try:
                from google_account_creator import GoogleAccountCreator
                gac = GoogleAccountCreator(adb_target=adb_target)
                signin_result = gac.sign_in_existing(
                    email=google_email,
                    password=google_password,
                    phone_number=real_phone,
                    otp_code=otp_code,
                )
                _provision_mgr.update(job_id, {"google_signin": signin_result.to_dict()})
                logger.info(f"Provision job {job_id}: Google sign-in {'OK' if signin_result.success else 'FAILED'}")
            except Exception as ge:
                logger.warning(f"Provision job {job_id}: Google sign-in failed: {ge}")
                _provision_mgr.update(job_id, {"google_signin": {"error": str(ge), "success": False}})
        else:
            _provision_mgr.update(job_id, {"google_signin": {"skipped": True}})

        # -- Step 5: GSM verify
        _provision_mgr.update(job_id, {"step": "gsm_verify", "step_n": 5})
        gsm_state    = adb_shell(adb_target, "getprop gsm.sim.state")
        gsm_operator = adb_shell(adb_target, "getprop gsm.sim.operator.alpha")
        gsm_mcc_mnc  = adb_shell(adb_target, "getprop gsm.sim.operator.numeric")
        gsm_ok = (
            gsm_state.strip() == "READY" and
            len(gsm_operator.strip()) > 0 and
            len(gsm_mcc_mnc.strip()) >= 5
        )
        _provision_mgr.update(job_id, {"gsm": {
            "ok": gsm_ok,
            "state": gsm_state.strip(),
            "operator": gsm_operator.strip(),
            "mcc_mnc": gsm_mcc_mnc.strip(),
            "expected_carrier": carrier,
        }})

        # -- Step 6: Trust score (canonical 14-check scorer)
        _provision_mgr.update(job_id, {"step": "trust_score", "step_n": 6})
        from trust_scorer import compute_trust_score
        trust_result = compute_trust_score(adb_target, profile_data=profile_data)
        trust_score = trust_result["trust_score"]

        _provision_mgr.update(job_id, {
            "status": "completed",
            "step": "done",
            "step_n": 6,
            "trust_score": trust_score,
            "trust_checks": trust_result["checks"],
            "completed_at": _time_mod.time(),
        })
        logger.info(f"Provision job {job_id} done: patch={report.score} trust={trust_score} gsm={'OK' if gsm_ok else 'FAIL'}")

    except Exception as e:
        _provision_mgr.update(job_id, {"status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Provision job {job_id} failed")


@router.post("/full-provision/{device_id}")
async def genesis_full_provision(device_id: str, body: FullProvisionBody):
    """One-shot endpoint: inject genesis profile + full_patch (26 phases) + GSM verify.
    Returns a job_id; poll /provision-status/{job_id} for progress."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())
    _attach_gallery(profile_data)
    card_data = _build_card_data(body, profile_data.get("persona_name", ""))

    job_id = str(_uuid.uuid4())[:8]
    _provision_mgr.create(job_id, {
        "status": "running",
        "device_id": device_id,
        "profile_id": body.profile_id,
        "step": "inject",
        "step_n": 1,
        "started_at": _time_mod.time(),
        "patch_score": None,
        "trust_score": None,
        "gsm": None,
    })

    t = threading.Thread(
        target=_run_provision_job,
        args=(job_id, dev.adb_target, profile_data, card_data,
              body.preset, body.lockdown, body.proxy_url,
              body.google_email, body.google_password,
              body.real_phone, body.otp_code),
        daemon=True,
    )
    t.start()

    return {
        "status": "started",
        "job_id": job_id,
        "device_id": device_id,
        "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/provision-status/{job_id}",
    }


@router.get("/provision-status/{job_id}")
async def genesis_provision_status(job_id: str):
    """Poll full-provision job status."""
    job = _provision_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Provision job not found")
    return job


# ═══════════════════════════════════════════════════════════════════════
# AGE DEVICE
# ═══════════════════════════════════════════════════════════════════════

class AgeDeviceBody(BaseModel):
    device_id: str
    preset: str = "pixel_9_pro"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    age_days: int = 90
    persona: str = ""


def _run_age_job(job_id: str, adb_target: str, preset: str, carrier: str,
                 location: str, device_id: str):
    """Background worker for age-device (200-365s typical)."""
    try:
        from anomaly_patcher import AnomalyPatcher
        patcher = AnomalyPatcher(adb_target=adb_target)
        # Use quick_repatch if device was rebooted
        if patcher.needs_repatch():
            _provision_mgr.update(job_id, {"step": "quick_repatch"})
            report = patcher.quick_repatch()
        else:
            _provision_mgr.update(job_id, {"step": "full_patch"})
            report = patcher.full_patch(preset, carrier, location)
        _provision_mgr.update(job_id, {
            "status": "completed", "step": "done",
            "score": report.score, "passed": report.passed, "total": report.total,
            "elapsed_sec": report.elapsed_sec,
            "phases": len(report.results),
            "completed_at": _time_mod.time(),
        })
        logger.info(f"Age job {job_id} done: {report.passed}/{report.total} score={report.score}")
    except Exception as e:
        _provision_mgr.update(job_id, {
            "status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Age job {job_id} failed")


@router.post("/age-device/{device_id}")
async def genesis_age_device(device_id: str, body: AgeDeviceBody):
    """Run anomaly-patching phases on the device (background job).

    Returns a job_id; poll /provision-status/{job_id} for progress.
    Full patch takes 200-365s; quick repatch after reboot takes ~30s.
    """
    dev = dm.get_device(device_id) if dm else None
    adb_target = dev.adb_target if dev else "127.0.0.1:6520"

    job_id = str(_uuid.uuid4())[:8]
    _provision_mgr.create(job_id, {
        "status": "running", "type": "age_device",
        "device_id": device_id, "step": "starting",
        "started_at": _time_mod.time(),
    })

    t = threading.Thread(
        target=_run_age_job,
        args=(job_id, adb_target, body.preset, body.carrier, body.location, device_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "started", "job_id": job_id,
        "device_id": device_id,
        "poll_url": f"/api/genesis/provision-status/{job_id}",
    }


# ═══════════════════════════════════════════════════════════════════════
# FORGE PIPELINE  (phase-ordered, generic reusable)
# ═══════════════════════════════════════════════════════════════════════

class PipelineBody(BaseModel):
    # Identity
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    ssn: str = ""
    # Address
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    gender: str = "M"
    occupation: str = "auto"
    # Card
    cc_number: str = ""
    cc_exp: str = ""          # MM/YYYY
    cc_cvv: str = ""
    cc_holder: str = ""
    # Google
    google_email: str = ""
    google_password: str = ""
    real_phone: str = ""
    otp_code: str = ""
    # Network
    proxy_url: str = ""
    # Device overrides
    device_model: str = "samsung_s24"
    carrier: str = "tmobile_us"
    location: str = "la"
    age_days: int = 120
    # Options
    skip_wipe: bool = False
    skip_patch: bool = False
    use_ai: bool = True


def _pl_log(job_id: str, msg: str):
    """Append a line to the pipeline job log."""
    job = _provision_mgr.get(job_id) or {}
    log = job.get("log", [])
    log.append(msg)
    _provision_mgr.update(job_id, {"log": log[-120:]})


def _pl_phase(job_id: str, phase_n: int, status: str, notes: str = ""):
    """Update one phase row in the pipeline job."""
    job = _provision_mgr.get(job_id) or {}
    phases = job.get("phases", [])
    for ph in phases:
        if ph["n"] == phase_n:
            ph["status"] = status
            if notes:
                ph["notes"] = notes
    _provision_mgr.update(job_id, {"phases": phases, "current_phase": phase_n})


def _adb_sh(adb_target: str, cmd: str, timeout: int = 20) -> str:
    import subprocess as _sp
    try:
        r = _sp.run(f'adb -s {adb_target} shell "{cmd}"',
                    shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _run_pipeline_job(job_id: str, adb_target: str, body: PipelineBody, device_id: str):
    """Phase-ordered forge pipeline background worker.

    Order: wipe → patch → proxy → forge → inject → google → post-harden → trust audit
    """
    import re as _re
    import subprocess as _sp
    from adb_utils import adb_shell

    def log(msg):
        logger.info(f"[pipeline:{job_id}] {msg}")
        _pl_log(job_id, msg)

    # ── Pre-flight: Ensure screen is awake (prevents black display) ─────
    _adb_sh(adb_target, "settings put system screen_off_timeout 2147483647")
    _adb_sh(adb_target, "svc power stayon true")
    _adb_sh(adb_target, "input keyevent KEYCODE_WAKEUP")

    # ── Phase 0: Wipe ──────────────────────────────────────────────────
    if not body.skip_wipe:
        _pl_phase(job_id, 0, "running")
        log("Phase 0 — Wipe: clearing all previous persona artefacts...")
        wipe_cmds = [
            "am broadcast -a com.google.android.gms.CLEAR_ACCOUNT 2>/dev/null; "
            "rm -f /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db*",

            "content delete --uri content://com.android.contacts/raw_contacts 2>/dev/null; "
            "rm -f /data/data/com.android.providers.contacts/databases/contacts2.db* "
            "/data/data/com.android.providers.contacts/databases/calllog.db*",

            "content delete --uri content://sms 2>/dev/null; "
            "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "
            "'DELETE FROM sms; DELETE FROM threads;' 2>/dev/null",

            "rm -rf /data/data/com.kiwibrowser.browser/app_chrome/Default/* "
            "/data/data/com.android.chrome/app_chrome/Default/Cookies "
            "/data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null",

            "rm -rf /sdcard/DCIM/* /sdcard/Pictures/* /data/media/0/DCIM/* 2>/dev/null",

            "rm -f /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db* "
            "/data/data/com.google.android.apps.walletnfcrel/shared_prefs/*.xml 2>/dev/null",

            "rm -rf /data/system/usagestats/0/* /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null",
        ]
        for cmd in wipe_cmds:
            _adb_sh(adb_target, cmd, timeout=30)
        log("Phase 0 — Wipe complete: all persona data cleared")
        _pl_phase(job_id, 0, "done", "cleared")
    else:
        _pl_phase(job_id, 0, "skipped", "skip_wipe=true")

    # ── Phase 1: Stealth Patch ──────────────────────────────────────────
    if not body.skip_patch:
        _pl_phase(job_id, 1, "running")
        log("Phase 1 — Stealth Patch: running 26 phases (3-6 min)...")
        try:
            from anomaly_patcher import AnomalyPatcher
            patcher = AnomalyPatcher(adb_target=adb_target)
            model    = body.device_model or "samsung_s24"
            carrier  = body.carrier or "tmobile_us"
            location = body.location or "la"
            if patcher.get_saved_patch_config():
                report = patcher.quick_repatch()
            else:
                report = patcher.full_patch(model, carrier, location, lockdown=False,
                                            age_days=1)
            _provision_mgr.update(job_id, {
                "patch_score": report.score, "phases_passed": report.passed,
                "phases_total": report.total,
            })
            log(f"Phase 1 — Stealth Patch done: {report.score}% ({report.passed}/{report.total})")
            _pl_phase(job_id, 1, "done", f"{report.score}% {report.passed}/{report.total}")
        except Exception as e:
            log(f"Phase 1 — Stealth Patch FAILED: {e}")
            _pl_phase(job_id, 1, "failed", str(e)[:60])
    else:
        _pl_phase(job_id, 1, "skipped", "skip_patch=true")

    # ── Phase 2: Network / Proxy ────────────────────────────────────────
    _pl_phase(job_id, 2, "running")
    log("Phase 2 — Network: IPv6 kill + tun2socks proxy...")
    _adb_sh(adb_target, "sysctl -w net.ipv6.conf.all.disable_ipv6=1 2>/dev/null")
    _adb_sh(adb_target, "ip6tables -P INPUT DROP 2>/dev/null")
    _adb_sh(adb_target, "ip6tables -P OUTPUT DROP 2>/dev/null")
    proxy_method = "none"
    if body.proxy_url:
        try:
            from proxy_router import ProxyRouter
            pr = ProxyRouter(adb_target=adb_target)
            result = pr.configure_socks5(body.proxy_url)
            proxy_method = result.method or "configured"
            _provision_mgr.update(job_id, {"proxy": result.to_dict()})
            log(f"Phase 2 — Proxy configured via {proxy_method}: {result.external_ip or '?'}")
            _pl_phase(job_id, 2, "done", f"{proxy_method} {result.external_ip or ''}")
        except Exception as e:
            log(f"Phase 2 — Proxy FAILED: {e}")
            _pl_phase(job_id, 2, "failed", str(e)[:60])
    else:
        log("Phase 2 — No proxy configured")
        _pl_phase(job_id, 2, "done", "no proxy")

    # ── Phase 3: Forge persona profile ─────────────────────────────────
    _pl_phase(job_id, 3, "running")
    log(f"Phase 3 — Forge: generating persona profile for {body.name or 'auto'}...")
    profile_id = ""
    profile_data = {}
    try:
        from android_profile_forge import AndroidProfileForge
        _forge_inst = AndroidProfileForge()

        # Determine age from DOB
        age = 40
        if body.dob:
            try:
                from datetime import date as _date
                parts = body.dob.replace("-", "/").split("/")
                if len(parts) == 3:
                    m, d, y = (int(p) for p in parts)
                    born = _date(y, m, d)
                    age = (_date.today() - born).days // 365
            except Exception:
                pass

        persona_address = None
        if body.street:
            persona_address = {
                "address": body.street, "city": body.city,
                "state": body.state, "zip": body.zip, "country": body.country,
            }

        profile_data = _forge_inst.forge(
            persona_name=body.name or "Auto User",
            persona_email=body.email or "",
            persona_phone=body.phone or "",
            country=body.country or "US",
            archetype=body.occupation if body.occupation != "auto" else "professional",
            age_days=body.age_days,
            carrier=body.carrier or "tmobile_us",
            location=body.location or "la",
            device_model=body.device_model or "samsung_s24",
            persona_address=persona_address,
        )
        profile_id = profile_data.get("id", "")
        # Persist profile
        pf = _profiles_dir() / f"{profile_id}.json"
        import json as _json
        pf.write_text(_json.dumps(profile_data))
        stats = profile_data.get("stats", {})
        log(f"Phase 3 — Forge done: {profile_id}  C:{stats.get('contacts',0)} "
            f"SMS:{stats.get('sms',0)} Calls:{stats.get('call_logs',0)} Cook:{stats.get('cookies',0)}")
        _provision_mgr.update(job_id, {"profile_id": profile_id})
        _pl_phase(job_id, 3, "done", profile_id)
    except Exception as e:
        log(f"Phase 3 — Forge FAILED: {e}")
        _pl_phase(job_id, 3, "failed", str(e)[:80])
        _provision_mgr.update(job_id, {
            "status": "failed", "error": f"Forge failed: {e}",
            "completed_at": _time_mod.time()
        })
        return

    # ── Phase 4: Google Account (BEFORE Inject — wallet needs Google signed in) ──
    _pl_phase(job_id, 4, "running")
    if body.google_email:
        log(f"Phase 4 — Google Account: injecting {body.google_email}...")
        try:
            from google_account_injector import GoogleAccountInjector
            gi = GoogleAccountInjector(adb_target=adb_target)
            gr = gi.inject_account(
                email=body.google_email,
                display_name=body.name or body.google_email.split("@")[0],
            )
            ok_str = f"inject={gr.success_count}/8"
            log(f"Phase 4 — Google inject: {ok_str}")

            # Attempt UI sign-in
            if body.google_password:
                try:
                    from google_account_creator import GoogleAccountCreator
                    gac = GoogleAccountCreator(adb_target=adb_target)
                    sr = gac.sign_in_existing(
                        email=body.google_email,
                        password=body.google_password,
                        phone_number=body.real_phone,
                        otp_code=body.otp_code,
                    )
                    ok_str += f" ui={'ok' if sr.success else 'fail'}"
                    log(f"Phase 4 — Google UI sign-in: {'success' if sr.success else 'failed'}")
                except Exception as ue:
                    log(f"Phase 4 — UI sign-in skipped: {ue}")

            _provision_mgr.update(job_id, {"google_inject": gr.success_count})
            _pl_phase(job_id, 4, "done", ok_str)
        except Exception as e:
            log(f"Phase 4 — Google Account FAILED: {e}")
            _pl_phase(job_id, 4, "failed", str(e)[:60])
    else:
        log("Phase 4 — Google Account: skipped (no gmail)")
        _pl_phase(job_id, 4, "skipped", "no google_email")

    # ── Phase 5: Inject (profile data + card) ───────────────────────────
    _pl_phase(job_id, 5, "running")
    log("Phase 5 — Inject: pushing profile data to device...")
    exp_m = exp_y = 0
    if body.cc_exp:
        try:
            parts = body.cc_exp.split("/")
            exp_m = int(parts[0])
            exp_y = int(parts[1])
        except Exception:
            pass

    card_data = None
    if body.cc_number:
        card_data = {
            "number": body.cc_number,
            "exp_month": exp_m, "exp_year": exp_y,
            "cvv": body.cc_cvv,
            "cardholder": body.cc_holder or body.name,
        }
    try:
        _attach_gallery(profile_data)
        injector = ProfileInjector(adb_target=adb_target)
        inj_result = injector.inject_full_profile(profile_data, card_data=card_data)
        _provision_mgr.update(job_id, {"inject_trust": inj_result.trust_score})
        log(f"Phase 5 — Inject done: inject_trust={inj_result.trust_score}")
        _pl_phase(job_id, 5, "done", f"inject_trust={inj_result.trust_score}")
    except Exception as e:
        log(f"Phase 5 — Inject FAILED: {e}")
        _pl_phase(job_id, 5, "failed", str(e)[:80])

    # ── Phase 6: Wallet Provision (Google Pay + Chrome Autofill) ────────
    _pl_phase(job_id, 6, "running")
    if card_data:
        log(f"Phase 6 — Wallet: provisioning Google Pay with card ...{body.cc_number[-4:]}")
        try:
            from wallet_provisioner import WalletProvisioner
            wp = WalletProvisioner(adb_target=adb_target)
            wp_result = wp.provision_card(
                card_number=body.cc_number,
                exp_month=exp_m,
                exp_year=exp_y,
                cardholder=body.cc_holder or body.name,
                cvv=body.cc_cvv or "",
                persona_email=body.google_email or body.email,
                persona_name=body.name or "",
                country=getattr(body, 'country', 'US') or 'US',
                zero_auth=True,
            )
            wp_ok = sum([
                getattr(wp_result, 'google_pay_ok', False),
                getattr(wp_result, 'play_store_ok', False),
                getattr(wp_result, 'chrome_autofill_ok', False),
                getattr(wp_result, 'gms_billing_ok', False),
            ])
            # Fix tapandpay.db ownership (GAP: wallet DB created as root, must be owned by wallet app UID)
            _wallet_uid = _adb_sh(adb_target, "stat -c '%U' /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
            if _wallet_uid and _wallet_uid != "root":
                _adb_sh(adb_target, f"chown -R {_wallet_uid}:{_wallet_uid} /data/data/com.google.android.apps.walletnfcrel/databases/")
                _adb_sh(adb_target, "restorecon -R /data/data/com.google.android.apps.walletnfcrel/databases/ 2>/dev/null")
            log(f"Phase 6 — Wallet done: {wp_ok}/4 subsystems OK (gpay={getattr(wp_result, 'google_pay_ok', '?')}, play={getattr(wp_result, 'play_store_ok', '?')}, chrome={getattr(wp_result, 'chrome_autofill_ok', '?')}, gms={getattr(wp_result, 'gms_billing_ok', '?')})")
            
            # Inject purchase history bridge (Chrome history + cookies + notifications + receipts)
            try:
                from purchase_history_bridge import generate_android_purchase_history
                from profile_injector import ProfileInjector
                phb_data = generate_android_purchase_history(
                    persona_name=body.name or profile_data.get("persona", {}).get("name", ""),
                    persona_email=body.email or profile_data.get("persona", {}).get("email", ""),
                    country=body.country or "US",
                    age_days=body.age_days or 120,
                    card_last4=body.cc_number[-4:] if body.cc_number else "0000",
                    card_network="visa" if body.cc_number and body.cc_number[0] == "4" else "mastercard",
                )
                pi = ProfileInjector(adb_target=adb_target)
                if phb_data.get("chrome_history"):
                    pi._inject_history(phb_data["chrome_history"])
                if phb_data.get("chrome_cookies"):
                    pi._inject_cookies(phb_data["chrome_cookies"])
                phb_summary = phb_data.get("purchase_summary", {})
                log(f"Phase 6 — Purchase history bridge: {phb_summary.get('total_purchases', 0)} purchases, "
                    f"{phb_summary.get('chrome_history_entries', 0)} history, "
                    f"{phb_summary.get('chrome_cookies', 0)} cookies")
            except Exception as phbe:
                log(f"Phase 6 — Purchase history bridge skipped: {phbe}")
            
            _pl_phase(job_id, 6, "done", f"wallet={wp_ok}/4")
        except Exception as e:
            log(f"Phase 6 — Wallet FAILED: {e}")
            _pl_phase(job_id, 6, "failed", str(e)[:80])
    else:
        log("Phase 6 — Wallet: skipped (no card data)")
        _pl_phase(job_id, 6, "skipped", "no card")

    # ── Phase 7: Provincial Layering (V3 App Bypass) ───────────────────
    _pl_phase(job_id, 7, "running")
    log("Phase 7 — Provincial Layering: injecting V3 app bypass configs...")
    try:
        from app_data_forger import AppDataForger
        app_forger = AppDataForger(adb_target=adb_target)
        province_country = (body.country or 'US').upper()
        prov_targets = {
            'US': ['com.coinbase.android', 'com.amazon.mShop.android.shopping',
                   'com.chase.sig.android', 'com.venmo', 'com.paypal.android.p2pmobile'],
            'GB': ['com.binance.dev', 'com.amazon.mShop.android.shopping',
                   'com.ebay.mobile', 'com.monzo.android', 'com.revolut.revolut'],
        }
        targets = prov_targets.get(province_country, prov_targets['US'])
        persona_dict = {
            'email': body.google_email or body.email or '',
            'name': body.name or '',
            'phone': body.phone or '',
            'country': province_country,
        }
        app_result = app_forger.forge_and_inject(
            installed_packages=targets,
            persona=persona_dict,
            play_purchases=profile_data.get('play_purchases'),
            app_installs=profile_data.get('app_installs'),
        )
        log(f"Phase 7 — Provincial Layering done: {app_result.apps_processed} apps, {app_result.shared_prefs_written} prefs, {app_result.databases_written} dbs")
        _pl_phase(job_id, 7, "done", f"{app_result.apps_processed} apps")
    except Exception as e:
        log(f"Phase 7 — Provincial Layering FAILED: {e}")
        _pl_phase(job_id, 7, "failed", str(e)[:80])

    # ── Phase 8: Post-Harden ────────────────────────────────────────────
    _pl_phase(job_id, 8, "running")
    log("Phase 7 — Post-Harden: Kiwi prefs, contacts data table, media scan...")
    try:
        # Kiwi Preferences (enables chrome_signin trust check)
        kiwi_path = "/data/data/com.kiwibrowser.browser/app_chrome/Default"
        _adb_sh(adb_target, f"mkdir -p {kiwi_path}")
        import json as _json
        prefs = _json.dumps({
            "account_info": [{
                "email": body.google_email or body.email,
                "full_name": body.name or "User",
                "gaia": "117234567890",
                "given_name": (body.name or "User").split()[0],
                "locale": "en-US",
            }],
            "signin": {"allowed": True, "allowed_on_next_startup": True},
            "sync": {"has_setup_completed": True},
            "browser": {"has_seen_welcome_page": True},
        })
        # Safe write via temp file
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            tf.write(prefs)
            tf_path = tf.name
        import subprocess as _sp
        _sp.run(f"adb -s {adb_target} push {tf_path} {kiwi_path}/Preferences",
                shell=True, capture_output=True, timeout=10)
        os.unlink(tf_path)
        _adb_sh(adb_target, f"restorecon {kiwi_path}/Preferences 2>/dev/null")

        # Media scanner
        _adb_sh(adb_target,
                "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                "-d file:///sdcard/DCIM/Camera/ 2>/dev/null")
        _adb_sh(adb_target,
                "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                "-d file:///data/media/0/DCIM/Camera/ 2>/dev/null")

        log("Phase 8 — Post-Harden done: Kiwi prefs written, media scan triggered")
        _pl_phase(job_id, 8, "done", "kiwi+scan")
    except Exception as e:
        log(f"Phase 8 — Post-Harden FAILED: {e}")
        _pl_phase(job_id, 8, "failed", str(e)[:60])

    # ── Phase 9: Attestation ────────────────────────────────────────────
    _pl_phase(job_id, 9, "running")
    log("Phase 9 — Attestation: checking keybox, verified boot, GSF...")
    issues = []
    kb  = _adb_sh(adb_target, "getprop persist.titan.keybox.loaded")
    vbs = _adb_sh(adb_target, "getprop ro.boot.verifiedbootstate")
    bt  = _adb_sh(adb_target, "getprop ro.build.type")
    qemu= _adb_sh(adb_target, "getprop ro.kernel.qemu")
    if kb.strip() != "1":    issues.append("keybox")
    if vbs.strip() != "green": issues.append(f"vbs={vbs.strip()}")
    if bt.strip() != "user":   issues.append(f"build={bt.strip()}")
    if qemu.strip() not in ("0", ""): issues.append("qemu_exposed")
    notes = "ok" if not issues else ", ".join(issues)
    log(f"Phase 9 — Attestation: {notes}")
    _pl_phase(job_id, 9, "done" if not issues else "warn", notes)

    # ── Phase 10: Trust Audit ───────────────────────────────────────────
    _pl_phase(job_id, 10, "running")
    log("Phase 10 — Trust Audit: running 14-check trust scorer...")
    trust_score = 0
    trust_checks = {}
    try:
        from trust_scorer import compute_trust_score
        result = compute_trust_score(adb_target, profile_data=profile_data)
        trust_score  = result.get("trust_score", 0)
        trust_checks = result.get("checks", {})
        grade = result.get("grade", "?")
        log(f"Phase 10 — Trust Audit: {trust_score}/100 ({grade})")
        _provision_mgr.update(job_id, {"trust_score": trust_score, "trust_checks": trust_checks, "grade": grade})
        _pl_phase(job_id, 10, "done", f"{trust_score}/100 {grade}")
    except Exception as e:
        log(f"Phase 10 — Trust Audit FAILED: {e}")
        _pl_phase(job_id, 10, "failed", str(e)[:60])

    # ── Final ────────────────────────────────────────────────────────────
    _provision_mgr.update(job_id, {
        "status": "completed",
        "completed_at": _time_mod.time(),
    })
    log(f"Pipeline complete. Trust: {trust_score}/100  Profile: {profile_id}")


@router.post("/pipeline/{device_id}")
async def genesis_pipeline(device_id: str, body: PipelineBody):
    """Run the full phase-ordered forge pipeline (wipe→patch→proxy→forge→inject→google→harden→trust).

    Returns a job_id for polling via /api/genesis/pipeline-status/{job_id}.
    """
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")

    job_id = str(_uuid.uuid4())[:8]

    phases = [
        {"n": 0, "name": "Wipe",              "status": "pending", "notes": ""},
        {"n": 1, "name": "Stealth Patch",     "status": "pending", "notes": ""},
        {"n": 2, "name": "Network/Proxy",     "status": "pending", "notes": ""},
        {"n": 3, "name": "Forge Profile",     "status": "pending", "notes": ""},
        {"n": 4, "name": "Google Account",    "status": "pending", "notes": ""},
        {"n": 5, "name": "Inject",            "status": "pending", "notes": ""},
        {"n": 6, "name": "Wallet/GPay",       "status": "pending", "notes": ""},
        {"n": 7, "name": "Provincial Layer",  "status": "pending", "notes": ""},
        {"n": 8, "name": "Post-Harden",       "status": "pending", "notes": ""},
        {"n": 9, "name": "Attestation",       "status": "pending", "notes": ""},
        {"n": 10, "name": "Trust Audit",      "status": "pending", "notes": ""},
    ]

    _provision_mgr.create(job_id, {
        "status": "running", "type": "pipeline",
        "device_id": device_id, "job_id": job_id,
        "current_phase": -1, "phases": phases,
        "log": [], "started_at": _time_mod.time(),
        "trust_score": 0, "profile_id": "",
    })

    t = threading.Thread(
        target=_run_pipeline_job,
        args=(job_id, dev.adb_target, body, device_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "started", "job_id": job_id, "device_id": device_id,
        "poll_url": f"/api/genesis/pipeline-status/{job_id}",
    }


@router.get("/pipeline-status/{job_id}")
async def genesis_pipeline_status(job_id: str):
    """Poll pipeline phase status."""
    job = _provision_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Pipeline job not found")
    return job


@router.post("/provincial-inject/{device_id}")
async def genesis_provincial_inject(device_id: str, request: Request):
    """Run the Provincial Injection Protocol (zero-auth wallet + app bypass) on a device.

    Bridges the standalone provincial_injection_protocol.py into the API.
    Body: {"region": "US"|"GB"}
    """
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    body = await request.json()
    region = body.get("region", "US").upper()
    if region not in ("US", "GB"):
        raise HTTPException(400, f"Unsupported region: {region}. Use US or GB.")
    try:
        from provincial_injection_protocol import forge_regional_profile
        result = forge_regional_profile(region, dev.adb_target)
        return {
            "device_id": device_id,
            "region": region,
            "zero_auth_ready": result.get("zero_auth_ready", False),
            "profile_name": result.get("profile", {}).get("persona_name", ""),
            "profile_email": result.get("profile", {}).get("persona_email", ""),
        }
    except ImportError:
        raise HTTPException(501, "provincial_injection_protocol module not found on PYTHONPATH")
    except Exception as e:
        logger.exception("Provincial injection failed")
        raise HTTPException(500, {"error": str(e)})


@router.get("/wallet-status/{device_id}")
async def genesis_wallet_status(device_id: str):
    """Check Google Pay / Wallet CC injection status for a device."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    adb_target = dev.adb_target

    # 1. Find latest profile for this device
    import json as _j
    profile_dir = _profiles_dir()
    latest_profile = None
    latest_time = ""
    for pf in profile_dir.glob("TITAN-*.json"):
        try:
            data = _j.loads(pf.read_text())
            ct = data.get("created_at", "")
            if ct > latest_time:
                latest_time = ct
                latest_profile = data
        except Exception:
            pass

    card_info = {}
    if latest_profile:
        # Extract card data from profile if stored
        card_info = {
            "profile_id": latest_profile.get("id", ""),
            "persona_name": latest_profile.get("persona_name", ""),
            "persona_email": latest_profile.get("persona_email", ""),
            "created_at": latest_profile.get("created_at", ""),
            "age_days": latest_profile.get("age_days", 0),
            "play_purchases": len(latest_profile.get("play_purchases", [])),
        }

    # 2. Check wallet verify (device-level checks)
    wallet_verify = {"score": 0, "grade": "F", "checks": [], "passed": 0, "total": 0}
    try:
        from wallet_verifier import WalletVerifier
        wv = WalletVerifier(adb_target=adb_target)
        report = wv.verify()
        wallet_verify = {
            "score": report.score,
            "grade": report.grade,
            "passed": report.passed,
            "total": report.total,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail,
                 "remediation": c.remediation}
                for c in report.checks
            ],
        }
    except Exception as e:
        wallet_verify["error"] = str(e)[:200]

    # 3. ADB reachability
    adb_ok = False
    try:
        out = _adb_sh(adb_target, "echo OK")
        adb_ok = "OK" in str(out)
    except Exception:
        pass

    return {
        "device_id": device_id,
        "adb_target": adb_target,
        "adb_reachable": adb_ok,
        "profile": card_info,
        "wallet_verify": wallet_verify,
        "note": "Wallet provisioning requires ADB + running VM. "
                "If adb_reachable=false, wallet files cannot be pushed to device.",
    }


# ═══════════════════════════════════════════════════════════════════════
# RE-FORGE — Factory reset + fresh pipeline on permanent device
# ═══════════════════════════════════════════════════════════════════════

class ReforgeBody(BaseModel):
    """Full re-forge request: factory reset then run pipeline with new identity."""
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    ssn: str = ""
    gender: str = "M"
    occupation: str = "auto"
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    cc_number: str = ""
    cc_exp: str = ""
    cc_cvv: str = ""
    cc_holder: str = ""
    google_email: str = ""
    google_password: str = ""
    real_phone: str = ""
    otp_code: str = ""
    proxy_url: str = ""
    device_model: str = "samsung_s25_ultra"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    age_days: int = 120
    skip_patch: bool = False
    use_ai: bool = True


def _run_reforge_job(job_id: str, body: ReforgeBody):
    """Background worker: factory reset → pipeline."""
    import asyncio as _aio

    def _log(msg):
        existing = _provision_mgr.get(job_id) or {}
        log_list = existing.get("log", [])
        log_list.append(f"[{_time_mod.strftime('%H:%M:%S')}] {msg}")
        _provision_mgr.update(job_id, {"log": log_list})

    try:
        _log("Phase 0: Factory resetting device...")
        _provision_mgr.update(job_id, {"step": "factory_reset", "step_n": 0})

        # Run factory reset in event loop
        loop = _aio.new_event_loop()
        try:
            loop.run_until_complete(dm.factory_reset_device(PERMANENT_DEVICE_ID))
        finally:
            loop.close()
        _log("Factory reset complete. Device clean.")

        # Now get fresh device reference
        dev = dm.get_permanent_device()
        if not dev:
            raise RuntimeError("Permanent device lost after reset")

        # Build a PipelineBody and delegate to pipeline runner
        _provision_mgr.update(job_id, {"step": "pipeline", "step_n": 1})
        _log("Phase 1: Starting forge pipeline...")

        pipeline_body = PipelineBody(
            name=body.name, email=body.email, phone=body.phone,
            dob=body.dob, ssn=body.ssn, gender=body.gender,
            occupation=body.occupation, street=body.street,
            city=body.city, state=body.state, zip=body.zip,
            country=body.country,
            cc_number=body.cc_number, cc_exp=body.cc_exp,
            cc_cvv=body.cc_cvv, cc_holder=body.cc_holder or body.name,
            google_email=body.google_email,
            google_password=body.google_password,
            real_phone=body.real_phone, otp_code=body.otp_code,
            proxy_url=body.proxy_url,
            device_model=body.device_model, carrier=body.carrier,
            location=body.location, age_days=body.age_days,
            skip_wipe=True,  # Already wiped by factory reset
            skip_patch=body.skip_patch, use_ai=body.use_ai,
        )

        _run_pipeline_job(job_id, dev.adb_target, pipeline_body, dev.id)

    except Exception as e:
        _provision_mgr.update(job_id, {
            "status": "failed", "error": str(e),
            "completed_at": _time_mod.time(),
        })
        logger.exception("Re-forge job %s failed", job_id)


@router.post("/reforge")
async def genesis_reforge(body: ReforgeBody):
    """Factory reset the permanent device and run a full forge pipeline.
    This is the primary workflow: reset → patch → forge → inject → verify.
    Returns job_id for polling via /api/genesis/pipeline-status/{job_id}."""
    dev = dm.get_permanent_device() if dm else None
    if not dev:
        raise HTTPException(404, "No permanent device registered. Is Cuttlefish running?")

    job_id = str(_uuid.uuid4())[:8]
    phases = [
        {"n": -1, "name": "Factory Reset",    "status": "pending", "notes": ""},
        {"n": 0, "name": "Wipe",              "status": "pending", "notes": "Skipped (reset)"},
        {"n": 1, "name": "Stealth Patch",     "status": "pending", "notes": ""},
        {"n": 2, "name": "Network/Proxy",     "status": "pending", "notes": ""},
        {"n": 3, "name": "Forge Profile",     "status": "pending", "notes": ""},
        {"n": 4, "name": "Google Account",    "status": "pending", "notes": ""},
        {"n": 5, "name": "Inject",            "status": "pending", "notes": ""},
        {"n": 6, "name": "Wallet/GPay",       "status": "pending", "notes": ""},
        {"n": 7, "name": "Provincial Layer",  "status": "pending", "notes": ""},
        {"n": 8, "name": "Post-Harden",       "status": "pending", "notes": ""},
        {"n": 9, "name": "Attestation",       "status": "pending", "notes": ""},
        {"n": 10, "name": "Trust Audit",      "status": "pending", "notes": ""},
    ]

    _provision_mgr.create(job_id, {
        "status": "running", "type": "reforge",
        "device_id": dev.id, "job_id": job_id,
        "current_phase": -1, "phases": phases,
        "log": [], "started_at": _time_mod.time(),
        "trust_score": 0, "profile_id": "",
    })

    t = threading.Thread(target=_run_reforge_job, args=(job_id, body), daemon=True)
    t.start()

    return {
        "status": "started", "job_id": job_id,
        "device_id": dev.id,
        "poll_url": f"/api/genesis/pipeline-status/{job_id}",
    }
