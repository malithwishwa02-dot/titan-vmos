"""
Titan V12.0 -- FastAPI Response Models
Pydantic models for documented API responses. Used with FastAPI's
response_model parameter for auto-generated OpenAPI docs.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Health / Admin

class HealthResponse(BaseModel):
    status: str = "ok"
    checks: Dict[str, Any] = {}
    timestamp: int = 0
    elapsed_ms: float = 0.0


class LivenessResponse(BaseModel):
    alive: bool = True
    version: str = ""


class ReadinessResponse(BaseModel):
    ready: bool = True
    devices: int = 0
    online: bool = False


# Genesis / Profile

class ProfileCreateResponse(BaseModel):
    profile_id: str
    persona_name: str = ""
    persona_email: str = ""
    country: str = ""
    age_days: int = 0
    device_model: str = ""
    data_summary: Dict[str, int] = Field(default_factory=dict)


# Stealth / Audit

class AuditCheckItem(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    category: str = ""


class AuditResponse(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    score: float = 0.0
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    elapsed_sec: float = 0.0


# Provision / Jobs

class JobStartResponse(BaseModel):
    status: str = "started"
    job_id: str = ""
    device_id: str = ""
    poll_url: str = ""


class ProvisionStatusResponse(BaseModel):
    status: str
    job_id: str = ""
    device_id: str = ""
    step: str = ""
    step_n: int = 0
    patch_score: Optional[int] = None
    trust_score: Optional[int] = None
    inject_trust: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class PatchStatusResponse(BaseModel):
    status: str
    job_id: str = ""
    device_id: str = ""
    step: str = ""
    score: Optional[int] = None
    passed: Optional[int] = None
    total: Optional[int] = None
    elapsed_sec: Optional[float] = None
    error: Optional[str] = None
