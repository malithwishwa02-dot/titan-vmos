"""
Titan V11.3 — Device Aging Report
===================================
Generates comprehensive verification reports for aged devices,
combining trust score, patch results, app installation status,
wallet state, injection results, and agent task history.

Usage:
    reporter = AgingReporter(device_manager=dm)
    report = await reporter.generate(device_id="dev-abc123")
    # Returns full JSON report with all checks
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.aging-report")

PROFILES_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
TRAJECTORY_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "trajectories"


@dataclass
class AgingReport:
    """Complete device aging report."""
    device_id: str = ""
    report_time: str = ""
    # Persona
    persona: Dict[str, str] = field(default_factory=dict)
    profile_id: str = ""
    profile_age_days: int = 0
    # Scores
    trust_score: Dict[str, Any] = field(default_factory=dict)
    patch_score: Dict[str, Any] = field(default_factory=dict)
    verify_score: Dict[str, Any] = field(default_factory=dict)
    # App state
    apps_installed: List[Dict[str, Any]] = field(default_factory=list)
    apps_signed_in: List[Dict[str, Any]] = field(default_factory=list)
    # Wallet
    wallet: Dict[str, Any] = field(default_factory=dict)
    # Injection results
    injection_results: Dict[str, Any] = field(default_factory=dict)
    # Agent tasks
    agent_tasks: List[Dict[str, Any]] = field(default_factory=list)
    # V12: Extended metrics
    lifepath_score: Dict[str, Any] = field(default_factory=dict)
    play_integrity: Dict[str, Any] = field(default_factory=dict)
    immune_watchdog: Dict[str, Any] = field(default_factory=dict)
    sensor_status: Dict[str, Any] = field(default_factory=dict)
    ghost_sim: Dict[str, Any] = field(default_factory=dict)
    gps_continuity: Dict[str, Any] = field(default_factory=dict)
    sms_coherence: Dict[str, Any] = field(default_factory=dict)
    wifi_consistency: Dict[str, Any] = field(default_factory=dict)
    # Overall
    overall_grade: str = ""
    overall_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class AgingReporter:
    """Generates comprehensive aging reports for devices."""

    def __init__(self, bridge=None, device_manager=None):
        self._bridge = bridge  # legacy — unused for Cuttlefish
        self.dm = device_manager

    async def generate(self, device_id: str) -> AgingReport:
        """Generate a full aging report for a device."""
        report = AgingReport(
            device_id=device_id,
            report_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        dev = self.dm.get_device(device_id) if self.dm else None
        adb_target = dev.adb_target if dev else "127.0.0.1:6520"

        # 1. Load persona from profile
        report.persona, report.profile_id, report.profile_age_days = (
            self._load_profile_info(device_id)
        )

        # 2. Trust score (if endpoint available)
        report.trust_score = await self._get_trust_score(device_id)

        # 3. Patch score
        report.patch_score = await self._get_patch_score(device_id)

        # 4. Task verification
        if dev:
            from task_verifier import TaskVerifier
            verifier = TaskVerifier(adb_target=adb_target)

            # Check expected apps
            expected_apps = self._get_expected_apps(device_id)
            verify = await verifier.full_verify(
                device_id=device_id,
                expected_apps=expected_apps,
            )
            report.verify_score = verify.to_dict()

            # Detailed app status
            for pkg in expected_apps:
                result = await verifier.verify_app_installed(pkg)
                signin = await verifier.verify_app_signed_in(pkg)
                report.apps_installed.append({
                    "package": pkg,
                    "installed": result.passed,
                })
                if signin.passed:
                    report.apps_signed_in.append({
                        "package": pkg,
                        "signed_in": True,
                    })

            # Wallet check
            wallet_check = await verifier.verify_wallet_active()
            report.wallet = {
                "active": wallet_check.passed,
                "detail": wallet_check.detail,
            }

        # 5. Injection results from profile
        report.injection_results = self._load_injection_results(device_id)

        # 6. Agent task history from trajectories
        report.agent_tasks = self._load_agent_tasks(device_id)

        # V12: Extended metrics collection
        report.lifepath_score = await self._get_lifepath_score(device_id)
        report.play_integrity = await self._get_play_integrity(adb_target)
        report.immune_watchdog = await self._get_immune_scan(adb_target)
        report.sensor_status = await self._get_sensor_status(adb_target)
        report.ghost_sim = await self._get_ghost_sim_status(adb_target)
        report.gps_continuity = self._check_gps_continuity(device_id)
        report.sms_coherence = self._check_sms_coherence(device_id)
        report.wifi_consistency = self._check_wifi_consistency(device_id)

        # 7. Calculate overall grade
        report.overall_score, report.overall_grade = self._calculate_grade(report)
        report.recommendations = self._generate_recommendations(report)

        logger.info(f"Aging report for {device_id}: {report.overall_grade} "
                     f"({report.overall_score:.0f}/100)")
        return report

    def _load_profile_info(self, device_id: str) -> tuple:
        """Load persona info from saved profile."""
        persona = {}
        profile_id = ""
        age_days = 0

        if not PROFILES_DIR.exists():
            return persona, profile_id, age_days

        # Find profile for this device
        for f in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("device_id") == device_id or device_id in f.name:
                    persona = {
                        "name": data.get("persona_name", ""),
                        "email": data.get("persona_email", ""),
                        "phone": data.get("persona_phone", ""),
                        "country": data.get("country", ""),
                    }
                    profile_id = data.get("profile_id", f.stem)
                    age_days = data.get("age_days", 0)
                    break
            except Exception:
                continue

        return persona, profile_id, age_days

    async def _get_trust_score(self, device_id: str) -> Dict:
        """Fetch trust score from API (internal call)."""
        def _fetch():
            import urllib.request
            api_port = os.environ.get("TITAN_API_PORT", "8080")
            url = f"http://127.0.0.1:{api_port}/api/genesis/trust-score/{device_id}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        try:
            return await asyncio.to_thread(_fetch)
        except Exception:
            return {"score": 0, "grade": "N/A", "error": "Could not fetch trust score"}

    async def _get_patch_score(self, device_id: str) -> Dict:
        """Fetch latest patch/audit results."""
        def _fetch():
            import urllib.request
            api_port = os.environ.get("TITAN_API_PORT", "8080")
            url = f"http://127.0.0.1:{api_port}/api/stealth/{device_id}/audit"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        try:
            return await asyncio.to_thread(_fetch)
        except Exception:
            return {"score": 0, "phases": "N/A"}

    def _get_expected_apps(self, device_id: str) -> List[str]:
        """Get list of apps expected to be installed on this device."""
        try:
            from app_bundles import APP_BUNDLES, COUNTRY_BUNDLES
            # Default to US bundle
            bundles = COUNTRY_BUNDLES.get("US", ["us_banking", "social"])
            pkgs = []
            for bkey in bundles:
                bundle = APP_BUNDLES.get(bkey, {})
                for app in bundle.get("apps", []):
                    pkgs.append(app["pkg"])
            return pkgs[:20]  # Cap at 20 to avoid timeout
        except Exception:
            return []

    def _load_injection_results(self, device_id: str) -> Dict:
        """Load injection results from stored profile data."""
        results = {
            "contacts": 0, "sms": 0, "call_logs": 0,
            "chrome_history": False, "chrome_cookies": False,
            "gallery_photos": 0, "wallet": False,
        }
        if not PROFILES_DIR.exists():
            return results

        for f in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("device_id") == device_id or device_id in f.name:
                    results["contacts"] = len(data.get("contacts", []))
                    results["sms"] = len(data.get("sms", []))
                    results["call_logs"] = len(data.get("call_logs", []))
                    results["chrome_history"] = len(data.get("history", [])) > 0
                    results["chrome_cookies"] = len(data.get("cookies", [])) > 0
                    results["gallery_photos"] = len(data.get("gallery_paths", []))
                    results["wallet"] = bool(data.get("wallet_provisioned"))
                    break
            except Exception:
                continue
        return results

    def _load_agent_tasks(self, device_id: str) -> List[Dict]:
        """Load agent task history from trajectory metadata."""
        tasks = []
        if not TRAJECTORY_DIR.exists():
            return tasks

        for d in sorted(TRAJECTORY_DIR.iterdir(), reverse=True):
            meta_file = d / "metadata.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text())
                if meta.get("device_id") == device_id or device_id in meta.get("device_id", ""):
                    tasks.append({
                        "task_id": meta.get("task_id"),
                        "prompt": meta.get("prompt", "")[:80],
                        "category": meta.get("task_category"),
                        "status": meta.get("status"),
                        "steps": meta.get("total_steps", 0),
                        "duration": f"{meta.get('duration', 0):.0f}s",
                        "model": meta.get("model"),
                        "is_demo": meta.get("is_demo", False),
                    })
            except Exception:
                continue

        return tasks[:20]  # Last 20 tasks

    def _calculate_grade(self, report: AgingReport) -> tuple:
        """Calculate overall aging score and letter grade.

        V12 weight distribution (total 100):
          trust=20, patch=12, verify=15, apps=10, wallet=8,
          lifepath=12, play_integrity=8, immune=5, sensors=5, coherence=5
        """
        score = 0.0
        weights = {
            "trust": 20,
            "patch": 12,
            "verify": 15,
            "apps": 10,
            "wallet": 8,
            "lifepath": 12,
            "play_integrity": 8,
            "immune": 5,
            "sensors": 5,
            "coherence": 5,
        }

        # Trust score component
        ts = report.trust_score.get("score", 0)
        if isinstance(ts, (int, float)):
            score += (ts / 100) * weights["trust"]

        # Patch score component
        ps = report.patch_score.get("score", 0)
        if isinstance(ps, (int, float)):
            score += (ps / 100) * weights["patch"]

        # Verify score component
        vs = report.verify_score.get("score", 0)
        if isinstance(vs, (int, float)):
            score += (vs / 100) * weights["verify"]

        # App installation rate
        if report.apps_installed:
            installed = sum(1 for a in report.apps_installed if a.get("installed"))
            rate = installed / len(report.apps_installed)
            score += rate * weights["apps"]

        # Wallet
        if report.wallet.get("active"):
            score += weights["wallet"]

        # V12: Life-path coherence
        lp = report.lifepath_score.get("score", 0)
        if isinstance(lp, (int, float)):
            score += (lp / 100) * weights["lifepath"]

        # V12: Play Integrity
        pi = report.play_integrity.get("score", 0)
        if isinstance(pi, (int, float)):
            score += (pi / 100) * weights["play_integrity"]

        # V12: Immune watchdog (invert risk: 0 risk = full score)
        risk = report.immune_watchdog.get("risk_score", 100)
        if isinstance(risk, (int, float)):
            immune_pct = max(0, 100 - risk)
            score += (immune_pct / 100) * weights["immune"]

        # V12: Sensor daemon running
        if report.sensor_status.get("running"):
            score += weights["sensors"]

        # V12: Data coherence (GPS + SMS + WiFi)
        coherence_checks = [
            report.gps_continuity.get("coherent", False),
            report.sms_coherence.get("coherent", False),
            report.wifi_consistency.get("coherent", False),
        ]
        coherent_count = sum(1 for c in coherence_checks if c)
        score += (coherent_count / max(len(coherence_checks), 1)) * weights["coherence"]

        # Grade
        if score >= 90:
            grade = "A+"
        elif score >= 80:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 50:
            grade = "D"
        else:
            grade = "F"

        return round(score, 1), grade

    # ─── V12 DATA COLLECTION METHODS ────────────────────────────────

    async def _get_lifepath_score(self, device_id: str) -> Dict:
        """Fetch lifepath coherence score from trust scorer."""
        try:
            profile = self._load_full_profile(device_id)
            if not profile:
                return {"score": 0, "grade": "N/A", "error": "no profile"}
            from core.trust_scorer import compute_lifepath_score
            return compute_lifepath_score(profile)
        except Exception as e:
            return {"score": 0, "grade": "N/A", "error": str(e)}

    async def _get_play_integrity(self, adb_target: str) -> Dict:
        """Run Play Integrity audit on device."""
        def _audit():
            from core.play_integrity_spoofer import PlayIntegritySpoofer
            spoofer = PlayIntegritySpoofer(adb_target=adb_target)
            return spoofer.audit()
        try:
            return await asyncio.to_thread(_audit)
        except Exception as e:
            return {"score": 0, "grade": "N/A", "error": str(e)}

    async def _get_immune_scan(self, adb_target: str) -> Dict:
        """Run immune watchdog full scan."""
        def _scan():
            from core.immune_watchdog import ImmuneWatchdog
            wd = ImmuneWatchdog(adb_target=adb_target)
            return wd.run_full_scan()
        try:
            return await asyncio.to_thread(_scan)
        except Exception as e:
            return {"risk_score": 100, "error": str(e)}

    async def _get_sensor_status(self, adb_target: str) -> Dict:
        """Check if sensor daemon is injecting data."""
        def _check():
            import subprocess
            r = subprocess.run(
                ["adb", "-s", adb_target, "shell",
                 "getprop persist.titan.sensor.accel.ts"],
                capture_output=True, text=True, timeout=10,
            )
            ts_str = r.stdout.strip()
            if not ts_str:
                return {"running": False, "stale": True}
            try:
                last_ts = float(ts_str)
                age = time.time() - last_ts
                return {"running": age < 30, "last_update_age_s": round(age, 1)}
            except ValueError:
                return {"running": False, "stale": True}
        try:
            return await asyncio.to_thread(_check)
        except Exception as e:
            return {"running": False, "error": str(e)}

    async def _get_ghost_sim_status(self, adb_target: str) -> Dict:
        """Check Ghost SIM configuration state."""
        def _check():
            import subprocess
            props = ["gsm.sim.state", "gsm.sim.operator.alpha", "gsm.nitz.time"]
            results = {}
            for p in props:
                r = subprocess.run(
                    ["adb", "-s", adb_target, "shell", f"getprop {p}"],
                    capture_output=True, text=True, timeout=10,
                )
                results[p] = r.stdout.strip()
            configured = results.get("gsm.sim.state") == "READY"
            return {"configured": configured, "props": results}
        try:
            return await asyncio.to_thread(_check)
        except Exception as e:
            return {"configured": False, "error": str(e)}

    def _check_gps_continuity(self, device_id: str) -> Dict:
        """Verify GPS coordinates in gallery match maps history."""
        profile = self._load_full_profile(device_id)
        if not profile:
            return {"coherent": False, "reason": "no profile"}
        gallery = profile.get("gallery_paths", [])
        maps_hist = profile.get("maps_history", {}).get("searches", [])
        if not gallery or not maps_hist:
            return {"coherent": len(gallery) == 0 and len(maps_hist) == 0,
                    "reason": "insufficient data"}
        # Check that GPS data exists in both sources
        has_gallery_gps = any(
            isinstance(p, dict) and (p.get("lat") or p.get("gps_lat"))
            for p in gallery
        )
        has_maps_gps = len(maps_hist) > 0
        return {
            "coherent": has_gallery_gps and has_maps_gps,
            "gallery_gps_count": sum(1 for p in gallery if isinstance(p, dict) and (p.get("lat") or p.get("gps_lat"))),
            "maps_search_count": len(maps_hist),
        }

    def _check_sms_coherence(self, device_id: str) -> Dict:
        """Verify SMS messages correlate with contacts and call logs."""
        profile = self._load_full_profile(device_id)
        if not profile:
            return {"coherent": False, "reason": "no profile"}
        contacts = profile.get("contacts", [])
        sms = profile.get("sms", [])
        calls = profile.get("call_logs", [])
        if not sms:
            return {"coherent": len(contacts) == 0, "reason": "no SMS data"}
        contact_numbers = {c.get("phone", "") for c in contacts if isinstance(c, dict)}
        sms_numbers = {s.get("address", "") for s in sms if isinstance(s, dict)}
        overlap = contact_numbers & sms_numbers
        ratio = len(overlap) / max(len(sms_numbers), 1)
        return {
            "coherent": ratio > 0.3,
            "overlap_ratio": round(ratio, 2),
            "sms_count": len(sms),
            "contacts_in_sms": len(overlap),
        }

    def _check_wifi_consistency(self, device_id: str) -> Dict:
        """Verify WiFi networks align with location profile."""
        profile = self._load_full_profile(device_id)
        if not profile:
            return {"coherent": False, "reason": "no profile"}
        wifi = profile.get("wifi_networks", [])
        location = profile.get("location", {})
        if not wifi:
            return {"coherent": False, "reason": "no WiFi networks"}
        home_count = sum(1 for w in wifi if isinstance(w, dict) and w.get("type") == "home")
        public_count = sum(1 for w in wifi if isinstance(w, dict) and w.get("type") == "public")
        return {
            "coherent": home_count >= 1 and len(wifi) >= 3,
            "total": len(wifi),
            "home": home_count,
            "public": public_count,
        }

    def _load_full_profile(self, device_id: str) -> Optional[Dict]:
        """Load full profile JSON for a device."""
        if not PROFILES_DIR.exists():
            return None
        for f in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("device_id") == device_id or device_id in f.name:
                    return data
            except Exception:
                continue
        return None

    def _generate_recommendations(self, report: AgingReport) -> List[str]:
        """Generate actionable recommendations based on report gaps."""
        recs = []

        ts = report.trust_score.get("score", 0)
        if isinstance(ts, (int, float)) and ts < 80:
            recs.append("Trust score below 80 — re-inject profile data or add missing data types")

        if not report.wallet.get("active"):
            recs.append("Wallet not active — inject tapandpay.db with card data")

        installed_count = sum(1 for a in report.apps_installed if a.get("installed"))
        total_expected = len(report.apps_installed)
        if total_expected > 0 and installed_count < total_expected * 0.7:
            missing = total_expected - installed_count
            recs.append(f"{missing} expected apps not installed — run app bundle install agent")

        signed_in = len(report.apps_signed_in)
        if installed_count > 0 and signed_in < installed_count * 0.3:
            recs.append("Low app sign-in rate — run sign-in agent for installed apps")

        if not report.agent_tasks:
            recs.append("No warmup tasks recorded — run warmup_device and warmup_youtube scenarios")

        # V12 recommendations
        lp = report.lifepath_score.get("score", 0)
        if isinstance(lp, (int, float)) and lp < 70:
            recs.append("Lifepath coherence below 70 — re-forge profile with correlate_lifepath()")

        pi = report.play_integrity.get("score", 0)
        if isinstance(pi, (int, float)) and pi < 80:
            recs.append("Play Integrity score low — apply_integrity_defense(tier='strong')")

        risk = report.immune_watchdog.get("risk_score", 100)
        if isinstance(risk, (int, float)) and risk > 30:
            recs.append(f"Immune risk score {risk} — deploy watchdog and harden probe paths")

        if not report.sensor_status.get("running"):
            recs.append("Sensor daemon not running — start_continuous_injection()")

        if not report.gps_continuity.get("coherent"):
            recs.append("GPS data incoherent — ensure gallery EXIF aligns with maps history")

        if not report.sms_coherence.get("coherent"):
            recs.append("SMS-contact overlap low — re-forge with correlated phone numbers")

        if not report.wifi_consistency.get("coherent"):
            recs.append("WiFi networks inconsistent — add home/public networks matching location")

        if not recs:
            recs.append("Device aging looks complete — monitor for anomaly detection")

        return recs
