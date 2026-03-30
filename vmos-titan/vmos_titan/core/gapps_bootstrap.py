"""
Titan V11.3 — GApps Bootstrap for Vanilla AOSP Cuttlefish
==========================================================
Installs GMS, Play Store, Chrome, Google Pay onto vanilla AOSP.
MUST run BEFORE the aging pipeline.

Usage:
    bootstrap = GAppsBootstrap(adb_target="127.0.0.1:6520")
    result = bootstrap.run()
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from exceptions import GAppsBootstrapError

logger = logging.getLogger("titan.gapps-bootstrap")

GAPPS_DIR = Path(os.environ.get("TITAN_GAPPS_DIR", "/opt/titan/data/gapps"))

# Install order matters: GSF → GMS → Play Store → WebView → apps
# A real Android flagship has ~150 packages. Cuttlefish AOSP ships ~38.
# After this bootstrap runs: ~70+ packages — closing the critical gap
# detected by UsageStatsManager, PackageManager queries, and RASP SDKs.
ESSENTIAL_APKS = [
    # ── Tier 1: GMS Core (everything depends on these) ────────────────
    {"pkg": "com.google.android.gsf", "name": "Google Services Framework",
     "required": True, "priority": 1,
     "globs": ["GoogleServicesFramework*.apk", "gsf*.apk", "GSF*.apk"]},
    {"pkg": "com.google.android.gms", "name": "Google Play Services",
     "required": True, "priority": 2,
     "globs": ["GmsCore*.apk", "GooglePlayServices*.apk", "gms*.apk",
               "com.google.android.gms*.apk", "PlayServices*.apk"]},
    {"pkg": "com.android.vending", "name": "Google Play Store",
     "required": True, "priority": 3,
     "globs": ["Phonesky*.apk", "PlayStore*.apk", "vending*.apk",
               "com.android.vending*.apk", "GooglePlayStore*.apk"]},

    # ── Tier 2: System WebView (required by ~80% of apps) ─────────────
    # Without this: bank apps crash on launch, BNPL apps show blank screens,
    # and the package-presence check instantly reveals a non-production device.
    {"pkg": "com.google.android.webview", "name": "Android System WebView",
     "required": True, "priority": 4,
     "globs": ["AndroidSystemWebView*.apk", "webview*.apk", "WebView*.apk",
               "com.google.android.webview*.apk", "Trichrome*.apk"]},

    # ── Tier 3: Browser ────────────────────────────────────────────────
    {"pkg": "com.android.chrome", "name": "Google Chrome",
     "required": True, "priority": 5,
     "globs": ["Chrome*.apk", "chrome*.apk", "com.android.chrome*.apk"],
     "alt_pkg": "com.kiwibrowser.browser",
     "alt_globs": ["Chrome_standalone*.apk", "Kiwi*.apk", "kiwi*.apk"]},

    # ── Tier 4: Wallet ─────────────────────────────────────────────────
    {"pkg": "com.google.android.apps.walletnfcrel", "name": "Google Pay / Wallet",
     "required": True, "priority": 6,
     "globs": ["GooglePay*.apk", "Wallet*.apk", "GPay*.apk",
               "com.google.android.apps.walletnfcrel*.apk"]},

    # ── Tier 5: Input Method (default keyboard) ────────────────────────
    # Without Gboard: default IME shows as AOSP virtual keyboard — instantly
    # detectable as a stock emulator since no real user keeps AOSP keyboard.
    {"pkg": "com.google.android.inputmethod.latin", "name": "Gboard",
     "required": True, "priority": 7,
     "globs": ["Gboard*.apk", "gboard*.apk", "LatinIME*.apk",
               "com.google.android.inputmethod.latin*.apk"]},

    # ── Tier 6: Google Search / Assistant ─────────────────────────────
    # Required: any app that deep-links to "Hey Google", Settings references it,
    # and its absence in pm list is a major forensic anomaly on all Google devices.
    {"pkg": "com.google.android.googlequicksearchbox", "name": "Google Search",
     "required": True, "priority": 8,
     "globs": ["GoogleSearch*.apk", "Velvet*.apk",
               "com.google.android.googlequicksearchbox*.apk"]},

    # ── Tier 7: Communication apps ────────────────────────────────────
    # Google Messages replaces AOSP MMS app on GMS devices.
    # Its absence is detected by bank apps that look for SMS OTP capability.
    {"pkg": "com.google.android.apps.messaging", "name": "Google Messages",
     "required": False, "priority": 9,
     "globs": ["GoogleMessages*.apk", "Messages*.apk",
               "com.google.android.apps.messaging*.apk"]},
    {"pkg": "com.google.android.dialer", "name": "Google Phone",
     "required": False, "priority": 10,
     "globs": ["GooglePhone*.apk", "Dialer*.apk",
               "com.google.android.dialer*.apk"]},

    # ── Tier 8: Core Google apps (package presence check) ─────────────
    {"pkg": "com.google.android.youtube", "name": "YouTube",
     "required": False, "priority": 11,
     "globs": ["YouTube*.apk", "youtube*.apk"]},
    {"pkg": "com.google.android.gm", "name": "Gmail",
     "required": False, "priority": 12,
     "globs": ["Gmail*.apk", "gmail*.apk"]},
    {"pkg": "com.google.android.apps.maps", "name": "Google Maps",
     "required": False, "priority": 13,
     "globs": ["Maps*.apk", "GoogleMaps*.apk"]},
    {"pkg": "com.google.android.apps.photos", "name": "Google Photos",
     "required": False, "priority": 14,
     "globs": ["Photos*.apk", "GooglePhotos*.apk"]},
    {"pkg": "com.google.android.apps.docs", "name": "Google Drive",
     "required": False, "priority": 15,
     "globs": ["Drive*.apk", "GoogleDrive*.apk", "com.google.android.apps.docs*.apk"]},
    {"pkg": "com.google.android.calendar", "name": "Google Calendar",
     "required": False, "priority": 16,
     "globs": ["Calendar*.apk", "GoogleCalendar*.apk",
               "com.google.android.calendar*.apk"]},
    {"pkg": "com.google.android.tts", "name": "Google Text-to-Speech",
     "required": False, "priority": 17,
     "globs": ["GoogleTTS*.apk", "TextToSpeech*.apk",
               "com.google.android.tts*.apk"]},
    {"pkg": "com.google.android.contacts", "name": "Google Contacts",
     "required": False, "priority": 18,
     "globs": ["GoogleContacts*.apk", "Contacts*.apk",
               "com.google.android.contacts*.apk"]},
    {"pkg": "com.google.android.keep", "name": "Google Keep",
     "required": False, "priority": 19,
     "globs": ["Keep*.apk", "GoogleKeep*.apk", "com.google.android.keep*.apk"]},
    {"pkg": "com.google.android.deskclock", "name": "Google Clock",
     "required": False, "priority": 20,
     "globs": ["Clock*.apk", "DeskClock*.apk",
               "com.google.android.deskclock*.apk"]},
]


@dataclass
class BootstrapResult:
    success: bool = False
    installed: List[str] = field(default_factory=list)
    already_installed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    missing_apks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    total_packages_before: int = 0
    total_packages_after: int = 0
    gms_ready: bool = False
    play_store_ready: bool = False
    chrome_ready: bool = False
    wallet_ready: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class GAppsBootstrap:
    """Installs GApps on a vanilla AOSP Cuttlefish device."""

    def __init__(self, adb_target: str = "127.0.0.1:6520", gapps_dir: str = ""):
        self.target = adb_target
        self.gapps_dir = Path(gapps_dir) if gapps_dir else GAPPS_DIR
        self._adb_cmd(["root"], timeout=10)
        time.sleep(1)

    def _adb_cmd(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        cmd = ["adb", "-s", self.target] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)

    def _shell(self, cmd: str, timeout: int = 15) -> str:
        ok, out = self._adb_cmd(["shell", cmd], timeout=timeout)
        return out.strip()

    def _is_installed(self, pkg: str) -> bool:
        out = self._shell(f"pm list packages {pkg} 2>/dev/null")
        return f"package:{pkg}" in out

    def _is_gms_prebaked(self) -> bool:
        """Check if GMS was injected into /system/priv-app/ at image build time."""
        out = self._shell("ls /system/priv-app/GmsCore/ 2>/dev/null || ls /system/priv-app/PrebuiltGmsCore/ 2>/dev/null")
        return "GmsCore" in out or ".apk" in out

    def _get_installed_packages(self) -> List[str]:
        out = self._shell("pm list packages 2>/dev/null")
        return [l.replace("package:", "").strip()
                for l in out.split("\n") if l.startswith("package:")]

    def _find_apk(self, entry: Dict) -> Optional[Path]:
        if not self.gapps_dir.exists():
            return None
        for pattern in entry["globs"]:
            matches = list(self.gapps_dir.glob(pattern))
            if matches:
                return max(matches, key=lambda p: p.stat().st_size)
        exact = self.gapps_dir / f"{entry['pkg']}.apk"
        return exact if exact.exists() else None

    def _install_apk(self, apk_path: Path) -> Tuple[bool, str]:
        cmd = ["install", "-r", "-d", "-g", str(apk_path)]
        logger.info(f"  Installing {apk_path.name} ({apk_path.stat().st_size // 1024}KB)...")
        ok, out = self._adb_cmd(cmd, timeout=120)
        if not ok and "INSTALL_FAILED_MISSING_SPLIT" in out:
            # Try XAPK bundle (zip with split APKs inside)
            return self._install_xapk(apk_path)
        if not ok and "INSTALL_FAILED_MISSING_SHARED_LIBRARY" in out:
            # Chrome needs TrichromeLibrary — skip, use alt browser
            logger.warning(f"  {apk_path.name} needs shared library — trying alt")
        return ok, out

    def _install_xapk(self, xapk_path: Path) -> Tuple[bool, str]:
        """Extract XAPK bundle and install via install-multiple."""
        import tempfile, zipfile
        xapk_file = xapk_path.with_suffix(".xapk")
        if not xapk_file.exists():
            # The .apk might itself be an XAPK — check for embedded APKs
            try:
                with zipfile.ZipFile(xapk_path) as zf:
                    apk_names = [n for n in zf.namelist() if n.endswith(".apk")]
                    if not apk_names:
                        return False, "Not an XAPK bundle"
                    xapk_file = xapk_path  # It IS an XAPK
            except zipfile.BadZipFile:
                return False, "Not a valid zip/XAPK"
        else:
            try:
                with zipfile.ZipFile(xapk_file) as zf:
                    apk_names = [n for n in zf.namelist() if n.endswith(".apk")]
            except zipfile.BadZipFile:
                return False, "Bad XAPK file"

        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"  Extracting XAPK: {len(apk_names)} splits")
            with zipfile.ZipFile(xapk_file) as zf:
                for name in apk_names:
                    zf.extract(name, tmpdir)
            splits = [str(Path(tmpdir) / n) for n in apk_names]
            cmd = ["install-multiple", "-r", "-d", "-g"] + splits
            return self._adb_cmd(cmd, timeout=180)

    def check_status(self) -> Dict:
        """Check current GApps status without making changes."""
        pkgs = self._get_installed_packages()
        gms = self._is_installed("com.google.android.gms")
        ps = self._is_installed("com.android.vending")
        ch = self._is_installed("com.android.chrome") or self._is_installed("com.kiwibrowser.browser")
        wl = self._is_installed("com.google.android.apps.walletnfcrel")
        # New required tier checks
        webview = self._is_installed("com.google.android.webview")
        gboard = self._is_installed("com.google.android.inputmethod.latin")
        gsearch = self._is_installed("com.google.android.googlequicksearchbox")
        # A real Samsung S25 Ultra has ~150 packages; we need at least 70+ to look credible
        total = len(pkgs)
        pkg_density_ok = total >= 70
        return {
            "gms_installed": gms, "play_store_installed": ps,
            "chrome_installed": ch, "wallet_installed": wl,
            "webview_installed": webview, "gboard_installed": gboard,
            "google_search_installed": gsearch,
            "youtube_installed": self._is_installed("com.google.android.youtube"),
            "gmail_installed": self._is_installed("com.google.android.gm"),
            "total_packages": total,
            "total_google_packages": sum(1 for p in pkgs if "google" in p or p == "com.android.vending"),
            "package_density_ok": pkg_density_ok,
            "needs_bootstrap": not (gms and ps and ch and wl and webview and gboard),
            "apk_dir": str(self.gapps_dir),
            "apks_available": (len(list(self.gapps_dir.glob("*.apk"))) +
                              len(list(self.gapps_dir.glob("*.xapk")))) if self.gapps_dir.exists() else 0,
        }

    def auto_download_apks(self) -> List[str]:
        """Download missing essential APKs. Best-effort with multiple sources."""
        import urllib.request
        self.gapps_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []

        # Also check alternate gapps directories
        alt_dirs = [
            Path("/opt/titan/data/gapps"),
            Path("/opt/titan/gapps"),
            Path("/opt/gapps"),
        ]
        for alt in alt_dirs:
            if alt.exists() and alt != self.gapps_dir:
                for apk in list(alt.glob("*.apk")) + list(alt.glob("*.xapk")):
                    dest = self.gapps_dir / apk.name
                    if not dest.exists() and apk.stat().st_size > 1_000_000:
                        import shutil
                        shutil.copy2(str(apk), str(dest))
                        logger.info(f"  Copied {apk.name} from {alt} ({apk.stat().st_size // 1024}KB)")

        # Purge broken downloads (HTML pages < 1MB masquerading as APKs)
        for f in list(self.gapps_dir.glob("*.apk")) + list(self.gapps_dir.glob("*.xapk")):
            if f.stat().st_size < 1_000_000:  # <1MB is not a real APK
                logger.warning(f"  Removing invalid APK {f.name} ({f.stat().st_size} bytes)")
                f.unlink()

        for entry in ESSENTIAL_APKS:
            if not entry["required"]:
                continue
            if self._find_apk(entry):
                continue
            pkg = entry["pkg"]

            # Source 1: APKPure direct download
            for fmt, ext in [("XAPK", ".xapk"), ("APK", ".apk")]:
                url = f"https://d.apkpure.net/b/{fmt}/{pkg}?version=latest"
                dest = self.gapps_dir / f"{pkg}{ext}"
                try:
                    logger.info(f"  Downloading {entry['name']} ({fmt}) from APKPure...")
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S921U) "
                                       "AppleWebKit/537.36 Chrome/131.0.6778.81 Mobile Safari/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        data = resp.read()
                        # Validate: real APKs are >1MB and start with PK or ZIP magic
                        if len(data) > 1_000_000 and (data[:2] == b'PK' or data[:4] == b'\x50\x4b\x03\x04'):
                            dest.write_bytes(data)
                            downloaded.append(pkg)
                            logger.info(f"  Downloaded {dest.name} ({len(data) // 1024}KB)")
                            break
                        else:
                            logger.warning(f"  {pkg}: got {len(data)} bytes, not a valid APK (HTML redirect?)")
                except Exception as e:
                    logger.warning(f"  Download failed for {pkg} ({fmt}): {e}")
        return downloaded

    def restore_gapps(self) -> List[str]:
        """Attempt to reinstall GApps that were previously uninstalled.
        Tries: (1) reinstall from /system partition, (2) install from gapps_dir."""
        restored = []

        # Method 1: Try pm install-existing (restores uninstalled system apps)
        for entry in ESSENTIAL_APKS:
            pkg = entry["pkg"]
            if self._is_installed(pkg):
                continue
            ok, out = self._adb_cmd(["shell", f"pm install-existing {pkg}"], timeout=30)
            if ok and "installed" in out.lower():
                logger.info(f"  Restored {entry['name']} via install-existing")
                restored.append(pkg)
                continue

            # Method 2: Check /system, /product, /system_ext for APKs
            sys_paths = self._shell(
                f"find /system /product /system_ext -name '*.apk' -path '*{pkg}*' 2>/dev/null"
            )
            for sys_apk in sys_paths.split("\n"):
                sys_apk = sys_apk.strip()
                if sys_apk and sys_apk.endswith(".apk"):
                    ok, out = self._adb_cmd(
                        ["shell", f"pm install -r -d -g {sys_apk}"], timeout=60
                    )
                    if ok and "Success" in out:
                        logger.info(f"  Restored {entry['name']} from {sys_apk}")
                        restored.append(pkg)
                        break

        return restored

    def run(self, skip_optional: bool = False) -> BootstrapResult:
        """Run the full GApps bootstrap."""
        result = BootstrapResult()
        logger.info("=" * 60)
        logger.info("GApps Bootstrap — Installing Google services on Cuttlefish")
        logger.info("=" * 60)

        result.total_packages_before = len(self._get_installed_packages())
        logger.info(f"Packages before: {result.total_packages_before}")

        # Fast-path: check if GMS is pre-baked into system image (MindTheGapps)
        if self._is_gms_prebaked():
            logger.info("GMS pre-baked in system image — verifying essential packages")
            all_present = True
            entries = [e for e in ESSENTIAL_APKS if e["required"]]
            for entry in entries:
                pkg = entry["pkg"]
                if self._is_installed(pkg):
                    result.already_installed.append(pkg)
                else:
                    alt_pkg = entry.get("alt_pkg")
                    if alt_pkg and self._is_installed(alt_pkg):
                        result.already_installed.append(alt_pkg)
                    else:
                        all_present = False
            if all_present:
                logger.info(f"All {len(result.already_installed)} essential packages present — skipping bootstrap")
                result.gms_ready = self._is_installed("com.google.android.gms")
                result.play_store_ready = self._is_installed("com.android.vending")
                result.chrome_ready = self._is_installed("com.android.chrome")
                result.wallet_ready = self._is_installed("com.google.android.apps.walletnfcrel")
                result.total_packages_after = len(self._get_installed_packages())
                return result
            logger.info("Some packages missing despite pre-baked image — continuing with install")

        # Phase 0: Try restoring previously-uninstalled GApps first (fastest path)
        restored = self.restore_gapps()
        if restored:
            logger.info(f"Restored {len(restored)} packages via install-existing/system: {restored}")

        self.gapps_dir.mkdir(parents=True, exist_ok=True)
        available = list(self.gapps_dir.glob("*.apk"))
        # Auto-download if very few APKs present
        if len(available) + len(list(self.gapps_dir.glob("*.xapk"))) < 3:
            logger.info("Few APKs found — attempting auto-download...")
            self.auto_download_apks()
            available = list(self.gapps_dir.glob("*.apk"))
        logger.info(f"APKs in {self.gapps_dir}: {len(available)}")
        for apk in sorted(available):
            logger.info(f"  {apk.name} ({apk.stat().st_size // 1024}KB)")

        entries = [e for e in ESSENTIAL_APKS if not skip_optional or e["required"]]
        for entry in sorted(entries, key=lambda e: e["priority"]):
            pkg, name = entry["pkg"], entry["name"]

            if self._is_installed(pkg):
                logger.info(f"  SKIP {name} ({pkg}) — already installed")
                result.already_installed.append(pkg)
                continue

            apk_path = self._find_apk(entry)
            # If primary APK not found or fails, try alternative package
            alt_pkg = entry.get("alt_pkg")
            if not apk_path and alt_pkg and self._is_installed(alt_pkg):
                logger.info(f"  SKIP {name} — alt {alt_pkg} already installed")
                result.already_installed.append(alt_pkg)
                continue
            if not apk_path and alt_pkg:
                # Try finding alt APK
                alt_entry = {"globs": entry.get("alt_globs", []), "pkg": alt_pkg}
                apk_path = self._find_apk(alt_entry)
            if not apk_path:
                msg = f"{name} ({pkg}) — APK not found"
                if entry["required"]:
                    logger.error(f"  MISSING {msg}")
                    result.missing_apks.append(pkg)
                else:
                    logger.info(f"  SKIP {msg} (optional)")
                continue

            ok, out = self._install_apk(apk_path)
            if ok and "Success" in out:
                logger.info(f"  OK {name} ({pkg})")
                result.installed.append(pkg)
            else:
                err = out.strip().split("\n")[-1] if out else "unknown"
                logger.error(f"  FAIL {name} ({pkg}) — {err}")
                # If primary install failed and alt package exists, try it immediately
                if alt_pkg and not self._is_installed(alt_pkg):
                    alt_entry = {"globs": entry.get("alt_globs", []), "pkg": alt_pkg}
                    alt_apk = self._find_apk(alt_entry)
                    if alt_apk:
                        logger.info(f"  Trying alt: {alt_pkg} ({alt_apk.name})")
                        alt_ok, alt_out = self._install_apk(alt_apk)
                        if alt_ok and "Success" in alt_out:
                            logger.info(f"  OK {name} via alt ({alt_pkg})")
                            result.installed.append(alt_pkg)
                            time.sleep(1)
                            continue
                result.failed.append(pkg)
                result.errors.append(f"{pkg}: {err}")
            time.sleep(1)

        # Post-install: grant GMS permissions
        if self._is_installed("com.google.android.gms"):
            for perm in ["ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
                         "READ_PHONE_STATE", "GET_ACCOUNTS", "READ_CONTACTS",
                         "WRITE_CONTACTS", "READ_EXTERNAL_STORAGE",
                         "WRITE_EXTERNAL_STORAGE", "RECEIVE_SMS"]:
                self._shell(f"pm grant com.google.android.gms android.permission.{perm} 2>/dev/null")

        # Post-install: grant WebView permissions
        if self._is_installed("com.google.android.webview"):
            self._shell("pm grant com.google.android.webview android.permission.ACCESS_FINE_LOCATION 2>/dev/null")
            # Mark WebView as current provider (required by any app using WebView)
            self._shell(
                "settings put global webview_provider com.google.android.webview 2>/dev/null || "
                "settings put global webview_multiprocess_enabled 1 2>/dev/null"
            )

        # Post-install: set Gboard as default IME (no real user keeps AOSP virtual keyboard)
        if self._is_installed("com.google.android.inputmethod.latin"):
            self._shell(
                "settings put secure default_input_method "
                "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME; "
                "settings put secure enabled_input_methods "
                "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME; "
                "pm grant com.google.android.inputmethod.latin android.permission.READ_CONTACTS 2>/dev/null"
            )
            logger.info("  Gboard set as default IME")

        # Post-install: grant Google Search permissions
        if self._is_installed("com.google.android.googlequicksearchbox"):
            for perm in ["ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
                         "READ_CONTACTS", "RECORD_AUDIO"]:
                self._shell(f"pm grant com.google.android.googlequicksearchbox "
                            f"android.permission.{perm} 2>/dev/null")

        # Post-install: disable GMS setup wizard nag
        self._shell("settings put secure user_setup_complete 1")
        self._shell("settings put global device_provisioned 1")
        self._shell("am broadcast -a com.google.android.checkin.CHECKIN_COMPLETE 2>/dev/null")

        # Verify
        result.total_packages_after = len(self._get_installed_packages())
        result.gms_ready = self._is_installed("com.google.android.gms")
        result.play_store_ready = self._is_installed("com.android.vending")
        result.chrome_ready = (self._is_installed("com.android.chrome")
                               or self._is_installed("com.kiwibrowser.browser"))
        result.wallet_ready = self._is_installed("com.google.android.apps.walletnfcrel")
        result.success = result.gms_ready and result.play_store_ready and not result.missing_apks

        logger.info("=" * 60)
        logger.info(f"Bootstrap complete: {len(result.installed)} installed, "
                     f"{len(result.already_installed)} skipped, "
                     f"{len(result.failed)} failed, "
                     f"{len(result.missing_apks)} missing")
        logger.info(f"  GMS={result.gms_ready} PlayStore={result.play_store_ready} "
                     f"Chrome={result.chrome_ready} Wallet={result.wallet_ready}")
        logger.info("=" * 60)
        return result
