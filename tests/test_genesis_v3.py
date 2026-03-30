"""
Tests for VMOS Genesis Engine V3 modules.

Run with: python -m pytest tests/test_genesis_v3.py -v
"""

import os
import sys
import pytest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from google_master_auth import GoogleMasterAuth, AuthResult
from vmos_db_builder import (
    VMOSDBBuilder, CardData, PurchaseRecord,
    generate_dpan, generate_order_id
)
from vmos_file_pusher import (
    build_shared_prefs_xml, build_coin_xml, build_finsky_xml, build_billing_xml
)


class TestGoogleMasterAuth:
    """Tests for GoogleMasterAuth module."""

    def test_auth_result_dataclass(self):
        """AuthResult should have all required fields."""
        result = AuthResult()
        assert result.success == False
        assert result.email == ""
        assert result.master_token == ""
        assert isinstance(result.oauth_tokens, dict)
        assert result.requires_2fa == False

    def test_auth_result_to_dict(self):
        """AuthResult.to_dict() should serialize properly."""
        result = AuthResult(
            success=True,
            email="test@gmail.com",
            gaia_id="123456789"
        )
        d = result.to_dict()
        assert d["success"] == True
        assert d["email"] == "test@gmail.com"
        assert d["gaia_id"] == "123456789"

    def test_google_master_auth_init(self):
        """GoogleMasterAuth should initialize without error."""
        auth = GoogleMasterAuth()
        assert auth.sdk_version == 34
        assert auth.device_country == "us"

    def test_get_all_tokens_for_injection(self):
        """Should convert AuthResult to token list format."""
        auth = GoogleMasterAuth()
        result = AuthResult(
            auth_token="ya29.test_token",
            sid="test_sid",
            lsid="test_lsid",
            oauth_tokens={
                "oauth2:https://www.googleapis.com/auth/plus.me": "ya29.plus_token"
            }
        )
        tokens = auth.get_all_tokens_for_injection(result)
        
        assert ("com.google", "ya29.test_token") in tokens
        assert ("SID", "test_sid") in tokens
        assert ("LSID", "test_lsid") in tokens
        assert ("oauth2:https://www.googleapis.com/auth/plus.me", "ya29.plus_token") in tokens


class TestVMOSDBBuilder:
    """Tests for VMOSDBBuilder module."""

    def test_build_accounts_ce_db(self):
        """Should build valid accounts_ce.db."""
        builder = VMOSDBBuilder()
        tokens = [
            ("com.google", "ya29.test_token"),
            ("SID", "test_sid_12345"),
            ("LSID", "test_lsid_12345"),
        ]
        
        db_bytes = builder.build_accounts_ce_db(
            email="test@gmail.com",
            gaia_id="123456789012345",
            tokens=tokens
        )
        
        # Should be valid SQLite database
        assert db_bytes[:16] == b'SQLite format 3\x00'
        assert len(db_bytes) > 1000

    def test_build_accounts_de_db(self):
        """Should build valid accounts_de.db."""
        builder = VMOSDBBuilder()
        
        db_bytes = builder.build_accounts_de_db(
            email="test@gmail.com",
            account_id=1
        )
        
        assert db_bytes[:16] == b'SQLite format 3\x00'
        assert len(db_bytes) > 1000

    def test_build_tapandpay_db(self):
        """Should build valid tapandpay.db with card data."""
        builder = VMOSDBBuilder()
        
        card = CardData(
            card_number="4111111111111111",
            exp_month=12,
            exp_year=2029,
            cardholder_name="Test User",
            network="visa"
        )
        
        db_bytes = builder.build_tapandpay_db(
            card=card,
            email="test@gmail.com",
            gaia_id="123456789",
            dpan="4895371234567890",
            token_ref_id="token_ref_12345"
        )
        
        assert db_bytes[:16] == b'SQLite format 3\x00'
        assert len(db_bytes) > 2000

    def test_build_library_db(self):
        """Should build valid library.db with purchases."""
        builder = VMOSDBBuilder()
        
        purchases = [
            PurchaseRecord(
                app_id="com.spotify.music",
                order_id="GPA.1234-5678-9012-34567",
                purchase_time_ms=1700000000000,
                price_micros=0,
                currency="USD"
            ),
            PurchaseRecord(
                app_id="com.netflix.mediaclient",
                order_id="GPA.ABCD-EFGH-IJKL-MNOPQ",
                purchase_time_ms=1700100000000,
                price_micros=0,
                currency="USD"
            ),
        ]
        
        db_bytes = builder.build_library_db("test@gmail.com", purchases)
        
        assert db_bytes[:16] == b'SQLite format 3\x00'
        assert len(db_bytes) > 1000


class TestDPANGeneration:
    """Tests for DPAN generation."""

    def test_generate_dpan_visa(self):
        """Should generate valid Visa DPAN."""
        dpan = generate_dpan("4111111111111111")
        
        # Should be 16 digits
        assert len(dpan) == 16
        assert dpan.isdigit()
        
        # Should use TSP BIN (489537, 489538, etc.)
        assert dpan[:3] in ["489", "400", "402"]
        
        # Should be Luhn valid
        assert _luhn_check(dpan)

    def test_generate_dpan_mastercard(self):
        """Should generate valid Mastercard DPAN."""
        dpan = generate_dpan("5111111111111111")
        
        assert len(dpan) == 16
        assert dpan.isdigit()
        assert _luhn_check(dpan)

    def test_generate_order_id(self):
        """Should generate valid Google Play order ID."""
        order_id = generate_order_id()
        
        assert order_id.startswith("GPA.")
        parts = order_id.split(".")
        assert len(parts) == 2
        
        segments = parts[1].split("-")
        assert len(segments) == 4
        assert len(segments[0]) == 4
        assert len(segments[1]) == 4
        assert len(segments[2]) == 4
        assert len(segments[3]) == 5


class TestXMLBuilders:
    """Tests for SharedPreferences XML builders."""

    def test_build_shared_prefs_xml(self):
        """Should build valid SharedPreferences XML."""
        prefs = {
            "string_pref": "value",
            "bool_pref": True,
            "int_pref": 42,
        }
        
        xml = build_shared_prefs_xml(prefs)
        
        assert '<?xml version' in xml
        assert '<map>' in xml
        assert '</map>' in xml
        assert 'name="string_pref"' in xml
        assert 'name="bool_pref"' in xml
        assert 'value="true"' in xml
        assert 'value="42"' in xml

    def test_build_coin_xml(self):
        """Should build valid COIN.xml for zero-auth."""
        xml = build_coin_xml("test@gmail.com", "4242")
        
        assert 'PAYMENTS_ZERO_AUTH_ENABLED' in xml
        assert 'value="true"' in xml
        assert 'test@gmail.com' in xml
        assert '4242' in xml

    def test_build_finsky_xml(self):
        """Should build valid finsky.xml for Play Store."""
        xml = build_finsky_xml("test@gmail.com")
        
        assert 'setup_done' in xml
        assert 'test@gmail.com' in xml

    def test_build_billing_xml(self):
        """Should build valid billing.xml."""
        xml = build_billing_xml("test@gmail.com")
        
        assert 'billing_account' in xml
        assert 'zero_auth_enabled' in xml


def _luhn_check(card_number: str) -> bool:
    """Verify Luhn checksum."""
    digits = [int(d) for d in card_number]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
