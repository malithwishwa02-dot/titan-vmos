"""
Titan V11.3 — Shared pytest fixtures and configuration.
Provides mock ADB layer, sample data, and path setup for all test modules.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup — ensure core/ and server/ are importable ──────────────
ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "core"
SERVER_DIR = ROOT / "server"

for p in [str(CORE_DIR), str(SERVER_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TITAN_DATA", str(ROOT / "data"))


# ═══════════════════════════════════════════════════════════════════════
# MARKERS
# ═══════════════════════════════════════════════════════════════════════

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Pure logic tests, no ADB or network")
    config.addinivalue_line("markers", "integration: Tests requiring mocked ADB layer")
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring live Cuttlefish device")


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES — Sample Data
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_adb_target() -> str:
    """Default ADB target for tests."""
    return "127.0.0.1:6520"


@pytest.fixture
def sample_profile() -> dict:
    """Minimal forged profile for testing injection."""
    return {
        "profile_id": "TEST-ABCDEF12",
        "persona_name": "Jane Doe",
        "persona_email": "jane.doe.test@gmail.com",
        "persona_phone": "+12125551234",
        "dob": "1985-06-15",
        "gender": "Female",
        "address": "123 Test St",
        "city": "New York",
        "state": "NY",
        "zip": "10001",
        "country": "US",
        "carrier": "tmobile_us",
        "location": "nyc",
        "device_model": "samsung_s25_ultra",
        "age_days": 90,
        "contacts": [
            {"name": "Alice Smith", "phone": "+12125559001", "email": "alice@test.com"},
            {"name": "Bob Jones", "phone": "+12125559002", "email": "bob@test.com"},
            {"name": "Carol White", "phone": "+12125559003", "email": ""},
        ],
        "call_logs": [
            {"number": "+12125559001", "type": 1, "duration": 120, "date": 1700000000000},
            {"number": "+12125559002", "type": 2, "duration": 60, "date": 1700100000000},
        ],
        "sms_messages": [
            {"address": "+12125559001", "body": "Hey!", "type": 1, "date": 1700000000000},
            {"address": "+12125559002", "body": "See you later", "type": 2, "date": 1700200000000},
        ],
        "browser_history": [
            {"url": "https://www.google.com", "title": "Google", "visits": 5, "last_visit": 1700000000},
            {"url": "https://www.youtube.com", "title": "YouTube", "visits": 3, "last_visit": 1700100000},
        ],
        "wifi_networks": [
            {"ssid": "HomeWiFi-5G", "bssid": "aa:bb:cc:dd:ee:ff", "key_mgmt": "WPA-PSK"},
        ],
    }


@pytest.fixture
def sample_card_data() -> dict:
    """Sample payment card data for wallet tests."""
    return {
        "number": "4532015112830366",
        "exp_month": 12,
        "exp_year": 2027,
        "cvv": "123",
        "cardholder": "JANE DOE",
        "network": "visa",
    }


@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporary TITAN_DATA directory for isolation."""
    data = tmp_path / "titan_data"
    for sub in ["devices", "profiles", "config", "jobs", "gapps", "logs"]:
        (data / sub).mkdir(parents=True)
    old = os.environ.get("TITAN_DATA")
    os.environ["TITAN_DATA"] = str(data)
    yield data
    if old:
        os.environ["TITAN_DATA"] = old
    else:
        os.environ.pop("TITAN_DATA", None)


@pytest.fixture
def temp_profile_file(tmp_path, sample_profile) -> Path:
    """Write sample profile to a temp JSON file."""
    pf = tmp_path / f"{sample_profile['profile_id']}.json"
    pf.write_text(json.dumps(sample_profile))
    return pf


# ═══════════════════════════════════════════════════════════════════════
# FIXTURES — Mock ADB
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_adb():
    """Patch subprocess.run to intercept all ADB calls.

    Usage:
        def test_something(mock_adb):
            mock_adb.set_response("shell getprop ro.product.model", "SM-S928U")
            # ... call code that invokes ADB ...
            assert mock_adb.was_called("shell getprop ro.product.model")
    """
    from tests.mocks.adb_mock import MockADB

    mock = MockADB()
    with mock.patch():
        yield mock


@pytest.fixture
def sample_device_preset():
    """Return a sample DevicePreset for testing."""
    from device_presets import get_preset
    return get_preset("samsung_s25_ultra")


@pytest.fixture
def sample_carrier():
    """Return a sample CarrierProfile for testing."""
    from device_presets import CARRIERS
    return CARRIERS["tmobile_us"]
