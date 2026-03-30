"""
Titan V13.0 — VMOS Cloud Router
/api/vmos/* — VMOS Pro cloud device management and modification

Provides REST endpoints for:
  - Instance management (list, start, stop, restart)
  - Device modification (fingerprint, GPS, WiFi)
  - Shell command execution
  - Content injection (contacts, SMS, calls)
  - Screenshot and UI control
"""

import logging
import os
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("titan.vmos")

# Ensure workspace core/ is in path
workspace_core = os.path.join(os.path.dirname(os.path.dirname(__file__)), "../core")
if workspace_core not in sys.path:
    sys.path.insert(0, workspace_core)

from vmos_cloud_module import VMOSCloudBridge, VMOSDeviceModifier  # noqa: E402

router = APIRouter(prefix="/api/vmos", tags=["vmos"])

# ═══════════════════════════════════════════════════════════════════════
# SHARED BRIDGE SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_bridge: VMOSCloudBridge | None = None
_modifier: VMOSDeviceModifier | None = None


def get_bridge() -> VMOSCloudBridge:
    """Get or create the shared VMOS bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = VMOSCloudBridge()
    return _bridge


def get_modifier() -> VMOSDeviceModifier:
    """Get or create the shared VMOS modifier instance."""
    global _modifier
    if _modifier is None:
        _modifier = VMOSDeviceModifier(get_bridge())
    return _modifier


def init(api_key: str | None = None, api_secret: str | None = None):
    """Initialize the VMOS bridge with credentials."""
    global _bridge, _modifier
    if api_key and api_secret:
        _bridge = VMOSCloudBridge(api_key=api_key, api_secret=api_secret)
        _modifier = VMOSDeviceModifier(_bridge)
        logger.info("VMOS bridge initialized with provided credentials")
    else:
        _bridge = VMOSCloudBridge()
        _modifier = VMOSDeviceModifier(_bridge)
        logger.info("VMOS bridge initialized from environment")


# ═══════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════


class VMOSStatusResponse(BaseModel):
    """VMOS API status response."""

    configured: bool = False
    host: str = ""
    message: str = ""


class VMOSInstanceResponse(BaseModel):
    """VMOS instance details."""

    pad_code: str = ""
    device_ip: str = ""
    status: str = ""
    device_level: str = ""
    device_name: str = ""
    rom_version: str = ""
    android_version: str = ""
    resolution: str = ""


class ShellCommandRequest(BaseModel):
    """Request to execute a shell command."""

    command: str = Field(..., description="Shell command to execute")
    timeout: int = Field(default=60, ge=5, le=300, description="Timeout in seconds")


class ShellCommandResponse(BaseModel):
    """Response from shell command execution."""

    ok: bool = False
    result: str = ""
    task_id: int = 0
    message: str = ""


class UpdatePropsRequest(BaseModel):
    """Request to update Android properties."""

    props: dict[str, str] = Field(..., description="Property name -> value mapping")


class ModifyFingerprintRequest(BaseModel):
    """Request for device fingerprint modification."""

    model: str = Field(default="samsung_s25_ultra", description="Device model preset")
    country: str = Field(default="US", description="Country code")
    carrier: str = Field(default="tmobile", description="Carrier preset")


class SetGPSRequest(BaseModel):
    """Request to set GPS location."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude")
    altitude: float = Field(default=10.0, description="Altitude in meters")


class SetWiFiRequest(BaseModel):
    """Request to set WiFi configuration."""

    ssid: str = Field(..., description="WiFi network name")
    mac: str = Field(..., description="WiFi MAC address")
    ip: str = Field(..., description="Device IP address")
    gateway: str = Field(default="192.168.1.1", description="Network gateway")


class ContactRequest(BaseModel):
    """Contact for injection."""

    firstName: str = ""
    lastName: str = ""
    phone: str = ""
    email: str = ""


class InjectContactsRequest(BaseModel):
    """Request to inject contacts."""

    contacts: list[ContactRequest]


class CallLogRequest(BaseModel):
    """Call log entry for injection."""

    number: str
    inputType: int = Field(default=1, ge=1, le=3, description="1=incoming, 2=outgoing, 3=missed")
    duration: int = Field(default=60, ge=0, description="Duration in seconds")
    timeString: str = Field(..., description="Time string YYYY-MM-DD HH:MM:SS")


class InjectCallLogsRequest(BaseModel):
    """Request to inject call logs."""

    calls: list[CallLogRequest]


class SendSMSRequest(BaseModel):
    """Request to send/inject SMS."""

    sender: str = Field(..., description="Sender phone number")
    message: str = Field(..., description="SMS message body")


class ClickRequest(BaseModel):
    """Request for click/tap event."""

    x: int = Field(..., ge=0, description="X coordinate")
    y: int = Field(..., ge=0, description="Y coordinate")


class SwipeRequest(BaseModel):
    """Request for swipe gesture."""

    start_x: int = Field(..., ge=0, description="Start X coordinate")
    start_y: int = Field(..., ge=0, description="Start Y coordinate")
    end_x: int = Field(..., ge=0, description="End X coordinate")
    end_y: int = Field(..., ge=0, description="End Y coordinate")
    duration: int = Field(default=300, ge=100, le=5000, description="Duration in milliseconds")


class InputTextRequest(BaseModel):
    """Request for text input."""

    text: str = Field(..., description="Text to input")


class KeyEventRequest(BaseModel):
    """Request for key event."""

    key_code: int = Field(..., description="Android key code")


class InstallAppRequest(BaseModel):
    """Request to install app."""

    apk_url: str = Field(..., description="URL to APK file")


class AppRequest(BaseModel):
    """Request for app operations."""

    package_name: str = Field(..., description="App package name")


class FullModificationRequest(BaseModel):
    """Request for full device modification."""

    model: str = Field(default="samsung_s25_ultra", description="Device model preset")
    country: str = Field(default="US", description="Country code")
    carrier: str = Field(default="tmobile", description="Carrier preset")
    inject_contacts: bool = Field(default=True, description="Inject sample contacts")
    inject_sms: bool = Field(default=True, description="Inject sample SMS")
    inject_calls: bool = Field(default=True, description="Inject sample call logs")
    set_gps: bool = Field(default=True, description="Set GPS to country location")
    restart_after: bool = Field(default=True, description="Restart device after modification")


class GenericResponse(BaseModel):
    """Generic success/failure response."""

    ok: bool = False
    message: str = ""
    data: dict[str, Any] | None = None


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - STATUS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@router.get("/status", response_model=VMOSStatusResponse)
async def get_status():
    """Check VMOS API configuration status."""
    bridge = get_bridge()
    return VMOSStatusResponse(
        configured=bridge.config.is_configured(),
        host=bridge.config.host,
        message="VMOS Cloud API configured" if bridge.config.is_configured() else "API credentials not set",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - INSTANCE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


@router.get("/instances", response_model=list[VMOSInstanceResponse])
async def list_instances():
    """List all VMOS cloud phone instances."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    instances = await bridge.list_instances()
    return [
        VMOSInstanceResponse(
            pad_code=inst.pad_code,
            device_ip=inst.device_ip,
            status=inst.status,
            device_level=inst.device_level,
            device_name=inst.device_name,
            rom_version=inst.rom_version,
            android_version=inst.android_version,
            resolution=inst.resolution,
        )
        for inst in instances
    ]


@router.get("/instances/{pad_code}", response_model=VMOSInstanceResponse)
async def get_instance(pad_code: str):
    """Get details of a specific VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    inst = await bridge.get_instance(pad_code)
    if not inst:
        raise HTTPException(404, f"Instance {pad_code} not found")

    return VMOSInstanceResponse(
        pad_code=inst.pad_code,
        device_ip=inst.device_ip,
        status=inst.status,
        device_level=inst.device_level,
        device_name=inst.device_name,
        rom_version=inst.rom_version,
        android_version=inst.android_version,
        resolution=inst.resolution,
    )


@router.post("/instances/{pad_code}/start", response_model=GenericResponse)
async def start_instance(pad_code: str):
    """Start a VMOS cloud phone instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.start_instance(pad_code)
    return GenericResponse(ok=r.ok, message=r.message if not r.ok else "Instance started")


@router.post("/instances/{pad_code}/stop", response_model=GenericResponse)
async def stop_instance(pad_code: str):
    """Stop a VMOS cloud phone instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.stop_instance(pad_code)
    return GenericResponse(ok=r.ok, message=r.message if not r.ok else "Instance stopped")


@router.post("/instances/{pad_code}/restart", response_model=GenericResponse)
async def restart_instance(pad_code: str):
    """Restart a VMOS cloud phone instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.restart_instance(pad_code)
    return GenericResponse(ok=r.ok, message=r.message if not r.ok else "Instance restarting")


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - SHELL EXECUTION
# ═══════════════════════════════════════════════════════════════════════


@router.post("/instances/{pad_code}/shell", response_model=ShellCommandResponse)
async def exec_shell(pad_code: str, req: ShellCommandRequest):
    """Execute a shell command on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.exec_shell(pad_code, req.command, req.timeout)
    return ShellCommandResponse(
        ok=r.ok,
        result=r.result or "",
        task_id=r.task_id,
        message=r.message if not r.ok else "",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - DEVICE MODIFICATION
# ═══════════════════════════════════════════════════════════════════════


@router.post("/instances/{pad_code}/props", response_model=GenericResponse)
async def update_props(pad_code: str, req: UpdatePropsRequest):
    """Update Android system properties on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.update_android_props(pad_code, req.props)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Updated {len(req.props)} properties",
        data={"count": len(req.props)},
    )


@router.post("/instances/{pad_code}/fingerprint", response_model=GenericResponse)
async def modify_fingerprint(pad_code: str, req: ModifyFingerprintRequest):
    """Apply a device fingerprint preset to a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.modify_fingerprint(pad_code, req.model, req.country, req.carrier)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Applied fingerprint: {req.model}",
        data={"model": req.model, "country": req.country, "carrier": req.carrier},
    )


@router.post("/instances/{pad_code}/gps", response_model=GenericResponse)
async def set_gps(pad_code: str, req: SetGPSRequest):
    """Set GPS location on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.set_gps(pad_code, req.latitude, req.longitude, req.altitude)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"GPS set to {req.latitude}, {req.longitude}",
        data={"latitude": req.latitude, "longitude": req.longitude},
    )


@router.post("/instances/{pad_code}/wifi", response_model=GenericResponse)
async def set_wifi(pad_code: str, req: SetWiFiRequest):
    """Set WiFi configuration on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.set_wifi(pad_code, req.ssid, req.mac, req.ip, req.gateway)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"WiFi set to {req.ssid}",
        data={"ssid": req.ssid, "ip": req.ip},
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - CONTENT INJECTION
# ═══════════════════════════════════════════════════════════════════════


@router.post("/instances/{pad_code}/contacts", response_model=GenericResponse)
async def inject_contacts(pad_code: str, req: InjectContactsRequest):
    """Inject contacts into a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    contacts = [c.model_dump() for c in req.contacts]
    r = await bridge.inject_contacts(pad_code, contacts)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Injected {len(contacts)} contacts",
        data={"count": len(contacts)},
    )


@router.post("/instances/{pad_code}/calls", response_model=GenericResponse)
async def inject_call_logs(pad_code: str, req: InjectCallLogsRequest):
    """Inject call log entries into a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    calls = [c.model_dump() for c in req.calls]
    r = await bridge.inject_call_logs(pad_code, calls)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Injected {len(calls)} call logs",
        data={"count": len(calls)},
    )


@router.post("/instances/{pad_code}/sms", response_model=GenericResponse)
async def send_sms(pad_code: str, req: SendSMSRequest):
    """Inject an SMS message into a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.send_sms(pad_code, req.sender, req.message)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else "SMS injected",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - UI CONTROL
# ═══════════════════════════════════════════════════════════════════════


@router.get("/instances/{pad_code}/screenshot", response_model=GenericResponse)
async def screenshot(pad_code: str):
    """Capture a screenshot from a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.screenshot(pad_code)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else "Screenshot captured",
        data=r.data,
    )


@router.post("/instances/{pad_code}/click", response_model=GenericResponse)
async def click(pad_code: str, req: ClickRequest):
    """Send a click/tap event to a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.click(pad_code, req.x, req.y)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Clicked at ({req.x}, {req.y})",
    )


@router.post("/instances/{pad_code}/swipe", response_model=GenericResponse)
async def swipe(pad_code: str, req: SwipeRequest):
    """Send a swipe gesture to a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.swipe(pad_code, req.start_x, req.start_y, req.end_x, req.end_y, req.duration)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else "Swipe completed",
    )


@router.post("/instances/{pad_code}/input", response_model=GenericResponse)
async def input_text(pad_code: str, req: InputTextRequest):
    """Input text on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.input_text(pad_code, req.text)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else "Text input completed",
    )


@router.post("/instances/{pad_code}/key", response_model=GenericResponse)
async def key_event(pad_code: str, req: KeyEventRequest):
    """Send a key event to a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.key_event(pad_code, req.key_code)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Key event {req.key_code} sent",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - APP MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


@router.post("/instances/{pad_code}/apps/install", response_model=GenericResponse)
async def install_app(pad_code: str, req: InstallAppRequest):
    """Install an APK from URL on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.install_app(pad_code, req.apk_url)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else "App installation started",
        data={"task_id": r.task_id} if r.task_id else None,
    )


@router.post("/instances/{pad_code}/apps/uninstall", response_model=GenericResponse)
async def uninstall_app(pad_code: str, req: AppRequest):
    """Uninstall an app from a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.uninstall_app(pad_code, req.package_name)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Uninstalled {req.package_name}",
    )


@router.post("/instances/{pad_code}/apps/launch", response_model=GenericResponse)
async def launch_app(pad_code: str, req: AppRequest):
    """Launch an app on a VMOS instance."""
    bridge = get_bridge()
    if not bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    r = await bridge.launch_app(pad_code, req.package_name)
    return GenericResponse(
        ok=r.ok,
        message=r.message if not r.ok else f"Launched {req.package_name}",
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS - HIGH-LEVEL ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════


@router.post("/instances/{pad_code}/modify", response_model=GenericResponse)
async def full_modification(pad_code: str, req: FullModificationRequest):
    """
    Perform a complete device modification.

    This high-level endpoint applies:
    - Device fingerprint (model, carrier, locale)
    - GPS location
    - Sample contacts, SMS, and call logs
    - Restarts the device to apply changes
    """
    modifier = get_modifier()
    if not modifier.bridge.config.is_configured():
        raise HTTPException(503, "VMOS API not configured")

    result = await modifier.full_modification(
        pad_code=pad_code,
        model=req.model,
        country=req.country,
        carrier=req.carrier,
        inject_contacts=req.inject_contacts,
        inject_sms=req.inject_sms,
        inject_calls=req.inject_calls,
        set_gps=req.set_gps,
        restart_after=req.restart_after,
    )

    return GenericResponse(
        ok=result.get("success", False),
        message="Modification completed" if result.get("success") else "Modification had failures",
        data=result,
    )
