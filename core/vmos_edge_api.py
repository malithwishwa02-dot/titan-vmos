"""
VMOS Edge API Client — Self-hosted VMOS Edge instance control.

This module provides two clients for managing self-hosted VMOS Edge instances:

1. VMOSEdgeContainerClient - Host-level management (Container API on port 18182)
   - Instance lifecycle (create, run, stop, reboot, reset, delete)
   - Batch operations on db_ids
   - App distribution and file management
   - Host system queries

2. VMOSEdgeControlClient - Android-level control (Control API on port 18185)
   - UI interaction (click, swipe, input)
   - Screenshot and observation
   - App management (install, start, stop)
   - Shell commands

Reference:
  - Container API: https://github.com/vmos-dev/vmos-edge-skills/tree/main/vmos-edge-container-api
  - Control API: https://github.com/vmos-dev/vmos-edge-skills/tree/main/vmos-edge-control-api
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Default configuration
_DEFAULT_CONTAINER_PORT = 18182
_DEFAULT_CONTROL_PORT = 18185
_DEFAULT_TIMEOUT = 30.0


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class EdgeInstance:
    """Represents a VMOS Edge instance."""
    
    db_id: str = ""
    user_name: str = ""
    status: str = ""
    cloud_ip: str = ""
    adb_port: int = 0
    android_version: str = ""
    resolution: str = ""
    image_repository: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "EdgeInstance":
        """Create instance from Container API response."""
        return cls(
            db_id=data.get("db_id", data.get("id", "")),
            user_name=data.get("user_name", ""),
            status=data.get("status", ""),
            cloud_ip=data.get("cloud_ip", data.get("ip", "")),
            adb_port=data.get("adb_port", 0),
            android_version=data.get("android_version", ""),
            resolution=data.get("resolution", ""),
            image_repository=data.get("image_repository", ""),
            raw_data=data,
        )


@dataclass
class EdgeResponse:
    """Generic response from VMOS Edge API."""
    
    ok: bool = False
    code: int = 0
    msg: str = ""
    data: Any = None
    request_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# VMOS EDGE CONTAINER CLIENT (Port 18182)
# ═══════════════════════════════════════════════════════════════════════════


class VMOSEdgeContainerClient:
    """
    Client for VMOS Edge Container API (host-level management).
    
    Base URL: http://{host_ip}:18182
    
    Capabilities:
      - Host management (heartbeat, systeminfo, images)
      - Instance lifecycle (create, run, stop, reboot, reset, delete)
      - Device control (shell, GPS, timezone, language)
      - App distribution (batch install, upload)
    """
    
    def __init__(
        self,
        host_ip: str | None = None,
        port: int | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        """
        Initialize Container API client.
        
        Args:
            host_ip: Host machine IP (default: 127.0.0.1 or VMOS_EDGE_HOST)
            port: Container API port (default: 18182)
            timeout: Request timeout in seconds
        """
        self.host = host_ip or os.getenv("VMOS_EDGE_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("VMOS_EDGE_CONTAINER_PORT", str(_DEFAULT_CONTAINER_PORT)))
        self.base_url = f"http://{self.host}:{self.port}"
        self.timeout = timeout
    
    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send HTTP request to Container API."""
        url = f"{self.base_url}{path}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if method == "GET":
                    resp = await client.get(url, params=params)
                elif method == "POST":
                    resp = await client.post(url, json=data or {})
                else:
                    resp = await client.request(method, url, json=data or {})
                
                resp.raise_for_status()
                result = resp.json()
                return result
                
            except httpx.HTTPStatusError as e:
                log.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                return {"code": e.response.status_code, "msg": str(e)}
            except Exception as e:
                log.error(f"Request error: {e}")
                return {"code": -1, "msg": str(e)}
    
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._request("GET", path, params=params)
    
    async def _post(self, path: str, data: dict[str, Any] | None = None) -> dict:
        return await self._request("POST", path, data=data)
    
    # ─── HOST MANAGEMENT ──────────────────────────────────────────────────
    
    async def heartbeat(self) -> dict:
        """Check host, Docker, and ping status."""
        return await self._get("/v1/heartbeat")
    
    async def systeminfo(self) -> dict:
        """Get host CPU, memory, disk, and swap info."""
        return await self._get("/v1/systeminfo")
    
    async def hardware_config(self) -> dict:
        """Get host hardware configuration."""
        return await self._get("/v1/get_hardware_cfg")
    
    async def net_info(self) -> dict:
        """Get host network information."""
        return await self._get("/v1/net_info")
    
    async def image_list(self) -> dict:
        """Get available Android images."""
        return await self._get("/v1/get_img_list")
    
    async def prune_images(self) -> dict:
        """Clean up unused images."""
        return await self._get("/v1/prune_images")
    
    async def adi_list(self) -> dict:
        """Get ADI template list."""
        return await self._get("/v1/get_adi_list")
    
    async def swap_enable(self, enable: bool = True) -> dict:
        """Enable or disable swap."""
        return await self._get(f"/v1/swap/{1 if enable else 0}")
    
    async def gms_start(self) -> dict:
        """Start GMS for all instances."""
        return await self._get("/container_api/v1/gms_start")
    
    async def gms_stop(self) -> dict:
        """Stop GMS for all instances."""
        return await self._get("/container_api/v1/gms_stop")
    
    # ─── INSTANCE LIST & DETAILS ──────────────────────────────────────────
    
    async def get_instances(self) -> list[EdgeInstance]:
        """Get list of all instances."""
        # Try POST first, fall back to GET
        result = await self._post("/container_api/v1/get_db", {})
        if result.get("code") != 200:
            result = await self._get("/container_api/v1/get_db")
        
        instances = []
        for item in result.get("data", []):
            instances.append(EdgeInstance.from_api_response(item))
        return instances
    
    async def list_names(self) -> dict:
        """Query all instance IDs, user names, and ADB info."""
        return await self._get("/container_api/v1/list_names")
    
    async def get_instance_detail(self, db_id: str) -> EdgeInstance | None:
        """Get details for a specific instance."""
        result = await self._get(f"/container_api/v1/get_android_detail/{db_id}")
        if result.get("code") != 200:
            return None
        data = result.get("data", {})
        return EdgeInstance.from_api_response(data) if data else None
    
    async def get_screenshot(self, db_id: str) -> dict:
        """Get instance screenshot."""
        return await self._get(f"/container_api/v1/screenshots/{db_id}")
    
    async def get_adb_start(self, db_id: str) -> dict:
        """Get ADB connection command."""
        return await self._get(f"/container_api/v1/adb_start/{db_id}")
    
    async def sync_status(self) -> dict:
        """Synchronize instance status."""
        return await self._get("/container_api/v1/sync_status")
    
    async def rom_status(self, db_id: str) -> dict:
        """Check if ROM is ready."""
        return await self._get(f"/container_api/v1/rom_status/{db_id}")
    
    async def clone_status(self) -> dict:
        """Check clone task status."""
        return await self._get("/container_api/v1/clone_status")
    
    # ─── INSTANCE LIFECYCLE ───────────────────────────────────────────────
    
    async def create_instance(
        self,
        user_name: str,
        bool_start: bool = False,
        image_repository: str | None = None,
        adi_id: int | None = None,
        resolution: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        country: str | None = None,
        count: int = 1,
        **kwargs,
    ) -> dict:
        """
        Create new instance(s).
        
        Args:
            user_name: Required display name
            bool_start: Auto-start after creation
            image_repository: Android image name
            adi_id: ADI template ID
            resolution: Screen resolution
            locale: System locale
            timezone: System timezone
            country: Country code
            count: Number of instances to create
        """
        body = {"user_name": user_name, "bool_start": bool_start, "count": count}
        
        if image_repository:
            body["image_repository"] = image_repository
        if adi_id is not None:
            body["adiID"] = adi_id
        if resolution:
            body["resolution"] = resolution
        if locale:
            body["locale"] = locale
        if timezone:
            body["timezone"] = timezone
        if country:
            body["country"] = country
        
        body.update(kwargs)
        return await self._post("/container_api/v1/create", body)
    
    async def run_instances(self, db_ids: list[str]) -> dict:
        """Start instances."""
        return await self._post("/container_api/v1/run", {"db_ids": db_ids})
    
    async def stop_instances(self, db_ids: list[str]) -> dict:
        """Stop instances."""
        return await self._post("/container_api/v1/stop", {"db_ids": db_ids})
    
    async def reboot_instances(self, db_ids: list[str]) -> dict:
        """Reboot instances."""
        return await self._post("/container_api/v1/reboot", {"db_ids": db_ids})
    
    async def reset_instances(self, db_ids: list[str]) -> dict:
        """Reset instances (factory reset)."""
        return await self._post("/container_api/v1/reset", {"db_ids": db_ids})
    
    async def delete_instances(self, db_ids: list[str]) -> dict:
        """Delete instances."""
        return await self._post("/container_api/v1/delete", {"db_ids": db_ids})
    
    async def clone_instance(self, db_id: str, **kwargs) -> dict:
        """Clone an instance."""
        return await self._post("/container_api/v1/clone", {"db_id": db_id, **kwargs})
    
    async def rename_instance(self, db_id: str, new_user_name: str) -> dict:
        """Rename instance display name."""
        return await self._get(f"/container_api/v1/rename/{db_id}/{new_user_name}")
    
    async def upgrade_image(self, db_ids: list[str], image_repository: str) -> dict:
        """Upgrade instances to new image."""
        return await self._post("/container_api/v1/upgrade_image", {
            "db_ids": db_ids,
            "image_repository": image_repository,
        })
    
    async def replace_devinfo(self, db_ids: list[str], user_prop: dict | None = None) -> dict:
        """One-key new device — reset device identity."""
        body: dict[str, Any] = {"db_ids": db_ids}
        if user_prop:
            body["userProp"] = user_prop
        return await self._post("/container_api/v1/replace_devinfo", body)
    
    async def update_user_prop(self, db_ids: list[str], user_prop: dict) -> dict:
        """Update instance user properties."""
        return await self._post("/container_api/v1/update_user_prop", {
            "db_ids": db_ids,
            "user_prop": user_prop,
        })
    
    async def set_ip(self, db_ids: list[str], start_ip: str, **kwargs) -> dict:
        """Set macvlan IP for instances."""
        return await self._post("/container_api/v1/set_ip", {
            "db_ids": db_ids,
            "macvlan_start_ip": start_ip,
            **kwargs,
        })
    
    # ─── DEVICE CONTROL ───────────────────────────────────────────────────
    
    async def shell(self, db_id: str, command: str) -> dict:
        """Execute ADB shell command on instance."""
        return await self._post(f"/android_api/v1/shell/{db_id}", {"command": command})
    
    async def gps_inject(self, db_id: str, lat: float, lng: float) -> dict:
        """Inject GPS location."""
        return await self._post(f"/android_api/v1/gps_inject/{db_id}", {
            "latitude": lat,
            "longitude": lng,
        })
    
    async def timezone_set(self, db_id: str, timezone: str) -> dict:
        """Set timezone."""
        return await self._post(f"/android_api/v1/timezone_set/{db_id}", {
            "timezone": timezone,
        })
    
    async def country_set(self, db_id: str, country: str) -> dict:
        """Set country code."""
        return await self._post(f"/android_api/v1/country_set/{db_id}", {
            "country": country,
        })
    
    async def language_set(self, db_id: str, language: str) -> dict:
        """Set language."""
        return await self._post(f"/android_api/v1/language_set/{db_id}", {
            "language": language,
        })
    
    async def get_timezone_locale(self, db_id: str) -> dict:
        """Get timezone, country, and language settings."""
        return await self._get(f"/android_api/v1/get_timezone_locale/{db_id}")
    
    async def ip_geo(self, db_id: str) -> dict:
        """Get current GPS coordinates."""
        return await self._get(f"/android_api/v1/ip_geo/{db_id}")
    
    async def stop_front_app(self, db_id: str) -> dict:
        """Stop foreground app."""
        return await self._get(f"/android_api/v1/stop_front_app/{db_id}")
    
    async def video_inject(self, db_id: str, video_url: str) -> dict:
        """Enable video injection."""
        return await self._post(f"/android_api/v1/video_inject/{db_id}", {
            "video_url": video_url,
        })
    
    async def video_inject_off(self, db_id: str) -> dict:
        """Disable video injection."""
        return await self._get(f"/android_api/v1/video_inject_off/{db_id}")
    
    # ─── APPLICATION MANAGEMENT ───────────────────────────────────────────
    
    async def app_list(self, db_id: str) -> dict:
        """Get installed apps."""
        return await self._get(f"/android_api/v1/app_get/{db_id}")
    
    async def app_start(self, db_ids: list[str], package_name: str) -> dict:
        """Batch start app."""
        return await self._post("/android_api/v1/app_start", {
            "db_ids": db_ids,
            "app": package_name,
        })
    
    async def app_stop(self, db_ids: list[str], package_name: str) -> dict:
        """Batch stop app."""
        return await self._post("/android_api/v1/app_stop", {
            "db_ids": db_ids,
            "app": package_name,
        })
    
    async def install_apk_batch(self, db_ids: list[str], apk_url: str) -> dict:
        """Batch install APK from URL."""
        return await self._post("/android_api/v1/install_apk_from_url_batch", {
            "url": apk_url,
            "db_ids": ",".join(db_ids),  # comma-separated
        })
    
    async def upload_file_batch(self, db_ids: list[str], file_url: str, target_path: str) -> dict:
        """Batch upload file from URL."""
        return await self._post("/android_api/v1/upload_file_from_url_batch", {
            "url": file_url,
            "db_ids": ",".join(db_ids),
            "target_path": target_path,
        })


# ═══════════════════════════════════════════════════════════════════════════
# VMOS EDGE CONTROL CLIENT (Port 18185)
# ═══════════════════════════════════════════════════════════════════════════


class VMOSEdgeControlClient:
    """
    Client for VMOS Edge Android Control API (device-level control).
    
    Supports two routing modes:
      1. Host routing: http://{host_ip}:18182/android_api/v2/{db_id}/{path}
      2. Cloud IP routing: http://{cloud_ip}:18185/api/{path}
    
    Capabilities:
      - Observation (screenshot, dump_compact, display info)
      - UI interaction (click, swipe, text input, keyevent)
      - App management (start, stop, install, uninstall)
      - Shell commands and system settings
    """
    
    def __init__(
        self,
        cloud_ip: str | None = None,
        host_ip: str | None = None,
        db_id: str | None = None,
        port: int | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        """
        Initialize Control API client.
        
        For host routing (recommended when Container API available):
            VMOSEdgeControlClient(host_ip="192.168.1.100", db_id="EDGE123")
        
        For direct cloud IP routing:
            VMOSEdgeControlClient(cloud_ip="192.168.1.50")
        
        Args:
            cloud_ip: Cloud device IP (for direct routing)
            host_ip: Host machine IP (for host routing via db_id)
            db_id: Instance db_id (required for host routing)
            port: Override port (default: 18185 for cloud_ip, 18182 for host_ip)
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        
        if host_ip and db_id:
            # Host routing via Container API
            self.port = port or _DEFAULT_CONTAINER_PORT
            self.base_url = f"http://{host_ip}:{self.port}/android_api/v2/{db_id}"
            self.routing_mode = "host"
        elif cloud_ip:
            # Direct cloud IP routing
            self.port = port or _DEFAULT_CONTROL_PORT
            self.base_url = f"http://{cloud_ip}:{self.port}/api"
            self.routing_mode = "cloud"
        else:
            # Default to localhost
            host = os.getenv("VMOS_EDGE_CLOUD_IP", "127.0.0.1")
            self.port = port or _DEFAULT_CONTROL_PORT
            self.base_url = f"http://{host}:{self.port}/api"
            self.routing_mode = "cloud"
    
    async def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send HTTP request to Control API."""
        url = f"{self.base_url}{path}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if method == "GET":
                    resp = await client.get(url, params=params)
                elif method == "POST":
                    resp = await client.post(url, json=data or {})
                else:
                    resp = await client.request(method, url, json=data or {})
                
                resp.raise_for_status()
                result = resp.json()
                return result
                
            except httpx.HTTPStatusError as e:
                log.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                return {"code": e.response.status_code, "msg": str(e)}
            except Exception as e:
                log.error(f"Request error: {e}")
                return {"code": -1, "msg": str(e)}
    
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._request("GET", path, params=params)
    
    async def _post(self, path: str, data: dict[str, Any] | None = None) -> dict:
        return await self._request("POST", path, data=data)
    
    # ─── CAPABILITY DISCOVERY ─────────────────────────────────────────────
    
    async def version_info(self) -> dict:
        """Get API version and supported capabilities."""
        return await self._get("/base/version_info")
    
    async def list_action(self, paths: list[str] | None = None, detail: bool = False) -> dict:
        """Query available API actions."""
        body: dict[str, Any] = {"detail": detail}
        if paths:
            body["paths"] = paths
        return await self._post("/base/list_action", body)
    
    async def sleep(self, duration_ms: int) -> dict:
        """Pause execution for specified milliseconds."""
        return await self._post("/base/sleep", {"duration": duration_ms})
    
    # ─── OBSERVATION ──────────────────────────────────────────────────────
    
    async def display_info(self) -> dict:
        """Get screen dimensions and density."""
        return await self._get("/display/info")
    
    async def screenshot_format(self) -> bytes:
        """Get screenshot in image format."""
        url = f"{self.base_url}/screenshot/format"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    
    async def screenshot_raw(self) -> bytes:
        """Get raw screenshot bytes."""
        url = f"{self.base_url}/screenshot/raw"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    
    async def screenshot_data_url(self) -> dict:
        """Get screenshot as data URL."""
        return await self._get("/screenshot/data_url")
    
    async def dump_compact(self) -> dict:
        """Get compact UI hierarchy dump."""
        return await self._get("/accessibility/dump_compact")
    
    async def top_activity(self) -> dict:
        """Get current foreground activity."""
        return await self._get("/activity/top_activity")
    
    # ─── UI INTERACTION ───────────────────────────────────────────────────
    
    async def click(self, x: int, y: int) -> dict:
        """Click at coordinates."""
        return await self._post("/input/click", {"x": x, "y": y})
    
    async def multi_click(self, x: int, y: int, times: int = 2, interval: int = 100) -> dict:
        """Multiple clicks at coordinates."""
        return await self._post("/input/multi_click", {
            "x": x,
            "y": y,
            "times": times,
            "interval": interval,
        })
    
    async def input_text(self, text: str) -> dict:
        """Input text at current focus."""
        return await self._post("/input/text", {"text": text})
    
    async def keyevent(self, key_code: int | None = None, key_codes: list[int] | None = None) -> dict:
        """Send key event(s)."""
        body = {}
        if key_code is not None:
            body["key_code"] = key_code
        if key_codes:
            body["key_codes"] = key_codes
        return await self._post("/input/keyevent", body)
    
    async def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: int = 300,
        up_delay: int = 0,
    ) -> dict:
        """Straight line swipe."""
        return await self._post("/input/swipe", {
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "duration": duration,
            "up_delay": up_delay,
        })
    
    async def scroll_bezier(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: int = 300,
        up_delay: int = 0,
        clear_fling: bool = False,
    ) -> dict:
        """Bezier curve swipe (more natural)."""
        return await self._post("/input/scroll_bezier", {
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "duration": duration,
            "up_delay": up_delay,
            "clear_fling": clear_fling,
        })
    
    # ─── ACCESSIBILITY NODE ───────────────────────────────────────────────
    
    async def node_action(
        self,
        selector: dict,
        action: str | None = None,
        action_params: dict | None = None,
        wait_timeout: int = 0,
        wait_interval: int = 500,
    ) -> dict:
        """
        Find UI node and optionally perform action.
        
        Selector fields:
          - xpath, text, content_desc, resource_id, class_name
          - package, clickable, enabled, scrollable, index
        
        Actions:
          - click, long_click, set_text, clear_text
          - scroll_forward, scroll_backward, scroll_up, scroll_down
          - focus, copy, paste, cut
        """
        body: dict[str, Any] = {
            "selector": selector,
            "wait_timeout": wait_timeout,
            "wait_interval": wait_interval,
        }
        if action:
            body["action"] = action
        if action_params:
            body["action_params"] = action_params
        return await self._post("/accessibility/node", body)
    
    # ─── APP MANAGEMENT ───────────────────────────────────────────────────
    
    async def start_app(self, package_name: str) -> dict:
        """Start app by package name."""
        return await self._post("/activity/start", {"package_name": package_name})
    
    async def launch_app(self, package_name: str, grant_all_permissions: bool = False) -> dict:
        """Start app with optional permission grant."""
        return await self._post("/activity/launch_app", {
            "package_name": package_name,
            "grant_all_permissions": grant_all_permissions,
        })
    
    async def start_activity(
        self,
        package_name: str,
        class_name: str | None = None,
        action: str | None = None,
        data: str | None = None,
        extras: dict | None = None,
    ) -> dict:
        """Start specific activity."""
        body: dict[str, Any] = {"package_name": package_name}
        if class_name:
            body["class_name"] = class_name
        if action:
            body["action"] = action
        if data:
            body["data"] = data
        if extras:
            body["extras"] = extras
        return await self._post("/activity/start_activity", body)
    
    async def stop_app(self, package_name: str) -> dict:
        """Stop app."""
        return await self._post("/activity/stop", {"package_name": package_name})
    
    async def install_app(self, apk_path: str) -> dict:
        """Install app from local path."""
        return await self._post("/package/install_sync", {"path": apk_path})
    
    async def install_app_uri(self, uri: str) -> dict:
        """Install app from URI."""
        return await self._post("/package/install_uri_sync", {"uri": uri})
    
    async def uninstall_app(self, package_name: str, keep_data: bool = False) -> dict:
        """Uninstall app."""
        return await self._post("/package/uninstall", {
            "package_name": package_name,
            "keep_data": keep_data,
        })
    
    async def package_list(self, type: str = "user") -> dict:
        """Get installed packages (type: 'user' or 'system')."""
        return await self._get("/package/list", {"type": type})
    
    # ─── SYSTEM & DEVICE ──────────────────────────────────────────────────
    
    async def shell(self, command: str, as_root: bool = False) -> dict:
        """Execute shell command."""
        return await self._post("/system/shell", {
            "command": command,
            "as_root": as_root,
        })
    
    async def settings_get(self, namespace: str, key: str) -> dict:
        """Get Android settings value."""
        return await self._post("/system/settings_get", {
            "namespace": namespace,
            "key": key,
        })
    
    async def settings_put(self, namespace: str, key: str, value: str) -> dict:
        """Set Android settings value."""
        return await self._post("/system/settings_put", {
            "namespace": namespace,
            "key": key,
            "value": value,
        })
    
    async def clipboard_set(self, text: str) -> dict:
        """Set clipboard content."""
        return await self._post("/clipboard/set", {"text": text})
    
    async def clipboard_get(self) -> dict:
        """Get clipboard content."""
        return await self._get("/clipboard/get")
    
    async def clipboard_list(self) -> dict:
        """Get clipboard history."""
        return await self._get("/clipboard/list")
    
    async def clipboard_clear(self) -> dict:
        """Clear clipboard."""
        return await self._post("/clipboard/clear", {})
    
    # ─── GOOGLE SERVICES ──────────────────────────────────────────────────
    
    async def google_set_enabled(self, enabled: bool) -> dict:
        """Enable or disable Google services."""
        return await self._post("/google/set_enabled", {"enabled": enabled})
    
    async def google_get_enabled(self) -> dict:
        """Check if Google services are enabled."""
        return await self._get("/google/get_enabled")
    
    async def google_reset_gaid(self) -> dict:
        """Reset Google Advertising ID."""
        return await self._post("/google/reset_gaid", {})


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════


def get_container_client(host_ip: str | None = None) -> VMOSEdgeContainerClient:
    """Create a Container API client."""
    return VMOSEdgeContainerClient(host_ip=host_ip)


def get_control_client(
    cloud_ip: str | None = None,
    host_ip: str | None = None,
    db_id: str | None = None,
) -> VMOSEdgeControlClient:
    """Create a Control API client."""
    return VMOSEdgeControlClient(cloud_ip=cloud_ip, host_ip=host_ip, db_id=db_id)


async def check_edge_support(host_ip: str = "127.0.0.1") -> bool:
    """
    Check if VMOS Edge Container API is available.
    
    Returns True if the heartbeat endpoint responds successfully.
    """
    client = VMOSEdgeContainerClient(host_ip=host_ip)
    try:
        result = await client.heartbeat()
        return result.get("code") == 200
    except Exception:
        return False


async def check_control_support(cloud_ip: str) -> bool:
    """
    Check if VMOS Edge Control API is available.
    
    Returns True if version_info endpoint responds successfully.
    """
    client = VMOSEdgeControlClient(cloud_ip=cloud_ip)
    try:
        result = await client.version_info()
        return result.get("code") == 200
    except Exception:
        return False
