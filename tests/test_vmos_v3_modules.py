"""
Tests for VMOS Genesis Engine V3 new modules:
  - google_master_auth.py
  - vmos_db_builder.py
  - vmos_file_pusher.py
  - coherence_bridge.py  (V3 Nexus OBLIVION)
"""

from __future__ import annotations

import asyncio
import base64
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure core is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


# ══════════════════════════════════════════════════════════════════════════════
# google_master_auth tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthResult:
    def _make_result(self, has_real: bool = False, has_synthetic: bool = True):
        from google_master_auth import AuthResult, AuthMethod
        r = AuthResult(email="test@gmail.com", method=AuthMethod.MASTER_TOKEN)
        if has_real:
            r.master_token = "aas_et/REAL_TOKEN"
            r.tokens = {
                "oauth2:https://www.googleapis.com/auth/plus.me": "ya29.real_token",
                "oauth2:https://www.googleapis.com/auth/gmail.readonly": "ya29.gmail",
            }
            r.success = True
        if has_synthetic:
            r.synthetic_tokens = {
                "com.google": "ya29.synth",
                "SID": "a" * 60,
                "LSID": "b" * 60,
            }
        return r

    def test_has_real_tokens_true(self):
        r = self._make_result(has_real=True)
        assert r.has_real_tokens is True

    def test_has_real_tokens_false_without_master_token(self):
        r = self._make_result(has_real=False)
        assert r.has_real_tokens is False

    def test_primary_token_from_real(self):
        r = self._make_result(has_real=True)
        assert r.primary_token.startswith("ya29.real_token")

    def test_all_tokens_for_injection_real(self):
        r = self._make_result(has_real=True)
        tokens = r.all_tokens_for_injection()
        assert "com.google" in tokens
        assert "oauth2:https://www.googleapis.com/auth/plus.me" in tokens

    def test_all_tokens_for_injection_fallback_to_synthetic(self):
        r = self._make_result(has_real=False, has_synthetic=True)
        tokens = r.all_tokens_for_injection()
        assert "com.google" in tokens  # always added

    def test_to_dict(self):
        r = self._make_result(has_real=True)
        d = r.to_dict()
        assert d["success"] is True
        assert d["has_real_tokens"] is True
        assert d["token_count"] == 2


class TestGoogleMasterAuth:
    def test_synthetic_tokens_generated(self):
        from google_master_auth import GoogleMasterAuth, AuthMethod
        auth = GoogleMasterAuth()
        # No network in sandbox — should gracefully degrade to synthetic
        r = auth.authenticate("test@gmail.com", "", method=AuthMethod.MASTER_TOKEN)
        assert len(r.synthetic_tokens) > 0
        # Account should be injectable even without real tokens
        tokens = r.all_tokens_for_injection()
        assert "com.google" in tokens

    def test_hybrid_method_c(self):
        from google_master_auth import GoogleMasterAuth, AuthMethod
        auth = GoogleMasterAuth()
        r = auth.authenticate("test@gmail.com", "secret", method=AuthMethod.HYBRID_INJECT)
        assert r.success is True
        assert hasattr(r, "_hybrid_password")
        assert r._hybrid_password == "secret"
        assert len(r.all_tokens_for_injection()) > 0

    def test_ui_automation_method_returns_error(self):
        from google_master_auth import GoogleMasterAuth, AuthMethod
        auth = GoogleMasterAuth()
        r = auth.authenticate("test@gmail.com", "", method=AuthMethod.UI_AUTOMATION)
        assert any("GoogleAccountCreator" in e for e in r.errors)

    def test_totp_generation(self):
        from google_master_auth import GoogleMasterAuth
        # RFC 6238 test vector (base32 key "JBSWY3DPEHPK3PXP")
        code = GoogleMasterAuth._generate_totp("JBSWY3DPEHPK3PXP")
        assert len(code) == 6
        assert code.isdigit()

    def test_totp_invalid_secret(self):
        from google_master_auth import GoogleMasterAuth
        code = GoogleMasterAuth._generate_totp("NOT_VALID_BASE32!!!")
        assert code == ""

    def test_make_synthetic_tokens_structure(self):
        from google_master_auth import GoogleMasterAuth
        tokens = GoogleMasterAuth._make_synthetic_tokens("user@gmail.com")
        assert "com.google" in tokens
        assert "SID" in tokens
        assert "LSID" in tokens
        # All oauth2 scopes should be present
        assert "oauth2:https://www.googleapis.com/auth/plus.me" in tokens


# ══════════════════════════════════════════════════════════════════════════════
# vmos_db_builder tests
# ══════════════════════════════════════════════════════════════════════════════

class TestVMOSDbBuilder:
    @pytest.fixture
    def builder(self):
        from vmos_db_builder import VMOSDbBuilder
        return VMOSDbBuilder()

    def _open_bytes(self, data: bytes) -> sqlite3.Connection:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return sqlite3.connect(tmp_path), tmp_path

    # ── accounts_ce.db ────────────────────────────────────────────────

    def test_build_accounts_ce_returns_valid_sqlite(self, builder):
        data = builder.build_accounts_ce("user@gmail.com", "User Name")
        assert data[:6] == b"SQLite"
        assert len(data) > 1000

    def test_build_accounts_ce_inserts_account_row(self, builder):
        tokens = {"com.google": "ya29.real_token"}
        data = builder.build_accounts_ce("user@gmail.com", "Jane Doe", tokens=tokens)
        conn, path = self._open_bytes(data)
        rows = conn.execute("SELECT name, type FROM accounts").fetchall()
        conn.close()
        Path(path).unlink()
        assert any(r[0] == "user@gmail.com" and r[1] == "com.google" for r in rows)

    def test_build_accounts_ce_inserts_tokens(self, builder):
        tokens = {
            "com.google": "ya29.real",
            "oauth2:https://www.googleapis.com/auth/plus.me": "ya29.plus",
        }
        data = builder.build_accounts_ce("user@gmail.com", tokens=tokens)
        conn, path = self._open_bytes(data)
        token_rows = conn.execute("SELECT type, authtoken FROM authtokens").fetchall()
        conn.close()
        Path(path).unlink()
        token_dict = dict(token_rows)
        assert token_dict.get("com.google") == "ya29.real"
        assert "oauth2:https://www.googleapis.com/auth/plus.me" in token_dict

    def test_build_accounts_ce_stores_gaia_id(self, builder):
        data = builder.build_accounts_ce("user@gmail.com", gaia_id="117234567890")
        conn, path = self._open_bytes(data)
        row = conn.execute(
            "SELECT value FROM extras WHERE key='google.services.gaia'"
        ).fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        assert row[0] == "117234567890"

    def test_build_accounts_ce_stores_password_for_hybrid(self, builder):
        data = builder.build_accounts_ce("user@gmail.com", password="secret")
        conn, path = self._open_bytes(data)
        row = conn.execute(
            "SELECT password FROM accounts WHERE name='user@gmail.com'"
        ).fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        assert row[0] == "secret"

    def test_build_accounts_ce_user_version(self, builder):
        data = builder.build_accounts_ce("user@gmail.com")
        conn, path = self._open_bytes(data)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        Path(path).unlink()
        assert ver == 10

    def test_build_accounts_de_returns_valid_sqlite(self, builder):
        data = builder.build_accounts_de("user@gmail.com")
        assert data[:6] == b"SQLite"
        conn, path = self._open_bytes(data)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        Path(path).unlink()
        assert ver == 3

    # ── tapandpay.db ──────────────────────────────────────────────────

    def test_build_tapandpay_returns_valid_sqlite(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        assert data[:6] == b"SQLite"

    def test_build_tapandpay_inserts_token_metadata(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        rows = conn.execute("SELECT last_four, network FROM token_metadata").fetchall()
        conn.close()
        Path(path).unlink()
        assert len(rows) == 1
        assert rows[0][0] == "1111"
        assert rows[0][1] == 1  # Visa

    def test_build_tapandpay_mastercard_network_id(self, builder):
        data = builder.build_tapandpay("5100000000000040", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT network FROM token_metadata").fetchone()
        conn.close()
        Path(path).unlink()
        assert row[0] == 2  # Mastercard

    def test_build_tapandpay_emv_key_present(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT luk_hex, atc FROM session_keys").fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        assert len(row[0]) == 32  # 16 bytes hex

    def test_build_tapandpay_dpan_uses_tsp_bin(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT dpan FROM token_metadata").fetchone()
        conn.close()
        Path(path).unlink()
        dpan = row[0]
        # DPAN must NOT start with the original card BIN (4111)
        assert not dpan.startswith("4111")
        # Must be 16 digits
        assert dpan.isdigit()
        assert len(dpan) == 16

    # ── library.db ────────────────────────────────────────────────────

    def test_build_library_returns_valid_sqlite(self, builder):
        data = builder.build_library("user@gmail.com")
        assert data[:6] == b"SQLite"

    def test_build_library_auto_generates_purchases(self, builder):
        data = builder.build_library("user@gmail.com", num_auto_purchases=5)
        conn, path = self._open_bytes(data)
        count = conn.execute("SELECT COUNT(*) FROM ownership").fetchone()[0]
        conn.close()
        Path(path).unlink()
        assert count == 5

    def test_build_library_explicit_purchases(self, builder):
        purchases = [
            {"app_id": "com.spotify.music", "purchase_time_ms": int(time.time() * 1000)},
            {"app_id": "com.netflix.mediaclient"},
        ]
        data = builder.build_library("user@gmail.com", purchases=purchases)
        conn, path = self._open_bytes(data)
        rows = conn.execute("SELECT doc_id FROM ownership ORDER BY doc_id").fetchall()
        conn.close()
        Path(path).unlink()
        pkg_names = [r[0] for r in rows]
        assert "com.spotify.music" in pkg_names
        assert "com.netflix.mediaclient" in pkg_names

    def test_build_library_generates_gpa_order_ids(self, builder):
        data = builder.build_library("user@gmail.com", num_auto_purchases=3)
        conn, path = self._open_bytes(data)
        rows = conn.execute("SELECT order_id FROM ownership").fetchall()
        conn.close()
        Path(path).unlink()
        for (order_id,) in rows:
            assert order_id.startswith("GPA.")

    def test_generate_order_id_format(self):
        from vmos_db_builder import _generate_order_id
        for _ in range(10):
            oid = _generate_order_id()
            parts = oid.replace("GPA.", "").split("-")
            assert len(parts) == 4
            assert len(parts[3]) == 5


# ══════════════════════════════════════════════════════════════════════════════
# vmos_file_pusher tests
# ══════════════════════════════════════════════════════════════════════════════

class TestVMOSFilePusher:
    def _make_pusher(self):
        """Return a VMOSFilePusher with a fully mocked VMOSCloudClient."""
        from vmos_file_pusher import VMOSFilePusher

        client = MagicMock()

        async def _async_cmd(pads, cmd):
            return {"code": 200, "data": [{"taskId": "TASK001"}]}

        async def _task_detail(task_ids):
            return {
                "code": 200,
                "data": [{"taskStatus": 3, "taskResult": "CHUNK_OK\nDECODE_OK\nPERMS_OK\nOK\nCHOWN_OK"}],
            }

        client.async_adb_cmd = AsyncMock(side_effect=_async_cmd)
        client.task_detail = AsyncMock(side_effect=_task_detail)

        pusher = VMOSFilePusher(client, "PAD001", shell_timeout=5, inter_chunk_delay=0.0)
        return pusher, client

    @pytest.mark.asyncio
    async def test_push_bytes_returns_true_on_success(self):
        pusher, _ = self._make_pusher()
        ok = await pusher.push_bytes(b"Hello World", "/tmp/test.txt", mode="644")
        assert ok is True

    @pytest.mark.asyncio
    async def test_push_empty_data_returns_false(self):
        pusher, _ = self._make_pusher()
        ok = await pusher.push_bytes(b"", "/tmp/test.txt")
        assert ok is False

    @pytest.mark.asyncio
    async def test_push_text_calls_push_bytes(self):
        pusher, _ = self._make_pusher()
        with patch.object(pusher, "push_bytes", new_callable=AsyncMock, return_value=True) as mock_pb:
            ok = await pusher.push_text("hello", "/tmp/test.txt")
            assert ok is True
            mock_pb.assert_called_once()
            # First positional argument is the data bytes
            call_args = mock_pb.call_args
            actual_data = call_args[0][0] if call_args[0] else call_args.kwargs.get("data")
            assert actual_data == b"hello"

    @pytest.mark.asyncio
    async def test_push_xml_pref_sets_permissions(self):
        pusher, client = self._make_pusher()
        xml = '<?xml version="1.0"?><map><boolean name="ok" value="true" /></map>'
        ok = await pusher.push_xml_pref(xml, "/data/data/pkg/shared_prefs/test.xml",
                                        pkg_dir="/data/data/pkg")
        assert ok is True

    @pytest.mark.asyncio
    async def test_push_bytes_encodes_as_base64_chunks(self):
        from vmos_file_pusher import _CHUNK_BYTES
        pusher, client = self._make_pusher()

        # 8KB of data → multiple chunks
        data = b"A" * 8192
        await pusher.push_bytes(data, "/tmp/large.bin")

        # Should have called async_adb_cmd multiple times (one per chunk + decode + perms)
        assert client.async_adb_cmd.call_count > 1

    @pytest.mark.asyncio
    async def test_sh_returns_false_on_api_error(self):
        from vmos_file_pusher import VMOSFilePusher

        client = MagicMock()
        client.async_adb_cmd = AsyncMock(return_value={"code": 500, "msg": "error"})
        client.task_detail = AsyncMock(return_value={"code": 200, "data": []})

        pusher = VMOSFilePusher(client, "PAD001", shell_timeout=2, inter_chunk_delay=0.0)
        result = await pusher._sh("echo OK", marker="OK")
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# V3 Nexus OBLIVION — enhanced tapandpay.db + coherence_bridge tests
# ══════════════════════════════════════════════════════════════════════════════

class TestOblivionTapandpay:
    """Tests for the V3 Nexus 5-table tapandpay.db schema."""

    @pytest.fixture
    def builder(self):
        from vmos_db_builder import VMOSDbBuilder
        return VMOSDbBuilder()

    def _open_bytes(self, data: bytes):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        conn = sqlite3.connect(tmp_path)
        return conn, tmp_path

    def test_all_five_tables_present(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        Path(path).unlink()
        assert "tokens" in tables
        assert "token_metadata" in tables
        assert "emv_metadata" in tables
        assert "session_keys" in tables
        assert "transaction_history" in tables

    def test_tokens_table_has_tsp_bin(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT dpan, tsp FROM tokens").fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        dpan, tsp = row
        # DPAN must use Visa TSP BIN (489537–489539 or 440066–440067)
        assert any(dpan.startswith(b) for b in ["489537", "489538", "489539", "440066", "440067"])
        assert tsp == "VISA_TSP"

    def test_emv_metadata_cvn17(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT cvn, cryptogram_version FROM emv_metadata").fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        assert row[0] == 17   # CVN 17
        assert row[1] == 17   # cryptogram_version = 17

    def test_session_keys_luk_16_bytes(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT luk_hex, atc FROM session_keys").fetchone()
        conn.close()
        Path(path).unlink()
        assert row is not None
        luk_hex, atc = row
        assert len(luk_hex) == 32  # 16 bytes as hex
        assert atc > 0

    def test_transaction_history_backdated(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe",
                                       age_days=90)
        conn, path = self._open_bytes(data)
        rows = conn.execute(
            "SELECT merchant_name, amount_cents, arqc, atc FROM transaction_history"
        ).fetchall()
        conn.close()
        Path(path).unlink()
        assert len(rows) > 0
        for merchant_name, amount_cents, arqc, atc in rows:
            assert merchant_name  # non-empty merchant
            assert amount_cents > 0
            assert len(arqc) == 16  # 8-byte ARQC as hex
            assert atc >= 0

    def test_transaction_history_arqcs_are_unique(self, builder):
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        arqcs = [r[0] for r in conn.execute("SELECT arqc FROM transaction_history").fetchall()]
        conn.close()
        Path(path).unlink()
        # With different ATC values, ARQCs should differ
        assert len(set(arqcs)) > 1

    def test_mastercard_uses_mc_tsp(self, builder):
        data = builder.build_tapandpay("5100000000000040", 12, 2027, "Jane Doe")
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT dpan, tsp FROM tokens").fetchone()
        conn.close()
        Path(path).unlink()
        assert row[1] == "MC_TSP"
        assert any(row[0].startswith(b)
                   for b in ["530060", "530061", "530062", "530063", "530064", "530065"])

    def test_custom_transaction_entries(self, builder):
        custom_txs = [
            {"merchant_name": "Starbucks", "merchant_category": "5814",
             "amount_cents": 650, "currency": "USD", "arqc": "AABBCCDD11223344",
             "atc": 7, "timestamp_ms": int(time.time() * 1000)},
        ]
        data = builder.build_tapandpay("4111111111111111", 12, 2027, "Jane Doe",
                                       transaction_entries=custom_txs)
        conn, path = self._open_bytes(data)
        row = conn.execute("SELECT merchant_name, arqc FROM transaction_history").fetchone()
        conn.close()
        Path(path).unlink()
        assert row[0] == "Starbucks"
        assert row[1] == "AABBCCDD11223344"


class TestEMVHelpers:
    """Tests for module-level EMV/LUK helpers."""

    def test_derive_luk_deterministic(self):
        from vmos_db_builder import _derive_luk
        luk1 = _derive_luk("4895370000001234", 10)
        luk2 = _derive_luk("4895370000001234", 10)
        assert luk1 == luk2
        assert len(luk1) == 16

    def test_derive_luk_different_atc(self):
        from vmos_db_builder import _derive_luk
        luk_a = _derive_luk("4895370000001234", 10)
        luk_b = _derive_luk("4895370000001234", 11)
        assert luk_a != luk_b

    def test_generate_arqc_format(self):
        from vmos_db_builder import _derive_luk, _generate_arqc
        luk = _derive_luk("4895370000001234", 10)
        arqc = _generate_arqc(luk, 1499, 10)
        assert len(arqc) == 16
        assert arqc == arqc.upper()
        assert all(c in "0123456789ABCDEF" for c in arqc)


class TestCoherenceData:
    """Tests for VMOSDbBuilder.build_coherence_data()."""

    @pytest.fixture
    def builder(self):
        from vmos_db_builder import VMOSDbBuilder
        return VMOSDbBuilder()

    def test_generates_correct_order_count(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=5)
        assert len(data["order_ids"]) == 5
        assert len(data["tx_entries"]) == 5
        assert len(data["browser_urls"]) == 5
        assert len(data["cookie_rows"]) == 5
        assert len(data["receipt_subjects"]) == 5

    def test_order_ids_are_gpa_format(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=3)
        for oid in data["order_ids"]:
            assert oid.startswith("GPA.")
            parts = oid[4:].split("-")
            assert len(parts) == 4

    def test_browser_urls_reference_merchant_domains(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=3)
        for entry in data["browser_urls"]:
            assert entry["url"].startswith("https://")
            assert "/orders/GPA." in entry["url"]

    def test_cookie_rows_have_required_fields(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=3)
        for cookie in data["cookie_rows"]:
            assert "host_key" in cookie
            assert "name" in cookie
            assert "value" in cookie
            assert cookie["is_secure"] == 1

    def test_receipt_subjects_contain_order_id(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=3)
        for i, subject in enumerate(data["receipt_subjects"]):
            order_id = data["order_ids"][i]
            assert order_id in subject

    def test_pre_built_order_ids_used(self, builder):
        custom_ids = ["GPA.1234-5678-9012-34567", "GPA.ABCD-EFGH-IJKL-MNOPQ"]
        data = builder.build_coherence_data("user@gmail.com", order_ids=custom_ids)
        assert data["order_ids"] == custom_ids

    def test_gb_country_uses_gbp_currency(self, builder):
        data = builder.build_coherence_data("user@gmail.com", num_orders=4, country="GB")
        for tx in data["tx_entries"]:
            assert tx["currency"] == "GBP"


class TestCoherenceBridge:
    """Tests for the CoherenceBridge orchestrator."""

    def _make_bridge(self):
        from vmos_db_builder import VMOSDbBuilder
        from coherence_bridge import CoherenceBridge
        from vmos_file_pusher import VMOSFilePusher

        client = MagicMock()

        async def _async_cmd(pads, cmd):
            return {"code": 200, "data": [{"taskId": "TASK001"}]}

        # Return a marker string that satisfies ALL checks used in the bridge:
        # - pusher._sh: CHUNK_OK, DECODE_OK, PERMS_OK, OK, CHOWN_OK
        # - chrome injections: HISTORY_DONE, COOKIES_DONE
        _ALL_MARKERS = (
            "CHUNK_OK\nDECODE_OK\nPERMS_OK\nOK\nCHOWN_OK\n"
            "HISTORY_DONE\nCOOKIES_DONE"
        )

        async def _task_detail(task_ids):
            return {
                "code": 200,
                "data": [{"taskStatus": 3, "taskResult": _ALL_MARKERS}],
            }

        client.async_adb_cmd = AsyncMock(side_effect=_async_cmd)
        client.task_detail = AsyncMock(side_effect=_task_detail)

        pusher = VMOSFilePusher(client, "PAD001", shell_timeout=5, inter_chunk_delay=0.0)
        builder = VMOSDbBuilder()
        return CoherenceBridge(pusher, builder)

    @pytest.mark.asyncio
    async def test_inject_all_returns_result(self):
        bridge = self._make_bridge()
        result = await bridge.inject_all(
            email="user@gmail.com", country="US", age_days=30, num_orders=3
        )
        assert len(result.order_ids) == 3
        assert result.summary()

    @pytest.mark.asyncio
    async def test_inject_all_sets_gmail_xml(self):
        bridge = self._make_bridge()
        result = await bridge.inject_all(
            email="user@gmail.com", country="US", age_days=30, num_orders=3
        )
        assert result.gmail_xml_ok is True

    @pytest.mark.asyncio
    async def test_inject_all_library_db_ok(self):
        bridge = self._make_bridge()
        result = await bridge.inject_all(
            email="user@gmail.com", country="US", age_days=30, num_orders=3
        )
        assert result.library_db_ok is True

    @pytest.mark.asyncio
    async def test_inject_all_uses_existing_order_ids(self):
        bridge = self._make_bridge()
        custom = ["GPA.AAAA-BBBB-CCCC-DDDDD"]
        result = await bridge.inject_all(
            email="user@gmail.com", existing_order_ids=custom, num_orders=1
        )
        assert result.order_ids == custom

    def test_coherence_result_summary_format(self):
        from coherence_bridge import CoherenceResult
        r = CoherenceResult(
            order_ids=["GPA.X", "GPA.Y"],
            chrome_history_ok=True,
            chrome_cookies_ok=True,
            gmail_xml_ok=True,
            library_db_ok=False,
        )
        s = r.summary()
        assert "orders=2" in s
        assert "history=ok" in s
        assert "library=fail" in s

    def test_coherence_result_to_dict(self):
        from coherence_bridge import CoherenceResult
        r = CoherenceResult(
            order_ids=["GPA.X"],
            chrome_history_ok=True,
            chrome_cookies_ok=False,
        )
        d = r.to_dict()
        assert d["chrome_history"] is True
        assert d["chrome_cookies"] is False
        assert d["success_count"] == 1
