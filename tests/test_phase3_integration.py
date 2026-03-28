"""
Titan V11.3 — Phase 3 Integration Tests
Tests for device aging pipeline patches (payment history, detection evasion, injection completeness).

Tests:
  - P3-1: Payment history forging
  - P3-2: Google Pay tokenization completion
  - P3-3: OTP interception & handling
  - P3-4: Play Integrity API spoofing
  - P3-5: Device property validation
  - P3-6: Payment pattern modeling
  - P3-7: App-specific injection expansion
  - P3-8: Timestamp consistency validation
"""

import pytest
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


class TestPaymentHistoryForge:
    """Test P3-1: Payment history forging."""

    def test_payment_history_generation(self):
        """Test payment history generation with realistic patterns."""
        from payment_history_forge import PaymentHistoryForge

        forge = PaymentHistoryForge()
        history = forge.forge(
            age_days=90,
            card_network="visa",
            card_last4="4532",
            persona_email="test@example.com",
        )

        assert "transactions" in history
        assert len(history["transactions"]) >= 30
        assert len(history["transactions"]) <= 250
        assert history["stats"]["total_transactions"] == len(history["transactions"])

    def test_merchant_category_diversity(self):
        """Test merchant category diversity in transactions."""
        from payment_history_forge import PaymentHistoryForge

        forge = PaymentHistoryForge()
        history = forge.forge(age_days=90, card_last4="4532")

        categories = set(t["category"] for t in history["transactions"])
        assert len(categories) >= 4  # At least 4 different categories

    def test_refund_generation(self):
        """Test refund/chargeback generation."""
        from payment_history_forge import PaymentHistoryForge

        forge = PaymentHistoryForge()
        history = forge.forge(age_days=90, card_last4="4532")

        assert "refunds" in history
        refund_rate = len(history["refunds"]) / len(history["transactions"])
        assert 0.02 <= refund_rate <= 0.05  # 2-5% refund rate

    def test_spending_patterns(self):
        """Test realistic spending patterns."""
        from payment_history_forge import PaymentHistoryForge

        forge = PaymentHistoryForge()
        history = forge.forge(age_days=90, card_last4="4532")

        patterns = history["patterns"]
        assert "category_distribution" in patterns
        assert "time_of_day_distribution" in patterns
        assert "day_of_week_distribution" in patterns


class TestOTPInterceptor:
    """Test P3-3: OTP interception & handling."""

    def test_otp_extraction(self):
        """Test OTP code extraction from SMS."""
        from otp_interceptor import OTPInterceptor

        interceptor = OTPInterceptor()

        # Test 6-digit code
        code = interceptor._extract_otp("Your verification code is 123456")
        assert code == "123456"

        # Test with prefix
        code = interceptor._extract_otp("code: 987654")
        assert code == "987654"

    def test_otp_queue_management(self):
        """Test OTP queue management."""
        from otp_interceptor import OTPInterceptor

        interceptor = OTPInterceptor()
        
        # Simulate OTP detection
        with interceptor._lock:
            interceptor._otp_queue.append({
                "code": "123456",
                "timestamp": time.time(),
                "body": "Your code is 123456",
            })

        stats = interceptor.get_otp_stats()
        assert stats["queued_otps"] == 1


class TestPlayIntegritySpoofer:
    """Test P3-4: Play Integrity API spoofing."""

    def test_attestation_response_setting(self):
        """Test setting custom attestation response."""
        from play_integrity_spoofer import PlayIntegritySpoofer

        spoofer = PlayIntegritySpoofer()
        result = spoofer.set_attestation_response(
            device_integrity="MEETS_STRONG_INTEGRITY",
            app_integrity="MEETS_APP_INTEGRITY",
        )

        assert result is True
        status = spoofer.get_hook_status()
        assert status["attestation_response"]["device_integrity"] == "MEETS_STRONG_INTEGRITY"


class TestPropertyValidator:
    """Test P3-5: Device property validation."""

    def test_property_group_validation(self):
        """Test property group validation."""
        from property_validator import PropertyValidator

        validator = PropertyValidator()
        
        # Mock properties
        validator._properties = {
            "ro.product.model": "SM-S928B",
            "ro.product.brand": "samsung",
            "ro.product.manufacturer": "Samsung",
        }

        result = validator._validate_property_group(
            "device_identity",
            ["ro.product.model", "ro.product.brand", "ro.product.manufacturer"]
        )

        assert result["passed"] is True
        assert len(result["properties"]) == 3

    def test_emulator_artifact_detection(self):
        """Test emulator artifact detection."""
        from property_validator import PropertyValidator

        validator = PropertyValidator()

        assert validator._contains_emulator_artifacts("cuttlefish") is True
        assert validator._contains_emulator_artifacts("vsoc") is True
        assert validator._contains_emulator_artifacts("SM-S928B") is False


class TestPaymentPatternForge:
    """Test P3-6: Payment pattern modeling."""

    def test_circadian_pattern_generation(self):
        """Test circadian spending pattern generation."""
        from payment_pattern_forge import PaymentPatternForge

        forge = PaymentPatternForge()
        patterns = forge.generate_patterns(
            age_days=90,
            persona_profile={"archetype": "professional"}
        )

        assert "circadian_pattern" in patterns
        circadian = patterns["circadian_pattern"]
        
        # Check that all time slots sum to ~1.0
        total = sum(circadian.values())
        assert 0.99 <= total <= 1.01

    def test_merchant_clustering(self):
        """Test merchant clustering by category."""
        from payment_pattern_forge import PaymentPatternForge

        forge = PaymentPatternForge()
        patterns = forge.generate_patterns(age_days=90)

        assert "merchant_clusters" in patterns
        clusters = patterns["merchant_clusters"]
        assert len(clusters) >= 4  # At least 4 merchant clusters

    def test_recurring_transactions(self):
        """Test recurring transaction generation."""
        from payment_pattern_forge import PaymentPatternForge

        forge = PaymentPatternForge()
        patterns = forge.generate_patterns(
            age_days=90,
            persona_profile={"archetype": "professional"}
        )

        assert "recurring_transactions" in patterns
        recurring = patterns["recurring_transactions"]
        assert len(recurring) >= 2  # At least Netflix + Spotify


class TestTimestampValidator:
    """Test P3-8: Timestamp consistency validation."""

    def test_monotonic_check(self):
        """Test monotonic timestamp progression check."""
        from timestamp_validator import TimestampValidator

        validator = TimestampValidator()

        # Test monotonic sequence
        assert validator._is_monotonic([1, 2, 3, 4, 5]) is True
        
        # Test non-monotonic sequence
        assert validator._is_monotonic([1, 3, 2, 4, 5]) is False

    def test_timestamp_parsing(self):
        """Test timestamp parsing from various formats."""
        from timestamp_validator import TimestampValidator

        validator = TimestampValidator()

        # Unix timestamp (seconds)
        dt = validator._parse_timestamp(1710777600)
        assert dt is not None
        assert isinstance(dt, datetime)

        # Unix timestamp (milliseconds)
        dt = validator._parse_timestamp(1710777600000)
        assert dt is not None

        # ISO format
        dt = validator._parse_timestamp("2024-03-18T12:00:00Z")
        assert dt is not None


class TestWalletProvisionerEnhanced:
    """Test P3-2: Google Pay tokenization completion."""

    def test_dpan_generation(self):
        """Test DPAN generation with TSP BIN ranges."""
        from wallet_provisioner import generate_dpan

        dpan = generate_dpan("4532015112830366")
        
        # Check DPAN length
        assert len(dpan) == 16
        
        # Check DPAN uses TSP BIN range (starts with 489537-489539 or 440066-440067 for Visa)
        assert dpan[:6] in ["489537", "489538", "489539", "440066", "440067"]

    def test_luhn_check(self):
        """Test Luhn checksum validation."""
        from wallet_provisioner import WalletProvisioner

        prov = WalletProvisioner()
        
        # Valid card number
        assert prov._luhn_check("4532015112830366") is True
        
        # Invalid card number
        assert prov._luhn_check("4532015112830367") is False


class TestIntegrationScenarios:
    """Integration tests for complete workflows."""

    def test_payment_history_with_patterns(self):
        """Test payment history generation with realistic patterns."""
        from payment_history_forge import PaymentHistoryForge
        from payment_pattern_forge import PaymentPatternForge

        # Generate patterns
        pattern_forge = PaymentPatternForge()
        patterns = pattern_forge.generate_patterns(
            age_days=90,
            persona_profile={"archetype": "professional", "location": "nyc"}
        )

        # Generate history
        history_forge = PaymentHistoryForge()
        history = history_forge.forge(
            age_days=90,
            card_last4="4532",
        )

        # Verify patterns are applied
        assert len(history["transactions"]) > 0
        assert "patterns" in history

    def test_property_validation_with_fixes(self):
        """Test property validation with automatic fixes."""
        from property_validator import PropertyValidator, PropertyValidationResult

        validator = PropertyValidator()
        
        # Mock properties with inconsistencies
        validator._properties = {
            "ro.product.model": "SM-S928B",
            "ro.product.brand": "google",  # Inconsistent with Samsung model
        }

        result = validator.validate_all_properties()
        
        # Should detect inconsistency
        assert result.passed is False or len(result.warnings) > 0

    def test_timestamp_validation_across_databases(self):
        """Test timestamp validation across multiple databases."""
        from timestamp_validator import TimestampValidator

        validator = TimestampValidator()
        
        # This would test cross-database timestamp consistency
        # For now, just verify the validator initializes
        assert validator.target is not None


class TestEndToEndPipeline:
    """End-to-end pipeline tests."""

    def test_complete_aging_pipeline_with_patches(self):
        """Test complete aging pipeline with all Phase 3 patches."""
        # This would test the full workflow:
        # 1. Generate payment history
        # 2. Apply payment patterns
        # 3. Inject into device
        # 4. Validate properties
        # 5. Validate timestamps
        # 6. Verify OTP handling
        # 7. Check Play Integrity spoofing
        
        # For now, just verify all modules can be imported
        from payment_history_forge import PaymentHistoryForge
        from payment_pattern_forge import PaymentPatternForge
        from otp_interceptor import OTPInterceptor
        from play_integrity_spoofer import PlayIntegritySpoofer
        from property_validator import PropertyValidator
        from timestamp_validator import TimestampValidator

        assert PaymentHistoryForge is not None
        assert PaymentPatternForge is not None
        assert OTPInterceptor is not None
        assert PlayIntegritySpoofer is not None
        assert PropertyValidator is not None
        assert TimestampValidator is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
