"""
Titan V11.3 — Android Profile Forge Unit Tests
Tests offline profile generation: persona fields, date boundaries,
circadian weighting, contact generation, history patterns.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from android_profile_forge import AndroidProfileForge


# ═══════════════════════════════════════════════════════════════════════
# PROFILE GENERATION — BASIC STRUCTURE
# ═══════════════════════════════════════════════════════════════════════

class TestProfileForgeBasic:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_forge_returns_dict(self, forge):
        profile = forge.forge(
            persona_name="Test User",
            persona_email="test@example.com",
            persona_phone="+12125551234",
            country="US",
            age_days=30,
        )
        assert isinstance(profile, dict)

    @pytest.mark.unit
    def test_forge_has_required_keys(self, forge):
        profile = forge.forge(
            persona_name="Test User",
            persona_email="test@example.com",
            persona_phone="+12125551234",
            country="US",
            age_days=30,
        )
        required = ["contacts", "call_logs", "sms_messages", "browser_history",
                     "cookies", "wifi_networks"]
        for key in required:
            assert key in profile, f"Missing key: {key}"

    @pytest.mark.unit
    def test_forge_persona_fields_present(self, forge):
        profile = forge.forge(
            persona_name="Jane Doe",
            persona_email="jane@test.com",
            persona_phone="+14155559999",
            country="US",
            age_days=90,
        )
        assert profile.get("persona_name") == "Jane Doe"
        assert profile.get("persona_email") == "jane@test.com"
        assert profile.get("persona_phone") == "+14155559999"

    @pytest.mark.unit
    def test_forge_with_archetype(self, forge):
        profile = forge.forge(
            persona_name="Pro User",
            persona_email="pro@test.com",
            persona_phone="+12125551234",
            country="US",
            archetype="professional",
            age_days=90,
        )
        assert isinstance(profile, dict)
        # Professional archetype should still generate contacts
        assert len(profile.get("contacts", [])) > 0


# ═══════════════════════════════════════════════════════════════════════
# CONTACTS GENERATION
# ═══════════════════════════════════════════════════════════════════════

class TestContactsGeneration:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_contacts_not_empty(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        assert len(profile.get("contacts", [])) > 0

    @pytest.mark.unit
    def test_contacts_have_names(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for contact in profile["contacts"][:5]:
            assert "name" in contact
            assert len(contact["name"]) > 0

    @pytest.mark.unit
    def test_contacts_have_phones(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for contact in profile["contacts"][:5]:
            assert "phone" in contact
            assert len(contact["phone"]) > 0

    @pytest.mark.unit
    def test_us_locale_contact_phones(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for contact in profile["contacts"][:5]:
            phone = contact["phone"]
            # US phones should start with +1 or have an area code
            assert phone.startswith("+1") or phone[0].isdigit()


# ═══════════════════════════════════════════════════════════════════════
# CALL LOGS — CIRCADIAN WEIGHTING
# ═══════════════════════════════════════════════════════════════════════

class TestCallLogGeneration:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_call_logs_generated(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        assert len(profile.get("call_logs", [])) > 0

    @pytest.mark.unit
    def test_call_log_has_required_fields(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for log in profile["call_logs"][:5]:
            assert "number" in log
            assert "type" in log
            assert "duration" in log
            assert "date" in log

    @pytest.mark.unit
    def test_call_types_valid(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        valid_types = {1, 2, 3}  # incoming, outgoing, missed
        for log in profile["call_logs"]:
            assert log["type"] in valid_types

    @pytest.mark.unit
    def test_call_dates_within_age(self, forge):
        age_days = 30
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=age_days,
        )
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        min_ms = now_ms - (age_days + 2) * 86400 * 1000  # +2 day buffer

        for log in profile["call_logs"][:10]:
            ts = log["date"]
            assert min_ms <= ts <= now_ms + 86400000, \
                f"Call date {ts} outside [{min_ms}, {now_ms}]"


# ═══════════════════════════════════════════════════════════════════════
# SMS GENERATION
# ═══════════════════════════════════════════════════════════════════════

class TestSMSGeneration:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_sms_generated(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        assert len(profile.get("sms_messages", [])) > 0

    @pytest.mark.unit
    def test_sms_has_body(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for sms in profile["sms_messages"][:5]:
            assert "body" in sms
            assert len(sms["body"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# BROWSER HISTORY / COOKIES
# ═══════════════════════════════════════════════════════════════════════

class TestBrowserDataGeneration:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_browser_history_generated(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        assert len(profile.get("browser_history", [])) > 0

    @pytest.mark.unit
    def test_cookies_generated(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        assert len(profile.get("cookies", [])) > 0

    @pytest.mark.unit
    def test_history_urls_valid(self, forge):
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=90,
        )
        for entry in profile["browser_history"][:10]:
            assert "url" in entry
            url = entry["url"]
            assert url.startswith("http://") or url.startswith("https://")


# ═══════════════════════════════════════════════════════════════════════
# AGE / DATE BOUNDARY EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestAgeBoundaries:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_age_1_day(self, forge):
        """Minimum age should still produce some data."""
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=1,
        )
        assert isinstance(profile, dict)

    @pytest.mark.unit
    def test_age_365_days(self, forge):
        """Full year profile should produce substantial data."""
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=365,
        )
        assert len(profile.get("call_logs", [])) > len(
            forge.forge(
                persona_name="Test", persona_email="t@t.com",
                persona_phone="+12125551234", country="US", age_days=30,
            ).get("call_logs", [])
        )

    @pytest.mark.unit
    def test_age_500_days(self, forge):
        """Extended age should work without error."""
        profile = forge.forge(
            persona_name="Test", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=500,
        )
        assert isinstance(profile, dict)
        assert len(profile.get("contacts", [])) > 0


# ═══════════════════════════════════════════════════════════════════════
# COUNTRY / LOCALE VARIANTS
# ═══════════════════════════════════════════════════════════════════════

class TestCountryLocales:

    @pytest.fixture
    def forge(self):
        return AndroidProfileForge()

    @pytest.mark.unit
    def test_us_locale(self, forge):
        profile = forge.forge(
            persona_name="Test US", persona_email="t@t.com",
            persona_phone="+12125551234", country="US", age_days=30,
        )
        assert isinstance(profile, dict)

    @pytest.mark.unit
    def test_gb_locale(self, forge):
        profile = forge.forge(
            persona_name="Test UK", persona_email="t@t.com",
            persona_phone="+447911123456", country="GB", age_days=30,
        )
        assert isinstance(profile, dict)

    @pytest.mark.unit
    def test_de_locale(self, forge):
        profile = forge.forge(
            persona_name="Test DE", persona_email="t@t.com",
            persona_phone="+491511234567", country="DE", age_days=30,
        )
        assert isinstance(profile, dict)
