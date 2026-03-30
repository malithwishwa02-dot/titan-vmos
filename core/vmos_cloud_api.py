"""
VMOS Cloud API Client — HMAC-SHA256 authenticated client for VMOSCloud OpenAPI.

Base URL: https://api.vmoscloud.com
Auth: HMAC-SHA256 signature (AK/SK)
Service: armcloud-paas

Covers all 10 API categories:
  1. Instance Management (restart, reset, properties, ADB, screenshot, touch, etc.)
  2. Resource Management (instance list)
  3. Application Management (install, uninstall, start, stop, upload)
  4. Task Management (task details, file tasks)
  5. Cloud Phone Management (create, list, info, SKU, images)
  6. Email Verification Service
  7. Dynamic Proxy Service
  8. Static Residential Proxy Service
  9. TK Automation
  10. SDK Token
"""

from __future__ import annotations

import binascii
import datetime
import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
_AK = os.getenv("VMOS_CLOUD_AK", "")
_SK = os.getenv("VMOS_CLOUD_SK", "")
_BASE_URL = os.getenv("VMOS_CLOUD_BASE_URL", "https://api.vmoscloud.com")
_HOST = os.getenv("VMOS_CLOUD_HOST", "api.vmoscloud.com")
_SERVICE = "armcloud-paas"
_CONTENT_TYPE = "application/json;charset=UTF-8"
_SIGNED_HEADERS = "content-type;host;x-content-sha256;x-date"
_ALGORITHM = "HMAC-SHA256"

# httpx timeout (seconds)
_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# HMAC-SHA256 Signing
# ---------------------------------------------------------------------------

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _compute_signature(body_json: str, x_date: str, sk: str) -> str:
    """Compute HMAC-SHA256 signature per VMOS Cloud auth spec."""
    x_content_sha256 = _sha256_hex(body_json.encode())
    short_x_date = x_date[:8]

    canonical = (
        f"host:{_HOST}\n"
        f"x-date:{x_date}\n"
        f"content-type:{_CONTENT_TYPE}\n"
        f"signedHeaders:{_SIGNED_HEADERS}\n"
        f"x-content-sha256:{x_content_sha256}"
    )

    credential_scope = f"{short_x_date}/{_SERVICE}/request"
    hash_canonical = _sha256_hex(canonical.encode())

    string_to_sign = (
        f"{_ALGORITHM}\n"
        f"{x_date}\n"
        f"{credential_scope}\n"
        f"{hash_canonical}"
    )

    # Derive signing key: HMAC(HMAC(HMAC(sk, date), service), "request")
    k_date = _hmac_sha256(sk.encode(), short_x_date)
    k_service = hmac.new(k_date, _SERVICE.encode(), hashlib.sha256).digest()
    signing_key = hmac.new(k_service, b"request", hashlib.sha256).digest()

    signature_bytes = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).digest()
    return binascii.hexlify(signature_bytes).decode()


def _build_headers(body_json: str, ak: str, sk: str) -> dict[str, str]:
    """Build signed request headers."""
    x_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    signature = _compute_signature(body_json, x_date, sk)
    return {
        "content-type": _CONTENT_TYPE,
        "x-date": x_date,
        "x-host": _HOST,
        "authorization": (
            f"HMAC-SHA256 Credential={ak}, "
            f"SignedHeaders={_SIGNED_HEADERS}, "
            f"Signature={signature}"
        ),
    }


# ---------------------------------------------------------------------------
# Core HTTP Client
# ---------------------------------------------------------------------------

class VMOSCloudClient:
    """Async client for VMOS Cloud OpenAPI."""

    def __init__(self, ak: str | None = None, sk: str | None = None,
                 base_url: str | None = None):
        self.ak = ak or _AK
        self.sk = sk or _SK
        self.base_url = (base_url or _BASE_URL).rstrip("/")
        if not self.ak or not self.sk:
            raise ValueError("VMOS_CLOUD_AK and VMOS_CLOUD_SK must be set")

    async def _post(self, path: str, data: dict[str, Any] | None = None) -> dict:
        body = data or {}
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = _build_headers(body_json, self.ak, self.sk)
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, content=body_json, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 200:
            log.warning("VMOS API %s returned code=%s msg=%s",
                        path, result.get("code"), result.get("msg"))
        return result

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        body_json = json.dumps(params or {}, separators=(",", ":"), ensure_ascii=False)
        headers = _build_headers(body_json, self.ak, self.sk)
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 200:
            log.warning("VMOS API %s returned code=%s msg=%s",
                        path, result.get("code"), result.get("msg"))
        return result

    # -----------------------------------------------------------------------
    # 1. Instance Management
    # -----------------------------------------------------------------------

    async def set_wifi_list(self, pad_codes: list[str], wifi_json_list: list[dict]) -> dict:
        """Modify WIFI list properties of specified instances."""
        return await self._post("/vcpcloud/api/padApi/setWifiList", {
            "padCodes": pad_codes,
            "wifiJsonList": wifi_json_list,
        })

    async def instance_details(self, **kwargs) -> dict:
        """Query instance details (padCodes, padIps, vmStatus, etc.)."""
        return await self._post("/vcpcloud/api/padApi/padDetails", kwargs)

    async def instance_restart(self, pad_codes: list[str]) -> dict:
        """Restart specified instances."""
        return await self._post("/vcpcloud/api/padApi/restart", {"padCodes": pad_codes})

    async def instance_reset(self, pad_codes: list[str]) -> dict:
        """Reset instances — clears all data."""
        return await self._post("/vcpcloud/api/padApi/reset", {"padCodes": pad_codes})

    async def query_instance_properties(self, pad_code: str) -> dict:
        """Query system/settings properties of an instance."""
        return await self._post("/vcpcloud/api/padApi/padProperties", {"padCode": pad_code})

    async def batch_query_instance_properties(self, pad_codes: list[str]) -> dict:
        """Batch query instance properties."""
        return await self._post("/vcpcloud/api/padApi/batchPadProperties", {"padCodes": pad_codes})

    async def modify_instance_properties(self, pad_codes: list[str], properties: dict) -> dict:
        """Dynamically modify instance properties (no restart needed)."""
        return await self._post("/vcpcloud/api/padApi/updatePadProperties", {
            "padCodes": pad_codes, **properties,
        })

    async def modify_android_props(self, pad_codes: list[str], properties: dict) -> dict:
        """Modify Android modification properties (requires restart)."""
        return await self._post("/vcpcloud/api/padApi/updatePadAndroidProp", {
            "padCode": pad_codes[0], "props": properties,
        })

    async def modify_sim_by_country(self, pad_codes: list[str], country_code: str) -> dict:
        """Modify SIM info based on country code (auto-restart)."""
        return await self._post("/vcpcloud/api/padApi/updateSIM", {
            "padCode": pad_codes[0], "countryCode": country_code,
        })

    async def stop_streaming(self, pad_codes: list[str]) -> dict:
        """Stop streaming for specified instances."""
        return await self._post("/vcpcloud/api/padApi/dissolveRoom", {"padCodes": pad_codes})

    async def check_ip(self, ip: str, port: int | None = None,
                       protocol: str | None = None) -> dict:
        """Smart IP proxy detection."""
        body: dict[str, Any] = {"ip": ip}
        if port:
            body["port"] = port
        if protocol:
            body["protocol"] = protocol
        return await self._post("/vcpcloud/api/padApi/checkIP", body)

    async def set_smart_ip(self, pad_codes: list[str], **kwargs) -> dict:
        """Set smart IP — changes exit IP, SIM, GPS, etc."""
        return await self._post("/vcpcloud/api/padApi/smartIp", {
            "padCodes": pad_codes, **kwargs,
        })

    async def cancel_smart_ip(self, pad_codes: list[str]) -> dict:
        """Cancel smart IP, restore defaults."""
        return await self._post("/vcpcloud/api/padApi/notSmartIp", {"padCodes": pad_codes})

    async def get_task_status(self, task_no: str) -> dict:
        """Query async task execution result."""
        return await self._post("/vcpcloud/api/padApi/getTaskStatus", {"taskId": task_no})

    async def get_installed_apps(self, pad_codes: list[str]) -> dict:
        """Get installed apps for specified instances."""
        return await self._post("/vcpcloud/api/padApi/getListInstalledApp", {"padCodes": pad_codes})

    async def modify_timezone(self, pad_codes: list[str], timezone: str) -> dict:
        """Modify instance timezone."""
        return await self._post("/vcpcloud/api/padApi/updateTimeZone", {
            "padCodes": pad_codes, "timeZone": timezone,
        })

    async def modify_language(self, pad_codes: list[str], language: str) -> dict:
        """Modify instance language."""
        return await self._post("/vcpcloud/api/padApi/updateLanguage", {
            "padCodes": pad_codes, "language": language,
        })

    async def set_gps(self, pad_codes: list[str], lat: float, lng: float,
                      altitude: float | None = None, speed: float | None = None,
                      bearing: float | None = None,
                      horizontal_accuracy: float | None = None) -> dict:
        """Set instance GPS (lat, lng, optional altitude/speed/bearing/accuracy)."""
        body: dict[str, Any] = {"padCodes": pad_codes, "latitude": lat, "longitude": lng}
        if altitude is not None:
            body["altitude"] = altitude
        if speed is not None:
            body["speed"] = speed
        if bearing is not None:
            body["bearing"] = bearing
        if horizontal_accuracy is not None:
            body["horizontalAccuracyMeters"] = horizontal_accuracy
        return await self._post("/vcpcloud/api/padApi/gpsInjectInfo", body)

    async def one_key_new_device(self, pad_codes: list[str],
                                 country_code: str | None = None, **kwargs) -> dict:
        """One-key new device — clear all data and reset Android properties."""
        body: dict[str, Any] = {"padCodes": pad_codes}
        if country_code:
            body["countryCode"] = country_code
        body.update(kwargs)
        return await self._post("/vcpcloud/api/padApi/replacePad", body)

    async def get_supported_countries(self) -> dict:
        """Query one-key new device supported countries."""
        return await self._get("/vcpcloud/api/padApi/country")

    async def update_contacts(self, pad_codes: list[str], contacts: list[dict]) -> dict:
        """Update contacts on instances."""
        return await self._post("/vcpcloud/api/padApi/updateContacts", {
            "padCodes": pad_codes, "info": contacts,
        })

    async def set_proxy(self, pad_codes: list[str], proxy_info: dict) -> dict:
        """Set proxy for specified instances."""
        return await self._post("/vcpcloud/api/padApi/setProxy", {
            "padCodes": pad_codes, **proxy_info,
        })

    async def list_installed_apps_realtime(self, pad_code: str) -> dict:
        """Real-time query installed apps list."""
        return await self._post("/vcpcloud/api/padApi/listInstalledApp", {"padCodes": [pad_code]})

    async def set_keep_alive_app(self, pad_codes: list[str], packages: list[str]) -> dict:
        """Set app keep-alive (Android 13/14/15)."""
        return await self._post("/vcpcloud/api/padApi/setKeepAliveApp", {
            "padCodes": pad_codes, "packageNames": packages,
        })

    async def async_adb_cmd(self, pad_codes: list[str], command: str) -> dict:
        """Async execute ADB command on instances."""
        return await self._post("/vcpcloud/api/padApi/asyncCmd", {
            "padCodes": pad_codes, "scriptContent": command,
        })

    async def switch_root(self, pad_codes: list[str], enable: bool = True) -> dict:
        """Switch root permissions on instances."""
        return await self._post("/vcpcloud/api/padApi/switchRoot", {
            "padCodes": pad_codes, "rootStatus": 1 if enable else 0,
        })

    async def screenshot(self, pad_codes: list[str]) -> dict:
        """Take local screenshot of instances."""
        return await self._post("/vcpcloud/api/padApi/screenshot", {"padCodes": pad_codes})

    async def get_preview_image(self, pad_codes: list[str]) -> dict:
        """Get real-time preview image URL."""
        return await self._post("/vcpcloud/api/padApi/getLongGenerateUrl", {"padCodes": pad_codes})

    async def upgrade_image(self, pad_codes: list[str], image_id: str) -> dict:
        """Batch instance image upgrade."""
        return await self._post("/vcpcloud/api/padApi/upgradeImage", {
            "padCodes": pad_codes, "imageId": image_id,
        })

    async def enable_adb(self, pad_codes: list[str], enable: bool = True) -> dict:
        """Enable or disable ADB for instances."""
        return await self._post("/vcpcloud/api/padApi/openOnlineAdb", {
            "padCodes": pad_codes, "open": 1 if enable else 0,
        })

    async def get_adb_info(self, pad_code: str, enable: bool = True) -> dict:
        """Get ADB connection information (enables ADB if needed)."""
        return await self._post("/vcpcloud/api/padApi/adb", {
            "padCode": pad_code, "enable": 1 if enable else 0,
        })

    async def simulate_touch(self, pad_codes: list[str], width: int, height: int,
                             positions: list[dict]) -> dict:
        """Simulate raw touch events (actionType: 0-pressed, 1-lifted, 2-touching)."""
        return await self._post("/vcpcloud/api/padApi/simulateTouch", {
            "padCodes": pad_codes, "width": width, "height": height,
            "positions": positions,
        })

    async def simulate_click_humanized(self, pad_code: str, x: int, y: int) -> dict:
        """Generate humanized click trajectory at coordinates."""
        return await self._post("/vcpcloud/api/openApi/simulateClick", {
            "padCode": pad_code, "x": x, "y": y,
        })

    async def simulate_swipe_humanized(self, pad_code: str,
                                       direction: str | None = None, **kwargs) -> dict:
        """Generate humanized swipe trajectory."""
        body: dict[str, Any] = {"padCode": pad_code}
        if direction:
            body["direction"] = direction
        body.update(kwargs)
        return await self._post("/vcpcloud/api/openApi/simulateSwipe", body)

    async def import_call_logs(self, pad_codes: list[str], records: list[dict]) -> dict:
        """Import call log data into cloud phone."""
        return await self._post("/vcpcloud/api/padApi/addPhoneRecord", {
            "padCodes": pad_codes, "callRecords": records,
        })

    async def input_text(self, pad_code: str, text: str) -> dict:
        """Input text into focused input box."""
        return await self._post("/vcpcloud/api/padApi/inputText", {
            "padCode": pad_code, "text": text,
        })

    async def simulate_sms(self, pad_code: str, phone: str, content: str) -> dict:
        """Simulate sending SMS to instance."""
        return await self._post("/vcpcloud/api/padApi/simulateSendSms", {
            "padCode": pad_code, "phone": phone, "content": content,
        })

    async def reset_gaid(self, pad_codes: list[str], reset_gms_type: int = 1) -> dict:
        """Reset advertising ID. reset_gms_type: 1=GAID."""
        return await self._post("/vcpcloud/api/padApi/resetGAID", {
            "padCodes": pad_codes,
            "resetGmsType": reset_gms_type,
        })

    async def inject_audio(self, pad_code: str, audio_url: str) -> dict:
        """Inject audio file to instance microphone."""
        return await self._post("/vcpcloud/api/padApi/injectAudioToMic", {
            "padCode": pad_code, "audioUrl": audio_url,
        })

    async def unmanned_live(self, pad_code: str, video_url: str) -> dict:
        """Instance video injection (unmanned live streaming)."""
        return await self._post("/vcpcloud/api/padApi/unmannedLive", {
            "padCode": pad_code, "videoUrl": video_url,
        })

    async def upload_user_image(self, **kwargs) -> dict:
        """Upload user ROM image."""
        return await self._post("/vcpcloud/api/padApi/addUserRom", kwargs)

    async def device_replacement(self, pad_code: str) -> dict:
        """Device replacement."""
        return await self._post("/vcpcloud/api/padApi/replacement", {"padCode": pad_code})

    async def transfer_cloud_phone(self, pad_code: str, target_account: str) -> dict:
        """Transfer cloud phone to another account."""
        return await self._post("/vcpcloud/api/padApi/confirmTransfer", {
            "padCode": pad_code, "targetAccount": target_account,
        })

    async def hide_accessibility_service(self, pad_codes: list[str],
                                         packages: list[str]) -> dict:
        """Hide accessibility service packages."""
        return await self._post("/vcpcloud/api/padApi/setHideAccessibilityAppList", {
            "padCodes": pad_codes, "appInfos": [{"packageName": p} for p in packages],
        })

    async def modify_real_device_adi_template(self, pad_codes: list[str],
                                              template_id: int,
                                              wipe_data: bool = False) -> dict:
        """Modify cloud real device ADI template."""
        return await self._post("/vcpcloud/api/padApi/replaceRealAdiTemplate", {
            "padCodes": pad_codes, "realPhoneTemplateId": template_id,
            "wipeData": wipe_data,
        })

    async def get_real_device_templates(self, page: int = 1, rows: int = 10) -> dict:
        """Paginated retrieval of real device templates."""
        return await self._post("/vcpcloud/api/padApi/templateList", {
            "page": page, "rows": rows,
        })

    async def show_hide_process(self, pad_codes: list[str],
                                packages: list[str], hide: bool = True) -> dict:
        """Show or hide app process."""
        return await self._post("/vcpcloud/api/padApi/toggleProcessHide", {
            "padCodes": pad_codes, "packageNames": packages,
            "hide": 1 if hide else 0,
        })

    async def query_proxy_info(self, pad_codes: list[str]) -> dict:
        """Query current proxy information for instances."""
        return await self._post("/vcpcloud/api/padApi/proxyInfo", {"padCodes": pad_codes})

    async def set_hide_app_list(self, pad_codes: list[str], packages: list[str]) -> dict:
        """Set app package hide list."""
        return await self._post("/vcpcloud/api/padApi/setHideAppList", {
            "padCodes": pad_codes, "packageNames": packages,
        })

    async def batch_get_model_info(self, model_names: list[str]) -> dict:
        """Batch get device model information."""
        return await self._post("/vcpcloud/api/padApi/modelInfo", {"modelNames": model_names})

    async def set_bandwidth(self, pad_codes: list[str], up: int = 0, down: int = 0) -> dict:
        """Set instance bandwidth. 0=unlimited, -1=block internet."""
        return await self._post("/vcpcloud/api/padApi/setSpeed", {
            "padCodes": pad_codes, "upBandwidth": up, "downBandwidth": down,
        })

    async def batch_get_adb_info(self, pad_codes: list[str]) -> dict:
        """Batch get ADB connection information."""
        return await self._post("/vcpcloud/api/padApi/batchAdb", {"padCodes": pad_codes})

    async def local_backup(self, pad_code: str, oss_config: dict) -> dict:
        """Create local instance backup (S3-compatible OSS config)."""
        return await self._post("/vcpcloud/api/padApi/localPodBackup", {
            "padCode": pad_code, **oss_config,
        })

    async def local_restore(self, pad_code: str, oss_config: dict) -> dict:
        """Restore instance from local backup (S3-compatible OSS config)."""
        return await self._post("/vcpcloud/api/padApi/localPodRestore", {
            "padCode": pad_code, **oss_config,
        })

    async def local_backup_list(self, page: int = 1, rows: int = 10) -> dict:
        """Query local backup list (paginated)."""
        return await self._post("/vcpcloud/api/padApi/localPodBackupSelectPage", {
            "page": page, "rows": rows,
        })

    async def clean_app_home(self, pad_codes: list[str]) -> dict:
        """Clear all processes and return to desktop."""
        return await self._post("/vcpcloud/api/padApi/cleanAppHome", {"padCodes": pad_codes})

    async def inject_picture(self, pad_code: str, image_url: str) -> dict:
        """Inject picture into device camera roll."""
        return await self._post("/vcpcloud/api/padApi/injectPicture", {
            "padCode": pad_code, "imageUrl": image_url,
        })

    # -----------------------------------------------------------------------
    # 2. Resource Management
    # -----------------------------------------------------------------------

    async def instance_list(self, page: int = 1, rows: int = 10, **kwargs) -> dict:
        """Paginated query of all ordered instances."""
        return await self._post("/vcpcloud/api/padApi/infos", {
            "page": page, "rows": rows, **kwargs,
        })

    # -----------------------------------------------------------------------
    # 3. Application Management
    # -----------------------------------------------------------------------

    async def install_app(self, pad_codes: list[str], app_url: str, **kwargs) -> dict:
        """Install app(s) on instance(s) — async operation."""
        return await self._post("/vcpcloud/api/padApi/installApp", {
            "padCodes": pad_codes, "appUrl": app_url, **kwargs,
        })

    async def uninstall_app(self, pad_codes: list[str], package_name: str) -> dict:
        """Uninstall app by package name."""
        return await self._post("/vcpcloud/api/padApi/uninstallApp", {
            "padCodes": pad_codes, "packageName": package_name,
        })

    async def start_app(self, pad_codes: list[str], package_name: str) -> dict:
        """Start app on instances."""
        return await self._post("/vcpcloud/api/padApi/startApp", {
            "padCodes": pad_codes, "packageName": package_name,
        })

    async def stop_app(self, pad_codes: list[str], package_name: str) -> dict:
        """Stop app on instances."""
        return await self._post("/vcpcloud/api/padApi/stopApp", {
            "padCodes": pad_codes, "packageName": package_name,
        })

    async def restart_app(self, pad_codes: list[str], package_name: str) -> dict:
        """Restart app on instances."""
        return await self._post("/vcpcloud/api/padApi/restartApp", {
            "padCodes": pad_codes, "packageName": package_name,
        })

    async def upload_file_via_url(self, pad_codes: list[str], file_url: str,
                                  **kwargs) -> dict:
        """Upload file via URL (with optional auto-install)."""
        return await self._post("/vcpcloud/api/padApi/uploadFileV3", {
            "padCodes": pad_codes, "fileUrl": file_url, **kwargs,
        })

    async def upload_file(self, **kwargs) -> dict:
        """Upload file to cloud storage."""
        return await self._post("/vcpcloud/api/padApi/uploadFile", kwargs)

    async def delete_cloud_files(self, file_ids: list[int]) -> dict:
        """Delete cloud storage files."""
        return await self._post("/vcpcloud/api/padApi/deleteOssFiles", {"fileIds": file_ids})

    async def query_user_files(self, page: int = 1, rows: int = 10) -> dict:
        """Query user file list."""
        return await self._post("/vcpcloud/api/padApi/selectFiles", {
            "page": page, "rows": rows,
        })

    # -----------------------------------------------------------------------
    # 4. Task Management
    # -----------------------------------------------------------------------

    async def task_detail(self, task_ids: list[int]) -> dict:
        """Query instance operation task execution results."""
        return await self._post("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": task_ids})

    async def file_task_detail(self, task_ids: list[int]) -> dict:
        """Query file task execution results."""
        return await self._post("/vcpcloud/api/padApi/fileTaskDetail", {"taskIds": task_ids})

    # -----------------------------------------------------------------------
    # 5. Cloud Phone Management
    # -----------------------------------------------------------------------

    async def create_cloud_phone(self, **kwargs) -> dict:
        """Create or renew a cloud phone instance."""
        return await self._post("/vcpcloud/api/padApi/createMoneyOrder", kwargs)

    async def cloud_phone_list(self, page: int = 1, rows: int = 10, **kwargs) -> dict:
        """List cloud phones."""
        return await self._post("/vcpcloud/api/padApi/userPadList", {
            "page": page, "rows": rows, **kwargs,
        })

    async def cloud_phone_info(self, pad_code: str) -> dict:
        """Query cloud phone information."""
        return await self._post("/vcpcloud/api/padApi/padInfo", {"padCode": pad_code})

    async def sku_package_list(self) -> dict:
        """List SKU packages."""
        return await self._get("/vcpcloud/api/padApi/getCloudGoodList")

    async def image_version_list(self, **kwargs) -> dict:
        """Get available Android image versions."""
        return await self._post("/vcpcloud/api/padApi/imageVersionList", kwargs)

    async def create_timing_order(self, **kwargs) -> dict:
        """Create timing device order."""
        return await self._post("/vcpcloud/api/padApi/createByTimingOrder", kwargs)

    async def timing_pad_on(self, pad_codes: list[str]) -> dict:
        """Power on timing devices."""
        return await self._post("/vcpcloud/api/padApi/timingPadOn", {"padCodes": pad_codes})

    async def timing_pad_off(self, pad_codes: list[str]) -> dict:
        """Power off timing devices."""
        return await self._post("/vcpcloud/api/padApi/timingPadOff", {"padCodes": pad_codes})

    async def timing_pad_delete(self, pad_codes: list[str]) -> dict:
        """Destroy timing devices."""
        return await self._post("/vcpcloud/api/padApi/timingPadDel", {"padCodes": pad_codes})

    async def create_pre_sale_order(self, android_version: str, good_id: int,
                                    good_num: int = 1, auto_renew: bool = False) -> dict:
        """Pre-sale purchase (stock insufficient, 30+ day rental)."""
        return await self._post("/vcpcloud/api/padApi/createMoneyProOrder", {
            "androidVersionName": android_version, "goodId": good_id,
            "goodNum": good_num, "autoRenew": auto_renew,
        })

    # -----------------------------------------------------------------------
    # 5b. Cloud Space Management
    # -----------------------------------------------------------------------

    async def buy_storage_goods(self, storage_id: int, auto_renew: int = 0) -> dict:
        """Purchase cloud space expansion. auto_renew: 0-No, 1-Yes."""
        return await self._post("/vcpcloud/api/padApi/buyStorageGoods", {
            "storageId": storage_id, "autoRenewOrder": auto_renew,
        })

    async def get_storage_backup_list(self) -> dict:
        """List storage resource packages after shutdown backup."""
        return await self._get("/vcpcloud/api/padApi/vcTimingBackupList")

    async def get_storage_goods(self) -> dict:
        """Get cloud space product list."""
        return await self._get("/vcpcloud/api/padApi/getVcStorageGoods")

    async def renew_storage_goods(self, auto_renew: int = 0) -> dict:
        """Aggregate renewal of cloud space products."""
        return await self._post("/vcpcloud/api/padApi/renewsStorageGoods", {
            "autoRenewOrder": auto_renew,
        })

    async def delete_backup_packages(self, backup_ids: list[str]) -> dict:
        """Delete backup resource package data."""
        return await self._post("/vcpcloud/api/padApi/deleteUploadFiles", backup_ids)

    async def update_storage_auto_renew(self, enable: bool = False) -> dict:
        """Toggle cloud space auto-renew."""
        return await self._get("/vcpcloud/api/padApi/updateRenewStorageStatus", {
            "renewStorageStatus": "true" if enable else "false",
        })

    async def query_storage_renewal(self) -> dict:
        """Query cloud space renewal details (expiration, amounts)."""
        return await self._get("/vcpcloud/api/padApi/selectAutoRenew")

    async def get_storage_info(self) -> dict:
        """Get remaining cloud storage capacity."""
        return await self._get("/vcpcloud/api/padApi/getRenewStorageInfo")

    # -----------------------------------------------------------------------
    # 6. Email Verification Service
    # -----------------------------------------------------------------------

    async def get_email_service_list(self) -> dict:
        """Retrieve email service list."""
        return await self._get("/vcpcloud/api/padApi/getEmailServiceList")

    async def get_email_type_list(self, service_id: int | None = None) -> dict:
        """Get email types and remaining inventory."""
        params = {}
        if service_id:
            params["serviceId"] = service_id
        return await self._get("/vcpcloud/api/padApi/getEmailTypeList", params)

    async def create_email_order(self, **kwargs) -> dict:
        """Create email purchase order."""
        return await self._post("/vcpcloud/api/padApi/createEmailOrder", kwargs)

    async def get_purchased_emails(self, page: int = 1, size: int = 10,
                                    service_id: int | None = None,
                                    email: str | None = None,
                                    status: int | None = None) -> dict:
        """Query purchased email list (status: 0-unused, 1-receiving, 2-used, 3-expired)."""
        params: dict[str, Any] = {"page": page, "size": size}
        if service_id is not None:
            params["serviceId"] = service_id
        if email is not None:
            params["email"] = email
        if status is not None:
            params["status"] = status
        return await self._get("/vcpcloud/api/vcEmailService/getEmailOrder", params)

    async def get_email_code(self, order_id: str) -> dict:
        """Refresh get email verification code (use outOrderId from purchased list)."""
        return await self._get("/vcpcloud/api/vcEmailService/getEmailCode", {"orderId": order_id})

    # -----------------------------------------------------------------------
    # 7. Dynamic Proxy Service
    # -----------------------------------------------------------------------

    async def get_dynamic_proxy_products(self) -> dict:
        """Query dynamic proxy product list."""
        return await self._get("/vcpcloud/api/padApi/getDynamicGoodService")

    async def get_dynamic_proxy_regions(self) -> dict:
        """Query dynamic proxy region list."""
        return await self._get("/vcpcloud/api/padApi/getDynamicProxyRegion")

    async def get_dynamic_proxy_balance(self) -> dict:
        """Get current traffic balance."""
        return await self._get("/vcpcloud/api/padApi/queryCurrentTrafficBalance")

    async def get_dynamic_proxy_hosts(self) -> dict:
        """Query supported server regions (continent-level addresses)."""
        return await self._get("/vcpcloud/api/padApi/getDynamicProxyHost")

    async def buy_dynamic_proxy(self, **kwargs) -> dict:
        """Purchase dynamic proxy traffic package."""
        return await self._post("/vcpcloud/api/padApi/buyDynamicProxy", kwargs)

    async def create_dynamic_proxy(self, **kwargs) -> dict:
        """Create dynamic proxy."""
        return await self._post("/vcpcloud/api/padApi/createProxy", kwargs)

    async def get_dynamic_proxies(self, page: int = 1, rows: int = 10) -> dict:
        """Query dynamic proxy list (paginated)."""
        return await self._get("/vcpcloud/api/padApi/getProxys", {
            "page": page, "rows": rows,
        })

    async def configure_proxy_for_instances(self, pad_codes: list[str],
                                            proxy_id: int) -> dict:
        """Configure dynamic proxy for instances."""
        return await self._post("/vcpcloud/api/padApi/batchPadConfigProxy", {
            "padCodes": pad_codes, "proxyId": proxy_id,
        })

    async def renew_dynamic_proxy(self, auto_renew: int = 0) -> dict:
        """Renew dynamic proxy traffic. auto_renew: 0-off, 1-on."""
        return await self._post("/vcpcloud/api/padApi/renewDynamicProxy", {
            "autoRenewOrder": auto_renew,
        })

    async def delete_dynamic_proxy(self, proxy_ids: list[int]) -> dict:
        """Delete dynamic proxies."""
        return await self._post("/vcpcloud/api/padApi/delProxyByIds", {"ids": proxy_ids})

    # -----------------------------------------------------------------------
    # 8. Static Residential Proxy Service
    # -----------------------------------------------------------------------

    async def get_static_proxy_products(self) -> dict:
        """Get static residential product list."""
        return await self._get("/vcpcloud/api/padApi/proxyGoodList")

    async def get_static_proxy_regions(self) -> dict:
        """Get supported countries/cities for static residential proxy."""
        return await self._get("/vcpcloud/api/padApi/getProxyRegion")

    async def buy_static_proxy(self, **kwargs) -> dict:
        """Purchase static residential proxy."""
        return await self._post("/vcpcloud/api/padApi/createProxyOrder", kwargs)

    async def query_static_proxy_list(self, page: int = 1, rows: int = 10) -> dict:
        """Query static residential proxy list."""
        return await self._post("/vcpcloud/api/padApi/queryProxyList", {
            "page": page, "rows": rows,
        })

    async def static_proxy_order_list(self, page: int = 1, rows: int = 10) -> dict:
        """Query static residential proxy order details."""
        return await self._post("/vcpcloud/api/padApi/selectProxyOrderList", {
            "page": page, "rows": rows,
        })

    async def renew_static_proxy(self, proxy_good_id: int, proxy_ips: str,
                                 auto_renew: bool = False) -> dict:
        """Renew static residential proxy by IP addresses (comma-separated)."""
        return await self._post("/vcpcloud/api/padApi/createRenewProxyOrder", {
            "proxyGoodId": proxy_good_id, "proxyIps": proxy_ips,
            "autoRenew": auto_renew,
        })

    # -----------------------------------------------------------------------
    # 9. TK Automation
    # -----------------------------------------------------------------------

    async def automation_task_list(self, page: int = 1, rows: int = 10) -> dict:
        """Query automation task list."""
        return await self._post("/vcpcloud/api/padApi/autoTaskList", {
            "page": page, "rows": rows,
        })

    async def create_automation_task(self, **kwargs) -> dict:
        """Create automation task."""
        return await self._post("/vcpcloud/api/padApi/addAutoTask", kwargs)

    async def retry_automation_task(self, task_id: int) -> dict:
        """Retry an automation task."""
        return await self._post("/vcpcloud/api/padApi/reExecutionAutoTask", {"taskId": task_id})

    async def cancel_automation_task(self, task_id: int) -> dict:
        """Cancel an automation task."""
        return await self._post("/vcpcloud/api/padApi/cancelAutoTask", {"taskId": task_id})

    # -----------------------------------------------------------------------
    # 10. SDK Token
    # -----------------------------------------------------------------------

    async def get_sdk_token(self, pad_code: str) -> dict:
        """Issue temporary SDK token for a cloud phone instance."""
        return await self._post("/vcpcloud/api/padApi/stsTokenByPadCode", {"padCode": pad_code})

    async def clear_sdk_token(self, pad_code: str) -> dict:
        """Clear SDK authorization token."""
        return await self._post("/vcpcloud/api/padApi/clearStsToken", {"padCode": pad_code})


# ---------------------------------------------------------------------------
# Sync convenience wrapper (for use in non-async contexts)
# ---------------------------------------------------------------------------

def get_client(ak: str | None = None, sk: str | None = None) -> VMOSCloudClient:
    """Create a new VMOSCloudClient instance."""
    return VMOSCloudClient(ak=ak, sk=sk)
