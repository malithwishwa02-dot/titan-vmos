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

import logging
import random
import secrets
import sqlite3
import string
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.vmos-db-builder")

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

    # ── tapandpay.db ──────────────────────────────────────────────────

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
    ) -> bytes:
        """Build the Google Pay token database (tapandpay.db).

        Constructs the full schema including ``token_metadata``,
        ``payment_instrument``, ``token_state``, and ``emv_key`` tables with
        a realistic card entry and DPAN.

        Args:
            card_number: Full card PAN (spaces/dashes stripped).
            exp_month: Expiry month (1-12).
            exp_year: Expiry year (2- or 4-digit).
            cardholder: Name on card.
            issuer: Issuing bank name.  Auto-detected from BIN if empty.
            persona_email: Google account email for wallet binding.
            zero_auth: If True, sets ``zero_auth_enabled`` preference to bypass
                OTP requirement for purchases.
            age_days: Used for ``added_timestamp`` backdating.

        Returns:
            Raw bytes of a valid SQLite3 database.
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

        network_id = {"visa": 1, "mastercard": 2, "amex": 3, "discover": 4}.get(network, 1)
        network_name = network.capitalize()
        display_name = f"{network_name} ****{last4}"
        card_color = {"visa": -16776961, "mastercard": -65536,
                      "amex": -16711936, "discover": -19712}.get(network, -12285185)

        if not issuer:
            issuer = self._detect_issuer(cc)

        added_ts_ms = int((time.time() - age_days * 86400) * 1000)
        atc = random.randint(5, 30)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Full tapandpay.db schema (GMS 24.09 compatible)
            c.executescript("""
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
                    account_name TEXT
                );
                CREATE TABLE IF NOT EXISTS payment_instrument (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    instrument_id TEXT,
                    network_id INTEGER,
                    last_four TEXT,
                    exp_month INTEGER,
                    exp_year INTEGER,
                    display_name TEXT,
                    card_color INTEGER,
                    is_default INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS token_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    state INTEGER DEFAULT 3,
                    error_code TEXT,
                    last_update INTEGER
                );
                CREATE TABLE IF NOT EXISTS emv_key (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT UNIQUE,
                    luk_hex TEXT,
                    atc INTEGER DEFAULT 0,
                    expiry_ms INTEGER,
                    max_transactions INTEGER DEFAULT 10
                );
                PRAGMA user_version = 5;
            """)

            # EMV session (simplified — see wallet_provisioner for full derivation)
            import hashlib, hmac as _hmac, struct
            mdk_seed = hashlib.sha256(f"TITAN-MDK-{dpan}".encode()).digest()[:16]
            pan_block = dpan[-13:-1].encode()
            udk = _hmac.new(mdk_seed, pan_block, hashlib.sha256).digest()[:16]
            atc_block = struct.pack(">I", atc)
            luk = _hmac.new(udk, atc_block, hashlib.sha256).digest()[:16]
            luk_hex = luk.hex().upper()

            # token_metadata row
            c.execute(
                "INSERT OR REPLACE INTO token_metadata "
                "(token_id, dpan, last_four, network, token_ref, display_name, "
                " is_default, card_color, token_state, added_timestamp, "
                " exp_month, exp_year, cardholder, issuer_name, account_name) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, 3, ?, ?, ?, ?, ?, ?)",
                (token_id, dpan, last4, network_id, token_ref, display_name,
                 card_color, added_ts_ms, exp_month, exp_year,
                 cardholder, issuer, persona_email),
            )

            # payment_instrument row
            c.execute(
                "INSERT OR REPLACE INTO payment_instrument "
                "(token_id, instrument_id, network_id, last_four, exp_month, exp_year, "
                " display_name, card_color, is_default) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (token_id, f"instrument_{token_id[:8]}", network_id, last4,
                 exp_month, exp_year, display_name, card_color),
            )

            # token_state row
            c.execute(
                "INSERT OR REPLACE INTO token_state (token_id, state, last_update) VALUES (?, 3, ?)",
                (token_id, int(time.time() * 1000)),
            )

            # emv_key row
            c.execute(
                "INSERT OR REPLACE INTO emv_key (token_id, luk_hex, atc, expiry_ms, max_transactions) "
                "VALUES (?, ?, ?, ?, ?)",
                (token_id, luk_hex, atc,
                 int(time.time() * 1000) + 86400000,   # 24h
                 random.randint(5, 10)),
            )

            conn.commit()
            conn.close()

            data = Path(tmp_path).read_bytes()
            logger.info(
                "Built tapandpay.db: network=%s last4=%s dpan=****%s size=%d zero_auth=%s",
                network, last4, dpan_last4, len(data), zero_auth,
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
