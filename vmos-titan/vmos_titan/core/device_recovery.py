"""
Titan V11.3 → V12 — Device Recovery Manager
Monitors device health and automatically recovers stuck devices.
V12: Added reboot detection + auto re-injection of profile data.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Callable, Any, Dict

logger = logging.getLogger("titan.device-recovery")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) if "os" in dir() else Path("/opt/titan/data")

import os
TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))

logger = logging.getLogger("titan.device-recovery")


class DeviceRecoveryManager:
    """Monitors and recovers stuck devices. V12: Auto-reinjects profile data after reboot."""
    
    def __init__(
        self,
        device_manager: Any,
        check_interval: int = 60,
        boot_timeout: int = 300,
        error_timeout: int = 600,
    ):
        self.dm = device_manager
        self.check_interval = check_interval
        self.boot_timeout = boot_timeout
        self.error_timeout = error_timeout
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # V12: Track last known uptime per device to detect reboots
        self._last_uptime: Dict[str, float] = {}
        self._reinjection_in_progress: set = set()
    
    async def start(self):
        """Start recovery monitoring."""
        if self._running:
            logger.warning("Recovery manager already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Device recovery manager started")
    
    async def stop(self):
        """Stop recovery monitoring."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Device recovery manager stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_devices()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in recovery monitor: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_devices(self):
        """Check all devices for stuck states."""
        devices = self.dm.list_devices()
        current_time = time.time()
        
        for dev in devices:
            try:
                # Check for stuck booting state
                if dev.state == "booting":
                    elapsed = current_time - (dev.created_at if isinstance(dev.created_at, float) 
                                             else time.time())
                    if elapsed > self.boot_timeout:
                        logger.warning(
                            f"Device {dev.id} stuck in booting for {elapsed:.0f}s, restarting"
                        )
                        await self._recover_device(dev.id, "restart")
                
                # Check for stuck error state
                elif dev.state == "error":
                    elapsed = current_time - (dev.created_at if isinstance(dev.created_at, float)
                                             else time.time())
                    if elapsed > self.error_timeout:
                        logger.warning(
                            f"Device {dev.id} in error state for {elapsed:.0f}s, destroying"
                        )
                        await self._recover_device(dev.id, "destroy")
                
                # Check ADB connectivity for ready devices
                elif dev.state in ("ready", "patched", "running"):
                    if not await self._is_device_responsive(dev.adb_target):
                        logger.warning(f"Device {dev.id} not responsive, reconnecting")
                        await self._recover_device(dev.id, "reconnect")
                    else:
                        # V12: Reboot detection via uptime monitoring
                        await self._check_reboot(dev)
            
            except Exception as e:
                logger.error(f"Error checking device {dev.id}: {e}")
    
    async def _is_device_responsive(self, adb_target: str) -> bool:
        """Check if device is responsive via ADB."""
        try:
            from adb_utils import is_device_connected
            return is_device_connected(adb_target)
        except Exception as e:
            logger.debug(f"Failed to check device responsiveness: {e}")
            return False
    
    async def _recover_device(self, device_id: str, action: str):
        """Execute recovery action on device."""
        try:
            if action == "restart":
                logger.info(f"Restarting device {device_id}")
                await self.dm.restart_device(device_id)
                logger.info(f"Device {device_id} restarted successfully")
            
            elif action == "reconnect":
                logger.info(f"Reconnecting device {device_id}")
                dev = self.dm.get_device(device_id)
                if dev:
                    from adb_utils import reconnect_device
                    success = reconnect_device(dev.adb_target, max_retries=3)
                    if success:
                        logger.info(f"Device {device_id} reconnected")
                        dev.state = "ready"
                        self.dm._save_state()
                    else:
                        logger.warning(f"Failed to reconnect device {device_id}")
            
            elif action == "destroy":
                logger.info(f"Destroying device {device_id}")
                await self.dm.destroy_device(device_id)
                logger.info(f"Device {device_id} destroyed")
        
        except Exception as e:
            logger.error(f"Recovery action '{action}' failed for device {device_id}: {e}")

    # ─── V12: REBOOT DETECTION + AUTO RE-INJECTION (A-4) ─────────────

    async def _check_reboot(self, dev: Any):
        """Detect device reboot by monitoring uptime. Trigger re-injection if detected."""
        try:
            from adb_utils import adb_shell
            uptime_str = adb_shell(dev.adb_target, "cat /proc/uptime 2>/dev/null", timeout=10)
            if not uptime_str or not uptime_str.strip():
                return

            current_uptime = float(uptime_str.strip().split()[0])
            last_uptime = self._last_uptime.get(dev.id, 0)

            if last_uptime > 0 and current_uptime < last_uptime:
                # Current uptime < last known uptime → device rebooted
                logger.warning(
                    f"REBOOT DETECTED: Device {dev.id} "
                    f"(uptime {current_uptime:.0f}s < last {last_uptime:.0f}s)"
                )
                await self._handle_reboot(dev)

            self._last_uptime[dev.id] = current_uptime

        except (ValueError, IndexError):
            pass
        except Exception as e:
            logger.debug(f"Uptime check failed for {dev.id}: {e}")

    async def _handle_reboot(self, dev: Any):
        """Handle detected reboot — re-inject profile data and re-apply patches."""
        if dev.id in self._reinjection_in_progress:
            logger.info(f"Re-injection already in progress for {dev.id}, skipping")
            return

        self._reinjection_in_progress.add(dev.id)
        try:
            logger.info(f"Starting post-reboot recovery for device {dev.id}")

            # Wait for boot to complete
            from adb_utils import adb_shell, ensure_adb_root
            for attempt in range(30):
                boot_complete = adb_shell(dev.adb_target,
                    "getprop sys.boot_completed", timeout=10)
                if boot_complete.strip() == "1":
                    break
                await asyncio.sleep(5)
            else:
                logger.error(f"Device {dev.id} did not complete boot after reboot")
                return

            ensure_adb_root(dev.adb_target)

            # 1. Re-run persistence script (patches should survive via init.d,
            #    but verify and re-apply if needed)
            adb_shell(dev.adb_target,
                "[ -x /system/etc/init.d/99-titan-patch.sh ] && "
                "sh /system/etc/init.d/99-titan-patch.sh 2>/dev/null",
                timeout=60)
            logger.info(f"  Device {dev.id}: Persistence script re-executed")

            # 2. Re-inject profile data if profile JSON exists
            profile_path = self._find_device_profile(dev.id)
            if profile_path:
                await self._reinject_profile(dev, profile_path)
            else:
                logger.warning(f"  Device {dev.id}: No profile found for re-injection")

            # 3. Re-inject wallet data if card info cached
            await self._reinject_wallet(dev)

            # 4. Restart sensor daemon
            try:
                from sensor_simulator import SensorSimulator
                sim = SensorSimulator(dev.adb_target)
                sim.start_continuous_injection(interval_s=2)
                logger.info(f"  Device {dev.id}: Sensor daemon restarted")
            except Exception as e:
                logger.warning(f"  Device {dev.id}: Sensor restart failed: {e}")

            logger.info(f"Post-reboot recovery complete for device {dev.id}")

        except Exception as e:
            logger.error(f"Post-reboot recovery failed for {dev.id}: {e}")
        finally:
            self._reinjection_in_progress.discard(dev.id)

    def _find_device_profile(self, device_id: str) -> Optional[Path]:
        """Find the most recent profile JSON for a device."""
        profiles_dir = TITAN_DATA / "profiles"
        if not profiles_dir.exists():
            return None

        # Search for profiles associated with this device
        for profile_file in sorted(profiles_dir.glob("TITAN-*.json"), reverse=True):
            try:
                data = json.loads(profile_file.read_text())
                if data.get("device_id") == device_id:
                    return profile_file
            except (json.JSONDecodeError, OSError):
                continue

        # Fallback: return most recent profile
        profiles = sorted(profiles_dir.glob("TITAN-*.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        return profiles[0] if profiles else None

    async def _reinject_profile(self, dev: Any, profile_path: Path):
        """Re-inject critical profile data after reboot."""
        try:
            profile = json.loads(profile_path.read_text())

            # Re-inject via ProfileInjector (runs in executor to avoid blocking)
            def _do_inject():
                from profile_injector import ProfileInjector
                injector = ProfileInjector(dev.adb_target)
                return injector.inject_full_profile(profile)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_inject)
            logger.info(f"  Device {dev.id}: Profile re-injected (trust={result.trust_score})")

        except Exception as e:
            logger.error(f"  Device {dev.id}: Profile re-injection failed: {e}")

    async def _reinject_wallet(self, dev: Any):
        """Re-inject wallet data if card info was previously cached."""
        wallet_cache = TITAN_DATA / "wallet_cache" / f"{dev.id}.json"
        if not wallet_cache.exists():
            return

        try:
            card_data = json.loads(wallet_cache.read_text())
            def _do_wallet():
                from wallet_provisioner import WalletProvisioner
                wp = WalletProvisioner(dev.adb_target)
                return wp.provision_card(**card_data)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_wallet)
            logger.info(f"  Device {dev.id}: Wallet re-provisioned ({result.success_count}/4)")
        except Exception as e:
            logger.error(f"  Device {dev.id}: Wallet re-injection failed: {e}")


class RecoveryMetrics:
    """Track recovery metrics."""
    
    def __init__(self):
        self.restarts = 0
        self.reconnects = 0
        self.destroys = 0
        self.last_recovery_time = 0
    
    def record_restart(self):
        """Record device restart."""
        self.restarts += 1
        self.last_recovery_time = time.time()
    
    def record_reconnect(self):
        """Record device reconnect."""
        self.reconnects += 1
        self.last_recovery_time = time.time()
    
    def record_destroy(self):
        """Record device destroy."""
        self.destroys += 1
        self.last_recovery_time = time.time()
    
    def get_stats(self) -> dict:
        """Get recovery statistics."""
        return {
            "restarts": self.restarts,
            "reconnects": self.reconnects,
            "destroys": self.destroys,
            "last_recovery_time": self.last_recovery_time,
        }
