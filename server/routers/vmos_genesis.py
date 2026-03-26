"""
VMOS Genesis Router — Full Pipeline API for VMOS Cloud Devices
/api/vmos-genesis/* — Pipeline start, status polling, device list
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_manager import JobManager
from vmos_genesis_engine import VMOSGenesisEngine, PipelineConfig

router = APIRouter(prefix="/api/vmos-genesis", tags=["vmos-genesis"])
logger = logging.getLogger("titan.vmos_genesis")

_jobs = JobManager("vmos_genesis", ttl=14400)
dm = None   # set by init()


def init(device_manager):
    global dm
    dm = device_manager


# ── Request models ────────────────────────────────────────────────────────

class VMOSPipelineBody(BaseModel):
    pad_code: str
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


# ── Background runner ─────────────────────────────────────────────────────

def _run_pipeline_async(job_id: str, body: VMOSPipelineBody):
    """Run pipeline in a new event loop (called from background thread)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_pipeline(job_id, body))
    except Exception as e:
        logger.exception("VMOS pipeline %s failed", job_id)
        _jobs.update(job_id, {
            "status": "failed",
            "error": str(e),
            "completed_at": time.time(),
        })
    finally:
        loop.close()


async def _run_pipeline(job_id: str, body: VMOSPipelineBody):
    """Async pipeline execution."""
    engine = VMOSGenesisEngine(body.pad_code)

    cfg = PipelineConfig(
        name=body.name,
        email=body.email,
        phone=body.phone,
        dob=body.dob,
        ssn=body.ssn,
        street=body.street,
        city=body.city,
        state=body.state,
        zip=body.zip,
        country=body.country,
        gender=body.gender,
        occupation=body.occupation,
        cc_number=body.cc_number,
        cc_exp=body.cc_exp,
        cc_cvv=body.cc_cvv,
        cc_holder=body.cc_holder,
        google_email=body.google_email,
        google_password=body.google_password,
        real_phone=body.real_phone,
        otp_code=body.otp_code,
        proxy_url=body.proxy_url,
        device_model=body.device_model,
        carrier=body.carrier,
        location=body.location,
        age_days=body.age_days,
        skip_wipe=body.skip_wipe,
        skip_patch=body.skip_patch,
    )

    def on_update(result):
        """Persist engine state to job manager on each phase change."""
        _jobs.update(job_id, engine.result_dict())

    result = await engine.run_pipeline(cfg, job_id=job_id, on_update=on_update)

    # Final persist
    final = engine.result_dict()
    final["status"] = "completed"
    final["completed_at"] = time.time()
    _jobs.update(job_id, final)


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/pipeline")
async def vmos_genesis_pipeline(body: VMOSPipelineBody):
    """Start full Genesis pipeline on a VMOS Cloud device.

    Returns a job_id for polling via /api/vmos-genesis/pipeline-status/{job_id}.
    """
    if not body.pad_code:
        raise HTTPException(400, "pad_code is required")

    job_id = str(uuid.uuid4())[:8]

    phases = [
        {"n": i, "name": n, "status": "pending", "notes": ""}
        for i, n in enumerate(VMOSGenesisEngine.PHASE_NAMES)
    ]

    _jobs.create(job_id, {
        "status": "running",
        "type": "vmos_pipeline",
        "pad_code": body.pad_code,
        "job_id": job_id,
        "phases": phases,
        "log": [],
        "started_at": time.time(),
        "trust_score": 0,
        "profile_id": "",
        "persona": body.name,
        "email": body.google_email or body.email,
    })

    import threading
    t = threading.Thread(
        target=_run_pipeline_async,
        args=(job_id, body),
        daemon=True,
    )
    t.start()

    return {
        "status": "started",
        "job_id": job_id,
        "pad_code": body.pad_code,
        "poll_url": f"/api/vmos-genesis/pipeline-status/{job_id}",
    }


@router.get("/pipeline-status/{job_id}")
async def vmos_genesis_pipeline_status(job_id: str):
    """Poll VMOS pipeline phase status."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Pipeline job not found")
    return job


@router.get("/jobs")
async def vmos_genesis_list_jobs(limit: int = 20):
    """List recent VMOS genesis pipeline jobs."""
    return _jobs.list_jobs(limit=limit)
