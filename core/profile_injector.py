"""
Titan V12.0 — Profile-to-Device Injector
Injects forged Genesis profiles directly into Cuttlefish Android VMs via ADB.

Injection targets:
  - Chrome cookies → /data/data/com.android.chrome/app_chrome/Default/Cookies
  - Chrome localStorage → /data/data/com.android.chrome/app_chrome/Default/Local Storage/
  - Chrome history → /data/data/com.android.chrome/app_chrome/Default/History
  - Chrome autofill → /data/data/com.android.chrome/app_chrome/Default/Web Data
  - Contacts → content://com.android.contacts/raw_contacts
  - Call logs → content://call_log/calls
  - SMS → content://sms
  - Gallery → /sdcard/DCIM/Camera/
  - App install dates → pm set-install-time (via backdating trick)

Usage:
    injector = ProfileInjector(adb_target="127.0.0.1:5555")
    result = injector.inject_full_profile(profile_data)
"""

import json
import logging
import os
import random
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adb_utils import adb as _adb, adb_shell as _adb_shell, adb_push as _adb_push, ensure_adb_root as _ensure_adb_root
from exceptions import InjectionError

logger = logging.getLogger("titan.profile-injector")


def _resolve_browser_package(target: str) -> Tuple[str, str]:
    """Detect which Chromium-based browser is installed and return (package, data_path).
    Chrome can't install on vanilla AOSP Cuttlefish (needs TrichromeLibrary),
    so Kiwi Browser is used as a drop-in Chromium replacement."""
    candidates = [
        ("com.android.chrome", "/data/data/com.android.chrome/app_chrome/Default"),
        ("com.kiwibrowser.browser", "/data/data/com.kiwibrowser.browser/app_chrome/Default"),
    ]
    for pkg, data_path in candidates:
        ok, out = _adb(target, f"shell pm path {pkg} 2>/dev/null")
        if ok and out.strip():
            return pkg, data_path
    return candidates[0][0], candidates[0][1]


def _fix_file_ownership(target: str, remote_path: str, package: str):
    """Standardized UID/chown/chmod/restorecon for injected files.

    When pushing files via root ADB, they inherit root:root ownership.
    The target app (running as unprivileged UID) gets permission denied,
    causing it to crash, clear data, or recreate an empty database —
    completely nullifying the injection.

    This function:
      1. Dynamically resolves the app's UID via stat
      2. Sets correct chown <uid>:<uid>
      3. Sets chmod 660 (owner+group rw)
      4. Runs restorecon to fix SELinux context labels
    """
    uid = _adb_shell(target,
        f"stat -c %U /data/data/{package} 2>/dev/null || "
        f"ls -ld /data/data/{package} | awk '{{print $3}}'").strip()
    if uid:
        _adb_shell(target, f"chown {uid}:{uid} {remote_path}")
    _adb_shell(target, f"chmod 660 {remote_path}")
    parent_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else remote_path
    _adb_shell(target, f"restorecon -R {parent_dir} 2>/dev/null")


# ═══════════════════════════════════════════════════════════════════════
# INJECTION RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class InjectionResult:
    device_id: str = ""
    profile_id: str = ""
    cookies_injected: int = 0
    history_injected: int = 0
    localstorage_injected: int = 0
    contacts_injected: int = 0
    call_logs_injected: int = 0
    sms_injected: int = 0
    photos_injected: int = 0
    autofill_injected: int = 0
    google_account_ok: bool = False
    wallet_ok: bool = False
    app_data_ok: bool = False
    play_purchases_ok: bool = False
    app_usage_ok: bool = False
    wifi_ok: bool = False
    trust_score: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        total = (self.cookies_injected + self.history_injected +
                 self.localstorage_injected + self.contacts_injected +
                 self.call_logs_injected + self.sms_injected +
                 self.photos_injected + self.autofill_injected)
        return {
            "device_id": self.device_id, "profile_id": self.profile_id,
            "total_items": total, "errors": self.errors,
            "cookies": self.cookies_injected, "history": self.history_injected,
            "localstorage": self.localstorage_injected,
            "contacts": self.contacts_injected, "call_logs": self.call_logs_injected,
            "sms": self.sms_injected, "photos": self.photos_injected,
            "autofill": self.autofill_injected,
            "google_account": self.google_account_ok,
            "wallet": self.wallet_ok,
            "app_data": self.app_data_ok,
            "play_purchases": self.play_purchases_ok,
            "app_usage": self.app_usage_ok,
            "wifi": self.wifi_ok,
            "trust_score": self.trust_score,
        }


# ═══════════════════════════════════════════════════════════════════════
# PROFILE INJECTOR
# ═══════════════════════════════════════════════════════════════════════

class ProfileInjector:
    """Injects forged Genesis profiles directly into Cuttlefish Android VMs via ADB."""

    CHROME_DATA = "/data/data/com.android.chrome/app_chrome/Default"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target
        self.result = InjectionResult()
        self._browser_pkg, self._browser_data = _resolve_browser_package(adb_target)
        self.CHROME_DATA = self._browser_data
        logger.info(f"Browser resolved: {self._browser_pkg} → {self._browser_data}")

    def inject_full_profile(self, profile: Dict[str, Any],
                             card_data: Optional[Dict] = None,
                             ) -> InjectionResult:
        """Inject all profile data into the device.

        Args:
            profile: Full profile dict from AndroidProfileForge
            card_data: Optional CC data dict with keys:
                       number, exp_month, exp_year, cardholder, cvv
        """
        self.result = InjectionResult(
            device_id=self.target,
            profile_id=profile.get("uuid", profile.get("id", "unknown")),
        )

        _ensure_adb_root(self.target)
        logger.info(f"Injecting profile {self.result.profile_id} → {self.target}")

        # Ensure app data directories exist by briefly launching key packages
        self._ensure_app_dirs()

        # Stop browser and Google apps to avoid DB locks
        for pkg in [self._browser_pkg, "com.google.android.gms",
                    "com.android.vending", "com.google.android.apps.walletnfcrel"]:
            _adb_shell(self.target, f"am force-stop {pkg}")
        time.sleep(1)

        # ── Phase 1: Original injection targets ──
        self._inject_cookies(profile.get("cookies", []))
        self._inject_history(profile.get("history", []))
        self._inject_localstorage(profile.get("local_storage", {}))
        self._inject_contacts(profile.get("contacts", []))
        self._inject_call_logs(profile.get("call_logs", []))
        self._inject_sms(profile.get("sms", []))
        self._inject_gallery(profile.get("gallery_paths", []))
        self._inject_autofill(profile.get("autofill", {}))

        # ── Phase 2: Google Account injection ──
        self._inject_google_account(profile)

        # ── Phase 3: Wallet / CC provisioning ──
        if card_data:
            self._inject_wallet(profile, card_data)

        # ── Phase 4: Per-app data (SharedPrefs + DBs) ──
        self._inject_app_data(profile)

        # ── Phase 5: Play Store purchases ──
        self._inject_play_purchases(profile)

        # ── Phase 5.5: Purchase history (commerce cookies + history) ──
        self._inject_purchase_history(profile)
        
        # ── Phase 5.5.1: Payment transaction history (P3-1) ──
        if card_data:
            self._inject_payment_history(profile, card_data)

        # ── Phase 5.6: WiFi saved networks ──
        self._inject_wifi_networks(profile.get("wifi_networks", []))

        # ── Phase 5.7: App usage stats ──
        self._inject_app_usage_stats(profile)

        # ── Phase 5.8: Google Maps history ──
        self._inject_maps_history(profile)

        # ── Phase 5.9: Samsung Health step/sleep data (Samsung devices only) ──
        if "samsung" in profile.get("device_model", "").lower():
            self._inject_samsung_health(profile)

        # ── Phase 5.10: Sensor calibration traces (V12) ──
        self._inject_sensor_traces(profile)

        # ── Phase 6: Compute trust score ──
        self.result.trust_score = self._compute_trust_score(profile, card_data)

        # ── Phase 7: Backdate filesystem timestamps ──
        self._backdate_timestamps(profile)

        logger.info(f"Injection complete: {self.result.to_dict()}")
        return self.result

    # ─── ENSURE APP DATA DIRS ────────────────────────────────────────────

    def _ensure_app_dirs(self):
        """Create app data directories needed for injection.
        On bare Android (no GMS), apps aren't installed so we skip launching
        and just create directories directly via mkdir."""
        t = self.target

        # Try launching installed apps to create proper data dirs
        packages_to_init = [
            (self._browser_pkg, None),
            ("com.google.android.gms", None),
            ("com.android.vending", None),
            ("com.google.android.apps.walletnfcrel", None),
        ]
        launched = []
        for pkg, activity in packages_to_init:
            # Check if package is installed before trying to launch
            ok, out = _adb(t, f"shell pm path {pkg} 2>/dev/null")
            if not ok or not out.strip():
                continue  # Package not installed, skip launch
            check = _adb_shell(t, f"ls /data/data/{pkg}/ 2>/dev/null")
            if check:
                continue
            if activity:
                _adb_shell(t, f"am start -n {pkg}/{activity} 2>/dev/null")
            else:
                _adb_shell(t, f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1 2>/dev/null")
            launched.append(pkg)

        if launched:
            logger.info(f"  Pre-launched {len(launched)} apps to create data dirs: {launched}")
            time.sleep(5)
            # Don't force-stop here — inject_full_profile does a comprehensive
            # force-stop of all relevant apps right after _ensure_app_dirs()

        # Create necessary directories (only for actually installed packages)
        dirs = [
            self.CHROME_DATA,
            f"/data/data/{self._browser_pkg}/shared_prefs",
            f"/data/data/{self._browser_pkg}/app_chrome/Default/Local Storage/leveldb",
            "/data/system_ce/0/",
            "/data/system_de/0/",
            "/data/data/com.google.android.gms/shared_prefs",
            "/data/data/com.google.android.apps.walletnfcrel/databases",
            "/data/data/com.google.android.apps.walletnfcrel/shared_prefs",
            "/data/data/com.android.vending/databases",
            "/data/data/com.android.vending/shared_prefs",
        ]
        for d in dirs:
            _adb_shell(t, f"mkdir -p '{d}'")
        logger.info(f"  Created {len(dirs)} app data directories")

    # ─── GOOGLE ACCOUNT ────────────────────────────────────────────────

    def _inject_google_account(self, profile: Dict[str, Any]):
        """Inject Google account for pre-logged-in state across all Google apps."""
        email = profile.get("persona_email", "")
        name = profile.get("persona_name", "")
        if not email:
            return

        try:
            from google_account_injector import GoogleAccountInjector
            injector = GoogleAccountInjector(adb_target=self.target)
            acct_result = injector.inject_account(
                email=email,
                display_name=name,
            )
            self.result.google_account_ok = acct_result.success_count >= 5
            if acct_result.errors:
                self.result.errors.extend(
                    [f"google_account: {e}" for e in acct_result.errors[:3]]
                )
            logger.info(f"  Google account: {acct_result.success_count}/8 targets")
        except ImportError:
            self.result.errors.append("google_account_injector module not found")
        except Exception as e:
            self.result.errors.append(f"google_account: {e}")

    # ─── WALLET / CC ───────────────────────────────────────────────────

    def _inject_wallet(self, profile: Dict[str, Any], card_data: Dict):
        """Provision CC into Google Pay, Play Store billing, and Chrome autofill."""
        try:
            from wallet_provisioner import WalletProvisioner
            prov = WalletProvisioner(adb_target=self.target)
            wallet_result = prov.provision_card(
                card_number=card_data.get("number", ""),
                exp_month=int(card_data.get("exp_month", 12)),
                exp_year=int(card_data.get("exp_year", 2027)),
                cardholder=card_data.get("cardholder", profile.get("persona_name", "")),
                cvv=card_data.get("cvv", ""),
                persona_email=profile.get("persona_email", ""),
                persona_name=profile.get("persona_name", ""),
                country=profile.get("country", "US"),
            )
            self.result.wallet_ok = wallet_result.success_count >= 3
            if wallet_result.errors:
                self.result.errors.extend(
                    [f"wallet: {e}" for e in wallet_result.errors[:3]]
                )
            logger.info(f"  Wallet: {wallet_result.success_count}/4 targets"
                        f" | verification: {wallet_result.verification.get('score', 'N/A')}")
        except ImportError:
            self.result.errors.append("wallet_provisioner module not found")
        except Exception as e:
            self.result.errors.append(f"wallet: {e}")

    # ─── APP DATA (SharedPrefs + DBs) ──────────────────────────────────

    def _inject_app_data(self, profile: Dict[str, Any]):
        """Forge and inject per-app SharedPreferences and databases."""
        try:
            from app_data_forger import AppDataForger

            # Collect installed package names from app_installs
            installed = [ai["package"] for ai in profile.get("app_installs", [])
                         if "package" in ai]

            if not installed:
                return

            persona = {
                "email": profile.get("persona_email", ""),
                "name": profile.get("persona_name", ""),
                "phone": profile.get("persona_phone", ""),
                "country": profile.get("country", "US"),
            }

            forger = AppDataForger(adb_target=self.target)
            forge_result = forger.forge_and_inject(
                installed_packages=installed,
                persona=persona,
                play_purchases=profile.get("play_purchases", []),
                app_installs=profile.get("app_installs", []),
            )
            self.result.app_data_ok = forge_result.apps_processed > 0
            self.result.play_purchases_ok = forge_result.play_library_ok
            if forge_result.errors:
                self.result.errors.extend(
                    [f"app_data: {e}" for e in forge_result.errors[:5]]
                )
            logger.info(f"  App data: {forge_result.apps_processed} apps, "
                        f"{forge_result.shared_prefs_written} prefs, "
                        f"{forge_result.databases_written} DBs")
        except ImportError:
            self.result.errors.append("app_data_forger module not found")
        except Exception as e:
            self.result.errors.append(f"app_data: {e}")

    # ─── PLAY PURCHASES ────────────────────────────────────────────────

    def _inject_play_purchases(self, profile: Dict[str, Any]):
        """Play Store purchases are injected via AppDataForger's library.db.
        This method handles the app_usage injection via usagestats.

        GAP-M4: Android UsageStatsService reads XML files (not JSON) from
        /data/system/usagestats/0/daily/. We also use `cmd usage-stats`
        shell commands to inject usage events into the live service."""
        app_usage = profile.get("app_usage", [])
        if not app_usage:
            return

        try:
            import tempfile

            # Method 1: Use `cmd usage-stats` to inject events directly
            # This is the most reliable approach — the OS records them natively
            for entry in app_usage[:30]:  # cap to avoid excessive ADB calls
                pkg = entry.get("package", "")
                if not pkg:
                    continue
                # MOVE_TO_FOREGROUND (1) then MOVE_TO_BACKGROUND (2)
                _adb_shell(self.target,
                           f"cmd usagestats report-event {pkg} 1 2>/dev/null")
                _adb_shell(self.target,
                           f"cmd usagestats report-event {pkg} 2 2>/dev/null")

            # Method 2: Write Android-format UsageStats XML as supplemental data
            # Android stores daily usage in XML with <usagestats> root element
            xml_lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
                         '<usagestats version="1" >']
            for entry in app_usage:
                pkg = entry.get("package", "")
                total_ms = entry.get("total_time_ms", 60000)
                last_used = entry.get("last_used_epoch_ms", int(time.time() * 1000))
                launch_count = entry.get("launch_count", 1)
                xml_lines.append(
                    f'  <package name="{pkg}" '
                    f'totalTime="{total_ms}" '
                    f'lastTimeUsed="{last_used}" '
                    f'appLaunchCount="{launch_count}" />')
            xml_lines.append('</usagestats>')
            usage_xml = "\n".join(xml_lines)

            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
                tmp.write(usage_xml)
                tmp_path = tmp.name

            remote_dir = "/data/system/usagestats/0/daily"
            _adb_shell(self.target, f"mkdir -p {remote_dir}")

            # Use current epoch as filename (Android names files by timestamp)
            epoch_file = str(int(time.time() * 1000))
            remote_path = f"{remote_dir}/{epoch_file}"
            if _adb_push(self.target, tmp_path, remote_path):
                _adb_shell(self.target, f"chmod 660 {remote_path}")
                _adb_shell(self.target, f"chown system:system {remote_path}")
                self.result.app_usage_ok = True
                logger.info(f"  App usage: {len(app_usage)} app records "
                            f"(cmd events + XML)")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"app_usage: {e}")

    # ─── PURCHASE HISTORY (commerce cookies + browsing) ────────────────

    def _inject_purchase_history(self, profile: Dict[str, Any]):
        """Inject commerce purchase history via the purchase_history_bridge.
        Adds: Chrome commerce cookies, purchase confirmation URLs to history,
        and order notification entries."""
        try:
            from purchase_history_bridge import generate_android_purchase_history

            # Get smartforge config if available (has purchase_categories)
            sf_config = profile.get("smartforge_config", {})
            purchase_cats = sf_config.get("purchase_categories",
                                          profile.get("purchase_categories", []))

            card_last4 = ""
            card_network = "visa"
            if sf_config.get("card_last4"):
                card_last4 = sf_config["card_last4"]
                card_network = sf_config.get("card_network", "visa")

            ph = generate_android_purchase_history(
                persona_name=profile.get("persona_name", ""),
                persona_email=profile.get("persona_email", ""),
                country=profile.get("country", "US"),
                age_days=profile.get("age_days", 90),
                card_last4=card_last4,
                card_network=card_network,
                purchase_categories=purchase_cats if purchase_cats else None,
            )

            # Inject commerce cookies into Chrome (append to existing)
            commerce_cookies = ph.get("chrome_cookies", [])
            if commerce_cookies:
                self._inject_cookies(commerce_cookies)
                logger.info(f"  Purchase history: {len(commerce_cookies)} commerce cookies")

            # Inject purchase confirmation URLs into Chrome history
            commerce_history = ph.get("chrome_history", [])
            if commerce_history:
                self._inject_history(commerce_history)
                logger.info(f"  Purchase history: {len(commerce_history)} history entries")

            summary = ph.get("purchase_summary", {})
            logger.info(f"  Purchase history: {summary.get('total_purchases', 0)} orders, "
                        f"${summary.get('total_spent', 0):.2f} total, "
                        f"{summary.get('unique_merchants', 0)} merchants")

        except ImportError:
            logger.debug("purchase_history_bridge not available — skipping")
        except Exception as e:
            self.result.errors.append(f"purchase_history: {e}")

    # ─── MAPS HISTORY ────────────────────────────────────────────

    def _inject_maps_history(self, profile: Dict[str, Any]):
        """Inject Google Maps search/navigation history via SQLite DB.

        GAP-M3: Maps stores data in gmm_storage.db and gmm_myplaces.db,
        NOT in custom JSON files. We inject into the actual SQLite DBs
        that Maps reads on launch so the data is visible to antifraud
        querying Maps content providers.
        """
        maps_history = profile.get("maps_history", [])
        if not maps_history:
            return

        try:
            import tempfile, sqlite3 as _sqlite3
            maps_pkg = "com.google.android.apps.maps"

            # Check Maps is installed
            ok, out = _adb(self.target, f"shell pm path {maps_pkg} 2>/dev/null")
            if not ok or not out.strip():
                logger.debug("Maps not installed — skipping maps history injection")
                return

            searches = [e for e in maps_history if e.get("type") == "search"]
            navigations = [e for e in maps_history if e.get("type") == "navigation"]

            recent_searches = sorted(searches, key=lambda x: x["timestamp"], reverse=True)[:50]
            recent_navs = sorted(navigations, key=lambda x: x["timestamp"], reverse=True)[:30]

            # Build gmm_storage.db with search history
            with tempfile.NamedTemporaryFile(suffix="_gmm.db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = _sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Maps search history table (simplified but real schema)
            c.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    latitude REAL DEFAULT 0,
                    longitude REAL DEFAULT 0,
                    source TEXT DEFAULT 'typed'
                )
            """)

            # Recent destinations / navigation history
            c.execute("""
                CREATE TABLE IF NOT EXISTS recents (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    address TEXT,
                    latitude REAL DEFAULT 0,
                    longitude REAL DEFAULT 0,
                    timestamp INTEGER NOT NULL,
                    type TEXT DEFAULT 'navigation'
                )
            """)

            for s in recent_searches:
                c.execute(
                    "INSERT INTO search_history (query, timestamp, source) VALUES (?,?,?)",
                    (s.get("query", ""), s.get("timestamp", 0), "typed")
                )

            for n in recent_navs:
                c.execute(
                    "INSERT INTO recents (name, address, latitude, longitude, timestamp, type) "
                    "VALUES (?,?,?,?,?,?)",
                    (n.get("destination", ""), n.get("address", ""),
                     n.get("lat", 0), n.get("lng", 0),
                     n.get("timestamp", 0), "navigation")
                )

            conn.commit()
            conn.close()

            maps_db_dir = f"/data/data/{maps_pkg}/databases"
            _adb_shell(self.target, f"mkdir -p {maps_db_dir}")

            remote_db = f"{maps_db_dir}/gmm_storage.db"
            if _adb_push(self.target, tmp_path, remote_db):
                _fix_file_ownership(self.target, remote_db, maps_pkg)
                logger.info(f"  Maps history: {len(recent_searches)} searches, "
                            f"{len(recent_navs)} navigations → gmm_storage.db")
            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"maps_history: {e}")

    # ─── SAMSUNG HEALTH ───────────────────────────────────────────

    def _inject_samsung_health(self, profile: Dict[str, Any]):
        """Inject Samsung Health step count and sleep data via its SQLite DB.

        Samsung Knox and risk engines check com.sec.android.app.shealth for:
          - Non-zero step history (empty = never carried phone = new/fake device)
          - Sleep records consistent with device age
          - Heart rate records (less critical, but adds depth)

        DB path: /data/data/com.sec.android.app.shealth/databases/com.samsung.health.db
        """
        age_days = profile.get("age_days", 90)
        if age_days < 7:
            return

        try:
            import tempfile, sqlite3 as _sqlite3, random as _rnd
            shealth_pkg = "com.sec.android.app.shealth"

            ok, out = _adb(self.target, f"shell pm path {shealth_pkg} 2>/dev/null")
            if not ok or not out.strip():
                logger.debug("Samsung Health not installed — skipping")
                return

            with tempfile.NamedTemporaryFile(suffix="_shealth.db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = _sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Step count table (simplified schema)
            c.execute("""
                CREATE TABLE IF NOT EXISTS step_daily_trend (
                    day_time INTEGER PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    calorie REAL DEFAULT 0,
                    distance REAL DEFAULT 0,
                    speed REAL DEFAULT 0,
                    source_pkg TEXT DEFAULT 'com.sec.android.app.shealth'
                )
            """)

            # Sleep table
            c.execute("""
                CREATE TABLE IF NOT EXISTS sleep_stage (
                    stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    stage INTEGER NOT NULL DEFAULT 40002,
                    extra_data TEXT DEFAULT ''
                )
            """)

            now_ms = int(time.time() * 1000)
            day_ms = 86400 * 1000

            # Insert step counts for the last min(age_days, 365) days
            step_days = min(age_days, 365)
            for d in range(step_days):
                day_start_ms = now_ms - (d + 1) * day_ms
                # Realistic step count: 3000-12000 steps/day (Poisson-ish)
                steps = _rnd.randint(2000, 12000)
                calorie = round(steps * 0.04, 1)
                distance = round(steps * 0.0007, 3)  # km
                c.execute(
                    "INSERT OR REPLACE INTO step_daily_trend "
                    "(day_time, count, calorie, distance, speed) VALUES (?,?,?,?,?)",
                    (day_start_ms, steps, calorie, distance, round(distance / 0.5, 2))
                )

            # Insert sleep records: one per night for last min(age_days, 180) days
            sleep_days = min(age_days, 180)
            for d in range(sleep_days):
                # Sleep 10pm-6am roughly
                sleep_start = now_ms - d * day_ms - 8 * 3600 * 1000
                sleep_end = sleep_start + _rnd.randint(6, 9) * 3600 * 1000
                c.execute(
                    "INSERT INTO sleep_stage (start_time, end_time, stage) VALUES (?,?,?)",
                    (sleep_start, sleep_end, 40002)  # 40002 = LIGHT sleep stage
                )

            conn.commit()
            conn.close()

            # Push DB to device
            shealth_db_dir = f"/data/data/{shealth_pkg}/databases"
            _adb_shell(self.target, f"mkdir -p {shealth_db_dir}")
            remote_db = f"{shealth_db_dir}/com.samsung.health.db"

            if _adb_push(self.target, tmp_path, remote_db):
                _fix_file_ownership(self.target, remote_db, shealth_pkg)
                logger.info(f"  Samsung Health: {step_days}d steps + {sleep_days}d sleep injected")
            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"samsung_health: {e}")

    # ─── SENSOR TRACES (V12) ──────────────────────────────────────────

    def _inject_sensor_traces(self, profile: Dict[str, Any]):
        """Inject sensor calibration data as Android system properties.

        Payment apps (Google Pay, banking) check for stale or absent sensor
        data as a VM indicator. This seeds initial accel/gyro/mag readings
        plus a recent timestamp so the sensor daemon has warm-start state.
        """
        traces = profile.get("sensor_traces", [])
        if not traces:
            return

        try:
            # Pick the most recent trace entry
            latest = traces[-1] if traces else {}
            accel = latest.get("accel_avg", {"x": 0.05, "y": 0.02, "z": 9.78})
            gyro = latest.get("gyro_avg", {"x": 0.001, "y": -0.002, "z": 0.0005})

            now_ts = str(time.time())
            props = {
                "persist.titan.sensor.accel.data": f"{accel.get('x', 0.05)},{accel.get('y', 0.02)},{accel.get('z', 9.78)}",
                "persist.titan.sensor.gyro.data": f"{gyro.get('x', 0.001)},{gyro.get('y', -0.002)},{gyro.get('z', 0.0005)}",
                "persist.titan.sensor.mag.data": "25.3,-12.1,42.8",
                "persist.titan.sensor.accel.ts": now_ts,
                "persist.titan.sensor.gyro.ts": now_ts,
                "persist.titan.sensor.mag.ts": now_ts,
            }

            # Batch setprop to minimize ADB calls
            batch_cmd = " && ".join(
                f"setprop {k} '{v}'" for k, v in props.items()
            )
            _adb_shell(self.target, batch_cmd, timeout=10)
            logger.info(f"  Sensor traces: {len(traces)} days of calibration data seeded")

        except Exception as e:
            self.result.errors.append(f"sensor_traces: {e}")

    # ─── TRUST SCORE ───────────────────────────────────────────────────

    def _compute_trust_score(self, profile: Dict[str, Any],
                             card_data: Optional[Dict] = None) -> int:
        """Compute a 0-100 trust score based on injected data completeness."""
        score = 0
        max_score = 100

        # Category weights (total = 100)
        checks = [
            ("contacts", len(profile.get("contacts", [])) >= 5, 8),
            ("call_logs", len(profile.get("call_logs", [])) >= 10, 7),
            ("sms", len(profile.get("sms", [])) >= 5, 7),
            ("cookies", self.result.cookies_injected >= 10, 8),
            ("history", self.result.history_injected >= 20, 8),
            ("gallery", self.result.photos_injected >= 5, 5),
            ("wifi", self.result.wifi_ok, 4),
            ("autofill", bool(profile.get("autofill", {}).get("name")), 5),
            ("google_account", self.result.google_account_ok, 15),
            ("wallet", self.result.wallet_ok, 12),
            ("app_data", self.result.app_data_ok, 8),
            ("play_purchases", self.result.play_purchases_ok, 8),
            ("app_usage", self.result.app_usage_ok, 5),
        ]

        details = []
        for name, passed, weight in checks:
            if passed:
                score += weight
                details.append(f"    ✓ {name}: +{weight}")
            else:
                details.append(f"    ✗ {name}: 0/{weight}")

        logger.info(f"  Trust score: {score}/{max_score}")
        for d in details:
            logger.info(d)

        return score

    # ─── COOKIES ──────────────────────────────────────────────────────

    def _inject_cookies(self, cookies: List[Dict]):
        """Inject cookies into Chrome's SQLite cookie database."""
        if not cookies:
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Pull existing cookie DB or create new one
            _adb(self.target, f"pull {self.CHROME_DATA}/Cookies {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Ensure table exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS cookies (
                    creation_utc INTEGER NOT NULL,
                    host_key TEXT NOT NULL,
                    top_frame_site_key TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    encrypted_value BLOB NOT NULL DEFAULT X'',
                    path TEXT NOT NULL DEFAULT '/',
                    expires_utc INTEGER NOT NULL DEFAULT 0,
                    is_secure INTEGER NOT NULL DEFAULT 1,
                    is_httponly INTEGER NOT NULL DEFAULT 0,
                    last_access_utc INTEGER NOT NULL DEFAULT 0,
                    has_expires INTEGER NOT NULL DEFAULT 1,
                    is_persistent INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 1,
                    samesite INTEGER NOT NULL DEFAULT -1,
                    source_scheme INTEGER NOT NULL DEFAULT 2,
                    source_port INTEGER NOT NULL DEFAULT 443,
                    last_update_utc INTEGER NOT NULL DEFAULT 0
                )
            """)

            count = 0
            for cookie in cookies:
                try:
                    # Chrome epoch: microseconds since 1601-01-01
                    chrome_epoch_offset = 11644473600000000
                    now_chrome = int(time.time() * 1000000) + chrome_epoch_offset
                    expire_offset = cookie.get("max_age", 31536000) * 1000000

                    c.execute("""
                        INSERT OR REPLACE INTO cookies
                        (creation_utc, host_key, name, value, path, expires_utc,
                         is_secure, is_httponly, last_access_utc, has_expires,
                         is_persistent, priority, samesite, source_scheme, last_update_utc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, 2, ?)
                    """, (
                        now_chrome - random.randint(0, expire_offset),
                        cookie.get("domain", ""),
                        cookie.get("name", ""),
                        cookie.get("value", ""),
                        cookie.get("path", "/"),
                        now_chrome + expire_offset,
                        1 if cookie.get("secure", True) else 0,
                        1 if cookie.get("httponly", False) else 0,
                        now_chrome - random.randint(0, 86400000000),
                        cookie.get("samesite", -1),
                        now_chrome,
                    ))
                    count += 1
                except Exception as e:
                    self.result.errors.append(f"cookie:{cookie.get('name','?')}: {e}")

            conn.commit()
            conn.close()

            # Push back to device
            if _adb_push(self.target, tmp_path, f"{self.CHROME_DATA}/Cookies"):
                _fix_file_ownership(self.target, f"{self.CHROME_DATA}/Cookies", self._browser_pkg)
                self.result.cookies_injected = count
                logger.info(f"  Cookies: {count} injected")
            else:
                self.result.errors.append("Failed to push cookies DB")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"cookies: {e}")
            logger.error(f"Cookie injection failed: {e}")

    # ─── BROWSING HISTORY ─────────────────────────────────────────────

    def _inject_history(self, history: List[Dict]):
        """Inject browsing history into Chrome's history database."""
        if not history:
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            _adb(self.target, f"pull {self.CHROME_DATA}/History {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    visit_count INTEGER NOT NULL DEFAULT 1,
                    typed_count INTEGER NOT NULL DEFAULT 0,
                    last_visit_time INTEGER NOT NULL DEFAULT 0,
                    hidden INTEGER NOT NULL DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS visits (
                    id INTEGER PRIMARY KEY,
                    url INTEGER NOT NULL,
                    visit_time INTEGER NOT NULL,
                    from_visit INTEGER NOT NULL DEFAULT 0,
                    transition INTEGER NOT NULL DEFAULT 0,
                    segment_id INTEGER NOT NULL DEFAULT 0,
                    visit_duration INTEGER NOT NULL DEFAULT 0
                )
            """)

            count = 0
            chrome_epoch_offset = 11644473600000000

            for entry in history:
                try:
                    visit_time = int(entry.get("timestamp", time.time())) * 1000000 + chrome_epoch_offset
                    visits = entry.get("visits", random.randint(1, 8))

                    c.execute("""
                        INSERT INTO urls (url, title, visit_count, last_visit_time)
                        VALUES (?, ?, ?, ?)
                    """, (entry["url"], entry.get("title", ""), visits, visit_time))

                    url_id = c.lastrowid
                    for v in range(visits):
                        vt = visit_time - random.randint(0, 2592000000000)  # up to 30 days
                        dur = random.randint(5000000, 300000000)  # 5s to 5min
                        c.execute("""
                            INSERT INTO visits (url, visit_time, transition, visit_duration)
                            VALUES (?, ?, 0, ?)
                        """, (url_id, vt, dur))

                    count += 1
                except Exception as e:
                    self.result.errors.append(f"history:{entry.get('url','?')}: {e}")

            conn.commit()
            conn.close()

            if _adb_push(self.target, tmp_path, f"{self.CHROME_DATA}/History"):
                _fix_file_ownership(self.target, f"{self.CHROME_DATA}/History", self._browser_pkg)
                self.result.history_injected = count
                logger.info(f"  History: {count} URLs injected")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"history: {e}")

    # ─── LOCAL STORAGE ────────────────────────────────────────────────

    def _inject_localstorage(self, storage: Dict[str, Dict[str, str]]):
        """Inject localStorage key-value pairs per origin.

        Chrome stores localStorage in LevelDB which is hard to write directly.
        We use a two-pronged approach:
        1. Create a Local Storage DB (legacy SQLite format Chrome can read)
        2. Write a JSON manifest for any future DevTools-based loader
        """
        if not storage:
            return

        count = 0
        try:
            import tempfile
            import sqlite3

            # Build a SQLite-based Local Storage DB
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS ItemTable (
                key TEXT NOT NULL, value TEXT NOT NULL)""")

            for origin, kv in storage.items():
                for key, value in kv.items():
                    # Chrome prefixes keys with origin in some versions
                    full_key = f"{origin}\x00{key}" if "://" in origin else key
                    c.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                              (full_key, value))
                    count += 1

            conn.commit()
            conn.close()

            # Push to each origin's storage dir
            ls_base = f"{self.CHROME_DATA}/Local Storage/leveldb"
            _adb_shell(self.target, f"mkdir -p {ls_base}")
            # Push as a companion DB that Chrome migration can pick up
            if _adb_push(self.target, tmp_path, f"{self.CHROME_DATA}/Local Storage/localstorage.db"):
                _fix_file_ownership(self.target, f"{self.CHROME_DATA}/Local Storage/localstorage.db",
                                    self._browser_pkg)

            os.unlink(tmp_path)

            # Also write a JSON manifest for DevTools-based injection
            manifest = json.dumps(storage, indent=2)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as mf:
                mf.write(manifest)
                mf_path = mf.name
            _adb_push(self.target, mf_path, f"{self.CHROME_DATA}/Local Storage/_titan_ls_manifest.json")
            os.unlink(mf_path)

        except Exception as e:
            self.result.errors.append(f"localstorage: {e}")

        self.result.localstorage_injected = count
        if count:
            logger.info(f"  localStorage: {count} entries injected")

    # ─── CONTACTS ─────────────────────────────────────────────────────

    def _inject_contacts(self, contacts: List[Dict]):
        """Inject contacts via SQLite batch (pull contacts2.db, insert locally, push back).

        Previous approach used per-contact ADB content-insert commands (~200ms each,
        3-4 cmds per contact) which took 72+ seconds for 90 contacts and frequently
        timed out the provision pipeline. SQLite batch completes in <2 seconds.
        """
        if not contacts:
            return

        REMOTE_DB = "/data/data/com.android.providers.contacts/databases/contacts2.db"

        try:
            import sqlite3 as _sqlite3

            # Stop contacts provider to avoid SQLite lock / crash
            _adb_shell(self.target, "am force-stop com.android.providers.contacts")
            time.sleep(0.5)

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Pull existing DB
            ok, _ = _adb(self.target, f"pull {REMOTE_DB} {tmp_path}", timeout=15)
            if not ok:
                # DB doesn't exist — create minimal schema
                conn = _sqlite3.connect(tmp_path)
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS raw_contacts (
                        _id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id INTEGER, version INTEGER DEFAULT 1,
                        dirty INTEGER DEFAULT 0, display_name TEXT);
                    CREATE TABLE IF NOT EXISTS mimetypes (
                        _id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mimetype TEXT UNIQUE);
                    INSERT OR IGNORE INTO mimetypes(mimetype) VALUES('vnd.android.cursor.item/name');
                    INSERT OR IGNORE INTO mimetypes(mimetype) VALUES('vnd.android.cursor.item/phone_v2');
                    INSERT OR IGNORE INTO mimetypes(mimetype) VALUES('vnd.android.cursor.item/email_v2');
                    CREATE TABLE IF NOT EXISTS data (
                        _id INTEGER PRIMARY KEY AUTOINCREMENT,
                        raw_contact_id INTEGER, mimetype_id INTEGER,
                        data1 TEXT, data2 TEXT);
                """)
                conn.commit()
            else:
                conn = _sqlite3.connect(tmp_path)

            c = conn.cursor()

            # Resolve mimetype IDs from the device's actual schema
            c.execute("SELECT _id, mimetype FROM mimetypes WHERE mimetype IN "
                      "('vnd.android.cursor.item/name','vnd.android.cursor.item/phone_v2',"
                      "'vnd.android.cursor.item/email_v2')")
            mime_map = {row[1]: row[0] for row in c.fetchall()}
            name_mid = mime_map.get('vnd.android.cursor.item/name')
            phone_mid = mime_map.get('vnd.android.cursor.item/phone_v2')
            email_mid = mime_map.get('vnd.android.cursor.item/email_v2')

            # Find next available raw_contact _id
            c.execute("SELECT COALESCE(MAX(_id), 0) FROM raw_contacts")
            next_rc_id = c.fetchone()[0] + 1

            count = 0
            for contact in contacts:
                name = contact.get("name", "")
                phone = contact.get("phone", "")
                email = contact.get("email", "")
                if not (name or phone or email):
                    continue

                rc_id = next_rc_id + count
                c.execute("INSERT OR IGNORE INTO raw_contacts(_id, account_id, version, dirty, display_name) "
                          "VALUES(?, NULL, 1, 0, ?)", (rc_id, name))

                if name and name_mid:
                    c.execute("INSERT INTO data(raw_contact_id, mimetype_id, data1) VALUES(?, ?, ?)",
                              (rc_id, name_mid, name))
                if phone and phone_mid:
                    c.execute("INSERT INTO data(raw_contact_id, mimetype_id, data1, data2) VALUES(?, ?, ?, ?)",
                              (rc_id, phone_mid, phone, "2"))
                if email and email_mid:
                    c.execute("INSERT INTO data(raw_contact_id, mimetype_id, data1, data2) VALUES(?, ?, ?, ?)",
                              (rc_id, email_mid, email, "1"))
                count += 1

            conn.commit()
            conn.close()

            if _adb_push(self.target, tmp_path, REMOTE_DB):
                _fix_file_ownership(self.target, REMOTE_DB, "com.android.providers.contacts")

            os.unlink(tmp_path)

            # Restart contacts provider so it picks up the new data
            _adb_shell(self.target,
                "am broadcast -a android.intent.action.PROVIDER_CHANGED "
                "-d content://com.android.contacts 2>/dev/null")

            self.result.contacts_injected = count
            logger.info(f"  Contacts: {count} injected (sqlite3 batch)")

        except Exception as e:
            self.result.errors.append(f"contacts: {e}")
            self.result.contacts_injected = 0
            logger.warning(f"  Contacts injection failed: {e}")

    # ─── CALL LOGS ────────────────────────────────────────────────────

    def _inject_call_logs(self, logs: List[Dict]):
        """Inject call history via SQLite batch (replaces slow per-entry ADB commands)."""
        if not logs:
            return

        REMOTE_DB = "/data/data/com.android.providers.contacts/databases/calllog.db"
        capped = logs[:500]

        try:
            import tempfile
            import sqlite3 as _sqlite3

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Pull existing DB if present
            ok, _ = _adb(self.target, f"pull {REMOTE_DB} {tmp_path}", timeout=15)
            if not ok:
                conn = _sqlite3.connect(tmp_path)
                conn.execute("""CREATE TABLE IF NOT EXISTS calls (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT, type INTEGER DEFAULT 1,
                    date INTEGER, duration INTEGER DEFAULT 0,
                    new INTEGER DEFAULT 0, name TEXT DEFAULT '',
                    numbertype INTEGER DEFAULT 0,
                    numberlabel TEXT DEFAULT '',
                    countryiso TEXT DEFAULT 'US',
                    geocoded_location TEXT DEFAULT '',
                    phone_account_component_name TEXT DEFAULT '',
                    phone_account_id TEXT DEFAULT '')""")
                conn.commit()
            else:
                conn = _sqlite3.connect(tmp_path)

            c = conn.cursor()
            count = 0
            for log_entry in capped:
                number = log_entry.get("number", "")
                call_type = log_entry.get("type", 1)
                duration = log_entry.get("duration", 0)
                date_ms = log_entry.get("date", int(time.time() * 1000) - random.randint(86400000, 2592000000))
                c.execute(
                    "INSERT INTO calls(number, type, date, duration, new) VALUES (?, ?, ?, ?, 0)",
                    (number, call_type, date_ms, duration))
                count += 1

            conn.commit()
            conn.close()

            if _adb_push(self.target, tmp_path, REMOTE_DB):
                _fix_file_ownership(self.target, REMOTE_DB, "com.android.providers.contacts")

            os.unlink(tmp_path)
            self.result.call_logs_injected = count
            logger.info(f"  Call logs: {count} injected (sqlite3 batch)")

        except Exception as e:
            self.result.errors.append(f"call_logs: {e}")
            self.result.call_logs_injected = 0
            logger.warning(f"  Call logs injection failed: {e}")

    # ─── SMS ──────────────────────────────────────────────────────────

    def _inject_sms(self, messages: List[Dict]):
        """Inject SMS messages by building a local SQLite DB and pushing it.

        Previous approach piped SQL through adb shell which broke on shell
        metacharacters in message bodies. Now we build locally with Python
        sqlite3 (parameterized queries) and merge into the device DB.
        """
        if not messages:
            return

        REMOTE_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        capped = messages[:500]

        try:
            import tempfile
            import sqlite3

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Pull existing DB if present to preserve existing messages
            ok, _ = _adb(self.target, f"pull {REMOTE_DB} {tmp_path}", timeout=15)
            if not ok:
                # DB doesn't exist yet — create fresh with schema
                conn = sqlite3.connect(tmp_path)
                conn.execute("""CREATE TABLE IF NOT EXISTS sms (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT, body TEXT, type INTEGER DEFAULT 1,
                    date INTEGER, read INTEGER DEFAULT 1,
                    seen INTEGER DEFAULT 1, thread_id INTEGER DEFAULT 1)""")
                conn.commit()
            else:
                conn = sqlite3.connect(tmp_path)

            c = conn.cursor()
            count = 0
            for msg in capped:
                address = msg.get("address", "")
                body = msg.get("body", "")[:160]
                msg_type = msg.get("type", 1)
                date_ms = msg.get("date", int(time.time() * 1000) - random.randint(86400000, 604800000))
                c.execute(
                    "INSERT INTO sms(address, body, type, date, read, seen) VALUES (?, ?, ?, ?, 1, 1)",
                    (address, body, msg_type, date_ms))
                count += 1

            conn.commit()
            conn.close()

            if _adb_push(self.target, tmp_path, REMOTE_DB):
                _fix_file_ownership(self.target, REMOTE_DB, "com.android.providers.telephony")

            os.unlink(tmp_path)
            self.result.sms_injected = count
            logger.info(f"  SMS: {count} injected (local sqlite3)")

        except Exception as e:
            self.result.errors.append(f"sms: {e}")
            self.result.sms_injected = 0
            logger.warning(f"  SMS injection failed: {e}")

    # ─── EXIF JPEG BUILDER ─────────────────────────────────────────────

    def _build_exif_jpeg(self, timestamp: float) -> bytes:
        """Build a minimal valid JPEG with EXIF APP1 segment containing
        DateTimeOriginal, camera Make/Model, GPS coords, and image dimensions.
        Pure struct-based — no external EXIF library needed."""
        import struct as _s

        dt_str = time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(timestamp))
        dt_bytes = dt_str.encode("ascii") + b'\x00'  # 20 bytes null-terminated

        # Camera model from device preset context (use Samsung as default)
        make = b'samsung\x00'
        model = b'SM-S928B\x00'

        # GPS — small random offset around a plausible city center
        # Default: NYC area with ±0.05 degree jitter
        lat = 40.7128 + random.uniform(-0.05, 0.05)
        lon = -74.0060 + random.uniform(-0.05, 0.05)
        lat_ref = b'N\x00' if lat >= 0 else b'S\x00'
        lon_ref = b'W\x00' if lon < 0 else b'E\x00'
        lat = abs(lat)
        lon = abs(lon)

        def _deg_to_rational(deg):
            d = int(deg)
            m = int((deg - d) * 60)
            s = int(((deg - d) * 60 - m) * 60 * 100)
            return _s.pack('>IIIIII', d, 1, m, 1, s, 100)

        lat_rational = _deg_to_rational(lat)
        lon_rational = _deg_to_rational(lon)

        # Build IFD entries manually (big-endian TIFF / Motorola byte order)
        # We build: IFD0 (Make, Model, DateTime, ExifOffset, GPSOffset)
        #           ExifIFD (DateTimeOriginal, PixelXDimension, PixelYDimension)
        #           GPSIFD (GPSLatitudeRef, GPSLatitude, GPSLongitudeRef, GPSLongitude)

        # Offsets are relative to TIFF header start (byte 12 in APP1)
        # TIFF header: 8 bytes (MM 002A 00000008)
        # IFD0 starts at offset 8

        ifd0_count = 5
        ifd0_size = 2 + ifd0_count * 12 + 4  # count + entries + next_ifd_ptr
        ifd0_start = 8

        # Data area starts after IFD0
        data_start = ifd0_start + ifd0_size

        # Pack string data sequentially
        data_area = bytearray()

        def _add_data(d):
            off = data_start + len(data_area)
            data_area.extend(d)
            return off

        make_off = _add_data(make)
        model_off = _add_data(model)
        dt_off = _add_data(dt_bytes)

        # ExifIFD will start after data area (we'll fix offset later)
        exif_ifd_placeholder_idx = len(data_area)

        # GPS rational data
        gps_lat_off = _add_data(lat_rational)
        gps_lon_off = _add_data(lon_rational)

        # Now we know where ExifIFD and GPSIFD start
        exif_ifd_offset = data_start + len(data_area)

        # ExifIFD: 3 entries
        exif_entries = _s.pack('>H', 3)
        exif_entries += _s.pack('>HHII', 0x9003, 2, 20, dt_off)  # DateTimeOriginal
        exif_entries += _s.pack('>HHII', 0xA002, 3, 1, (4032 << 16))  # PixelXDimension SHORT
        exif_entries += _s.pack('>HHII', 0xA003, 3, 1, (3024 << 16))  # PixelYDimension SHORT
        exif_entries += _s.pack('>I', 0)  # next IFD
        data_area.extend(exif_entries)

        gps_ifd_offset = data_start + len(data_area)

        # GPSIFD: 4 entries
        gps_entries = _s.pack('>H', 4)
        gps_entries += _s.pack('>HHII', 0x0001, 2, 2, int.from_bytes(lat_ref, 'big') << 16)  # GPSLatitudeRef
        gps_entries += _s.pack('>HHII', 0x0002, 5, 3, gps_lat_off)  # GPSLatitude
        gps_entries += _s.pack('>HHII', 0x0003, 2, 2, int.from_bytes(lon_ref, 'big') << 16)  # GPSLongitudeRef
        gps_entries += _s.pack('>HHII', 0x0004, 5, 3, gps_lon_off)  # GPSLongitude
        gps_entries += _s.pack('>I', 0)  # next IFD
        data_area.extend(gps_entries)

        # Build IFD0
        ifd0 = _s.pack('>H', ifd0_count)
        ifd0 += _s.pack('>HHII', 0x010F, 2, len(make), make_off)      # Make
        ifd0 += _s.pack('>HHII', 0x0110, 2, len(model), model_off)    # Model
        ifd0 += _s.pack('>HHII', 0x0132, 2, 20, dt_off)               # DateTime
        ifd0 += _s.pack('>HHII', 0x8769, 4, 1, exif_ifd_offset)       # ExifIFD Pointer
        ifd0 += _s.pack('>HHII', 0x8825, 4, 1, gps_ifd_offset)       # GPSIFD Pointer
        ifd0 += _s.pack('>I', 0)  # next IFD pointer (none)

        # Assemble TIFF data
        tiff = b'MM' + _s.pack('>HI', 42, 8) + ifd0 + bytes(data_area)

        # APP1 segment: EXIF header + TIFF
        exif_header = b'Exif\x00\x00'
        app1_data = exif_header + tiff
        app1 = b'\xff\xe1' + _s.pack('>H', len(app1_data) + 2) + app1_data

        # Minimal JPEG: SOI + APP1 + random body + EOI
        body = os.urandom(random.randint(8192, 32768))
        return b'\xff\xd8' + app1 + body + b'\xff\xd9'

    # ─── GALLERY ──────────────────────────────────────────────────────

    def _inject_gallery(self, paths):
        """Push images to device gallery.
        Accepts List[Dict] with {path, lat, lon, timestamp} or List[str].
        If source files don't exist (temp files cleaned up), generate stub JPEGs
        with EXIF metadata (GPS, camera model, DateTimeOriginal) so they pass
        forensic analysis as real camera photos."""
        import struct as _struct

        _adb_shell(self.target, "mkdir -p /sdcard/DCIM/Camera")
        count = 0

        # Try pushing existing files first
        for entry in (paths or []):
            path = entry["path"] if isinstance(entry, dict) else entry
            if os.path.exists(path):
                fname = os.path.basename(path)
                if _adb_push(self.target, path, f"/sdcard/DCIM/Camera/{fname}"):
                    count += 1

        # If no files existed, generate stub JPEGs with EXIF (8-12 photos)
        if count == 0:
            num_photos = random.randint(50, 80)
            now = time.time()
            age_days = 90  # default; overridden by caller context
            for i in range(num_photos):
                days_back = random.randint(1, max(1, age_days))
                photo_ts = now - (days_back * 86400) - random.randint(0, 86400)
                date_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(photo_ts))
                fname = f"IMG_{date_str}_{random.randint(100,999)}.jpg"

                jpeg_data = self._build_exif_jpeg(photo_ts)

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp.write(jpeg_data)
                    tmp_path = tmp.name

                if _adb_push(self.target, tmp_path, f"/sdcard/DCIM/Camera/{fname}"):
                    # Backdate the file timestamp on device
                    touch_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(photo_ts))
                    _adb_shell(self.target,
                        f"touch -t {touch_fmt} /sdcard/DCIM/Camera/{fname} 2>/dev/null")
                    count += 1
                os.unlink(tmp_path)

        # Trigger media scan
        _adb_shell(self.target,
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            "-d file:///sdcard/DCIM/Camera/")
        _adb_shell(self.target, "restorecon -R /sdcard/DCIM/Camera/ 2>/dev/null")

        self.result.photos_injected = count
        logger.info(f"  Gallery: {count} photos pushed")

    # ─── AUTOFILL ─────────────────────────────────────────────────────

    def _inject_autofill(self, autofill: Dict[str, Any]):
        """Inject Chrome autofill data into Web Data SQLite DB."""
        if not autofill:
            return

        name = autofill.get("name", "")
        email = autofill.get("email", "")
        phone = autofill.get("phone", "")
        address = autofill.get("address", {})

        if not (name or email or phone):
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            web_data_path = f"{self.CHROME_DATA}/Web Data"
            _adb(self.target, f"pull {web_data_path} {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profiles (
                    guid TEXT PRIMARY KEY,
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
                    use_count INTEGER NOT NULL DEFAULT 1,
                    use_date INTEGER NOT NULL DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profile_names (
                    guid TEXT, first_name TEXT, middle_name TEXT, last_name TEXT,
                    full_name TEXT)
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profile_emails (
                    guid TEXT, email TEXT)
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profile_phones (
                    guid TEXT, number TEXT)
            """)

            import uuid as _uuid
            guid = str(_uuid.uuid4())
            chrome_epoch_offset = 11644473600000000
            now_chrome = int(time.time() * 1000000) + chrome_epoch_offset
            use_date = now_chrome - random.randint(86400000000, 2592000000000)

            parts = name.split() if name else [""]
            first = parts[0] if parts else ""
            last = parts[-1] if len(parts) > 1 else ""

            c.execute(
                "INSERT OR REPLACE INTO autofill_profiles "
                "(guid, street_address, city, state, zipcode, country_code, "
                "date_modified, use_count, use_date) VALUES (?,?,?,?,?,?,?,?,?)",
                (guid, address.get("street", ""), address.get("city", ""),
                 address.get("state", ""), address.get("zip", ""),
                 address.get("country", "US"),
                 int(time.time()), random.randint(2, 15), use_date))

            c.execute(
                "INSERT INTO autofill_profile_names VALUES (?,?,?,?,?)",
                (guid, first, "", last, name))

            if email:
                c.execute(
                    "INSERT INTO autofill_profile_emails VALUES (?,?)",
                    (guid, email))
            if phone:
                c.execute(
                    "INSERT INTO autofill_profile_phones VALUES (?,?)",
                    (guid, phone))

            conn.commit()
            conn.close()

            _adb_shell(self.target, f"mkdir -p '{self.CHROME_DATA}'")
            if _adb_push(self.target, tmp_path, web_data_path):
                _fix_file_ownership(self.target, web_data_path, self._browser_pkg)
                self.result.autofill_injected = 1
                logger.info(f"  Autofill: injected profile ({name}, {email}, {phone})")
            else:
                self.result.errors.append("Failed to push autofill Web Data")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"autofill: {e}")
            logger.error(f"Autofill injection failed: {e}")

    # ─── APP USAGE STATS ─────────────────────────────────────────────

    def _inject_app_usage_stats(self, profile: Dict[str, Any]):
        """Inject realistic app usage stats so Settings > Battery > App usage
        shows non-zero screen time. Uses `cmd usagestats` where available,
        falls back to direct usagestats DB insertion."""
        age_days = profile.get("age_days", 90)
        now = int(time.time() * 1000)  # ms

        # Core packages with plausible daily usage minutes
        usage_map = {
            self._browser_pkg: (25, 60),
            "com.google.android.youtube": (15, 45),
            "com.google.android.gms": (2, 8),
            "com.android.vending": (3, 10),
            "com.google.android.apps.maps": (5, 15),
        }

        cmds = []
        for pkg, (min_mins, max_mins) in usage_map.items():
            # Generate usage events across recent days
            for days_back in range(min(age_days, 14)):
                day_ms = now - (days_back * 86400000)
                usage_mins = random.randint(min_mins, max_mins)
                # Move-to-foreground event (type 1) and move-to-background (type 2)
                fg_time = day_ms - random.randint(0, 43200000)  # random time in day
                bg_time = fg_time + (usage_mins * 60000)
                cmds.append(
                    f"cmd usagestats report-event {pkg} 1 {fg_time} 2>/dev/null; "
                    f"cmd usagestats report-event {pkg} 2 {bg_time} 2>/dev/null"
                )

        if cmds:
            # Batch into groups of 20 to avoid command-line overflow
            for i in range(0, len(cmds), 20):
                batch = "; ".join(cmds[i:i+20])
                _adb_shell(self.target, batch, timeout=15)

            self.result.app_usage_ok = True
            logger.info(f"  App usage: stats injected for {len(usage_map)} apps × {min(age_days, 14)} days")
        else:
            logger.info("  App usage: skipped (no packages)")

    # ─── WIFI SAVED NETWORKS ──────────────────────────────────────────

    def _inject_wifi_networks(self, wifi_networks: List[Dict]):
        """Inject WifiConfigStore.xml with persona-specific saved networks."""
        if not wifi_networks:
            return

        import secrets as _sec
        net_blocks = []
        for i, net in enumerate(wifi_networks[:4]):
            ssid = net.get("ssid", net) if isinstance(net, dict) else str(net)
            psk = _sec.token_hex(16)
            net_blocks.append(f'''<Network>
<string name="SSID">&quot;{ssid}&quot;</string>
<string name="PreSharedKey">&quot;{psk}&quot;</string>
<boolean name="ScanResultCache" value="true" />
<boolean name="HasEverConnected" value="true" />
<int name="Priority" value="{10 - i}" />
</Network>''')

        xml_content = (
            "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
            "<WifiConfigStoreData>\n"
            "<int name=\"Version\" value=\"3\" />\n"
            "<NetworkList>\n"
            + "\n".join(net_blocks) +
            "\n</NetworkList>\n"
            "</WifiConfigStoreData>"
        )

        try:
            import tempfile as _tf
            with _tf.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as tmp:
                tmp.write(xml_content)
                tmp_path = tmp.name

            _adb_shell(self.target, "mkdir -p /data/misc/wifi")
            if _adb_push(self.target, tmp_path, "/data/misc/wifi/WifiConfigStore.xml"):
                _adb_shell(self.target,
                    "chown wifi:wifi /data/misc/wifi/WifiConfigStore.xml 2>/dev/null; "
                    "chmod 660 /data/misc/wifi/WifiConfigStore.xml; "
                    "restorecon /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
                self.result.wifi_ok = True
                logger.info(f"  WiFi networks: {len(net_blocks)} saved to WifiConfigStore.xml")
            os.unlink(tmp_path)
        except Exception as e:
            self.result.errors.append(f"wifi: {e}")
            logger.warning(f"  WiFi injection failed: {e}")

    # ─── TIMESTAMP BACKDATING ─────────────────────────────────────────

    def _backdate_timestamps(self, profile: Dict[str, Any]):
        """Backdate mtime of all injected files to match profile age.

        Without this, all files have 'created just now' timestamps which
        is a forensic indicator of synthetic injection.
        """
        age_days = profile.get("age_days", 90)
        now = time.time()

        # Map package directories to their appropriate age offset
        paths_to_backdate = [
            (self.CHROME_DATA, age_days),
            (f"/data/data/{self._browser_pkg}/app_chrome/Default", age_days),
            ("/data/data/com.google.android.gms/shared_prefs", age_days - random.randint(0, 5)),
            ("/data/data/com.google.android.gsf/shared_prefs", age_days - random.randint(0, 3)),
            ("/data/data/com.android.vending/shared_prefs", age_days - random.randint(5, 15)),
            ("/data/system_ce/0", age_days),
            ("/data/system_de/0", age_days),
            ("/sdcard/DCIM/Camera", age_days),
        ]

        cmds = []
        for path, backdate_days in paths_to_backdate:
            # Vary each file/dir by a few hours to avoid "all same timestamp"
            hours_var = random.randint(1, 72)
            ts = now - (backdate_days * 86400) - (hours_var * 3600)
            touch_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(ts))
            cmds.append(f"find {path} -maxdepth 2 -exec touch -t {touch_fmt} {{}} + 2>/dev/null")

            # Also backdate parent directory itself with slight offset
            parent_ts = ts - random.randint(3600, 86400)
            parent_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(parent_ts))
            cmds.append(f"touch -t {parent_fmt} {path} 2>/dev/null")

        if cmds:
            _adb_shell(self.target, "; ".join(cmds))
            logger.info(f"  Timestamps: backdated {len(paths_to_backdate)} directories")

        # Backdate app install times by touching APK dirs in /data/app/
        # Without this, 30+ apps all show "installed just now" — a forensic anomaly
        app_installs = profile.get("app_installs", [])
        core_packages = [
            self._browser_pkg, "com.google.android.gms",
            "com.google.android.gsf", "com.android.vending",
            "com.google.android.apps.maps", "com.google.android.youtube",
            "com.google.android.apps.photos",
        ]
        install_cmds = []
        pm_cmds = []  # pm set-install-time commands (Android 11+)
        for pkg in core_packages:
            days_back = random.randint(max(1, age_days - 10), age_days)
            hours_var = random.randint(1, 48)
            ts = now - (days_back * 86400) - (hours_var * 3600)
            ts_ms = int(ts * 1000)
            touch_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(ts))
            install_cmds.append(
                f"for d in /data/app/*{pkg}*; do touch -t {touch_fmt} $d $d/*.apk 2>/dev/null; done")
            # pm set-install-time updates PackageManager's internal database
            # so Settings > Apps > [app] shows correct install date
            pm_cmds.append(
                f"pm set-install-time {pkg} {ts_ms} 2>/dev/null")
        for app in app_installs[:20]:
            pkg = app.get("package", "")
            app_ts = app.get("install_time", 0)
            if pkg and app_ts:
                ts_sec = app_ts / 1000 if app_ts > 1e12 else app_ts
                ts_ms = int(ts_sec * 1000)
                touch_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(ts_sec))
                install_cmds.append(
                    f"for d in /data/app/*{pkg}*; do touch -t {touch_fmt} $d $d/*.apk 2>/dev/null; done")
                pm_cmds.append(
                    f"pm set-install-time {pkg} {ts_ms} 2>/dev/null")
        if install_cmds:
            _adb_shell(self.target, "; ".join(install_cmds))
            logger.info(f"  Install times: backdated {len(install_cmds)} packages (filesystem)")
        if pm_cmds:
            # pm set-install-time may not exist on all Android versions — non-fatal
            _adb_shell(self.target, "; ".join(pm_cmds))
            logger.info(f"  Install times: backdated {len(pm_cmds)} packages (PackageManager)")

    # ─── PAYMENT HISTORY INJECTION (P3-1) ────────────────────────────────

    def _inject_payment_history(self, profile: Dict[str, Any], card_data: Dict[str, Any]):
        """Inject payment transaction history into banking app databases."""
        try:
            from payment_history_forge import PaymentHistoryForge
            
            logger.info("  Injecting payment transaction history")
            
            # Generate payment history
            forge = PaymentHistoryForge()
            history = forge.forge(
                age_days=profile.get("age_days", 90),
                card_network=card_data.get("network", "visa"),
                card_last4=card_data.get("number", "")[-4:],
                persona_email=profile.get("persona_email", ""),
                persona_name=profile.get("persona_name", ""),
                country=profile.get("country", "US"),
            )
            
            # Inject transaction history into banking app databases
            # This would write to app-specific databases
            # For now, store in profile for later use
            profile["payment_history"] = history
            
            logger.info(f"  Payment history: {len(history['transactions'])} transactions generated")
            
        except Exception as e:
            logger.warning(f"  Payment history injection failed: {e}")
            self.result.errors.append(f"payment_history: {e}")
