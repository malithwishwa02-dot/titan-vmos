"""
Titan V12 — Keybox Lifecycle Manager
=====================================
Centralized keybox management for TrickyStore/PlayIntegrityFork attestation.
Handles validation, installation, revocation checking, rotation, and health
monitoring. All keybox operations across the codebase should delegate here.

Keybox Health States:
  MISSING     — No keybox file found
  PLACEHOLDER — Auto-generated test keybox (random bytes, won't pass real PI)
  VALID       — Structurally valid keybox with parseable key material
  REVOKED     — Keybox serial found on Google's attestation CRL
  UNKNOWN     — Could not determine status (CRL fetch failed, etc.)

Usage:
    mgr = KeyboxManager()
    health = mgr.validate_keybox("/opt/titan/data/keybox.xml")
    mgr.install_keybox("/opt/titan/data/keybox.xml", "127.0.0.1:6520")
    status = mgr.get_keybox_status("127.0.0.1:6520")
"""

import enum
import hashlib
import logging
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Optional

from adb_utils import adb_shell, adb_push, ensure_adb_root
from exceptions import TitanError

logger = logging.getLogger("titan.keybox-manager")

# Google's attestation status endpoint
_ATTESTATION_STATUS_URL = "https://android.googleapis.com/attestation/status"

# Default host-side keybox paths (checked in order)
DEFAULT_KEYBOX_PATHS = [
    "/opt/titan/data/keybox.xml",
    "/opt/titan/data/keybox/keybox.xml",
]

# Device-side paths where TrickyStore/PIF expect keybox
DEVICE_KEYBOX_PATHS = [
    "/data/adb/tricky_store/keybox.xml",
    "/data/adb/modules/playintegrityfix/keybox.xml",
    "/data/adb/modules/tricky_store/keybox.xml",
]

# Markers that identify placeholder/test keyboxes
_PLACEHOLDER_DEVICE_IDS = {"titan-test-device", "titan", "test", "placeholder"}


class KeyboxHealth(enum.Enum):
    """Health status of a keybox."""
    MISSING = "missing"
    PLACEHOLDER = "placeholder"
    VALID = "valid"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class KeyboxError(TitanError):
    """Keybox-specific error."""
    def __init__(self, message: str = "") -> None:
        super().__init__(message, code="KEYBOX_ERROR")


@dataclass
class KeyboxInfo:
    """Structured keybox metadata."""
    health: KeyboxHealth
    path: str = ""
    sha256: str = ""
    algorithm: str = ""
    device_id: str = ""
    num_certificates: int = 0
    has_private_key: bool = False
    serial: str = ""
    detail: str = ""


class KeyboxManager:
    """Centralized keybox lifecycle management."""

    def __init__(self):
        self._crl_cache: Optional[set] = None
        self._crl_cache_time: float = 0.0
        self._crl_cache_ttl: float = 3600.0  # 1 hour

    # ─── VALIDATION ───────────────────────────────────────────────

    def validate_keybox(self, path: str) -> KeyboxInfo:
        """Parse and validate a keybox.xml file.

        Returns KeyboxInfo with health status:
          MISSING     — file does not exist
          PLACEHOLDER — auto-generated test keybox (random bytes)
          VALID       — structurally valid with parseable key material
        """
        if not os.path.isfile(path):
            return KeyboxInfo(health=KeyboxHealth.MISSING, path=path,
                              detail="File not found")

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            return KeyboxInfo(health=KeyboxHealth.MISSING, path=path,
                              detail=f"Read error: {e}")

        sha = hashlib.sha256(raw).hexdigest()

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            return KeyboxInfo(health=KeyboxHealth.UNKNOWN, path=path,
                              sha256=sha, detail=f"XML parse error: {e}")

        # Check root element
        if root.tag != "AndroidAttestation":
            return KeyboxInfo(health=KeyboxHealth.UNKNOWN, path=path,
                              sha256=sha,
                              detail=f"Unexpected root element: {root.tag}")

        # Find keybox
        keybox_el = root.find("Keybox")
        if keybox_el is None:
            return KeyboxInfo(health=KeyboxHealth.UNKNOWN, path=path,
                              sha256=sha, detail="No <Keybox> element found")

        device_id = keybox_el.get("DeviceID", "")
        key_el = keybox_el.find("Key")
        algorithm = key_el.get("algorithm", "") if key_el is not None else ""

        # Check for private key
        private_key_el = key_el.find("PrivateKey") if key_el is not None else None
        has_private_key = (private_key_el is not None
                          and private_key_el.text is not None
                          and len(private_key_el.text.strip()) > 32)

        # Count certificates
        chain_el = key_el.find("CertificateChain") if key_el is not None else None
        num_certs = 0
        serial = ""
        if chain_el is not None:
            certs = chain_el.findall("Certificate")
            num_certs = len(certs)
            # Try to extract serial from first cert text (heuristic)
            if certs and certs[0].text:
                cert_text = certs[0].text.strip()
                # Look for serial in PEM-decoded cert (basic heuristic)
                serial_match = re.search(r"serial[:\s]*([0-9a-fA-F:]+)", cert_text)
                if serial_match:
                    serial = serial_match.group(1).replace(":", "")

        # Determine if placeholder
        is_placeholder = (
            device_id.lower() in _PLACEHOLDER_DEVICE_IDS
            or not has_private_key
            or num_certs < 2  # Real keyboxes have multi-cert chains
            or (key_el is not None and key_el.find("Format") is not None
                and not has_private_key)
        )

        if is_placeholder:
            return KeyboxInfo(
                health=KeyboxHealth.PLACEHOLDER,
                path=path, sha256=sha, algorithm=algorithm,
                device_id=device_id, num_certificates=num_certs,
                has_private_key=has_private_key, serial=serial,
                detail="Placeholder/test keybox — won't pass real Play Integrity",
            )

        return KeyboxInfo(
            health=KeyboxHealth.VALID,
            path=path, sha256=sha, algorithm=algorithm,
            device_id=device_id, num_certificates=num_certs,
            has_private_key=has_private_key, serial=serial,
            detail=f"Valid keybox ({algorithm}, {num_certs} cert(s))",
        )

    # ─── REVOCATION CHECK ─────────────────────────────────────────

    def check_revocation(self, path: str) -> KeyboxInfo:
        """Validate keybox and check serial against Google's attestation status.

        Google publishes revoked key status at:
          https://android.googleapis.com/attestation/status

        This is a JSON endpoint listing serial numbers with
        status entries (REVOKED, SUSPENDED, etc).
        """
        info = self.validate_keybox(path)
        if info.health in (KeyboxHealth.MISSING, KeyboxHealth.PLACEHOLDER):
            return info

        # Fetch revocation list
        revoked_serials = self._fetch_attestation_status()
        if revoked_serials is None:
            info.detail += " | CRL check failed (network error)"
            return info

        if info.serial and info.serial.lower() in revoked_serials:
            info.health = KeyboxHealth.REVOKED
            info.detail = f"REVOKED — serial {info.serial[:16]}... found on Google CRL"
            logger.warning(f"Keybox {path} is REVOKED (serial={info.serial[:16]})")
            return info

        info.detail += " | Not on Google CRL"
        return info

    def _fetch_attestation_status(self) -> Optional[set]:
        """Fetch Google's attestation status JSON and extract revoked serials.

        Caches results for 1 hour to avoid excessive requests.
        Returns set of lowercase hex serial strings, or None on failure.
        """
        now = time.time()
        if self._crl_cache is not None and (now - self._crl_cache_time) < self._crl_cache_ttl:
            return self._crl_cache

        try:
            import urllib.request
            import json

            req = urllib.request.Request(
                _ATTESTATION_STATUS_URL,
                headers={"User-Agent": "Titan/12.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            # The status JSON has structure: {"entries": {"<serial_hex>": {"status": "REVOKED", ...}}}
            revoked = set()
            entries = data.get("entries", {})
            for serial_hex, entry in entries.items():
                status = entry.get("status", "").upper()
                if status in ("REVOKED", "SUSPENDED"):
                    revoked.add(serial_hex.lower().replace(":", ""))

            self._crl_cache = revoked
            self._crl_cache_time = now
            logger.info(f"Attestation status fetched: {len(revoked)} revoked entries")
            return revoked

        except Exception as e:
            logger.warning(f"Failed to fetch attestation status: {e}")
            return None

    # ─── INSTALLATION ─────────────────────────────────────────────

    def install_keybox(self, keybox_path: str, adb_target: str,
                       skip_validation: bool = False) -> Dict[str, Any]:
        """Validate and install keybox to device at all required paths.

        Returns dict with: ok, health, paths_pushed, hash, device_id, detail
        """
        ensure_adb_root(adb_target)

        # Validate
        if not skip_validation:
            info = self.validate_keybox(keybox_path)
        else:
            info = KeyboxInfo(health=KeyboxHealth.VALID, path=keybox_path)
            if os.path.isfile(keybox_path):
                with open(keybox_path, "rb") as f:
                    info.sha256 = hashlib.sha256(f.read()).hexdigest()

        is_real = info.health == KeyboxHealth.VALID
        is_placeholder = info.health == KeyboxHealth.PLACEHOLDER
        kb_type = "real" if is_real else ("placeholder" if is_placeholder else "none")

        if info.health == KeyboxHealth.MISSING:
            logger.error(f"Keybox not found: {keybox_path}")
            return {"ok": False, "health": info.health.value,
                    "detail": info.detail, "paths_pushed": 0}

        if info.health == KeyboxHealth.REVOKED:
            logger.error(f"Keybox is REVOKED: {keybox_path}")
            return {"ok": False, "health": info.health.value,
                    "detail": info.detail, "paths_pushed": 0}

        # Push to device
        pushed = 0
        for device_path in DEVICE_KEYBOX_PATHS:
            parent = device_path.rsplit("/", 1)[0]
            adb_shell(adb_target, f"mkdir -p {parent}", timeout=5)
            ok = adb_push(adb_target, keybox_path, device_path, timeout=15)
            if ok:
                pushed += 1
                adb_shell(adb_target, f"chmod 600 {device_path}", timeout=3)
            else:
                logger.debug(f"Keybox push to {device_path} failed")

        # Set properties — differentiate real vs placeholder
        props = {
            "persist.titan.keybox.loaded": "1" if pushed > 0 else "0",
            "persist.titan.keybox.type": kb_type,
            "persist.titan.keybox.hash": info.sha256[:16],
            "persist.titan.keybox.paths": str(pushed),
        }
        prop_cmds = " && ".join(f"setprop {k} '{v}'" for k, v in props.items())
        adb_shell(adb_target, prop_cmds, timeout=10)

        result = {
            "ok": pushed > 0,
            "health": info.health.value,
            "kb_type": kb_type,
            "paths_pushed": pushed,
            "total_paths": len(DEVICE_KEYBOX_PATHS),
            "hash": info.sha256[:16],
            "device_id": info.device_id,
            "algorithm": info.algorithm,
            "detail": info.detail,
        }

        if pushed > 0 and is_placeholder:
            logger.warning(f"Placeholder keybox installed ({pushed} paths) — "
                           "won't pass real Play Integrity. Place real keybox at "
                           "/opt/titan/data/keybox.xml for STRONG attestation.")
        elif pushed > 0:
            logger.info(f"Keybox installed: hash={info.sha256[:16]}, "
                        f"{pushed}/{len(DEVICE_KEYBOX_PATHS)} paths")
        else:
            logger.error("Keybox push failed to all device paths")

        return result

    # ─── ROTATION ─────────────────────────────────────────────────

    def rotate_keybox(self, new_keybox_path: str, adb_target: str) -> Dict[str, Any]:
        """Hot-swap keybox: validate new → install → clear GMS cache → verify.

        Returns dict with installation result plus rotation-specific fields.
        """
        # Validate new keybox first
        info = self.check_revocation(new_keybox_path)
        if info.health in (KeyboxHealth.MISSING, KeyboxHealth.REVOKED):
            return {
                "ok": False,
                "health": info.health.value,
                "detail": info.detail,
                "step": "pre_validation",
            }

        if info.health == KeyboxHealth.PLACEHOLDER:
            logger.warning("Rotating to placeholder keybox — attestation will degrade")

        # Install new keybox
        result = self.install_keybox(new_keybox_path, adb_target, skip_validation=True)
        if not result["ok"]:
            result["step"] = "installation"
            return result

        # Clear GMS attestation cache to force fresh check
        cache_cmds = [
            "am force-stop com.google.android.gms",
            "rm -rf /data/data/com.google.android.gms/cache/safetynet* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/cache/play_integrity* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/databases/dg_* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/files/droidguard* 2>/dev/null",
        ]
        adb_shell(adb_target, " && ".join(cache_cmds), timeout=15)
        logger.info("GMS cache cleared after keybox rotation")

        result["rotated"] = True
        result["step"] = "completed"
        result["detail"] = f"Rotated to {info.sha256[:16]} — GMS cache cleared"
        return result

    # ─── STATUS ───────────────────────────────────────────────────

    def get_keybox_status(self, adb_target: str) -> Dict[str, Any]:
        """Get current keybox status from device properties and file checks."""
        ensure_adb_root(adb_target)

        loaded = adb_shell(adb_target,
                           "getprop persist.titan.keybox.loaded", timeout=3).strip()
        kb_type = adb_shell(adb_target,
                            "getprop persist.titan.keybox.type", timeout=3).strip()
        kb_hash = adb_shell(adb_target,
                            "getprop persist.titan.keybox.hash", timeout=3).strip()
        strategy = adb_shell(adb_target,
                             "getprop persist.titan.attestation.strategy",
                             timeout=3).strip()

        # Check which device paths actually have keybox files
        installed_paths = []
        for dp in DEVICE_KEYBOX_PATHS:
            check = adb_shell(adb_target,
                              f"test -f {dp} && echo exists",
                              timeout=3).strip()
            if check == "exists":
                installed_paths.append(dp)

        # Check Magisk/Zygisk status
        magisk_ver = adb_shell(adb_target,
                               "magisk -v 2>/dev/null || echo none",
                               timeout=3).strip()
        zygisk = adb_shell(adb_target,
                           "magisk --zygisk-status 2>/dev/null || echo unknown",
                           timeout=3).strip()

        # Check TrickyStore module
        ts_module = adb_shell(adb_target,
                              "test -f /data/adb/modules/tricky_store/module.prop "
                              "&& echo installed || echo missing",
                              timeout=3).strip()

        # Check PIF module
        pif_module = adb_shell(adb_target,
                               "test -f /data/adb/modules/playintegrityfix/module.prop "
                               "&& echo installed || echo missing",
                               timeout=3).strip()

        # Determine effective health
        if loaded != "1":
            health = KeyboxHealth.MISSING
        elif kb_type == "placeholder":
            health = KeyboxHealth.PLACEHOLDER
        elif kb_type == "real":
            health = KeyboxHealth.VALID
        else:
            health = KeyboxHealth.UNKNOWN

        return {
            "health": health.value,
            "loaded": loaded == "1",
            "type": kb_type or "unknown",
            "hash": kb_hash,
            "strategy": strategy or "none",
            "installed_paths": installed_paths,
            "magisk_version": magisk_ver,
            "zygisk_status": zygisk,
            "trickystore_module": ts_module,
            "pif_module": pif_module,
            "attestation_ready": (
                health == KeyboxHealth.VALID
                and ts_module == "installed"
                and pif_module == "installed"
            ),
        }

    # ─── HOST-SIDE KEYBOX DISCOVERY ───────────────────────────────

    def find_keybox(self) -> Optional[str]:
        """Find keybox.xml on the host filesystem (checks default paths)."""
        custom = os.environ.get("TITAN_KEYBOX_PATH", "")
        if custom and os.path.isfile(custom):
            return custom
        for p in DEFAULT_KEYBOX_PATHS:
            if os.path.isfile(p):
                return p
        return None

    def generate_placeholder(self, output_path: str) -> KeyboxInfo:
        """Generate a marked placeholder keybox for structural compliance.

        The placeholder is clearly marked and will NOT pass real Play Integrity.
        Unlike the old _generate_test_keybox(), this sets kb_type=placeholder
        to prevent downstream deception.
        """
        import base64
        key_material = base64.b64encode(os.urandom(256)).decode()
        cert_material = base64.b64encode(os.urandom(512)).decode()
        keybox_xml = f'''<?xml version="1.0"?>
<AndroidAttestation>
  <NumberOfKeyboxes>1</NumberOfKeyboxes>
  <Keybox DeviceID="titan-placeholder">
    <Key algorithm="ecdsa">
      <PrivateKey format="pem">
{key_material}
      </PrivateKey>
      <CertificateChain>
        <NumberOfCertificates>1</NumberOfCertificates>
        <Certificate format="pem">
{cert_material}
        </Certificate>
      </CertificateChain>
    </Key>
  </Keybox>
</AndroidAttestation>'''
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(keybox_xml)
        logger.info(f"Placeholder keybox written to {output_path}")
        return self.validate_keybox(output_path)
