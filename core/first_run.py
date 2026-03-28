"""
Titan V12 — First-Run Auto-Provisioner

If no devices exist on startup, automatically creates and provisions
a default device so the operator has a ready-to-use instance immediately
after install.

Called from titan_api.py startup hook. Runs in a background thread to avoid
blocking the API server boot.
"""

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("titan.first_run")

# Sentinel file that prevents first-run from re-triggering after first completion
FIRST_RUN_MARKER = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / ".first_run_complete"


def is_first_run() -> bool:
    """Check whether first-run provisioning should execute."""
    return not FIRST_RUN_MARKER.exists()


def mark_first_run_complete() -> None:
    """Write sentinel so first-run never triggers again."""
    FIRST_RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
    FIRST_RUN_MARKER.write_text("1")
    logger.info("First-run complete — marker written", extra={"marker": str(FIRST_RUN_MARKER)})


def run_first_provision(device_manager) -> None:
    """
    Background thread entry point. Creates a default device, patches it,
    and forges an initial profile.

    Skips GApps bootstrap if MindTheGapps is pre-baked into the system image
    (detected by build/build-image.sh during .deb assembly).
    """
    try:
        _provision_default_device(device_manager)
    except Exception as e:
        logger.error("First-run provisioning failed", extra={"error": str(e)}, exc_info=True)


def _provision_default_device(dm) -> None:
    """Create, boot, and patch the first device."""
    from device_manager import CreateDeviceRequest

    # If devices already exist, just mark and return
    existing = dm.list_devices()
    if existing:
        logger.info("Devices already exist — skipping first-run", extra={"count": len(existing)})
        mark_first_run_complete()
        return

    logger.info("First-run: creating default device (Samsung S25 Ultra, US)")

    req = CreateDeviceRequest(
        model="samsung_s25_ultra",
        country="US",
        carrier="tmobile_us",
        android_version="14",
        memory_mb=4096,
        cpus=4,
    )

    # create_device is async, run it in event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        device = loop.run_until_complete(dm.create_device(req))
        loop.close()
    except Exception as e:
        logger.error("First-run: device creation failed", extra={"error": str(e)})
        return

    if not device:
        logger.error("First-run: device creation returned None")
        return

    device_id = device.id
    adb_target = device.adb_target
    logger.info("First-run: device created, waiting for boot", extra={"device_id": device_id, "adb": adb_target})

    # --- GApps bootstrap (skip if pre-baked) ---
    gapps_prebaked = _check_gapps_prebaked()
    if not gapps_prebaked:
        try:
            from gapps_bootstrap import GAppsBootstrap
            bootstrap = GAppsBootstrap(adb_target)
            result = bootstrap.run()
            logger.info("First-run: GApps bootstrap done", extra={"result": str(result)[:200]})
        except Exception as e:
            logger.warning("First-run: GApps bootstrap failed (may already be present)", extra={"error": str(e)})
    else:
        logger.info("First-run: GApps pre-baked in system image — skipping bootstrap")

    # --- Anomaly patch ---
    try:
        from anomaly_patcher import AnomalyPatcher
        patcher = AnomalyPatcher(adb_target)
        report = patcher.full_patch(
            preset_name="samsung_s25_ultra",
            carrier_name="tmobile_us",
            location_name="new_york",
            lockdown=False,
            age_days=90,
        )
        logger.info("First-run: anomaly patch complete", extra={
            "success": report.success_count if hasattr(report, 'success_count') else 'unknown',
            "total": report.total_count if hasattr(report, 'total_count') else 'unknown',
        })
    except Exception as e:
        logger.warning("First-run: anomaly patcher failed", extra={"error": str(e)})

    # --- Profile forge ---
    try:
        from android_profile_forge import AndroidProfileForge
        forge = AndroidProfileForge()
        profile = forge.forge(
            persona_name="Alex Thompson",
            persona_email="alex.thompson.us@gmail.com",
            persona_phone="+12125551234",
            country="US",
            archetype="professional",
            age_days=90,
            carrier="tmobile_us",
            location="new_york",
            device_model="samsung_s25_ultra",
        )
        logger.info("First-run: profile forged", extra={"trust_keys": list(profile.keys())[:10]})

        # --- Inject profile ---
        from profile_injector import ProfileInjector
        injector = ProfileInjector(adb_target)
        result = injector.inject_full_profile(profile)
        logger.info("First-run: profile injected", extra={"result": str(result)[:200]})
    except Exception as e:
        logger.warning("First-run: profile forge/inject failed", extra={"error": str(e)})

    mark_first_run_complete()
    logger.info("First-run provisioning complete", extra={"device_id": device_id})


def _check_gapps_prebaked() -> bool:
    """
    Check if MindTheGapps was baked into the system image at build time.
    The build-image.sh pipeline writes an image-info.json with gapps_injected=true.
    """
    info_paths = [
        Path("/opt/titan/images/image-info.json"),
        Path(os.environ.get("CVD_IMAGES_DIR", "/opt/titan/images")) / "image-info.json",
    ]
    for p in info_paths:
        if p.exists():
            try:
                import json
                info = json.loads(p.read_text())
                return info.get("gapps_injected", False)
            except Exception:
                pass
    return False


async def maybe_start_first_run(device_manager) -> Optional[threading.Thread]:
    """
    Called from titan_api.py startup. If first-run is needed, spawns a background
    thread and returns it (for optional join). If not needed, returns None.
    """
    if not is_first_run():
        logger.info("First-run already completed — skipping")
        return None

    logger.info("First-run triggered — spawning background provisioner")
    t = threading.Thread(
        target=run_first_provision,
        args=(device_manager,),
        name="titan-first-run",
        daemon=True,
    )
    t.start()
    return t
