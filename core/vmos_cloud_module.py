"""
Titan V13 — VMOS Cloud Module
Cloud device management and modification for VMOS Pro cloud phone instances.

This module provides:
  1. Instance Management - Create, list, start, stop, restart cloud phones
  2. Device Modification - Update Android properties, SIM, GPS, WiFi
  3. Shell Execution - Run commands on cloud devices
  4. Content Injection - Contacts, SMS, call logs, gallery
  5. Screenshot/UI Control - Capture screenshots, send input events

Authentication:
  Uses HMAC-SHA256 signature authentication with access_key/secret_key.
  Keys are loaded from environment variables:
    - VMOS_API_KEY: API access key
    - VMOS_API_SECRET: API secret key
    - VMOS_API_HOST: API host (default: api.vmoscloud.com)

Usage:
    from vmos_cloud_module import VMOSCloudBridge

    bridge = VMOSCloudBridge()
    instances = await bridge.list_instances()
    result = await bridge.exec_shell("PAD_CODE", "getprop ro.product.model")
    await bridge.update_android_props("PAD_CODE", {"ro.product.brand": "samsung"})

API Reference:
  https://github.com/malithwishwa02-dot/Vmos-api
"""

import asyncio
import hashlib
import hmac
import http.client
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("titan.vmos-cloud")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_API_HOST = "api.vmoscloud.com"
DEFAULT_SERVICE = "armcloud-paas"
DEFAULT_TIMEOUT = 60


@dataclass
class VMOSConfig:
    """VMOS Cloud API configuration."""

    api_key: str = ""
    api_secret: str = ""
    host: str = DEFAULT_API_HOST
    service: str = DEFAULT_SERVICE
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "VMOSConfig":
        """Load configuration from environment variables."""
        return cls(
            api_key=os.environ.get("VMOS_API_KEY", ""),
            api_secret=os.environ.get("VMOS_API_SECRET", ""),
            host=os.environ.get("VMOS_API_HOST", DEFAULT_API_HOST),
            service=os.environ.get("VMOS_API_SERVICE", DEFAULT_SERVICE),
            timeout=int(os.environ.get("VMOS_API_TIMEOUT", str(DEFAULT_TIMEOUT))),
        )

    def is_configured(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.api_key and self.api_secret)


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class VMOSInstance:
    """Represents a VMOS cloud phone instance."""

    pad_code: str = ""
    device_ip: str = ""
    status: str = ""
    device_level: str = ""
    device_name: str = ""
    create_time: str = ""
    update_time: str = ""
    rom_version: str = ""
    android_version: str = ""
    resolution: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pad_code": self.pad_code,
            "device_ip": self.device_ip,
            "status": self.status,
            "device_level": self.device_level,
            "device_name": self.device_name,
            "create_time": self.create_time,
            "update_time": self.update_time,
            "rom_version": self.rom_version,
            "android_version": self.android_version,
            "resolution": self.resolution,
        }

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "VMOSInstance":
        """Create instance from API response."""
        return cls(
            pad_code=data.get("padCode", ""),
            device_ip=data.get("deviceIp", ""),
            status=data.get("status", ""),
            device_level=data.get("deviceLevel", ""),
            device_name=data.get("deviceName", ""),
            create_time=data.get("createTime", ""),
            update_time=data.get("updateTime", ""),
            rom_version=data.get("romVersion", ""),
            android_version=data.get("androidVersion", ""),
            resolution=data.get("resolution", ""),
            raw_data=data,
        )


@dataclass
class VMOSResponse:
    """Generic response from VMOS API."""

    ok: bool = False
    status: int = 0
    code: int = 0
    message: str = ""
    data: Any = None
    result: Any = None
    task_id: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": self.ok,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "result": self.result,
            "task_id": self.task_id,
        }


@dataclass
class ContactInfo:
    """Contact information for injection."""

    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class CallLogEntry:
    """Call log entry for injection."""

    number: str = ""
    input_type: int = 1  # 1=incoming, 2=outgoing, 3=missed
    duration: int = 0  # seconds
    time_string: str = ""  # YYYY-MM-DD HH:MM:SS


@dataclass
class SMSEntry:
    """SMS message for injection."""

    sender: str = ""
    message: str = ""
    timestamp: int | None = None


# ═══════════════════════════════════════════════════════════════════════
# VMOS CLOUD BRIDGE
# ═══════════════════════════════════════════════════════════════════════


class VMOSCloudBridge:
    """
    Bridge to VMOS Cloud API for managing cloud phone instances.

    Supports:
      - Instance lifecycle (list, start, stop, restart)
      - Device property modification
      - Shell command execution
      - Content injection (contacts, SMS, calls)
      - GPS/WiFi/SIM configuration
      - Screenshot capture
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        config: VMOSConfig | None = None,
    ):
        """
        Initialize VMOS Cloud Bridge.

        Args:
            api_key: API access key (or from VMOS_API_KEY env var)
            api_secret: API secret key (or from VMOS_API_SECRET env var)
            base_url: Full base URL (e.g., "https://api.vmoscloud.com")
            config: VMOSConfig object (overrides other params)
        """
        if config:
            self.config = config
        else:
            self.config = VMOSConfig.from_env()

        # Override with explicit params
        if api_key:
            self.config.api_key = api_key
        if api_secret:
            self.config.api_secret = api_secret
        if base_url:
            # Parse base_url to extract host
            if base_url.startswith("https://"):
                self.config.host = base_url[8:].split("/")[0]
            elif base_url.startswith("http://"):
                self.config.host = base_url[7:].split("/")[0]
            else:
                self.config.host = base_url.split("/")[0]

        if not self.config.is_configured():
            logger.warning("VMOS Cloud API credentials not configured")

    # ─── HMAC-SHA256 SIGNATURE ─────────────────────────────────────────

    def _sign_request(self, body_str: str) -> dict[str, str]:
        """
        Generate HMAC-SHA256 signature headers for VMOS API request.

        Args:
            body_str: JSON request body as string

        Returns:
            Dictionary of required headers
        """
        x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]
        content_type = "application/json;charset=UTF-8"
        signed_headers = "content-type;host;x-content-sha256;x-date"

        # Content hash
        content_sha256 = hashlib.sha256(body_str.encode()).hexdigest()

        # Canonical request
        canonical = (
            f"host:{self.config.host}\n"
            f"x-date:{x_date}\n"
            f"content-type:{content_type}\n"
            f"signedHeaders:{signed_headers}\n"
            f"x-content-sha256:{content_sha256}"
        )
        canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()

        # Credential scope
        credential_scope = f"{short_date}/{self.config.service}/request"

        # String to sign
        string_to_sign = f"HMAC-SHA256\n{x_date}\n{credential_scope}\n{canonical_hash}"

        # Signing key derivation
        k_date = hmac.new(
            self.config.api_secret.encode(), short_date.encode(), hashlib.sha256
        ).digest()
        k_service = hmac.new(k_date, self.config.service.encode(), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()

        # Final signature
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        return {
            "content-type": content_type,
            "x-host": self.config.host,
            "x-date": x_date,
            "authorization": (
                f"HMAC-SHA256 Credential={self.config.api_key}, "
                f"SignedHeaders={signed_headers}, "
                f"Signature={signature}"
            ),
        }

    # ─── HTTP CLIENT ───────────────────────────────────────────────────

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """
        Send POST request to VMOS API.

        Args:
            path: API endpoint path
            body: Request body dictionary

        Returns:
            Response data dictionary
        """
        if not self.config.is_configured():
            logger.error("VMOS API not configured")
            return {"code": -1, "msg": "API not configured"}

        body_str = json.dumps(body, separators=(",", ":"))

        # Run synchronous HTTP in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._post_sync, path, body_str)

    def _post_sync(self, path: str, body_str: str) -> dict[str, Any]:
        """Synchronous POST request (for thread pool execution)."""
        try:
            headers = self._sign_request(body_str)
            # Use SSL context that doesn't verify (for TencentEdgeOne CDN compatibility)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            conn = http.client.HTTPSConnection(
                self.config.host,
                timeout=self.config.timeout,
                context=ctx,
            )
            conn.request("POST", path, body=body_str.encode(), headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode()
            conn.close()

            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return {"code": -1, "msg": f"JSON decode error: {e}"}
        except Exception as e:
            logger.error(f"HTTP error: {e}")
            return {"code": -1, "msg": f"HTTP error: {e}"}

    # ─── INSTANCE MANAGEMENT ───────────────────────────────────────────

    async def list_instances(self, page: int = 1, rows: int = 50) -> list[VMOSInstance]:
        """
        List all cloud phone instances.

        Args:
            page: Page number (starting from 1)
            rows: Number of instances per page

        Returns:
            List of VMOSInstance objects
        """
        r = await self._post(
            "/vcpcloud/api/padApi/list", {"pageNo": page, "pageSize": rows}
        )
        if r.get("code") != 200:
            logger.error(f"list_instances failed: {r.get('msg', 'Unknown error')}")
            return []

        instances = []
        for item in r.get("data", {}).get("list", []):
            instances.append(VMOSInstance.from_api_response(item))
        return instances

    async def get_instance(self, pad_code: str) -> VMOSInstance | None:
        """
        Get details of a specific instance.

        Args:
            pad_code: Instance pad code

        Returns:
            VMOSInstance or None if not found
        """
        r = await self._post("/vcpcloud/api/padApi/detail", {"padCode": pad_code})
        if r.get("code") != 200:
            logger.error(f"get_instance failed: {r.get('msg', 'Unknown error')}")
            return None
        data = r.get("data", {})
        if not data:
            return None
        return VMOSInstance.from_api_response(data)

    async def start_instance(self, pad_code: str) -> VMOSResponse:
        """Start a cloud phone instance."""
        r = await self._post("/vcpcloud/api/padApi/start", {"padCodes": [pad_code]})
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def stop_instance(self, pad_code: str) -> VMOSResponse:
        """Stop a cloud phone instance."""
        r = await self._post("/vcpcloud/api/padApi/stop", {"padCodes": [pad_code]})
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def restart_instance(self, pad_code: str) -> VMOSResponse:
        """Restart a cloud phone instance."""
        r = await self._post("/vcpcloud/api/padApi/restart", {"padCodes": [pad_code]})
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    # ─── SHELL EXECUTION ───────────────────────────────────────────────

    async def exec_shell(
        self, pad_code: str, command: str, timeout: int = 60
    ) -> VMOSResponse:
        """
        Execute shell command on a cloud phone.

        Args:
            pad_code: Instance pad code
            command: Shell command to execute
            timeout: Max seconds to wait for result

        Returns:
            VMOSResponse with result field containing command output
        """
        # Start async command
        r = await self._post(
            "/vcpcloud/api/padApi/asyncCmd",
            {"padCodes": [pad_code], "scriptContent": command},
        )
        if r.get("code") != 200:
            return VMOSResponse(
                ok=False, code=r.get("code", 0), message=r.get("msg", ""), raw=r
            )

        # Get task ID
        task_data = r.get("data", [{}])
        task_id = task_data[0].get("taskId", 0) if task_data else 0
        if not task_id:
            return VMOSResponse(ok=False, message="No task ID returned", raw=r)

        # Poll for completion
        start = time.time()
        while time.time() - start < timeout:
            await asyncio.sleep(2)
            d = await self._post(
                "/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [task_id]}
            )
            if d.get("code") == 200 and d.get("data"):
                task = d["data"][0]
                status = task.get("taskStatus", 0)
                if status >= 3:
                    # 3 = completed, 4 = failed
                    if status == 3:
                        return VMOSResponse(
                            ok=True,
                            task_id=task_id,
                            result=task.get("taskResult", ""),
                            raw=d,
                        )
                    else:
                        return VMOSResponse(
                            ok=False,
                            task_id=task_id,
                            message=task.get("errorMsg", "Task failed"),
                            raw=d,
                        )

        return VMOSResponse(ok=False, task_id=task_id, message="Timeout", raw=r)

    # ─── DEVICE MODIFICATION ───────────────────────────────────────────

    async def update_android_props(
        self, pad_code: str, props: dict[str, str]
    ) -> VMOSResponse:
        """
        Update Android system properties on a cloud phone.

        Args:
            pad_code: Instance pad code
            props: Dictionary of property name -> value

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/updatePadAndroidProp",
            {"padCode": pad_code, "props": props},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            status=r.get("code", 0),
            raw=r,
        )

    async def set_gps(
        self,
        pad_code: str,
        lat: float,
        lon: float,
        altitude: float = 10.0,
    ) -> VMOSResponse:
        """
        Set GPS location on a cloud phone.

        Args:
            pad_code: Instance pad code
            lat: Latitude
            lon: Longitude
            altitude: Altitude in meters

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/setGps",
            {
                "padCode": pad_code,
                "latitude": lat,
                "longitude": lon,
                "altitude": altitude,
            },
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def set_wifi(
        self,
        pad_code: str,
        ssid: str,
        mac: str,
        ip: str,
        gateway: str = "192.168.1.1",
    ) -> VMOSResponse:
        """
        Set WiFi configuration on a cloud phone.

        Args:
            pad_code: Instance pad code
            ssid: WiFi network name
            mac: WiFi MAC address
            ip: Device IP address
            gateway: Network gateway

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/setWifi",
            {
                "padCode": pad_code,
                "ssid": ssid,
                "mac": mac,
                "ip": ip,
                "gateway": gateway,
            },
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    # ─── CONTENT INJECTION ─────────────────────────────────────────────

    async def inject_contacts(
        self, pad_code: str, contacts: list[dict[str, str]]
    ) -> VMOSResponse:
        """
        Inject contacts into a cloud phone.

        Args:
            pad_code: Instance pad code
            contacts: List of contact dicts with firstName, lastName, phone

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/addContacts",
            {"padCode": pad_code, "contacts": contacts},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def inject_call_logs(
        self, pad_code: str, calls: list[dict[str, Any]]
    ) -> VMOSResponse:
        """
        Inject call log entries into a cloud phone.

        Args:
            pad_code: Instance pad code
            calls: List of call dicts with number, inputType, duration, timeString

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/addCallLog",
            {"padCode": pad_code, "callLogs": calls},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def send_sms(
        self, pad_code: str, sender: str, message: str
    ) -> VMOSResponse:
        """
        Inject an SMS message into a cloud phone.

        Args:
            pad_code: Instance pad code
            sender: Sender phone number
            message: SMS message body

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/sendSms",
            {"padCode": pad_code, "sender": sender, "message": message},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    # ─── SCREENSHOT / UI CONTROL ───────────────────────────────────────

    async def screenshot(self, pad_code: str) -> VMOSResponse:
        """
        Capture a screenshot from a cloud phone.

        Args:
            pad_code: Instance pad code

        Returns:
            VMOSResponse with data containing screenshot URL or base64
        """
        r = await self._post(
            "/vcpcloud/api/padApi/screenshot", {"padCode": pad_code}
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            data=r.get("data"),
            raw=r,
        )

    async def click(self, pad_code: str, x: int, y: int) -> VMOSResponse:
        """
        Send a click/tap event to a cloud phone.

        Args:
            pad_code: Instance pad code
            x: X coordinate
            y: Y coordinate

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/click",
            {"padCode": pad_code, "x": x, "y": y},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def swipe(
        self,
        pad_code: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: int = 300,
    ) -> VMOSResponse:
        """
        Send a swipe gesture to a cloud phone.

        Args:
            pad_code: Instance pad code
            start_x: Start X coordinate
            start_y: Start Y coordinate
            end_x: End X coordinate
            end_y: End Y coordinate
            duration: Swipe duration in milliseconds

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/swipe",
            {
                "padCode": pad_code,
                "startX": start_x,
                "startY": start_y,
                "endX": end_x,
                "endY": end_y,
                "duration": duration,
            },
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def input_text(self, pad_code: str, text: str) -> VMOSResponse:
        """
        Input text on a cloud phone.

        Args:
            pad_code: Instance pad code
            text: Text to input

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/inputText",
            {"padCode": pad_code, "text": text},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def key_event(self, pad_code: str, key_code: int) -> VMOSResponse:
        """
        Send a key event to a cloud phone.

        Args:
            pad_code: Instance pad code
            key_code: Android key code (e.g., 4=BACK, 3=HOME)

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/keyEvent",
            {"padCode": pad_code, "keyCode": key_code},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    # ─── APP MANAGEMENT ────────────────────────────────────────────────

    async def install_app(self, pad_code: str, apk_url: str) -> VMOSResponse:
        """
        Install an APK from URL on a cloud phone.

        Args:
            pad_code: Instance pad code
            apk_url: URL to APK file

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/installApp",
            {"padCode": pad_code, "apkUrl": apk_url},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            task_id=r.get("data", {}).get("taskId", 0) if isinstance(r.get("data"), dict) else 0,
            raw=r,
        )

    async def uninstall_app(self, pad_code: str, package_name: str) -> VMOSResponse:
        """
        Uninstall an app from a cloud phone.

        Args:
            pad_code: Instance pad code
            package_name: App package name

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/uninstallApp",
            {"padCode": pad_code, "packageName": package_name},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    async def launch_app(self, pad_code: str, package_name: str) -> VMOSResponse:
        """
        Launch an app on a cloud phone.

        Args:
            pad_code: Instance pad code
            package_name: App package name

        Returns:
            VMOSResponse indicating success/failure
        """
        r = await self._post(
            "/vcpcloud/api/padApi/launchApp",
            {"padCode": pad_code, "packageName": package_name},
        )
        return VMOSResponse(
            ok=r.get("code") == 200,
            code=r.get("code", 0),
            message=r.get("msg", ""),
            raw=r,
        )

    # ─── FINGERPRINT MODIFICATION ──────────────────────────────────────

    async def modify_fingerprint(
        self,
        pad_code: str,
        model: str = "samsung_s25_ultra",
        country: str = "US",
        carrier: str = "tmobile",
    ) -> VMOSResponse:
        """
        Apply a complete device fingerprint modification.

        This is a high-level method that sets all properties needed to make
        the device appear as a specific real device model.

        Args:
            pad_code: Instance pad code
            model: Device model preset (e.g., "samsung_s25_ultra", "pixel_9_pro")
            country: Country code for locale/carrier
            carrier: Carrier preset

        Returns:
            VMOSResponse indicating success/failure
        """
        # Device fingerprint presets
        presets = {
            "samsung_s25_ultra": {
                "ro.product.brand": "samsung",
                "ro.product.model": "SM-S928U",
                "ro.product.device": "e3q",
                "ro.product.name": "e3qxeq",
                "ro.product.manufacturer": "samsung",
                "ro.product.board": "sun",
                "ro.build.product": "e3q",
                "ro.hardware": "qcom",
                "ro.build.fingerprint": "samsung/e3qxeq/e3q:15/AP4A.250305.002/S928USQU3AYC6:user/release-keys",
                "ro.build.display.id": "AP4A.250305.002.S928USQU3AYC6",
                "ro.build.version.release": "15",
                "ro.build.version.sdk": "35",
                "ro.build.version.security_patch": "2026-03-05",
                "ro.build.type": "user",
                "ro.build.tags": "release-keys",
            },
            "pixel_9_pro": {
                "ro.product.brand": "google",
                "ro.product.model": "Pixel 9 Pro",
                "ro.product.device": "caiman",
                "ro.product.name": "caiman",
                "ro.product.manufacturer": "Google",
                "ro.product.board": "caiman",
                "ro.build.product": "caiman",
                "ro.hardware": "tensor",
                "ro.build.fingerprint": "google/caiman/caiman:15/AP4A.250305.002/12345678:user/release-keys",
                "ro.build.display.id": "AP4A.250305.002",
                "ro.build.version.release": "15",
                "ro.build.version.sdk": "35",
                "ro.build.version.security_patch": "2026-03-05",
                "ro.build.type": "user",
                "ro.build.tags": "release-keys",
            },
        }

        carrier_props = {
            "tmobile": {
                "gsm.sim.operator.alpha": "T-Mobile",
                "gsm.sim.operator.numeric": "310260",
                "gsm.sim.operator.iso-country": "us",
                "gsm.operator.alpha": "T-Mobile",
                "gsm.operator.numeric": "310260",
                "gsm.network.type": "LTE",
            },
            "verizon": {
                "gsm.sim.operator.alpha": "Verizon",
                "gsm.sim.operator.numeric": "311480",
                "gsm.sim.operator.iso-country": "us",
                "gsm.operator.alpha": "Verizon",
                "gsm.operator.numeric": "311480",
                "gsm.network.type": "LTE",
            },
            "att": {
                "gsm.sim.operator.alpha": "AT&T",
                "gsm.sim.operator.numeric": "310410",
                "gsm.sim.operator.iso-country": "us",
                "gsm.operator.alpha": "AT&T",
                "gsm.operator.numeric": "310410",
                "gsm.network.type": "LTE",
            },
        }

        country_props = {
            "US": {
                "persist.sys.timezone": "America/New_York",
                "persist.sys.locale": "en-US",
                "persist.sys.language": "en",
                "persist.sys.country": "US",
                "ro.boot.wificountrycode": "US",
            },
            "GB": {
                "persist.sys.timezone": "Europe/London",
                "persist.sys.locale": "en-GB",
                "persist.sys.language": "en",
                "persist.sys.country": "GB",
                "ro.boot.wificountrycode": "GB",
            },
        }

        # Build combined props
        props = {}
        if model in presets:
            props.update(presets[model])
        if carrier in carrier_props:
            props.update(carrier_props[carrier])
        if country in country_props:
            props.update(country_props[country])

        if not props:
            return VMOSResponse(
                ok=False, message=f"Unknown model/carrier/country: {model}/{carrier}/{country}"
            )

        return await self.update_android_props(pad_code, props)


# ═══════════════════════════════════════════════════════════════════════
# DEVICE MODIFIER (HIGH-LEVEL ORCHESTRATION)
# ═══════════════════════════════════════════════════════════════════════


class VMOSDeviceModifier:
    """
    High-level device modification orchestrator for VMOS cloud phones.

    Provides complete device identity transformation including:
      - Device fingerprint (model, build, hardware)
      - SIM/carrier identity
      - Network configuration
      - Content injection (contacts, SMS, calls)
      - GPS location
      - App installation
    """

    def __init__(self, bridge: VMOSCloudBridge | None = None):
        """
        Initialize device modifier.

        Args:
            bridge: VMOSCloudBridge instance (created if not provided)
        """
        self.bridge = bridge or VMOSCloudBridge()

    async def full_modification(
        self,
        pad_code: str,
        model: str = "samsung_s25_ultra",
        country: str = "US",
        carrier: str = "tmobile",
        inject_contacts: bool = True,
        inject_sms: bool = True,
        inject_calls: bool = True,
        set_gps: bool = True,
        restart_after: bool = True,
    ) -> dict[str, Any]:
        """
        Perform a complete device modification.

        Args:
            pad_code: Instance pad code
            model: Device model preset
            country: Country code
            carrier: Carrier preset
            inject_contacts: Whether to inject contacts
            inject_sms: Whether to inject SMS messages
            inject_calls: Whether to inject call logs
            set_gps: Whether to set GPS location
            restart_after: Whether to restart device after modification

        Returns:
            Dictionary with results of each modification step
        """
        results = {
            "pad_code": pad_code,
            "model": model,
            "country": country,
            "carrier": carrier,
            "steps": {},
        }

        # 1. Apply fingerprint modification
        logger.info(f"Modifying fingerprint: {model} / {country} / {carrier}")
        r = await self.bridge.modify_fingerprint(pad_code, model, country, carrier)
        results["steps"]["fingerprint"] = r.to_dict()

        # 2. Set GPS location based on country
        if set_gps:
            gps_coords = {
                "US": (40.7128, -74.0060),  # NYC
                "GB": (51.5074, -0.1278),  # London
                "DE": (52.5200, 13.4050),  # Berlin
                "FR": (48.8566, 2.3522),  # Paris
            }
            lat, lon = gps_coords.get(country, (40.7128, -74.0060))
            logger.info(f"Setting GPS: {lat}, {lon}")
            r = await self.bridge.set_gps(pad_code, lat, lon)
            results["steps"]["gps"] = r.to_dict()

        # 3. Inject contacts
        if inject_contacts:
            contacts = [
                {"firstName": "Mom", "phone": "+15165557890"},
                {"firstName": "Dad", "phone": "+15165557891"},
                {"firstName": "Sarah", "lastName": "Johnson", "phone": "+12125551234"},
                {"firstName": "Mike", "lastName": "Chen", "phone": "+12125559876"},
                {"firstName": "CVS Pharmacy", "phone": "+12125558100"},
            ]
            logger.info(f"Injecting {len(contacts)} contacts")
            r = await self.bridge.inject_contacts(pad_code, contacts)
            results["steps"]["contacts"] = r.to_dict()

        # 4. Inject SMS
        if inject_sms:
            messages = [
                ("+15165557890", "Call me when you get a chance sweetie"),
                ("+12125551234", "Hey! Are you free for dinner tonight?"),
                ("+12345", "Your T-Mobile bill is ready. Amount due: $85.00"),
            ]
            sms_results = []
            for sender, msg in messages:
                r = await self.bridge.send_sms(pad_code, sender, msg)
                sms_results.append({"sender": sender, "ok": r.ok})
            results["steps"]["sms"] = {"count": len(messages), "results": sms_results}

        # 5. Inject call logs
        if inject_calls:
            import random
            import time

            base_ts = time.time()
            calls = []
            numbers = ["+15165557890", "+12125551234", "+12125559876"]
            for _ in range(5):
                ts = base_ts - random.randint(3600, 86400 * 7)
                t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                calls.append({
                    "number": random.choice(numbers),
                    "inputType": random.choice([1, 2, 3]),
                    "duration": random.randint(15, 300),
                    "timeString": t,
                })
            logger.info(f"Injecting {len(calls)} call logs")
            r = await self.bridge.inject_call_logs(pad_code, calls)
            results["steps"]["calls"] = r.to_dict()

        # 6. Restart device
        if restart_after:
            logger.info("Restarting device to apply changes")
            r = await self.bridge.restart_instance(pad_code)
            results["steps"]["restart"] = r.to_dict()

        results["success"] = all(
            step.get("ok", False) for step in results["steps"].values() if isinstance(step, dict)
        )
        return results


# ═══════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "CallLogEntry",
    "ContactInfo",
    "SMSEntry",
    "VMOSCloudBridge",
    "VMOSConfig",
    "VMOSDeviceModifier",
    "VMOSInstance",
    "VMOSResponse",
]
