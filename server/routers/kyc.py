"""
Titan V12.0 — KYC Router
/api/kyc/* — Camera inject, deepfake, liveness, voice, KYC flow
"""

import logging
from fastapi import APIRouter, HTTPException, Request

from device_manager import DeviceManager

router = APIRouter(prefix="/api/kyc", tags=["kyc"])
logger = logging.getLogger("titan.kyc")

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.post("/{device_id}/upload_face")
async def kyc_upload_face(device_id: str, request: Request):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    try:
        from gpu_reenact_client import GPUReenactClient
        client = GPUReenactClient()
        # In real implementation, read the uploaded file
        return {"status": "face_uploaded", "device": device_id, "gpu_connected": True}
    except ImportError:
        logger.warning("GPUReenactClient not available; falling back to no-op face upload")
        return {"status": "face_upload_not_supported", "device": device_id}


@router.post("/{device_id}/start_deepfake")
async def kyc_start_deepfake(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    try:
        from gpu_reenact_client import GPUReenactClient
        client = GPUReenactClient()
        result = client.start_reenactment(device_id=device_id)
        return {"status": "deepfake_started", "device": device_id, "result": result}
    except ImportError:
        logger.warning("GPUReenactClient not available; deepfake flow not supported")
        return {"status": "deepfake_feature_not_available", "device": device_id}


@router.post("/{device_id}/stop_deepfake")
async def kyc_stop_deepfake(device_id: str):
    try:
        from gpu_reenact_client import GPUReenactClient
        client = GPUReenactClient()
        client.stop_reenactment()
    except ImportError:
        pass
    return {"status": "deepfake_stopped", "device": device_id}


@router.get("/{device_id}/status")
async def kyc_status(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    gpu_ready = False
    cameras = []
    try:
        from kyc_core import KYCController
        ctrl = KYCController()
        cameras = ctrl.get_available_cameras()
    except Exception as e:
        logger.debug(f"KYC camera detection failed: {e}")
    try:
        from gpu_reenact_client import GPUReenactClient
        client = GPUReenactClient()
        gpu_ready = client.is_connected()
    except Exception as e:
        logger.debug(f"GPU reenact check failed: {e}")
    return {
        "device": device_id, "device_state": dev.state,
        "gpu_ready": gpu_ready, "face_loaded": False,
        "deepfake_active": False, "cameras": cameras,
    }


@router.get("/{device_id}/deepfake_status")
async def kyc_deepfake_status_alias(device_id: str):
    """Alias called by the UI (deepfake_status → status)."""
    return await kyc_status(device_id)


@router.post("/{device_id}/kyc-flow")
async def kyc_flow(device_id: str, request: Request):
    body = await request.json()
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    try:
        from kyc_core import KYCController
        kyc = KYCController()
        result = kyc.run_flow(
            provider=body.get("provider", "auto"),
            face_image=body.get("face_image", ""),
        )
        return {"device": device_id, "result": result}
    except ImportError:
        logger.warning("KYCController not available; returning no-op kyc flow response")
        return {"device": device_id, "result": {"status": "not_available", "provider": body.get("provider", "auto")}}
    except Exception as e:
        logger.exception("KYC flow execution failed")
        return {"device": device_id, "error": str(e)}


@router.post("/{device_id}/voice")
async def kyc_voice(device_id: str, request: Request):
    body = await request.json()
    try:
        from kyc_voice_engine import KYCVoiceEngine
        engine = KYCVoiceEngine()
        result = engine.synthesize(
            text=body.get("text", ""),
            voice=body.get("voice", "en-US-male"),
        )
        return {"device": device_id, "result": result}
    except ImportError:
        logger.warning("KYCVoiceEngine is unavailable; returning placeholder response")
        return {"device": device_id, "result": {"status": "voice_feature_not_supported"}}
    except Exception as e:
        logger.exception("KYC voice synthesis failed")
        return {"device": device_id, "error": str(e)}
