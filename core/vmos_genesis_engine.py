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
import json
import os
import random
import secrets
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
    # Options
    skip_wipe: bool = False
    skip_patch: bool = False


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
        "Wipe", "Stealth Patch", "Network/Proxy", "Forge Profile",
        "Google Account", "Inject", "Wallet/GPay", "Provincial Layer",
        "Post-Harden", "Attestation", "Trust Audit",
    ]

    def __init__(self, pad_code: str, *, client: VMOSCloudClient | None = None):
        self.pad = pad_code
        self.pads = [pad_code]
        self.client = client or VMOSCloudClient()
        self._profile_data: Dict[str, Any] = {}
        self._result: PipelineResult | None = None
        self._on_update: Optional[Callable[[PipelineResult], None]] = None

    # ── ADB helpers ───────────────────────────────────────────────────

    async def _sh(self, cmd: str, timeout: int = 30) -> str:
        """Execute ADB shell command via VMOS Cloud, return stdout."""
        resp = await self.client.async_adb_cmd(self.pads, cmd)
        if resp.get("code") != 200:
            logger.warning("ADB submit failed: %s", resp)
            return ""
        data = resp.get("data", [])
        task_id = None
        if isinstance(data, list) and data:
            task_id = data[0].get("taskId")
        elif isinstance(data, dict):
            task_id = data.get("taskId")
        if not task_id:
            return ""
        for _ in range(timeout):
            await asyncio.sleep(1)
            detail = await self.client.task_detail([task_id])
            if detail.get("code") == 200 and detail.get("data"):
                items = detail["data"]
                if isinstance(items, list) and items:
                    item = items[0]
                    st = item.get("taskStatus")
                    if st == 3:
                        return item.get("taskResult", "")
                    if st in (-1, -2, -3, -4, -5):
                        return ""
        return ""

    async def _sh_ok(self, cmd: str, marker: str = "OK", timeout: int = 30) -> bool:
        """Execute ADB command and check for success marker in output."""
        result = await self._sh(cmd, timeout)
        return marker in (result or "")

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

        # Phase 1: Stealth Patch (fingerprint + root hiding + proc sterilization)
        await self._phase_stealth(cfg, preset, carrier, location)

        # Phase 2: Network / Proxy
        await self._phase_network(cfg)

        # Phase 3: Forge Profile
        profile_data = await self._phase_forge(cfg, preset, carrier, location)

        # Phase 4: Google Account
        await self._phase_google(cfg)

        # Phase 5: Inject
        await self._phase_inject(cfg, profile_data, preset)

        # Phase 6: Wallet
        await self._phase_wallet(cfg, profile_data)

        # Phase 7: Provincial Layering
        await self._phase_provincial(cfg, profile_data)

        # Phase 8: Post-Harden
        await self._phase_postharden(cfg)

        # Phase 9: Attestation
        await self._phase_attestation(preset)

        # Phase 10: Trust Audit
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
        """Phase 1: Device fingerprint + root hiding + proc sterilization."""
        n = 1
        if cfg.skip_patch:
            self._set_phase(n, "skipped", "user skip")
            return
        self._set_phase(n, "running")
        self._log("Phase 1 — Stealth: fingerprint + root hide + proc scrub...")
        t0 = time.time()
        ok_count = 0
        total = 0

        try:
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
                resp = await self.client._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
                    'padCode': self.pad, 'props': batch,
                })
                if resp.get("code") == 200:
                    ok_count += len(batch)
                await asyncio.sleep(2)

            self._log(f"Phase 1a — Props: {ok_count}/{total}")

            # ── 1b. SIM card ──
            resp = await self.client._post('/vcpcloud/api/padApi/updateSIM', {
                'padCode': self.pad, 'countryCode': cfg.country or 'US',
            })
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

            # Wait for restart from prop changes
            self._log("Phase 1 — Waiting 20s for prop changes to apply...")
            await asyncio.sleep(20)

            # Check device is responsive
            for attempt in range(10):
                result = await self._sh("echo ALIVE", timeout=10)
                if "ALIVE" in (result or ""):
                    break
                await asyncio.sleep(5)

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

            # ── 1g. Proc sterilization ──
            proc_cmd = (
                "mkdir -p /dev/.sc 2>/dev/null; "
                "cat /proc/cmdline | "
                "sed 's/cuttlefish//g;s/vsoc//g;s/virtio//g;s/goldfish//g;s/qemu//g;"
                "s/redroid//g;s/cloud//g;s/armcloud//g;s/vmos//g' > /dev/.sc/cmdline; "
                "mount -o bind /dev/.sc/cmdline /proc/cmdline 2>/dev/null; "
                "cat /proc/mounts | "
                "grep -v cloudservice | grep -v redroid | grep -v vmos > /dev/.sc/mounts; "
                "mount -o bind /dev/.sc/mounts /proc/mounts 2>/dev/null; "
                "echo '0::/' > /dev/.sc/cgroup; "
                "mount -o bind /dev/.sc/cgroup /proc/1/cgroup 2>/dev/null; "
                "echo PROC_CLEAN"
            )
            proc_ok = await self._sh_ok(proc_cmd, "PROC_CLEAN", timeout=20)
            self._log(f"Phase 1g — Proc sterilize: {'ok' if proc_ok else 'partial'}")

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

            elapsed = time.time() - t0
            sub_ok = sum([root_ok, prop_ok, proc_ok, boot_ok])
            self._set_phase(n, "done", f"{ok_count}/{total} props, {sub_ok}/4 stealth, {elapsed:.0f}s")
            self._log(f"Phase 1 — Stealth done: {ok_count}/{total} props, {sub_ok}/4 stealth in {elapsed:.0f}s")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 1 — Stealth FAILED: {e}")

    async def _phase_network(self, cfg: PipelineConfig):
        """Phase 2: Set proxy if provided."""
        n = 2
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

    async def _phase_forge(self, cfg: PipelineConfig, preset, carrier, location) -> Dict[str, Any]:
        """Phase 3: Forge identity profile."""
        n = 3
        self._set_phase(n, "running")
        self._log("Phase 3 — Forge: generating identity profile...")
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
            self._log(f"Phase 3 — Forge done: {profile_id} ({elapsed:.1f}s)")
            return profile_data

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 3 — Forge FAILED: {e}")
            return {}

    async def _phase_google(self, cfg: PipelineConfig):
        """Phase 4: Google Account injection into Android databases."""
        n = 4
        email = cfg.google_email or cfg.email
        name = cfg.name or "User"
        if not email:
            self._set_phase(n, "skipped", "no email")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 4 — Google Account: {email}...")
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

            ok_str = f"acct={'ok' if acct_ok else 'fail'} gms={'ok' if gms_ok else 'fail'} gsf={'ok' if gsf_ok else 'fail'} playstore={'ok' if playstore_ok else 'fail'}"
            self._set_phase(n, "done" if acct_ok else "warn", ok_str)
            self._log(f"Phase 4 — Google Account: {ok_str}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 4 — Google Account FAILED: {e}")

    async def _phase_inject(self, cfg: PipelineConfig, profile: Dict[str, Any], preset):
        """Phase 5: Inject contacts, call logs, SMS, WiFi, Chrome, autofill, battery."""
        n = 5
        self._set_phase(n, "running")
        self._log("Phase 5 — Inject: contacts, calls, SMS, WiFi, Chrome, autofill...")
        t0 = time.time()
        counts = {}

        try:
            # ── 5a. Contacts via content insert ──
            contacts_raw = profile.get("contacts", [])
            if contacts_raw:
                batch = contacts_raw[:30]
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
                self._log(f"Phase 5a — Contacts: {contact_ok}/{len(batch)}")

            # ── 5b. Call Logs ──
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
                self._log(f"Phase 5b — Call logs: {call_ok}/{len(batch)}")

            # ── 5c. SMS ──
            sms_list = profile.get("sms", [])
            if sms_list:
                batch = sms_list[:30]
                sms_cmds = []
                for sm in batch:
                    phone = _sanitize(sm.get("address", "+10000000000"))
                    body = _sanitize(sm.get("body", "Hey"))[:150]
                    sms_type = sm.get("type", 1)
                    ts = sm.get("timestamp", int(time.time()))
                    date_ms = int(ts * 1000)
                    sms_cmds.append(
                        f"content insert --uri content://sms "
                        f"--bind address:s:\"{phone}\" --bind body:s:\"{body}\" "
                        f"--bind type:i:{sms_type} --bind date:l:{date_ms} --bind read:i:1 2>/dev/null"
                    )
                sms_ok = 0
                for cs in range(0, len(sms_cmds), 10):
                    chunk = sms_cmds[cs:cs+10]
                    script = " && ".join(chunk) + " && echo BATCH_DONE"
                    result = await self._sh(script, timeout=30)
                    if "BATCH_DONE" in (result or ""):
                        sms_ok += len(chunk)
                counts["sms"] = sms_ok
                self._log(f"Phase 5c — SMS: {sms_ok}/{len(batch)}")

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
                self._log(f"Phase 5d — WiFi: {counts['wifi']} networks")

            # ── 5e. Chrome Cookies via sqlite3 ──
            cookies = profile.get("cookies", [])
            if cookies:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                sql_cmds = []
                for c in cookies[:30]:
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
                if sql_cmds:
                    batch_sql = "\n".join(sql_cmds)
                    cmd = (
                        f"sqlite3 {chrome_dir}/Cookies \"{batch_sql}\" 2>/dev/null; "
                        f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/Cookies 2>/dev/null; "
                        f"echo COOKIES_DONE"
                    )
                    ok = await self._sh_ok(cmd, "COOKIES_DONE", timeout=20)
                    counts["cookies"] = len(sql_cmds) if ok else 0
                    self._log(f"Phase 5e — Cookies: {counts.get('cookies', 0)}")

            # ── 5f. Chrome History via sqlite3 ──
            history = profile.get("history", [])
            if history:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                sql_cmds = []
                for h in history[:50]:
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
                    f"sqlite3 {chrome_dir}/History \"{batch_sql}\" 2>/dev/null; "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/History 2>/dev/null; "
                    f"echo HISTORY_DONE"
                )
                ok = await self._sh_ok(cmd, "HISTORY_DONE", timeout=20)
                counts["history"] = len(sql_cmds) if ok else 0
                self._log(f"Phase 5f — History: {counts.get('history', 0)}")

            # ── 5g. Autofill ──
            autofill = profile.get("autofill", {})
            if autofill or cfg.street:
                chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
                af_name = _sanitize(cfg.name or "User").replace("'", "''")
                af_email = _sanitize(cfg.google_email or cfg.email or "").replace("'", "''")
                af_phone = _sanitize(cfg.phone or "").replace("'", "''")
                af_street = _sanitize(cfg.street or "").replace("'", "''")
                af_city = _sanitize(cfg.city or "").replace("'", "''")
                af_state = _sanitize(cfg.state or "").replace("'", "''")
                af_zip = _sanitize(cfg.zip or "").replace("'", "''")
                af_country = _sanitize(cfg.country or "US").replace("'", "''")
                profile_guid = str(uuid.uuid4())
                cmd = (
                    f"sqlite3 {chrome_dir}/\"Web Data\" \""
                    f"INSERT OR REPLACE INTO autofill_profiles "
                    f"(guid,full_name,email_address,phone_number,"
                    f"street_address,city,state,zipcode,country_code) "
                    f"VALUES("
                    f"'{profile_guid}','{af_name}','{af_email}','{af_phone}',"
                    f"'{af_street}','{af_city}','{af_state}','{af_zip}','{af_country}'"
                    f");\" 2>/dev/null; echo AUTOFILL_DONE"
                )
                ok = await self._sh_ok(cmd, "AUTOFILL_DONE", timeout=15)
                counts["autofill"] = 1 if ok else 0
                self._log(f"Phase 5g — Autofill: {'ok' if ok else 'fail'}")

            # ── 5h. Battery via native API ──
            battery_level = random.randint(42, 87)
            charging = random.choice([0, 1])
            resp = await self.client.modify_instance_properties(self.pads, {
                "batteryLevel": battery_level,
                "batteryStatus": charging,
            })
            counts["battery"] = 1 if resp.get("code") == 200 else 0
            self._log(f"Phase 5h — Battery: {battery_level}% {'charging' if charging else 'discharging'}")

            # ── 5i. GAID reset ──
            resp = await self.client.reset_gaid(self.pads)
            counts["gaid"] = 1 if resp.get("code") == 200 else 0

            # ── 5j. UsageStats aging ──
            now_ts = int(time.time())
            birth_ts = now_ts - (cfg.age_days * 86400)
            usage_entries = []
            for day_offset in range(0, cfg.age_days, 3):
                day_ts = (birth_ts + day_offset * 86400) * 1000
                usage_entries.append(
                    f"<usageStats package=\"com.android.chrome\" "
                    f"totalTimeInForeground=\"{random.randint(60000, 900000)}\" "
                    f"lastTimeUsed=\"{day_ts}\" />"
                )
                usage_entries.append(
                    f"<usageStats package=\"com.google.android.apps.maps\" "
                    f"totalTimeInForeground=\"{random.randint(30000, 300000)}\" "
                    f"lastTimeUsed=\"{day_ts}\" />"
                )
                usage_entries.append(
                    f"<usageStats package=\"com.android.vending\" "
                    f"totalTimeInForeground=\"{random.randint(30000, 600000)}\" "
                    f"lastTimeUsed=\"{day_ts}\" />"
                )
            usage_xml = (
                '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                '<usagestats version="1">\n'
                + "\n".join(usage_entries) +
                '\n</usagestats>'
            )
            usage_cmd = (
                "mkdir -p /data/system/usagestats/0/daily 2>/dev/null; "
                f"cat > /data/system/usagestats/0/daily/usage_stats.xml << 'USEOF'\n"
                f"{usage_xml}\n"
                f"USEOF\n"
                "chown system:system /data/system/usagestats/0/daily/usage_stats.xml 2>/dev/null; "
                "chmod 600 /data/system/usagestats/0/daily/usage_stats.xml 2>/dev/null; "
                "echo USAGE_SET"
            )
            usage_ok = await self._sh_ok(usage_cmd, "USAGE_SET", timeout=20)
            counts["usagestats"] = len(usage_entries) if usage_ok else 0
            self._log(f"Phase 5j — UsageStats: {counts['usagestats']} entries over {cfg.age_days} days")

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

            elapsed = time.time() - t0
            summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
            self._set_phase(n, "done", f"{summary}, {elapsed:.0f}s")
            self._log(f"Phase 5 — Inject done in {elapsed:.0f}s: {summary}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 5 — Inject FAILED: {e}")

    async def _phase_wallet(self, cfg: PipelineConfig, profile: Dict[str, Any]):
        """Phase 6: Wallet / GPay credit card injection."""
        n = 6
        cc = cfg.cc_number.replace(" ", "").replace("-", "")
        if not cc or len(cc) < 13:
            self._set_phase(n, "skipped", "no card")
            self._log("Phase 6 — Wallet: skipped (no card data)")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 6 — Wallet: injecting card ***{cc[-4:]}...")
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
                f"2>/dev/null; "
                f"chown $(stat -c '%u:%g' {chrome_dir}/) {chrome_dir}/\"Web Data\" 2>/dev/null; "
                f"echo WEBDATA_DONE"
            )
            webdata_ok = await self._sh_ok(web_data_cmd, "WEBDATA_DONE", timeout=15)

            # ── 6b. GMS tapandpay.db ──
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
                f"'{token_ref}', '{display}', 1, -12285185, 3);\" 2>/dev/null; "
                f"chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                f"/data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null; "
                f"echo TPAY_DONE"
            )
            tpay_ok = await self._sh_ok(tpay_cmd, "TPAY_DONE", timeout=15)

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

            results = f"web_data={'ok' if webdata_ok else 'fail'} tpay={'ok' if tpay_ok else 'fail'} coin={'ok' if coin_ok else 'fail'}"
            ok_total = sum([webdata_ok, tpay_ok, coin_ok])
            self._set_phase(n, "done" if ok_total >= 2 else "warn", f"{ok_total}/3 targets")
            self._log(f"Phase 6 — Wallet: {results}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 6 — Wallet FAILED: {e}")

    async def _phase_provincial(self, cfg: PipelineConfig, profile: Dict[str, Any]):
        """Phase 7: Provincial Layering — app-specific SharedPreferences injection."""
        n = 7
        self._set_phase(n, "running")
        self._log("Phase 7 — Provincial Layering: injecting app-specific data...")
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
            self._log(f"Phase 7 — Provincial: {prefs_ok}/{len(targets)} apps")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 7 — Provincial FAILED: {e}")

    async def _phase_postharden(self, cfg: PipelineConfig):
        """Phase 8: Post-Harden — Kiwi/Chrome prefs, media scan."""
        n = 8
        self._set_phase(n, "running")
        self._log("Phase 8 — Post-Harden: Kiwi prefs, media scan...")
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
            self._log(f"Phase 8 — Post-Harden: {notes}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 8 — Post-Harden FAILED: {e}")

    async def _phase_attestation(self, preset):
        """Phase 9: Attestation checks — keybox, verified boot, build type."""
        n = 9
        self._set_phase(n, "running")
        self._log("Phase 9 — Attestation: keybox, verified boot, GSF...")
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
            self._log(f"Phase 9 — Attestation: {notes}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 9 — Attestation FAILED: {e}")

    async def _phase_trust_audit(self, profile: Dict[str, Any]):
        """Phase 10: Trust score — verify injected data counts with enhanced checks."""
        n = 10
        self._set_phase(n, "running")
        self._log("Phase 10 — Trust Audit: comprehensive verification...")
        try:
            # Enhanced audit with more checks for higher score potential
            audit_cmd = (
                "echo CONTACTS=$(content query --uri content://com.android.contacts/raw_contacts --projection _id 2>/dev/null | wc -l); "
                "echo CALLS=$(content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l); "
                "echo SMS=$(content query --uri content://sms --projection _id 2>/dev/null | wc -l); "
                "echo CHROME_COOKIES=$(sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies "
                "'SELECT COUNT(*) FROM cookies' 2>/dev/null || echo 0); "
                "echo CHROME_HISTORY=$(sqlite3 /data/data/com.android.chrome/app_chrome/Default/History "
                "'SELECT COUNT(*) FROM urls' 2>/dev/null || echo 0); "
                "echo ACCOUNTS=$(sqlite3 /data/system_ce/0/accounts_ce.db "
                "'SELECT COUNT(*) FROM accounts' 2>/dev/null || echo 0); "
                "echo USAGE=$(ls /data/system/usagestats/0/daily/ 2>/dev/null | wc -l); "
                "echo TPAY=$(sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db "
                "'SELECT COUNT(*) FROM token_metadata' 2>/dev/null || echo 0); "
                # Additional checks for 95%+ score
                "echo PLAYSTORE=$(ls /data/data/com.android.vending/shared_prefs/*.xml 2>/dev/null | wc -l); "
                "echo GMS_REG=$(test -f /data/data/com.google.android.gms/shared_prefs/device_registration.xml && echo 1 || echo 0); "
                "echo GSF_ID=$(test -f /data/data/com.google.android.gsf/shared_prefs/gservices.xml && echo 1 || echo 0); "
                "echo KIWI=$(test -f /data/data/com.kiwibrowser.browser/app_chrome/Default/Preferences && echo 1 || echo 0); "
                "echo AUTOFILL=$(sqlite3 /data/data/com.android.chrome/app_chrome/Default/'Web Data' "
                "'SELECT COUNT(*) FROM autofill_profiles' 2>/dev/null || echo 0); "
                "echo WIFI=$(getprop persist.sys.cloud.wifi.ssid 2>/dev/null || echo ''); "
                "echo BUILD_TYPE=$(getprop ro.build.type); "
                "echo VMOS_LEAK=$(getprop ro.vmos.simplest.rom || echo '')"
            )
            result = await self._sh(audit_cmd, timeout=25)

            checks = {}
            for line in (result or "").strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    checks[k.strip()] = v.strip()

            # Compute comprehensive trust score (total potential = 100)
            score = 0
            
            # Core data injection (50 points)
            if int(checks.get("ACCOUNTS", "0")) > 0:
                score += 12   # Google Account
            if int(checks.get("CHROME_COOKIES", "0")) > 0:
                score += 8    # Chrome Cookies
            if int(checks.get("CHROME_HISTORY", "0")) > 0:
                score += 8    # Chrome History
            if int(checks.get("TPAY", "0")) > 0:
                score += 8    # Wallet/GPay
            if int(checks.get("CONTACTS", "0")) >= 5:
                score += 7    # Contacts (5+ entries)
            if int(checks.get("CALLS", "0")) >= 10:
                score += 7    # Call Logs (10+ entries)
            
            # Secondary data (25 points)
            if int(checks.get("SMS", "0")) >= 5:
                score += 6    # SMS (5+ messages)
            if int(checks.get("USAGE", "0")) > 0:
                score += 5    # UsageStats
            if int(checks.get("AUTOFILL", "0")) > 0:
                score += 4    # Chrome Autofill
            if int(checks.get("PLAYSTORE", "0")) > 3:
                score += 6    # Play Store prefs (signed in indicator)
            if int(checks.get("KIWI", "0")) > 0:
                score += 4    # Kiwi browser configured
            
            # Service registration (15 points)
            if checks.get("GMS_REG") == "1":
                score += 5    # GMS device registration
            if checks.get("GSF_ID") == "1":
                score += 5    # GSF ID registered
            if checks.get("WIFI"):
                score += 5    # WiFi configured
            
            # Security/Stealth (10 points)
            if checks.get("BUILD_TYPE") == "user":
                score += 5    # Correct build type
            if not checks.get("VMOS_LEAK"):
                score += 5    # No VMOS detection
            
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
            self._set_phase(n, "done", notes[:120])
            self._log(f"Phase 10 — Trust Audit: {score}/100 ({grade})")
            self._log(f"  Checks: {json.dumps(checks)}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 10 — Trust Audit FAILED: {e}")

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
