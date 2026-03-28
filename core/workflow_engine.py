"""Titan V12.0 — Device Aging Workflow Engine (Cuttlefish)
========================================================
High-level orchestrator that chains multiple operations into a complete
device aging pipeline driven by user inputs.

Workflow stages:
  1. Forge Genesis profile (contacts, SMS, call logs, Chrome data)
  2. Inject profile into device
  3. Patch device for stealth (Cuttlefish artifact masking)
  4. Install app bundles via AI agent
  5. Sign into apps via AI agent (using persona credentials)
  6. Set up wallet (data injection via ADB)
  7. Run warmup browsing/YouTube sessions
  8. Generate verification report

Each stage decides the optimal method (data injection vs AI agent)
based on the app/task type.

Usage:
    engine = WorkflowEngine(device_manager=dm)
    job = await engine.start_workflow(
        device_id="dev-abc123",
        persona={"name": "James Mitchell", "email": "jm@gmail.com", ...},
        bundles=["us_banking", "social"],
        card_data={"number": "4532...", "exp_month": 12, ...},
        country="US",
        aging_level="medium",  # light=30d, medium=90d, heavy=365d
    )
    status = engine.get_status(job.job_id)
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.workflow-engine")

AGING_LEVELS = {
    "light": {"age_days": 30, "warmup_tasks": 2, "browse_queries": 3},
    "medium": {"age_days": 90, "warmup_tasks": 4, "browse_queries": 6},
    "heavy": {"age_days": 365, "warmup_tasks": 8, "browse_queries": 12},
}


@dataclass
class WorkflowStage:
    """Single stage in a workflow."""
    name: str = ""
    status: str = "pending"  # pending | running | completed | failed | skipped
    method: str = ""         # inject | agent | patch | forge
    detail: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


@dataclass
class WorkflowJob:
    """Complete workflow job."""
    job_id: str = ""
    device_id: str = ""
    status: str = "pending"
    stages: List[WorkflowStage] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0
    report: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.stages if s.status == "completed")

    @property
    def progress(self) -> float:
        return self.completed_stages / max(len(self.stages), 1)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "device_id": self.device_id,
            "status": self.status,
            "progress": round(self.progress * 100, 1),
            "stages": [asdict(s) for s in self.stages],
            "config": self.config,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "report": self.report,
        }


class WorkflowEngine:
    """Orchestrates complete device aging workflows."""

    def __init__(self, device_manager=None):
        self.dm = device_manager
        self._jobs: Dict[str, WorkflowJob] = {}
        self._threads: Dict[str, threading.Thread] = {}

    async def start_workflow(self, device_id: str,
                             persona: Dict[str, str] = None,
                             bundles: List[str] = None,
                             card_data: Dict[str, Any] = None,
                             country: str = "US",
                             aging_level: str = "medium",
                             skip_forge: bool = False,
                             skip_patch: bool = False,
                             profile_id: str = "",
                             disable_adb: bool = False) -> WorkflowJob:
        """Start a complete device aging workflow."""
        job_id = f"wf-{uuid.uuid4().hex[:8]}"
        aging = AGING_LEVELS.get(aging_level, AGING_LEVELS["medium"])

        job = WorkflowJob(
            job_id=job_id,
            device_id=device_id,
            status="pending",
            created_at=time.time(),
            config={
                "persona": persona or {},
                "bundles": bundles or ["us_banking", "social"],
                "card_data": {k: v for k, v in (card_data or {}).items() if k != "number"},
                "country": country,
                "aging_level": aging_level,
                "aging_config": aging,
                "profile_id": profile_id,
            },
        )

        # Build stage list — ORDER MATTERS:
        #   0. bootstrap_gapps  — install GMS/Play Store/Chrome/GPay (skip if present)
        #   1. forge_profile    — generate persona data
        #   2. install_apps     — via AI agent + Play Store (needs Play Store!)
        #   3. inject_profile   — push data into apps that now exist
        #   4. setup_wallet     — needs Google Pay APK installed
        #   5. patch_device     — stealth masking LAST (bind-mounts /proc)
        #   6. warmup           — natural usage after all data is in place
        #   7. verify           — audit + trust + wallet checks
        job.stages.append(WorkflowStage(name="bootstrap_gapps", method="inject"))
        if persona.get("proxy_url"):
            job.stages.append(WorkflowStage(name="configure_proxy", method="inject"))
        # V12: Ghost SIM configuration (before forge — carrier data needed)
        job.stages.append(WorkflowStage(name="ghost_sim_configure", method="inject"))
        if not skip_forge and not profile_id:
            job.stages.append(WorkflowStage(name="forge_profile", method="forge"))
        job.stages.append(WorkflowStage(name="install_apps", method="agent"))
        job.stages.append(WorkflowStage(name="inject_profile", method="inject"))
        if persona.get("phone"):
            job.stages.append(WorkflowStage(name="create_google_account", method="agent"))
        job.stages.append(WorkflowStage(name="setup_wallet", method="inject"))
        # V12: HCE bridge provisioning (after wallet — needs DPAN)
        if card_data and card_data.get("number"):
            job.stages.append(WorkflowStage(name="hce_provisioning", method="inject"))
        if not skip_patch:
            job.stages.append(WorkflowStage(name="patch_device", method="patch"))
        # V12: Play Integrity defense (after patch — needs fingerprint props)
        job.stages.append(WorkflowStage(name="play_integrity_defense", method="inject"))
        # V12: Sensor warmup (after patch — avoid prop conflicts)
        job.stages.append(WorkflowStage(name="sensor_warmup", method="inject"))
        job.stages.append(WorkflowStage(name="warmup_browse", method="agent"))
        job.stages.append(WorkflowStage(name="warmup_youtube", method="agent"))
        job.stages.append(WorkflowStage(name="verify_report", method="inject"))
        # V12: Immune watchdog (last defense layer before lockdown)
        job.stages.append(WorkflowStage(name="immune_watchdog", method="inject"))
        if disable_adb:
            job.stages.append(WorkflowStage(name="lockdown_device", method="inject"))

        self._jobs[job_id] = job

        job.config["disable_adb"] = disable_adb

        # Run in background thread
        thread = threading.Thread(
            target=self._run_workflow, args=(job_id, persona or {},
                                             bundles or ["us_banking", "social"],
                                             card_data or {}, country, aging),
            daemon=True,
        )
        self._threads[job_id] = thread
        job.status = "running"
        thread.start()

        logger.info(f"Workflow {job_id} started: {len(job.stages)} stages for {device_id}")
        return job

    def _check_adb_connectivity(self, job: WorkflowJob) -> bool:
        """Verify ADB connection to device before starting stages."""
        import subprocess
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        try:
            r = subprocess.run(
                ["adb", "-s", target, "shell", "echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and "ok" in r.stdout:
                logger.info(f"ADB connectivity OK: {target}")
                return True
            # Try reconnecting once
            subprocess.run(["adb", "connect", target],
                           capture_output=True, timeout=10)
            time.sleep(2)
            r = subprocess.run(
                ["adb", "-s", target, "shell", "echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0 and "ok" in r.stdout
        except Exception as e:
            logger.error(f"ADB connectivity check failed: {e}")
            return False

    def _run_workflow(self, job_id: str, persona: Dict, bundles: List[str],
                      card_data: Dict, country: str, aging: Dict):
        """Execute workflow stages sequentially."""
        job = self._jobs[job_id]

        try:
            # Pre-flight: verify ADB connectivity
            if not self._check_adb_connectivity(job):
                job.status = "failed"
                job.completed_at = time.time()
                logger.error(f"Workflow {job_id} aborted: ADB unreachable")
                return

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._run_stages(job, persona, bundles, card_data, country, aging))
            finally:
                loop.close()

            job.status = "completed"
        except Exception as e:
            job.status = "failed"
            logger.exception(f"Workflow {job_id} failed: {e}")

        job.completed_at = time.time()
        duration = job.completed_at - job.created_at
        logger.info(f"Workflow {job_id} finished: {job.status} "
                     f"({job.completed_stages}/{len(job.stages)} stages, {duration:.0f}s)")

    async def _run_stages(self, job: 'WorkflowJob', persona: Dict,
                          bundles: List[str], card_data: Dict,
                          country: str, aging: Dict):
        """Execute all workflow stages in order."""
        stage_map = {
            "bootstrap_gapps": lambda: self._stage_bootstrap_gapps(job),
            "configure_proxy": lambda: self._stage_configure_proxy(job, persona),
            "ghost_sim_configure": lambda: self._stage_ghost_sim(job, persona, country),
            "forge_profile": lambda: self._stage_forge(job, persona, country, aging),
            "inject_profile": lambda: self._stage_inject(job, persona, card_data),
            "create_google_account": lambda: self._stage_create_google_account(job, persona),
            "patch_device": lambda: self._stage_patch(job, country),
            "install_apps": lambda: self._stage_install_apps(job, bundles),
            "setup_wallet": lambda: self._stage_wallet(job, card_data),
            "hce_provisioning": lambda: self._stage_hce(job, card_data),
            "play_integrity_defense": lambda: self._stage_play_integrity(job),
            "sensor_warmup": lambda: self._stage_sensor_warmup(job),
            "warmup_browse": lambda: self._stage_warmup(job, "browse", aging),
            "warmup_youtube": lambda: self._stage_warmup(job, "youtube", aging),
            "verify_report": lambda: self._stage_verify(job),
            "immune_watchdog": lambda: self._stage_immune_watchdog(job),
            "lockdown_device": lambda: self._stage_lockdown(job),
        }

        ABORT_ON_FAILURE = {"bootstrap_gapps", "forge_profile"}
        RETRYABLE_STAGES = {"inject_profile", "install_apps", "setup_wallet",
                            "warmup_browse", "warmup_youtube", "verify_report",
                            "hce_provisioning", "sensor_warmup", "play_integrity_defense"}
        MAX_RETRIES = 2

        for idx, stage in enumerate(job.stages):
            stage.status = "running"
            stage.started_at = time.time()

            handler = stage_map.get(stage.name)
            if not handler:
                stage.status = "completed"
                stage.completed_at = time.time()
                continue

            last_error = None
            retries = MAX_RETRIES if stage.name in RETRYABLE_STAGES else 0
            for attempt in range(retries + 1):
                try:
                    await handler()
                    stage.status = "completed"
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < retries:
                        logger.info(f"Stage {stage.name} attempt {attempt+1} failed, retrying: {e}")
                        await asyncio.sleep(3 * (attempt + 1))
                    else:
                        stage.status = "failed"
                        stage.error = str(e)
                        logger.warning(f"Stage {stage.name} failed after {attempt+1} attempts: {e}")

            if last_error and stage.name in ABORT_ON_FAILURE:
                stage.completed_at = time.time()
                for remaining in job.stages[idx + 1:]:
                    remaining.status = "skipped"
                    remaining.error = f"Skipped: critical stage '{stage.name}' failed"
                raise RuntimeError(f"Aborting workflow: critical stage '{stage.name}' failed: {last_error}")

            stage.completed_at = time.time()

    # ─── STAGE IMPLEMENTATIONS ───────────────────────────────────────

    async def _stage_bootstrap_gapps(self, job: WorkflowJob):
        """Stage 0: Install GMS, Play Store, Chrome, Google Pay if missing."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from gapps_bootstrap import GAppsBootstrap
        bs = GAppsBootstrap(adb_target=dev.adb_target)

        # Quick check — skip if already bootstrapped
        status = bs.check_status()
        if not status["needs_bootstrap"]:
            logger.info("GApps already installed — skipping bootstrap")
            return

        result = bs.run(skip_optional=False)
        if result.missing_apks:
            logger.warning(f"Missing APKs (place in /opt/titan/data/gapps/): "
                           f"{result.missing_apks}")
        if not result.gms_ready or not result.play_store_ready:
            raise RuntimeError(
                f"GApps bootstrap incomplete: GMS={result.gms_ready} "
                f"PlayStore={result.play_store_ready}. "
                f"Place APKs in /opt/titan/data/gapps/ and retry.")
        logger.info(f"GApps bootstrap: {len(result.installed)} installed, "
                     f"{len(result.already_installed)} already present")

    async def _stage_configure_proxy(self, job: WorkflowJob, persona: Dict):
        """Stage: Configure SOCKS5 proxy routing on device."""
        proxy_url = persona.get("proxy_url", "")
        if not proxy_url:
            logger.info("No proxy URL — skipping proxy configuration")
            return

        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"

        from proxy_router import ProxyRouter
        router = ProxyRouter(adb_target=target)
        result = router.configure_socks5(proxy_url)

        if result.success:
            logger.info(f"Proxy configured via {result.method}, external IP: {result.external_ip}")
            job.config["proxy_method"] = result.method
            job.config["proxy_external_ip"] = result.external_ip
        else:
            errors = "; ".join(result.errors[:3])
            logger.warning(f"Proxy configuration failed: {errors}")
            # Non-fatal — continue without proxy

    async def _stage_create_google_account(self, job: WorkflowJob, persona: Dict):
        """Stage: Create a real Google account on device for OAuth session.
        
        This must run AFTER GApps bootstrap (GMS required) and BEFORE wallet 
        provisioning (Google Pay needs real account to display cards).
        """
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        phone = persona.get("phone", "")

        if not phone:
            logger.warning("No phone number for Google account creation — skipping")
            return

        from google_account_creator import GoogleAccountCreator
        creator = GoogleAccountCreator(adb_target=target)

        # Use manual OTP flow since phone is external
        result = creator.create_account(
            persona=persona,
            phone_number=phone,
            otp_callback=persona.get("otp_callback"),
        )

        if result.success:
            job.config["google_email"] = result.email
            job.config["google_password"] = result.password
            logger.info(f"Google account created: {result.email}")
        elif result.otp_required and not result.otp_received:
            # OTP needed but not received — store partial state for manual continuation
            job.config["google_email"] = result.email
            job.config["google_password"] = result.password
            job.config["otp_pending"] = True
            logger.warning(
                f"Google account creation paused — OTP sent to {phone}. "
                f"Call continue_with_otp() with the 6-digit code."
            )
        else:
            errors = "; ".join(result.errors[:3])
            logger.warning(f"Google account creation failed: {errors}")

    async def _stage_forge(self, job: WorkflowJob, persona: Dict,
                           country: str, aging: Dict):
        """Stage: Forge Genesis profile (direct call, no HTTP back-loop)."""
        from android_profile_forge import AndroidProfileForge

        forge = AndroidProfileForge()
        profile = forge.forge(
            persona_name=persona.get("name", ""),
            persona_email=persona.get("email", ""),
            persona_phone=persona.get("phone", ""),
            country=country,
            age_days=aging["age_days"],
        )

        # Embed card metadata in profile so downstream stages
        # (purchase_history_bridge, payment_history_forge) can reference
        # the actual card being provisioned (GAP-H3)
        card_data = job.config.get("card_data", {})
        card_number = card_data.get("number", "")
        if card_number and len(card_number) >= 4:
            profile["card_last4"] = card_number[-4:]
            # Detect card network from BIN
            first = card_number[0] if card_number else ""
            if first == "4":
                profile["card_network"] = "visa"
            elif first in ("5", "2"):
                profile["card_network"] = "mastercard"
            elif first == "3":
                profile["card_network"] = "amex"
            elif first == "6":
                profile["card_network"] = "discover"
            else:
                profile["card_network"] = "visa"
            profile["card_cardholder"] = card_data.get("cardholder", persona.get("name", ""))

        # Persist profile to disk (same path as genesis router)
        profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_id = profile.get("id", f"TITAN-{uuid.uuid4().hex[:8].upper()}")
        profile["id"] = profile_id
        (profiles_dir / f"{profile_id}.json").write_text(json.dumps(profile, indent=2))

        job.config["profile_id"] = profile_id
        logger.info(f"Profile forged: {profile_id}")

    async def _stage_inject(self, job: WorkflowJob, persona: Dict,
                            card_data: Dict):
        """Stage: Inject profile into device (direct call — no HTTP back-loop)."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        profile_id = job.config.get("profile_id", "")
        if not profile_id:
            logger.warning("No profile_id — skipping inject")
            return

        # Load profile data directly from disk
        profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
        profile_path = profiles_dir / f"{profile_id}.json"
        if not profile_path.exists():
            raise RuntimeError(f"Profile {profile_id} not found at {profile_path}")
        profile_data = json.loads(profile_path.read_text())

        # Direct inject via ProfileInjector (no HTTP round-trip)
        from profile_injector import ProfileInjector
        injector = ProfileInjector(adb_target=dev.adb_target)
        result = injector.inject_full_profile(profile_data, card_data=card_data if card_data else None)
        logger.info(f"Profile inject: {result.injected}/{result.total} items "
                     f"({result.success_rate:.0%})")

        # NOTE: Wallet injection is handled by the dedicated _stage_wallet stage.
        # Do NOT duplicate it here — that causes double-inject, DB overwrites,
        # and AttributeError crashes on WalletProvisionResult.

    async def _stage_patch(self, job: WorkflowJob, country: str):
        """Stage: Apply stealth patches via AnomalyPatcher."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from anomaly_patcher import AnomalyPatcher
        from device_presets import COUNTRY_DEFAULTS
        from pathlib import Path as _Path

        defaults = COUNTRY_DEFAULTS.get(country, COUNTRY_DEFAULTS.get("US", {}))
        carrier  = defaults.get("carrier", "att_us")
        location = defaults.get("location", "la")
        model    = dev.config.get("model", "samsung_s25_ultra")

        # Override with genesis profile values so GSM props match the persona's carrier
        profile_id = job.config.get("profile_id", "")
        if profile_id:
            _pf = _Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles" / f"{profile_id}.json"
            if _pf.exists():
                try:
                    _pd = json.loads(_pf.read_text())
                    carrier  = _pd.get("carrier",      carrier)
                    location = _pd.get("location",     location)
                    model    = _pd.get("device_model", model)
                    logger.info(f"Patch using profile values: preset={model} carrier={carrier} location={location}")
                except Exception as _e:
                    logger.warning(f"Could not load profile for patch params: {_e}")

        patcher = AnomalyPatcher(adb_target=dev.adb_target)
        report = patcher.full_patch(model, carrier, location)
        dev.patch_result = report.to_dict()
        dev.stealth_score = report.score
        dev.state = "patched"
        logger.info(f"Patch complete: score={report.score}")

    def _check_agent_available(self, adb_target: str) -> bool:
        """Pre-flight check: verify AI agent (Ollama) is reachable."""
        try:
            from device_agent import DeviceAgent
            agent = DeviceAgent(adb_target=adb_target)
            # Quick connectivity test — if Ollama is down, this will fail
            import urllib.request
            url = agent.ollama_url if hasattr(agent, 'ollama_url') else "http://127.0.0.1:11434"
            req = urllib.request.Request(f"{url}/api/tags", method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            return resp.status == 200
        except Exception:
            return False

    def _adb_sideload_apps(self, adb_target: str, bundles: List[str]) -> int:
        """Fallback: install apps via ADB sideload from local APK cache."""
        import subprocess
        from app_bundles import APP_BUNDLES

        apk_dirs = [
            Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "apks",
            Path("/opt/titan/data/apks"),
        ]

        installed = 0
        for bkey in bundles:
            bundle = APP_BUNDLES.get(bkey, {})
            for app in bundle.get("apps", []):
                pkg = app.get("pkg", "")
                if not pkg:
                    continue

                # Check if already installed
                try:
                    r = subprocess.run(
                        ["adb", "-s", adb_target, "shell", "pm", "path", pkg],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        installed += 1
                        continue
                except Exception:
                    pass

                # Search APK cache directories for matching APK
                apk_found = False
                for apk_dir in apk_dirs:
                    if not apk_dir.exists():
                        continue
                    # Match by package name (e.g., com.venmo.apk or com.venmo*.apk)
                    candidates = list(apk_dir.glob(f"{pkg}*.apk")) + list(apk_dir.glob(f"{app['name']}*.apk"))
                    if candidates:
                        apk_path = candidates[0]
                        try:
                            r = subprocess.run(
                                ["adb", "-s", adb_target, "install", "-r", str(apk_path)],
                                capture_output=True, text=True, timeout=120,
                            )
                            if r.returncode == 0:
                                installed += 1
                                apk_found = True
                                logger.info(f"  Sideloaded: {app['name']} ({pkg})")
                                break
                        except Exception as e:
                            logger.warning(f"  Sideload failed for {pkg}: {e}")

                if not apk_found:
                    logger.debug(f"  No APK found for {pkg} — skipping sideload")

        return installed

    async def _stage_install_apps(self, job: WorkflowJob, bundles: List[str]):
        """Stage: Install apps via AI agent, with ADB sideload fallback."""
        from app_bundles import APP_BUNDLES
        apps = []
        for bkey in bundles:
            bundle = APP_BUNDLES.get(bkey, {})
            for app in bundle.get("apps", []):
                apps.append(app["name"])

        if not apps:
            return

        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        # Try AI agent first, fall back to ADB sideload
        agent_ok = self._check_agent_available(dev.adb_target)

        if agent_ok:
            from device_agent import DeviceAgent
            agent = DeviceAgent(adb_target=dev.adb_target)

            batch_size = 3
            batches = [apps[i:i + batch_size] for i in range(0, min(len(apps), 12), batch_size)]

            for batch_idx, batch in enumerate(batches):
                app_list = ", ".join(batch)
                steps_per_app = 25
                prompt = (f"Open Google Play Store and install these apps one by one: "
                          f"{app_list}. For each: search by name, tap Install, wait for "
                          f"it to complete, then search for the next. Skip any requiring payment.")

                try:
                    task = agent.start_task(prompt, max_steps=steps_per_app * len(batch))
                    task_id = task.get("task_id", "")
                except Exception as e:
                    logger.warning(f"App install batch {batch_idx} failed to start: {e}")
                    continue

                for _ in range(120):
                    await asyncio.sleep(5)
                    try:
                        status = agent.get_task_status(task_id)
                        if status.get("status") in ("completed", "failed", "stopped"):
                            logger.info(f"App install batch {batch_idx+1}/{len(batches)}: "
                                         f"{status.get('status')} ({status.get('steps_taken', 0)} steps)")
                            break
                    except Exception:
                        continue

                await asyncio.sleep(3)
        else:
            logger.warning("AI agent unavailable — using ADB sideload fallback for app install")

        # Verify + sideload fallback: check which apps are missing and sideload from cache
        sideloaded = await asyncio.to_thread(self._adb_sideload_apps, dev.adb_target, bundles)
        if sideloaded > 0:
            logger.info(f"ADB sideload fallback: {sideloaded} apps installed/verified")

    async def _stage_wallet(self, job: WorkflowJob, card_data: Dict):
        """Stage: Set up wallet via ADB data injection."""
        if not card_data.get("number"):
            logger.info("No card data — skipping wallet stage")
            return

        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from wallet_provisioner import WalletProvisioner
        persona = job.config.get("persona", {})
        prov = WalletProvisioner(adb_target=dev.adb_target)
        result = prov.provision_card(
            card_number=card_data["number"],
            exp_month=card_data.get("exp_month", 12),
            exp_year=card_data.get("exp_year", 2027),
            cardholder=card_data.get("cardholder", persona.get("name", "")),
            cvv=card_data.get("cvv", ""),
            persona_email=persona.get("email", ""),
            persona_name=persona.get("name", ""),
        )
        if result.success_count < 2:
            errors = "; ".join(result.errors[:3]) if result.errors else "unknown"
            raise RuntimeError(f"Wallet injection failed ({result.success_count}/4): {errors}")
        logger.info(f"Wallet provisioned: {result.card_network} ****{result.card_last4} "
                     f"({result.success_count}/4 targets)")

    def _adb_warmup_fallback(self, adb_target: str, warmup_type: str):
        """Fallback: ADB-scripted warmup when AI agent is unavailable.
        Opens browser/YouTube via intents, performs basic navigation via input events."""
        import subprocess
        import random as _rnd

        def _sh(cmd: str, timeout: int = 15):
            subprocess.run(
                ["adb", "-s", adb_target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout,
            )

        def _sleep(lo: float = 1.0, hi: float = 3.0):
            time.sleep(_rnd.uniform(lo, hi))

        if warmup_type == "browse":
            urls = [
                "https://www.google.com/search?q=weather+forecast",
                "https://www.google.com/search?q=best+restaurants+near+me",
                "https://www.wikipedia.org",
                "https://news.google.com",
                "https://www.reddit.com",
            ]
            for url in urls[:3]:
                _sh(f"am start -a android.intent.action.VIEW -d '{url}'")
                _sleep(3.0, 6.0)
                # Scroll down a few times
                for _ in range(_rnd.randint(2, 5)):
                    _sh(f"input swipe 540 1200 540 400 {_rnd.randint(300, 600)}")
                    _sleep(1.0, 2.5)
            logger.info("ADB warmup (browse): visited 3 URLs with scroll gestures")

        elif warmup_type == "youtube":
            _sh("am start -a android.intent.action.VIEW -d 'https://www.youtube.com'")
            _sleep(4.0, 7.0)
            # Scroll feed
            for _ in range(_rnd.randint(3, 6)):
                _sh(f"input swipe 540 1200 540 400 {_rnd.randint(300, 600)}")
                _sleep(1.5, 3.0)
            # Tap center to play a video
            _sh("input tap 540 600")
            _sleep(15.0, 25.0)  # Watch for 15-25 seconds
            _sh("input keyevent KEYCODE_BACK")
            _sleep(2.0, 4.0)
            logger.info("ADB warmup (youtube): scrolled feed + watched 1 video")

    async def _stage_warmup(self, job: WorkflowJob, warmup_type: str,
                            aging: Dict):
        """Stage: Run warmup browsing/YouTube sessions (agent with ADB fallback)."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        # Check if AI agent is available
        if not self._check_agent_available(dev.adb_target):
            logger.warning(f"AI agent unavailable — using ADB warmup fallback ({warmup_type})")
            await asyncio.to_thread(self._adb_warmup_fallback, dev.adb_target, warmup_type)
            return

        from device_agent import DeviceAgent
        agent = DeviceAgent(adb_target=dev.adb_target)

        if warmup_type == "browse":
            prompt = ("Open the web browser and browse naturally. Visit Google, search for "
                      "'best restaurants near me', click a result, scroll through it. "
                      "Then search for 'weather forecast', view results. Visit 2 more "
                      "websites naturally.")
        else:
            prompt = ("Open YouTube. Browse the home feed, watch a video for 30 seconds, "
                      "scroll the feed, watch another video. Like one video.")

        try:
            task = agent.start_task(prompt, max_steps=25)
            task_id = task.get("task_id", "")
        except Exception as e:
            logger.warning(f"Agent warmup start failed: {e} — using ADB fallback")
            await asyncio.to_thread(self._adb_warmup_fallback, dev.adb_target, warmup_type)
            return

        # Poll agent directly (up to 15 min)
        for _ in range(180):
            await asyncio.sleep(5)
            try:
                status = agent.get_task_status(task_id)
                if status.get("status") in ("completed", "failed", "stopped"):
                    logger.info(f"Warmup {warmup_type}: {status.get('status')}")
                    return
            except Exception:
                continue

    async def _stage_verify(self, job: WorkflowJob):
        """Stage: Generate verification report + deep wallet verification."""
        from aging_report import AgingReporter
        reporter = AgingReporter(device_manager=self.dm)
        report = await reporter.generate(device_id=job.device_id)
        job.report = report.to_dict()
        logger.info(f"Verify report: {report.overall_grade} ({report.overall_score}/100)")

        # Deep wallet verification (13-check)
        try:
            from wallet_verifier import WalletVerifier
            dev = self.dm.get_device(job.device_id) if self.dm else None
            target = dev.adb_target if dev else "127.0.0.1:6520"
            wv = WalletVerifier(adb_target=target)
            wallet_report = wv.verify()
            job.report["wallet_verification"] = wallet_report.to_dict()
            logger.info(f"Wallet verify: {wallet_report.passed}/{wallet_report.total} ({wallet_report.grade})")
        except Exception as e:
            logger.warning(f"Wallet verification failed: {e}")

    # ─── V12 STAGES ────────────────────────────────────────────────

    async def _stage_ghost_sim(self, job: WorkflowJob, persona: Dict, country: str):
        """Stage: Ghost SIM v2.0 — configure virtual SIM before forge."""
        from ghost_sim import GhostSIM
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        carrier = persona.get("carrier", "tmobile_us")
        location = persona.get("location", "nyc")
        phone = persona.get("phone", "+12125551234")
        gsim = GhostSIM(adb_target=target)
        sim_config = gsim.configure(carrier=carrier, phone=phone, location=location)
        job.report["ghost_sim"] = {"carrier": carrier, "location": location,
                                    "imsi": sim_config.imsi, "msisdn": sim_config.msisdn}
        logger.info("Ghost SIM configured", extra={"carrier": carrier, "country": country})
        # Start signal jitter daemon in background
        gsim.start_signal_daemon()

    async def _stage_hce(self, job: WorkflowJob, card_data: Optional[Dict]):
        """Stage: HCE Bridge — register NFC payment service with DPAN."""
        if not card_data or not card_data.get("number"):
            logger.info("HCE skipped — no card data")
            return
        from hce_bridge import HCEBridge
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        wallet_data = job.report.get("wallet", {})
        dpan = wallet_data.get("dpan", "")
        network = card_data.get("network", "visa")
        bridge = HCEBridge(adb_target=target)
        hce_config = bridge.configure(
            dpan=dpan or card_data["number"],
            exp_month=int(card_data.get("exp_month", 12)),
            exp_year=int(card_data.get("exp_year", 2027)),
            cardholder=card_data.get("cardholder", card_data.get("name", "CARDHOLDER")),
            network=network,
        )
        bridge.register_hce_service()
        job.report["hce"] = {"dpan": hce_config.dpan, "network": network}
        logger.info("HCE bridge provisioned", extra={"network": network})

    async def _stage_play_integrity(self, job: WorkflowJob):
        """Stage: Play Integrity defense — prop hardening + PIF config."""
        from play_integrity_spoofer import PlayIntegritySpoofer
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        preset_name = dev.config.get("model", "samsung_s25_ultra") if dev else "samsung_s25_ultra"
        spoofer = PlayIntegritySpoofer(adb_target=target)
        result = spoofer.apply_integrity_defense(tier="strong", preset=preset_name)
        job.report["play_integrity"] = result
        logger.info("Play Integrity defense applied", extra={"tier": "strong"})

    async def _stage_sensor_warmup(self, job: WorkflowJob):
        """Stage: Sensor daemon — start continuous sensor injection."""
        from sensor_simulator import SensorSimulator
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        preset_name = dev.config.get("model", "samsung_s25_ultra") if dev else "samsung_s25_ultra"
        brand = "samsung" if "samsung" in preset_name else "google"
        sim = SensorSimulator(adb_target=target, device_profile=brand)
        sim.start_continuous_injection(interval_s=2)
        job.report["sensor_warmup"] = {"status": "running", "profile": brand}
        logger.info("Sensor daemon started", extra={"profile": brand})

    async def _stage_immune_watchdog(self, job: WorkflowJob):
        """Stage: Immune Watchdog — deploy honeypots + monitoring."""
        from immune_watchdog import ImmuneWatchdog
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        wd = ImmuneWatchdog(adb_target=target)
        deploy_result = wd.deploy()
        wd.start_monitoring(interval_s=30)
        scan = wd.run_full_scan()
        job.report["immune_watchdog"] = {
            "deploy": deploy_result,
            "initial_scan": scan,
        }
        logger.info("Immune watchdog deployed", extra={"risk": scan.get("risk_score", -1)})

    async def _stage_lockdown(self, job: WorkflowJob):
        """Stage: Production lockdown — disable ADB and developer options.

        Only called when disable_adb=True was passed to start_workflow.
        Disables ADB to remove the biggest forensic indicator that a device
        is under automated control. Device becomes unmanageable via ADB
        after this — only use in production deployments.
        """
        import subprocess
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        logger.info(f"Lockdown: disabling ADB on {target}")
        try:
            cmds = [
                "settings put global adb_enabled 0",
                "settings put global development_settings_enabled 0",
                "settings put secure adb_notify 0",
                "setprop service.adb.tcp.port -1",
                "setprop persist.sys.usb.config mtp",
            ]
            subprocess.run(
                ["adb", "-s", target, "shell", ";".join(cmds)],
                capture_output=True, text=True, timeout=15,
            )
            logger.info("Lockdown complete — ADB disabled")
        except Exception as e:
            logger.warning(f"Lockdown failed: {e}")

    # ─── PUBLIC API ──────────────────────────────────────────────────

    def get_status(self, job_id: str) -> Optional[WorkflowJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[Dict]:
        return [j.to_dict() for j in self._jobs.values()]
