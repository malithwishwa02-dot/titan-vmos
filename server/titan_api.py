"""
Titan V13.0 — Unified API Server (Zero-Gaps)
FastAPI backend serving all 18 routers + device management.
Consolidated from V11.3 dev + prod into single source of truth.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ─── Path setup (must be FIRST, before any local imports) ─────────────
SERVER_DIR = Path(__file__).parent
PROJECT_ROOT = SERVER_DIR.parent
CORE_DIR = PROJECT_ROOT / "core"
OPT_TITAN_CORE = Path("/opt/titan/core")
# WORKSPACE core must come BEFORE system /opt/titan/core (reverse order for insert(0))
for _p in [str(OPT_TITAN_CORE), str(CORE_DIR), str(PROJECT_ROOT), str(SERVER_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
V11_CORE = os.environ.get("PYTHONPATH", "").split(":")
for p in V11_CORE:
    if p and p not in sys.path and p:
        sys.path.insert(0, p)

# Load .env BEFORE any middleware or config reads os.environ
from dotenv import load_dotenv
_env_candidates = [
    PROJECT_ROOT / ".env",
    Path("/opt/titan/.env"),
]
for _ef in _env_candidates:
    if _ef.exists():
        load_dotenv(_ef, override=False)
        break

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from response_models import HealthResponse, LivenessResponse, ReadinessResponse


from device_manager import DeviceManager
from json_logger import configure_all_loggers
from device_recovery import DeviceRecoveryManager
from metrics import get_metrics
from alerting import get_alert_manager, get_health_monitor

# Configure JSON logging for all components
configure_all_loggers()
logger = logging.getLogger("titan.api")

# Global recovery manager
recovery_manager: Optional[DeviceRecoveryManager] = None

# Health monitor
health_monitor = None

# Metrics collector
metrics = get_metrics()

# Alert manager
alert_manager = get_alert_manager()

# ═══════════════════════════════════════════════════════════════════════
# APP INIT
# ═══════════════════════════════════════════════════════════════════════

app = FastAPI(title="Titan V13.0 Antidetect Device Platform (Cuttlefish)", version="13.0.0")

CONSOLE_DIR = Path(__file__).parent.parent / "console"

# ─── Middleware ────────────────────────────────────────────────────────
from middleware.auth import AuthMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.cpu_governor import cpu_governor

app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
_default_cors = "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000,http://127.0.0.1:8080"
_cors_origins = [
    o.strip()
    for o in os.getenv("TITAN_CORS_ORIGINS", _default_cors).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Desktop-only mode — API only accessible from local Electron apps
DESKTOP_ONLY = True

# Serve static console files
if CONSOLE_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(CONSOLE_DIR)), name="static")

# Device manager singleton
dm = DeviceManager()

# Register DM with FastAPI Depends system
from deps import set_device_manager
set_device_manager(dm)

# ─── Register Routers ─────────────────────────────────────────────────
from routers import devices, stealth, genesis, provision, agent, intel, network
from routers import cerberus, targets, kyc, admin, dashboard, settings
from routers import bundles, ai, ws, training, viewer
from routers import vmos

# Initialize routers that need the device manager (legacy pattern, kept for compat)
for mod in [devices, stealth, genesis, provision, agent, kyc, admin, dashboard, bundles, ws, ai, training]:
    mod.init(dm)

# Initialize VMOS router with credentials from environment
vmos.init()

# Include all routers
for r in [devices, stealth, genesis, provision, agent, intel, network, cerberus,
          targets, kyc, admin, dashboard, settings, bundles, ai, ws, training, viewer, vmos]:
    app.include_router(r.router)


# ═══════════════════════════════════════════════════════════════════════
# CONSOLE — Serves the SPA
# ═══════════════════════════════════════════════════════════════════════

@app.get("/ready", response_model=ReadinessResponse)
@app.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check():
    """Kubernetes-style readiness probe - is the app ready to serve traffic?"""
    try:
        # Check if at least one device is available
        devs = dm.list_devices()
        has_device = any(
            (d.get("state", "") if isinstance(d, dict) else getattr(d, "state", ""))
            in ("ready", "patched", "running", "online")
            for d in devs
        )
        return {"ready": True, "devices": len(devs), "online": has_device}
    except Exception as e:
        return {"ready": False, "error": str(e)}


@app.get("/live", response_model=LivenessResponse)
@app.get("/health/live", response_model=LivenessResponse)
async def liveness_check():
    """Kubernetes-style liveness probe - is the app alive?"""
    return {"alive": True, "version": "13.0.0"}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check: ADB, Ollama, disk, memory."""
    import shutil, subprocess as _sp
    import time
    start = time.time()
    health = {"status": "ok", "checks": {}, "timestamp": int(start)}
    # ADB
    try:
        devs = dm.list_devices()
        adb_targets = [
            (d.get("adb_target", "") if isinstance(d, dict) else getattr(d, "adb_target", ""))
            for d in devs
            if (d.get("state", "") if isinstance(d, dict) else getattr(d, "state", ""))
            in ("ready", "patched", "running", "online")
        ]
        adb_ok = False
        for t in adb_targets[:1]:
            r = _sp.run(["adb", "-s", t, "shell", "echo ok"], capture_output=True, text=True, timeout=5)
            adb_ok = "ok" in r.stdout
        health["checks"]["adb"] = {"ok": adb_ok, "devices": len(devs)}
    except Exception as e:
        health["checks"]["adb"] = {"ok": False, "error": str(e)}
    # Ollama
    try:
        import httpx
        r = httpx.get(os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435") + "/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        health["checks"]["ollama"] = {"ok": True, "models": len(models)}
    except Exception:
        health["checks"]["ollama"] = {"ok": False, "models": 0}
    # Disk
    try:
        usage = shutil.disk_usage("/")
        free_gb = round(usage.free / (1024**3), 1)
        health["checks"]["disk"] = {"ok": free_gb > 5, "free_gb": free_gb}
    except Exception:
        health["checks"]["disk"] = {"ok": False}
    # Memory
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {l.split(":")[0].strip(): int(l.split(":")[1].strip().split()[0]) for l in lines[:3]}
        avail_gb = round(mem.get("MemAvailable", 0) / (1024**2), 1)
        health["checks"]["memory"] = {"ok": avail_gb > 1, "available_gb": avail_gb}
    except Exception:
        health["checks"]["memory"] = {"ok": False}
    if not all(c.get("ok") for c in health["checks"].values()):
        health["status"] = "degraded"
    return health


API_VERSION = "13.0.0"


@app.get("/api/version")
async def api_version():
    """Return current API version info."""
    return {
        "version": API_VERSION,
        "name": "Titan",
        "codename": "V13",
        "api": "FastAPI/Uvicorn",
    }


@app.get("/api/capabilities")
async def capabilities():
    """Report which optional modules are actually available vs stub."""
    caps = {}
    # Network modules
    for name, imp in [
        ("mullvad_vpn", "mullvad_vpn"),
        ("forensic_monitor", "forensic_monitor"),
        ("network_shield", "network_shield"),
        ("proxy_scorer", "proxy_quality_scorer"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Intel modules
    for name, imp in [
        ("ai_intelligence", "ai_intelligence"),
        ("target_intelligence", "target_intelligence"),
        ("osint_orchestrator", "osint_orchestrator"),
        ("three_ds_strategy", "three_ds_strategy"),
        ("onion_search", "onion_search"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Cerberus modules
    for name, imp in [
        ("cerberus_engine", "cerberus_core"),
        ("bin_database", "bin_database"),
        ("bin_scanner", "bin_scanner"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Targets modules
    for name, imp in [
        ("web_check", "web_check_engine"),
        ("waf_detector", "waf_detector"),
        ("dns_intel", "dns_intel"),
        ("target_profiler", "target_profiler"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # KYC modules
    for name, imp in [
        ("gpu_reenact", "gpu_reenact_client"),
        ("kyc_controller", "kyc_core"),
        ("kyc_voice", "kyc_voice"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    available = sum(1 for v in caps.values() if v)
    return {
        "total": len(caps),
        "available": available,
        "stub": len(caps) - available,
        "modules": caps,
    }


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    # Update device state counts
    devices = dm.list_devices()
    states = {}
    for dev in devices:
        states[dev.state] = states.get(dev.state, 0) + 1
    metrics.update_device_states(states)
    
    # Export as Prometheus format
    return Response(content=metrics.to_prometheus_format(), media_type="text/plain")


@app.get("/api/metrics")
async def api_metrics_endpoint():
    """JSON metrics endpoint."""
    # Update device state counts
    devices = dm.list_devices()
    states = {}
    for dev in devices:
        states[dev.state] = states.get(dev.state, 0) + 1
    metrics.update_device_states(states)
    
    return metrics.to_dict()


@app.get("/", response_class=HTMLResponse)
async def console_root():
    index = CONSOLE_DIR / "index.html"
    content = index.read_text() if index.exists() else "<h1>Titan V13.0 — Console not found. Deploy console/index.html</h1>"
    resp = HTMLResponse(content)
    # Inject API auth token as cookie so console JS can read it
    secret = os.environ.get("TITAN_API_SECRET", "").strip()
    if secret and secret != "change-me-to-a-secure-random-string":
        resp.set_cookie("titan_token", secret, httponly=False, samesite="strict", path="/")
    return resp



@app.get("/favicon.ico")
async def favicon():
    # Inline 1x1 transparent ICO to suppress 404s
    ico = CONSOLE_DIR / "favicon.ico"
    if ico.exists():
        return Response(content=ico.read_bytes(), media_type="image/x-icon")
    # Minimal 16x16 ICO header (transparent)
    import struct
    bmp = b'\x28\x00\x00\x00\x10\x00\x00\x00\x20\x00\x00\x00\x01\x00\x20\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    pixels = b'\x00\xd4\xff\xff' * 256  # 16x16 cyan pixels
    mask = b'\x00' * 64
    img_data = bmp + pixels + mask
    header = struct.pack('<HHH', 0, 1, 1)
    entry = struct.pack('<BBBBHHII', 16, 16, 0, 0, 1, 32, len(img_data), 22)
    return Response(content=header + entry + img_data, media_type="image/x-icon")


# ═══════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    global recovery_manager, health_monitor
    logger.info("Titan V13.0 API Server starting")
    logger.info(f"Devices loaded: {len(dm.list_devices())}")
    logger.info(f"Console dir: {CONSOLE_DIR}")
    logger.info(f"Core dir: {CORE_DIR}")
    await cpu_governor.start()
    
    # Start device recovery manager
    try:
        recovery_manager = DeviceRecoveryManager(dm, check_interval=60, boot_timeout=300)
        await recovery_manager.start()
        logger.info("Device recovery manager started")
    except Exception as e:
        logger.warning(f"Device recovery manager init failed: {e}")
    
    # Start health monitor
    try:
        health_monitor = get_health_monitor(dm)
        await health_monitor.start()
        logger.info("Health monitor started")
    except Exception as e:
        logger.warning(f"Health monitor init failed: {e}")
    
    # Start ADB connection watchdog for all ready/patched devices
    try:
        from adb_utils import start_connection_watchdog
        targets = [d.adb_target for d in dm.list_devices() if d.state in ("ready", "patched", "running")]
        if targets:
            start_connection_watchdog(targets, check_interval=30)
            logger.info(f"ADB watchdog started for {len(targets)} devices")
    except Exception as e:
        logger.warning(f"ADB watchdog init failed: {e}")

    # First-run auto-provisioner (creates default device if none exist)
    try:
        from first_run import maybe_start_first_run
        await maybe_start_first_run(dm)
    except Exception as e:
        logger.warning(f"First-run provisioner init failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown - drain in-flight requests and cleanup."""
    global recovery_manager, health_monitor
    logger.info("Titan V13.0 API Server shutting down gracefully")
    
    # Stop health monitor
    if health_monitor:
        try:
            await health_monitor.stop()
            logger.info("Health monitor stopped")
        except Exception as e:
            logger.warning(f"Error stopping health monitor: {e}")
    
    # Stop recovery manager
    if recovery_manager:
        try:
            await recovery_manager.stop()
            logger.info("Device recovery manager stopped")
        except Exception as e:
            logger.warning(f"Error stopping recovery manager: {e}")
    
    # Stop CPU governor
    try:
        await cpu_governor.stop()
    except Exception:
        pass
    
    # Allow in-flight requests to complete (up to 10 seconds)
    import asyncio
    await asyncio.sleep(2)
    
    logger.info("Shutdown complete")

