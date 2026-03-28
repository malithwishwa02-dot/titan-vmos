"""
Tests for the Unified Genesis Engine.
"""
import pytest
import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


def test_genesis_config_creation():
    """Test that GenesisConfig can be created with default values."""
    from unified_genesis_engine import GenesisConfig
    
    config = GenesisConfig()
    
    assert config.persona.country == "US"
    assert config.device.model == "samsung_s24"
    assert config.aging.age_days == 90
    assert config.options.skip_wipe is False


def test_genesis_config_from_dict():
    """Test creating GenesisConfig from a flat dictionary."""
    from unified_genesis_engine import GenesisConfig
    
    data = {
        "name": "John Smith",
        "email": "john@example.com",
        "country": "GB",
        "age_days": 180,
        "device_model": "pixel_9_pro",
        "cc_number": "4538123456789012",
        "cc_exp": "12/2027",
    }
    
    config = GenesisConfig.from_dict(data)
    
    assert config.persona.name == "John Smith"
    assert config.persona.email == "john@example.com"
    assert config.persona.country == "GB"
    assert config.aging.age_days == 180
    assert config.device.model == "pixel_9_pro"
    assert config.payment.cc_number == "4538123456789012"
    assert config.payment.cc_exp_month == 12
    assert config.payment.cc_exp_year == 2027


def test_payment_config_card_network():
    """Test card network detection from BIN."""
    from unified_genesis_engine import PaymentConfig
    
    # Visa
    visa = PaymentConfig(cc_number="4538123456789012")
    assert visa.card_network == "visa"
    
    # Mastercard
    mc = PaymentConfig(cc_number="5538123456789012")
    assert mc.card_network == "mastercard"
    
    # Amex
    amex = PaymentConfig(cc_number="3782822463100005")
    assert amex.card_network == "amex"
    
    # Discover
    disc = PaymentConfig(cc_number="6011123456789012")
    assert disc.card_network == "discover"
    
    # Unknown
    empty = PaymentConfig(cc_number="")
    assert empty.card_network == "unknown"


def test_calculate_optimal_aging_profile():
    """Test the aging profile calculation algorithm."""
    from unified_genesis_engine import calculate_optimal_aging_profile
    
    # US, 90 days, moderate
    profile = calculate_optimal_aging_profile("US", 90, "moderate", "professional")
    
    assert profile["aging_level"] == "medium"
    assert profile["country"] == "US"
    assert profile["locale"] == "en-US"
    assert "contacts_range" in profile
    assert "transaction_range" in profile
    assert len(profile["recommended_apps"]) > 0


def test_aging_levels():
    """Test aging level calculations."""
    from unified_genesis_engine import calculate_optimal_aging_profile
    
    # Light (<=45 days)
    light = calculate_optimal_aging_profile("US", 30)
    assert light["aging_level"] == "light"
    
    # Medium (46-180 days)
    medium = calculate_optimal_aging_profile("US", 90)
    assert medium["aging_level"] == "medium"
    
    # Heavy (>180 days)
    heavy = calculate_optimal_aging_profile("US", 365)
    assert heavy["aging_level"] == "heavy"


def test_country_profiles():
    """Test country-specific profiles."""
    from unified_genesis_engine import COUNTRY_PROFILES
    
    assert "US" in COUNTRY_PROFILES
    assert "GB" in COUNTRY_PROFILES
    assert "DE" in COUNTRY_PROFILES
    
    us = COUNTRY_PROFILES["US"]
    assert us["locale"] == "en-US"
    assert us["currency"] == "USD"
    assert "tmobile_us" in us["default_carrier"]


def test_genesis_phases():
    """Test pipeline phase definitions."""
    from unified_genesis_engine import GENESIS_PHASES
    
    assert len(GENESIS_PHASES) == 16
    
    phase_names = [p["name"] for p in GENESIS_PHASES]
    assert "Pre-Flight Check" in phase_names
    assert "Stealth Patch" in phase_names
    assert "Trust Audit" in phase_names
    assert "Final Verify" in phase_names


def test_phase_result_dataclass():
    """Test PhaseResult dataclass."""
    from unified_genesis_engine import PhaseResult
    
    phase = PhaseResult(phase_id=1, name="Test Phase", status="done")
    phase.started_at = 100.0
    phase.completed_at = 105.0
    
    assert phase.duration == 5.0


def test_genesis_result_progress():
    """Test GenesisResult progress calculation."""
    from unified_genesis_engine import GenesisResult, PhaseResult
    
    result = GenesisResult(
        job_id="test-123",
        phases=[
            PhaseResult(phase_id=0, name="Phase 0", status="done"),
            PhaseResult(phase_id=1, name="Phase 1", status="done"),
            PhaseResult(phase_id=2, name="Phase 2", status="running"),
            PhaseResult(phase_id=3, name="Phase 3", status="pending"),
        ]
    )
    
    assert result.progress == 0.5  # 2 done out of 4


def test_genesis_result_to_dict():
    """Test GenesisResult serialization."""
    from unified_genesis_engine import GenesisResult, PhaseResult
    
    result = GenesisResult(
        job_id="test-123",
        status="completed",
        trust_score=85,
        trust_grade="A",
        phases=[
            PhaseResult(phase_id=0, name="Phase 0", status="done"),
        ]
    )
    
    data = result.to_dict()
    
    assert data["job_id"] == "test-123"
    assert data["status"] == "completed"
    assert data["trust_score"] == 85
    assert data["trust_grade"] == "A"
    assert len(data["phases"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
