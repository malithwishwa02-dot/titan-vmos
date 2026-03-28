# Titan V13.0 — Core modules
"""
Core package exports for cleaner imports.
Usage:
    from core import AnomalyPatcher, ProfileInjector, AndroidProfileForge
    from core.exceptions import TitanError, ADBConnectionError
    from core.models import PatchPhase, JobStatus, DeviceState
    from core.vmos_cloud_module import VMOSCloudBridge, VMOSDeviceModifier
"""

from core.exceptions import (
    ADBCommandError,
    ADBConnectionError,
    DeviceNotFoundError,
    DeviceOfflineError,
    GAppsBootstrapError,
    InjectionError,
    PatchPhaseError,
    ProfileForgeError,
    ResetpropError,
    TitanError,
    WalletProvisionError,
)
from core.vmos_cloud_module import (
    VMOSCloudBridge,
    VMOSConfig,
    VMOSDeviceModifier,
    VMOSInstance,
    VMOSResponse,
)

__all__ = [
    "ADBCommandError",
    "ADBConnectionError",
    "DeviceNotFoundError",
    "DeviceOfflineError",
    "GAppsBootstrapError",
    "InjectionError",
    "PatchPhaseError",
    "ProfileForgeError",
    "ResetpropError",
    "TitanError",
    "VMOSCloudBridge",
    "VMOSConfig",
    "VMOSDeviceModifier",
    "VMOSInstance",
    "VMOSResponse",
    "WalletProvisionError",
]
