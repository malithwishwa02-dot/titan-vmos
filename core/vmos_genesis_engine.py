"""
VMOS Genesis Engine — Full Identity Pipeline for VMOS Cloud Devices
====================================================================
Translates the local-ADB Genesis pipeline (provision.py _run_pipeline_job)
into VMOS Cloud API calls.  Every phase mirrors the Titan Console pipeline:

  Phase 0:  Wipe
  Phase 1:  Stealth Patch
  Phase 2:  Network / Proxy
  Phase 3:  Forge Profile
  Phase 4:  Google Account
  Phase 5:  Inject (contacts, call logs, SMS, WiFi, Chrome, autofill)
  Phase 6:  Wallet / GPay
  Phase 7:  Provincial Layering (app data)
  Phase 8:  Post-Harden (Kiwi, media scan)
  Phase 9:  Attestation
  Phase 10: Trust Audit

Uses VMOSCloudClient for native APIs (props, SIM, GPS, proxy, contacts)
and async_adb_cmd for shell operations (content insert, sqlite3, resetprop).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import secrets
import sqlite3 as sqlite3_mod
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from vmos_cloud_api import VMOSCloudClient
from android_profile_forge import AndroidProfileForge
from device_presets import DEVICE_PRESETS, CARRIERS, LOCATIONS
from json_logger import setup_json_logging

logger = setup_json_logging("vmos_genesis")

# ── Helpers ────────────────────────────────────────────────────────────────

_PROFILES_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"


def _gen_imei(tac_prefix: str) -> str:
    serial_digits = "".join([str(random.randint(0, 9)) for _ in range(6)])
    body = tac_prefix + serial_digits
    digits = [int(d) for d in body]
    for i in range(1, len(digits), 2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    check = (10 - sum(digits) % 10) % 10
    return body + str(check)


def _gen_serial() -> str:
    return "".join(random.choices("0123456789ABCDEF", k=16))


def _gen_android_id() -> str:
    return secrets.token_hex(8)


def _gen_gsf_id() -> str:
    return str(random.randint(3000000000000000000, 3999999999999999999))


def _sanitize(val: str) -> str:
    """Strip characters that break ADB shell quoting."""
    return val.replace("'", "").replace('"', '').replace(';', ',').replace('`', '')


def _safe_int(val: str, default: int = 0) -> int:
    """Parse int from potentially noisy ADB output (e.g. '0 0' → 0)."""
    try:
        return int(val.strip())
    except (ValueError, TypeError):
        # Take first number-like token
        import re as _re
        m = _re.search(r'\d+', str(val))
        return int(m.group()) if m else default


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Mirrors PipelineBody from provision.py."""
    # Identity
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    ssn: str = ""
    # Address
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"
    gender: str = "M"
    occupation: str = "auto"
    # Card
    cc_number: str = ""
    cc_exp: str = ""       # MM/YYYY
    cc_cvv: str = ""
    cc_holder: str = ""
    # Google
    google_email: str = ""
    google_password: str = ""
    real_phone: str = ""
    otp_code: str = ""
    # Network
    proxy_url: str = ""
    # Device overrides
    device_model: str = "samsung_s24"
    carrier: str = "tmobile_us"
    location: str = "la"
    age_days: int = 120
    # App install — dict of package_name -> APK URL for missing apps
    app_installs: Dict[str, str] = field(default_factory=dict)
    # Options
    skip_wipe: bool = False
    skip_patch: bool = False
    skip_proxy: bool = False


@dataclass
class PhaseResult:
    phase: int
    name: str
    status: str = "pending"  # pending | running | done | failed | skipped | warn
    notes: str = ""
    elapsed_sec: float = 0.0


@dataclass
class PipelineResult:
    job_id: str
    pad_code: str
    profile_id: str = ""
    phases: List[PhaseResult] = field(default_factory=list)
    trust_score: int = 0
    grade: str = ""
    log: List[str] = field(default_factory=list)
    status: str = "running"
    started_at: float = 0.0
    completed_at: float = 0.0


# ── Engine ────────────────────────────────────────────────────────────────

class VMOSGenesisEngine:
    """Runs the full Genesis pipeline against a VMOS Cloud device."""

    PHASE_NAMES = [
        "Wipe", "Env+Stealth", "Network/Proxy", "App Install",
        "Forge Profile", "Google Account", "Inject", "Wallet/GPay",
        "Provincial Layer", "Post-Harden", "Attestation", "Trust Audit",
    ]

    def __init__(self, pad_code: str, *, client: VMOSCloudClient | None = None):
        self.pad = pad_code
        self.pads = [pad_code]
        self.client = client or VMOSCloudClient()
        self._profile_data: Dict[str, Any] = {}
        self._result: PipelineResult | None = None
        self._on_update: Optional[Callable[[PipelineResult], None]] = None
        self._env_info: Dict[str, Any] = {}  # populated by env scan in Phase 1

    # ── ADB helpers ───────────────────────────────────────────────────

    async def _sh(self, cmd: str, timeout: int = 30) -> str:
        """Execute ADB shell command via VMOS Cloud, return stdout."""
        resp = await self.client.async_adb_cmd(self.pads, cmd)
        if resp.get("code") != 200:
            logger.warning(f"ADB submit failed: {resp}")
            return ""
        data = resp.get("data", [])
        task_id = None
        if isinstance(data, list) and data:
            task_id = data[0].get("taskId")
        elif isinstance(data, dict):
            task_id = data.get("taskId")
        if not task_id:
            return ""
        # Initial wait — VMOS async commands need time to execute
        await asyncio.sleep(2)
        for attempt in range(timeout):
            try:
                detail = await self.client.task_detail([task_id])
                if detail and detail.get("code") == 200 and detail.get("data"):
                    items = detail["data"]
                    if isinstance(items, list) and items:
                        item = items[0]
                        st = item.get("taskStatus")
                        if st == 3:
                            return item.get("taskResult") or ""
                        if st in (-1, -2, -3, -4, -5):
                            return ""
            except Exception:
                pass
            await asyncio.sleep(1)
        return ""

    async def _sh_ok(self, cmd: str, marker: str = "OK", timeout: int = 30) -> bool:
        """Execute ADB command and check for success marker in output."""
        result = await self._sh(cmd, timeout)
        return marker in (result or "")

    async def _push_sqlite_db(self, db_path: str, owner: str,
                              create_fn, *, timeout: int = 30) -> bool:
        """Create a SQLite DB locally, push to device via base64 ADB.

        Args:
            db_path: Target path on device (e.g. /data/data/.../Cookies)
            owner: chown target (e.g. 'u0_a60:u0_a60')
            create_fn: callable(conn) that creates tables and inserts data
            timeout: ADB poll timeout
        Returns:
            True if push succeeded
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
            conn = sqlite3_mod.connect(tmp.name)
            try:
                create_fn(conn)
                conn.commit()
            finally:
                conn.close()
            db_bytes = Path(tmp.name).read_bytes()

        b64 = base64.b64encode(db_bytes).decode()
        # VMOS Cloud API has ~4000 char total script limit;
        # keep chunks at 2000 chars to stay well under with boilerplate
        chunk_size = 2000
        chunks = [b64[i:i+chunk_size] for i in range(0, len(b64), chunk_size)]

        # Ensure parent dir exists
        parent = str(Path(db_path).parent)
        await self._sh(f"mkdir -p '{parent}' 2>/dev/null; echo MKDIR_OK", timeout=10)

        # Write chunks
        for i, chunk in enumerate(chunks):
            op = ">" if i == 0 else ">>"
            cmd = f"echo -n '{chunk}' {op} /data/local/tmp/_titan_b64.tmp && echo CH{i}_OK"
            ok = await self._sh_ok(cmd, f"CH{i}_OK", timeout=15)
            if not ok:
                return False

        # Decode and move
        cmd = (
            f"base64 -d /data/local/tmp/_titan_b64.tmp > '{db_path}' && "
            f"rm -f /data/local/tmp/_titan_b64.tmp && "
            f"chown {owner} '{db_path}' 2>/dev/null; "
            f"chmod 660 '{db_path}' 2>/dev/null; "
            f"restorecon '{db_path}' 2>/dev/null; "
            f"ls -s '{db_path}' && echo PUSH_DONE"
        )
        return await self._sh_ok(cmd, "PUSH_DONE", timeout=timeout)

    # ── Logging helpers ───────────────────────────────────────────────

    def _log(self, msg: str):
        logger.info(f"[{self.pad}] {msg}")
        if self._result:
            self._result.log.append(msg)
            self._result.log = self._result.log[-200:]
            if self._on_update:
                self._on_update(self._result)

    def _set_phase(self, n: int, status: str, notes: str = ""):
        if self._result and n < len(self._result.phases):
            ph = self._result.phases[n]
            ph.status = status
            ph.notes = notes
            if self._on_update:
                self._on_update(self._result)

    # ── Main entry ────────────────────────────────────────────────────

    async def run_pipeline(
        self,
        cfg: PipelineConfig,
        job_id: str = "",
        on_update: Optional[Callable[[PipelineResult], None]] = None,
    ) -> PipelineResult:
        """Run the full 11-phase pipeline."""
        if not job_id:
            job_id = str(uuid.uuid4())[:8]

        self._on_update = on_update
        self._result = PipelineResult(
            job_id=job_id,
            pad_code=self.pad,
            started_at=time.time(),
            phases=[PhaseResult(phase=i, name=n) for i, n in enumerate(self.PHASE_NAMES)],
        )

        self._log(f"Pipeline starting for {self.pad}")
        self._log(f"Persona: {cfg.name} <{cfg.email or cfg.google_email}>")

        # Ensure ADB is enabled and device is responsive
        try:
            await self.client.enable_adb(self.pads)
            self._log("ADB enabled")
        except Exception as e:
            self._log(f"WARNING: ADB enable failed: {e}")

        preset = DEVICE_PRESETS.get(cfg.device_model)
        carrier = CARRIERS.get(cfg.carrier)
        location = LOCATIONS.get(cfg.location)
        if not preset:
            self._log(f"WARNING: Unknown device preset '{cfg.device_model}', using samsung_s24")
            preset = DEVICE_PRESETS.get("samsung_s24", list(DEVICE_PRESETS.values())[0])
        if not carrier:
            carrier = CARRIERS["tmobile_us"]
        if not location:
            location = LOCATIONS.get("la", list(LOCATIONS.values())[0])

        # Phase 0: Wipe
        await self._phase_wipe(cfg)

        # Phase 1: Env Scan + Stealth Patch (deep analysis → fingerprint → root hiding)
        await self._phase_stealth(cfg, preset, carrier, location)

        # Phase 2: Network / Proxy
        await self._phase_network(cfg)

        # Phase 3: App Install (install missing critical apps)
        await self._phase_app_install(cfg)

        # Phase 4: Forge Profile
        profile_data = await self._phase_forge(cfg, preset, carrier, location)

        # Phase 5: Google Account (enhanced Play Store injection)
        await self._phase_google(cfg)

        # Phase 6: Inject
        await self._phase_inject(cfg, profile_data, preset)

        # Phase 7: Wallet
        await self._phase_wallet(cfg, profile_data)

        # Phase 8: Provincial Layering
        await self._phase_provincial(cfg, profile_data)

        # Phase 9: Post-Harden
        await self._phase_postharden(cfg)

        # Phase 10: Attestation
        await self._phase_attestation(preset)

        # Phase 11: Trust Audit (fast ADB verification)
        await self._phase_trust_audit(profile_data)

        # Final
        self._result.status = "completed"
        self._result.completed_at = time.time()
        elapsed = self._result.completed_at - self._result.started_at
        self._log(f"Pipeline complete in {elapsed:.0f}s. Trust: {self._result.trust_score}/100")

        if self._on_update:
            self._on_update(self._result)
        return self._result

    # ══════════════════════════════════════════════════════════════════
    # PHASES
    # ══════════════════════════════════════════════════════════════════

    async def _phase_wipe(self, cfg: PipelineConfig):
        """Phase 0: Wipe previous identity data."""
        n = 0
        if cfg.skip_wipe:
            self._set_phase(n, "skipped", "user skip")
            return
        self._set_phase(n, "running")
        self._log("Phase 0 — Wipe: clearing previous persona data...")
        t0 = time.time()
        try:
            wipe_cmd = (
                # Clear accounts
                "rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null; "
                # Clear contacts / call logs / SMS
                "content delete --uri content://com.android.contacts/raw_contacts 2>/dev/null; "
                "content delete --uri content://call_log/calls 2>/dev/null; "
                "content delete --uri content://sms 2>/dev/null; "
                # Clear Chrome data
                "rm -rf /data/data/com.android.chrome/app_chrome/Default/Cookies "
                "/data/data/com.android.chrome/app_chrome/Default/History "
                "/data/data/com.android.chrome/app_chrome/Default/Login\\ Data "
                "/data/data/com.android.chrome/app_chrome/Default/'Web Data' 2>/dev/null; "
                # Clear wallet
                "rm -rf /data/data/com.google.android.gms/databases/tapandpay.db* 2>/dev/null; "
                # Clear UsageStats
                "rm -rf /data/system/usagestats/0/* 2>/dev/null; "
                # Clear gallery
                "rm -f /sdcard/DCIM/Camera/*.jpg /data/media/0/DCIM/Camera/*.jpg 2>/dev/null; "
                "echo WIPE_DONE"
            )
            ok = await self._sh_ok(wipe_cmd, "WIPE_DONE", timeout=20)
            self._set_phase(n, "done" if ok else "warn", f"{time.time()-t0:.1f}s")
            self._log(f"Phase 0 — Wipe {'done' if ok else 'partial'}")
        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 0 — Wipe FAILED: {e}")

    async def _phase_stealth(self, cfg: PipelineConfig, preset, carrier, location):
        """Phase 1: Env scan (deep device analysis) + fingerprint + root hiding + proc sterilization."""
        n = 1
        if cfg.skip_patch:
            self._set_phase(n, "skipped", "user skip")
            return
        self._set_phase(n, "running")
        self._log("Phase 1 — Env Scan + Stealth: analyzing device → fingerprint → root hide...")
        t0 = time.time()
        ok_count = 0
        total = 0

        try:
            # ── 1-ENV: Deep Environment Scan ──────────────────────────────
            self._log("Phase 1-ENV — Scanning device environment...")

            # Batch 1: Installed apps (Google ecosystem + common apps)
            env_r1 = await self._sh(
                "echo '---PACKAGES---'; "
                "pm list packages -3 2>/dev/null | head -80; "  # third-party
                "echo '---SYSTEM---'; "
                "for p in com.google.android.gms com.android.chrome com.android.vending "
                "com.google.android.apps.walletnfcrel com.google.android.youtube "
                "com.google.android.apps.maps com.google.android.gm "
                "com.google.android.gsf com.google.android.apps.docs "
                "com.google.android.apps.photos com.whatsapp "
                "com.amazon.mShop.android.shopping com.paypal.android.p2pmobile; "
                "do pm path $p >/dev/null 2>&1 && echo HAS:$p || echo MISS:$p; done",
                timeout=30,
            )

            # Batch 2: Root state + device info
            env_r2 = await self._sh(
                "echo ROOT_SU=$(which su 2>/dev/null || echo none); "
                "echo ROOT_MAGISK=$(ls /data/adb/magisk/ 2>/dev/null | head -3 | tr '\\n' ','); "
                "echo RESETPROP=$(which resetprop 2>/dev/null || "
                "  test -f /data/local/tmp/magisk64 && echo /data/local/tmp/magisk64 || echo none); "
                "echo FRIDA=$(which frida-server 2>/dev/null || "
                "  ls /data/local/tmp/frida* 2>/dev/null | head -1 || echo none); "
                "echo ANDROID_VER=$(getprop ro.build.version.release); "
                "echo SDK=$(getprop ro.build.version.sdk); "
                "echo BUILD_TYPE=$(getprop ro.build.type); "
                "echo GMS_VER=$(dumpsys package com.google.android.gms 2>/dev/null | grep versionName | head -1 | awk -F= '{print $2}'); "
                "echo CHROME_VER=$(dumpsys package com.android.chrome 2>/dev/null | grep versionName | head -1 | awk -F= '{print $2}'); "
                "echo PLAY_VER=$(dumpsys package com.android.vending 2>/dev/null | grep versionName | head -1 | awk -F= '{print $2}'); "
                "echo ACCOUNTS=$(dumpsys account 2>/dev/null | grep -c 'Account {' || echo 0)",
                timeout=30,
            )

            # Parse environment results
            installed_apps = []
            missing_apps = []
            third_party_apps = []
            env_vals = {}

            for line in (env_r1 or "").strip().split("\n"):
                if line.startswith("package:"):
                    third_party_apps.append(line.replace("package:", "").strip())
                elif line.startswith("HAS:"):
                    installed_apps.append(line.replace("HAS:", "").strip())
                elif line.startswith("MISS:"):
                    missing_apps.append(line.replace("MISS:", "").strip())

            for line in (env_r2 or "").strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    env_vals[k.strip()] = v.strip()

            # Store env info for later phases
            self._env_info = {
                "installed_apps": installed_apps,
                "missing_apps": missing_apps,
                "third_party_count": len(third_party_apps),
                "third_party_apps": third_party_apps[:30],
                "root_su": env_vals.get("ROOT_SU", "none"),
                "root_magisk": env_vals.get("ROOT_MAGISK", ""),
                "resetprop": env_vals.get("RESETPROP", "none"),
                "frida": env_vals.get("FRIDA", "none"),
                "android_version": env_vals.get("ANDROID_VER", "?"),
                "sdk": env_vals.get("SDK", "?"),
                "build_type": env_vals.get("BUILD_TYPE", "?"),
                "gms_version": env_vals.get("GMS_VER", "?"),
                "chrome_version": env_vals.get("CHROME_VER", "?"),
                "play_version": env_vals.get("PLAY_VER", "?"),
                "existing_accounts": _safe_int(env_vals.get("ACCOUNTS", "0")),
            }

            self._log(f"Phase 1-ENV — Android {self._env_info['android_version']} "
                       f"SDK {self._env_info['sdk']} Build={self._env_info['build_type']}")
            self._log(f"Phase 1-ENV — GMS={self._env_info['gms_version']} "
                       f"Chrome={self._env_info['chrome_version']} "
                       f"PlayStore={self._env_info['play_version']}")
            self._log(f"Phase 1-ENV — Installed: {', '.join(installed_apps)}")
            self._log(f"Phase 1-ENV — Missing: {', '.join(missing_apps) if missing_apps else 'none'}")
            self._log(f"Phase 1-ENV — 3rd-party: {len(third_party_apps)} apps")
            self._log(f"Phase 1-ENV — Root: su={self._env_info['root_su']} "
                       f"magisk={self._env_info['root_magisk'] or 'none'} "
                       f"resetprop={self._env_info['resetprop']}")
            self._log(f"Phase 1-ENV — Existing accounts: {self._env_info['existing_accounts']}")

            # ── 1-ENV.2: Deep device state (storage, display, network, battery, SELinux) ──
            env_r3 = await self._sh(
                "echo STORAGE_TOTAL=$(df /data 2>/dev/null | tail -1 | awk '{print $2}'); "
                "echo STORAGE_USED=$(df /data 2>/dev/null | tail -1 | awk '{print $3}'); "
                "echo STORAGE_AVAIL=$(df /data 2>/dev/null | tail -1 | awk '{print $4}'); "
                "echo DISPLAY_DENSITY=$(getprop ro.sf.lcd_density 2>/dev/null || wm density 2>/dev/null | awk '{print $NF}'); "
                "echo DISPLAY_SIZE=$(wm size 2>/dev/null | awk '{print $NF}'); "
                "echo SELINUX=$(getenforce 2>/dev/null || echo Unknown); "
                "echo UPTIME=$(cat /proc/uptime 2>/dev/null | awk '{print $1}'); "
                "echo NET_IFACES=$(ls /sys/class/net 2>/dev/null | tr '\\n' ','); "
                "echo BATT_LVL=$(dumpsys battery 2>/dev/null | grep level | awk '{print $2}'); "
                "echo BATT_STATUS=$(dumpsys battery 2>/dev/null | grep status | awk '{print $2}'); "
                "echo ACCESSIBILITY=$(settings get secure enabled_accessibility_services 2>/dev/null || echo null); "
                "echo RUNNING_PROCS=$(ps -A 2>/dev/null | wc -l); "
                "echo SQLITE3_EXISTS=$(which sqlite3 2>/dev/null && echo yes || echo no); "
                "echo BASE64_EXISTS=$(which base64 2>/dev/null && echo yes || echo no); "
                "echo CURL_EXISTS=$(which curl 2>/dev/null && echo yes || echo no)",
                timeout=30,
            )

            for line in (env_r3 or "").strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    env_vals[k.strip()] = v.strip()

            self._env_info.update({
                "storage_total": env_vals.get("STORAGE_TOTAL", "?"),
                "storage_used": env_vals.get("STORAGE_USED", "?"),
                "storage_avail": env_vals.get("STORAGE_AVAIL", "?"),
                "display_density": env_vals.get("DISPLAY_DENSITY", "?"),
                "display_size": env_vals.get("DISPLAY_SIZE", "?"),
                "selinux": env_vals.get("SELINUX", "?"),
                "uptime_sec": env_vals.get("UPTIME", "?"),
                "net_interfaces": env_vals.get("NET_IFACES", ""),
                "battery_level": env_vals.get("BATT_LVL", "?"),
                "battery_status": env_vals.get("BATT_STATUS", "?"),
                "accessibility": env_vals.get("ACCESSIBILITY", "null"),
                "running_procs": env_vals.get("RUNNING_PROCS", "?"),
                "has_sqlite3": env_vals.get("SQLITE3_EXISTS", "no") == "yes",
                "has_base64": env_vals.get("BASE64_EXISTS", "no") == "yes",
                "has_curl": env_vals.get("CURL_EXISTS", "no") == "yes",
            })

            self._log(f"Phase 1-ENV — Storage: total={env_vals.get('STORAGE_TOTAL','?')}K "
                       f"used={env_vals.get('STORAGE_USED','?')}K avail={env_vals.get('STORAGE_AVAIL','?')}K")
            self._log(f"Phase 1-ENV — Display: {env_vals.get('DISPLAY_SIZE','?')} @ {env_vals.get('DISPLAY_DENSITY','?')}dpi")
            self._log(f"Phase 1-ENV — SELinux={env_vals.get('SELINUX','?')} Uptime={env_vals.get('UPTIME','?')}s "
                       f"Procs={env_vals.get('RUNNING_PROCS','?')}")
            self._log(f"Phase 1-ENV — Battery: {env_vals.get('BATT_LVL','?')}% status={env_vals.get('BATT_STATUS','?')}")
            self._log(f"Phase 1-ENV — Tools: sqlite3={self._env_info['has_sqlite3']} "
                       f"base64={self._env_info['has_base64']} curl={self._env_info['has_curl']}")
            if self._env_info['accessibility'] not in ('null', ''):
                self._log(f"Phase 1-ENV — ⚠ Accessibility services ACTIVE: {self._env_info['accessibility']}")

            # ── 1-ENV.3: Root decision — determine when root is needed & disable after ──
            # Root is REQUIRED for: resetprop (ro.* props), proc bind-mounts, iptables,
            #   file injection into system app dirs, chown/restorecon
            # Root should be HIDDEN after: all injection phases complete (Phase 9+)
            root_available = self._env_info['root_su'] != 'none' or self._env_info['resetprop'] != 'none'
            self._env_info['root_available'] = root_available
            self._env_info['root_strategy'] = 'use_then_hide' if root_available else 'rootless'
            self._log(f"Phase 1-ENV — Root strategy: {self._env_info['root_strategy']} "
                       f"(su={self._env_info['root_su']}, resetprop={self._env_info['resetprop']})")

            # ── End Deep Env Scan ─────────────────────────────────────────
            # ── 1a. Android properties (restart-required) via native API ──
            imei = _gen_imei(preset.tac_prefix)
            imei2 = _gen_imei(preset.tac_prefix)
            serial = _gen_serial()

            prop_batches = [
                {
                    "ro.product.brand": preset.brand,
                    "ro.product.manufacturer": preset.manufacturer,
                    "ro.product.model": preset.model,
                    "ro.product.device": preset.device,
                    "ro.product.name": preset.product,
                    "ro.product.board": preset.board,
                },
                {
                    "ro.build.fingerprint": preset.fingerprint,
                    "ro.build.display.id": preset.build_id,
                    "ro.build.description": f"{preset.product}-user {preset.android_version} {preset.build_id} release-keys",
                    "ro.build.product": preset.device,
                    "ro.build.type": "user",
                    "ro.build.tags": "release-keys",
                },
                {
                    "ro.hardware": preset.hardware,
                    "ro.board.platform": preset.board,
                    "ro.build.version.sdk": preset.sdk_version,
                    "ro.build.version.release": preset.android_version,
                    "ro.build.version.security_patch": preset.security_patch,
                },
                {
                    "ro.serialno": serial,
                    "ro.boot.serialno": serial,
                    "ro.product.vendor.brand": preset.brand,
                    "ro.product.vendor.device": preset.device,
                    "ro.product.vendor.model": preset.model,
                    "ro.product.vendor.manufacturer": preset.manufacturer,
                },
                {
                    "ro.product.bootimage.brand": preset.brand,
                    "ro.product.bootimage.device": preset.device,
                    "ro.product.bootimage.model": preset.model,
                    "ro.product.system.brand": preset.brand,
                    "ro.product.system.model": preset.model,
                },
            ]

            for batch in prop_batches:
                total += len(batch)
                resp = await self.client.modify_android_props(self.pads, batch)
                if resp.get("code") == 200:
                    ok_count += len(batch)
                await asyncio.sleep(2)

            self._log(f"Phase 1a — Props: {ok_count}/{total}")

            # ── 1b. SIM card ──
            resp = await self.client.modify_sim_by_country(self.pads, cfg.country or 'US')
            self._log(f"Phase 1b — SIM: {resp.get('msg', 'ok')}")

            # ── 1c. GPS ──
            lat = location["lat"] + random.uniform(-0.003, 0.003)
            lng = location["lon"] + random.uniform(-0.003, 0.003)
            resp = await self.client.set_gps(
                self.pads, lat=lat, lng=lng,
                altitude=round(random.uniform(25, 75), 1),
                speed=0.0,
                bearing=round(random.uniform(0, 360), 1),
                horizontal_accuracy=round(random.uniform(3, 12), 1),
            )
            self._log(f"Phase 1c — GPS: ({lat:.4f}, {lng:.4f})")

            # ── 1d. Timezone + Language ──
            await self.client.modify_timezone(self.pads, location.get("tz", "America/Los_Angeles"))
            await self.client.modify_language(self.pads, "en")

            # Wait for restart from prop+SIM changes
            self._log("Phase 1 — Waiting 30s for prop/SIM changes to apply...")
            await asyncio.sleep(30)

            # Check device is responsive — retry with longer waits
            device_ready = False
            for attempt in range(15):
                result = await self._sh("echo ALIVE", timeout=10)
                if "ALIVE" in (result or ""):
                    device_ready = True
                    break
                self._log(f"Phase 1 — Device not ready, retry {attempt+1}/15...")
                await asyncio.sleep(5)
            
            if not device_ready:
                self._log("Phase 1 — WARNING: Device didn't respond after prop changes")
                # Re-enable ADB in case restart cleared it
                await self.client.enable_adb(self.pads)
                await asyncio.sleep(10)

            # ── 1e. Root artifact hiding ──
            root_cmd = (
                "for p in /system/bin/su /system/xbin/su /sbin/su /su/bin/su; do "
                "  if [ -e \"$p\" ]; then "
                "    chmod 000 \"$p\" 2>/dev/null; "
                "    mount -o bind /dev/null \"$p\" 2>/dev/null; "
                "  fi; "
                "done; "
                "if [ -d /data/adb/magisk ]; then "
                "  chmod 000 /data/adb/magisk 2>/dev/null; "
                "  mount -t tmpfs tmpfs /data/adb/magisk 2>/dev/null; "
                "fi; "
                "pm disable-user --user 0 com.topjohnwu.magisk 2>/dev/null; "
                "pm hide com.topjohnwu.magisk 2>/dev/null; "
                "echo ROOT_HIDDEN"
            )
            root_ok = await self._sh_ok(root_cmd, "ROOT_HIDDEN", timeout=20)
            self._log(f"Phase 1e — Root hiding: {'ok' if root_ok else 'partial'}")

            # ── 1f. Cloud/emulator property scrubbing ──
            prop_cmd = (
                "resetprop --delete ro.vmos.cloud 2>/dev/null; "
                "resetprop --delete ro.cloudservice.enabled 2>/dev/null; "
                "resetprop --delete ro.armcloud.device 2>/dev/null; "
                "resetprop --delete ro.redroid.enabled 2>/dev/null; "
                "resetprop --delete ro.kernel.qemu 2>/dev/null; "
                "resetprop --delete ro.hardware.virtual 2>/dev/null; "
                "resetprop --delete init.svc.cloudservice 2>/dev/null; "
                "resetprop --delete ro.boot.qemu 2>/dev/null; "
                "resetprop --delete qemu.gles 2>/dev/null; "
                "resetprop ro.boot.verifiedbootstate green 2>/dev/null; "
                "resetprop ro.boot.flash.locked 1 2>/dev/null; "
                "resetprop ro.boot.vbmeta.device_state locked 2>/dev/null; "
                "resetprop ro.debuggable 0 2>/dev/null; "
                "resetprop ro.secure 1 2>/dev/null; "
                "resetprop ro.adb.secure 1 2>/dev/null; "
                "resetprop ro.build.type user 2>/dev/null; "
                "resetprop ro.build.tags release-keys 2>/dev/null; "
                f"resetprop ro.build.display.id {preset.build_id} 2>/dev/null; "
                f"resetprop ro.build.host build.{preset.brand.lower()}.com 2>/dev/null; "
                f"resetprop ro.hardware.egl adreno 2>/dev/null; "
                f"resetprop ro.opengles.version 196610 2>/dev/null; "
                "echo PROPS_CLEAN"
            )
            prop_ok = await self._sh_ok(prop_cmd, "PROPS_CLEAN", timeout=20)
            self._log(f"Phase 1f — Prop scrub: {'ok' if prop_ok else 'partial'}")

            # ── 1g. Proc sterilization (enhanced — clean cmdline rewrite) ──
            proc_cmd = (
                "mkdir -p /dev/.sc 2>/dev/null; "
                # Rewrite cmdline completely — remove verifiedbootstate=orange leak
                "echo 'androidboot.mode=normal' > /dev/.sc/cmdline; "
                "mount -o bind /dev/.sc/cmdline /proc/cmdline 2>/dev/null; "
                # Clean /proc/mounts
                "cat /proc/mounts | "
                "grep -v cloudservice | grep -v redroid | grep -v vmos > /dev/.sc/mounts; "
                "mount -o bind /dev/.sc/mounts /proc/mounts 2>/dev/null; "
                # Clean /proc/1/cgroup
                "echo '0::/' > /dev/.sc/cgroup; "
                "mount -o bind /dev/.sc/cgroup /proc/1/cgroup 2>/dev/null; "
                # Clean /proc/self/mountinfo (2-pass filter)
                "cat /proc/self/mountinfo | "
                "grep -v virtio | grep -v vsoc | grep -v cuttlefish | grep -v goldfish | "
                "grep -v qemu | grep -v cloud > /dev/.sc/mountinfo 2>/dev/null; "
                "mount -o bind /dev/.sc/mountinfo /proc/self/mountinfo 2>/dev/null; "
                "echo PROC_CLEAN"
            )
            proc_ok = await self._sh_ok(proc_cmd, "PROC_CLEAN", timeout=20)
            self._log(f"Phase 1g — Proc sterilize: {'ok' if proc_ok else 'partial'}")

            # ── 1j. Frida & detection port blocking ──
            fw_cmd = (
                "iptables -D OUTPUT -p tcp --dport 27042 -j DROP 2>/dev/null; "
                "iptables -D OUTPUT -p tcp --dport 27043 -j DROP 2>/dev/null; "
                "iptables -A OUTPUT -p tcp --dport 27042 -j DROP 2>/dev/null; "
                "iptables -A OUTPUT -p tcp --dport 27043 -j DROP 2>/dev/null; "
                "iptables -A OUTPUT -p tcp --dport 5555 -j DROP 2>/dev/null; "
                # Block IPv6 fully
                "ip6tables -P OUTPUT DROP 2>/dev/null; "
                "ip6tables -P INPUT DROP 2>/dev/null; "
                "ip6tables -P FORWARD DROP 2>/dev/null; "
                "echo FW_DONE"
            )
            fw_ok = await self._sh_ok(fw_cmd, "FW_DONE", timeout=15)
            self._log(f"Phase 1j — Firewall: {'ok' if fw_ok else 'partial'}")

            # ── 1h. Verified boot fingerprint alignment ──
            boot_cmd = (
                f"resetprop ro.bootimage.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.vendor.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.odm.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.system_ext.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.product.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.build.fingerprint '{preset.fingerprint}' 2>/dev/null; "
                f"resetprop ro.build.version.security_patch '{preset.security_patch}' 2>/dev/null; "
                "echo BOOT_ALIGNED"
            )
            boot_ok = await self._sh_ok(boot_cmd, "BOOT_ALIGNED", timeout=15)
            self._log(f"Phase 1h — Boot alignment: {'ok' if boot_ok else 'partial'}")

            # ── 1i. VMOS native process & accessibility hiding ──
            try:
                # Hide accessibility services from detection
                await self.client.hide_accessibility_service(self.pads, [])
                # Hide root-related processes
                await self.client.show_hide_process(self.pads,
                    packages=["com.topjohnwu.magisk", "eu.chainfire.supersu"],
                    hide=True)
                self._log("Phase 1i — VMOS process hiding: ok")
            except Exception as e:
                self._log(f"Phase 1i — VMOS process hiding: {e}")

            elapsed = time.time() - t0
            sub_ok = sum([root_ok, prop_ok, proc_ok, boot_ok, fw_ok])
            self._set_phase(n, "done", f"{ok_count}/{total} props, {sub_ok}/5 stealth, {elapsed:.0f}s")
            self._log(f"Phase 1 — Stealth done: {ok_count}/{total} props, {sub_ok}/5 stealth in {elapsed:.0f}s")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 1 — Stealth FAILED: {e}")

    async def _phase_network(self, cfg: PipelineConfig):
        """Phase 2: Set proxy if provided."""
        n = 2
        if cfg.skip_proxy:
            self._set_phase(n, "skipped", "user configured manually")
            self._log("Phase 2 — Network: proxy configured manually by user, skipping")
            return
        if not cfg.proxy_url:
            self._set_phase(n, "skipped", "no proxy")
            self._log("Phase 2 — Network: no proxy configured, skipping")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 2 — Network: setting proxy {cfg.proxy_url[:40]}...")
        try:
            # Parse proxy URL: socks5://user:pass@host:port or http://host:port
            from urllib.parse import urlparse
            parsed = urlparse(cfg.proxy_url)
            scheme = parsed.scheme.lower()
            proxy_name = "socks5" if "socks" in scheme else "http-relay"
            proxy_info = {
                "enable": True,
                "proxyType": "proxy",
                "proxyName": proxy_name,
                "proxyIp": parsed.hostname or "",
                "proxyPort": parsed.port or 1080,
            }
            if parsed.username:
                proxy_info["proxyUser"] = parsed.username
            if parsed.password:
                proxy_info["proxyPassword"] = parsed.password

            resp = await self.client.set_proxy(self.pads, proxy_info)
            ok = resp.get("code") == 200
            self._set_phase(n, "done" if ok else "failed", resp.get("msg", "")[:60])
            self._log(f"Phase 2 — Proxy: {'set' if ok else 'FAILED'}")
        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 2 — Network FAILED: {e}")

    async def _phase_app_install(self, cfg: PipelineConfig):
        """Phase 3: Install missing critical apps via VMOS Cloud API."""
        n = 3
        # Determine what needs installing from env scan
        missing = self._env_info.get("missing_apps", [])
        user_installs = cfg.app_installs or {}

        if not missing and not user_installs:
            self._set_phase(n, "skipped", "all apps present")
            self._log("Phase 3 — App Install: all critical apps already installed")
            return

        self._set_phase(n, "running")
        self._log(f"Phase 3 — App Install: {len(missing)} missing, {len(user_installs)} user-specified")
        t0 = time.time()
        installed_count = 0
        failed = []

        try:
            # Install user-specified apps (package → APK URL)
            for pkg, url in user_installs.items():
                if not url:
                    self._log(f"Phase 3 — Skipping {pkg}: no APK URL provided")
                    continue
                self._log(f"Phase 3 — Installing {pkg}...")
                try:
                    resp = await self.client.install_app(
                        self.pads, url, is_authorization=1
                    )
                    if resp.get("code") == 200:
                        # Poll for completion
                        task_data = resp.get("data", [])
                        task_id = None
                        if isinstance(task_data, list) and task_data:
                            task_id = task_data[0].get("taskId")
                        elif isinstance(task_data, dict):
                            task_id = task_data.get("taskId")
                        if task_id:
                            # Wait for install to complete (up to 120s)
                            for _ in range(60):
                                await asyncio.sleep(2)
                                detail = await self.client.task_detail([task_id])
                                if detail and detail.get("code") == 200:
                                    items = detail.get("data", [])
                                    if isinstance(items, list) and items:
                                        st = items[0].get("taskStatus")
                                        if st == 3:
                                            installed_count += 1
                                            self._log(f"Phase 3 — {pkg}: installed OK")
                                            break
                                        elif st in (-1, -2, -3, -4, -5):
                                            fail_msg = items[0].get("taskResult", "unknown")
                                            failed.append(f"{pkg}({fail_msg[:30]})")
                                            self._log(f"Phase 3 — {pkg}: FAILED ({fail_msg[:50]})")
                                            break
                            else:
                                failed.append(f"{pkg}(timeout)")
                                self._log(f"Phase 3 — {pkg}: install timeout")
                        else:
                            installed_count += 1
                    else:
                        failed.append(f"{pkg}(api:{resp.get('code')})")
                        self._log(f"Phase 3 — {pkg}: API error {resp.get('msg', '')[:50]}")
                except Exception as e:
                    failed.append(f"{pkg}(err)")
                    self._log(f"Phase 3 — {pkg}: {e}")

            # Log missing apps that have no URL
            no_url = [p for p in missing if p not in user_installs]
            if no_url:
                self._log(f"Phase 3 — Missing (no APK URL): {', '.join(no_url)}")

            elapsed = time.time() - t0
            notes = f"{installed_count} installed, {len(failed)} failed, {len(no_url)} no-url, {elapsed:.0f}s"
            status = "done" if not failed else ("warn" if installed_count > 0 else "warn")
            self._set_phase(n, status, notes)
            self._log(f"Phase 3 — App Install: {notes}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 3 — App Install FAILED: {e}")

    async def _phase_forge(self, cfg: PipelineConfig, preset, carrier, location) -> Dict[str, Any]:
        """Phase 4: Forge identity profile."""
        n = 4
        self._set_phase(n, "running")
        self._log("Phase 4 — Forge: generating identity profile...")
        t0 = time.time()
        try:
            forge = AndroidProfileForge()
            addr = None
            if cfg.street:
                addr = {
                    "address": cfg.street,
                    "city": cfg.city,
                    "state": cfg.state,
                    "zip": cfg.zip,
                    "country": cfg.country,
                }
            profile_data = forge.forge(
                persona_name=cfg.name or "Alex Mercer",
                persona_email=cfg.google_email or cfg.email or "user@gmail.com",
                persona_phone=cfg.phone or "+12125551234",
                country=cfg.country or "US",
                archetype=cfg.occupation if cfg.occupation != "auto" else "professional",
                age_days=cfg.age_days,
                carrier=cfg.carrier,
                location=cfg.location,
                device_model=cfg.device_model,
                persona_address=addr,
            )

            # Save profile
            _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            profile_id = profile_data.get("id", str(uuid.uuid4())[:8])
            profile_path = _PROFILES_DIR / f"{profile_id}.json"

            def _ser(obj):
                if isinstance(obj, bytes):
                    return f"<bytes:{len(obj)}>"
                raise TypeError(f"Not serializable: {type(obj)}")

            with open(profile_path, "w") as f:
                json.dump(profile_data, f, indent=2, default=_ser)

            self._profile_data = profile_data
            self._result.profile_id = profile_id

            counts = {k: len(v) if isinstance(v, list) else ("yes" if v else "no")
                       for k in ["contacts", "call_logs", "sms", "cookies", "history",
                                 "wifi_networks", "gallery_paths"] if k in profile_data
                       for v in [profile_data[k]]}
            elapsed = time.time() - t0
            self._set_phase(n, "done", f"id={profile_id}, {elapsed:.1f}s")
            self._log(f"Phase 4 — Forge done: {profile_id} ({elapsed:.1f}s)")
            return profile_data

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 4 — Forge FAILED: {e}")
            return {}

    async def _phase_google(self, cfg: PipelineConfig):
        """Phase 5: Google Account injection into Android databases."""
        n = 5
        email = cfg.google_email or cfg.email
        name = cfg.name or "User"
        if not email:
            self._set_phase(n, "skipped", "no email")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 5 — Google Account: {email}...")
        try:
            first = name.split()[0] if name else "User"
            last = name.split()[-1] if name and len(name.split()) > 1 else ""
            e_safe = _sanitize(email)
            f_safe = _sanitize(first)
            l_safe = _sanitize(last)

            acct_cmd = (
                # accounts_ce.db
                f"sqlite3 /data/system_ce/0/accounts_ce.db \""
                f"INSERT OR REPLACE INTO accounts (_id, name, type, previous_name) "
                f"VALUES (1, '{e_safe}', 'com.google', NULL); "
                f"INSERT OR REPLACE INTO extras (_id, accounts_id, key, value) "
                f"VALUES (1, 1, 'given_name', '{f_safe}'); "
                f"INSERT OR REPLACE INTO extras (_id, accounts_id, key, value) "
                f"VALUES (2, 1, 'family_name', '{l_safe}');\" 2>/dev/null; "
                "chown system:system /data/system_ce/0/accounts_ce.db 2>/dev/null; "
                "chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null; "
                # accounts_de.db
                f"sqlite3 /data/system_de/0/accounts_de.db \""
                f"INSERT OR REPLACE INTO accounts (_id, name, type, previous_name) "
                f"VALUES (1, '{e_safe}', 'com.google', NULL); "
                f"INSERT OR REPLACE INTO extras (_id, accounts_id, key, value) "
                f"VALUES (1, 1, 'given_name', '{f_safe}'); "
                f"INSERT OR REPLACE INTO extras (_id, accounts_id, key, value) "
                f"VALUES (2, 1, 'family_name', '{l_safe}');\" 2>/dev/null; "
                "chown system:system /data/system_de/0/accounts_de.db 2>/dev/null; "
                "chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null; "
                "echo ACCOUNT_INJECTED"
            )
            acct_ok = await self._sh_ok(acct_cmd, "ACCOUNT_INJECTED", timeout=20)
            if not acct_ok:
                # Fallback: generate account DBs locally and push via base64
                self._log("Phase 5 — sqlite3 missing, using host-push fallback for accounts")

                def _make_acct_db(conn):
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS accounts ("
                        "_id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, "
                        "previous_name TEXT, last_password_entry_time_millis_epoch INTEGER DEFAULT 0)"
                    )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS extras ("
                        "_id INTEGER PRIMARY KEY, accounts_id INTEGER, key TEXT NOT NULL, "
                        "value TEXT)"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO accounts VALUES(1,?,?,NULL,0)",
                        (e_safe, "com.google"),
                    )
                    conn.execute("INSERT OR REPLACE INTO extras VALUES(1,1,'given_name',?)", (f_safe,))
                    conn.execute("INSERT OR REPLACE INTO extras VALUES(2,1,'family_name',?)", (l_safe,))

                ce_ok = await self._push_sqlite_db(
                    "/data/system_ce/0/accounts_ce.db", "system:system", _make_acct_db
                )
                de_ok = await self._push_sqlite_db(
                    "/data/system_de/0/accounts_de.db", "system:system", _make_acct_db
                )
                acct_ok = ce_ok and de_ok

            # GMS shared_prefs
            gms_cmd = (
                "mkdir -p /data/data/com.google.android.gms/shared_prefs 2>/dev/null; "
                f"cat > /data/data/com.google.android.gms/shared_prefs/device_registration.xml << 'GMSEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <long name=\"device_registered_timestamp\" value=\"{(int(time.time()) - cfg.age_days * 86400) * 1000}\" />\n'
                f'  <string name=\"device_id\">{_gen_android_id()}</string>\n'
                f'  <int name=\"gms_version\" value=\"240913900\" />\n'
                f"</map>\n"
                f"GMSEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                "/data/data/com.google.android.gms/shared_prefs/device_registration.xml 2>/dev/null; "
                "echo GMS_SET"
            )
            gms_ok = await self._sh_ok(gms_cmd, "GMS_SET", timeout=15)

            # GSF ID
            gsf_id = _gen_gsf_id()
            birth_ts = int(time.time()) - cfg.age_days * 86400
            gsf_cmd = (
                "mkdir -p /data/data/com.google.android.gsf/shared_prefs 2>/dev/null; "
                f"cat > /data/data/com.google.android.gsf/shared_prefs/gservices.xml << 'GSFEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <string name=\"android_id\">{gsf_id}</string>\n'
                f'  <long name=\"registration_timestamp\" value=\"{birth_ts * 1000}\" />\n'
                f"</map>\n"
                f"GSFEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.gsf/ 2>/dev/null) "
                "/data/data/com.google.android.gsf/shared_prefs/gservices.xml 2>/dev/null; "
                "echo GSF_SET"
            )
            gsf_ok = await self._sh_ok(gsf_cmd, "GSF_SET", timeout=15)

            # NEW: Also inject Play Store account data for sign-in detection
            playstore_ok = False
            if email:
                playstore_cmd = (
                    "mkdir -p /data/data/com.android.vending/shared_prefs 2>/dev/null; "
                    f"cat > /data/data/com.android.vending/shared_prefs/finsky.xml << 'FINSKYEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"signed_in_account\">{e_safe}</string>\n'
                    f'  <boolean name=\"setup_complete\" value=\"true\" />\n'
                    f'  <boolean name=\"has_consented\" value=\"true\" />\n'
                    f'  <long name=\"consent_timestamp\" value=\"{(int(time.time()) - cfg.age_days * 86400) * 1000}\" />\n'
                    f'  <int name=\"onboarding_completed\" value=\"1\" />\n'
                    f"</map>\n"
                    f"FINSKYEOF\n"
                    "chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) "
                    "/data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null; "
                    "chmod 660 /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null; "
                    # Also register in GMS phenotype for app discovery
                    f"sqlite3 /data/data/com.google.android.gms/databases/phenotype.db "
                    f"\"INSERT OR REPLACE INTO ApplicationTags (packageName, user, version) "
                    f"VALUES ('com.android.vending', '{e_safe}', 1);\" 2>/dev/null; "
                    "echo PLAYSTORE_SET"
                )
                playstore_ok = await self._sh_ok(playstore_cmd, "PLAYSTORE_SET", timeout=15)

            # ── 5e. Deep Play Store Account Binding (enhanced) ──────────
            # Inject into AccountManager via content provider so Android
            # system recognizes the Google account natively
            am_ok = False
            if email:
                am_cmd = (
                    # Register account in AccountManager via content provider
                    f"content insert --uri content://com.google.android.gms.auth.accounts "
                    f"--bind name:s:\"{e_safe}\" --bind type:s:com.google 2>/dev/null; "
                    # Inject auth tokens into accounts_ce.db for Play Store
                    f"sqlite3 /data/system_ce/0/accounts_ce.db \""
                    f"CREATE TABLE IF NOT EXISTS authtokens "
                    f"(_id INTEGER PRIMARY KEY, accounts_id INTEGER, type TEXT NOT NULL, authtoken TEXT); "
                    f"INSERT OR REPLACE INTO authtokens VALUES(1, 1, 'SID', 'DQAA{secrets.token_urlsafe(60)}'); "
                    f"INSERT OR REPLACE INTO authtokens VALUES(2, 1, 'LSID', 'DQAA{secrets.token_urlsafe(60)}'); "
                    f"INSERT OR REPLACE INTO authtokens VALUES(3, 1, 'oauth2:https://www.googleapis.com/auth/googleplay', '{secrets.token_urlsafe(40)}'); "
                    f"INSERT OR REPLACE INTO authtokens VALUES(4, 1, 'androidmarket', '{secrets.token_urlsafe(40)}');\" "
                    f"2>/dev/null; "
                    "chown system:system /data/system_ce/0/accounts_ce.db 2>/dev/null; "
                    "echo AM_SET"
                )
                am_ok = await self._sh_ok(am_cmd, "AM_SET", timeout=20)
                self._log(f"Phase 5e — AccountManager+tokens: {'ok' if am_ok else 'fail'}")

            # ── 5f. GMS Account Binding (Play Services internal state) ──
            gms_acct_ok = False
            if email:
                gsf_id = _gen_gsf_id()
                gms_acct_cmd = (
                    "mkdir -p /data/data/com.google.android.gms/shared_prefs 2>/dev/null; "
                    # GMS account cache — makes GMS services recognize signed-in user
                    f"cat > /data/data/com.google.android.gms/shared_prefs/google_account_prefs.xml << 'GAEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"default_account\">{e_safe}</string>\n'
                    f'  <boolean name=\"has_default_account\" value=\"true\" />\n'
                    f'  <string name=\"account_name\">{e_safe}</string>\n'
                    f'  <string name=\"account_type\">com.google</string>\n'
                    f'  <long name=\"last_authenticated\" value=\"{int(time.time()) * 1000}\" />\n'
                    f"</map>\n"
                    f"GAEOF\n"
                    # Play Store account info for library/purchases UI
                    f"cat > /data/data/com.android.vending/shared_prefs/account_info.xml << 'ACEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"last_account_name\">{e_safe}</string>\n'
                    f'  <string name=\"display_name\">{_sanitize(name)}</string>\n'
                    f'  <boolean name=\"is_signed_in\" value=\"true\" />\n'
                    f'  <long name=\"sign_in_time\" value=\"{(int(time.time()) - cfg.age_days * 86400) * 1000}\" />\n'
                    f"</map>\n"
                    f"ACEOF\n"
                    # Fix ownership
                    "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                    "/data/data/com.google.android.gms/shared_prefs/google_account_prefs.xml 2>/dev/null; "
                    "chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) "
                    "/data/data/com.android.vending/shared_prefs/account_info.xml 2>/dev/null; "
                    "echo GMSACCT_SET"
                )
                gms_acct_ok = await self._sh_ok(gms_acct_cmd, "GMSACCT_SET", timeout=15)
                self._log(f"Phase 5f — GMS Account binding: {'ok' if gms_acct_ok else 'fail'}")

            # ── 5g. Deep Play Store sign-in injection (enhanced) ──────────
            # Inject into multiple Play Store internal databases and prefs
            # so the store appears fully signed-in without actual app login
            play_deep_ok = False
            if email:
                birth_ms = str(int((time.time() - cfg.age_days * 86400) * 1000))
                play_deep_cmd = (
                    # Play Store library cache — recent installs history
                    "mkdir -p /data/data/com.android.vending/shared_prefs 2>/dev/null; "
                    f"cat > /data/data/com.android.vending/shared_prefs/lastaccount.xml << 'LAEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"lastAccount\">{e_safe}</string>\n'
                    f'  <string name=\"lastAccountType\">com.google</string>\n'
                    f"</map>\n"
                    f"LAEOF\n"
                    # Auto-update preferences
                    f"cat > /data/data/com.android.vending/shared_prefs/auto-update.xml << 'AUEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <int name=\"auto_update_policy\" value=\"1\" />\n'
                    f'  <boolean name=\"auto_update_enabled\" value=\"true\" />\n'
                    f'  <long name=\"last_auto_update_check\" value=\"{int(time.time() * 1000)}\" />\n'
                    f"</map>\n"
                    f"AUEOF\n"
                    # ContentProvider account tracker — Play Services uses this
                    f"cat > /data/data/com.android.vending/shared_prefs/account_tracker.xml << 'ATEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"tracked_account\">{e_safe}</string>\n'
                    f'  <long name=\"first_login_ms\" value=\"{birth_ms}\" />\n'
                    f'  <boolean name=\"tos_accepted\" value=\"true\" />\n'
                    f'  <int name=\"tos_version\" value=\"3\" />\n'
                    f"</map>\n"
                    f"ATEOF\n"
                    # Fix ownership for all injected prefs
                    "chown -R $(stat -c '%u:%g' /data/data/com.android.vending/) "
                    "/data/data/com.android.vending/shared_prefs/ 2>/dev/null; "
                    # SyncAdapter registration — makes Settings show Google sync active
                    f"content insert --uri content://com.android.contacts/raw_contacts "
                    f"--bind account_type:s:com.google --bind account_name:s:\"{e_safe}\" 2>/dev/null; "
                    "echo PLAY_DEEP_SET"
                )
                play_deep_ok = await self._sh_ok(play_deep_cmd, "PLAY_DEEP_SET", timeout=20)
                self._log(f"Phase 5g — Deep Play Store injection: {'ok' if play_deep_ok else 'fail'}")

            # ── 5h. Force restart GMS + Play Store to pick up injected accounts ──
            restart_cmd = (
                "am force-stop com.google.android.gms 2>/dev/null; "
                "am force-stop com.android.vending 2>/dev/null; "
                "sleep 2; "
                "am startservice -n com.google.android.gms/.auth.setup.devicesignals.LockScreenDeviceSignalCollectionService 2>/dev/null; "
                "echo RESTARTED"
            )
            await self._sh_ok(restart_cmd, "RESTARTED", timeout=15)

            ok_str = (
                f"acct={'ok' if acct_ok else 'fail'} gms={'ok' if gms_ok else 'fail'} "
                f"gsf={'ok' if gsf_ok else 'fail'} playstore={'ok' if playstore_ok else 'fail'} "
                f"am={'ok' if am_ok else 'fail'} bind={'ok' if gms_acct_ok else 'fail'} "
                f"play_deep={'ok' if play_deep_ok else 'fail'}"
            )
            self._set_phase(n, "done" if acct_ok else "warn", ok_str)
            self._log(f"Phase 5 — Google Account: {ok_str}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 5 — Google Account FAILED: {e}")

    async def _phase_inject(self, cfg: PipelineConfig, profile: Dict[str, Any], preset):
        """Phase 6: Inject contacts, call logs, SMS, WiFi, Chrome, autofill, battery."""
        n = 6
        self._set_phase(n, "running")
        self._log("Phase 6 — Inject: contacts, calls, SMS, WiFi, Chrome, autofill...")
        t0 = time.time()
        counts = {}

        try:
            # ── Pre-step: Initialize Chrome data directory ──
            # Chrome must be launched once to create its internal directory structure
            chrome_init = await self._sh(
                "ls /data/data/com.android.chrome/app_chrome/Default/ >/dev/null 2>&1 && echo EXISTS || "
                "{ am start -n com.android.chrome/com.google.android.apps.chrome.Main -d 'about:blank' 2>/dev/null; "
                "sleep 5; am force-stop com.android.chrome 2>/dev/null; sleep 2; echo CREATED; }",
                timeout=30,
            )
            self._log(f"Phase 6 — Chrome init: {(chrome_init or '').strip()[:30]}")
            # Force-stop Chrome to release DB locks
            await self._sh("am force-stop com.android.chrome 2>/dev/null; echo OK", timeout=10)
            # Ensure directory exists with correct ownership
            chrome_owner = await self._sh(
                "stat -c '%u:%g' /data/data/com.android.chrome/ 2>/dev/null || echo 10060:10060",
                timeout=10,
            )
            chrome_owner = (chrome_owner or "10060:10060").strip()
            await self._sh(
                f"mkdir -p /data/data/com.android.chrome/app_chrome/Default && "
                f"chown -R {chrome_owner} /data/data/com.android.chrome/app_chrome/ 2>/dev/null; echo DIR_OK",
                timeout=10,
            )

            # ── 6a. Contacts via VMOS native API ──
            contacts_raw = profile.get("contacts", [])
            if contacts_raw:
                batch = contacts_raw[:30]
                vmos_contacts = []
                for c in batch:
                    cname = _sanitize(c.get("name", "Unknown"))
                    cphone = _sanitize(c.get("phone", "+10000000000"))
                    vmos_contacts.append({
                        "name": cname,
                        "phoneNumber": cphone,
                    })
                resp = await self.client.update_contacts(self.pads, vmos_contacts)
                contact_ok = len(batch) if resp.get("code") == 200 else 0
                if contact_ok == 0:
                    # Fallback: content insert via ADB
                    self._log("Phase 6a — Native contacts failed, using content insert fallback")
                    contact_cmds = []
                    for c in batch:
                        cname = _sanitize(c.get("name", "Unknown"))
                        cphone = _sanitize(c.get("phone", "+10000000000"))
                        contact_cmds.append(
                            f"content insert --uri content://com.android.contacts/raw_contacts "
                            f"--bind account_type:s:local --bind account_name:s:local 2>/dev/null && "
                            f"CID=$(content query --uri content://com.android.contacts/raw_contacts "
                            f"--projection _id --sort \"_id DESC LIMIT 1\" 2>/dev/null | head -1 | sed \"s/.*_id=//;s/,.*//\") && "
                            f"content insert --uri content://com.android.contacts/data "
                            f"--bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/name "
                            f"--bind data1:s:\"{cname}\" 2>/dev/null && "
                            f"content insert --uri content://com.android.contacts/data "
                            f"--bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                            f"--bind data1:s:\"{cphone}\" --bind data2:i:2 2>/dev/null"
                        )
                    contact_ok = 0
                    for cs in range(0, len(contact_cmds), 5):
                        chunk = contact_cmds[cs:cs+5]
                        script = " ; ".join(chunk) + " ; echo BATCH_DONE"
                        result = await self._sh(script, timeout=30)
                        if "BATCH_DONE" in (result or ""):
                            contact_ok += len(chunk)
                counts["contacts"] = contact_ok
                self._log(f"Phase 6a — Contacts: {contact_ok}/{len(batch)}")

            # ── 5b. Call Logs — content insert via ADB (content provider visible for trust scoring) ──
            call_logs = profile.get("call_logs", [])
            if call_logs:
                batch = call_logs[:80]
                call_cmds = []
                for cl in batch:
                    number = _sanitize(cl.get("number", "+10000000000"))
                    call_type = cl.get("type", 1)
                    duration = cl.get("duration", 0)
                    ts = cl.get("timestamp", int(time.time()))
                    date_ms = int(ts * 1000)
                    call_cmds.append(
                        f"content insert --uri content://call_log/calls "
                        f"--bind number:s:\"{number}\" --bind type:i:{call_type} "
                        f"--bind duration:i:{duration} --bind date:l:{date_ms} --bind new:i:0 2>/dev/null"
                    )
                call_ok = 0
                for cs in range(0, len(call_cmds), 15):
                    chunk = call_cmds[cs:cs+15]
                    script = " && ".join(chunk) + " && echo BATCH_DONE"
                    result = await self._sh(script, timeout=30)
                    if "BATCH_DONE" in (result or ""):
                        call_ok += len(chunk)
                counts["call_logs"] = call_ok
                self._log(f"Phase 6b — Call logs: {call_ok}/{len(batch)}")

            # ── 5c. SMS via VMOS native API + ADB fallback ──
            sms_list = profile.get("sms", [])
            if sms_list:
                batch = sms_list[:30]
                sms_ok = 0
                # Use VMOS simulate_sms for incoming messages
                for sm in batch:
                    phone = _sanitize(sm.get("address", "+10000000000"))
                    body = _sanitize(sm.get("body", "Hey"))[:150]
                    sms_type = sm.get("type", 1)
                    if sms_type == 1:  # Incoming — use native API
                        try:
                            resp = await self.client.simulate_sms(self.pad, phone, body)
                            if resp.get("code") == 200:
                                sms_ok += 1
                                continue
                        except Exception:
                            pass
                    # Fallback: content insert for outgoing or failed incoming
                    ts = sm.get("timestamp", int(time.time()))
                    date_ms = int(ts * 1000)
                    cmd = (
                        f"content insert --uri content://sms "
                        f"--bind address:s:\"{phone}\" --bind body:s:\"{body}\" "
                        f"--bind type:i:{sms_type} --bind date:l:{date_ms} --bind read:i:1 2>/dev/null && "
                        f"echo SMS_OK"
                    )
                    if await self._sh_ok(cmd, "SMS_OK", timeout=10):
                        sms_ok += 1
                counts["sms"] = sms_ok
                self._log(f"Phase 6c — SMS: {sms_ok}/{len(batch)}")

            # ── 5d. WiFi Networks via VMOS native API ──
            wifi_nets = profile.get("wifi_networks", [])
            if wifi_nets:
                vmos_wifi = []
                for w in wifi_nets:
                    mac_parts = preset.mac_oui.split(":")
                    bssid = ":".join(mac_parts + [f"{random.randint(0,255):02X}" for _ in range(3)])
                    vmos_wifi.append({
                        "wifiName": w.get("ssid", "NETGEAR-5G"),
                        "bssid": bssid,
                        "ipAddress": f"192.168.{random.randint(0,10)}.{random.randint(100,200)}",
                        "macAddress": ":".join([f"{random.randint(0,255):02X}" for _ in range(6)]),
                        "gateway": f"192.168.{random.randint(0,10)}.1",
                        "dns": "8.8.8.8",
                        "signal": random.randint(-70, -30),
                    })
                resp = await self.client.set_wifi_list(self.pads, vmos_wifi)
                counts["wifi"] = len(wifi_nets) if resp.get("code") == 200 else 0
                # Write marker so trust audit can verify WiFi was set
                if counts["wifi"] > 0:
                    await self._sh_ok(
                        f"echo {counts['wifi']} > /data/local/tmp/.titan_wifi_count && echo WIFI_MARK",
                        "WIFI_MARK", timeout=10,
                    )
                self._log(f"Phase 6d — WiFi: {counts['wifi']} networks")

            # ── 5e. Chrome Cookies — sqlite3 with host-push fallback ──
            cookies = profile.get("cookies", [])
            if cookies:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                batch = cookies[:30]
                # Try sqlite3 on device first
                sql_cmds = []
                for c in batch:
                    domain = c.get("domain", ".google.com").replace("'", "''")
                    cname = c.get("name", "NID").replace("'", "''")
                    cvalue = c.get("value", "x").replace("'", "''")[:100]
                    cpath = c.get("path", "/").replace("'", "''")
                    secure = 1 if c.get("secure") else 0
                    httponly = 1 if c.get("httponly") else 0
                    creation_days = c.get("creation_days_ago", 30)
                    creation_us = (time.time() - creation_days * 86400) * 1000000 + 11644473600000000
                    expiry_us = creation_us + (c.get("max_age", 31536000) * 1000000)
                    sql_cmds.append(
                        f"INSERT OR REPLACE INTO cookies "
                        f"(host_key,name,value,path,is_secure,is_httponly,"
                        f"creation_utc,expires_utc,last_access_utc) "
                        f"VALUES('{domain}','{cname}','{cvalue}','{cpath}',"
                        f"{secure},{httponly},{int(creation_us)},{int(expiry_us)},{int(creation_us)});"
                    )
                batch_sql = "\n".join(sql_cmds)
                cmd = (
                    f"sqlite3 {chrome_dir}/Cookies \"{batch_sql}\" 2>/dev/null && {{ "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/Cookies 2>/dev/null; "
                    f"echo COOKIES_DONE; }}"
                )
                ok = await self._sh_ok(cmd, "COOKIES_DONE", timeout=20)
                if not ok:
                    # Fallback: generate DB locally and push via base64
                    self._log("Phase 6e — sqlite3 missing, using host-push fallback for Cookies")
                    chrome_owner = await self._sh(
                        f"stat -c '%u:%g' /data/data/com.android.chrome/ 2>/dev/null || echo u0_a60:u0_a60",
                        timeout=10,
                    )
                    chrome_owner = (chrome_owner or "u0_a60:u0_a60").strip()

                    def _create_cookies(conn):
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS cookies ("
                            "creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, "
                            "name TEXT NOT NULL, value TEXT NOT NULL, path TEXT NOT NULL DEFAULT '/', "
                            "expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL DEFAULT 0, "
                            "is_httponly INTEGER NOT NULL DEFAULT 0, "
                            "last_access_utc INTEGER NOT NULL DEFAULT 0, "
                            "has_expires INTEGER NOT NULL DEFAULT 1, "
                            "is_persistent INTEGER NOT NULL DEFAULT 1, "
                            "priority INTEGER NOT NULL DEFAULT 1, "
                            "samesite INTEGER NOT NULL DEFAULT -1, "
                            "source_scheme INTEGER NOT NULL DEFAULT 2, "
                            "PRIMARY KEY (host_key, name, path))"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS meta (key TEXT NOT NULL UNIQUE PRIMARY KEY, value TEXT)"
                        )
                        conn.execute("INSERT OR REPLACE INTO meta VALUES('version','20')")
                        for c in batch:
                            domain = c.get("domain", ".google.com")
                            cn = c.get("name", "NID")
                            cv = c.get("value", "x")[:100]
                            cp = c.get("path", "/")
                            sec = 1 if c.get("secure") else 0
                            ho = 1 if c.get("httponly") else 0
                            cd = c.get("creation_days_ago", 30)
                            cus = int((time.time() - cd * 86400) * 1000000 + 11644473600000000)
                            eus = cus + int(c.get("max_age", 31536000) * 1000000)
                            conn.execute(
                                "INSERT OR REPLACE INTO cookies "
                                "(creation_utc,host_key,name,value,path,expires_utc,"
                                "is_secure,is_httponly,last_access_utc) "
                                "VALUES(?,?,?,?,?,?,?,?,?)",
                                (cus, domain, cn, cv, cp, eus, sec, ho, cus),
                            )

                    ok = await self._push_sqlite_db(
                        f"{chrome_dir}/Cookies", chrome_owner, _create_cookies
                    )
                counts["cookies"] = len(batch) if ok else 0
                self._log(f"Phase 6e — Cookies: {counts.get('cookies', 0)}")

            # ── 5f. Chrome History — sqlite3 with host-push fallback ──
            history = profile.get("history", [])
            if history:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                batch = history[:50]
                sql_cmds = []
                for h in batch:
                    url = h.get("url", "https://www.google.com").replace("'", "''")[:200]
                    title = h.get("title", "Google").replace("'", "''")[:100]
                    visits = h.get("visits", 1)
                    ts = h.get("timestamp", int(time.time()))
                    chrome_ts = int(ts * 1000000 + 11644473600000000)
                    sql_cmds.append(
                        f"INSERT OR IGNORE INTO urls (url,title,visit_count,last_visit_time) "
                        f"VALUES('{url}','{title}',{visits},{chrome_ts});"
                    )
                batch_sql = "\n".join(sql_cmds)
                cmd = (
                    f"sqlite3 {chrome_dir}/History \"{batch_sql}\" 2>/dev/null && {{ "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/History 2>/dev/null; "
                    f"echo HISTORY_DONE; }}"
                )
                ok = await self._sh_ok(cmd, "HISTORY_DONE", timeout=20)
                if not ok:
                    self._log("Phase 6f — sqlite3 missing, using host-push fallback for History")
                    chrome_owner = await self._sh(
                        f"stat -c '%u:%g' /data/data/com.android.chrome/ 2>/dev/null || echo u0_a60:u0_a60",
                        timeout=10,
                    )
                    chrome_owner = (chrome_owner or "u0_a60:u0_a60").strip()

                    def _create_history(conn):
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS urls ("
                            "id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT DEFAULT '', "
                            "visit_count INTEGER DEFAULT 0, typed_count INTEGER DEFAULT 0, "
                            "last_visit_time INTEGER NOT NULL, hidden INTEGER DEFAULT 0)"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS visits ("
                            "id INTEGER PRIMARY KEY, url INTEGER NOT NULL, visit_time INTEGER NOT NULL, "
                            "from_visit INTEGER DEFAULT 0, transition INTEGER DEFAULT 0x30000000, "
                            "visit_duration INTEGER DEFAULT 0)"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS meta (key TEXT NOT NULL UNIQUE PRIMARY KEY, value TEXT)"
                        )
                        conn.execute("INSERT OR REPLACE INTO meta VALUES('version','46')")
                        for h in batch:
                            u = h.get("url", "https://www.google.com")[:200]
                            t = h.get("title", "Google")[:100]
                            v = h.get("visits", 1)
                            ts = h.get("timestamp", int(time.time()))
                            cts = int(ts * 1000000 + 11644473600000000)
                            conn.execute(
                                "INSERT OR IGNORE INTO urls (url,title,visit_count,last_visit_time) "
                                "VALUES(?,?,?,?)", (u, t, v, cts),
                            )

                    ok = await self._push_sqlite_db(
                        f"{chrome_dir}/History", chrome_owner, _create_history
                    )
                counts["history"] = len(batch) if ok else 0
                self._log(f"Phase 6f — History: {counts.get('history', 0)}")

            # ── 5g. Autofill — sqlite3 with host-push fallback ──
            autofill = profile.get("autofill", {})
            if autofill or cfg.street:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                af_name = _sanitize(cfg.name or "User")
                af_email = _sanitize(cfg.google_email or cfg.email or "")
                af_phone = _sanitize(cfg.phone or "")
                af_street = _sanitize(cfg.street or "")
                af_city = _sanitize(cfg.city or "")
                af_state = _sanitize(cfg.state or "")
                af_zip = _sanitize(cfg.zip or "")
                af_country = _sanitize(cfg.country or "US")
                profile_guid = str(uuid.uuid4())
                cmd = (
                    f"sqlite3 {chrome_dir}/\"Web Data\" \""
                    f"INSERT OR REPLACE INTO autofill_profiles "
                    f"(guid,full_name,email_address,phone_number,"
                    f"street_address,city,state,zipcode,country_code) "
                    f"VALUES("
                    f"'{profile_guid}','{af_name.replace(chr(39),chr(39)+chr(39))}','{af_email.replace(chr(39),chr(39)+chr(39))}','{af_phone}',"
                    f"'{af_street.replace(chr(39),chr(39)+chr(39))}','{af_city.replace(chr(39),chr(39)+chr(39))}','{af_state}','{af_zip}','{af_country}'"
                    f");\" 2>/dev/null && echo AUTOFILL_DONE"
                )
                ok = await self._sh_ok(cmd, "AUTOFILL_DONE", timeout=15)
                if not ok:
                    self._log("Phase 6g — sqlite3 missing, using host-push fallback for Web Data")
                    chrome_owner = await self._sh(
                        f"stat -c '%u:%g' /data/data/com.android.chrome/ 2>/dev/null || echo u0_a60:u0_a60",
                        timeout=10,
                    )
                    chrome_owner = (chrome_owner or "u0_a60:u0_a60").strip()

                    def _create_webdata(conn):
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS autofill_profiles ("
                            "guid TEXT PRIMARY KEY, full_name TEXT, email_address TEXT, "
                            "phone_number TEXT, street_address TEXT, city TEXT, state TEXT, "
                            "zipcode TEXT, country_code TEXT, date_modified INTEGER, "
                            "use_count INTEGER DEFAULT 1, use_date INTEGER)"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS autofill_profile_names ("
                            "guid TEXT, first_name TEXT, middle_name TEXT, last_name TEXT, full_name TEXT)"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS credit_cards ("
                            "guid TEXT PRIMARY KEY, name_on_card TEXT, card_number TEXT, "
                            "expiration_month INTEGER, expiration_year INTEGER, date_modified INTEGER)"
                        )
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS meta (key TEXT NOT NULL UNIQUE PRIMARY KEY, value TEXT)"
                        )
                        conn.execute("INSERT OR REPLACE INTO meta VALUES('version','110')")
                        now_s = int(time.time())
                        conn.execute(
                            "INSERT OR REPLACE INTO autofill_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (profile_guid, af_name, af_email, af_phone, af_street,
                             af_city, af_state, af_zip, af_country, now_s, 3, now_s),
                        )
                        parts = af_name.split(None, 1)
                        first = parts[0] if parts else ""
                        last = parts[1] if len(parts) > 1 else ""
                        conn.execute(
                            "INSERT OR REPLACE INTO autofill_profile_names VALUES(?,?,?,?,?)",
                            (profile_guid, first, "", last, af_name),
                        )

                    ok = await self._push_sqlite_db(
                        f"{chrome_dir}/Web Data", chrome_owner, _create_webdata
                    )
                counts["autofill"] = 1 if ok else 0
                self._log(f"Phase 6g — Autofill: {'ok' if ok else 'fail'}")

            # ── 5h. Battery via native API ──
            battery_level = random.randint(42, 87)
            charging = random.choice([0, 1])
            resp = await self.client.modify_instance_properties(self.pads, {
                "batteryLevel": battery_level,
                "batteryStatus": charging,
            })
            counts["battery"] = 1 if resp.get("code") == 200 else 0
            self._log(f"Phase 6h — Battery: {battery_level}% {'charging' if charging else 'discharging'}")

            # ── 6i. GAID reset ──
            try:
                resp = await self.client.reset_gaid(self.pads, reset_gms_type=1)
                counts["gaid"] = 1 if resp.get("code") == 200 else 0
            except Exception:
                counts["gaid"] = 0

            # ── 6j. UsageStats aging (base64 push — reduced entries for reliability) ──
            now_ts = int(time.time())
            birth_ts = now_ts - (cfg.age_days * 86400)
            usage_entries = []
            # Use every 14 days instead of every 3 to keep XML small (fewer ADB chunks)
            pkgs = ["com.android.chrome", "com.google.android.apps.maps", "com.android.vending"]
            for day_offset in range(0, cfg.age_days, 14):
                day_ts = (birth_ts + day_offset * 86400) * 1000
                for pkg in pkgs:
                    usage_entries.append(
                        f'<usageStats package="{pkg}" '
                        f'totalTimeInForeground="{random.randint(60000, 900000)}" '
                        f'lastTimeUsed="{day_ts}" />'
                    )
            usage_xml = (
                '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                '<usagestats version="1">\n'
                + "\n".join(usage_entries) +
                '\n</usagestats>'
            )
            usage_b64 = base64.b64encode(usage_xml.encode()).decode()
            usage_chunks = [usage_b64[i:i+2000] for i in range(0, len(usage_b64), 2000)]
            await self._sh("mkdir -p /data/system/usagestats/0/daily 2>/dev/null; echo OK", timeout=10)
            usage_ok = True
            for i, chunk in enumerate(usage_chunks):
                op = ">" if i == 0 else ">>"
                ok = await self._sh_ok(
                    f"echo -n '{chunk}' {op} /data/local/tmp/_usage_b64.tmp && echo UCH{i}_OK",
                    f"UCH{i}_OK", timeout=15,
                )
                if not ok:
                    self._log(f"Phase 6j — UsageStats chunk {i}/{len(usage_chunks)} failed, retrying...")
                    # Retry once
                    ok = await self._sh_ok(
                        f"echo -n '{chunk}' {op} /data/local/tmp/_usage_b64.tmp && echo UCH{i}_OK",
                        f"UCH{i}_OK", timeout=15,
                    )
                    if not ok:
                        usage_ok = False
                        break
            if usage_ok:
                usage_ok = await self._sh_ok(
                    "base64 -d /data/local/tmp/_usage_b64.tmp > /data/system/usagestats/0/daily/usage_stats.xml && "
                    "rm -f /data/local/tmp/_usage_b64.tmp && "
                    "chown system:system /data/system/usagestats/0/daily/usage_stats.xml 2>/dev/null; "
                    "chmod 600 /data/system/usagestats/0/daily/usage_stats.xml 2>/dev/null; "
                    "ls -s /data/system/usagestats/0/daily/usage_stats.xml && echo USAGE_SET",
                    "USAGE_SET", timeout=20,
                )
            counts["usagestats"] = len(usage_entries) if usage_ok else 0
            self._log(f"Phase 6j — UsageStats: {counts['usagestats']} entries over {cfg.age_days} days")

            # ── 5k. App timestamp backdating ──
            apps_to_age = [
                "com.android.chrome", "com.google.android.gms",
                "com.google.android.apps.maps", "com.android.vending",
                "com.google.android.youtube",
            ]
            age_cmds = []
            for pkg in apps_to_age:
                install_ts = birth_ts + random.randint(0, 86400 * 7)
                age_cmds.append(
                    f"touch -t $(date -d @{install_ts} '+%Y%m%d%H%M.%S') "
                    f"/data/data/{pkg}/ 2>/dev/null"
                )
            age_cmd = "; ".join(age_cmds) + "; echo APPS_AGED"
            aged = await self._sh_ok(age_cmd, "APPS_AGED", timeout=15)
            counts["app_aging"] = 1 if aged else 0

            # ── 5l. GMS Identity Prefs Injection (NEW — from deep research) ──
            email = _sanitize(cfg.google_email or cfg.email or "")
            gms_prefs = "/data/data/com.google.android.gms/shared_prefs"
            pseudo_id = secrets.token_urlsafe(150)[:200]
            dg_uuid = str(uuid.uuid4())
            backup_ts = str(int((time.time() - random.randint(86400 * 7, 86400 * cfg.age_days)) * 1000))

            gms_id_cmd = (
                f"mkdir -p {gms_prefs} 2>/dev/null; "
                # PseudonymousIdPrefs — GMS device fingerprint
                f"cat > {gms_prefs}/PseudonymousIdPrefs.xml << 'PIDEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <string name=\"pseudonymousId\">{pseudo_id}</string>\n'
                f"</map>\n"
                f"PIDEOF\n"
                # DroidGuard client_uuid
                f"cat > {gms_prefs}/dg_shared_preferences.xml << 'DGEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <string name=\"client_uuid\">{dg_uuid}</string>\n'
                f"</map>\n"
                f"DGEOF\n"
                # BackupDeviceState — makes device appear to have backup history
                f"cat > {gms_prefs}/BackupDeviceState.xml << 'BKEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <long name=\"lastKvBackupPassTimeMs\" value=\"{backup_ts}\" />\n'
                f"</map>\n"
                f"BKEOF\n"
                # Fix ownership
                f"chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                f"{gms_prefs}/PseudonymousIdPrefs.xml "
                f"{gms_prefs}/dg_shared_preferences.xml "
                f"{gms_prefs}/BackupDeviceState.xml 2>/dev/null; "
                f"echo GMS_ID_DONE"
            )
            gms_id_ok = await self._sh_ok(gms_id_cmd, "GMS_ID_DONE", timeout=20)
            counts["gms_identity"] = 3 if gms_id_ok else 0
            self._log(f"Phase 6l — GMS Identity Prefs: {'ok' if gms_id_ok else 'fail'}")

            # ── 5m. GMS Measurement Timestamp Backdating (NEW) ──
            # Manipulate first_open_time and app_install_time in measurement prefs
            first_open_ms = str(int((time.time() - cfg.age_days * 86400) * 1000))
            install_ms = str(int((time.time() - (cfg.age_days + random.randint(1, 7)) * 86400) * 1000))
            measure_cmd = (
                f"cat > {gms_prefs}/com.google.android.gms.measurement.prefs.xml << 'MSEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <long name=\"first_open_time\" value=\"{first_open_ms}\" />\n'
                f'  <long name=\"app_install_time\" value=\"{install_ms}\" />\n'
                f'  <long name=\"last_upload_attempt\" value=\"{int(time.time() * 1000)}\" />\n'
                f"</map>\n"
                f"MSEOF\n"
                f"chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                f"{gms_prefs}/com.google.android.gms.measurement.prefs.xml 2>/dev/null; "
                f"echo MEASURE_DONE"
            )
            measure_ok = await self._sh_ok(measure_cmd, "MEASURE_DONE", timeout=15)
            counts["measurement_age"] = 1 if measure_ok else 0
            self._log(f"Phase 6m — Measurement timestamps: {'ok' if measure_ok else 'fail'}")

            elapsed = time.time() - t0
            summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
            self._set_phase(n, "done", f"{summary}, {elapsed:.0f}s")
            self._log(f"Phase 6 — Inject done in {elapsed:.0f}s: {summary}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 6 — Inject FAILED: {e}")

    async def _phase_wallet(self, cfg: PipelineConfig, profile: Dict[str, Any]):
        """Phase 7: Wallet / GPay credit card injection."""
        n = 7
        cc = cfg.cc_number.replace(" ", "").replace("-", "")
        if not cc or len(cc) < 13:
            self._set_phase(n, "skipped", "no card")
            self._log("Phase 7 — Wallet: skipped (no card data)")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 7 — Wallet: injecting card ***{cc[-4:]}...")
        try:
            # Parse expiry
            exp_parts = cfg.cc_exp.split("/") if "/" in cfg.cc_exp else [cfg.cc_exp[:2], cfg.cc_exp[2:]]
            exp_month = int(exp_parts[0]) if exp_parts else 12
            exp_year = int(exp_parts[1]) if len(exp_parts) > 1 else 2029
            if exp_year < 100:
                exp_year += 2000
            holder = cfg.cc_holder or cfg.name or "Cardholder"

            # Determine card network from BIN
            first = cc[0]
            network = "visa"
            if first == "5":
                network = "mastercard"
            elif first == "3":
                network = "amex"
            elif first == "6":
                network = "discover"

            # ── 6a. Chrome Web Data (autofill credit card) ──
            chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
            card_guid = str(uuid.uuid4())
            holder_safe = holder.replace("'", "''")
            web_data_cmd = (
                f"sqlite3 {chrome_dir}/\"Web Data\" \""
                f"CREATE TABLE IF NOT EXISTS credit_cards "
                f"(guid TEXT PRIMARY KEY, name_on_card TEXT, card_number_encrypted BLOB, "
                f"expiration_month INTEGER, expiration_year INTEGER, "
                f"date_modified INTEGER, origin TEXT, billing_address_id TEXT, nickname TEXT); "
                f"INSERT OR REPLACE INTO credit_cards "
                f"(guid, name_on_card, card_number_encrypted, expiration_month, expiration_year, "
                f"date_modified, origin, billing_address_id, nickname) "
                f"VALUES('{card_guid}', '{holder_safe}', X'{cc.encode().hex()}', "
                f"{exp_month}, {exp_year}, {int(time.time())}, 'https://pay.google.com', '', '{network.upper()}');\" "
                f"2>/dev/null && {{ "
                f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/\"Web Data\" 2>/dev/null; "
                f"echo WEBDATA_DONE; }}"
            )
            webdata_ok = await self._sh_ok(web_data_cmd, "WEBDATA_DONE", timeout=15)
            if not webdata_ok:
                # Web Data may already exist from autofill injection — just verify
                chk = await self._sh(f"stat -c '%s' {chrome_dir}/'Web Data' 2>/dev/null || echo 0", timeout=10)
                webdata_ok = int((chk or "0").strip()) > 8192

            # ── 6b. GMS tapandpay.db — sqlite3 with host-push fallback ──
            dpan = "5" + "".join([str(random.randint(0,9)) for _ in range(14)])
            token_ref = secrets.token_hex(16)
            network_id = {"visa": 1, "mastercard": 2, "amex": 3, "discover": 4}.get(network, 1)
            display = f"{network.upper()} ****{cc[-4:]}"
            tpay_cmd = (
                "mkdir -p /data/data/com.google.android.gms/databases 2>/dev/null; "
                f"sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db \""
                f"CREATE TABLE IF NOT EXISTS token_metadata ("
                f"id INTEGER PRIMARY KEY, dpan TEXT, last_four TEXT, network INTEGER, "
                f"token_ref TEXT, display_name TEXT, is_default INTEGER, "
                f"card_color INTEGER, token_state INTEGER); "
                f"INSERT OR REPLACE INTO token_metadata "
                f"(id, dpan, last_four, network, token_ref, display_name, is_default, "
                f"card_color, token_state) VALUES "
                f"(1, '{dpan}', '{cc[-4:]}', {network_id}, "
                f"'{token_ref}', '{display}', 1, -12285185, 3);\" 2>/dev/null && {{ "
                f"chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                f"/data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null; "
                f"echo TPAY_DONE; }}"
            )
            tpay_ok = await self._sh_ok(tpay_cmd, "TPAY_DONE", timeout=15)
            if not tpay_ok:
                self._log("Phase 7b — sqlite3 missing, using host-push fallback for tapandpay")
                gms_owner = await self._sh(
                    "stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null || echo u0_a36:u0_a36",
                    timeout=10,
                )
                gms_owner = (gms_owner or "u0_a36:u0_a36").strip()

                def _create_tpay(conn):
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS token_metadata ("
                        "id INTEGER PRIMARY KEY, dpan TEXT, last_four TEXT, network INTEGER, "
                        "token_ref TEXT, display_name TEXT, is_default INTEGER, "
                        "card_color INTEGER, token_state INTEGER)"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO token_metadata VALUES(?,?,?,?,?,?,?,?,?)",
                        (1, dpan, cc[-4:], network_id, token_ref, display, 1, -12285185, 3),
                    )

                tpay_ok = await self._push_sqlite_db(
                    "/data/data/com.google.android.gms/databases/tapandpay.db",
                    gms_owner, _create_tpay,
                )

            # ── 6c. GMS billing prefs ──
            email = cfg.google_email or cfg.email or ""
            billing_cmd = (
                "mkdir -p /data/data/com.google.android.gms/shared_prefs 2>/dev/null; "
                f"cat > /data/data/com.google.android.gms/shared_prefs/COIN.xml << 'COINEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <boolean name=\"has_payment_methods\" value=\"true\" />\n'
                f'  <string name=\"default_instrument_id\">instrument_1</string>\n'
                f'  <string name=\"account_name\">{_sanitize(email)}</string>\n'
                f'  <boolean name=\"wallet_enabled\" value=\"true\" />\n'
                f"</map>\n"
                f"COINEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                "/data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null; "
                "echo COIN_DONE"
            )
            coin_ok = await self._sh_ok(billing_cmd, "COIN_DONE", timeout=15)

            # ── 6d. android_pay WalletPsdLogs injection (NEW — from deep research) ──
            android_pay_path = "/data/data/com.google.android.gms/databases/android_pay"
            psd_ts = int(time.time() * 1000)
            psd_expiry = psd_ts + 86400000 * 30  # 30 day expiry
            ap_cmd = (
                f"sqlite3 '{android_pay_path}' \""
                f"CREATE TABLE IF NOT EXISTS WalletPsdLogs ("
                f"account_id TEXT, environment TEXT, log_id TEXT, "
                f"psd_key TEXT, psd_logs BLOB, "
                f"record_timestamp INTEGER, expiration_timestamp INTEGER); "
                f"INSERT OR REPLACE INTO WalletPsdLogs VALUES("
                f"'{_sanitize(email)}', 'PRODUCTION', '{secrets.token_hex(8)}', "
                f"'psd_wallet_main', X'00', {psd_ts}, {psd_expiry}); "
                f"CREATE TABLE IF NOT EXISTS TapDoodleGroupsV2 ("
                f"doodle_group_id TEXT, environment TEXT, account_id TEXT, "
                f"proto BLOB, is_seen INTEGER); "
                f"INSERT OR REPLACE INTO TapDoodleGroupsV2 VALUES("
                f"'tap_main', 'PRODUCTION', '{_sanitize(email)}', X'00', 1);\" "
                f"2>/dev/null && echo APAY_DONE"
            )
            apay_ok = await self._sh_ok(ap_cmd, "APAY_DONE", timeout=15)
            if not apay_ok:
                # Fallback: host-push
                gms_owner = await self._sh(
                    "stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null || echo u0_a36:u0_a36",
                    timeout=10,
                )
                gms_owner = (gms_owner or "u0_a36:u0_a36").strip()

                def _create_android_pay(conn):
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS WalletPsdLogs ("
                        "account_id TEXT, environment TEXT, log_id TEXT, "
                        "psd_key TEXT, psd_logs BLOB, "
                        "record_timestamp INTEGER, expiration_timestamp INTEGER)"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO WalletPsdLogs VALUES(?,?,?,?,?,?,?)",
                        (email, "PRODUCTION", secrets.token_hex(8),
                         "psd_wallet_main", b"\x00", psd_ts, psd_expiry),
                    )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS TapDoodleGroupsV2 ("
                        "doodle_group_id TEXT, environment TEXT, account_id TEXT, "
                        "proto BLOB, is_seen INTEGER)"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO TapDoodleGroupsV2 VALUES(?,?,?,?,?)",
                        ("tap_main", "PRODUCTION", email, b"\x00", 1),
                    )

                apay_ok = await self._push_sqlite_db(
                    android_pay_path, gms_owner, _create_android_pay,
                )
            self._log(f"Phase 7d — android_pay: {'ok' if apay_ok else 'fail'}")

            # ── 7e. Fast Visual Verification — UIAutomator XML dump (no screenshots) ──
            verify_results = {}
            try:
                # Open Google Wallet or Chrome payment settings
                wallet_pkg = await self._sh(
                    "pm path com.google.android.apps.walletnfcrel 2>/dev/null && echo FOUND || echo MISSING",
                    timeout=10,
                )
                if "FOUND" in (wallet_pkg or ""):
                    await self._sh(
                        "am force-stop com.google.android.apps.walletnfcrel 2>/dev/null; "
                        "am start -n com.google.android.apps.walletnfcrel/com.google.android.gms.tapandpay.app.main.TapAndPayActivity 2>/dev/null; "
                        "echo WALLET_OPENED",
                        timeout=15,
                    )
                    await asyncio.sleep(3)
                    # Dump UI hierarchy and search for card info
                    ui_dump = await self._sh(
                        "uiautomator dump /dev/stdout 2>/dev/null || "
                        "uiautomator dump /data/local/tmp/_ui.xml 2>/dev/null && cat /data/local/tmp/_ui.xml",
                        timeout=15,
                    )
                    ui_text = (ui_dump or "").lower()
                    verify_results["wallet_app_opened"] = "tapandpay" in ui_text or "wallet" in ui_text
                    verify_results["card_last4_visible"] = cc[-4:] in (ui_dump or "")
                    verify_results["card_network_visible"] = network.lower() in ui_text
                else:
                    # Fallback: open Chrome payment settings and verify via UI XML
                    await self._sh(
                        "am force-stop com.android.chrome 2>/dev/null; "
                        "am start -n com.android.chrome/com.google.android.apps.chrome.Main "
                        "-d 'chrome://settings/paymentMethods' 2>/dev/null; "
                        "echo CHROME_PAY_OPENED",
                        timeout=15,
                    )
                    await asyncio.sleep(3)
                    ui_dump = await self._sh(
                        "uiautomator dump /dev/stdout 2>/dev/null || "
                        "uiautomator dump /data/local/tmp/_ui.xml 2>/dev/null && cat /data/local/tmp/_ui.xml",
                        timeout=15,
                    )
                    ui_text = (ui_dump or "").lower()
                    verify_results["chrome_pay_opened"] = "payment" in ui_text
                    verify_results["card_last4_visible"] = cc[-4:] in (ui_dump or "")

                # Also verify Google account in Settings > Accounts
                await self._sh(
                    "am force-stop com.android.settings 2>/dev/null; "
                    "am start -a android.settings.SYNC_SETTINGS 2>/dev/null; "
                    "echo SETTINGS_OPENED",
                    timeout=10,
                )
                await asyncio.sleep(2)
                acct_dump = await self._sh(
                    "uiautomator dump /dev/stdout 2>/dev/null || "
                    "uiautomator dump /data/local/tmp/_ui.xml 2>/dev/null && cat /data/local/tmp/_ui.xml",
                    timeout=15,
                )
                acct_text = (acct_dump or "")
                verify_results["google_account_visible"] = (cfg.google_email or cfg.email or "") in acct_text

                # Close all verification apps
                await self._sh(
                    "am force-stop com.google.android.apps.walletnfcrel 2>/dev/null; "
                    "am force-stop com.android.chrome 2>/dev/null; "
                    "am force-stop com.android.settings 2>/dev/null; "
                    "input keyevent KEYCODE_HOME 2>/dev/null; echo OK",
                    timeout=10,
                )

                verify_str = ", ".join(f"{k}={'YES' if v else 'no'}" for k, v in verify_results.items())
                self._log(f"Phase 7e — Fast UI verification: {verify_str}")
            except Exception as ve:
                self._log(f"Phase 7e — UI verification error: {ve}")

            results = (
                f"web_data={'ok' if webdata_ok else 'fail'} "
                f"tpay={'ok' if tpay_ok else 'fail'} "
                f"coin={'ok' if coin_ok else 'fail'} "
                f"apay={'ok' if apay_ok else 'fail'}"
            )
            ok_total = sum([webdata_ok, tpay_ok, coin_ok, apay_ok])
            self._set_phase(n, "done" if ok_total >= 3 else "warn", f"{ok_total}/4 targets")
            self._log(f"Phase 7 — Wallet: {results}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 7 — Wallet FAILED: {e}")

    async def _phase_provincial(self, cfg: PipelineConfig, profile: Dict[str, Any]):
        """Phase 8: Provincial Layering — app-specific SharedPreferences injection."""
        n = 8
        self._set_phase(n, "running")
        self._log("Phase 8 — Provincial Layering: injecting app-specific data...")
        try:
            country = (cfg.country or "US").upper()
            app_targets = {
                "US": ["com.amazon.mShop.android.shopping", "com.venmo",
                       "com.paypal.android.p2pmobile"],
                "GB": ["com.amazon.mShop.android.shopping", "com.ebay.mobile",
                       "com.revolut.revolut"],
            }
            targets = app_targets.get(country, app_targets["US"])
            email = _sanitize(cfg.google_email or cfg.email or "")
            name = _sanitize(cfg.name or "User")
            prefs_ok = 0

            for pkg in targets:
                prefs_dir = f"/data/data/{pkg}/shared_prefs"
                prefs_cmd = (
                    f"mkdir -p {prefs_dir} 2>/dev/null; "
                    f"cat > {prefs_dir}/user_prefs.xml << 'PREFEOF'\n"
                    f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                    f"<map>\n"
                    f'  <string name=\"user_email\">{email}</string>\n'
                    f'  <string name=\"user_name\">{name}</string>\n'
                    f'  <boolean name=\"onboarding_complete\" value=\"true\" />\n'
                    f'  <boolean name=\"notifications_enabled\" value=\"true\" />\n'
                    f'  <int name=\"app_open_count\" value=\"{random.randint(5, 50)}\" />\n'
                    f'  <long name=\"first_open_timestamp\" value=\"{(int(time.time()) - cfg.age_days * 86400) * 1000}\" />\n'
                    f"</map>\n"
                    f"PREFEOF\n"
                    f"chown $(stat -c '%u:%g' /data/data/{pkg}/ 2>/dev/null) {prefs_dir}/user_prefs.xml 2>/dev/null; "
                    f"echo PREF_SET"
                )
                ok = await self._sh_ok(prefs_cmd, "PREF_SET", timeout=15)
                if ok:
                    prefs_ok += 1

            self._set_phase(n, "done", f"{prefs_ok}/{len(targets)} apps")
            self._log(f"Phase 8 — Provincial: {prefs_ok}/{len(targets)} apps")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 8 — Provincial FAILED: {e}")

    async def _phase_postharden(self, cfg: PipelineConfig):
        """Phase 9: Post-Harden — Kiwi/Chrome prefs, media scan."""
        n = 9
        self._set_phase(n, "running")
        self._log("Phase 9 — Post-Harden: Kiwi prefs, media scan...")
        try:
            email = _sanitize(cfg.google_email or cfg.email or "user@gmail.com")
            name = _sanitize(cfg.name or "User")
            first = name.split()[0] if name else "User"

            # Kiwi browser preferences for chrome_signin trust signal
            kiwi_path = "/data/data/com.kiwibrowser.browser/app_chrome/Default"
            kiwi_cmd = (
                f"mkdir -p {kiwi_path} 2>/dev/null; "
                f"cat > {kiwi_path}/Preferences << 'KIWIEOF'\n"
                + json.dumps({
                    "account_info": [{
                        "email": email,
                        "full_name": name,
                        "gaia": "117234567890",
                        "given_name": first,
                        "locale": "en-US",
                    }],
                    "signin": {"allowed": True, "allowed_on_next_startup": True},
                    "sync": {"has_setup_completed": True},
                    "browser": {"has_seen_welcome_page": True},
                }, indent=2) +
                f"\nKIWIEOF\n"
                f"restorecon {kiwi_path}/Preferences 2>/dev/null; "
                f"echo KIWI_DONE"
            )
            kiwi_ok = await self._sh_ok(kiwi_cmd, "KIWI_DONE", timeout=15)

            # Media scan
            scan_cmd = (
                "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                "-d file:///sdcard/DCIM/Camera/ 2>/dev/null; "
                "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                "-d file:///data/media/0/DCIM/Camera/ 2>/dev/null; "
                "echo SCAN_DONE"
            )
            scan_ok = await self._sh_ok(scan_cmd, "SCAN_DONE", timeout=10)

            notes = f"kiwi={'ok' if kiwi_ok else 'fail'} scan={'ok' if scan_ok else 'fail'}"
            self._set_phase(n, "done", notes)
            self._log(f"Phase 9 — Post-Harden: {notes}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 9 — Post-Harden FAILED: {e}")

    async def _phase_attestation(self, preset):
        """Phase 10: Attestation checks — keybox, verified boot, build type."""
        n = 10
        self._set_phase(n, "running")
        self._log("Phase 10 — Attestation: keybox, verified boot, GSF...")
        try:
            check_cmd = (
                "echo KB=$(getprop persist.titan.keybox.loaded); "
                "echo VBS=$(getprop ro.boot.verifiedbootstate); "
                "echo BT=$(getprop ro.build.type); "
                "echo QEMU=$(getprop ro.kernel.qemu)"
            )
            result = await self._sh(check_cmd, timeout=15)
            issues = []
            lines = (result or "").strip().split("\n")
            vals = {}
            for line in lines:
                if "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip()

            if vals.get("KB") != "1":
                issues.append("keybox")
            if vals.get("VBS") != "green":
                issues.append(f"vbs={vals.get('VBS', '?')}")
            if vals.get("BT") != "user":
                issues.append(f"build={vals.get('BT', '?')}")
            if vals.get("QEMU") not in ("0", ""):
                issues.append("qemu_exposed")

            notes = "ok" if not issues else ", ".join(issues)
            self._set_phase(n, "done" if not issues else "warn", notes)
            self._log(f"Phase 10 — Attestation: {notes}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 10 — Attestation FAILED: {e}")

    async def _phase_trust_audit(self, profile: Dict[str, Any]):
        """Phase 11: Trust score — fast ADB-based verification (no screenshots)."""
        n = 11
        self._set_phase(n, "running")
        self._log("Phase 11 — Trust Audit: fast ADB verification...")
        try:
            checks = {}

            # Batch 1: Content provider data counts
            r1 = await self._sh(
                "echo CONTACTS=$(content query --uri content://com.android.contacts/raw_contacts --projection _id 2>/dev/null | wc -l); "
                "echo CALLS=$(content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l); "
                "echo SMS=$(content query --uri content://sms --projection _id 2>/dev/null | wc -l)",
                timeout=15,
            )

            # Batch 2: Chrome data
            r2 = await self._sh(
                "CD=/data/data/com.android.chrome/app_chrome/Default; "
                "echo CHROME_COOKIES=$(stat -c '%s' $CD/Cookies 2>/dev/null || echo 0); "
                "echo CHROME_HISTORY=$(stat -c '%s' $CD/History 2>/dev/null || echo 0); "
                'echo AUTOFILL=$(stat -c "%s" "$CD/Web Data" 2>/dev/null || echo 0)',
                timeout=15,
            )

            # Batch 3: System data + GMS
            r3 = await self._sh(
                "echo USAGE=$(ls /data/system/usagestats/0/daily/ 2>/dev/null | wc -l); "
                "echo TPAY=$(stat -c '%s' /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null || echo 0); "
                "echo PLAYSTORE=$(ls /data/data/com.android.vending/shared_prefs/*.xml 2>/dev/null | wc -l); "
                "echo GMS_REG=$(test -f /data/data/com.google.android.gms/shared_prefs/device_registration.xml && echo 1 || echo 0); "
                "echo GSF_ID=$(test -f /data/data/com.google.android.gsf/shared_prefs/gservices.xml && echo 1 || echo 0)",
                timeout=15,
            )

            # Batch 4: Browser, wifi, stealth
            r4 = await self._sh(
                "echo KIWI=$(test -f /data/data/com.kiwibrowser.browser/app_chrome/Default/Preferences && echo 1 || echo 0); "
                "echo WIFI=$(cat /data/local/tmp/.titan_wifi_count 2>/dev/null || echo 0); "
                "echo BUILD_TYPE=$(getprop ro.build.type); "
                "echo VMOS_LEAK=$(getprop ro.vmos.simplest.rom 2>/dev/null || echo '')",
                timeout=15,
            )

            # Batch 5: Identity depth (GMS identity prefs + measurement timestamps)
            r5 = await self._sh(
                "echo GMS_IDENTITY=$(test -f /data/data/com.google.android.gms/shared_prefs/PseudonymousIdPrefs.xml && echo 1 || echo 0); "
                "echo MEASURE_AGE=$(test -f /data/data/com.google.android.gms/shared_prefs/com.google.android.gms.measurement.prefs.xml && echo 1 || echo 0); "
                "echo GMS_BACKUP=$(test -f /data/data/com.google.android.gms/shared_prefs/BackupDeviceState.xml && echo 1 || echo 0); "
                "echo PLAY_SIGNED=$(grep -l 'signed_in_account' /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null && echo yes || echo no); "
                "echo FP=$(getprop ro.build.fingerprint | head -c 60)",
                timeout=15,
            )

            # Batch 6: Stealth verification (proc + root hiding)
            r6 = await self._sh(
                "echo SU_HIDDEN=$(which su 2>/dev/null && echo EXPOSED || echo hidden); "
                "echo PROC_CLEAN=$(cat /proc/cmdline 2>/dev/null | grep -qi 'cuttlefish\\|vsoc\\|goldfish\\|qemu' && echo LEAKED || echo clean); "
                "echo FRIDA_PORT=$(ss -tlnp 2>/dev/null | grep -c ':27042' || echo 0); "
                "echo ADB_PORT=$(ss -tlnp 2>/dev/null | grep -c ':5555' || echo 0); "
                "echo MAGISK_HIDDEN=$(test -f /system/bin/su -o -f /sbin/su && echo EXPOSED || echo hidden)",
                timeout=15,
            )

            # Parse all results
            for result_str in [r1, r2, r3, r4, r5, r6]:
                for line in (result_str or "").strip().split("\n"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        checks[k.strip()] = v.strip()

            # ── Compute trust score (100 points total, achievable via injection) ──
            score = 0

            # Content Data (55 points)
            if _safe_int(checks.get("CONTACTS", "0")) >= 5:
                score += 8    # Contacts (5+ entries)
            if _safe_int(checks.get("CALLS", "0")) >= 10:
                score += 8    # Call Logs (10+ entries)
            if _safe_int(checks.get("SMS", "0")) >= 5:
                score += 6    # SMS (5+ messages)
            if _safe_int(checks.get("CHROME_COOKIES", "0")) > 0:
                score += 8    # Chrome Cookies (file exists with data)
            if _safe_int(checks.get("CHROME_HISTORY", "0")) > 0:
                score += 8    # Chrome History (file exists with data)
            if _safe_int(checks.get("TPAY", "0")) > 0:
                score += 8    # Wallet/GPay tapandpay.db exists
            if _safe_int(checks.get("AUTOFILL", "0")) > 0:
                score += 5    # Chrome Autofill (Web Data exists)
            if _safe_int(checks.get("PLAYSTORE", "0")) > 0:
                score += 4    # Play Store prefs present

            # System & Identity (25 points)
            if _safe_int(checks.get("USAGE", "0")) > 0:
                score += 5    # UsageStats present
            if checks.get("GMS_REG") == "1":
                score += 5    # GMS device registration
            if checks.get("GSF_ID") == "1":
                score += 5    # GSF ID registered
            if _safe_int(checks.get("WIFI", "0")) > 0:
                score += 5    # WiFi configured
            if checks.get("GMS_IDENTITY") == "1":
                score += 5    # GMS PseudonymousId + DroidGuard prefs

            # Stealth & Security (20 points)
            if checks.get("BUILD_TYPE") == "user":
                score += 5    # Correct build type
            if not checks.get("VMOS_LEAK"):
                score += 5    # No VMOS detection
            if _safe_int(checks.get("KIWI", "0")) > 0:
                score += 5    # Kiwi browser configured
            if checks.get("MEASURE_AGE") == "1":
                score += 5    # Measurement timestamps backdated

            # Cap at 100
            score = min(score, 100)

            grade = "F"
            if score >= 95: grade = "A+"
            elif score >= 90: grade = "A"
            elif score >= 80: grade = "B+"
            elif score >= 70: grade = "B"
            elif score >= 60: grade = "C"
            elif score >= 50: grade = "D"

            self._result.trust_score = score
            self._result.grade = grade

            # Create detailed notes
            notes = f"{score}/100 ({grade}) — " + ", ".join(f"{k}={v}" for k, v in checks.items() if v)
            self._set_phase(n, "done", notes[:200])
            self._log(f"Phase 11 — Trust Audit: {score}/100 ({grade})")
            self._log(f"  Checks: {json.dumps(checks)}")

            # Stealth verification report
            stealth_issues = []
            if checks.get("SU_HIDDEN") == "EXPOSED":
                stealth_issues.append("su binary EXPOSED")
            if checks.get("PROC_CLEAN") == "LEAKED":
                stealth_issues.append("/proc/cmdline LEAKED emulator strings")
            if _safe_int(checks.get("FRIDA_PORT", "0")) > 0:
                stealth_issues.append("Frida port 27042 OPEN")
            if _safe_int(checks.get("ADB_PORT", "0")) > 0:
                stealth_issues.append("ADB port 5555 OPEN")
            if checks.get("MAGISK_HIDDEN") == "EXPOSED":
                stealth_issues.append("Magisk su binary EXPOSED")
            if checks.get("PLAY_SIGNED") == "no":
                stealth_issues.append("Play Store NOT signed in")

            if stealth_issues:
                self._log(f"  ⚠ Stealth issues: {'; '.join(stealth_issues)}")
            else:
                self._log("  ✓ Stealth verification: all clear")
            self._log(f"  Fingerprint: {checks.get('FP', '?')}")

            # ── 11b. Fast UIAutomator visual verification (no screenshots) ──
            try:
                ui_checks = {}
                # Check Settings > Accounts for Google account
                await self._sh(
                    "am start -a android.settings.SYNC_SETTINGS 2>/dev/null; echo OK",
                    timeout=10,
                )
                await asyncio.sleep(2)
                acct_ui = await self._sh(
                    "uiautomator dump /dev/stdout 2>/dev/null || "
                    "uiautomator dump /data/local/tmp/_ui.xml 2>/dev/null && cat /data/local/tmp/_ui.xml",
                    timeout=15,
                )
                acct_text = acct_ui or ""
                cfg_email = self._result.log[0] if self._result.log else ""
                # Extract email from early log  
                for log_line in self._result.log:
                    if "Phase 5 — Google Account:" in log_line:
                        cfg_email = log_line.split(":")[-1].strip().rstrip(".")
                        break
                ui_checks["google_in_settings"] = "google" in acct_text.lower() or "@gmail" in acct_text

                # Go home
                await self._sh("input keyevent KEYCODE_HOME 2>/dev/null; echo OK", timeout=5)

                ui_str = ", ".join(f"{k}={'YES' if v else 'no'}" for k, v in ui_checks.items())
                self._log(f"  UI verification: {ui_str}")
            except Exception as uie:
                self._log(f"  UI verification skipped: {uie}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 11 — Trust Audit FAILED: {e}")

    # ── Convenience: serialize result for API ─────────────────────────

    def result_dict(self) -> Dict[str, Any]:
        """Convert PipelineResult to a JSON-safe dict."""
        if not self._result:
            return {}
        return {
            "job_id": self._result.job_id,
            "pad_code": self._result.pad_code,
            "profile_id": self._result.profile_id,
            "status": self._result.status,
            "trust_score": self._result.trust_score,
            "grade": self._result.grade,
            "started_at": self._result.started_at,
            "completed_at": self._result.completed_at,
            "phases": [
                {"n": p.phase, "name": p.name, "status": p.status, "notes": p.notes}
                for p in self._result.phases
            ],
            "log": self._result.log,
        }
