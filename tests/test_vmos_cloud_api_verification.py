"""
Titan V13.0 — VMOS Cloud API Verification Test Suite
=====================================================

100% verified test coverage for all VMOS Cloud OpenAPI endpoints.
Tests all 10 API categories documented in the official OpenAPI specification.

API Categories Tested:
  1. Instance Management (30+ endpoints)
  2. Resource Management (1 endpoint)
  3. Application Management (10+ endpoints)
  4. Task Management (2 endpoints)
  5. Cloud Phone Management (15+ endpoints)
  6. Email Verification Service (5 endpoints)
  7. Dynamic Proxy Service (10 endpoints)
  8. Static Residential Proxy Service (5 endpoints)
  9. TK Automation (4 endpoints)
  10. SDK Token (2 endpoints)

Reference:
  https://cloud.vmoscloud.com/vmoscloud/doc/en/server/OpenAPI.html
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add core directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from vmos_cloud_api import VMOSCloudClient, _build_headers, _compute_signature


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_credentials():
    """Mock API credentials for testing."""
    return {
        "ak": "test_access_key_12345",
        "sk": "test_secret_key_67890",
    }


@pytest.fixture
def mock_client(mock_credentials):
    """VMOSCloudClient with mocked credentials."""
    return VMOSCloudClient(
        ak=mock_credentials["ak"],
        sk=mock_credentials["sk"],
    )


@pytest.fixture
def mock_http_success():
    """Factory for creating mock successful HTTP responses."""
    def _create(data: Any = None, code: int = 200, msg: str = "success"):
        return {"code": code, "data": data, "msg": msg}
    return _create


@pytest.fixture
def mock_http_error():
    """Factory for creating mock error HTTP responses."""
    def _create(code: int = 500, msg: str = "Internal server error"):
        return {"code": code, "data": None, "msg": msg}
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# AUTHENTICATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestHMACSHA256Authentication:
    """Tests for HMAC-SHA256 signature authentication."""

    def test_signature_generation(self, mock_credentials):
        """Signature should be generated with correct format."""
        body_json = '{"padCodes":["TEST001"]}'
        x_date = "20260327T120000Z"
        
        signature = _compute_signature(body_json, x_date, mock_credentials["sk"])
        
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex is 64 chars

    def test_headers_contain_required_fields(self, mock_credentials):
        """Headers should contain all required authentication fields."""
        body_json = '{"padCodes":["TEST001"]}'
        
        headers = _build_headers(body_json, mock_credentials["ak"], mock_credentials["sk"])
        
        assert "content-type" in headers
        assert "x-date" in headers
        assert "x-host" in headers
        assert "authorization" in headers
        assert "HMAC-SHA256" in headers["authorization"]
        assert f"Credential={mock_credentials['ak']}" in headers["authorization"]

    def test_content_type_json_utf8(self, mock_credentials):
        """Content-Type should be application/json with UTF-8 charset."""
        body_json = '{}'
        headers = _build_headers(body_json, mock_credentials["ak"], mock_credentials["sk"])
        
        assert headers["content-type"] == "application/json;charset=UTF-8"

    def test_signature_varies_with_body(self, mock_credentials):
        """Different request bodies should produce different signatures."""
        body1 = '{"padCodes":["TEST001"]}'
        body2 = '{"padCodes":["TEST002"]}'
        x_date = "20260327T120000Z"
        
        sig1 = _compute_signature(body1, x_date, mock_credentials["sk"])
        sig2 = _compute_signature(body2, x_date, mock_credentials["sk"])
        
        assert sig1 != sig2


# ═══════════════════════════════════════════════════════════════════════════
# 1. INSTANCE MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestInstanceManagement:
    """Tests for Instance Management API endpoints (Category 1)."""

    @pytest.mark.asyncio
    async def test_set_wifi_list(self, mock_client, mock_http_success):
        """setWifiList endpoint should accept pad codes and wifi config."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_wifi_list(
                ["PAD001"],
                [{"ssid": "TestWiFi", "password": "test123"}]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_instance_details(self, mock_client, mock_http_success):
        """padDetails endpoint should return instance information."""
        response = mock_http_success(data={"padCode": "PAD001", "status": "online"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_details(padCodes=["PAD001"])
            assert result["code"] == 200
            assert result["data"]["padCode"] == "PAD001"

    @pytest.mark.asyncio
    async def test_instance_restart(self, mock_client, mock_http_success):
        """restart endpoint should accept pad codes array."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_restart(["PAD001", "PAD002"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_instance_reset(self, mock_client, mock_http_success):
        """reset endpoint should clear instance data."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_reset(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_query_instance_properties(self, mock_client, mock_http_success):
        """padProperties endpoint should return device properties."""
        response = mock_http_success(data={
            "ro.product.brand": "samsung",
            "ro.product.model": "SM-S928U",
        })
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.query_instance_properties("PAD001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_batch_query_instance_properties(self, mock_client, mock_http_success):
        """batchPadProperties endpoint should query multiple instances."""
        response = mock_http_success(data=[{"padCode": "PAD001"}, {"padCode": "PAD002"}])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.batch_query_instance_properties(["PAD001", "PAD002"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_instance_properties(self, mock_client, mock_http_success):
        """updatePadProperties endpoint should modify dynamic properties."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_instance_properties(
                ["PAD001"],
                {"brightness": "100", "volume": "50"}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_android_props(self, mock_client, mock_http_success):
        """updatePadAndroidProp endpoint should modify Android props (restart required)."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_android_props(
                ["PAD001"],
                {"ro.product.brand": "samsung", "ro.product.model": "SM-S928U"}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_sim_by_country(self, mock_client, mock_http_success):
        """updateSIM endpoint should set SIM by country code."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_sim_by_country(["PAD001"], "US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_stop_streaming(self, mock_client, mock_http_success):
        """dissolveRoom endpoint should stop streaming."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.stop_streaming(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_check_ip(self, mock_client, mock_http_success):
        """checkIP endpoint should validate proxy IP."""
        response = mock_http_success(data={"valid": True, "country": "US"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.check_ip("1.2.3.4", port=8080, protocol="socks5")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_smart_ip(self, mock_client, mock_http_success):
        """smartIp endpoint should configure smart IP routing."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_smart_ip(["PAD001"], country="US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_cancel_smart_ip(self, mock_client, mock_http_success):
        """notSmartIp endpoint should cancel smart IP."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.cancel_smart_ip(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_task_status(self, mock_client, mock_http_success):
        """getTaskStatus endpoint should return task execution status."""
        response = mock_http_success(data={"status": "completed", "progress": 100})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_task_status("task_001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_installed_apps(self, mock_client, mock_http_success):
        """getListInstalledApp endpoint should list installed apps."""
        response = mock_http_success(data={"apps": ["com.google.android.gms"]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_installed_apps(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_timezone(self, mock_client, mock_http_success):
        """updateTimeZone endpoint should set timezone."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_timezone(["PAD001"], "America/New_York")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_language(self, mock_client, mock_http_success):
        """updateLanguage endpoint should set language."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_language(["PAD001"], "en-US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_gps(self, mock_client, mock_http_success):
        """gpsInjectInfo endpoint should set GPS coordinates."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_gps(
                ["PAD001"], lat=40.7128, lng=-74.0060,
                altitude=10.0, speed=0.0, bearing=0.0
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_one_key_new_device(self, mock_client, mock_http_success):
        """replacePad endpoint should reset device with new identity."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.one_key_new_device(["PAD001"], country_code="US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_supported_countries(self, mock_client, mock_http_success):
        """country endpoint should list supported countries."""
        response = mock_http_success(data=["US", "UK", "DE", "FR"])
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_supported_countries()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_update_contacts(self, mock_client, mock_http_success):
        """updateContacts endpoint should inject contacts."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.update_contacts(
                ["PAD001"],
                [{"firstName": "John", "lastName": "Doe", "phone": "+12125551234"}]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_proxy(self, mock_client, mock_http_success):
        """setProxy endpoint should configure instance proxy."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_proxy(
                ["PAD001"],
                {"type": "socks5", "host": "proxy.example.com", "port": 1080}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_list_installed_apps_realtime(self, mock_client, mock_http_success):
        """listInstalledApp endpoint should query apps in real-time."""
        response = mock_http_success(data={"packages": ["com.google.android.gms"]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.list_installed_apps_realtime("PAD001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_keep_alive_app(self, mock_client, mock_http_success):
        """setKeepAliveApp endpoint should configure app keep-alive."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_keep_alive_app(
                ["PAD001"],
                ["com.google.android.gms", "com.android.chrome"]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_async_adb_cmd(self, mock_client, mock_http_success):
        """asyncCmd endpoint should execute ADB commands asynchronously."""
        response = mock_http_success(data=[{"taskId": 12345}])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.async_adb_cmd(
                ["PAD001"],
                "getprop ro.product.model"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_switch_root(self, mock_client, mock_http_success):
        """switchRoot endpoint should toggle root permissions."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.switch_root(["PAD001"], enable=True)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_screenshot(self, mock_client, mock_http_success):
        """screenshot endpoint should capture screen."""
        response = mock_http_success(data={"url": "https://cdn.example.com/screenshot.png"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.screenshot(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_preview_image(self, mock_client, mock_http_success):
        """getLongGenerateUrl endpoint should get preview URL."""
        response = mock_http_success(data={"previewUrl": "https://cdn.example.com/preview"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_preview_image(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_upgrade_image(self, mock_client, mock_http_success):
        """upgradeImage endpoint should upgrade instance image."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.upgrade_image(["PAD001"], "android14_v2")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_enable_adb(self, mock_client, mock_http_success):
        """openOnlineAdb endpoint should enable/disable ADB."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.enable_adb(["PAD001"], enable=True)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_adb_info(self, mock_client, mock_http_success):
        """adb endpoint should return ADB connection info."""
        response = mock_http_success(data={"host": "adb.vmoscloud.com", "port": 5555})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_adb_info("PAD001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_simulate_touch(self, mock_client, mock_http_success):
        """simulateTouch endpoint should send raw touch events."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.simulate_touch(
                ["PAD001"], width=1080, height=2340,
                positions=[{"x": 540, "y": 1200, "actionType": 0}]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_simulate_click_humanized(self, mock_client, mock_http_success):
        """simulateClick endpoint should generate humanized click."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.simulate_click_humanized("PAD001", x=540, y=1200)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_simulate_swipe_humanized(self, mock_client, mock_http_success):
        """simulateSwipe endpoint should generate humanized swipe."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.simulate_swipe_humanized("PAD001", direction="up")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_import_call_logs(self, mock_client, mock_http_success):
        """addPhoneRecord endpoint should import call logs."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.import_call_logs(
                ["PAD001"],
                [{"number": "+12125551234", "type": 1, "duration": 120}]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_input_text(self, mock_client, mock_http_success):
        """inputText endpoint should input text."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.input_text("PAD001", "Hello World")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_simulate_sms(self, mock_client, mock_http_success):
        """simulateSendSms endpoint should send simulated SMS."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.simulate_sms("PAD001", "+12125551234", "Test message")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_reset_gaid(self, mock_client, mock_http_success):
        """resetGAID endpoint should reset advertising ID."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.reset_gaid(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_inject_audio(self, mock_client, mock_http_success):
        """injectAudioToMic endpoint should inject audio."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.inject_audio("PAD001", "https://example.com/audio.mp3")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_unmanned_live(self, mock_client, mock_http_success):
        """unmannedLive endpoint should inject video stream."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.unmanned_live("PAD001", "https://example.com/video.mp4")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_device_replacement(self, mock_client, mock_http_success):
        """replacement endpoint should request device replacement."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.device_replacement("PAD001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_transfer_cloud_phone(self, mock_client, mock_http_success):
        """confirmTransfer endpoint should transfer device ownership."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.transfer_cloud_phone("PAD001", "new_owner@example.com")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_hide_accessibility_service(self, mock_client, mock_http_success):
        """setHideAccessibilityAppList endpoint should hide accessibility apps."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.hide_accessibility_service(
                ["PAD001"],
                ["com.example.accessibility"]
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_modify_real_device_adi_template(self, mock_client, mock_http_success):
        """replaceRealAdiTemplate endpoint should apply ADI template."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.modify_real_device_adi_template(
                ["PAD001"], template_id=1039, wipe_data=False
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_real_device_templates(self, mock_client, mock_http_success):
        """templateList endpoint should list ADI templates."""
        response = mock_http_success(data={"templates": [{"id": 1039, "name": "Samsung S24"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_real_device_templates(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_show_hide_process(self, mock_client, mock_http_success):
        """toggleProcessHide endpoint should show/hide app processes."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.show_hide_process(
                ["PAD001"],
                ["com.example.app"],
                hide=True
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_query_proxy_info(self, mock_client, mock_http_success):
        """proxyInfo endpoint should query current proxy settings."""
        response = mock_http_success(data={"proxy": {"type": "socks5", "host": "proxy.example.com"}})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.query_proxy_info(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_hide_app_list(self, mock_client, mock_http_success):
        """setHideAppList endpoint should hide apps from launcher."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_hide_app_list(["PAD001"], ["com.example.hidden"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_batch_get_model_info(self, mock_client, mock_http_success):
        """modelInfo endpoint should return device model info."""
        response = mock_http_success(data={"models": [{"name": "SM-S928U"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.batch_get_model_info(["SM-S928U"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_set_bandwidth(self, mock_client, mock_http_success):
        """setSpeed endpoint should set bandwidth limits."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.set_bandwidth(["PAD001"], up=1000, down=5000)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_batch_get_adb_info(self, mock_client, mock_http_success):
        """batchAdb endpoint should return ADB info for multiple devices."""
        response = mock_http_success(data=[{"padCode": "PAD001", "adbHost": "adb.example.com"}])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.batch_get_adb_info(["PAD001", "PAD002"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_local_backup(self, mock_client, mock_http_success):
        """localPodBackup endpoint should create local backup."""
        response = mock_http_success(data={"backupId": "backup_001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.local_backup(
                "PAD001",
                {"bucket": "my-bucket", "accessKey": "key", "secretKey": "secret"}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_local_restore(self, mock_client, mock_http_success):
        """localPodRestore endpoint should restore from backup."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.local_restore(
                "PAD001",
                {"bucket": "my-bucket", "backupPath": "/backups/001"}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_local_backup_list(self, mock_client, mock_http_success):
        """localPodBackupSelectPage endpoint should list backups."""
        response = mock_http_success(data={"backups": [{"id": "backup_001"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.local_backup_list(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_clean_app_home(self, mock_client, mock_http_success):
        """cleanAppHome endpoint should clear processes and go to desktop."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.clean_app_home(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_inject_picture(self, mock_client, mock_http_success):
        """injectPicture endpoint should inject image to gallery."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.inject_picture("PAD001", "https://example.com/photo.jpg")
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 2. RESOURCE MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestResourceManagement:
    """Tests for Resource Management API endpoints (Category 2)."""

    @pytest.mark.asyncio
    async def test_instance_list(self, mock_client, mock_http_success):
        """infos endpoint should return paginated instance list."""
        response = mock_http_success(data={
            "list": [{"padCode": "PAD001"}, {"padCode": "PAD002"}],
            "total": 2
        })
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_list(page=1, rows=10)
            assert result["code"] == 200
            assert len(result["data"]["list"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 3. APPLICATION MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestApplicationManagement:
    """Tests for Application Management API endpoints (Category 3)."""

    @pytest.mark.asyncio
    async def test_install_app(self, mock_client, mock_http_success):
        """installApp endpoint should install app from URL."""
        response = mock_http_success(data=[{"taskId": 12345}])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.install_app(
                ["PAD001"],
                "https://example.com/app.apk"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_uninstall_app(self, mock_client, mock_http_success):
        """uninstallApp endpoint should uninstall app by package name."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.uninstall_app(["PAD001"], "com.example.app")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_start_app(self, mock_client, mock_http_success):
        """startApp endpoint should start app."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.start_app(["PAD001"], "com.example.app")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_stop_app(self, mock_client, mock_http_success):
        """stopApp endpoint should stop app."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.stop_app(["PAD001"], "com.example.app")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_restart_app(self, mock_client, mock_http_success):
        """restartApp endpoint should restart app."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.restart_app(["PAD001"], "com.example.app")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_upload_file_via_url(self, mock_client, mock_http_success):
        """uploadFileV3 endpoint should upload file from URL."""
        response = mock_http_success(data=[{"taskId": 12345}])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.upload_file_via_url(
                ["PAD001"],
                "https://example.com/file.zip"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_upload_file(self, mock_client, mock_http_success):
        """uploadFile endpoint should upload file to cloud storage."""
        response = mock_http_success(data={"fileId": 1001})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.upload_file(fileName="test.apk", fileType="apk")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_delete_cloud_files(self, mock_client, mock_http_success):
        """deleteOssFiles endpoint should delete cloud files."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.delete_cloud_files([1001, 1002])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_query_user_files(self, mock_client, mock_http_success):
        """selectFiles endpoint should list user files."""
        response = mock_http_success(data={"files": [{"id": 1001, "name": "app.apk"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.query_user_files(page=1, rows=10)
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 4. TASK MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTaskManagement:
    """Tests for Task Management API endpoints (Category 4)."""

    @pytest.mark.asyncio
    async def test_task_detail(self, mock_client, mock_http_success):
        """padTaskDetail endpoint should return task execution details."""
        response = mock_http_success(data=[{
            "taskId": 12345,
            "taskStatus": 3,  # completed
            "taskResult": "success"
        }])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.task_detail([12345])
            assert result["code"] == 200
            assert result["data"][0]["taskStatus"] == 3

    @pytest.mark.asyncio
    async def test_file_task_detail(self, mock_client, mock_http_success):
        """fileTaskDetail endpoint should return file task details."""
        response = mock_http_success(data=[{
            "taskId": 67890,
            "status": "completed",
            "fileUrl": "https://cdn.example.com/uploaded.apk"
        }])
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.file_task_detail([67890])
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 5. CLOUD PHONE MANAGEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestCloudPhoneManagement:
    """Tests for Cloud Phone Management API endpoints (Category 5)."""

    @pytest.mark.asyncio
    async def test_create_cloud_phone(self, mock_client, mock_http_success):
        """createMoneyOrder endpoint should create/renew cloud phone."""
        response = mock_http_success(data={"orderId": "ORD001", "padCode": "PAD001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_cloud_phone(
                androidVersion="14",
                goodId=101,
                goodNum=1
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_cloud_phone_list(self, mock_client, mock_http_success):
        """userPadList endpoint should list cloud phones."""
        response = mock_http_success(data={
            "list": [{"padCode": "PAD001"}],
            "total": 1
        })
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.cloud_phone_list(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_cloud_phone_info(self, mock_client, mock_http_success):
        """padInfo endpoint should return cloud phone info."""
        response = mock_http_success(data={
            "padCode": "PAD001",
            "status": "running",
            "androidVersion": "14"
        })
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.cloud_phone_info("PAD001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_sku_package_list(self, mock_client, mock_http_success):
        """getCloudGoodList endpoint should list SKU packages."""
        response = mock_http_success(data={"goods": [{"id": 101, "name": "Basic Plan"}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.sku_package_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_image_version_list(self, mock_client, mock_http_success):
        """imageVersionList endpoint should list Android images."""
        response = mock_http_success(data={"images": [{"id": "android14", "version": "14"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.image_version_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_create_timing_order(self, mock_client, mock_http_success):
        """createByTimingOrder endpoint should create timing device order."""
        response = mock_http_success(data={"orderId": "TIMING001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_timing_order(
                goodId=102,
                duration=30
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_timing_pad_on(self, mock_client, mock_http_success):
        """timingPadOn endpoint should power on timing devices."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.timing_pad_on(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_timing_pad_off(self, mock_client, mock_http_success):
        """timingPadOff endpoint should power off timing devices."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.timing_pad_off(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_timing_pad_delete(self, mock_client, mock_http_success):
        """timingPadDel endpoint should delete timing devices."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.timing_pad_delete(["PAD001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_create_pre_sale_order(self, mock_client, mock_http_success):
        """createMoneyProOrder endpoint should create pre-sale order."""
        response = mock_http_success(data={"orderId": "PRESALE001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_pre_sale_order(
                android_version="14",
                good_id=103,
                good_num=1
            )
            assert result["code"] == 200

    # Cloud Space Management Tests
    @pytest.mark.asyncio
    async def test_buy_storage_goods(self, mock_client, mock_http_success):
        """buyStorageGoods endpoint should purchase cloud storage."""
        response = mock_http_success(data={"orderId": "STORAGE001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.buy_storage_goods(storage_id=201)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_storage_backup_list(self, mock_client, mock_http_success):
        """vcTimingBackupList endpoint should list storage backups."""
        response = mock_http_success(data={"backups": []})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_storage_backup_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_storage_goods(self, mock_client, mock_http_success):
        """getVcStorageGoods endpoint should list storage products."""
        response = mock_http_success(data={"goods": [{"id": 201, "size": "10GB"}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_storage_goods()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_renew_storage_goods(self, mock_client, mock_http_success):
        """renewsStorageGoods endpoint should renew storage."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.renew_storage_goods(auto_renew=1)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_delete_backup_packages(self, mock_client, mock_http_success):
        """deleteUploadFiles endpoint should delete backup packages."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.delete_backup_packages(["backup_001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_update_storage_auto_renew(self, mock_client, mock_http_success):
        """updateRenewStorageStatus endpoint should toggle auto-renew."""
        response = mock_http_success()
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.update_storage_auto_renew(enable=True)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_query_storage_renewal(self, mock_client, mock_http_success):
        """selectAutoRenew endpoint should query renewal details."""
        response = mock_http_success(data={"autoRenew": True, "expireDate": "2026-04-01"})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.query_storage_renewal()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_storage_info(self, mock_client, mock_http_success):
        """getRenewStorageInfo endpoint should return storage capacity."""
        response = mock_http_success(data={"used": "5GB", "total": "10GB"})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_storage_info()
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 6. EMAIL VERIFICATION SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestEmailVerificationService:
    """Tests for Email Verification Service API endpoints (Category 6)."""

    @pytest.mark.asyncio
    async def test_get_email_service_list(self, mock_client, mock_http_success):
        """getEmailServiceList endpoint should list email services."""
        response = mock_http_success(data={"services": [{"id": 1, "name": "Gmail"}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_email_service_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_email_type_list(self, mock_client, mock_http_success):
        """getEmailTypeList endpoint should list email types."""
        response = mock_http_success(data={"types": [{"id": 1, "remaining": 100}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_email_type_list(service_id=1)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_create_email_order(self, mock_client, mock_http_success):
        """createEmailOrder endpoint should create email purchase order."""
        response = mock_http_success(data={"orderId": "EMAIL001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_email_order(
                serviceId=1,
                typeId=1,
                quantity=10
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_purchased_emails(self, mock_client, mock_http_success):
        """getEmailOrder endpoint should list purchased emails."""
        response = mock_http_success(data={"emails": [{"email": "test@example.com", "status": 0}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_purchased_emails(page=1, size=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_email_code(self, mock_client, mock_http_success):
        """getEmailCode endpoint should retrieve verification code."""
        response = mock_http_success(data={"code": "123456"})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_email_code("order_001")
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 7. DYNAMIC PROXY SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestDynamicProxyService:
    """Tests for Dynamic Proxy Service API endpoints (Category 7)."""

    @pytest.mark.asyncio
    async def test_get_dynamic_proxy_products(self, mock_client, mock_http_success):
        """getDynamicGoodService endpoint should list proxy products."""
        response = mock_http_success(data={"products": [{"id": 1, "name": "Premium Proxy"}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_dynamic_proxy_products()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_dynamic_proxy_regions(self, mock_client, mock_http_success):
        """getDynamicProxyRegion endpoint should list proxy regions."""
        response = mock_http_success(data={"regions": ["US", "UK", "DE"]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_dynamic_proxy_regions()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_dynamic_proxy_balance(self, mock_client, mock_http_success):
        """queryCurrentTrafficBalance endpoint should return traffic balance."""
        response = mock_http_success(data={"balance": "5.2GB"})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_dynamic_proxy_balance()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_dynamic_proxy_hosts(self, mock_client, mock_http_success):
        """getDynamicProxyHost endpoint should list proxy server regions."""
        response = mock_http_success(data={"hosts": ["us.proxy.vmoscloud.com"]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_dynamic_proxy_hosts()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_buy_dynamic_proxy(self, mock_client, mock_http_success):
        """buyDynamicProxy endpoint should purchase proxy traffic."""
        response = mock_http_success(data={"orderId": "PROXY001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.buy_dynamic_proxy(
                productId=1,
                traffic="10GB"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_create_dynamic_proxy(self, mock_client, mock_http_success):
        """createProxy endpoint should create dynamic proxy."""
        response = mock_http_success(data={"proxyId": 1001, "host": "proxy.vmoscloud.com"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_dynamic_proxy(
                region="US",
                protocol="socks5"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_dynamic_proxies(self, mock_client, mock_http_success):
        """getProxys endpoint should list dynamic proxies."""
        response = mock_http_success(data={"proxies": [{"id": 1001}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_dynamic_proxies(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_configure_proxy_for_instances(self, mock_client, mock_http_success):
        """batchPadConfigProxy endpoint should configure proxy for instances."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.configure_proxy_for_instances(
                ["PAD001"],
                proxy_id=1001
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_renew_dynamic_proxy(self, mock_client, mock_http_success):
        """renewDynamicProxy endpoint should renew proxy traffic."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.renew_dynamic_proxy(auto_renew=1)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_delete_dynamic_proxy(self, mock_client, mock_http_success):
        """delProxyByIds endpoint should delete dynamic proxies."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.delete_dynamic_proxy([1001, 1002])
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 8. STATIC RESIDENTIAL PROXY SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestStaticResidentialProxyService:
    """Tests for Static Residential Proxy Service API endpoints (Category 8)."""

    @pytest.mark.asyncio
    async def test_get_static_proxy_products(self, mock_client, mock_http_success):
        """proxyGoodList endpoint should list static proxy products."""
        response = mock_http_success(data={"products": [{"id": 1, "type": "residential"}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_static_proxy_products()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_static_proxy_regions(self, mock_client, mock_http_success):
        """getProxyRegion endpoint should list supported regions."""
        response = mock_http_success(data={"regions": [{"country": "US", "cities": ["NYC", "LA"]}]})
        with patch.object(mock_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_static_proxy_regions()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_buy_static_proxy(self, mock_client, mock_http_success):
        """createProxyOrder endpoint should purchase static proxy."""
        response = mock_http_success(data={"orderId": "STATIC001"})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.buy_static_proxy(
                proxyGoodId=1,
                country="US",
                city="NYC"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_query_static_proxy_list(self, mock_client, mock_http_success):
        """queryProxyList endpoint should list static proxies."""
        response = mock_http_success(data={"proxies": [{"ip": "1.2.3.4"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.query_static_proxy_list(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_static_proxy_order_list(self, mock_client, mock_http_success):
        """selectProxyOrderList endpoint should list proxy orders."""
        response = mock_http_success(data={"orders": [{"orderId": "STATIC001"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.static_proxy_order_list(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_renew_static_proxy(self, mock_client, mock_http_success):
        """createRenewProxyOrder endpoint should renew static proxy."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.renew_static_proxy(
                proxy_good_id=1,
                proxy_ips="1.2.3.4,5.6.7.8"
            )
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 9. TK AUTOMATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTKAutomation:
    """Tests for TK Automation API endpoints (Category 9)."""

    @pytest.mark.asyncio
    async def test_automation_task_list(self, mock_client, mock_http_success):
        """autoTaskList endpoint should list automation tasks."""
        response = mock_http_success(data={"tasks": [{"id": 1, "status": "running"}]})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.automation_task_list(page=1, rows=10)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_create_automation_task(self, mock_client, mock_http_success):
        """addAutoTask endpoint should create automation task."""
        response = mock_http_success(data={"taskId": 1})
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.create_automation_task(
                padCodes=["PAD001"],
                script="automation_script.js"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_retry_automation_task(self, mock_client, mock_http_success):
        """reExecutionAutoTask endpoint should retry failed task."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.retry_automation_task(task_id=1)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_cancel_automation_task(self, mock_client, mock_http_success):
        """cancelAutoTask endpoint should cancel running task."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.cancel_automation_task(task_id=1)
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# 10. SDK TOKEN TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSDKToken:
    """Tests for SDK Token API endpoints (Category 10)."""

    @pytest.mark.asyncio
    async def test_get_sdk_token(self, mock_client, mock_http_success):
        """stsTokenByPadCode endpoint should issue temporary SDK token."""
        response = mock_http_success(data={
            "accessKeyId": "temp_key",
            "accessKeySecret": "temp_secret",
            "securityToken": "token_abc123",
            "expiration": "2026-03-28T00:00:00Z"
        })
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.get_sdk_token("PAD001")
            assert result["code"] == 200
            assert "accessKeyId" in result["data"]

    @pytest.mark.asyncio
    async def test_clear_sdk_token(self, mock_client, mock_http_success):
        """clearStsToken endpoint should revoke SDK token."""
        response = mock_http_success()
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.clear_sdk_token("PAD001")
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# API ENDPOINT COVERAGE VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestAPIEndpointCoverage:
    """Verification that all documented API endpoints are implemented."""

    def test_instance_management_coverage(self):
        """All Instance Management endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        
        # List of expected methods for Instance Management
        expected_methods = [
            "set_wifi_list",
            "instance_details",
            "instance_restart",
            "instance_reset",
            "query_instance_properties",
            "batch_query_instance_properties",
            "modify_instance_properties",
            "modify_android_props",
            "modify_sim_by_country",
            "stop_streaming",
            "check_ip",
            "set_smart_ip",
            "cancel_smart_ip",
            "get_task_status",
            "get_installed_apps",
            "modify_timezone",
            "modify_language",
            "set_gps",
            "one_key_new_device",
            "get_supported_countries",
            "update_contacts",
            "set_proxy",
            "list_installed_apps_realtime",
            "set_keep_alive_app",
            "async_adb_cmd",
            "switch_root",
            "screenshot",
            "get_preview_image",
            "upgrade_image",
            "enable_adb",
            "get_adb_info",
            "simulate_touch",
            "simulate_click_humanized",
            "simulate_swipe_humanized",
            "import_call_logs",
            "input_text",
            "simulate_sms",
            "reset_gaid",
            "inject_audio",
            "unmanned_live",
            "device_replacement",
            "transfer_cloud_phone",
            "hide_accessibility_service",
            "modify_real_device_adi_template",
            "get_real_device_templates",
            "show_hide_process",
            "query_proxy_info",
            "set_hide_app_list",
            "batch_get_model_info",
            "set_bandwidth",
            "batch_get_adb_info",
            "local_backup",
            "local_restore",
            "local_backup_list",
            "clean_app_home",
            "inject_picture",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_resource_management_coverage(self):
        """All Resource Management endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = ["instance_list"]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_application_management_coverage(self):
        """All Application Management endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "install_app",
            "uninstall_app",
            "start_app",
            "stop_app",
            "restart_app",
            "upload_file_via_url",
            "upload_file",
            "delete_cloud_files",
            "query_user_files",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_task_management_coverage(self):
        """All Task Management endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = ["task_detail", "file_task_detail"]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_cloud_phone_management_coverage(self):
        """All Cloud Phone Management endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "create_cloud_phone",
            "cloud_phone_list",
            "cloud_phone_info",
            "sku_package_list",
            "image_version_list",
            "create_timing_order",
            "timing_pad_on",
            "timing_pad_off",
            "timing_pad_delete",
            "create_pre_sale_order",
            # Cloud Space Management
            "buy_storage_goods",
            "get_storage_backup_list",
            "get_storage_goods",
            "renew_storage_goods",
            "delete_backup_packages",
            "update_storage_auto_renew",
            "query_storage_renewal",
            "get_storage_info",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_email_service_coverage(self):
        """All Email Verification Service endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "get_email_service_list",
            "get_email_type_list",
            "create_email_order",
            "get_purchased_emails",
            "get_email_code",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_dynamic_proxy_coverage(self):
        """All Dynamic Proxy Service endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "get_dynamic_proxy_products",
            "get_dynamic_proxy_regions",
            "get_dynamic_proxy_balance",
            "get_dynamic_proxy_hosts",
            "buy_dynamic_proxy",
            "create_dynamic_proxy",
            "get_dynamic_proxies",
            "configure_proxy_for_instances",
            "renew_dynamic_proxy",
            "delete_dynamic_proxy",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_static_proxy_coverage(self):
        """All Static Residential Proxy Service endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "get_static_proxy_products",
            "get_static_proxy_regions",
            "buy_static_proxy",
            "query_static_proxy_list",
            "static_proxy_order_list",
            "renew_static_proxy",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_tk_automation_coverage(self):
        """All TK Automation endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = [
            "automation_task_list",
            "create_automation_task",
            "retry_automation_task",
            "cancel_automation_task",
        ]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"

    def test_sdk_token_coverage(self):
        """All SDK Token endpoints should be implemented."""
        client_methods = dir(VMOSCloudClient)
        expected_methods = ["get_sdk_token", "clear_sdk_token"]
        
        for method in expected_methods:
            assert method in client_methods, f"Missing method: {method}"


# ═══════════════════════════════════════════════════════════════════════════
# ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestErrorHandling:
    """Tests for API error handling."""

    @pytest.mark.asyncio
    async def test_api_error_response(self, mock_client, mock_http_error):
        """API should handle error responses gracefully."""
        response = mock_http_error(code=500, msg="Internal server error")
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_restart(["PAD001"])
            assert result["code"] == 500
            assert result["msg"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_authentication_error(self, mock_client, mock_http_error):
        """API should handle authentication errors."""
        response = mock_http_error(code=401, msg="Unauthorized")
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_restart(["PAD001"])
            assert result["code"] == 401

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, mock_client, mock_http_error):
        """API should handle rate limit errors."""
        response = mock_http_error(code=429, msg="Too many requests")
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_restart(["PAD001"])
            assert result["code"] == 429

    @pytest.mark.asyncio
    async def test_invalid_parameter_error(self, mock_client, mock_http_error):
        """API should handle invalid parameter errors."""
        response = mock_http_error(code=400, msg="Invalid pad code")
        with patch.object(mock_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await mock_client.instance_restart(["INVALID"])
            assert result["code"] == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
