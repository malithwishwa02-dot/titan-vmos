"""
Titan V13.0 — VMOS Cloud Module Tests
Unit tests for the VMOS Cloud Bridge and Device Modifier.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from vmos_cloud_module import (
    VMOSCloudBridge,
    VMOSDeviceModifier,
    VMOSConfig,
    VMOSInstance,
    VMOSResponse,
)


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_config():
    """Sample VMOS config for testing."""
    return VMOSConfig(
        api_key="test_api_key",
        api_secret="test_api_secret",
        host="api.vmoscloud.com",
    )


@pytest.fixture
def bridge(mock_config):
    """VMOSCloudBridge with mocked credentials."""
    return VMOSCloudBridge(config=mock_config)


@pytest.fixture
def mock_http_response():
    """Factory for creating mock HTTP responses."""
    def _create(code=200, data=None, msg="success"):
        return {"code": code, "data": data, "msg": msg}
    return _create


# ═══════════════════════════════════════════════════════════════════════
# CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestVMOSConfig:
    """Tests for VMOSConfig."""

    def test_from_env_empty(self):
        """Config should handle missing env vars."""
        with patch.dict(os.environ, {}, clear=True):
            config = VMOSConfig.from_env()
            assert not config.is_configured()
            assert config.api_key == ""
            assert config.api_secret == ""
            assert config.host == "api.vmoscloud.com"

    def test_from_env_configured(self):
        """Config should load from environment variables."""
        with patch.dict(os.environ, {
            "VMOS_API_KEY": "test_key",
            "VMOS_API_SECRET": "test_secret",
            "VMOS_API_HOST": "custom.host.com",
        }):
            config = VMOSConfig.from_env()
            assert config.is_configured()
            assert config.api_key == "test_key"
            assert config.api_secret == "test_secret"
            assert config.host == "custom.host.com"

    def test_is_configured(self, mock_config):
        """is_configured should require both key and secret."""
        assert mock_config.is_configured()

        config_no_key = VMOSConfig(api_secret="secret")
        assert not config_no_key.is_configured()

        config_no_secret = VMOSConfig(api_key="key")
        assert not config_no_secret.is_configured()


# ═══════════════════════════════════════════════════════════════════════
# INSTANCE MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestVMOSInstance:
    """Tests for VMOSInstance model."""

    def test_from_api_response(self):
        """Instance should parse API response correctly."""
        data = {
            "padCode": "PAD123",
            "deviceIp": "192.168.1.100",
            "status": "online",
            "deviceLevel": "pro",
            "deviceName": "My Device",
            "romVersion": "1.0.0",
            "androidVersion": "13",
            "resolution": "1080x1920",
        }
        inst = VMOSInstance.from_api_response(data)
        assert inst.pad_code == "PAD123"
        assert inst.device_ip == "192.168.1.100"
        assert inst.status == "online"
        assert inst.android_version == "13"

    def test_to_dict(self):
        """Instance should convert to dict correctly."""
        inst = VMOSInstance(
            pad_code="PAD456",
            device_ip="10.0.0.1",
            status="offline",
        )
        d = inst.to_dict()
        assert d["pad_code"] == "PAD456"
        assert d["device_ip"] == "10.0.0.1"
        assert d["status"] == "offline"


# ═══════════════════════════════════════════════════════════════════════
# BRIDGE TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestVMOSCloudBridge:
    """Tests for VMOSCloudBridge."""

    def test_init_with_params(self):
        """Bridge should accept explicit credentials."""
        bridge = VMOSCloudBridge(api_key="key", api_secret="secret")
        assert bridge.config.api_key == "key"
        assert bridge.config.api_secret == "secret"

    def test_init_with_config(self, mock_config):
        """Bridge should accept config object."""
        bridge = VMOSCloudBridge(config=mock_config)
        assert bridge.config.api_key == "test_api_key"

    def test_init_with_base_url(self):
        """Bridge should parse base URL to extract host."""
        bridge = VMOSCloudBridge(
            api_key="key",
            api_secret="secret",
            base_url="https://custom.api.com",
        )
        assert bridge.config.host == "custom.api.com"

    def test_sign_request(self, bridge):
        """Signature should include required headers."""
        body = '{"test": "data"}'
        headers = bridge._sign_request(body)

        assert "content-type" in headers
        assert "x-host" in headers
        assert "x-date" in headers
        assert "authorization" in headers
        assert "HMAC-SHA256" in headers["authorization"]
        assert "Credential=test_api_key" in headers["authorization"]

    @pytest.mark.asyncio
    async def test_list_instances(self, bridge, mock_http_response):
        """list_instances should parse response correctly."""
        response = mock_http_response(
            code=200,
            data={
                "list": [
                    {"padCode": "PAD001", "status": "online"},
                    {"padCode": "PAD002", "status": "offline"},
                ]
            },
        )
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            instances = await bridge.list_instances()
            assert len(instances) == 2
            assert instances[0].pad_code == "PAD001"
            assert instances[1].pad_code == "PAD002"

    @pytest.mark.asyncio
    async def test_list_instances_error(self, bridge, mock_http_response):
        """list_instances should return empty list on error."""
        response = mock_http_response(code=500, msg="Server error")
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            instances = await bridge.list_instances()
            assert instances == []

    @pytest.mark.asyncio
    async def test_get_instance(self, bridge, mock_http_response):
        """get_instance should return instance details."""
        response = mock_http_response(
            code=200,
            data={"padCode": "PAD001", "status": "online", "deviceIp": "10.0.0.1"},
        )
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            inst = await bridge.get_instance("PAD001")
            assert inst is not None
            assert inst.pad_code == "PAD001"
            assert inst.device_ip == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_start_instance(self, bridge, mock_http_response):
        """start_instance should return success response."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.start_instance("PAD001")
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_stop_instance(self, bridge, mock_http_response):
        """stop_instance should return success response."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.stop_instance("PAD001")
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_restart_instance(self, bridge, mock_http_response):
        """restart_instance should return success response."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.restart_instance("PAD001")
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_exec_shell(self, bridge, mock_http_response):
        """exec_shell should execute command and return result."""
        # First call returns task ID
        start_response = mock_http_response(code=200, data=[{"taskId": 12345}])
        # Second call returns completed task
        result_response = mock_http_response(
            code=200,
            data=[{"taskStatus": 3, "taskResult": "command output"}],
        )

        with patch.object(bridge, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [start_response, result_response]
            r = await bridge.exec_shell("PAD001", "echo hello")
            assert r.ok is True
            assert r.result == "command output"
            assert r.task_id == 12345

    @pytest.mark.asyncio
    async def test_update_android_props(self, bridge, mock_http_response):
        """update_android_props should set properties."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.update_android_props(
                "PAD001",
                {"ro.product.brand": "samsung", "ro.product.model": "SM-S928U"},
            )
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_set_gps(self, bridge, mock_http_response):
        """set_gps should set location."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.set_gps("PAD001", lat=40.7128, lon=-74.0060)
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_set_wifi(self, bridge, mock_http_response):
        """set_wifi should configure WiFi."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.set_wifi(
                "PAD001",
                ssid="HomeWiFi",
                mac="AA:BB:CC:DD:EE:FF",
                ip="192.168.1.100",
            )
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_inject_contacts(self, bridge, mock_http_response):
        """inject_contacts should add contacts."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.inject_contacts(
                "PAD001",
                [{"firstName": "John", "phone": "+12125551234"}],
            )
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_send_sms(self, bridge, mock_http_response):
        """send_sms should inject message."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.send_sms("PAD001", sender="+12125550000", message="Test")
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_screenshot(self, bridge, mock_http_response):
        """screenshot should return capture data."""
        response = mock_http_response(code=200, data={"url": "https://example.com/screenshot.png"})
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.screenshot("PAD001")
            assert r.ok is True
            assert r.data is not None

    @pytest.mark.asyncio
    async def test_click(self, bridge, mock_http_response):
        """click should send tap event."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.click("PAD001", x=540, y=960)
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_modify_fingerprint(self, bridge, mock_http_response):
        """modify_fingerprint should apply preset."""
        response = mock_http_response(code=200)
        with patch.object(bridge, "_post", new_callable=AsyncMock, return_value=response):
            r = await bridge.modify_fingerprint(
                "PAD001",
                model="samsung_s25_ultra",
                country="US",
                carrier="tmobile",
            )
            assert r.ok is True

    @pytest.mark.asyncio
    async def test_modify_fingerprint_unknown_model(self, bridge):
        """modify_fingerprint should fail for unknown model."""
        r = await bridge.modify_fingerprint(
            "PAD001",
            model="unknown_model",
            country="XX",
            carrier="unknown",
        )
        assert r.ok is False
        assert "Unknown" in r.message


# ═══════════════════════════════════════════════════════════════════════
# DEVICE MODIFIER TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestVMOSDeviceModifier:
    """Tests for VMOSDeviceModifier."""

    @pytest.fixture
    def modifier(self, bridge):
        """VMOSDeviceModifier with mocked bridge."""
        return VMOSDeviceModifier(bridge=bridge)

    @pytest.mark.asyncio
    async def test_full_modification(self, modifier, mock_http_response):
        """full_modification should run all steps."""
        response = mock_http_response(code=200)

        with patch.object(
            modifier.bridge, "_post", new_callable=AsyncMock, return_value=response
        ):
            result = await modifier.full_modification(
                pad_code="PAD001",
                model="samsung_s25_ultra",
                country="US",
                carrier="tmobile",
                inject_contacts=False,
                inject_sms=False,
                inject_calls=False,
                set_gps=False,
                restart_after=False,
            )

            assert "pad_code" in result
            assert result["pad_code"] == "PAD001"
            assert "steps" in result
            assert "fingerprint" in result["steps"]

    @pytest.mark.asyncio
    async def test_full_modification_with_content(self, modifier, mock_http_response):
        """full_modification should inject content when enabled."""
        response = mock_http_response(code=200, data=[{"taskId": 1}])

        with patch.object(
            modifier.bridge, "_post", new_callable=AsyncMock, return_value=response
        ):
            result = await modifier.full_modification(
                pad_code="PAD001",
                inject_contacts=True,
                inject_sms=True,
                inject_calls=True,
                set_gps=True,
                restart_after=False,
            )

            assert "steps" in result
            assert "contacts" in result["steps"]
            assert "sms" in result["steps"]
            assert "calls" in result["steps"]
            assert "gps" in result["steps"]


# ═══════════════════════════════════════════════════════════════════════
# RESPONSE MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestVMOSResponse:
    """Tests for VMOSResponse model."""

    def test_to_dict(self):
        """Response should convert to dict correctly."""
        r = VMOSResponse(
            ok=True,
            status=200,
            code=200,
            message="success",
            task_id=12345,
        )
        d = r.to_dict()
        assert d["ok"] is True
        assert d["status"] == 200
        assert d["task_id"] == 12345

    def test_defaults(self):
        """Response should have sensible defaults."""
        r = VMOSResponse()
        assert r.ok is False
        assert r.status == 0
        assert r.message == ""
        assert r.data is None
