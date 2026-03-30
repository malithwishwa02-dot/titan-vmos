"""
Titan V12.0 — Stealth / Anomaly Patching Router
/api/stealth/* — Presets, carriers, locations, patch, audit, repatch
"""

import asyncio
import logging
import threading
import time as _time_mod
import uuid as _uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from response_models import JobStartResponse, PatchStatusResponse
from anomaly_patcher import AnomalyPatcher
from device_presets import CARRIERS, LOCATIONS, list_preset_names
from job_manager import JobManager
from wallet_verifier import WalletVerifier

router = APIRouter(prefix="/api/stealth", tags=["stealth"])
logger = logging.getLogger("titan.stealth")

dm: DeviceManager = None
_patch_jobs = JobManager("stealth_patch", ttl=7200)


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class PatchDeviceBody(BaseModel):
    preset: str = ""
    carrier: str = ""
    location: str = ""


@router.get("/presets")
async def list_presets():
    return {"presets": list_preset_names()}


@router.get("/carriers")
async def list_carriers():
    return {"carriers": {k: {"name": v.name, "mcc": v.mcc, "mnc": v.mnc, "country": v.country}
                         for k, v in CARRIERS.items()}}


@router.get("/locations")
async def list_locations():
    return {"locations": LOCATIONS}


def _run_patch_job(job_id: str, adb_target: str, preset: str, carrier: str,
                   location: str, device_id: str):
    """Background worker for stealth patching (200-365s typical)."""
    try:
        patcher = AnomalyPatcher(adb_target=adb_target)
        # Use quick_repatch if saved config exists (device already patched once)
        saved = patcher.get_saved_patch_config()
        if saved:
            logger.info(f"Patch job {job_id}: saved config found, using quick_repatch")
            _patch_jobs.update(job_id, {"step": "quick_repatch"})
            report = patcher.quick_repatch()
        else:
            _patch_jobs.update(job_id, {"step": "full_patch"})
            report = patcher.full_patch(preset, carrier, location, age_days=1)
        _patch_jobs.update(job_id, {
            "status": "completed",
            "score": report.score, "passed": report.passed, "total": report.total,
            "elapsed_sec": report.elapsed_sec,
            "results": report.results[:40],
            "completed_at": _time_mod.time(),
        })
        logger.info(f"Patch job {job_id} done: {report.passed}/{report.total} score={report.score}")
    except Exception as e:
        _patch_jobs.update(job_id, {
            "status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Patch job {job_id} failed")


@router.post("/{device_id}/patch", response_model=JobStartResponse)
async def patch_device(device_id: str, body: PatchDeviceBody):
    """Start stealth patching as a background job. Poll /patch-status/{job_id} for progress.
    Full patch takes 200-365s; quick repatch after reboot takes ~30s."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    preset = body.preset or dev.config.get("model", "samsung_s25_ultra")
    carrier = body.carrier or dev.config.get("carrier", "tmobile_us")
    location = body.location or "nyc"

    job_id = str(_uuid.uuid4())[:8]
    _patch_jobs.create(job_id, {
        "status": "running", "device_id": device_id,
        "preset": preset, "carrier": carrier, "location": location,
        "step": "starting", "started_at": _time_mod.time(),
    })

    t = threading.Thread(
        target=_run_patch_job,
        args=(job_id, dev.adb_target, preset, carrier, location, device_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "started", "job_id": job_id,
        "device_id": device_id,
        "poll_url": f"/api/stealth/{device_id}/patch-status/{job_id}",
    }


@router.get("/{device_id}/patch-status/{job_id}")
async def patch_status(device_id: str, job_id: str):
    """Poll stealth patch job status."""
    job = _patch_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Patch job not found")
    return job


@router.get("/{device_id}/needs-repatch")
async def needs_repatch(device_id: str):
    """Check if device needs re-patching after reboot."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    def _check(adb_target: str):
        patcher = AnomalyPatcher(adb_target=adb_target)
        return {
            "needs_repatch": patcher.needs_repatch(),
            "config": patcher.get_saved_patch_config(),
        }
    return await asyncio.to_thread(_check, dev.adb_target)


def _run_audit(adb_target: str):
    """Blocking helper — runs in thread to avoid blocking event loop."""
    patcher = AnomalyPatcher(adb_target=adb_target)
    return patcher.audit()


@router.get("/{device_id}/audit")
async def audit_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    return await asyncio.to_thread(_run_audit, dev.adb_target)


def _run_wallet_verify(adb_target: str):
    """Blocking helper — runs in thread to avoid blocking event loop."""
    verifier = WalletVerifier(adb_target=adb_target)
    return verifier.verify()


@router.get("/{device_id}/wallet-verify")
async def wallet_verify(device_id: str):
    """Deep wallet injection verification — 13 checks across Google Pay,
    Play Store, Chrome, GMS, keybox, GSF alignment, and file ownership."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    report = await asyncio.to_thread(_run_wallet_verify, dev.adb_target)
    return report.to_dict()


# ═══════════════════════════════════════════════════════════════════════
# GAPPS BOOTSTRAP
# ═══════════════════════════════════════════════════════════════════════

def _run_bootstrap(adb_target: str, skip_optional: bool):
    """Blocking helper — runs in thread."""
    from gapps_bootstrap import GAppsBootstrap
    bs = GAppsBootstrap(adb_target=adb_target)
    return bs.run(skip_optional=skip_optional)


def _check_gapps_status(adb_target: str):
    """Blocking helper — runs in thread."""
    from gapps_bootstrap import GAppsBootstrap
    bs = GAppsBootstrap(adb_target=adb_target)
    return bs.check_status()


class BootstrapBody(BaseModel):
    skip_optional: bool = False


@router.post("/{device_id}/bootstrap-gapps")
async def bootstrap_gapps(device_id: str, body: BootstrapBody = BootstrapBody()):
    """Install GMS, Play Store, Chrome, Google Pay on vanilla AOSP Cuttlefish.
    APKs must be in /opt/titan/data/gapps/. Must run BEFORE aging pipeline."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    result = await asyncio.to_thread(_run_bootstrap, dev.adb_target, body.skip_optional)
    return result.to_dict()


@router.get("/{device_id}/gapps-status")
async def gapps_status(device_id: str):
    """Check which Google apps are installed on the device."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return await asyncio.to_thread(_check_gapps_status, dev.adb_target)
