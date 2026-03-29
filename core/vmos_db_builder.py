"""
Titan V13.0 — VMOS Database Builder
=====================================
Constructs Android SQLite databases **host-side** and returns them as raw bytes
so they can be pushed to a VMOS Cloud device (which has no ``sqlite3`` binary).

Supported databases
-------------------
* ``accounts_ce.db``  — Credential-encrypted Google account store (Android 7+)
* ``tapandpay.db``    — Google Pay / Wallet token store
* ``library.db``      — Google Play Store purchase history

All schema versions match Android 13 (API 33) / GMS 24.09.x.

Usage::

    from vmos_db_builder import VMOSDbBuilder

    builder = VMOSDbBuilder()

    # Build accounts DB with real or synthetic tokens
    accts_bytes = builder.build_accounts_ce(
        email="user@gmail.com",
        display_name="Jane Doe",
        gaia_id="117234567890",
        tokens={"com.google": "ya29.real...", ...},
    )

    # Build wallet DB
    wallet_bytes = builder.build_tapandpay(
        card_number="4532015112830366",
        exp_month=12, exp_year=2027,
        cardholder="Jane Doe",
    )

    # Build Play Store purchase history
    library_bytes = builder.build_library(
        email="user@gmail.com",
        purchases=[
            {"app_id": "com.spotify.music", "purchase_time_ms": ..., "price_micros": 0},
        ],
    )
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import logging
import random
import secrets
import sqlite3
import string
import struct
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.vmos-db-builder")

# ── Circadian transaction distribution weights ────────────────────────────────
# Weighted toward business hours (7 am–7 pm).  Index = hour of day (0–23).
_CIRCADIAN_WEIGHTS = [
    1, 1, 1, 1, 1, 1,    # 00–05 (night, very low)
    2, 4, 6, 8, 10, 10,  # 06–11 (morning ramp-up, commute, coffee)
    9, 10, 10, 9,         # 12–15 (lunch, afternoon peak)
    8, 8, 7, 6, 5, 4,    # 16–21 (evening, dinner, winding down)
    2, 1,                 # 22–23 (late night, very low)
]

# ── Token BIN ranges for DPAN generation (mirrors wallet_provisioner) ─────────

_TOKEN_BIN_RANGES: Dict[str, List[str]] = {
    "visa":       ["489537", "489538", "489539", "440066", "440067"],
    "mastercard": ["530060", "530061", "530062", "530063", "530064", "530065"],
    "amex":       ["374800", "374801"],
    "discover":   ["601156", "601157"],
}


def _detect_network(card_number: str) -> str:
    num = card_number.replace(" ", "").replace("-", "")
    if num.startswith("4"):
        return "visa"
    if num[:2] in ("51", "52", "53", "54", "55"):
        return "mastercard"
    if num[:2] in ("34", "37"):
        return "amex"
    if num.startswith("6"):
        return "discover"
    return "visa"


def _generate_dpan(card_number: str) -> str:
    """Generate a TSP-assigned Device PAN (DPAN) with valid Luhn check digit."""
    num = card_number.replace(" ", "").replace("-", "")
    network = _detect_network(num)
    bins = _TOKEN_BIN_RANGES.get(network, _TOKEN_BIN_RANGES["visa"])
    token_bin = random.choice(bins)
    remaining = len(num) - 7  # -6 BIN, -1 check
    body = "".join(str(random.randint(0, 9)) for _ in range(remaining))
    partial = token_bin + body
    digits = [int(d) for d in partial]
    total = sum(
        (d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 == 0 else d
        for i, d in enumerate(reversed(digits))
    )
    check = (10 - total % 10) % 10
    return partial + str(check)


def _generate_order_id() -> str:
    """Generate a realistic Google Play order ID (GPA.XXXX-XXXX-XXXX-XXXXX)."""
    chars = string.digits + string.ascii_uppercase
    parts = [
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=4)),
        "".join(random.choices(chars, k=5)),
    ]
    return f"GPA.{'-'.join(parts)}"


# ── EMV / LUK derivation (full OBLIVION implementation) ─────────────────────

def _derive_luk(dpan: str, atc: int, mdk_seed: Optional[bytes] = None) -> bytes:
    """Derive a Limited Use Key (LUK) using HMAC-SHA256 (EMV CDA approximation).

    Returns 16 bytes — double-length 3DES key size for DB compatibility.
    NOTE: Functional for DB population / ARQC generation.  Real terminal
    verification uses 3DES-MAC with hardware HSM keys.
    """
    if mdk_seed is None:
        mdk_seed = hashlib.sha256(f"TITAN-MDK-{dpan}".encode()).digest()[:16]
    pan_block = dpan[-13:-1].encode()
    udk = _hmac_mod.new(mdk_seed, pan_block, hashlib.sha256).digest()[:16]
    atc_block = struct.pack(">I", atc)
    return _hmac_mod.new(udk, atc_block, hashlib.sha256).digest()[:16]


def _generate_arqc(luk: bytes, amount_cents: int, atc: int) -> str:
    """Generate an ARQC (Authorization Request Cryptogram) matching CVN 17 format.

    CVN 17 (Cryptogram Version Number) is the EMV mode used by Visa contactless
    tokens.  This produces an 8-byte (16 hex char) cryptogram.
    """
    un = secrets.token_bytes(4)
    txn_data = struct.pack(">IH", amount_cents, atc & 0xFFFF) + un
    mac = _hmac_mod.new(luk, txn_data, hashlib.sha256).digest()[:8]
    return mac.hex().upper()


# ── Regional merchant sets for coherent transaction history ───────────────────

_MERCHANTS: Dict[str, List[Tuple[str, str, int, int]]] = {
    # (merchant_name, merchant_category_code, min_cents, max_cents)
    "US": [
        ("Starbucks",       "5814",  450,  1250),
        ("Amazon.com",      "5942",  999, 14999),
        ("Target",          "5411", 1299,  8999),
        ("Whole Foods",     "5411", 2199, 12500),
        ("Shell Gas",       "5541", 3500,  6500),
        ("Uber",            "4121",  899,  4500),
        ("Walgreens",       "5912",  399,  2999),
        ("Netflix",         "4899", 1599,  1599),
        ("Spotify",         "4899", 1099,  1099),
        ("McDonald's",      "5812",  699,  1299),
        ("Chipotle",        "5812",  899,  1599),
        ("Trader Joe's",    "5411", 1500,  7500),
        ("CVS Pharmacy",    "5912",  499,  3999),
        ("Costco",          "5311", 4999, 24999),
        ("Home Depot",      "5251", 2999, 29999),
        ("Lyft",            "4121",  799,  3500),
        ("DoorDash",        "5812", 1299,  5999),
        ("Apple",           "5732", 1999, 99999),
        ("Best Buy",        "5732", 2999, 149999),
        ("Marriott Hotels", "7011", 8999, 49999),
    ],
    "GB": [
        ("Tesco",           "5411",  850,  7500),
        ("Sainsburys",      "5411", 1200,  9500),
        ("Costa Coffee",    "5814",  295,   595),
        ("BP",              "5541", 3000,  6500),
        ("Amazon.co.uk",    "5942",  899, 12999),
        ("Boots",           "5912",  450,  3200),
        ("Uber",            "4121",  700,  3500),
        ("Deliveroo",       "5812", 1100,  3500),
        ("Netflix",         "4899", 1099,  1099),
        ("TfL Contactless", "4111",  260,  1400),
    ],
    "DE": [
        ("REWE",            "5411",  900,  8500),
        ("Lidl",            "5411",  600,  5000),
        ("Amazon.de",       "5942",  999, 14999),
        ("Shell",           "5541", 3500,  7000),
        ("Deutsche Bahn",   "4111", 2500, 12000),
        ("Netflix",         "4899", 1299,  1299),
        ("Spotify",         "4899",  999,   999),
    ],
}


# ── Builder class ─────────────────────────────────────────────────────────────

class VMOSDbBuilder:
    """Build Android SQLite databases host-side and return them as bytes."""

    # ── accounts_ce.db ────────────────────────────────────────────────

    def build_accounts_ce(
        self,
        email: str,
        display_name: str = "",
        gaia_id: str = "",
        tokens: Optional[Dict[str, str]] = None,
        password: str = "",
        age_days: int = 90,
    ) -> bytes:
        """Build the credential-encrypted account database (accounts_ce.db).

        Args:
            email: Google account email.
            display_name: Full display name (e.g. "Jane Doe").
            gaia_id: Google user ID (21-digit string).  Generated if empty.
            tokens: Dict of ``{scope: token}`` to store in the ``authtokens``
                table.  When *real* tokens from :class:`GoogleMasterAuth` are
                provided, apps will authenticate without re-prompting.  When
                synthetic tokens are provided, apps show Sign-in Required after
                first sync.
            password: Optional plaintext password stored in the ``accounts``
                ``password`` column so GMS can re-authenticate automatically.
                Leave empty when using Method A real tokens.
            age_days: Account age for metadata timestamps.

        Returns:
            Raw bytes of a valid SQLite3 database.
        """
        if not gaia_id:
            gaia_id = str(random.randint(100_000_000_000, 999_999_999_999_999_999_999))
        if not display_name:
            display_name = email.split("@")[0].replace(".", " ").title()

        parts = display_name.split()
        given_name = parts[0] if parts else ""
        family_name = parts[-1] if len(parts) > 1 else ""

        birth_ts_ms = int((time.time() - age_days * 86400) * 1000)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Android 13 accounts_ce schema (user_version = 10)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    password TEXT,
                    UNIQUE(name, type)
                );
                CREATE TABLE IF NOT EXISTS authtokens (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    authtoken TEXT,
                    UNIQUE(accounts_id, type)
                );
                CREATE TABLE IF NOT EXISTS extras (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER,
                    key TEXT NOT NULL,
                    value TEXT,
                    UNIQUE(accounts_id, key)
                );
                CREATE TABLE IF NOT EXISTS grants (
                    accounts_id INTEGER NOT NULL,
                    auth_token_type TEXT NOT NULL DEFAULT '',
                    uid INTEGER NOT NULL,
                    UNIQUE(accounts_id, auth_token_type, uid)
                );
                CREATE TABLE IF NOT EXISTS shared_accounts (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    UNIQUE(name, type)
                );
                PRAGMA user_version = 10;
            """)

            # Insert account row
            c.execute(
                "INSERT OR REPLACE INTO accounts (name, type, password) VALUES (?, 'com.google', ?)",
                (email, password or ""),
            )
            account_id = c.lastrowid or 1

            # Insert auth tokens
            token_map = tokens or {}
            for scope, token in token_map.items():
                c.execute(
                    "INSERT OR REPLACE INTO authtokens (accounts_id, type, authtoken) VALUES (?, ?, ?)",
                    (account_id, scope, token),
                )

            # Insert extras (metadata)
            extras = [
                ("google.services.gaia", gaia_id),
                ("GoogleUserId", gaia_id),
                ("is_child_account", "false"),
                ("given_name", given_name),
                ("family_name", family_name),
                ("display_name", display_name),
                ("account_creation_time", str(birth_ts_ms)),
                ("last_known_device_id_key", secrets.token_hex(8)),
            ]
            for key, value in extras:
                c.execute(
                    "INSERT OR REPLACE INTO extras (accounts_id, key, value) VALUES (?, ?, ?)",
                    (account_id, key, value),
                )

            # Shared accounts mirror
            c.execute(
                "INSERT OR IGNORE INTO shared_accounts (name, type) VALUES (?, 'com.google')",
                (email,),
            )

            # GMS visibility grants — ensure key system apps can see the account
            GMS_UID = 1021
            VENDING_UID = 10026
            YOUTUBE_UID = 10062
            for uid in (GMS_UID, VENDING_UID, YOUTUBE_UID):
                c.execute(
                    "INSERT OR IGNORE INTO grants (accounts_id, auth_token_type, uid) VALUES (?, '', ?)",
                    (account_id, uid),
                )

            conn.commit()
            conn.close()

            data = Path(tmp_path).read_bytes()
            logger.info("Built accounts_ce.db: email=%s tokens=%d size=%d",
                        email, len(token_map), len(data))
            return data

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def build_accounts_de(
        self,
        email: str,
        display_name: str = "",
        gaia_id: str = "",
        age_days: int = 90,
    ) -> bytes:
        """Build the device-encrypted account database (accounts_de.db).

        The DE database holds structural account info but no auth tokens.
        """
        if not gaia_id:
            gaia_id = str(random.randint(100_000_000_000, 999_999_999_999_999_999_999))
        if not display_name:
            display_name = email.split("@")[0].replace(".", " ").title()

        parts = display_name.split()
        given_name = parts[0] if parts else ""
        family_name = parts[-1] if len(parts) > 1 else ""

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Android 13 accounts_de schema (user_version = 3)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    _id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    previous_name TEXT,
                    last_password_entry_time_millis_epoch INTEGER DEFAULT 0,
                    UNIQUE(name, type)
                );
                CREATE TABLE IF NOT EXISTS grants (
                    accounts_id INTEGER NOT NULL,
                    auth_token_type TEXT NOT NULL DEFAULT '',
                    uid INTEGER NOT NULL,
                    UNIQUE(accounts_id, auth_token_type, uid)
                );
                CREATE TABLE IF NOT EXISTS visibility (
                    accounts_id INTEGER NOT NULL,
                    _package TEXT NOT NULL,
                    value INTEGER,
                    UNIQUE(accounts_id, _package)
                );
                CREATE TABLE IF NOT EXISTS authtokens (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER NOT NULL,
                    type TEXT NOT NULL DEFAULT '',
                    authtoken TEXT,
                    UNIQUE(accounts_id, type)
                );
                CREATE TABLE IF NOT EXISTS extras (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER NOT NULL,
                    key TEXT NOT NULL DEFAULT '',
                    value TEXT,
                    UNIQUE(accounts_id, key)
                );
                PRAGMA user_version = 3;
            """)

            last_entry_ms = int(time.time() * 1000)
            c.execute(
                "INSERT OR REPLACE INTO accounts (name, type, previous_name, last_password_entry_time_millis_epoch) "
                "VALUES (?, 'com.google', NULL, ?)",
                (email, last_entry_ms),
            )
            account_id = c.lastrowid or 1

            for key, value in [("given_name", given_name), ("family_name", family_name),
                                ("display_name", display_name), ("GoogleUserId", gaia_id)]:
                c.execute(
                    "INSERT OR IGNORE INTO extras (accounts_id, key, value) VALUES (?, ?, ?)",
                    (account_id, key, value),
                )

            # Visibility — allow GMS + Play Store to see the account
            for pkg in ("com.google.android.gms", "com.android.vending",
                        "com.google.android.youtube", "com.google.android.gm"):
                c.execute(
                    "INSERT OR IGNORE INTO visibility (accounts_id, _package, value) VALUES (?, ?, 1)",
                    (account_id, pkg),
                )

            conn.commit()
            conn.close()

            data = Path(tmp_path).read_bytes()
            logger.info("Built accounts_de.db: email=%s size=%d", email, len(data))
            return data

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── tapandpay.db — OBLIVION full 5-table schema ───────────────────

    def build_tapandpay(
        self,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cardholder: str,
        issuer: str = "",
        persona_email: str = "",
        zero_auth: bool = True,
        age_days: int = 90,
        country: str = "US",
        transaction_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """Build the Google Pay token database (tapandpay.db) — V3 Nexus OBLIVION.

        Constructs the **full 5-table schema** required for token lifecycle
        survivability against GMS reconciliation:

        * ``tokens`` — Base token record with TSP-BIN DPAN and PROVISIONED status
        * ``token_metadata`` — Display metadata (network, color, issuer)
        * ``emv_metadata`` — CVN 17 configuration, ARQC seed, CVM list
        * ``session_keys`` — Derived LUK + ATC counter for transaction readiness
        * ``transaction_history`` — Backdated merchant transactions for behavioral aging

        The DPAN uses TSP-assigned BIN ranges (e.g. 489537 for Visa) ensuring
        network-legitimacy checks pass.  The ``token_state`` is set to
        ``PROVISIONED`` (3) to skip the activation UI in Google Wallet.

        Args:
            card_number: Full PAN (spaces/dashes stripped automatically).
            exp_month: Expiry month (1–12).
            exp_year: Expiry year (2- or 4-digit).
            cardholder: Name on card.
            issuer: Issuing bank name; auto-detected from BIN if empty.
            persona_email: Google account email for wallet binding.
            zero_auth: If True, token_state reflects zero-auth provisioned mode.
            age_days: Backdating depth for ``added_timestamp`` and tx history.
            country: ISO country for regional merchant tx history.
            transaction_entries: Pre-built tx entries to embed in
                ``transaction_history``.  Auto-generated if None.

        Returns:
            Raw bytes of a valid SQLite3 ``tapandpay.db``.
        """
        cc = card_number.replace(" ", "").replace("-", "")
        last4 = cc[-4:]
        if exp_year < 100:
            exp_year += 2000

        network = _detect_network(cc)
        dpan = _generate_dpan(cc)
        dpan_last4 = dpan[-4:]
        token_ref = secrets.token_hex(16).upper()
        token_id = str(uuid.uuid4()).replace("-", "").upper()[:32]
        instrument_id = f"instrument_{token_id[:12]}"

        network_id = {"visa": 1, "mastercard": 2, "amex": 3, "discover": 4}.get(network, 1)
        network_name = network.capitalize()
        display_name = f"{network_name} ****{last4}"
        card_color = {
            "visa": -16776961, "mastercard": -65536,
            "amex": -16711936, "discover": -19712,
        }.get(network, -12285185)

        if not issuer:
            issuer = self._detect_issuer(cc)

        now_ms = int(time.time() * 1000)
        added_ts_ms = now_ms - age_days * 86400 * 1000

        # ── LUK derivation ──────────────────────────────────────────────
        atc_start = random.randint(5, 30)
        luk = _derive_luk(dpan, atc_start)
        luk_hex = luk.hex().upper()

        # ── Transaction history ─────────────────────────────────────────
        if transaction_entries is None:
            transaction_entries = self._generate_tx_history(
                dpan=dpan, luk=luk, atc_start=atc_start,
                age_days=age_days, country=country, num_entries=random.randint(8, 20),
            )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # ── Full 5-table schema (GMS 24.09 / tapandpay v5) ──────────
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE NOT NULL,
                    dpan TEXT NOT NULL,
                    fpan_suffix TEXT,
                    network_id INTEGER NOT NULL,
                    token_ref TEXT,
                    token_state INTEGER DEFAULT 3,
                    account_name TEXT,
                    instrument_id TEXT,
                    tsp TEXT DEFAULT 'VISA_TSP',
                    added_timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS token_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    dpan TEXT,
                    last_four TEXT,
                    network INTEGER,
                    token_ref TEXT,
                    display_name TEXT,
                    is_default INTEGER DEFAULT 0,
                    card_color INTEGER,
                    token_state INTEGER DEFAULT 3,
                    added_timestamp INTEGER,
                    exp_month INTEGER,
                    exp_year INTEGER,
                    cardholder TEXT,
                    issuer_name TEXT,
                    account_name TEXT,
                    instrument_id TEXT
                );
                CREATE TABLE IF NOT EXISTS emv_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    cvn INTEGER DEFAULT 17,
                    cvm_list TEXT,
                    arqc_seed TEXT,
                    pan_sequence_number INTEGER DEFAULT 0,
                    chip_lifecycle_state INTEGER DEFAULT 1,
                    cryptogram_version INTEGER DEFAULT 17
                );
                CREATE TABLE IF NOT EXISTS session_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    luk_hex TEXT NOT NULL,
                    atc INTEGER DEFAULT 0,
                    expiry_ms INTEGER,
                    max_transactions INTEGER DEFAULT 10,
                    replenishment_threshold INTEGER DEFAULT 2
                );
                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT NOT NULL,
                    merchant_name TEXT,
                    merchant_category TEXT,
                    amount_cents INTEGER,
                    currency TEXT DEFAULT 'USD',
                    arqc TEXT,
                    atc INTEGER,
                    timestamp_ms INTEGER,
                    status TEXT DEFAULT 'APPROVED'
                );
                PRAGMA user_version = 5;
            """)

            # ── tokens row ────────────────────────────────────────────────
            tsp = {"visa": "VISA_TSP", "mastercard": "MC_TSP",
                   "amex": "AMEX_TSP", "discover": "DISC_TSP"}.get(network, "VISA_TSP")
            c.execute(
                "INSERT OR REPLACE INTO tokens "
                "(token_id, dpan, fpan_suffix, network_id, token_ref, "
                " token_state, account_name, instrument_id, tsp, added_timestamp) "
                "VALUES (?, ?, ?, ?, ?, 3, ?, ?, ?, ?)",
                (token_id, dpan, last4, network_id, token_ref,
                 persona_email, instrument_id, tsp, added_ts_ms),
            )

            # ── token_metadata row ────────────────────────────────────────
            c.execute(
                "INSERT OR REPLACE INTO token_metadata "
                "(token_id, dpan, last_four, network, token_ref, display_name, "
                " is_default, card_color, token_state, added_timestamp, "
                " exp_month, exp_year, cardholder, issuer_name, account_name, instrument_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, 3, ?, ?, ?, ?, ?, ?, ?)",
                (token_id, dpan, last4, network_id, token_ref, display_name,
                 card_color, added_ts_ms, exp_month, exp_year,
                 cardholder, issuer, persona_email, instrument_id),
            )

            # ── emv_metadata row (CVN 17) ─────────────────────────────────
            arqc_seed = secrets.token_hex(8).upper()
            cvm_list = "5E031F0000"  # EMV CVM list for CVN 17 contactless
            c.execute(
                "INSERT OR REPLACE INTO emv_metadata "
                "(token_id, cvn, cvm_list, arqc_seed, "
                " pan_sequence_number, chip_lifecycle_state, cryptogram_version) "
                "VALUES (?, 17, ?, ?, 0, 1, 17)",
                (token_id, cvm_list, arqc_seed),
            )

            # ── session_keys row ──────────────────────────────────────────
            current_atc = atc_start + len(transaction_entries)
            c.execute(
                "INSERT OR REPLACE INTO session_keys "
                "(token_id, luk_hex, atc, expiry_ms, max_transactions, replenishment_threshold) "
                "VALUES (?, ?, ?, ?, ?, 2)",
                (token_id, luk_hex, current_atc,
                 now_ms + 86400000,          # 24h expiry
                 random.randint(5, 10)),
            )

            # ── transaction_history rows ──────────────────────────────────
            for tx in transaction_entries:
                c.execute(
                    "INSERT INTO transaction_history "
                    "(token_id, merchant_name, merchant_category, amount_cents, "
                    " currency, arqc, atc, timestamp_ms, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED')",
                    (
                        token_id,
                        tx.get("merchant_name", "Unknown"),
                        tx.get("merchant_category", "5999"),
                        tx.get("amount_cents", 0),
                        tx.get("currency", "USD"),
                        tx.get("arqc", ""),
                        tx.get("atc", 0),
                        tx.get("timestamp_ms", now_ms),
                    ),
                )

            conn.commit()
            conn.close()

            data = Path(tmp_path).read_bytes()
            logger.info(
                "Built tapandpay.db (OBLIVION): network=%s last4=%s dpan=****%s "
                "txs=%d size=%d",
                network, last4, dpan_last4, len(transaction_entries), len(data),
            )
            return data

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── library.db ────────────────────────────────────────────────────

    def build_library(
        self,
        email: str,
        purchases: Optional[List[Dict[str, Any]]] = None,
        num_auto_purchases: int = 12,
        age_days: int = 90,
    ) -> bytes:
        """Build the Google Play Store purchase history database (library.db).

        Each entry in *purchases* may contain:
            * ``app_id`` — package name (e.g. ``com.spotify.music``)
            * ``doc_type`` — 1=app, 2=book, 3=movie, 4=music (default 1)
            * ``purchase_time_ms`` — Unix ms timestamp (auto-distributed if 0)
            * ``price_micros`` — price in micro-units (0 = free/pre-installed)
            * ``currency`` — ISO currency code (default ``USD``)
            * ``order_id`` — GPA.XXXX-... order ID (auto-generated if empty)

        If *purchases* is empty or None, ``num_auto_purchases`` plausible
        free-tier app purchases are generated automatically.

        Returns:
            Raw bytes of a valid SQLite3 database.
        """
        purchases = purchases or []
        if not purchases and num_auto_purchases > 0:
            purchases = self._generate_default_purchases(
                email, num_auto_purchases, age_days
            )

        now_ms = int(time.time() * 1000)
        birth_ms = now_ms - age_days * 86400 * 1000

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Android Play Store library.db schema (AIDL 3.x)
            c.executescript("""
                CREATE TABLE IF NOT EXISTS ownership (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    doc_type INTEGER DEFAULT 1,
                    purchase_time INTEGER,
                    purchase_state INTEGER DEFAULT 0,
                    order_id TEXT,
                    price_micros INTEGER DEFAULT 0,
                    currency_code TEXT DEFAULT 'USD',
                    UNIQUE(account, doc_id, doc_type)
                );
                CREATE TABLE IF NOT EXISTS apps (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_name TEXT UNIQUE,
                    version_code INTEGER DEFAULT 0,
                    install_time INTEGER,
                    last_update_time INTEGER
                );
                PRAGMA user_version = 2;
            """)

            for p in purchases:
                app_id = p.get("app_id", "")
                if not app_id:
                    continue
                doc_type = p.get("doc_type", 1)
                # Distribute purchases across account lifetime if not specified
                pt_ms = p.get("purchase_time_ms") or (
                    birth_ms + random.randint(0, now_ms - birth_ms)
                )
                order_id = p.get("order_id") or _generate_order_id()
                price = p.get("price_micros", 0)
                currency = p.get("currency", "USD")

                c.execute(
                    "INSERT OR IGNORE INTO ownership "
                    "(account, doc_id, doc_type, purchase_time, purchase_state, "
                    " order_id, price_micros, currency_code) "
                    "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                    (email, app_id, doc_type, pt_ms, order_id, price, currency),
                )

                if doc_type == 1:  # app
                    c.execute(
                        "INSERT OR IGNORE INTO apps (package_name, version_code, install_time, last_update_time) "
                        "VALUES (?, ?, ?, ?)",
                        (app_id, random.randint(100, 50000),
                         pt_ms, pt_ms + random.randint(0, 7 * 86400 * 1000)),
                    )

            conn.commit()
            conn.close()

            data = Path(tmp_path).read_bytes()
            logger.info("Built library.db: email=%s entries=%d size=%d",
                        email, len(purchases), len(data))
            return data

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_issuer(card_number: str) -> str:
        """Quick BIN-based issuer detection."""
        num = card_number.replace(" ", "").replace("-", "")
        _ISSUERS = {
            "4532": "Chase", "4916": "US Bank", "4111": "Test Bank",
            "5100": "Citi", "5425": "Mastercard Inc.", "5200": "Bank of America",
            "3782": "American Express", "6011": "Discover",
        }
        return _ISSUERS.get(num[:4], "Bank")

    @staticmethod
    def _generate_default_purchases(
        email: str, count: int, age_days: int
    ) -> List[Dict[str, Any]]:
        """Generate plausible free-tier app purchase records."""
        _FREE_APPS = [
            "com.google.android.apps.maps",
            "com.google.android.youtube",
            "com.google.android.gm",
            "com.instagram.android",
            "com.facebook.katana",
            "com.twitter.android",
            "com.spotify.music",
            "com.netflix.mediaclient",
            "com.amazon.mShop.android.shopping",
            "com.whatsapp",
            "com.snapchat.android",
            "com.ubercab",
            "com.grubhub.android",
            "com.doordash.driverapp",
            "com.starbucks.mobilecard",
            "com.target.ui",
            "com.walmart.android",
            "com.paypal.android.p2pmobile",
            "com.venmo",
            "com.cashapp",
        ]
        now_ms = int(time.time() * 1000)
        birth_ms = now_ms - age_days * 86400 * 1000

        apps = random.sample(_FREE_APPS, min(count, len(_FREE_APPS)))
        purchases = []
        for app_id in apps:
            pt_ms = birth_ms + random.randint(0, now_ms - birth_ms)
            purchases.append({
                "app_id": app_id,
                "doc_type": 1,
                "purchase_time_ms": pt_ms,
                "price_micros": 0,
                "currency": "USD",
                "order_id": _generate_order_id(),
            })
        return purchases

    # ── Transaction history generator ─────────────────────────────────

    @staticmethod
    def _generate_tx_history(
        dpan: str,
        luk: bytes,
        atc_start: int,
        age_days: int,
        country: str,
        num_entries: int,
    ) -> List[Dict[str, Any]]:
        """Generate backdated transaction history with real ARQC cryptograms.

        Transactions are distributed with circadian bias (more purchases during
        daytime hours) and weighted toward high-frequency merchants (coffee,
        grocery, gas).
        """
        merchants = _MERCHANTS.get(country.upper(), _MERCHANTS["US"])
        now_s = time.time()
        birth_s = now_s - age_days * 86400

        currency_map = {
            "US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR",
            "CA": "CAD", "AU": "AUD", "JP": "JPY", "IN": "INR",
        }
        currency = currency_map.get(country.upper(), "USD")

        entries: List[Dict[str, Any]] = []
        for i in range(num_entries):
            # Circadian distribution: bias toward daytime hours
            day_offset = random.uniform(0, age_days)
            hour = random.choices(range(24), weights=_CIRCADIAN_WEIGHTS)[0]
            ts_s = birth_s + day_offset * 86400
            ts_s = (ts_s // 86400) * 86400 + hour * 3600 + random.randint(0, 3599)
            ts_ms = int(ts_s * 1000)

            merchant_name, mcc, min_c, max_c = random.choice(merchants)
            amount_cents = random.randint(min_c, max_c)
            atc = atc_start + i

            arqc = _generate_arqc(luk, amount_cents, atc)

            entries.append({
                "merchant_name": merchant_name,
                "merchant_category": mcc,
                "amount_cents": amount_cents,
                "currency": currency,
                "arqc": arqc,
                "atc": atc,
                "timestamp_ms": ts_ms,
            })

        entries.sort(key=lambda x: x["timestamp_ms"])
        return entries

    # ── Coherence Bridge data generator ───────────────────────────────

    def build_coherence_data(
        self,
        email: str,
        order_ids: Optional[List[str]] = None,
        num_orders: int = 8,
        age_days: int = 90,
        country: str = "US",
    ) -> Dict[str, Any]:
        """Generate correlated data for the V3 Nexus Coherence Bridge.

        Anti-fraud engines (Sift, Sardine) flag accounts where data stores do
        not align.  This method produces a **single consistent dataset** of
        Order IDs and merchant interactions that can be embedded across:

        * ``tapandpay.db`` ``transaction_history`` (payment events)
        * Chrome ``History`` and ``Cookies`` (browsing footprint at merchant domains)
        * ``library.db`` ``ownership`` (Play Store purchase records)
        * ``Gmail.xml`` receipt metadata (email references to same Order IDs)

        Returns:
            Dict with keys:
              * ``order_ids``        — List of GPA.XXXX-... strings
              * ``tx_entries``       — tapandpay.db-ready transaction list
              * ``browser_urls``     — Chrome History URL rows
              * ``cookie_rows``      — Chrome Cookies rows
              * ``receipt_subjects`` — Gmail.xml receipt subject lines
        """
        if order_ids is None:
            order_ids = [_generate_order_id() for _ in range(num_orders)]

        merchants = _MERCHANTS.get(country.upper(), _MERCHANTS["US"])
        currency_map = {
            "US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR",
            "CA": "CAD", "AU": "AUD", "JP": "JPY",
        }
        currency = currency_map.get(country.upper(), "USD")
        currency_sym = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$",
                        "AUD": "A$", "JPY": "¥"}.get(currency, "$")

        now_s = time.time()
        birth_s = now_s - age_days * 86400

        _DOMAIN_MAP = {
            "Amazon.com": "www.amazon.com",
            "Amazon.co.uk": "www.amazon.co.uk",
            "Amazon.de": "www.amazon.de",
            "Netflix": "www.netflix.com",
            "Spotify": "open.spotify.com",
            "Starbucks": "www.starbucks.com",
            "Target": "www.target.com",
            "Uber": "www.uber.com",
            "Lyft": "www.lyft.com",
            "Tesco": "www.tesco.com",
        }

        tx_entries: List[Dict[str, Any]] = []
        browser_urls: List[Dict[str, Any]] = []
        cookie_rows: List[Dict[str, Any]] = []
        receipt_subjects: List[str] = []

        for order_id in order_ids:
            merchant_name, mcc, min_c, max_c = random.choice(merchants)
            amount_cents = random.randint(min_c, max_c)
            amount_str = f"{currency_sym}{amount_cents / 100:.2f}"

            day_offset = random.uniform(0, age_days)
            ts_s = birth_s + day_offset * 86400
            ts_ms = int(ts_s * 1000)

            domain = _DOMAIN_MAP.get(
                merchant_name,
                f"www.{merchant_name.lower().replace(' ', '').replace('.', '')}.com",
            )
            receipt_url = f"https://{domain}/orders/{order_id}"
            chrome_ts = int(ts_s * 1_000_000 + 11_644_473_600_000_000)
            cookie_exp_us = int(
                (ts_s + random.randint(86400 * 7, 86400 * 90)) * 1_000_000
                + 11_644_473_600_000_000
            )

            tx_entries.append({
                "merchant_name": merchant_name,
                "merchant_category": mcc,
                "amount_cents": amount_cents,
                "currency": currency,
                "order_id": order_id,
                "timestamp_ms": ts_ms,
                "arqc": "",
                "atc": 0,
            })

            browser_urls.append({
                "url": receipt_url,
                "title": f"Order {order_id} — {merchant_name}",
                "visit_count": random.randint(1, 3),
                "last_visit_time": chrome_ts,
            })

            cookie_rows.append({
                "host_key": f".{domain}",
                "name": random.choice(["session_id", "auth_token", "user_id", "_ga"]),
                "value": secrets.token_urlsafe(24),
                "path": "/",
                "is_secure": 1,
                "is_httponly": 1,
                "creation_utc": chrome_ts,
                "expires_utc": cookie_exp_us,
            })

            receipt_subjects.append(
                f"Your order {order_id} from {merchant_name} — {amount_str}"
            )

        logger.info(
            "Coherence data: %d order_ids, %d tx, %d urls, %d cookies",
            len(order_ids), len(tx_entries), len(browser_urls), len(cookie_rows),
        )
        return {
            "order_ids": order_ids,
            "tx_entries": tx_entries,
            "browser_urls": browser_urls,
            "cookie_rows": cookie_rows,
            "receipt_subjects": receipt_subjects,
        }

