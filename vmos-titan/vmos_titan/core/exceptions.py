"""
Titan V11.3 — Structured Exception Hierarchy
All Titan-specific exceptions inherit from TitanError for unified
catch-all handling and structured error reporting.
"""

from typing import Optional


class TitanError(Exception):
    """Base exception for all Titan errors."""

    def __init__(self, message: str = "", code: str = "TITAN_ERROR") -> None:
        self.code = code
        super().__init__(message)


# ═══════════════════════════════════════════════════════════════════════
# ADB / Device Errors
# ═══════════════════════════════════════════════════════════════════════

class ADBConnectionError(TitanError):
    """ADB connection failed after retries."""

    def __init__(self, device_id: str, port: int = 0, attempts: int = 1) -> None:
        self.device_id = device_id
        self.port = port
        self.attempts = attempts
        super().__init__(
            f"ADB connection to {device_id}:{port} failed after {attempts} attempts",
            code="ADB_CONNECTION_ERROR",
        )


class ADBCommandError(TitanError):
    """An ADB shell command failed."""

    def __init__(self, command: str, output: str = "", device_id: str = "") -> None:
        self.command = command
        self.output = output
        self.device_id = device_id
        super().__init__(
            f"ADB command failed on {device_id}: {command[:80]}",
            code="ADB_COMMAND_ERROR",
        )


class DeviceOfflineError(TitanError):
    """Device is offline or not responding."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"Device {device_id} is offline", code="DEVICE_OFFLINE")


class DeviceNotFoundError(TitanError):
    """Requested device not found in DeviceManager."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"Device not found: {device_id}", code="DEVICE_NOT_FOUND")


# ═══════════════════════════════════════════════════════════════════════
# Patch / Stealth Errors
# ═══════════════════════════════════════════════════════════════════════

class PatchPhaseError(TitanError):
    """A specific anomaly patcher phase failed."""

    def __init__(self, phase: str, vector: str = "", reason: str = "") -> None:
        self.phase = phase
        self.vector = vector
        msg = f"Phase {phase}"
        if vector:
            msg += f" vector {vector}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, code="PATCH_PHASE_ERROR")


class PatchPersistenceError(TitanError):
    """Patch persistence (reboot survival) failed."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            f"Patch persistence failed: {reason}" if reason else "Patch persistence failed",
            code="PATCH_PERSISTENCE_ERROR",
        )


class ResetpropError(TitanError):
    """resetprop binary not available or failed."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            f"resetprop error: {reason}" if reason else "resetprop not available",
            code="RESETPROP_ERROR",
        )


# ═══════════════════════════════════════════════════════════════════════
# Profile / Injection Errors
# ═══════════════════════════════════════════════════════════════════════

class ProfileForgeError(TitanError):
    """Profile generation/forging failed."""

    def __init__(self, reason: str = "", profile_id: str = "") -> None:
        self.profile_id = profile_id
        super().__init__(
            f"Profile forge failed ({profile_id}): {reason}" if profile_id else f"Profile forge failed: {reason}",
            code="PROFILE_FORGE_ERROR",
        )


class InjectionError(TitanError):
    """Profile injection into device failed."""

    def __init__(self, target: str = "", reason: str = "", device_id: str = "") -> None:
        self.target = target
        self.device_id = device_id
        msg = f"Injection failed"
        if target:
            msg += f" ({target})"
        if device_id:
            msg += f" on {device_id}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, code="INJECTION_ERROR")


# ═══════════════════════════════════════════════════════════════════════
# Wallet / Payment Errors
# ═══════════════════════════════════════════════════════════════════════

class WalletProvisionError(TitanError):
    """Wallet provisioning failed."""

    def __init__(self, reason: str = "", card_last4: str = "") -> None:
        self.card_last4 = card_last4
        msg = "Wallet provisioning failed"
        if card_last4:
            msg += f" (card *{card_last4})"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, code="WALLET_PROVISION_ERROR")


# ═══════════════════════════════════════════════════════════════════════
# GApps / Bootstrap Errors
# ═══════════════════════════════════════════════════════════════════════

class GAppsBootstrapError(TitanError):
    """GApps installation/bootstrap failed."""

    def __init__(self, reason: str = "", package: str = "") -> None:
        self.package = package
        msg = "GApps bootstrap failed"
        if package:
            msg += f" ({package})"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, code="GAPPS_BOOTSTRAP_ERROR")


# ═══════════════════════════════════════════════════════════════════════
# Workflow / Pipeline Errors
# ═══════════════════════════════════════════════════════════════════════

class WorkflowError(TitanError):
    """Workflow engine stage failed."""

    def __init__(self, stage: str = "", reason: str = "") -> None:
        self.stage = stage
        super().__init__(
            f"Workflow stage '{stage}' failed: {reason}" if stage else f"Workflow failed: {reason}",
            code="WORKFLOW_ERROR",
        )


class ProvisionError(TitanError):
    """Full provisioning pipeline failed."""

    def __init__(self, step: str = "", reason: str = "", job_id: str = "") -> None:
        self.step = step
        self.job_id = job_id
        msg = "Provisioning failed"
        if step:
            msg += f" at step '{step}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, code="PROVISION_ERROR")
