"""
Titan V11.3 — Typed Data Models
Canonical Pydantic/dataclass models for structured data flowing through
the forge→inject→patch→verify pipeline. Provides type safety and
serialization for API responses, job state, and inter-module contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════

class PatchPhase(str, Enum):
    """All 26 anomaly patcher phases."""
    IDENTITY = "identity"
    TELEPHONY = "telephony"
    ANTI_EMULATOR = "anti_emulator"
    BUILD_VERIFICATION = "build_verification"
    RASP_EVASION = "rasp_evasion"
    GPU_GRAPHICS = "gpu_graphics"
    BATTERY = "battery"
    LOCATION = "location"
    MEDIA_HISTORY = "media_history"
    NETWORK = "network"
    GMS_INTEGRITY = "gms_integrity"
    KEYBOX_ATTESTATION = "keybox_attestation"
    GSF_ALIGNMENT = "gsf_alignment"
    SENSORS = "sensors"
    BLUETOOTH = "bluetooth"
    PROC_STERILIZE = "proc_sterilize"
    CAMERA = "camera"
    NFC_STORAGE = "nfc_storage"
    WIFI_SCAN = "wifi_scan"
    SELINUX = "selinux"
    STORAGE_ENCRYPTION = "storage_encryption"
    PROCESS_STEALTH = "process_stealth"
    AUDIO = "audio"
    KINEMATIC_INPUT = "kinematic_input"
    KERNEL_HARDENING = "kernel_hardening"
    PERSISTENCE = "persistence"


class JobStatus(str, Enum):
    """Background job lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeviceState(str, Enum):
    """Device lifecycle states in DeviceManager."""
    OFFLINE = "offline"
    BOOTING = "booting"
    ONLINE = "online"
    READY = "ready"
    PATCHED = "patched"
    RUNNING = "running"
    ERROR = "error"


class TrustGrade(str, Enum):
    """Trust score letter grades."""
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


# ═══════════════════════════════════════════════════════════════════════
# PATCH MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PatchResultItem:
    """Single patch vector result."""
    name: str
    success: bool
    detail: str = ""
    phase: str = ""


@dataclass
class PatchReport:
    """Full patch run report — returned by AnomalyPatcher.full_patch()."""
    preset: str = ""
    carrier: str = ""
    location: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    score: int = 0
    elapsed_sec: float = 0.0
    phase_timings: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preset": self.preset,
            "carrier": self.carrier,
            "location": self.location,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": self.score,
            "results": self.results,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "phase_timings": {k: round(v, 2) for k, v in self.phase_timings.items()},
        }


# ═══════════════════════════════════════════════════════════════════════
# AUDIT MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AuditCheckResult:
    """Single audit check result."""
    name: str
    passed: bool
    detail: str = ""
    category: str = ""


@dataclass
class AuditReport:
    """Full audit report — returned by AnomalyPatcher.audit()."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    score: float = 0.0
    checks: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": self.score,
            "checks": self.checks,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


# ═══════════════════════════════════════════════════════════════════════
# INJECTION MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class InjectionResult:
    """Profile injection result — returned by ProfileInjector."""
    contacts_ok: bool = False
    call_log_ok: bool = False
    sms_ok: bool = False
    browser_ok: bool = False
    cookies_ok: bool = False
    media_ok: bool = False
    wifi_ok: bool = False
    accounts_ok: bool = False
    wallet_ok: bool = False
    app_data_ok: bool = False
    trust_score: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contacts_ok": self.contacts_ok,
            "call_log_ok": self.call_log_ok,
            "sms_ok": self.sms_ok,
            "browser_ok": self.browser_ok,
            "cookies_ok": self.cookies_ok,
            "media_ok": self.media_ok,
            "wifi_ok": self.wifi_ok,
            "accounts_ok": self.accounts_ok,
            "wallet_ok": self.wallet_ok,
            "app_data_ok": self.app_data_ok,
            "trust_score": self.trust_score,
            "errors": self.errors,
        }


# ═══════════════════════════════════════════════════════════════════════
# PROFILE / PERSONA MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ProfileData:
    """Forged persona profile data."""
    profile_id: str = ""
    persona_name: str = ""
    persona_email: str = ""
    persona_phone: str = ""
    dob: str = ""
    gender: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    device_model: str = "samsung_s25_ultra"
    age_days: int = 90


@dataclass
class CardData:
    """Payment card data for wallet provisioning."""
    number: str = ""
    exp_month: int = 12
    exp_year: int = 2027
    cvv: str = ""
    cardholder: str = ""
    network: str = ""  # visa, mastercard, amex
    issuer: str = ""


# ═══════════════════════════════════════════════════════════════════════
# DEVICE INFO
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DeviceInfo:
    """Device information as tracked by DeviceManager."""
    device_id: str = ""
    adb_target: str = ""
    state: str = "offline"
    model: str = ""
    android_version: str = ""
    stealth_score: int = 0
    trust_score: int = 0
    profile_id: str = ""
    config: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# API RESPONSE MODELS (for FastAPI response_model)
# ═══════════════════════════════════════════════════════════════════════

try:
    from pydantic import BaseModel

    class HealthResponse(BaseModel):
        status: str = "ok"
        checks: Dict[str, Any] = {}
        timestamp: int = 0
        elapsed_ms: float = 0.0

    class ProfileCreateResponse(BaseModel):
        profile_id: str
        persona_name: str = ""
        persona_email: str = ""
        age_days: int = 0
        device_model: str = ""

    class ProvisionStatusResponse(BaseModel):
        status: str
        job_id: str = ""
        device_id: str = ""
        step: str = ""
        step_n: int = 0
        patch_score: Optional[int] = None
        trust_score: Optional[int] = None
        error: Optional[str] = None

    class AuditResponse(BaseModel):
        total: int = 0
        passed: int = 0
        failed: int = 0
        score: float = 0.0
        checks: List[Dict[str, Any]] = []
        elapsed_sec: float = 0.0

except ImportError:
    pass  # pydantic not available — dataclass models still work
