"""
Titan V12.0 — Devices Router (Cuttlefish)
/api/devices/* — Device CRUD, streaming, screenshots, input, factory reset
"""

import asyncio
import io
import logging
import subprocess
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("titan.devices")

import sys
import os
# Ensure workspace core/ is in path before system /opt/titan/core/
workspace_core = os.path.join(os.path.dirname(os.path.dirname(__file__)), '../core')
if workspace_core not in sys.path:
    sys.path.insert(0, workspace_core)

from device_manager import DeviceManager, CreateDeviceRequest, PERMANENT_DEVICE_ID
from anomaly_patcher import AnomalyPatcher
from device_presets import COUNTRY_DEFAULTS

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Shared device manager singleton — set by main app
dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class CreateDeviceBody(BaseModel):
    model: str = "samsung_s25_ultra"
    country: str = "US"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    phone_number: str = ""
    android_version: str = "14"
    auto_patch: bool = False


class InputBody(BaseModel):
    type: str = "tap"
    x: float = 0.0
    y: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    duration: int = 300
    keycode: str = ""
    text: str = ""


@router.get("")
async def list_devices():
    devices = dm.list_devices()
    return {"devices": [d.to_dict() for d in devices]}


# ═══════════════════════════════════════════════════════════════════════
# PERMANENT DEVICE — Single desktop Cuttlefish instance
# ═══════════════════════════════════════════════════════════════════════

@router.get("/permanent")
async def get_permanent_device():
    """Get the permanent desktop Cuttlefish device."""
    dev = dm.get_permanent_device()
    if not dev:
        raise HTTPException(404, "No permanent device registered. Is Cuttlefish running?")
    return dev.to_dict()


@router.post("/permanent/reconnect")
async def reconnect_permanent_device():
    """Verify ADB connectivity for the permanent device and set state to ready.
    Call this after the Cuttlefish VM has booted to clear any stale error state."""
    from device_manager import _run, PERMANENT_ADB_TARGET
    dev = dm.get_permanent_device()
    if not dev:
        # Try to auto-register now
        dm._register_permanent_device()
        dev = dm.get_permanent_device()
        if not dev:
            raise HTTPException(404, "Permanent device not detected. Is Cuttlefish running at " + PERMANENT_ADB_TARGET + "?")

    # Ensure ADB is connected
    _run(f"adb connect {PERMANENT_ADB_TARGET}", timeout=5)
    r = _run(f"adb -s {PERMANENT_ADB_TARGET} shell echo ok", timeout=8)
    if r.get("ok") and "ok" in r.get("stdout", ""):
        dev.state = "ready"
        dev.error = ""
        dm._save_state()
        return {"ok": True, "state": "ready", "device": dev.to_dict()}
    else:
        return {"ok": False, "state": "unreachable", "detail": r.get("stderr", "ADB not responding")}


class FactoryResetBody(BaseModel):
    confirm: bool = False


@router.post("/factory-reset")
async def factory_reset(body: FactoryResetBody = FactoryResetBody()):
    """Factory reset the permanent desktop device.
    Wipes /data (user data, app data, profiles, patches), reboots,
    and returns a clean device ready for fresh forge + inject."""
    dev = dm.get_permanent_device()
    if not dev:
        raise HTTPException(404, "No permanent device registered")
    try:
        result = await dm.factory_reset_device(dev.id)
        return result
    except RuntimeError as e:
        raise HTTPException(500, str(e))


class UpdateDeviceConfigBody(BaseModel):
    model: str = ""
    country: str = ""
    carrier: str = ""
    location: str = ""


@router.post("/permanent/config")
async def update_permanent_config(body: UpdateDeviceConfigBody):
    """Update the permanent device's identity configuration (model, carrier, country).
    Used before factory reset + re-forge to set the new device identity."""
    dev = dm.get_permanent_device()
    if not dev:
        raise HTTPException(404, "No permanent device registered")
    if body.model:
        dev.config["model"] = body.model
    if body.country:
        dev.config["country"] = body.country
    if body.carrier:
        dev.config["carrier"] = body.carrier
    if body.location:
        dev.config["location"] = body.location
    dm._save_state()
    return {"ok": True, "config": dev.config}


@router.get("/{device_id}")
async def get_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return dev.to_dict()


@router.get("/{device_id}/info")
async def get_device_info(device_id: str):
    info = dm.get_device_info(device_id)
    if not info:
        raise HTTPException(404, "Device not found or not ready")
    return info


@router.post("")
async def create_device(body: CreateDeviceBody):
    try:
        req = CreateDeviceRequest(
            model=body.model,
            country=body.country,
            carrier=body.carrier,
            phone_number=body.phone_number,
            android_version=body.android_version,
        )
        dev = await dm.create_device(req)

        if body.auto_patch:
            # Auto-patch with matching preset + carrier + location
            location = body.location
            if not location:
                defaults = COUNTRY_DEFAULTS.get(body.country, {})
                location = defaults.get("location", "nyc")

            def _run_patch():
                patcher = AnomalyPatcher(adb_target=dev.adb_target)
                return patcher.full_patch(body.model, body.carrier, location)
            patch_result = await asyncio.to_thread(_run_patch)
            dev.patch_result = patch_result.to_dict()
            dev.stealth_score = patch_result.score
            dev.state = "patched"
            return {"device": dev.to_dict(), "patch": patch_result.to_dict()}

        return {"device": dev.to_dict()}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{device_id}")
async def destroy_device(device_id: str):
    ok = await dm.destroy_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    # B4: Clean up stale agents for this device
    try:
        from routers.agent import cleanup_agent as _agent_cleanup
        _agent_cleanup(device_id)
    except Exception:
        pass
    try:
        from routers.ai import cleanup_agent as _ai_cleanup
        _ai_cleanup(device_id)
    except Exception:
        pass
    return {"ok": True}


@router.post("/{device_id}/restart")
async def restart_device(device_id: str):
    ok = await dm.restart_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    return {"ok": True}


@router.get("/{device_id}/screenshot")
async def device_screenshot(device_id: str):
    data = await dm.screenshot(device_id)
    if not data:
        raise HTTPException(404, "Screenshot failed")
    return StreamingResponse(io.BytesIO(data), media_type="image/jpeg")


@router.post("/{device_id}/input")
async def device_input(device_id: str, body: InputBody):
    """Send touch/key input to device via ADB."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    from device_manager import _adb
    t = dev.adb_target

    # Get screen resolution for coordinate mapping
    info = _adb(t, 'shell "wm size"')
    width, height = 1080, 2400
    if info["ok"] and "x" in info["stdout"]:
        try:
            parts = info["stdout"].split(":")[-1].strip().split("x")
            width, height = int(parts[0]), int(parts[1])
        except Exception as e:
            logger.debug(f"Screen resolution parse failed: {e}")

    if body.type == "tap":
        px, py = int(body.x * width), int(body.y * height)
        try:
            subprocess.run(
                ["adb", "-s", t, "shell", "input", "tap", str(px), str(py)],
                capture_output=True, timeout=10
            )
            return {"ok": True, "action": "tap", "px": px, "py": py}
        except Exception as e:
            logger.error(f"Tap failed: {e}")
            return {"ok": False, "error": str(e)}

    elif body.type == "swipe":
        px1, py1 = int(body.x1 * width), int(body.y1 * height)
        px2, py2 = int(body.x2 * width), int(body.y2 * height)
        dur = max(100, min(body.duration, 2000))
        try:
            subprocess.run(
                ["adb", "-s", t, "shell", "input", "swipe", str(px1), str(py1), str(px2), str(py2), str(dur)],
                capture_output=True, timeout=10
            )
            return {"ok": True, "action": "swipe"}
        except Exception as e:
            logger.error(f"Swipe failed: {e}")
            return {"ok": False, "error": str(e)}

    elif body.type == "key":
        try:
            subprocess.run(
                ["adb", "-s", t, "shell", "input", "keyevent", body.keycode],
                capture_output=True, timeout=10
            )
            return {"ok": True, "action": "key", "keycode": body.keycode}
        except Exception as e:
            logger.error(f"Key event failed: {e}")
            return {"ok": False, "error": str(e)}

    elif body.type == "text":
        try:
            subprocess.run(
                ["adb", "-s", t, "shell", "input", "text", body.text],
                capture_output=True, timeout=10
            )
            return {"ok": True, "action": "text", "length": len(body.text)}
        except Exception as e:
            logger.error(f"Text input failed: {e}")
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "unknown input type"}
