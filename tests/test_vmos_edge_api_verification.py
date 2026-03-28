"""
Titan V13.0 — VMOS Edge API Verification Test Suite
====================================================

Tests for VMOS Edge Container and Control APIs (self-hosted instances).

Container API (Port 18182):
  - Host management (heartbeat, systeminfo)
  - Instance lifecycle (create, run, stop, reboot, delete)
  - Device control (shell, GPS, timezone)
  - App distribution

Control API (Port 18185):
  - Observation (screenshot, dump_compact)
  - UI interaction (click, swipe, text)
  - App management (start, stop, install)
  - Shell and system settings

Reference:
  - https://github.com/vmos-dev/vmos-edge-skills
"""

import asyncio
import json
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add core directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from vmos_edge_api import (
    VMOSEdgeContainerClient,
    VMOSEdgeControlClient,
    EdgeInstance,
    get_container_client,
    get_control_client,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def container_client():
    """VMOSEdgeContainerClient for testing."""
    return VMOSEdgeContainerClient(host_ip="192.168.1.100", port=18182)


@pytest.fixture
def control_client_cloud():
    """VMOSEdgeControlClient with cloud_ip routing."""
    return VMOSEdgeControlClient(cloud_ip="192.168.1.50", port=18185)


@pytest.fixture
def control_client_host():
    """VMOSEdgeControlClient with host_ip routing."""
    return VMOSEdgeControlClient(host_ip="192.168.1.100", db_id="EDGE123")


@pytest.fixture
def mock_http_success():
    """Factory for creating mock successful HTTP responses."""
    def _create(data: Any = None, code: int = 200, msg: str = "OK"):
        return {"code": code, "data": data, "msg": msg}
    return _create


@pytest.fixture
def mock_http_error():
    """Factory for creating mock error HTTP responses."""
    def _create(code: int = 500, msg: str = "Internal server error"):
        return {"code": code, "data": None, "msg": msg}
    return _create


# ═══════════════════════════════════════════════════════════════════════════
# EDGE INSTANCE MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestEdgeInstance:
    """Tests for EdgeInstance model."""

    def test_from_api_response(self):
        """EdgeInstance should parse API response correctly."""
        data = {
            "db_id": "EDGE123",
            "user_name": "test-device",
            "status": "running",
            "cloud_ip": "192.168.1.50",
            "adb_port": 5555,
            "android_version": "13",
            "resolution": "1080x1920",
        }
        instance = EdgeInstance.from_api_response(data)
        
        assert instance.db_id == "EDGE123"
        assert instance.user_name == "test-device"
        assert instance.status == "running"
        assert instance.cloud_ip == "192.168.1.50"

    def test_from_api_response_alt_fields(self):
        """EdgeInstance should handle alternative field names."""
        data = {
            "id": "EDGE456",
            "ip": "192.168.1.60",
        }
        instance = EdgeInstance.from_api_response(data)
        
        assert instance.db_id == "EDGE456"
        assert instance.cloud_ip == "192.168.1.60"


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINER CLIENT TESTS - HOST MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestContainerHostManagement:
    """Tests for Container API host management endpoints."""

    @pytest.mark.asyncio
    async def test_heartbeat(self, container_client, mock_http_success):
        """heartbeat endpoint should check host health."""
        response = mock_http_success(data={"docker": "ok", "ping": "ok"})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.heartbeat()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_systeminfo(self, container_client, mock_http_success):
        """systeminfo endpoint should return system stats."""
        response = mock_http_success(data={
            "cpu": 20.5,
            "memory": 65.3,
            "disk": 45.0,
        })
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.systeminfo()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_hardware_config(self, container_client, mock_http_success):
        """get_hardware_cfg endpoint should return hardware info."""
        response = mock_http_success(data={"cpu_cores": 8, "ram_gb": 32})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.hardware_config()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_net_info(self, container_client, mock_http_success):
        """net_info endpoint should return network info."""
        response = mock_http_success(data={"ip": "192.168.1.100"})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.net_info()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_image_list(self, container_client, mock_http_success):
        """get_img_list endpoint should return available images."""
        response = mock_http_success(data=[
            {"name": "vcloud_android13_edge", "size": "5GB"}
        ])
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.image_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_prune_images(self, container_client, mock_http_success):
        """prune_images endpoint should clean unused images."""
        response = mock_http_success()
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.prune_images()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_adi_list(self, container_client, mock_http_success):
        """get_adi_list endpoint should return ADI templates."""
        response = mock_http_success(data=[{"id": 1039, "name": "Samsung S24"}])
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.adi_list()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_swap_enable(self, container_client, mock_http_success):
        """swap endpoint should enable/disable swap."""
        response = mock_http_success()
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.swap_enable(True)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_gms_start(self, container_client, mock_http_success):
        """gms_start endpoint should start GMS."""
        response = mock_http_success()
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.gms_start()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_gms_stop(self, container_client, mock_http_success):
        """gms_stop endpoint should stop GMS."""
        response = mock_http_success()
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.gms_stop()
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINER CLIENT TESTS - INSTANCE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestContainerInstanceManagement:
    """Tests for Container API instance management endpoints."""

    @pytest.mark.asyncio
    async def test_get_instances(self, container_client, mock_http_success):
        """get_db endpoint should return instance list."""
        response = mock_http_success(data=[
            {"db_id": "EDGE001", "status": "running"},
            {"db_id": "EDGE002", "status": "stopped"},
        ])
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            instances = await container_client.get_instances()
            assert len(instances) == 2
            assert instances[0].db_id == "EDGE001"

    @pytest.mark.asyncio
    async def test_list_names(self, container_client, mock_http_success):
        """list_names endpoint should return names and IDs."""
        response = mock_http_success(data=[
            {"db_id": "EDGE001", "user_name": "device-1"}
        ])
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.list_names()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_instance_detail(self, container_client, mock_http_success):
        """get_android_detail endpoint should return instance info."""
        response = mock_http_success(data={
            "db_id": "EDGE001",
            "status": "running",
            "android_version": "13",
        })
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            instance = await container_client.get_instance_detail("EDGE001")
            assert instance is not None
            assert instance.db_id == "EDGE001"

    @pytest.mark.asyncio
    async def test_get_screenshot(self, container_client, mock_http_success):
        """screenshots endpoint should return screenshot URL."""
        response = mock_http_success(data={"url": "http://example.com/screenshot.png"})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.get_screenshot("EDGE001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_get_adb_start(self, container_client, mock_http_success):
        """adb_start endpoint should return ADB command."""
        response = mock_http_success(data={"adb": "adb connect 192.168.1.50:5555"})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.get_adb_start("EDGE001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_rom_status(self, container_client, mock_http_success):
        """rom_status endpoint should check ROM readiness."""
        response = mock_http_success(data={"ready": True})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.rom_status("EDGE001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_clone_status(self, container_client, mock_http_success):
        """clone_status endpoint should check clone task."""
        response = mock_http_success(data={"status": "completed"})
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.clone_status()
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINER CLIENT TESTS - INSTANCE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestContainerInstanceLifecycle:
    """Tests for Container API instance lifecycle endpoints."""

    @pytest.mark.asyncio
    async def test_create_instance(self, container_client, mock_http_success):
        """create endpoint should create new instance."""
        response = mock_http_success(data={"db_id": "EDGE_NEW"})
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.create_instance(
                user_name="test-device",
                bool_start=True,
                image_repository="vcloud_android13",
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_run_instances(self, container_client, mock_http_success):
        """run endpoint should start instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.run_instances(["EDGE001", "EDGE002"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_stop_instances(self, container_client, mock_http_success):
        """stop endpoint should stop instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.stop_instances(["EDGE001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_reboot_instances(self, container_client, mock_http_success):
        """reboot endpoint should reboot instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.reboot_instances(["EDGE001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_reset_instances(self, container_client, mock_http_success):
        """reset endpoint should factory reset instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.reset_instances(["EDGE001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_delete_instances(self, container_client, mock_http_success):
        """delete endpoint should delete instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.delete_instances(["EDGE001"])
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_clone_instance(self, container_client, mock_http_success):
        """clone endpoint should clone instance."""
        response = mock_http_success(data={"new_db_id": "EDGE_CLONE"})
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.clone_instance("EDGE001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_rename_instance(self, container_client, mock_http_success):
        """rename endpoint should rename instance."""
        response = mock_http_success()
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.rename_instance("EDGE001", "new-name")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_upgrade_image(self, container_client, mock_http_success):
        """upgrade_image endpoint should upgrade instances."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.upgrade_image(
                ["EDGE001"],
                "vcloud_android14"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_replace_devinfo(self, container_client, mock_http_success):
        """replace_devinfo endpoint should reset device identity."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.replace_devinfo(["EDGE001"])
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINER CLIENT TESTS - DEVICE CONTROL
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestContainerDeviceControl:
    """Tests for Container API device control endpoints."""

    @pytest.mark.asyncio
    async def test_shell(self, container_client, mock_http_success):
        """shell endpoint should execute command."""
        response = mock_http_success(data={"output": "SM-S928U"})
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.shell("EDGE001", "getprop ro.product.model")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_gps_inject(self, container_client, mock_http_success):
        """gps_inject endpoint should set GPS coordinates."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.gps_inject("EDGE001", 40.7128, -74.0060)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_timezone_set(self, container_client, mock_http_success):
        """timezone_set endpoint should set timezone."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.timezone_set("EDGE001", "America/New_York")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_country_set(self, container_client, mock_http_success):
        """country_set endpoint should set country."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.country_set("EDGE001", "US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_language_set(self, container_client, mock_http_success):
        """language_set endpoint should set language."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.language_set("EDGE001", "en-US")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_app_list(self, container_client, mock_http_success):
        """app_get endpoint should list installed apps."""
        response = mock_http_success(data=["com.google.android.gms"])
        with patch.object(container_client, "_get", new_callable=AsyncMock, return_value=response):
            result = await container_client.app_list("EDGE001")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_app_start(self, container_client, mock_http_success):
        """app_start endpoint should start app."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.app_start(["EDGE001"], "com.android.chrome")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_install_apk_batch(self, container_client, mock_http_success):
        """install_apk_from_url_batch endpoint should install APK."""
        response = mock_http_success()
        with patch.object(container_client, "_post", new_callable=AsyncMock, return_value=response):
            result = await container_client.install_apk_batch(
                ["EDGE001"],
                "https://example.com/app.apk"
            )
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL CLIENT TESTS - CAPABILITY DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestControlCapabilityDiscovery:
    """Tests for Control API capability discovery endpoints."""

    @pytest.mark.asyncio
    async def test_version_info(self, control_client_cloud, mock_http_success):
        """version_info endpoint should return API version."""
        response = mock_http_success(data={
            "version_name": "2.0.0",
            "version_code": 200,
            "supported_list": ["screenshot", "click", "swipe"],
        })
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.version_info()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_list_action(self, control_client_cloud, mock_http_success):
        """list_action endpoint should list available actions."""
        response = mock_http_success(data={
            "actions": ["/input/click", "/input/swipe", "/screenshot/format"]
        })
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.list_action(detail=False)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_sleep(self, control_client_cloud, mock_http_success):
        """sleep endpoint should pause execution."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.sleep(1000)
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL CLIENT TESTS - OBSERVATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestControlObservation:
    """Tests for Control API observation endpoints."""

    @pytest.mark.asyncio
    async def test_display_info(self, control_client_cloud, mock_http_success):
        """display/info endpoint should return screen info."""
        response = mock_http_success(data={
            "width": 1080,
            "height": 2340,
            "density": 440,
        })
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.display_info()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_dump_compact(self, control_client_cloud, mock_http_success):
        """dump_compact endpoint should return UI hierarchy."""
        response = mock_http_success(data={"nodes": []})
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.dump_compact()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_top_activity(self, control_client_cloud, mock_http_success):
        """top_activity endpoint should return foreground activity."""
        response = mock_http_success(data={
            "package": "com.android.launcher",
            "activity": "MainActivity",
        })
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.top_activity()
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL CLIENT TESTS - UI INTERACTION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestControlUIInteraction:
    """Tests for Control API UI interaction endpoints."""

    @pytest.mark.asyncio
    async def test_click(self, control_client_cloud, mock_http_success):
        """click endpoint should tap at coordinates."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.click(540, 1200)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_multi_click(self, control_client_cloud, mock_http_success):
        """multi_click endpoint should perform multiple taps."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.multi_click(540, 1200, times=2)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_input_text(self, control_client_cloud, mock_http_success):
        """text endpoint should input text."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.input_text("Hello World")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_keyevent(self, control_client_cloud, mock_http_success):
        """keyevent endpoint should send key event."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.keyevent(key_code=66)  # Enter
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_swipe(self, control_client_cloud, mock_http_success):
        """swipe endpoint should perform swipe gesture."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.swipe(540, 1500, 540, 500, duration=300)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_scroll_bezier(self, control_client_cloud, mock_http_success):
        """scroll_bezier endpoint should perform natural scroll."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.scroll_bezier(540, 1500, 540, 500)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_node_action_find(self, control_client_cloud, mock_http_success):
        """node endpoint should find UI elements."""
        response = mock_http_success(data={"found": True, "node": {"text": "Settings"}})
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.node_action(
                selector={"text": "Settings", "clickable": True}
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_node_action_click(self, control_client_cloud, mock_http_success):
        """node endpoint should click UI element."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.node_action(
                selector={"resource_id": "com.example:id/button"},
                action="click",
                wait_timeout=5000,
            )
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL CLIENT TESTS - APP MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestControlAppManagement:
    """Tests for Control API app management endpoints."""

    @pytest.mark.asyncio
    async def test_start_app(self, control_client_cloud, mock_http_success):
        """start endpoint should start app."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.start_app("com.android.chrome")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_launch_app(self, control_client_cloud, mock_http_success):
        """launch_app endpoint should start with permissions."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.launch_app(
                "com.android.chrome",
                grant_all_permissions=True
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_start_activity(self, control_client_cloud, mock_http_success):
        """start_activity endpoint should launch specific activity."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.start_activity(
                "mark.via",
                action="android.intent.action.VIEW",
                data="https://google.com"
            )
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_stop_app(self, control_client_cloud, mock_http_success):
        """stop endpoint should stop app."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.stop_app("com.android.chrome")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_install_app_uri(self, control_client_cloud, mock_http_success):
        """install_uri_sync endpoint should install from URI."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.install_app_uri("https://example.com/app.apk")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_uninstall_app(self, control_client_cloud, mock_http_success):
        """uninstall endpoint should remove app."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.uninstall_app("com.example.app")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_package_list(self, control_client_cloud, mock_http_success):
        """package/list endpoint should list packages."""
        response = mock_http_success(data=["com.android.chrome", "com.google.android.gms"])
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.package_list(type="user")
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL CLIENT TESTS - SYSTEM & DEVICE
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestControlSystemDevice:
    """Tests for Control API system and device endpoints."""

    @pytest.mark.asyncio
    async def test_shell(self, control_client_cloud, mock_http_success):
        """shell endpoint should execute command."""
        response = mock_http_success(data={"output": "test output"})
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.shell("echo test")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_settings_get(self, control_client_cloud, mock_http_success):
        """settings_get endpoint should read settings."""
        response = mock_http_success(data={"value": "1"})
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.settings_get("system", "screen_brightness")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_settings_put(self, control_client_cloud, mock_http_success):
        """settings_put endpoint should write settings."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.settings_put("system", "screen_brightness", "200")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_clipboard_set(self, control_client_cloud, mock_http_success):
        """clipboard/set endpoint should set clipboard."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.clipboard_set("test text")
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_clipboard_get(self, control_client_cloud, mock_http_success):
        """clipboard/get endpoint should get clipboard."""
        response = mock_http_success(data={"text": "test text"})
        with patch.object(control_client_cloud, "_get", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.clipboard_get()
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_google_set_enabled(self, control_client_cloud, mock_http_success):
        """google/set_enabled endpoint should toggle GMS."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.google_set_enabled(True)
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_google_reset_gaid(self, control_client_cloud, mock_http_success):
        """google/reset_gaid endpoint should reset GAID."""
        response = mock_http_success()
        with patch.object(control_client_cloud, "_post", new_callable=AsyncMock, return_value=response):
            result = await control_client_cloud.google_reset_gaid()
            assert result["code"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING MODE TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRoutingModes:
    """Tests for Control API routing modes."""

    def test_cloud_ip_routing(self):
        """Cloud IP routing should use port 18185."""
        client = VMOSEdgeControlClient(cloud_ip="192.168.1.50")
        assert client.base_url == "http://192.168.1.50:18185/api"
        assert client.routing_mode == "cloud"

    def test_host_routing(self):
        """Host routing should use port 18182 with db_id."""
        client = VMOSEdgeControlClient(host_ip="192.168.1.100", db_id="EDGE123")
        assert client.base_url == "http://192.168.1.100:18182/android_api/v2/EDGE123"
        assert client.routing_mode == "host"

    def test_custom_ports(self):
        """Custom ports should override defaults."""
        client = VMOSEdgeControlClient(cloud_ip="192.168.1.50", port=9999)
        assert client.base_url == "http://192.168.1.50:9999/api"


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_container_client(self):
        """get_container_client should create client with host."""
        client = get_container_client("192.168.1.100")
        assert isinstance(client, VMOSEdgeContainerClient)
        assert client.host == "192.168.1.100"

    def test_get_control_client_cloud(self):
        """get_control_client should support cloud_ip."""
        client = get_control_client(cloud_ip="192.168.1.50")
        assert isinstance(client, VMOSEdgeControlClient)
        assert "192.168.1.50" in client.base_url

    def test_get_control_client_host(self):
        """get_control_client should support host_ip + db_id."""
        client = get_control_client(host_ip="192.168.1.100", db_id="EDGE123")
        assert isinstance(client, VMOSEdgeControlClient)
        assert "EDGE123" in client.base_url


# ═══════════════════════════════════════════════════════════════════════════
# API COVERAGE TESTS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestEdgeAPICoverage:
    """Verify all documented Edge API endpoints are implemented."""

    def test_container_host_coverage(self):
        """All Container API host endpoints should be implemented."""
        methods = dir(VMOSEdgeContainerClient)
        expected = [
            "heartbeat", "systeminfo", "hardware_config", "net_info",
            "image_list", "prune_images", "adi_list", "swap_enable",
            "gms_start", "gms_stop",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_container_instance_coverage(self):
        """All Container API instance endpoints should be implemented."""
        methods = dir(VMOSEdgeContainerClient)
        expected = [
            "get_instances", "list_names", "get_instance_detail",
            "get_screenshot", "get_adb_start", "sync_status",
            "rom_status", "clone_status",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_container_lifecycle_coverage(self):
        """All Container API lifecycle endpoints should be implemented."""
        methods = dir(VMOSEdgeContainerClient)
        expected = [
            "create_instance", "run_instances", "stop_instances",
            "reboot_instances", "reset_instances", "delete_instances",
            "clone_instance", "rename_instance", "upgrade_image",
            "replace_devinfo", "update_user_prop", "set_ip",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_container_control_coverage(self):
        """All Container API device control endpoints should be implemented."""
        methods = dir(VMOSEdgeContainerClient)
        expected = [
            "shell", "gps_inject", "timezone_set", "country_set",
            "language_set", "get_timezone_locale", "ip_geo",
            "stop_front_app", "video_inject", "video_inject_off",
            "app_list", "app_start", "app_stop",
            "install_apk_batch", "upload_file_batch",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_control_observation_coverage(self):
        """All Control API observation endpoints should be implemented."""
        methods = dir(VMOSEdgeControlClient)
        expected = [
            "version_info", "list_action", "sleep",
            "display_info", "screenshot_format", "screenshot_raw",
            "screenshot_data_url", "dump_compact", "top_activity",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_control_input_coverage(self):
        """All Control API input endpoints should be implemented."""
        methods = dir(VMOSEdgeControlClient)
        expected = [
            "click", "multi_click", "input_text", "keyevent",
            "swipe", "scroll_bezier", "node_action",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_control_app_coverage(self):
        """All Control API app endpoints should be implemented."""
        methods = dir(VMOSEdgeControlClient)
        expected = [
            "start_app", "launch_app", "start_activity", "stop_app",
            "install_app", "install_app_uri", "uninstall_app", "package_list",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"

    def test_control_system_coverage(self):
        """All Control API system endpoints should be implemented."""
        methods = dir(VMOSEdgeControlClient)
        expected = [
            "shell", "settings_get", "settings_put",
            "clipboard_set", "clipboard_get", "clipboard_list", "clipboard_clear",
            "google_set_enabled", "google_get_enabled", "google_reset_gaid",
        ]
        for method in expected:
            assert method in methods, f"Missing method: {method}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
