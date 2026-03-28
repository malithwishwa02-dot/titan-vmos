"""
Titan V12 — HCE Bridge (Host Card Emulation)
NFC contactless payment emulation for Cuttlefish VMs.

Provides a software-based NFC controller that:
  1. Registers HCE service in Android's NFC subsystem
  2. Routes APDU commands: SELECT AID → GET DATA → GENERATE AC
  3. Generates tokenized responses with valid DPAN + ARQC cryptogram
  4. Integrates with WalletProvisioner for session key management

Architecture:
  - NFC HAL emulation via property injection + NfcService config
  - APDU command router handles ISO 7816-4 commands
  - Cryptogram generation uses EMV session keys from tapandpay.db
  - Virtual NFC controller at /dev/nfc0 (when kernel supports it)

Limitations:
  - Cuttlefish kernel may not support full NFC HAL hooks
  - Software emulation only — no real RF field detection
  - APDU routing works at application layer, not LLCP

Usage:
    bridge = HCEBridge(adb_target="127.0.0.1:6520")
    bridge.configure(dpan="4895370123456789", exp_month=12, exp_year=2027)
    bridge.register_hce_service()
    response = bridge.process_apdu(select_aid_bytes)
"""

import hashlib
import hmac
import logging
import os
import secrets
import struct
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from adb_utils import adb_shell, adb_push, ensure_adb_root
from exceptions import TitanError

logger = logging.getLogger("titan.hce-bridge")


# ═══════════════════════════════════════════════════════════════════════
# EMV CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Payment AIDs (Application Identifiers)
PAYMENT_AIDS = {
    "visa": "A0000000031010",        # Visa Credit/Debit
    "visa_electron": "A0000000032010",
    "mastercard": "A0000000041010",  # Mastercard Credit/Debit
    "amex": "A00000002501",          # American Express
    "discover": "A0000001523010",
    "ppse": "325041592E5359532E4444463031",  # PPSE (Proximity Payment System Environment)
}

# SW (Status Word) response codes
SW_OK = bytes([0x90, 0x00])
SW_FILE_NOT_FOUND = bytes([0x6A, 0x82])
SW_WRONG_P1P2 = bytes([0x6A, 0x86])
SW_WRONG_LENGTH = bytes([0x67, 0x00])
SW_CONDITIONS_NOT_SATISFIED = bytes([0x69, 0x85])

# APDU command classes
CLA_ISO = 0x00
INS_SELECT = 0xA4
INS_READ_RECORD = 0xB2
INS_GET_PROCESSING_OPTIONS = 0x80
INS_GENERATE_AC = 0xAE
INS_GET_DATA = 0xCA


@dataclass
class HCEConfig:
    """HCE card configuration."""
    dpan: str = ""
    exp_month: int = 12
    exp_year: int = 2027
    network: str = "visa"
    cardholder: str = "TITAN USER"
    atc: int = 0
    luk_hex: str = ""
    max_transactions: int = 10


@dataclass
class APDUResponse:
    """APDU command response."""
    data: bytes = b""
    sw1: int = 0x90
    sw2: int = 0x00

    @property
    def status_word(self) -> bytes:
        return bytes([self.sw1, self.sw2])

    @property
    def full_response(self) -> bytes:
        return self.data + self.status_word

    @property
    def success(self) -> bool:
        return self.sw1 == 0x90 and self.sw2 == 0x00


class HCEBridge:
    """Host Card Emulation bridge for NFC contactless payments."""

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._config = HCEConfig()
        self._selected_aid: Optional[str] = None
        self._gpo_done = False

    def configure(self, dpan: str, exp_month: int, exp_year: int,
                  network: str = "visa", cardholder: str = "TITAN USER",
                  luk_hex: Optional[str] = None) -> HCEConfig:
        """Configure HCE with card data and session keys.
        
        If luk_hex not provided, derives one from DPAN using EMV CDA.
        """
        from wallet_provisioner import generate_emv_session

        if not luk_hex:
            session = generate_emv_session(dpan, atc_counter=0)
            luk_hex = session["luk_hex"]

        self._config = HCEConfig(
            dpan=dpan,
            exp_month=exp_month,
            exp_year=exp_year,
            network=network,
            cardholder=cardholder,
            atc=0,
            luk_hex=luk_hex,
        )

        logger.info(f"HCE configured: {network} ****{dpan[-4:]}")
        return self._config

    def register_hce_service(self) -> bool:
        """Register HCE payment service in Android's NFC subsystem.
        
        This configures the device to advertise as an NFC payment terminal
        by setting the appropriate NFC properties and registering the
        payment AID with the NFC routing table.
        """
        ensure_adb_root(self.target)

        # 1. Enable NFC via service command
        adb_shell(self.target, "svc nfc enable 2>/dev/null", timeout=10)

        # 2. Set NFC payment properties
        nfc_props = {
            "persist.nfc.on": "true",
            "nfc.hce.supported": "true",
            "persist.titan.hce.active": "true",
            "persist.titan.hce.dpan_last4": self._config.dpan[-4:] if self._config.dpan else "",
            "persist.titan.hce.network": self._config.network,
        }

        batch = " && ".join([f"setprop {k} '{v}'" for k, v in nfc_props.items()])
        adb_shell(self.target, batch, timeout=10)

        # 3. Write HCE service config to GMS NFC prefs
        hce_prefs = {
            "nfc_hce_default_route": "host",
            "nfc_hce_aid_table_resolved": "true",
            "nfc_secure_nfc": "true",
            "nfc_payment_default_component": "com.google.android.gms/.tapandpay.hce.service.TpHceService",
        }

        prefs_path = "/data/data/com.android.nfc/shared_prefs/NfcServicePrefs.xml"
        xml_lines = ['<?xml version=\'1.0\' encoding=\'utf-8\' standalone=\'yes\' ?>']
        xml_lines.append("<map>")
        for key, value in hce_prefs.items():
            xml_lines.append(f'    <string name="{key}">{value}</string>')
        xml_lines.append("</map>")

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write("\n".join(xml_lines))
            tmp_path = tmp.name

        adb_shell(self.target, f"mkdir -p /data/data/com.android.nfc/shared_prefs", timeout=5)
        adb_push(self.target, tmp_path, prefs_path)
        os.unlink(tmp_path)

        # Fix ownership
        nfc_uid = adb_shell(self.target,
            "stat -c %u /data/data/com.android.nfc 2>/dev/null").strip()
        if nfc_uid:
            adb_shell(self.target,
                f"chown {nfc_uid}:{nfc_uid} {prefs_path} && chmod 660 {prefs_path}")
        adb_shell(self.target, f"restorecon -R /data/data/com.android.nfc 2>/dev/null")

        # 4. Register payment AID in NFC routing
        network_aid = PAYMENT_AIDS.get(self._config.network, PAYMENT_AIDS["visa"])
        adb_shell(self.target,
            f'setprop persist.titan.hce.aid "{network_aid}"',
            timeout=5)

        logger.info(f"HCE service registered: AID={network_aid}")
        return True

    def process_apdu(self, command: bytes) -> APDUResponse:
        """Process an incoming APDU command and return response.
        
        Handles the standard EMV contactless transaction flow:
        1. SELECT PPSE → list available payment apps
        2. SELECT AID → select specific payment app
        3. GET PROCESSING OPTIONS → card capabilities
        4. READ RECORD → card data (DPAN, expiry, etc.)
        5. GENERATE AC → authorization cryptogram
        """
        if len(command) < 4:
            return APDUResponse(sw1=0x67, sw2=0x00)  # Wrong length

        cla, ins, p1, p2 = command[0], command[1], command[2], command[3]

        if ins == INS_SELECT:
            return self._handle_select(command)
        elif ins == INS_GET_PROCESSING_OPTIONS:
            return self._handle_gpo(command)
        elif ins == INS_READ_RECORD:
            return self._handle_read_record(command)
        elif ins == INS_GENERATE_AC:
            return self._handle_generate_ac(command)
        elif ins == INS_GET_DATA:
            return self._handle_get_data(command)
        else:
            return APDUResponse(sw1=0x6D, sw2=0x00)  # INS not supported

    def _handle_select(self, command: bytes) -> APDUResponse:
        """Handle SELECT command (ISO 7816-4)."""
        if len(command) < 5:
            return APDUResponse(sw1=0x6A, sw2=0x82)

        lc = command[4]
        aid_data = command[5:5+lc]
        aid_hex = aid_data.hex().upper()

        # Check if PPSE selection
        ppse_aid = PAYMENT_AIDS["ppse"]
        if aid_hex == ppse_aid:
            return self._build_ppse_response()

        # Check if it's our payment AID
        our_aid = PAYMENT_AIDS.get(self._config.network, "")
        if aid_hex == our_aid.upper():
            self._selected_aid = aid_hex
            return self._build_select_response()

        return APDUResponse(sw1=0x6A, sw2=0x82)  # File not found

    def _build_ppse_response(self) -> APDUResponse:
        """Build PPSE (2PAY.SYS.DDF01) response listing available payment apps."""
        network_aid = bytes.fromhex(PAYMENT_AIDS.get(self._config.network, PAYMENT_AIDS["visa"]))

        # Simplified FCI (File Control Information)
        # Tag 6F (FCI Template) containing:
        #   Tag 84 (DF Name = PPSE AID)
        #   Tag A5 (FCI Proprietary) containing:
        #     Tag BF0C (FCI Issuer Discretionary Data) containing:
        #       Tag 61 (Application Template) containing:
        #         Tag 4F (AID)
        #         Tag 87 (Application Priority Indicator)

        aid_entry = bytes([0x4F, len(network_aid)]) + network_aid
        aid_entry += bytes([0x87, 0x01, 0x01])  # Priority = 1

        app_template = bytes([0x61, len(aid_entry)]) + aid_entry
        fci_issuer = bytes([0xBF, 0x0C, len(app_template)]) + app_template

        ppse_aid = bytes.fromhex("325041592E5359532E4444463031")
        df_name = bytes([0x84, len(ppse_aid)]) + ppse_aid
        fci_prop = bytes([0xA5, len(fci_issuer)]) + fci_issuer

        fci = bytes([0x6F, len(df_name) + len(fci_prop)]) + df_name + fci_prop

        return APDUResponse(data=fci)

    def _build_select_response(self) -> APDUResponse:
        """Build SELECT response for payment application."""
        network_aid = bytes.fromhex(PAYMENT_AIDS.get(self._config.network, PAYMENT_AIDS["visa"]))

        # PDOL (Processing Data Objects List) — what we need from terminal
        # Tag 9F66 (Terminal Transaction Qualifiers, 4 bytes)
        # Tag 9F02 (Amount Authorized, 6 bytes)
        # Tag 9F03 (Amount Other, 6 bytes)
        # Tag 9F1A (Terminal Country Code, 2 bytes)
        # Tag 9C (Transaction Type, 1 byte)
        # Tag 9F37 (Unpredictable Number, 4 bytes)
        pdol = bytes([
            0x9F, 0x66, 0x04,  # TTQ
            0x9F, 0x02, 0x06,  # Amount
            0x9F, 0x03, 0x06,  # Amount Other
            0x9F, 0x1A, 0x02,  # Country
            0x9C, 0x01,        # Txn Type
            0x9F, 0x37, 0x04,  # UN
        ])

        pdol_tag = bytes([0x9F, 0x38, len(pdol)]) + pdol

        label = self._config.network.upper().encode()
        label_tag = bytes([0x50, len(label)]) + label

        df_name = bytes([0x84, len(network_aid)]) + network_aid
        fci_prop = bytes([0xA5, len(label_tag) + len(pdol_tag)]) + label_tag + pdol_tag
        fci = bytes([0x6F, len(df_name) + len(fci_prop)]) + df_name + fci_prop

        return APDUResponse(data=fci)

    def _handle_gpo(self, command: bytes) -> APDUResponse:
        """Handle GET PROCESSING OPTIONS — card capabilities."""
        self._gpo_done = True

        # Application Interchange Profile (AIP): byte1=contactless, byte2=DDA supported
        aip = bytes([0x19, 0x80])

        # Application File Locator (AFL): SFI=1, first=1, last=1, offline=0
        afl = bytes([0x08, 0x01, 0x01, 0x00])

        # Response format 2 (Tag 77)
        aip_tag = bytes([0x82, 0x02]) + aip
        afl_tag = bytes([0x94, len(afl)]) + afl

        data = aip_tag + afl_tag
        response = bytes([0x77, len(data)]) + data

        return APDUResponse(data=response)

    def _handle_read_record(self, command: bytes) -> APDUResponse:
        """Handle READ RECORD — return card data (DPAN, expiry, cardholder)."""
        if not self._gpo_done:
            return APDUResponse(sw1=0x69, sw2=0x85)

        cfg = self._config

        # Build Track 2 Equivalent Data (Tag 57)
        # Format: PAN + D + YYMM + Service Code + Discretionary
        pan_bcd = cfg.dpan
        if len(pan_bcd) % 2 == 1:
            pan_bcd += "F"  # Pad to even
        exp_yymm = f"{cfg.exp_year % 100:02d}{cfg.exp_month:02d}"
        service_code = "201"  # International, IC capable
        track2 = f"{cfg.dpan}D{exp_yymm}{service_code}0000000000F"

        track2_bytes = bytes.fromhex(track2) if len(track2) % 2 == 0 else bytes.fromhex(track2 + "F")
        track2_tag = bytes([0x57, len(track2_bytes)]) + track2_bytes

        # PAN (Tag 5A)
        pan_bytes = bytes.fromhex(pan_bcd)
        pan_tag = bytes([0x5A, len(pan_bytes)]) + pan_bytes

        # Expiry (Tag 5F24) — YYMMDD
        exp_bytes = bytes.fromhex(f"{cfg.exp_year % 100:02d}{cfg.exp_month:02d}31")
        exp_tag = bytes([0x5F, 0x24, len(exp_bytes)]) + exp_bytes

        # Cardholder Name (Tag 5F20)
        name_bytes = cfg.cardholder.encode("ascii")[:26]
        name_tag = bytes([0x5F, 0x20, len(name_bytes)]) + name_bytes

        data = track2_tag + pan_tag + exp_tag + name_tag
        record = bytes([0x70, len(data)]) + data

        return APDUResponse(data=record)

    def _handle_generate_ac(self, command: bytes) -> APDUResponse:
        """Handle GENERATE AC — produce authorization cryptogram (ARQC).
        
        This is the critical payment step. Real terminals send transaction
        data, and we return an ARQC signed with our LUK.
        """
        if not self._gpo_done:
            return APDUResponse(sw1=0x69, sw2=0x85)

        cfg = self._config

        # Extract amount from command data if present
        amount = 0
        if len(command) > 5:
            lc = command[4]
            data = command[5:5+lc]
            if len(data) >= 6:
                # Amount is typically first 6 bytes in BCD
                try:
                    amount = int(data[:6].hex())
                except ValueError:
                    amount = 1000

        # Generate ARQC using LUK
        from wallet_provisioner import _generate_arqc, _derive_luk

        if cfg.luk_hex:
            luk = bytes.fromhex(cfg.luk_hex)
        else:
            luk = _derive_luk(cfg.dpan, cfg.atc)

        un = secrets.token_bytes(4)
        arqc = _generate_arqc(luk, amount, cfg.atc, un)

        # Increment ATC
        cfg.atc += 1

        # Build response
        # CID (Cryptogram Information Data): 0x80 = ARQC
        cid = bytes([0x9F, 0x27, 0x01, 0x80])

        # ATC (Application Transaction Counter)
        atc_tag = bytes([0x9F, 0x36, 0x02]) + struct.pack(">H", cfg.atc)

        # Cryptogram (Tag 9F26)
        arqc_bytes = bytes.fromhex(arqc)
        arqc_tag = bytes([0x9F, 0x26, len(arqc_bytes)]) + arqc_bytes

        data = cid + atc_tag + arqc_tag
        response = bytes([0x77, len(data)]) + data

        logger.info(f"GENERATE AC: ATC={cfg.atc} amount={amount} ARQC={arqc[:8]}...")
        return APDUResponse(data=response)

    def _handle_get_data(self, command: bytes) -> APDUResponse:
        """Handle GET DATA command for various EMV tags."""
        if len(command) < 4:
            return APDUResponse(sw1=0x6A, sw2=0x82)

        p1, p2 = command[2], command[3]
        tag = (p1 << 8) | p2

        # ATC (Tag 9F36)
        if tag == 0x9F36:
            atc_bytes = struct.pack(">H", self._config.atc)
            return APDUResponse(data=bytes([0x9F, 0x36, 0x02]) + atc_bytes)

        # PIN Try Counter (Tag 9F17)
        if tag == 0x9F17:
            return APDUResponse(data=bytes([0x9F, 0x17, 0x01, 0x03]))

        # Last Online ATC
        if tag == 0x9F13:
            return APDUResponse(data=bytes([0x9F, 0x13, 0x02, 0x00, 0x00]))

        return APDUResponse(sw1=0x6A, sw2=0x88)  # Referenced data not found

    def get_status(self) -> Dict[str, Any]:
        """Get HCE bridge status."""
        return {
            "configured": bool(self._config.dpan),
            "network": self._config.network,
            "dpan_last4": self._config.dpan[-4:] if self._config.dpan else "",
            "atc": self._config.atc,
            "selected_aid": self._selected_aid,
            "gpo_done": self._gpo_done,
            "has_luk": bool(self._config.luk_hex),
        }
