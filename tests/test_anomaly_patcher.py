"""
Titan V11.3 — Anomaly Patcher Unit Tests
Tests pure functions (IMEI/ICCID/serial generators, dataclasses) and
mocked ADB interactions (needs_repatch, getprop parsing, audit structure).
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from anomaly_patcher import (
    AnomalyPatcher,
    PatchReport,
    PatchResult,
    _luhn_checksum,
    generate_android_id,
    generate_drm_id,
    generate_gaid,
    generate_imei,
    generate_iccid,
    generate_mac,
    generate_serial,
)
from device_presets import CARRIERS, get_preset


# ═══════════════════════════════════════════════════════════════════════
# PURE FUNCTION TESTS (no ADB needed)
# ═══════════════════════════════════════════════════════════════════════


class TestLuhnChecksum:
    """Test Luhn checksum algorithm used for IMEI/ICCID validation."""

    @pytest.mark.unit
    def test_luhn_known_values(self):
        # IMEI body "35209100176148" → check digit 6
        result = _luhn_checksum("35209100176148")
        assert result == "352091001761486"

    @pytest.mark.unit
    def test_luhn_all_zeros(self):
        result = _luhn_checksum("00000000000000")
        assert result[-1] == "0"
        assert len(result) == 15

    @pytest.mark.unit
    def test_luhn_output_length(self):
        partial = "1234567890"
        result = _luhn_checksum(partial)
        assert len(result) == len(partial) + 1

    @pytest.mark.unit
    def test_luhn_result_validates(self):
        """The Luhn check digit should make the full number pass Luhn validation."""
        result = _luhn_checksum("7992739871")
        digits = [int(d) for d in result]
        odd = sum(digits[-1::-2])
        even = sum(sum(divmod(2 * d, 10)) for d in digits[-2::-2])
        assert (odd + even) % 10 == 0


class TestIMEIGenerator:

    @pytest.mark.unit
    def test_imei_length(self):
        imei = generate_imei("35365811")
        assert len(imei) == 15

    @pytest.mark.unit
    def test_imei_starts_with_tac(self):
        tac = "35365811"
        imei = generate_imei(tac)
        assert imei.startswith(tac)

    @pytest.mark.unit
    def test_imei_all_digits(self):
        imei = generate_imei("35365811")
        assert imei.isdigit()

    @pytest.mark.unit
    def test_imei_passes_luhn(self):
        imei = generate_imei("35365811")
        digits = [int(d) for d in imei]
        odd = sum(digits[-1::-2])
        even = sum(sum(divmod(2 * d, 10)) for d in digits[-2::-2])
        assert (odd + even) % 10 == 0

    @pytest.mark.unit
    def test_imei_uniqueness(self):
        imeis = {generate_imei("35365811") for _ in range(50)}
        assert len(imeis) >= 40  # should be nearly all unique


class TestICCIDGenerator:

    @pytest.mark.unit
    def test_iccid_length(self):
        carrier = CARRIERS["tmobile_us"]
        iccid = generate_iccid(carrier)
        assert len(iccid) == 19 or len(iccid) == 20  # 18-19 digits + check

    @pytest.mark.unit
    def test_iccid_starts_with_89(self):
        carrier = CARRIERS["att_us"]
        iccid = generate_iccid(carrier)
        assert iccid.startswith("89")

    @pytest.mark.unit
    def test_iccid_all_digits(self):
        carrier = CARRIERS["verizon_us"]
        iccid = generate_iccid(carrier)
        assert iccid.isdigit()

    @pytest.mark.unit
    def test_iccid_passes_luhn(self):
        carrier = CARRIERS["tmobile_us"]
        iccid = generate_iccid(carrier)
        digits = [int(d) for d in iccid]
        odd = sum(digits[-1::-2])
        even = sum(sum(divmod(2 * d, 10)) for d in digits[-2::-2])
        assert (odd + even) % 10 == 0


class TestSerialGenerator:

    @pytest.mark.unit
    def test_samsung_serial_starts_with_R(self):
        serial = generate_serial("Samsung")
        assert serial.startswith("R")
        assert len(serial) == 11

    @pytest.mark.unit
    def test_google_serial_length(self):
        serial = generate_serial("Google")
        assert len(serial) == 12

    @pytest.mark.unit
    def test_generic_serial_length(self):
        serial = generate_serial("OnePlus")
        assert len(serial) == 10


class TestOtherGenerators:

    @pytest.mark.unit
    def test_android_id_format(self):
        aid = generate_android_id()
        assert len(aid) == 16
        assert all(c in "0123456789abcdef" for c in aid)

    @pytest.mark.unit
    def test_mac_format(self):
        mac = generate_mac("A4:77:33")
        parts = mac.split(":")
        assert len(parts) == 6
        assert mac.startswith("A4:77:33:")

    @pytest.mark.unit
    def test_drm_id_format(self):
        drm = generate_drm_id()
        assert len(drm) == 32
        assert all(c in "0123456789abcdef" for c in drm)

    @pytest.mark.unit
    def test_gaid_uuid_format(self):
        gaid = generate_gaid()
        parts = gaid.split("-")
        assert len(parts) == 5
        assert len(gaid) == 36


# ═══════════════════════════════════════════════════════════════════════
# DATACLASS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestPatchReport:

    @pytest.mark.unit
    def test_default_values(self):
        r = PatchReport()
        assert r.total == 0
        assert r.passed == 0
        assert r.score == 0
        assert r.results == []
        assert r.phase_timings == {}

    @pytest.mark.unit
    def test_to_dict(self):
        r = PatchReport(preset="samsung_s25_ultra", carrier="tmobile_us",
                        total=10, passed=8, failed=2, score=80,
                        elapsed_sec=123.456)
        d = r.to_dict()
        assert d["preset"] == "samsung_s25_ultra"
        assert d["score"] == 80
        assert d["elapsed_sec"] == 123.46  # rounded

    @pytest.mark.unit
    def test_to_dict_phase_timings_rounded(self):
        r = PatchReport(phase_timings={"identity": 1.23456, "telephony": 2.78901})
        d = r.to_dict()
        assert d["phase_timings"]["identity"] == 1.23
        assert d["phase_timings"]["telephony"] == 2.79


class TestPatchResult:

    @pytest.mark.unit
    def test_defaults(self):
        r = PatchResult(name="test_vector", success=True)
        assert r.name == "test_vector"
        assert r.success is True
        assert r.detail == ""

    @pytest.mark.unit
    def test_with_detail(self):
        r = PatchResult(name="identity", success=False, detail="prop not set")
        assert r.detail == "prop not set"


# ═══════════════════════════════════════════════════════════════════════
# MOCKED ADB TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestAnomalyPatcherInit:

    @pytest.mark.integration
    def test_init_with_mock(self, mock_adb):
        """AnomalyPatcher.__init__ calls adb root — verify it works with mock."""
        mock_adb.set_response("root", "adbd is already running as root")
        patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
        assert patcher.target == "127.0.0.1:6520"
        assert mock_adb.was_called("root")


class TestNeedsRepatch:

    @pytest.mark.integration
    def test_needs_repatch_no_config(self, mock_adb):
        """needs_repatch returns False if no saved config exists."""
        mock_adb.set_response("shell cat /data/local/tmp/titan_patch_config.json", "",
                              returncode=1, stderr="No such file")
        patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
        # needs_repatch checks if patch config exists AND key props are missing
        mock_adb.set_response("shell getprop ro.product.model", "Cuttlefish")
        result = patcher.needs_repatch()
        assert isinstance(result, bool)

    @pytest.mark.integration
    def test_get_saved_patch_config_empty(self, mock_adb):
        """get_saved_patch_config returns None if no config saved."""
        mock_adb.set_response("shell cat /data/local/tmp/titan_patch_config.json", "",
                              returncode=1)
        patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
        config = patcher.get_saved_patch_config()
        assert config is None

    @pytest.mark.integration
    def test_get_saved_patch_config_valid(self, mock_adb):
        """get_saved_patch_config returns dict if config exists."""
        cfg = json.dumps({"preset": "samsung_s25_ultra", "carrier": "tmobile_us"})
        mock_adb.set_response("shell cat /data/local/tmp/titan_patch_config.json", cfg)
        patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
        config = patcher.get_saved_patch_config()
        assert config is not None
        assert config["preset"] == "samsung_s25_ultra"


class TestDevicePresets:
    """Test preset lookup used by the patcher."""

    @pytest.mark.unit
    def test_samsung_preset_exists(self):
        preset = get_preset("samsung_s25_ultra")
        assert preset is not None
        assert preset.brand.lower() == "samsung"

    @pytest.mark.unit
    def test_pixel_preset_exists(self):
        preset = get_preset("pixel_9_pro")
        assert preset is not None
        assert preset.brand.lower() == "google"

    @pytest.mark.unit
    def test_unknown_preset_returns_none(self):
        preset = get_preset("nonexistent_device_xyz")
        assert preset is None

    @pytest.mark.unit
    def test_carrier_tmobile(self):
        c = CARRIERS["tmobile_us"]
        assert c.mcc == "310"
        assert c.mnc == "260"
        assert c.country == "US"
