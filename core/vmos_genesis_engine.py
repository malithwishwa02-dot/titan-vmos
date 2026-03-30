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
import hashlib
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
from google_master_auth import GoogleMasterAuth, AuthMethod
from vmos_db_builder import VMOSDbBuilder
from vmos_file_pusher import VMOSFilePusher
from coherence_bridge import CoherenceBridge

logger = setup_json_logging("vmos_genesis")

# ── Constants ──────────────────────────────────────────────────────────────

_GMS_VERSION_INT = 240913900  # GMS version code in device_registration.xml


# ── Helpers ────────────────────────────────────────────────────────────────

_PROFILES_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"

# ── TSP-assigned Token BIN ranges (for DPAN generation) ───────────────────
_TOKEN_BIN_RANGES = {
    "visa":       ["489537", "489538", "489539", "440066", "440067"],
    "mastercard": ["530060", "530061", "530062", "530063", "530064", "530065"],
    "amex":       ["374800", "374801"],
    "discover":   ["601156", "601157"],
}

# ── Bank SMS sender IDs ──────────────────────────────────────────────────
_BANK_SMS_SENDERS = {
    "visa": [
        ("33789", "Chase: Your card ending in {last4} was charged ${amt:.2f} at {merchant}"),
        ("73981", "BofA Alert: Purchase of ${amt:.2f} on card ending {last4}"),
    ],
    "mastercard": [
        ("227462", "Capital One: Transaction alert for card ...{last4}: ${amt:.2f} at {merchant}"),
        ("95686", "Citi Alert: ${amt:.2f} charge on card ending in {last4} at {merchant}"),
    ],
    "amex": [("26297", "Amex: Card ending {last4} charged ${amt:.2f} at {merchant}")],
    "discover": [("347268", "Discover: ${amt:.2f} purchase on card ending {last4}")],
}

# ── Purchase history merchants ────────────────────────────────────────────
_MERCHANTS = [
    {"name": "Amazon.com", "domain": "amazon.com", "cookies": ["session-id", "ubid-main"],
     "amounts": (15.99, 149.99)},
    {"name": "Walmart", "domain": "walmart.com", "cookies": ["auth", "cart-item-count"],
     "amounts": (7.97, 98.00)},
    {"name": "Target", "domain": "target.com", "cookies": ["visitorId"],
     "amounts": (8.00, 45.00)},
    {"name": "Starbucks", "domain": "starbucks.com", "cookies": ["JSESSIONID"],
     "amounts": (4.75, 12.50)},
    {"name": "Netflix", "domain": "netflix.com", "cookies": ["NetflixId"],
     "amounts": (15.49, 22.99)},
    {"name": "Uber Eats", "domain": "ubereats.com", "cookies": ["sid"],
     "amounts": (12.00, 45.00)},
    {"name": "DoorDash", "domain": "doordash.com", "cookies": ["dd-session"],
     "amounts": (15.00, 55.00)},
]

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


def _detect_network(card_number: str) -> str:
    """Detect card network from BIN prefix."""
    first = card_number[0] if card_number else ""
    if first == "4":
        return "visa"
    elif first in ("5", "2"):
        return "mastercard"
    elif first == "3":
        return "amex"
    elif first == "6":
        return "discover"
    return "visa"


def _gen_dpan(card_number: str) -> str:
    """Generate DPAN using real TSP-assigned Token BIN ranges."""
    network = _detect_network(card_number)
    token_bin = random.choice(_TOKEN_BIN_RANGES.get(network, _TOKEN_BIN_RANGES["visa"]))
    remaining_len = len(card_number) - 7  # 6 BIN digits + 1 check digit
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
    check = (10 - total % 10) % 10
    return partial + str(check)


def _gen_luk_seed(dpan: str, atc: int) -> str:
    """Generate Limited Use Key seed via HMAC-SHA256 derivation."""
    import hmac as _hmac
    master = hashlib.sha256(f"TITAN-MK-{dpan}".encode()).digest()
    derived = _hmac.new(master, f"{dpan}{atc:04d}".encode(), hashlib.sha256).hexdigest()
    return derived[:32]



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
        # V3 helpers — shared across phases
        self._db_builder = VMOSDbBuilder()
        self._file_pusher = VMOSFilePusher(self.client, pad_code)
        self._coherence = CoherenceBridge(self._file_pusher, self._db_builder)

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

        # Phase 4b: Purchase History (V3 — library.db host-built + pushed)
        await self._phase_purchase_history(cfg)

        # Phase 5: Inject
        await self._phase_inject(cfg, profile_data, preset)

        # Phase 5c: Coherence Bridge (OBLIVION) — cross-store data alignment
        await self._phase_coherence(cfg)

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
                # Clear wallet (BOTH paths)
                "rm -rf /data/data/com.google.android.gms/databases/tapandpay.db* 2>/dev/null; "
                "rm -rf /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db* 2>/dev/null; "
                "rm -rf /data/data/com.google.android.apps.walletnfcrel/shared_prefs/*.xml 2>/dev/null; "
                "rm -rf /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null; "
                "rm -rf /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null; "
                "rm -rf /data/data/com.google.android.gms/shared_prefs/payment_profile_prefs.xml 2>/dev/null; "
                # Clear UsageStats
                "rm -rf /data/system/usagestats/0/* 2>/dev/null; "
                # Clear WiFi config
                "rm -f /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null; "
                "rm -f /data/misc/wifi/WifiConfigStore.xml 2>/dev/null; "
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

            # ── 1i. NFC enable (required for wallet) ──
            nfc_cmd = (
                "settings put secure nfc_on 1 2>/dev/null; "
                "settings put secure nfc_payment_foreground 1 2>/dev/null; "
                "svc nfc enable 2>/dev/null; "
                "echo NFC_ON"
            )
            nfc_ok = await self._sh_ok(nfc_cmd, "NFC_ON", timeout=10)
            self._log(f"Phase 1i — NFC enable: {'ok' if nfc_ok else 'partial'}")

            # ── 1j. VMOS-specific artifact scrubbing ──
            vmos_cmd = (
                "resetprop --delete ro.vmos.simplest.rom 2>/dev/null; "
                "resetprop --delete ro.vmos.version 2>/dev/null; "
                "resetprop --delete persist.sys.cloud.wifi.ssid 2>/dev/null; "
                "resetprop --delete ro.cloudphone 2>/dev/null; "
                "resetprop --delete persist.sys.cloud.phone 2>/dev/null; "
                "pm disable-user --user 0 com.vmos.toolbox 2>/dev/null; "
                "pm hide com.vmos.toolbox 2>/dev/null; "
                "echo VMOS_CLEAN"
            )
            vmos_ok = await self._sh_ok(vmos_cmd, "VMOS_CLEAN", timeout=15)
            self._log(f"Phase 1j — VMOS scrub: {'ok' if vmos_ok else 'partial'}")

            elapsed = time.time() - t0
            sub_ok = sum([root_ok, prop_ok, proc_ok, boot_ok, nfc_ok, vmos_ok])
            self._set_phase(n, "done", f"{ok_count}/{total} props, {sub_ok}/6 stealth, {elapsed:.0f}s")
            self._log(f"Phase 1 — Stealth done: {ok_count}/{total} props, {sub_ok}/6 stealth in {elapsed:.0f}s")

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
        """Phase 4: Google Account injection — V3 Nexus OBLIVION.

        Execution order:
          0. Phase 1 Reconnaissance — retrieve real android_id + GSF ID from device.
          1. Attempt Method A (gpsoauth master-token) using the device's android_id.
          2. Fall back to Method C (hybrid inject) if Method A fails.
          3. Build accounts_ce.db + accounts_de.db **host-side** with
             :class:`VMOSDbBuilder` and push via :class:`VMOSFilePusher`
             (avoids dependency on device-side ``sqlite3`` binary).
          4. Write GMS / GSF / Play Store shared_prefs.
        """
        n = 4
        email = cfg.google_email or cfg.email
        name = cfg.name or "User"
        if not email:
            self._set_phase(n, "skipped", "no email")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 4 — Google Account V3 OBLIVION: {email}...")

        try:
            # ── Phase 1 Recon: retrieve real android_id + GSF ID ──────
            # Using the device's own android_id as the AAS binding key ensures
            # the master token is bound to this specific device fingerprint,
            # avoiding re-auth triggers from GMS device-mismatch detection.
            import hashlib as _hl
            device_android_id = await self._retrieve_android_id()
            if not device_android_id:
                # Deterministic fallback derived from email (repeatable across runs)
                device_android_id = _hl.sha256(email.encode()).hexdigest()[:16]
                self._log(f"Phase 4 Recon — android_id not found, using derived: {device_android_id}")
            else:
                self._log(f"Phase 4 Recon — android_id retrieved: {device_android_id}")

            # ── 4a. Acquire tokens (Method A → C fallback) ────────────
            auth_result = None
            password = cfg.google_password or ""

            if password:
                self._log("Phase 4a — GoogleMasterAuth: attempting master-token flow...")
                auth = GoogleMasterAuth(country=(cfg.country or "US").lower())

                auth_result = auth.authenticate(
                    email=email,
                    password=password,
                    android_id=device_android_id,
                    method=AuthMethod.MASTER_TOKEN,
                )

                if auth_result.success and auth_result.has_real_tokens:
                    self._log(
                        f"Phase 4a — Real tokens acquired: {len(auth_result.tokens)} scopes"
                    )
                else:
                    self._log(
                        f"Phase 4a — Method A failed ({auth_result.errors}), "
                        f"falling back to Method C hybrid injection"
                    )
                    auth_result = auth.authenticate(
                        email=email,
                        password=password,
                        android_id=device_android_id,
                        method=AuthMethod.HYBRID_INJECT,
                    )
            else:
                self._log("Phase 4a — No password provided, using synthetic tokens")
                _auth = GoogleMasterAuth()
                auth_result = _auth.authenticate(
                    email=email,
                    password="",
                    android_id=device_android_id,
                    method=AuthMethod.MASTER_TOKEN,
                )

            # Collect tokens for DB injection
            tokens = auth_result.all_tokens_for_injection() if auth_result else {}
            hybrid_password = getattr(auth_result, "_hybrid_password", "") if auth_result else ""
            token_mode = (
                "real" if (auth_result and auth_result.has_real_tokens)
                else "hybrid" if hybrid_password
                else "synthetic"
            )

            # ── 4b. Build accounts_ce.db + accounts_de.db host-side ───
            self._log(f"Phase 4b — Building accounts_ce.db (mode={token_mode})...")
            gaia_id = str(random.randint(100_000_000_000, 999_999_999_999_999_999_999))

            ce_bytes = self._db_builder.build_accounts_ce(
                email=email,
                display_name=name,
                gaia_id=gaia_id,
                tokens=tokens,
                password=hybrid_password,
                age_days=cfg.age_days,
            )
            de_bytes = self._db_builder.build_accounts_de(
                email=email,
                display_name=name,
                gaia_id=gaia_id,
                age_days=cfg.age_days,
            )

            # ── 4c. Push databases to device ──────────────────────────
            self._log("Phase 4c — Pushing account databases to device...")
            ce_ok = await self._file_pusher.push_bytes(
                data=ce_bytes,
                remote_path="/data/system_ce/0/accounts_ce.db",
                owner="system:system",
                mode="600",
            )
            de_ok = await self._file_pusher.push_bytes(
                data=de_bytes,
                remote_path="/data/system_de/0/accounts_de.db",
                owner="system:system",
                mode="600",
            )
            acct_ok = ce_ok or de_ok  # at least one must succeed

            # ── 4d. GMS shared_prefs ──────────────────────────────────
            e_safe = _sanitize(email)
            f_safe = _sanitize(name.split()[0] if name else "User")
            l_safe = _sanitize(name.split()[-1] if name and len(name.split()) > 1 else "")
            birth_ts = int(time.time()) - cfg.age_days * 86400

            gms_xml = (
                '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                "<map>\n"
                f'  <long name="device_registered_timestamp" value="{birth_ts * 1000}" />\n'
                f'  <string name="device_id">{_gen_android_id()}</string>\n'
                f'  <int name="gms_version" value="{_GMS_VERSION_INT}" />\n'
                "</map>"
            )
            gms_ok = await self._file_pusher.push_xml_pref(
                gms_xml,
                "/data/data/com.google.android.gms/shared_prefs/device_registration.xml",
                pkg_dir="/data/data/com.google.android.gms",
            )

            # ── 4e. GSF ID ─────────────────────────────────────────────
            gsf_id = _gen_gsf_id()
            gsf_xml = (
                '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                "<map>\n"
                f'  <string name="android_id">{gsf_id}</string>\n'
                f'  <long name="registration_timestamp" value="{birth_ts * 1000}" />\n'
                "</map>"
            )
            gsf_ok = await self._file_pusher.push_xml_pref(
                gsf_xml,
                "/data/data/com.google.android.gsf/shared_prefs/gservices.xml",
                pkg_dir="/data/data/com.google.android.gsf",
            )

            # ── 4f. Play Store account binding ────────────────────────
            finsky_xml = (
                '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                "<map>\n"
                f'  <string name="signed_in_account">{e_safe}</string>\n'
                '  <boolean name="setup_complete" value="true" />\n'
                '  <boolean name="has_consented" value="true" />\n'
                f'  <long name="consent_timestamp" value="{birth_ts * 1000}" />\n'
                '  <int name="onboarding_completed" value="1" />\n'
                "</map>"
            )
            playstore_ok = await self._file_pusher.push_xml_pref(
                finsky_xml,
                "/data/data/com.android.vending/shared_prefs/finsky.xml",
                pkg_dir="/data/data/com.android.vending",
            )

            # ── 4g. GMS phenotype (app discovery) via shell ────────────
            phenotype_cmd = (
                f"sqlite3 /data/data/com.google.android.gms/databases/phenotype.db "
                f"\"INSERT OR REPLACE INTO ApplicationTags (packageName, user, version) "
                f"VALUES ('com.android.vending', '{e_safe}', 1);\" 2>/dev/null; "
                "echo PHENOTYPE_OK"
            )
            await self._sh(phenotype_cmd, timeout=10)

            ok_str = (
                f"tokens={token_mode} ce={'ok' if ce_ok else 'fail'} "
                f"de={'ok' if de_ok else 'fail'} gms={'ok' if gms_ok else 'fail'} "
                f"gsf={'ok' if gsf_ok else 'fail'} play={'ok' if playstore_ok else 'fail'}"
            )
            phase_status = "done" if acct_ok else "warn"
            self._set_phase(n, phase_status, ok_str)
            self._log(f"Phase 4 — Google Account V3: {ok_str}")

        except Exception as e:
            self._set_phase(n, "failed", str(e)[:80])
            self._log(f"Phase 4 — Google Account FAILED: {e}")


    async def _phase_purchase_history(self, cfg: PipelineConfig):
        """Phase 4b: Play Store purchase history injection (V3 addition).

        Builds ``library.db`` host-side via :class:`VMOSDbBuilder` and pushes it
        to the device.  This creates realistic app-ownership records that Play
        Store reads when showing installed/purchased apps.
        """
        email = cfg.google_email or cfg.email
        if not email:
            return

        self._log("Phase 4b — Purchase History: building library.db...")
        try:
            lib_bytes = self._db_builder.build_library(
                email=email,
                num_auto_purchases=15,
                age_days=cfg.age_days,
            )
            lib_ok = await self._file_pusher.push_bytes(
                data=lib_bytes,
                remote_path="/data/data/com.android.vending/databases/library.db",
                owner="",  # inherited via dynamic chown below
                mode="660",
            )
            # Inherit ownership from vending app dir
            await self._sh(
                "OWNER=$(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null); "
                "[ -n \"$OWNER\" ] && chown $OWNER "
                "/data/data/com.android.vending/databases/library.db 2>/dev/null; "
                "echo CHOWN_OK",
                timeout=10,
            )
            self._log(f"Phase 4b — Purchase History: {'ok' if lib_ok else 'fail'} ({len(lib_bytes)}B)")
        except Exception as exc:
            self._log(f"Phase 4b — Purchase History FAILED: {exc}")

    async def _retrieve_android_id(self) -> str:
        """Phase 1 Reconnaissance: retrieve the device's real android_id.

        Tries three sources in priority order:
          1. GSF android_id from gservices.xml (most authoritative)
          2. Settings secure android_id (Settings provider)
          3. Build property ro.serialno

        Returns:
            16-char hex android_id string, or empty string if not found.
        """
        try:
            result = await self._sh(
                "echo GSID=$(sqlite3 /data/data/com.google.android.gsf/shared_prefs/gservices.xml "
                "2>/dev/null | grep android_id | head -1 || "
                "settings get secure android_id 2>/dev/null || echo ''); "
                "echo SERIAL=$(getprop ro.serialno 2>/dev/null || echo '')",
                timeout=10,
            )
            for line in (result or "").strip().split("\n"):
                if line.startswith("GSID="):
                    val = line[5:].strip()
                    if val and len(val) >= 8 and val not in ("null", ""):
                        return val[:16]
                if line.startswith("SERIAL="):
                    val = line[7:].strip()
                    if val and len(val) >= 8 and val not in ("null", ""):
                        return val[:16]
        except Exception as exc:
            self._log(f"Phase 1 Recon — android_id retrieval error: {exc}")
        return ""

    async def _phase_coherence(self, cfg: PipelineConfig):
        """Phase 5c: Coherence Bridge — V3 Nexus OBLIVION cross-store alignment.

        Synchronizes Order IDs and merchant events across:
          * Chrome History (receipt confirmation pages)
          * Chrome Cookies (merchant session cookies)
          * Gmail.xml (receipt inbox metadata with matching Order IDs)
          * library.db (Play Store ownership records)

        This eliminates behavioral fingerprinting signals that arise when
        tapandpay.db lists transactions at merchants not present in other stores.
        """
        email = cfg.google_email or cfg.email
        if not email:
            self._log("Phase 5c — Coherence: skipped (no email)")
            return

        self._log(f"Phase 5c — Coherence Bridge: synchronizing cross-store data...")
        try:
            result = await self._coherence.inject_all(
                email=email,
                country=cfg.country or "US",
                age_days=cfg.age_days,
                num_orders=8,
            )
            self._log(f"Phase 5c — Coherence Bridge: {result.summary()}")
        except Exception as exc:
            self._log(f"Phase 5c — Coherence Bridge FAILED: {exc}")

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
        """Phase 6: Wallet / GPay — 5 subsystem injection matching purchase validation docs."""
        n = 6
        cc = cfg.cc_number.replace(" ", "").replace("-", "")
        if not cc or len(cc) < 13:
            self._set_phase(n, "skipped", "no card")
            self._log("Phase 6 — Wallet: skipped (no card data)")
            return
        self._set_phase(n, "running")
        self._log(f"Phase 6 — Wallet: injecting card ***{cc[-4:]} into 5 subsystems...")
        t0 = time.time()
        results = {}
        try:
            # Parse expiry
            exp_parts = cfg.cc_exp.split("/") if "/" in cfg.cc_exp else [cfg.cc_exp[:2], cfg.cc_exp[2:]]
            exp_month = int(exp_parts[0]) if exp_parts else 12
            exp_year = int(exp_parts[1]) if len(exp_parts) > 1 else 2029
            if exp_year < 100:
                exp_year += 2000
            holder = cfg.cc_holder or cfg.name or "Cardholder"
            email = _sanitize(cfg.google_email or cfg.email or "")
            network = _detect_network(cc)
            network_id = {"visa": 1, "mastercard": 2, "amex": 3, "discover": 4}.get(network, 1)
            last4 = cc[-4:]
            dpan = _gen_dpan(cc)
            token_ref = secrets.token_hex(16)
            luk_seed = _gen_luk_seed(dpan, 1)
            display = f"{network.upper()} ····{last4}"
            holder_safe = holder.replace("'", "''")
            now_ts = int(time.time())
            birth_ts = now_ts - (cfg.age_days * 86400)

            # ══════════════════════════════════════════════════════════════
            # SUBSYSTEM 1: Google Pay (tapandpay.db) — FULL SCHEMA
            # ══════════════════════════════════════════════════════════════
            # Generate transaction history entries
            tx_entries_sql = []
            for i in range(random.randint(5, 12)):
                m = random.choice(_MERCHANTS)
                tx_amt = round(random.uniform(*m["amounts"]), 2)
                tx_ts = birth_ts + random.randint(86400 * 7, cfg.age_days * 86400)
                tx_id = secrets.token_hex(8)
                tx_entries_sql.append(
                    f"INSERT INTO transaction_history (transaction_id, amount_cents, "
                    f"currency_code, merchant_name, timestamp_ms, dpan, status) VALUES "
                    f"('{tx_id}', {int(tx_amt * 100)}, 'USD', "
                    f"'{m['name']}', {tx_ts * 1000}, '{dpan}', 'COMPLETED');"
                )

            # Build full tapandpay.db with 5 tables
            tpay_sql = (
                # Table 1: token_metadata
                "CREATE TABLE IF NOT EXISTS token_metadata ("
                "id INTEGER PRIMARY KEY, dpan TEXT, last_four TEXT, network INTEGER, "
                "token_ref TEXT, display_name TEXT, is_default INTEGER, "
                "card_color INTEGER, token_state INTEGER, issuer_name TEXT, "
                "card_art_url TEXT, provisioning_status TEXT, "
                "expiry_month INTEGER, expiry_year INTEGER); "
                f"INSERT OR REPLACE INTO token_metadata VALUES "
                f"(1, '{dpan}', '{last4}', {network_id}, '{token_ref}', "
                f"'{display}', 1, -12285185, 3, "
                f"'{holder_safe}', '', 'PROVISIONED', {exp_month}, {exp_year}); "
                # Table 2: tokens
                "CREATE TABLE IF NOT EXISTS tokens ("
                "id INTEGER PRIMARY KEY, token_data TEXT, pan_last_four TEXT, "
                "network_id INTEGER, token_state INTEGER); "
                f"INSERT OR REPLACE INTO tokens VALUES "
                f"(1, '{token_ref}', '{last4}', {network_id}, 3); "
                # Table 3: emv_metadata
                "CREATE TABLE IF NOT EXISTS emv_metadata ("
                "id INTEGER PRIMARY KEY, dpan TEXT, luk_seed TEXT, "
                "atc INTEGER, derivation_type TEXT); "
                f"INSERT OR REPLACE INTO emv_metadata VALUES "
                f"(1, '{dpan}', '{luk_seed}', 1, 'HMAC_SHA256'); "
                # Table 4: transaction_history
                "CREATE TABLE IF NOT EXISTS transaction_history ("
                "transaction_id TEXT PRIMARY KEY, amount_cents INTEGER, "
                "currency_code TEXT, merchant_name TEXT, timestamp_ms INTEGER, "
                "dpan TEXT, status TEXT); "
                + " ".join(tx_entries_sql) + " "
                # Table 5: payment_instrument
                "CREATE TABLE IF NOT EXISTS payment_instrument ("
                "id INTEGER PRIMARY KEY, instrument_id TEXT, display_name TEXT, "
                "network TEXT, last_four TEXT, is_active INTEGER); "
                f"INSERT OR REPLACE INTO payment_instrument VALUES "
                f"(1, 'instrument_1', '{display}', '{network}', '{last4}', 1);"
            )

            # Inject into BOTH paths
            for db_dir in [
                "/data/data/com.google.android.gms/databases",
                "/data/data/com.google.android.apps.walletnfcrel/databases",
            ]:
                tpay_cmd = (
                    f"mkdir -p {db_dir} 2>/dev/null; "
                    f"sqlite3 {db_dir}/tapandpay.db \"{tpay_sql}\" 2>/dev/null; "
                    f"echo TPAY_OK"
                )
                await self._sh_ok(tpay_cmd, "TPAY_OK", timeout=20)

            # Fix ownership for both paths
            own_cmd = (
                "for d in /data/data/com.google.android.gms "
                "/data/data/com.google.android.apps.walletnfcrel; do "
                "  uid=$(stat -c '%u:%g' $d 2>/dev/null); "
                "  [ -n \"$uid\" ] && chown -R $uid $d/databases/ 2>/dev/null; "
                "  chmod 660 $d/databases/tapandpay.db 2>/dev/null; "
                "  restorecon -R $d/databases/ 2>/dev/null; "
                "done; echo OWN_OK"
            )
            results["tapandpay"] = await self._sh_ok(own_cmd, "OWN_OK", timeout=15)
            self._log(f"Phase 6a — tapandpay.db: {'ok' if results['tapandpay'] else 'fail'} (5 tables, {len(tx_entries_sql)} transactions)")

            # ══════════════════════════════════════════════════════════════
            # SUBSYSTEM 2: Play Store Billing (COIN.xml) — 6 ZERO-AUTH FLAGS
            # ══════════════════════════════════════════════════════════════
            auth_token = secrets.token_hex(32)
            coin_cmd = (
                "mkdir -p /data/data/com.google.android.gms/shared_prefs 2>/dev/null; "
                f"cat > /data/data/com.google.android.gms/shared_prefs/COIN.xml << 'COINEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <boolean name=\"has_payment_methods\" value=\"true\" />\n'
                f'  <string name=\"default_instrument_id\">instrument_1</string>\n'
                f'  <string name=\"account_name\">{email}</string>\n'
                f'  <boolean name=\"wallet_enabled\" value=\"true\" />\n'
                f'  <string name=\"payment_method_id\">pm_{token_ref[:16]}</string>\n'
                f'  <string name=\"payment_method_last_four\">{last4}</string>\n'
                f'  <string name=\"payment_method_type\">{network.upper()}</string>\n'
                f'  <boolean name=\"purchase_requires_auth\" value=\"false\" />\n'
                f'  <boolean name=\"require_purchase_auth\" value=\"false\" />\n'
                f'  <boolean name=\"one_touch_enabled\" value=\"true\" />\n'
                f'  <boolean name=\"biometric_payment_enabled\" value=\"true\" />\n'
                f'  <string name=\"auth_token\">{auth_token}</string>\n'
                f"</map>\n"
                f"COINEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                "/data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null; "
                "echo COIN_OK"
            )
            results["coin"] = await self._sh_ok(coin_cmd, "COIN_OK", timeout=15)
            self._log(f"Phase 6b — COIN.xml: {'ok' if results['coin'] else 'fail'} (6 zero-auth flags)")

            # ══════════════════════════════════════════════════════════════
            # SUBSYSTEM 3: Chrome Autofill (Web Data) — card_number = NULL
            # ══════════════════════════════════════════════════════════════
            card_guid = str(uuid.uuid4())
            for chrome_dir in ["/data/data/com.android.chrome/app_chrome/Default",
                               "/data/data/com.kiwibrowser.browser/app_chrome/Default"]:
                web_data_cmd = (
                    f"sqlite3 {chrome_dir}/\"Web Data\" \""
                    f"CREATE TABLE IF NOT EXISTS credit_cards "
                    f"(guid TEXT PRIMARY KEY, name_on_card TEXT, card_number_encrypted BLOB, "
                    f"expiration_month INTEGER, expiration_year INTEGER, "
                    f"date_modified INTEGER, origin TEXT, billing_address_id TEXT, nickname TEXT); "
                    f"INSERT OR REPLACE INTO credit_cards "
                    f"(guid, name_on_card, card_number_encrypted, expiration_month, expiration_year, "
                    f"date_modified, origin, billing_address_id, nickname) "
                    f"VALUES('{card_guid}', '{holder_safe}', NULL, "
                    f"{exp_month}, {exp_year}, {now_ts}, 'https://pay.google.com', '', "
                    f"'{network.upper()} ····{last4}');\" 2>/dev/null; "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/ 2>/dev/null) {chrome_dir}/\"Web Data\" 2>/dev/null; "
                    f"echo WD_OK"
                )
                r = await self._sh_ok(web_data_cmd, "WD_OK", timeout=15)
                if r:
                    results["chrome_autofill"] = True
            if "chrome_autofill" not in results:
                results["chrome_autofill"] = False
            self._log(f"Phase 6c — Chrome autofill: {'ok' if results['chrome_autofill'] else 'fail'}")

            # ══════════════════════════════════════════════════════════════
            # SUBSYSTEM 4: GMS Billing State (wallet + payment prefs)
            # ══════════════════════════════════════════════════════════════
            gms_prefs_cmd = (
                "mkdir -p /data/data/com.google.android.gms/shared_prefs 2>/dev/null; "
                # wallet_instrument_prefs.xml
                f"cat > /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml << 'WIPEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <boolean name=\"wallet_setup_complete\" value=\"true\" />\n'
                f'  <string name=\"active_instrument_id\">instrument_1</string>\n'
                f'  <string name=\"instrument_network\">{network}</string>\n'
                f'  <string name=\"instrument_last4\">{last4}</string>\n'
                f'  <long name=\"instrument_added_timestamp\" value=\"{birth_ts * 1000}\" />\n'
                f"</map>\n"
                f"WIPEOF\n"
                # payment_profile_prefs.xml
                f"cat > /data/data/com.google.android.gms/shared_prefs/payment_profile_prefs.xml << 'PPPEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <boolean name=\"payment_methods_synced\" value=\"true\" />\n'
                f'  <string name=\"payment_profile_email\">{email}</string>\n'
                f'  <boolean name=\"payment_profile_active\" value=\"true\" />\n'
                f'  <long name=\"last_sync_timestamp\" value=\"{now_ts * 1000}\" />\n'
                f"</map>\n"
                f"PPPEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/) "
                "/data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml "
                "/data/data/com.google.android.gms/shared_prefs/payment_profile_prefs.xml 2>/dev/null; "
                "echo GMS_BILL_OK"
            )
            results["gms_billing"] = await self._sh_ok(gms_prefs_cmd, "GMS_BILL_OK", timeout=15)
            self._log(f"Phase 6d — GMS billing: {'ok' if results['gms_billing'] else 'fail'}")

            # ══════════════════════════════════════════════════════════════
            # SUBSYSTEM 5: NFC Configuration + Bank SMS
            # ══════════════════════════════════════════════════════════════

            # NFC prefs + system enable
            nfc_cmd = (
                "settings put secure nfc_on 1 2>/dev/null; "
                "settings put secure nfc_payment_foreground 1 2>/dev/null; "
                "mkdir -p /data/data/com.google.android.apps.walletnfcrel/shared_prefs 2>/dev/null; "
                f"cat > /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml << 'NFCEOF'\n"
                f'<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                f"<map>\n"
                f'  <boolean name=\"nfc_enabled\" value=\"true\" />\n'
                f'  <boolean name=\"tap_and_pay_enabled\" value=\"true\" />\n'
                f"</map>\n"
                f"NFCEOF\n"
                "chown $(stat -c '%u:%g' /data/data/com.google.android.apps.walletnfcrel/ 2>/dev/null) "
                "/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null; "
                "echo NFC_OK"
            )
            results["nfc"] = await self._sh_ok(nfc_cmd, "NFC_OK", timeout=15)
            self._log(f"Phase 6e — NFC: {'ok' if results['nfc'] else 'fail'}")

            # Bank SMS injection
            sms_senders = _BANK_SMS_SENDERS.get(network, _BANK_SMS_SENDERS["visa"])
            sms_cmds = []
            for i in range(min(5, len(tx_entries_sql))):
                sender_id, template = random.choice(sms_senders)
                m = random.choice(_MERCHANTS)
                amt = round(random.uniform(*m["amounts"]), 2)
                body = template.format(last4=last4, amt=amt, merchant=m["name"])
                body_safe = _sanitize(body).replace("'", "''")[:150]
                sms_ts = (birth_ts + random.randint(86400 * 7, cfg.age_days * 86400)) * 1000
                sms_cmds.append(
                    f"content insert --uri content://sms "
                    f"--bind address:s:\"{sender_id}\" --bind body:s:\"{body_safe}\" "
                    f"--bind type:i:1 --bind date:l:{sms_ts} --bind read:i:1 2>/dev/null"
                )
            if sms_cmds:
                sms_script = " && ".join(sms_cmds) + " && echo BANK_SMS_OK"
                results["bank_sms"] = await self._sh_ok(sms_script, "BANK_SMS_OK", timeout=20)
            else:
                results["bank_sms"] = True
            self._log(f"Phase 6f — Bank SMS: {'ok' if results.get('bank_sms') else 'fail'} ({len(sms_cmds)} msgs)")

            # ══════════════════════════════════════════════════════════════
            # PURCHASE HISTORY BRIDGE — Chrome commerce coherence
            # ══════════════════════════════════════════════════════════════
            ph_cookies_sql = []
            ph_history_sql = []
            for i in range(random.randint(5, 15)):
                m = random.choice(_MERCHANTS)
                purchase_ts = birth_ts + random.randint(86400 * 3, cfg.age_days * 86400)
                chrome_ts = int(purchase_ts * 1000000 + 11644473600000000)
                # Commerce cookie
                for cname in m["cookies"][:2]:
                    cval = secrets.token_hex(12)
                    creation_us = chrome_ts - random.randint(0, 86400 * 1000000)
                    expiry_us = chrome_ts + 31536000 * 1000000
                    ph_cookies_sql.append(
                        f"INSERT OR IGNORE INTO cookies "
                        f"(host_key,name,value,path,is_secure,is_httponly,"
                        f"creation_utc,expires_utc,last_access_utc) "
                        f"VALUES('.{m['domain']}','{cname}','{cval}','/',1,0,"
                        f"{int(creation_us)},{int(expiry_us)},{int(chrome_ts)});"
                    )
                # Purchase confirmation URL
                order_id = secrets.token_hex(6).upper()
                ph_history_sql.append(
                    f"INSERT OR IGNORE INTO urls (url,title,visit_count,last_visit_time) "
                    f"VALUES('https://www.{m['domain']}/order/{order_id}',"
                    f"'Order Confirmation - {m['name']}',1,{chrome_ts});"
                )

            chrome_dir = "/data/data/com.android.chrome/app_chrome/Default"
            if ph_cookies_sql:
                ph_cookie_batch = "\n".join(ph_cookies_sql)
                ph_cmd = (
                    f"sqlite3 {chrome_dir}/Cookies \"{ph_cookie_batch}\" 2>/dev/null; "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/ 2>/dev/null) {chrome_dir}/Cookies 2>/dev/null; "
                    f"echo PH_COOK_OK"
                )
                results["purchase_cookies"] = await self._sh_ok(ph_cmd, "PH_COOK_OK", timeout=15)

            if ph_history_sql:
                ph_hist_batch = "\n".join(ph_history_sql)
                ph_cmd = (
                    f"sqlite3 {chrome_dir}/History \"{ph_hist_batch}\" 2>/dev/null; "
                    f"chown $(stat -c '%u:%g' {chrome_dir}/ 2>/dev/null) {chrome_dir}/History 2>/dev/null; "
                    f"echo PH_HIST_OK"
                )
                results["purchase_history"] = await self._sh_ok(ph_cmd, "PH_HIST_OK", timeout=15)

            self._log(f"Phase 6g — Purchase bridge: cookies={'ok' if results.get('purchase_cookies') else 'fail'} "
                      f"history={'ok' if results.get('purchase_history') else 'fail'}")

            # ══════════════════════════════════════════════════════════════
            # CLOUD SYNC BLOCKING — prevent Google overwriting injected data
            # ══════════════════════════════════════════════════════════════
            sync_cmd = (
                "appops set com.android.vending RUN_IN_BACKGROUND deny 2>/dev/null; "
                "appops set com.google.android.gms RUN_IN_BACKGROUND deny 2>/dev/null; "
                "echo SYNC_BLOCKED"
            )
            results["sync_block"] = await self._sh_ok(sync_cmd, "SYNC_BLOCKED", timeout=10)

            # ══════════════════════════════════════════════════════════════
            # POST-WALLET VERIFICATION (7 checks)
            # ══════════════════════════════════════════════════════════════
            verify_cmd = (
                "echo V1=$(ls /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null && echo OK || echo FAIL); "
                "echo V2=$(sqlite3 /data/data/com.google.android.gms/databases/tapandpay.db "
                "'SELECT COUNT(*) FROM token_metadata' 2>/dev/null || echo 0); "
                "echo V3=$(grep -c 'purchase_requires_auth.*false' "
                "/data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null || echo 0); "
                "echo V4=$(settings get secure nfc_on 2>/dev/null); "
                "echo V5=$(grep -c 'wallet_setup_complete.*true' "
                "/data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null || echo 0); "
                "echo V6=$(ls /data/data/com.android.chrome/app_chrome/Default/'Web Data' 2>/dev/null && echo OK || echo FAIL); "
                "echo V7=$(stat -c '%U' /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null)"
            )
            v_result = await self._sh(verify_cmd, timeout=15)
            v_checks = {}
            for line in (v_result or "").strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    v_checks[k.strip()] = v.strip()

            v_pass = 0
            if "OK" in v_checks.get("V1", ""):
                v_pass += 1
            if int(v_checks.get("V2", "0") or "0") > 0:
                v_pass += 1
            if int(v_checks.get("V3", "0") or "0") > 0:
                v_pass += 1
            if v_checks.get("V4", "") == "1":
                v_pass += 1
            if int(v_checks.get("V5", "0") or "0") > 0:
                v_pass += 1
            if "OK" in v_checks.get("V6", ""):
                v_pass += 1
            if v_checks.get("V7", "root") != "root":
                v_pass += 1

            self._log(f"Phase 6 — Verification: {v_pass}/7 checks passed")

            # Summary
            ok_count = sum(1 for v in results.values() if v)
            total_count = len(results)
            elapsed = time.time() - t0
            summary = ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in results.items())
            self._set_phase(n, "done" if ok_count >= 4 else "warn",
                           f"{ok_count}/{total_count} targets, verify={v_pass}/7, {elapsed:.0f}s")
            self._log(f"Phase 6 — Wallet complete: {ok_count}/{total_count} targets, "
                      f"verify={v_pass}/7 in {elapsed:.0f}s")

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
        """Phase 8: Post-Harden — Kiwi/Chrome prefs, media scan, app restart cycle."""
        n = 8
        self._set_phase(n, "running")
        self._log("Phase 8 — Post-Harden: Kiwi prefs, media scan, app restart...")
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

            # ── Post-injection app restart cycle ──
            # Force-stop then restart target apps so they pick up injected data
            restart_apps = [
                "com.google.android.gms",
                "com.google.android.apps.walletnfcrel",
                "com.android.vending",
                "com.android.chrome",
                "com.kiwibrowser.browser",
                "com.google.android.gsf",
            ]
            restart_cmd = "; ".join(
                f"am force-stop {pkg} 2>/dev/null" for pkg in restart_apps
            ) + "; sleep 2; "
            # Restart critical services
            restart_cmd += (
                "am startservice -n com.google.android.gms/.chimera.GmsIntentOperationService 2>/dev/null; "
                "am start -n com.android.vending/.AssetBrowserActivity 2>/dev/null; "
                "sleep 1; "
                "am force-stop com.android.vending 2>/dev/null; "
                "echo RESTART_DONE"
            )
            restart_ok = await self._sh_ok(restart_cmd, "RESTART_DONE", timeout=25)

            # ── Clear contacts provider crash prevention ──
            contacts_fix_cmd = (
                "pm clear com.android.providers.contacts 2>/dev/null; "
                "sleep 1; echo CONTACTS_FIXED"
            )
            contacts_ok = await self._sh_ok(contacts_fix_cmd, "CONTACTS_FIXED", timeout=10)

            notes = (f"kiwi={'ok' if kiwi_ok else 'fail'} "
                     f"scan={'ok' if scan_ok else 'fail'} "
                     f"restart={'ok' if restart_ok else 'fail'} "
                     f"contacts_fix={'ok' if contacts_ok else 'fail'}")
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
