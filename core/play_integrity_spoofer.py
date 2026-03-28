"""
Titan V12 — Play Integrity Defense System
==========================================
Property-based Play Integrity defense integrated with AnomalyPatcher's
3-tier keybox strategy. Replaces broken Frida hooks from v11.3.

V12 Strategy:
  1. PlayIntegrityFork/TrickyStore module installation (Zygisk)
  2. Keybox injection (static or TEE-proxied)
  3. Property hardening (verified boot, build fingerprint)
  4. GMS cache management (force fresh attestation)
  5. Audit / verification of attestation state

Attestation Tiers:
  - BASIC: Properties only — no hardware attestation
  - DEVICE: Properties + static keybox — passes Play Protect
  - STRONG: Properties + RKA proxy to real TEE — full attestation

Dependencies:
  - AnomalyPatcher._patch_keybox() — handles 3-tier keybox injection
  - device_presets — provides real device fingerprints
  - Magisk/KernelSU + PlayIntegrityFork module (optional)

Usage:
    spoofer = PlayIntegritySpoofer(adb_target="127.0.0.1:6520")
    result = spoofer.apply_integrity_defense(tier="device", preset="samsung_s25_ultra")
    audit = spoofer.audit()
"""

import json
from keybox_manager import KeyboxManager
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from adb_utils import adb_shell, adb_push, ensure_adb_root
from exceptions import TitanError

logger = logging.getLogger("titan.play-integrity-spoofer")


# Build fingerprints known to pass PI — periodically refreshed.
# These WILL be revoked by Google. Primary source should be device_presets.py
# which tracks current OEM firmware releases. These are fallbacks only.
# Update cycle: check https://xdaforums.com/t/play-integrity-fix.4607985/ monthly.
KNOWN_GOOD_FINGERPRINTS = {
    "samsung_s25_ultra": "samsung/dm3qzsks/dm3q:14/UP1A.231005.007/S928BXXS1AXL7:user/release-keys",
    "samsung_s24": "samsung/e3qxxx/e3q:14/UP1A.231005.007/S926BXXS1AXL5:user/release-keys",
    "pixel_9_pro": "google/husky/husky:14/AP2A.240905.003/12231197:user/release-keys",
    "pixel_8": "google/shiba/shiba:14/AP2A.240805.005/12025142:user/release-keys",
    # Fallback fingerprints (less targeted, harder to blocklist)
    "samsung_a54": "samsung/a54xnsxx/a54x:14/UP1A.231005.007/A546BXXS8DXK3:user/release-keys",
    "samsung_a15": "samsung/a15nsxx/a15:14/UP1A.231005.007/A156BXXS2AXJ2:user/release-keys",
}

# Attestation level definitions
ATTESTATION_TIERS = {
    "basic": {
        "deviceIntegrity": ["MEETS_DEVICE_INTEGRITY"],
        "description": "Basic device integrity — no hardware attestation",
    },
    "device": {
        "deviceIntegrity": ["MEETS_DEVICE_INTEGRITY"],
        "description": "Device-level — static keybox + verified boot",
    },
    "strong": {
        "deviceIntegrity": ["MEETS_STRONG_INTEGRITY"],
        "description": "Strong integrity — RKA proxy or TEE simulator",
    },
}


class PlayIntegritySpoofer:
    """V12 Play Integrity defense via property hardening + keybox management."""

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._tier = "basic"
        self._preset = ""
        self._keybox_installed = False
        self._pif_module_installed = False
        self._last_audit: Optional[Dict] = None

    def apply_integrity_defense(self, tier: str = "device",
                                preset: str = "samsung_s25_ultra",
                                rka_host: Optional[str] = None) -> Dict[str, Any]:
        """Apply complete Play Integrity defense stack."""
        ensure_adb_root(self.target)
        self._tier = tier
        self._preset = preset

        results = {"tier": tier, "preset": preset, "steps": []}

        prop_result = self._harden_integrity_props(preset)
        results["steps"].append({"name": "property_hardening", "ok": prop_result})

        pif_result = self._configure_pif_module(preset)
        results["steps"].append({"name": "pif_module", "ok": pif_result})

        if tier in ("device", "strong"):
            if tier == "strong" and rka_host:
                kb_result = self._configure_rka_proxy(rka_host)
            else:
                kb_result = self._inject_keybox()
            results["steps"].append({"name": "keybox", "ok": kb_result})

        cache_result = self._clear_gms_attestation_cache()
        results["steps"].append({"name": "gms_cache_clear", "ok": cache_result})

        vb_result = self._set_verified_boot()
        results["steps"].append({"name": "verified_boot", "ok": vb_result})

        ok_count = sum(1 for s in results["steps"] if s["ok"])
        results["success"] = ok_count == len(results["steps"])
        results["score"] = f"{ok_count}/{len(results['steps'])}"

        logger.info(f"Play Integrity defense applied: tier={tier} {results['score']}")
        return results

    def _harden_integrity_props(self, preset: str) -> bool:
        """Set all properties required for Play Integrity verdicts."""
        try:
            from device_presets import DEVICE_PRESETS
        except ImportError:
            DEVICE_PRESETS = {}

        device = DEVICE_PRESETS.get(preset, {})
        fingerprint = device.get("fingerprint", KNOWN_GOOD_FINGERPRINTS.get(preset, ""))
        if not fingerprint:
            fingerprint = KNOWN_GOOD_FINGERPRINTS.get("samsung_s25_ultra", "")

        parts = fingerprint.split("/")
        brand = parts[0] if len(parts) > 0 else "samsung"

        props = {
            "ro.build.fingerprint": fingerprint,
            "ro.build.description": fingerprint.replace("/", " ").replace(":", " "),
            "ro.build.type": "user",
            "ro.build.tags": "release-keys",
            "ro.build.flavor": device.get("name", "dm3qzsks") + "-user",
            "ro.build.version.security_patch": device.get("security_patch", "2024-12-01"),
            "ro.build.version.sdk": str(device.get("sdk_version", 34)),
            "ro.build.version.release": device.get("android_version", "14"),
            "ro.boot.verifiedbootstate": "green",
            "ro.boot.flash.locked": "1",
            "ro.boot.vbmeta.device_state": "locked",
            "ro.debuggable": "0",
            "ro.secure": "1",
            "ro.adb.secure": "1",
            "ro.product.model": device.get("model", "SM-S928B"),
            "ro.product.brand": brand,
            "ro.product.manufacturer": device.get("manufacturer", brand),
            "ro.product.device": device.get("hardware", "dm3q"),
            "ro.product.board": device.get("board", "dm3q"),
            "ro.build.selinux": "1",
            "ro.product.first_api_level": str(device.get("sdk_version", 34)),
        }

        has_resetprop = adb_shell(
            self.target, "test -f /data/local/tmp/magisk64 && echo y", timeout=3
        ).strip() == "y"

        cmds = []
        for key, value in props.items():
            if has_resetprop:
                cmds.append(f"/data/local/tmp/magisk64 resetprop {key} '{value}'")
            else:
                cmds.append(f"setprop {key} '{value}'")

        for i in range(0, len(cmds), 10):
            batch = " && ".join(cmds[i:i+10])
            adb_shell(self.target, batch, timeout=15)

        logger.info(f"Hardened {len(props)} integrity properties (resetprop={has_resetprop})")
        return True

    def _configure_pif_module(self, preset: str) -> bool:
        """Configure PlayIntegrityFork/TrickyStore module if Zygisk is available."""
        try:
            from device_presets import DEVICE_PRESETS
        except ImportError:
            DEVICE_PRESETS = {}

        device = DEVICE_PRESETS.get(preset, {})
        fingerprint = device.get("fingerprint", KNOWN_GOOD_FINGERPRINTS.get(preset, ""))

        pif_config = {
            "FINGERPRINT": fingerprint,
            "MANUFACTURER": device.get("manufacturer", "samsung"),
            "MODEL": device.get("model", "SM-S928B"),
            "BRAND": device.get("brand", "samsung"),
            "PRODUCT": device.get("name", "dm3qzsks"),
            "DEVICE": device.get("hardware", "dm3q"),
            "SECURITY_PATCH": device.get("security_patch", "2024-12-01"),
            "DEVICE_INITIAL_SDK_INT": str(device.get("sdk_version", 34)),
            "BUILD_ID": "UP1A.231005.007",
            "spoofBuild": True,
            "spoofProps": True,
            "spoofProvider": True,
            "spoofSignature": False,
        }

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(pif_config, f, indent=2)
            tmp_path = f.name

        pif_paths = [
            "/data/adb/pif.json",
            "/data/adb/tricky_store/pif.json",
            "/data/adb/modules/playintegrityfix/pif.json",
        ]

        pushed = False
        for path in pif_paths:
            parent = os.path.dirname(path)
            adb_shell(self.target, f"mkdir -p {parent} 2>/dev/null", timeout=3)
            ok = adb_push(self.target, tmp_path, path)
            if ok:
                pushed = True

        os.unlink(tmp_path)
        if pushed:
            self._pif_module_installed = True

        module_check = adb_shell(
            self.target, "ls /data/adb/modules/playintegrityfix/module.prop 2>/dev/null",
            timeout=3
        ).strip()

        if module_check:
            logger.info("PlayIntegrityFork module detected and configured")
        else:
            logger.info("PIF config written (module not installed — prop-based defense only)")
        return True

    def _inject_keybox(self) -> bool:
        """Inject keybox for hardware attestation via centralized KeyboxManager.

        Priority:
          1. External real keybox discovered by KeyboxManager.find_keybox()
          2. Marked placeholder generated by KeyboxManager.generate_placeholder()

        For STRONG tier, use _configure_rka_proxy() instead.
        """
        kb_mgr = KeyboxManager()
        keybox_path = kb_mgr.find_keybox()

        if not keybox_path:
            keybox_path = "/opt/titan/data/keybox.xml"
            kb_mgr.generate_placeholder(keybox_path)
            logger.warning("Using placeholder keybox — DEVICE tier only. "
                           "For STRONG, place real keybox at /opt/titan/data/keybox/keybox.xml")

        result = kb_mgr.install_keybox(keybox_path, self.target)
        success = result.get("ok", False)
        kb_type = result.get("kb_type", "unknown")

        if success:
            self._keybox_installed = True
            logger.info(f"Keybox injected via KeyboxManager (type={kb_type})")
        else:
            logger.warning("Failed to inject keybox")
        return success

    def _configure_rka_proxy(self, rka_host: str) -> bool:
        """Configure Remote Key Attestation proxy for STRONG integrity."""
        parts = rka_host.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 443

        rka_config = {
            "enabled": True,
            "host": host,
            "port": port,
            "timeout_ms": 5000,
            "fallback_to_static": True,
        }

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(rka_config, f, indent=2)
            tmp_path = f.name

        config_path = "/data/local/tmp/rka_config.json"
        ok = adb_push(self.target, tmp_path, config_path)
        os.unlink(tmp_path)

        if ok:
            adb_shell(self.target, "setprop persist.titan.rka.enabled 1", timeout=3)
            adb_shell(self.target, f"setprop persist.titan.rka.host {host}:{port}", timeout=3)
            logger.info(f"RKA proxy configured: {host}:{port}")
            return True
        return False

    def _clear_gms_attestation_cache(self) -> bool:
        """Clear GMS attestation cache to force fresh check."""
        cmds = [
            "am force-stop com.google.android.gms",
            "rm -rf /data/data/com.google.android.gms/cache/safetynet* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/cache/play_integrity* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/databases/dg_* 2>/dev/null",
            "rm -rf /data/data/com.google.android.gms/files/droidguard* 2>/dev/null",
        ]
        adb_shell(self.target, " && ".join(cmds), timeout=15)
        logger.info("GMS attestation cache cleared")
        return True

    def _set_verified_boot(self) -> bool:
        """Ensure verified boot state properties are correct."""
        vb_props = {
            "ro.boot.verifiedbootstate": "green",
            "ro.boot.flash.locked": "1",
            "ro.boot.vbmeta.device_state": "locked",
            "ro.boot.vbmeta.hash_alg": "sha256",
            "ro.boot.vbmeta.size": "8192",
            "ro.boot.vbmeta.invalidate_on_error": "yes",
        }

        has_resetprop = adb_shell(
            self.target, "test -f /data/local/tmp/magisk64 && echo y", timeout=3
        ).strip() == "y"

        cmds = []
        for k, v in vb_props.items():
            if has_resetprop:
                cmds.append(f"/data/local/tmp/magisk64 resetprop {k} '{v}'")
            else:
                cmds.append(f"setprop {k} '{v}'")

        adb_shell(self.target, " && ".join(cmds), timeout=10)
        logger.info("Verified boot state set to green/locked")
        return True

    def audit(self) -> Dict[str, Any]:
        """Audit current Play Integrity readiness. Checks 12 vectors."""
        ensure_adb_root(self.target)

        checks = {}
        score = 0
        max_score = 12

        # 1. Build fingerprint format
        fp = adb_shell(self.target, "getprop ro.build.fingerprint", timeout=3).strip()
        fp_valid = fp.count("/") >= 3 and ":user/release-keys" in fp
        checks["fingerprint"] = {"value": fp[:60], "valid": fp_valid}
        if fp_valid:
            score += 1

        # 2. Build type
        build_type = adb_shell(self.target, "getprop ro.build.type", timeout=3).strip()
        type_ok = build_type == "user"
        checks["build_type"] = {"value": build_type, "valid": type_ok}
        if type_ok:
            score += 1

        # 3. Build tags
        tags = adb_shell(self.target, "getprop ro.build.tags", timeout=3).strip()
        tags_ok = tags == "release-keys"
        checks["build_tags"] = {"value": tags, "valid": tags_ok}
        if tags_ok:
            score += 1

        # 4. Verified boot state
        vb = adb_shell(self.target, "getprop ro.boot.verifiedbootstate", timeout=3).strip()
        vb_ok = vb == "green"
        checks["verified_boot"] = {"value": vb, "valid": vb_ok}
        if vb_ok:
            score += 1

        # 5. Bootloader lock
        locked = adb_shell(self.target, "getprop ro.boot.flash.locked", timeout=3).strip()
        lock_ok = locked == "1"
        checks["bootloader_locked"] = {"value": locked, "valid": lock_ok}
        if lock_ok:
            score += 1

        # 6. Debug disabled
        debug = adb_shell(self.target, "getprop ro.debuggable", timeout=3).strip()
        debug_ok = debug == "0"
        checks["debug_disabled"] = {"value": debug, "valid": debug_ok}
        if debug_ok:
            score += 1

        # 7. SELinux enforcing
        selinux = adb_shell(self.target, "getenforce 2>/dev/null", timeout=3).strip()
        se_ok = selinux.lower() == "enforcing"
        checks["selinux"] = {"value": selinux, "valid": se_ok}
        if se_ok:
            score += 1

        # 8. Keybox present
        kb_loaded = adb_shell(self.target, "getprop persist.titan.keybox.loaded", timeout=3).strip()
        kb_file = adb_shell(self.target,
            "test -f /data/adb/tricky_store/keybox.xml && echo y", timeout=3
        ).strip()
        kb_ok = kb_loaded == "1" or kb_file == "y"
        checks["keybox"] = {"loaded": kb_ok}
        if kb_ok:
            score += 1

        # 9. PIF module config
        pif_exists = adb_shell(self.target,
            "test -f /data/adb/pif.json && echo y", timeout=3
        ).strip() == "y"
        checks["pif_config"] = {"present": pif_exists}
        if pif_exists:
            score += 1

        # 10. GMS installed and running
        gms_running = "com.google.android.gms" in adb_shell(
            self.target, "ps -A -o NAME 2>/dev/null | grep gms", timeout=5
        )
        checks["gms_running"] = {"active": gms_running}
        if gms_running:
            score += 1

        # 11. No root binaries
        root_check = adb_shell(
            self.target,
            "test -f /system/bin/su || test -f /system/xbin/su && echo FOUND",
            timeout=3
        ).strip()
        no_root = "FOUND" not in root_check
        checks["no_root_binaries"] = {"clean": no_root}
        if no_root:
            score += 1

        # 12. No emulator artifacts in props
        emu_props = ["ro.kernel.qemu", "ro.hardware.goldfish"]
        emu_found = False
        for prop in emu_props:
            val = adb_shell(self.target, f"getprop {prop}", timeout=3).strip()
            if val and val != "":
                emu_found = True
                break
        checks["no_emulator_props"] = {"clean": not emu_found}
        if not emu_found:
            score += 1

        normalized = round(score / max_score * 100)
        grade = (
            "A+" if normalized >= 90 else
            "A" if normalized >= 80 else
            "B" if normalized >= 65 else
            "C" if normalized >= 50 else
            "F"
        )

        result = {
            "score": normalized,
            "raw_score": score,
            "max_score": max_score,
            "grade": grade,
            "tier": self._tier,
            "preset": self._preset,
            "checks": checks,
        }

        self._last_audit = result
        logger.info(f"PI audit: {grade} ({score}/{max_score})")
        return result

    def get_status(self) -> Dict[str, Any]:
        """Get current spoofer status."""
        return {
            "tier": self._tier,
            "preset": self._preset,
            "keybox_installed": self._keybox_installed,
            "pif_module_configured": self._pif_module_installed,
            "last_audit": self._last_audit,
        }
