"""
Titan V11.3 — Profile Injector Unit Tests
Tests InjectionResult dataclass, SQLite batch injection logic,
trust score computation, and browser resolution.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from profile_injector import InjectionResult


# ═══════════════════════════════════════════════════════════════════════
# INJECTION RESULT DATACLASS
# ═══════════════════════════════════════════════════════════════════════

class TestInjectionResult:

    @pytest.mark.unit
    def test_default_values(self):
        r = InjectionResult()
        assert r.cookies_injected == 0
        assert r.contacts_injected == 0
        assert r.trust_score == 0
        assert r.errors == []

    @pytest.mark.unit
    def test_to_dict_structure(self):
        r = InjectionResult(
            device_id="127.0.0.1:6520",
            profile_id="TEST-123",
            cookies_injected=72,
            history_injected=500,
            contacts_injected=268,
            call_logs_injected=368,
            sms_injected=180,
            photos_injected=50,
            wallet_ok=True,
            trust_score=84,
        )
        d = r.to_dict()
        assert d["device_id"] == "127.0.0.1:6520"
        assert d["profile_id"] == "TEST-123"
        assert d["cookies"] == 72
        assert d["history"] == 500
        assert d["contacts"] == 268
        assert d["call_logs"] == 368
        assert d["sms"] == 180
        assert d["photos"] == 50
        assert d["wallet"] is True
        assert d["trust_score"] == 84

    @pytest.mark.unit
    def test_to_dict_total_items(self):
        r = InjectionResult(
            cookies_injected=10,
            history_injected=20,
            localstorage_injected=5,
            contacts_injected=30,
            call_logs_injected=40,
            sms_injected=15,
            photos_injected=8,
            autofill_injected=3,
        )
        d = r.to_dict()
        assert d["total_items"] == 10 + 20 + 5 + 30 + 40 + 15 + 8 + 3

    @pytest.mark.unit
    def test_errors_list(self):
        r = InjectionResult()
        r.errors.append("contacts: DB locked")
        r.errors.append("wallet: module not found")
        d = r.to_dict()
        assert len(d["errors"]) == 2
        assert "contacts: DB locked" in d["errors"]


# ═══════════════════════════════════════════════════════════════════════
# SQLITE BATCH INJECTION LOGIC (offline — uses temp DBs)
# ═══════════════════════════════════════════════════════════════════════

class TestContactsSQLiteBatch:
    """Test the SQLite batch injection pattern used for contacts."""

    @pytest.mark.unit
    def test_contacts_db_insert(self, tmp_path):
        """Simulate the SQLite batch pattern used in _inject_contacts."""
        db_path = str(tmp_path / "contacts2.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Create minimal contacts2.db schema
        c.execute("""CREATE TABLE raw_contacts (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name TEXT,
            account_type TEXT,
            display_name TEXT,
            times_contacted INTEGER DEFAULT 0,
            last_time_contacted INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE data (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_contact_id INTEGER,
            mimetype_id INTEGER,
            data1 TEXT, data2 TEXT, data3 TEXT,
            data4 TEXT, data14 TEXT, data15 TEXT
        )""")
        conn.commit()

        # Simulate batch injection
        contacts = [
            {"name": "Alice Smith", "phone": "+12125559001", "email": "alice@test.com"},
            {"name": "Bob Jones", "phone": "+12125559002", "email": "bob@test.com"},
            {"name": "Carol White", "phone": "+12125559003", "email": ""},
        ]

        for contact in contacts:
            c.execute(
                "INSERT INTO raw_contacts (account_name, account_type, display_name) VALUES (?, ?, ?)",
                ("local", "com.android.contacts", contact["name"]),
            )
            rid = c.lastrowid
            c.execute(
                "INSERT INTO data (raw_contact_id, mimetype_id, data1) VALUES (?, ?, ?)",
                (rid, 7, contact["name"]),
            )
            c.execute(
                "INSERT INTO data (raw_contact_id, mimetype_id, data1) VALUES (?, ?, ?)",
                (rid, 5, contact["phone"]),
            )
            if contact.get("email"):
                c.execute(
                    "INSERT INTO data (raw_contact_id, mimetype_id, data1) VALUES (?, ?, ?)",
                    (rid, 1, contact["email"]),
                )
        conn.commit()

        # Verify
        assert c.execute("SELECT COUNT(*) FROM raw_contacts").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM data").fetchone()[0] == 8  # 3 names + 3 phones + 2 emails
        conn.close()


class TestCallLogsSQLiteBatch:

    @pytest.mark.unit
    def test_call_logs_insert(self, tmp_path):
        """Simulate SQLite batch injection for call logs."""
        db_path = str(tmp_path / "calllog.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute("""CREATE TABLE calls (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT, type INTEGER, duration INTEGER,
            date INTEGER, new INTEGER DEFAULT 0,
            name TEXT, numbertype INTEGER DEFAULT 0
        )""")
        conn.commit()

        logs = [
            {"number": "+12125559001", "type": 1, "duration": 120, "date": 1700000000000},
            {"number": "+12125559002", "type": 2, "duration": 60, "date": 1700100000000},
            {"number": "+12125559003", "type": 3, "duration": 0, "date": 1700200000000},
        ]

        for log in logs:
            c.execute(
                "INSERT INTO calls (number, type, duration, date, new) VALUES (?, ?, ?, ?, 0)",
                (log["number"], log["type"], log["duration"], log["date"]),
            )
        conn.commit()

        assert c.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 3
        # Verify incoming call
        row = c.execute("SELECT * FROM calls WHERE type=1").fetchone()
        assert row is not None
        conn.close()


class TestSMSSQLiteBatch:

    @pytest.mark.unit
    def test_sms_insert(self, tmp_path):
        """Simulate SQLite batch injection for SMS."""
        db_path = str(tmp_path / "mmssms.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute("""CREATE TABLE sms (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT, body TEXT, type INTEGER,
            date INTEGER, read INTEGER DEFAULT 1,
            seen INTEGER DEFAULT 1
        )""")
        conn.commit()

        messages = [
            {"address": "+12125559001", "body": "Hey!", "type": 1, "date": 1700000000000},
            {"address": "+12125559002", "body": "See you later", "type": 2, "date": 1700200000000},
        ]

        for msg in messages:
            c.execute(
                "INSERT INTO sms (address, body, type, date, read, seen) VALUES (?, ?, ?, ?, 1, 1)",
                (msg["address"], msg["body"], msg["type"], msg["date"]),
            )
        conn.commit()

        assert c.execute("SELECT COUNT(*) FROM sms").fetchone()[0] == 2
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# BROWSER RESOLUTION
# ═══════════════════════════════════════════════════════════════════════

class TestBrowserResolution:

    @pytest.mark.integration
    def test_chrome_found(self, mock_adb):
        """When Chrome is installed, _resolve_browser_package returns Chrome."""
        mock_adb.set_response("shell pm path com.android.chrome", "package:/system/app/Chrome/Chrome.apk")
        from profile_injector import _resolve_browser_package
        pkg, path = _resolve_browser_package("127.0.0.1:6520")
        assert pkg == "com.android.chrome"
        assert "chrome" in path.lower()

    @pytest.mark.integration
    def test_kiwi_fallback(self, mock_adb):
        """When Chrome is missing, falls back to Kiwi Browser."""
        mock_adb.set_response("shell pm path com.android.chrome", "", returncode=1)
        mock_adb.set_response("shell pm path com.kiwibrowser.browser",
                              "package:/data/app/com.kiwibrowser.browser/base.apk")
        from profile_injector import _resolve_browser_package
        pkg, path = _resolve_browser_package("127.0.0.1:6520")
        assert pkg == "com.kiwibrowser.browser"

    @pytest.mark.integration
    def test_default_when_none_installed(self, mock_adb):
        """When no browser installed, defaults to Chrome paths."""
        mock_adb.set_failure("shell pm path com.android.chrome")
        mock_adb.set_failure("shell pm path com.kiwibrowser.browser")
        from profile_injector import _resolve_browser_package
        pkg, path = _resolve_browser_package("127.0.0.1:6520")
        # Should still return a valid package name
        assert isinstance(pkg, str)
        assert len(pkg) > 0
