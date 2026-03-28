"""
Titan V11.3 — Wallet Provisioner Unit Tests
Tests pure functions: detect_network, detect_issuer, generate_dpan,
WalletProvisionResult, and card validation edge cases.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from wallet_provisioner import (
    CARD_NETWORKS,
    ISSUER_MAP,
    WalletProvisionResult,
    detect_network,
    detect_issuer,
    generate_dpan,
)


# ═══════════════════════════════════════════════════════════════════════
# CARD NETWORK DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestDetectNetwork:

    @pytest.mark.unit
    def test_visa_prefix_4(self):
        result = detect_network("4532015112830366")
        assert result["network"] == "visa"
        assert result["network_id"] == 1

    @pytest.mark.unit
    def test_mastercard_prefix_51(self):
        result = detect_network("5100123456789012")
        assert result["network"] == "mastercard"
        assert result["network_id"] == 2

    @pytest.mark.unit
    def test_mastercard_prefix_2221(self):
        result = detect_network("2221001234567890")
        assert result["network"] == "mastercard"

    @pytest.mark.unit
    def test_amex_prefix_34(self):
        result = detect_network("340000000000000")
        assert result["network"] == "amex"
        assert result["network_id"] == 3

    @pytest.mark.unit
    def test_amex_prefix_37(self):
        result = detect_network("370000000000000")
        assert result["network"] == "amex"

    @pytest.mark.unit
    def test_discover_prefix_6011(self):
        result = detect_network("6011000000000000")
        assert result["network"] == "discover"

    @pytest.mark.unit
    def test_unknown_defaults_to_visa(self):
        result = detect_network("9999999999999999")
        assert result["network"] == "visa"

    @pytest.mark.unit
    def test_strips_spaces(self):
        result = detect_network("4532 0151 1283 0366")
        assert result["network"] == "visa"

    @pytest.mark.unit
    def test_strips_dashes(self):
        result = detect_network("4532-0151-1283-0366")
        assert result["network"] == "visa"


# ═══════════════════════════════════════════════════════════════════════
# ISSUER DETECTION
# ═══════════════════════════════════════════════════════════════════════

class TestDetectIssuer:

    @pytest.mark.unit
    def test_chase_bin(self):
        issuer = detect_issuer("4532015112830366")
        assert issuer == "Chase"

    @pytest.mark.unit
    def test_citi_bin(self):
        issuer = detect_issuer("5100123456789012")
        assert issuer == "Citi"

    @pytest.mark.unit
    def test_amex_bin(self):
        issuer = detect_issuer("3782822463100050")
        assert issuer == "American Express"

    @pytest.mark.unit
    def test_unknown_bin_returns_bank(self):
        issuer = detect_issuer("9999999999999999")
        assert isinstance(issuer, str)
        assert len(issuer) > 0  # Should return "Bank" or similar default


# ═══════════════════════════════════════════════════════════════════════
# DPAN GENERATION
# ═══════════════════════════════════════════════════════════════════════

class TestGenerateDPAN:

    @pytest.mark.unit
    def test_dpan_length_matches_pan(self):
        pan = "4532015112830366"
        dpan = generate_dpan(pan)
        assert len(dpan) == len(pan)

    @pytest.mark.unit
    def test_dpan_different_from_pan(self):
        pan = "4532015112830366"
        dpan = generate_dpan(pan)
        assert dpan != pan

    @pytest.mark.unit
    def test_dpan_uses_token_bin(self):
        """DPAN should use TSP-assigned Token BIN, not the original card BIN."""
        pan = "4532015112830366"
        dpan = generate_dpan(pan)
        # Visa Token BIN ranges: 489537, 489538, 489539, 440066, 440067
        token_bins = ["489537", "489538", "489539", "440066", "440067"]
        assert any(dpan.startswith(b) for b in token_bins), \
            f"DPAN {dpan[:6]} not in Visa Token BIN ranges"

    @pytest.mark.unit
    def test_dpan_passes_luhn(self):
        """Generated DPAN must pass Luhn validation."""
        pan = "4532015112830366"
        dpan = generate_dpan(pan)
        digits = [int(d) for d in dpan]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                doubled = d * 2
                total += doubled - 9 if doubled > 9 else doubled
            else:
                total += d
        assert total % 10 == 0, f"DPAN {dpan} fails Luhn check"

    @pytest.mark.unit
    def test_dpan_mastercard_token_bin(self):
        pan = "5100123456789012"
        dpan = generate_dpan(pan)
        mc_bins = ["530060", "530061", "530062", "530063", "530064", "530065"]
        assert any(dpan.startswith(b) for b in mc_bins)

    @pytest.mark.unit
    def test_dpan_amex_token_bin(self):
        pan = "340000000000000"
        dpan = generate_dpan(pan)
        amex_bins = ["374800", "374801"]
        assert any(dpan.startswith(b) for b in amex_bins)

    @pytest.mark.unit
    def test_dpan_uniqueness(self):
        """Multiple DPANs from same PAN should be different."""
        pan = "4532015112830366"
        dpans = {generate_dpan(pan) for _ in range(20)}
        assert len(dpans) >= 15


# ═══════════════════════════════════════════════════════════════════════
# WALLET PROVISION RESULT
# ═══════════════════════════════════════════════════════════════════════

class TestWalletProvisionResult:

    @pytest.mark.unit
    def test_default_values(self):
        r = WalletProvisionResult()
        assert r.success_count == 0
        assert r.errors == []

    @pytest.mark.unit
    def test_to_dict(self):
        r = WalletProvisionResult()
        r.success_count = 3
        r.errors.append("chrome autofill failed")
        d = r.to_dict()
        assert d["success_count"] == 3
        assert len(d["errors"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# CARD NETWORKS CONFIG
# ═══════════════════════════════════════════════════════════════════════

class TestCardNetworksConfig:

    @pytest.mark.unit
    def test_all_networks_defined(self):
        assert "visa" in CARD_NETWORKS
        assert "mastercard" in CARD_NETWORKS
        assert "amex" in CARD_NETWORKS
        assert "discover" in CARD_NETWORKS

    @pytest.mark.unit
    def test_network_ids_unique(self):
        ids = [info["network_id"] for info in CARD_NETWORKS.values()]
        assert len(ids) == len(set(ids))

    @pytest.mark.unit
    def test_issuer_map_has_common_bins(self):
        assert "4532" in ISSUER_MAP  # Chase
        assert "5100" in ISSUER_MAP  # Citi
        assert "3782" in ISSUER_MAP  # Amex
