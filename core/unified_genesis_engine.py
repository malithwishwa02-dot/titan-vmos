"""
Titan V13.0 — Unified Genesis Engine
=====================================
A comprehensive, single-tab Genesis algorithm that orchestrates all device aging,
identity forging, wallet provisioning, and stealth patching operations based on
user inputs (country, age, aging period, purchase history, etc.).

This engine consolidates:
  - Profile Forge (AndroidProfileForge)
  - Device Aging (AnomalyPatcher - 26 phases, 103+ vectors)
  - Wallet Provisioning (WalletProvisioner)
  - Payment History Generation (PaymentHistoryForge)
  - Google Account Injection (GoogleAccountInjector)
  - App Data Forging (AppDataForger)
  - Trust Scoring (14-check trust scorer)
  - Play Integrity Defense (PlayIntegritySpoofer)
  - Sensor Warmup (SensorSimulator)
  - Immune Watchdog (honeypot deploy, path/prop hardening)

Usage:
    from unified_genesis_engine import UnifiedGenesisEngine, GenesisConfig

    config = GenesisConfig(
        country="US",
        age_days=120,
        persona_name="John Smith",
        persona_email="john.smith@gmail.com",
        persona_phone="+12125551234",
        occupation="software_engineer",
        # ... other fields
    )

    engine = UnifiedGenesisEngine(adb_target="0.0.0.0:6520")
    result = await engine.execute(config)
"""

import asyncio
import json
import logging
import os
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.unified-genesis")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PersonaConfig:
    """Persona identity configuration."""
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""  # MM/DD/YYYY
    ssn: str = ""
    gender: str = "M"  # M or F
    occupation: str = "professional"
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    country: str = "US"


@dataclass
class PaymentConfig:
    """Payment card configuration."""
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_holder: str = ""
    
    @property
    def cc_exp(self) -> str:
        """Return expiry as MM/YYYY format."""
        if self.cc_exp_month and self.cc_exp_year:
            return f"{self.cc_exp_month:02d}/{self.cc_exp_year}"
        return ""

    @property
    def card_network(self) -> str:
        """Detect card network from BIN."""
        if not self.cc_number:
            return "unknown"
        first = self.cc_number[0]
        if first == "4":
            return "visa"
        elif first == "5":
            return "mastercard"
        elif first == "3":
            return "amex"
        elif first == "6":
            return "discover"
        return "unknown"

    @property
    def last4(self) -> str:
        """Get last 4 digits of card."""
        return self.cc_number[-4:] if len(self.cc_number) >= 4 else "0000"


@dataclass
class GoogleConfig:
    """Google account configuration."""
    email: str = ""
    password: str = ""
    real_phone: str = ""  # For OTP
    otp_code: str = ""


@dataclass
class DeviceConfig:
    """Device identity configuration."""
    model: str = "samsung_s24"
    carrier: str = "tmobile_us"
    location: str = "la"
    proxy_url: str = ""


@dataclass
class AgingConfig:
    """Aging profile configuration."""
    age_days: int = 90
    aging_level: str = "medium"  # light=30d, medium=90d, heavy=365d
    
    # Purchase history settings
    purchase_frequency: str = "moderate"  # low, moderate, high
    purchase_categories: List[str] = field(default_factory=lambda: [
        "groceries", "restaurants", "online_shopping", "subscriptions"
    ])
    average_purchase_amount: float = 45.0
    
    # Behavioral settings
    browsing_intensity: str = "normal"  # minimal, normal, heavy
    social_activity: str = "moderate"  # none, minimal, moderate, active
    app_usage: str = "normal"  # minimal, normal, power_user


@dataclass
class ExecutionOptions:
    """Pipeline execution options."""
    skip_wipe: bool = False
    skip_patch: bool = False
    skip_wallet: bool = False
    skip_google: bool = False
    enable_ai_enrichment: bool = True
    run_trust_audit: bool = True
    run_attestation_check: bool = True
    enable_immune_watchdog: bool = True


@dataclass
class GenesisConfig:
    """Complete unified Genesis configuration."""
    # Core settings
    device_id: str = ""
    adb_target: str = "0.0.0.0:6520"
    
    # Sub-configurations
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    payment: PaymentConfig = field(default_factory=PaymentConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    aging: AgingConfig = field(default_factory=AgingConfig)
    options: ExecutionOptions = field(default_factory=ExecutionOptions)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GenesisConfig':
        """Create config from flat dictionary (e.g., from API request)."""
        config = cls()
        
        # Device ID
        config.device_id = data.get("device_id", "")
        config.adb_target = data.get("adb_target", "0.0.0.0:6520")
        
        # Persona
        config.persona.name = data.get("name", "")
        config.persona.email = data.get("email", "")
        config.persona.phone = data.get("phone", "")
        config.persona.dob = data.get("dob", "")
        config.persona.ssn = data.get("ssn", "")
        config.persona.gender = data.get("gender", "M")
        config.persona.occupation = data.get("occupation", "professional")
        config.persona.street = data.get("street", "")
        config.persona.city = data.get("city", "")
        config.persona.state = data.get("state", "")
        config.persona.zip_code = data.get("zip", data.get("zip_code", ""))
        config.persona.country = data.get("country", "US")
        
        # Payment
        config.payment.cc_number = data.get("cc_number", "")
        cc_exp = data.get("cc_exp", "")
        if cc_exp and "/" in cc_exp:
            parts = cc_exp.split("/")
            config.payment.cc_exp_month = int(parts[0])
            config.payment.cc_exp_year = int(parts[1])
        else:
            config.payment.cc_exp_month = data.get("cc_exp_month", 0)
            config.payment.cc_exp_year = data.get("cc_exp_year", 0)
        config.payment.cc_cvv = data.get("cc_cvv", "")
        config.payment.cc_holder = data.get("cc_holder", data.get("name", ""))
        
        # Google
        config.google.email = data.get("google_email", "")
        config.google.password = data.get("google_password", "")
        config.google.real_phone = data.get("real_phone", "")
        config.google.otp_code = data.get("otp_code", "")
        
        # Device
        config.device.model = data.get("device_model", "samsung_s24")
        config.device.carrier = data.get("carrier", "tmobile_us")
        config.device.location = data.get("location", "la")
        config.device.proxy_url = data.get("proxy_url", "")
        
        # Aging
        config.aging.age_days = data.get("age_days", 90)
        config.aging.aging_level = data.get("aging_level", "medium")
        config.aging.purchase_frequency = data.get("purchase_frequency", "moderate")
        config.aging.purchase_categories = data.get("purchase_categories", [
            "groceries", "restaurants", "online_shopping", "subscriptions"
        ])
        config.aging.average_purchase_amount = data.get("average_purchase_amount", 45.0)
        config.aging.browsing_intensity = data.get("browsing_intensity", "normal")
        config.aging.social_activity = data.get("social_activity", "moderate")
        config.aging.app_usage = data.get("app_usage", "normal")
        
        # Options
        config.options.skip_wipe = data.get("skip_wipe", False)
        config.options.skip_patch = data.get("skip_patch", False)
        config.options.skip_wallet = data.get("skip_wallet", False)
        config.options.skip_google = data.get("skip_google", False)
        config.options.enable_ai_enrichment = data.get("use_ai", data.get("enable_ai_enrichment", True))
        config.options.run_trust_audit = data.get("run_trust_audit", True)
        config.options.run_attestation_check = data.get("run_attestation_check", True)
        config.options.enable_immune_watchdog = data.get("enable_immune_watchdog", True)
        
        return config

    def to_dict(self) -> Dict[str, Any]:
        """Convert to flat dictionary for API response."""
        return {
            "device_id": self.device_id,
            "adb_target": self.adb_target,
            "persona": asdict(self.persona),
            "payment": {
                "cc_number_last4": self.payment.last4,
                "cc_exp": self.payment.cc_exp,
                "card_network": self.payment.card_network,
            },
            "google": {
                "email": self.google.email,
                "has_password": bool(self.google.password),
            },
            "device": asdict(self.device),
            "aging": asdict(self.aging),
            "options": asdict(self.options),
        }


# ═══════════════════════════════════════════════════════════════════════
# PHASE & RESULT DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PhaseResult:
    """Result of a single pipeline phase."""
    phase_id: int
    name: str
    status: str = "pending"  # pending, running, done, failed, skipped, warn
    notes: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0


@dataclass
class GenesisResult:
    """Complete result of unified genesis execution."""
    job_id: str = ""
    status: str = "pending"  # pending, running, completed, failed
    phases: List[PhaseResult] = field(default_factory=list)
    profile_id: str = ""
    trust_score: int = 0
    trust_grade: str = ""
    trust_checks: Dict[str, Any] = field(default_factory=dict)
    patch_score: int = 0
    wallet_score: int = 0
    attestation_ok: bool = False
    started_at: float = 0.0
    completed_at: float = 0.0
    log: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def progress(self) -> float:
        if not self.phases:
            return 0.0
        completed = sum(1 for p in self.phases if p.status in ("done", "skipped"))
        return completed / len(self.phases)

    @property
    def duration(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": round(self.progress * 100, 1),
            "phases": [asdict(p) for p in self.phases],
            "profile_id": self.profile_id,
            "trust_score": self.trust_score,
            "trust_grade": self.trust_grade,
            "trust_checks": self.trust_checks,
            "patch_score": self.patch_score,
            "wallet_score": self.wallet_score,
            "attestation_ok": self.attestation_ok,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "log": self.log[-100:],  # Last 100 log lines
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED GENESIS PIPELINE PHASES
# ═══════════════════════════════════════════════════════════════════════

GENESIS_PHASES = [
    {"id": 0, "name": "Pre-Flight Check", "desc": "Validate ADB connectivity and device state"},
    {"id": 1, "name": "Factory Wipe", "desc": "Clear all previous persona artifacts"},
    {"id": 2, "name": "Stealth Patch", "desc": "Apply 26-phase anomaly patching (103+ vectors)"},
    {"id": 3, "name": "Network Config", "desc": "IPv6 kill + proxy configuration"},
    {"id": 4, "name": "Forge Profile", "desc": "Generate persona data (contacts, SMS, calls, history)"},
    {"id": 5, "name": "Payment History", "desc": "Generate transaction history and receipts"},
    {"id": 6, "name": "Google Account", "desc": "Inject Google account into 8 subsystems"},
    {"id": 7, "name": "Profile Inject", "desc": "Push forged data to device"},
    {"id": 8, "name": "Wallet Provision", "desc": "Google Pay + Chrome Autofill + GMS Billing"},
    {"id": 9, "name": "App Bypass", "desc": "Provincial layering for target apps"},
    {"id": 10, "name": "Browser Harden", "desc": "Kiwi prefs + Chrome sign-in markers"},
    {"id": 11, "name": "Play Integrity", "desc": "Attestation defense configuration"},
    {"id": 12, "name": "Sensor Warmup", "desc": "OADEV-coupled sensor noise initialization"},
    {"id": 13, "name": "Immune Watchdog", "desc": "Honeypot deploy + process cloaking"},
    {"id": 14, "name": "Trust Audit", "desc": "14-check trust scoring (0-100)"},
    {"id": 15, "name": "Final Verify", "desc": "Complete verification and report generation"},
]


# ═══════════════════════════════════════════════════════════════════════
# COUNTRY-SPECIFIC CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════

COUNTRY_PROFILES = {
    "US": {
        "locale": "en-US",
        "timezone": "America/New_York",
        "currency": "USD",
        "phone_format": "+1XXXXXXXXXX",
        "default_carrier": "tmobile_us",
        "default_location": "nyc",
        "popular_apps": [
            "com.venmo", "com.cashapp", "com.chase.sig.android",
            "com.amazon.mShop.android.shopping", "com.walmart.android",
            "com.target.ui", "com.starbucks.mobilecard"
        ],
        "popular_banks": ["Chase", "Bank of America", "Wells Fargo", "Capital One"],
        "purchase_merchants": [
            "Amazon", "Walmart", "Target", "Costco", "Starbucks",
            "Uber Eats", "DoorDash", "Netflix", "Spotify"
        ],
    },
    "GB": {
        "locale": "en-GB",
        "timezone": "Europe/London",
        "currency": "GBP",
        "phone_format": "+44XXXXXXXXXX",
        "default_carrier": "ee_uk",
        "default_location": "london",
        "popular_apps": [
            "com.monzo.android", "com.revolut.revolut", "com.starlingbank",
            "com.amazon.mShop.android.shopping", "com.ocado.mobile",
            "com.deliveroo.orderapp", "com.justeat.app.uk"
        ],
        "popular_banks": ["Monzo", "Revolut", "Starling", "Barclays", "HSBC"],
        "purchase_merchants": [
            "Amazon UK", "Tesco", "Sainsbury's", "ASDA", "Boots",
            "Deliveroo", "Just Eat", "Netflix", "Spotify"
        ],
    },
    "DE": {
        "locale": "de-DE",
        "timezone": "Europe/Berlin",
        "currency": "EUR",
        "phone_format": "+49XXXXXXXXXX",
        "default_carrier": "vodafone_de",
        "default_location": "berlin",
        "popular_apps": [
            "com.n26.app", "de.commerzbank.mobilebanking",
            "com.amazon.mShop.android.shopping", "de.rewe.app",
            "de.lidl.mobile", "com.lieferando.android"
        ],
        "popular_banks": ["N26", "Commerzbank", "Deutsche Bank", "ING"],
        "purchase_merchants": [
            "Amazon DE", "REWE", "Lidl", "dm", "Douglas",
            "Lieferando", "Netflix", "Spotify"
        ],
    },
    "FR": {
        "locale": "fr-FR",
        "timezone": "Europe/Paris",
        "currency": "EUR",
        "phone_format": "+33XXXXXXXXX",
        "default_carrier": "orange_fr",
        "default_location": "paris",
        "popular_apps": [
            "com.boursorama.android.clients", "fr.ca.android.ca",
            "com.amazon.mShop.android.shopping", "fr.carrefour.mobile",
            "com.ubereats.app", "com.deliveroo.orderapp"
        ],
        "popular_banks": ["Boursorama", "Crédit Agricole", "BNP Paribas"],
        "purchase_merchants": [
            "Amazon FR", "Carrefour", "Leclerc", "Auchan",
            "Uber Eats", "Netflix", "Spotify"
        ],
    },
    "CA": {
        "locale": "en-CA",
        "timezone": "America/Toronto",
        "currency": "CAD",
        "phone_format": "+1XXXXXXXXXX",
        "default_carrier": "rogers_ca",
        "default_location": "toronto",
        "popular_apps": [
            "com.rbc.mobile.android", "com.td.android",
            "com.amazon.mShop.android.shopping", "com.loblaw.pcplusandroid",
            "com.skipthedishes", "ca.uber.eats"
        ],
        "popular_banks": ["RBC", "TD Bank", "Scotiabank", "BMO"],
        "purchase_merchants": [
            "Amazon CA", "Loblaws", "Costco", "Tim Hortons",
            "Skip The Dishes", "Netflix", "Spotify"
        ],
    },
    "AU": {
        "locale": "en-AU",
        "timezone": "Australia/Sydney",
        "currency": "AUD",
        "phone_format": "+61XXXXXXXXX",
        "default_carrier": "telstra_au",
        "default_location": "sydney",
        "popular_apps": [
            "au.com.commbank.netbank", "au.com.nab.mobile",
            "com.amazon.mShop.android.shopping", "au.com.woolworths",
            "au.com.menulog.m", "com.ubereats.app"
        ],
        "popular_banks": ["CommBank", "NAB", "Westpac", "ANZ"],
        "purchase_merchants": [
            "Amazon AU", "Woolworths", "Coles", "JB Hi-Fi",
            "Uber Eats", "Netflix", "Spotify"
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════
# AGING LEVEL CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════

AGING_LEVELS = {
    "light": {
        "age_days": 30,
        "contacts_count": (15, 25),
        "call_logs_count": (30, 60),
        "sms_count": (20, 50),
        "chrome_history_count": (50, 100),
        "chrome_cookies_count": (30, 60),
        "gallery_count": (5, 15),
        "app_installs_count": (10, 20),
        "wifi_networks_count": (2, 5),
        "purchase_count": (10, 25),
        "warmup_tasks": 2,
    },
    "medium": {
        "age_days": 90,
        "contacts_count": (30, 60),
        "call_logs_count": (100, 200),
        "sms_count": (80, 150),
        "chrome_history_count": (150, 300),
        "chrome_cookies_count": (80, 150),
        "gallery_count": (20, 40),
        "app_installs_count": (25, 50),
        "wifi_networks_count": (5, 10),
        "purchase_count": (40, 80),
        "warmup_tasks": 4,
    },
    "heavy": {
        "age_days": 365,
        "contacts_count": (80, 150),
        "call_logs_count": (400, 800),
        "sms_count": (300, 600),
        "chrome_history_count": (500, 1000),
        "chrome_cookies_count": (200, 400),
        "gallery_count": (60, 120),
        "app_installs_count": (60, 100),
        "wifi_networks_count": (10, 20),
        "purchase_count": (150, 300),
        "warmup_tasks": 8,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# PURCHASE FREQUENCY CONFIGURATIONS
# ═══════════════════════════════════════════════════════════════════════

PURCHASE_FREQUENCIES = {
    "low": {
        "transactions_per_month": (5, 15),
        "avg_transaction_amount": (20, 50),
        "subscription_count": (1, 2),
    },
    "moderate": {
        "transactions_per_month": (20, 40),
        "avg_transaction_amount": (30, 80),
        "subscription_count": (2, 4),
    },
    "high": {
        "transactions_per_month": (50, 100),
        "avg_transaction_amount": (40, 120),
        "subscription_count": (4, 8),
    },
}


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED GENESIS ENGINE
# ═══════════════════════════════════════════════════════════════════════

class UnifiedGenesisEngine:
    """
    Unified Genesis Engine that consolidates all device aging and identity
    forging operations into a single, configurable pipeline.
    
    This engine orchestrates:
      1. Pre-flight ADB connectivity check
      2. Factory wipe (clear previous persona)
      3. Stealth patch (26 phases, 103+ detection vectors)
      4. Network configuration (proxy, IPv6 kill)
      5. Profile forge (contacts, SMS, calls, browser data)
      6. Payment history generation
      7. Google account injection
      8. Profile injection into device
      9. Wallet provisioning (Google Pay, Chrome Autofill)
      10. App bypass configuration
      11. Browser hardening
      12. Play Integrity defense
      13. Sensor warmup
      14. Immune watchdog deployment
      15. Trust audit
      16. Final verification
    """

    def __init__(self, adb_target: str = "0.0.0.0:6520", device_manager=None):
        self.adb_target = adb_target
        self.dm = device_manager
        self._jobs: Dict[str, GenesisResult] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._callbacks: Dict[str, List[Callable]] = {}

    def _adb_shell(self, cmd: str, timeout: int = 30) -> str:
        """Execute ADB shell command using adb_utils for consistency."""
        try:
            from adb_utils import adb_shell
            return adb_shell(self.adb_target, cmd, timeout=timeout)
        except ImportError:
            # Fallback if adb_utils not available
            import subprocess
            try:
                result = subprocess.run(
                    f'adb -s {self.adb_target} shell "{cmd}"',
                    shell=True, capture_output=True, text=True, timeout=timeout
                )
                return result.stdout.strip()
            except Exception as e:
                logger.warning(f"ADB shell failed: {e}")
                return ""
        except Exception as e:
            logger.warning(f"ADB shell failed: {e}")
            return ""

    def _profiles_dir(self) -> Path:
        """Get profiles directory."""
        d = TITAN_DATA / "profiles"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_job(self, config: GenesisConfig) -> str:
        """Create a new genesis job and return job ID."""
        job_id = f"gen-{uuid.uuid4().hex[:8]}"
        
        result = GenesisResult(
            job_id=job_id,
            status="pending",
            phases=[
                PhaseResult(phase_id=p["id"], name=p["name"])
                for p in GENESIS_PHASES
            ],
        )
        
        self._jobs[job_id] = result
        return job_id

    def get_job(self, job_id: str) -> Optional[GenesisResult]:
        """Get job status by ID."""
        return self._jobs.get(job_id)

    def start(self, config: GenesisConfig) -> GenesisResult:
        """Start genesis execution in background thread."""
        job_id = self.create_job(config)
        result = self._jobs[job_id]
        
        self.adb_target = config.adb_target
        
        thread = threading.Thread(
            target=self._execute_sync,
            args=(job_id, config),
            daemon=True
        )
        self._threads[job_id] = thread
        result.status = "running"
        result.started_at = time.time()
        thread.start()
        
        logger.info(f"Genesis job {job_id} started")
        return result

    async def execute(self, config: GenesisConfig) -> GenesisResult:
        """Execute the complete genesis pipeline asynchronously."""
        job_id = self.create_job(config)
        result = self._jobs[job_id]
        
        self.adb_target = config.adb_target
        result.status = "running"
        result.started_at = time.time()
        
        try:
            await self._run_all_phases(job_id, config)
            result.status = "completed"
        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.exception(f"Genesis job {job_id} failed: {e}")
        
        result.completed_at = time.time()
        return result

    def _execute_sync(self, job_id: str, config: GenesisConfig):
        """Synchronous wrapper for async execution."""
        result = self._jobs[job_id]
        
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._run_all_phases(job_id, config))
            finally:
                loop.close()
            result.status = "completed"
        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.exception(f"Genesis job {job_id} failed: {e}")
        
        result.completed_at = time.time()
        logger.info(f"Genesis job {job_id} finished: {result.status} in {result.duration:.0f}s")

    def _log(self, job_id: str, msg: str):
        """Add log entry to job."""
        result = self._jobs.get(job_id)
        if result:
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] {msg}"
            result.log.append(entry)
            logger.info(f"[{job_id}] {msg}")

    def _update_phase(self, job_id: str, phase_id: int, 
                      status: str = None, notes: str = None, 
                      error: str = None, data: Dict = None):
        """Update phase status."""
        result = self._jobs.get(job_id)
        if not result:
            return
        
        for phase in result.phases:
            if phase.phase_id == phase_id:
                if status:
                    phase.status = status
                    if status == "running":
                        phase.started_at = time.time()
                    elif status in ("done", "failed", "skipped", "warn"):
                        phase.completed_at = time.time()
                if notes:
                    phase.notes = notes
                if error:
                    phase.error = error
                if data:
                    phase.data.update(data)
                break

    async def _run_all_phases(self, job_id: str, config: GenesisConfig):
        """Execute all genesis phases in sequence."""
        result = self._jobs[job_id]
        
        # Phase 0: Pre-flight check
        await self._phase_preflight(job_id, config)
        
        # Phase 1: Factory wipe
        if not config.options.skip_wipe:
            await self._phase_wipe(job_id, config)
        else:
            self._update_phase(job_id, 1, "skipped", "skip_wipe=true")
        
        # Phase 2: Stealth patch
        if not config.options.skip_patch:
            await self._phase_stealth_patch(job_id, config)
        else:
            self._update_phase(job_id, 2, "skipped", "skip_patch=true")
        
        # Phase 3: Network config
        await self._phase_network(job_id, config)
        
        # Phase 4: Forge profile
        profile_data = await self._phase_forge_profile(job_id, config)
        
        # Phase 5: Payment history
        if config.payment.cc_number:
            await self._phase_payment_history(job_id, config, profile_data)
        else:
            self._update_phase(job_id, 5, "skipped", "no card data")
        
        # Phase 6: Google account
        if config.google.email and not config.options.skip_google:
            await self._phase_google_account(job_id, config)
        else:
            self._update_phase(job_id, 6, "skipped", "no google credentials")
        
        # Phase 7: Profile inject
        await self._phase_inject_profile(job_id, config, profile_data)
        
        # Phase 8: Wallet provision
        if config.payment.cc_number and not config.options.skip_wallet:
            await self._phase_wallet_provision(job_id, config, profile_data)
        else:
            self._update_phase(job_id, 8, "skipped", "no card or skip_wallet")
        
        # Phase 9: App bypass
        await self._phase_app_bypass(job_id, config, profile_data)
        
        # Phase 10: Browser harden
        await self._phase_browser_harden(job_id, config)
        
        # Phase 11: Play Integrity
        await self._phase_play_integrity(job_id, config)
        
        # Phase 12: Sensor warmup
        await self._phase_sensor_warmup(job_id, config)
        
        # Phase 13: Immune watchdog
        if config.options.enable_immune_watchdog:
            await self._phase_immune_watchdog(job_id, config)
        else:
            self._update_phase(job_id, 13, "skipped", "disabled")
        
        # Phase 14: Trust audit
        if config.options.run_trust_audit:
            await self._phase_trust_audit(job_id, config, profile_data)
        else:
            self._update_phase(job_id, 14, "skipped", "disabled")
        
        # Phase 15: Final verify
        await self._phase_final_verify(job_id, config, profile_data)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════════

    async def _phase_preflight(self, job_id: str, config: GenesisConfig):
        """Phase 0: Pre-flight connectivity check."""
        self._update_phase(job_id, 0, "running")
        self._log(job_id, "Phase 0 — Pre-flight: checking ADB connectivity...")
        
        try:
            output = self._adb_shell("echo OK")
            if "OK" not in output:
                # Try reconnecting using adb_utils if available
                try:
                    from adb_utils import adb_connect
                    adb_connect(self.adb_target)
                except ImportError:
                    import subprocess
                    subprocess.run(["adb", "connect", self.adb_target],
                                  capture_output=True, timeout=10)
                await asyncio.sleep(2)
                output = self._adb_shell("echo OK")
            
            if "OK" in output:
                self._log(job_id, f"Phase 0 — Pre-flight: ADB connected to {self.adb_target}")
                self._update_phase(job_id, 0, "done", f"connected to {self.adb_target}")
            else:
                raise RuntimeError(f"ADB unreachable: {self.adb_target}")
        except Exception as e:
            self._log(job_id, f"Phase 0 — Pre-flight FAILED: {e}")
            self._update_phase(job_id, 0, "failed", str(e))
            raise

    async def _phase_wipe(self, job_id: str, config: GenesisConfig):
        """Phase 1: Factory wipe - clear all persona artifacts."""
        self._update_phase(job_id, 1, "running")
        self._log(job_id, "Phase 1 — Wipe: clearing all previous persona artifacts...")
        
        wipe_commands = [
            # Clear accounts
            "rm -f /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db*",
            # Clear contacts and call logs
            "content delete --uri content://com.android.contacts/raw_contacts 2>/dev/null; "
            "rm -f /data/data/com.android.providers.contacts/databases/contacts2.db* "
            "/data/data/com.android.providers.contacts/databases/calllog.db*",
            # Clear SMS
            "content delete --uri content://sms 2>/dev/null; "
            "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "
            "'DELETE FROM sms; DELETE FROM threads;' 2>/dev/null",
            # Clear browser data
            "rm -rf /data/data/com.kiwibrowser.browser/app_chrome/Default/* "
            "/data/data/com.android.chrome/app_chrome/Default/Cookies "
            "/data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null",
            # Clear media
            "rm -rf /sdcard/DCIM/* /sdcard/Pictures/* /data/media/0/DCIM/* 2>/dev/null",
            # Clear wallet
            "rm -f /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db* "
            "/data/data/com.google.android.apps.walletnfcrel/shared_prefs/*.xml 2>/dev/null",
            # Clear usage stats and WiFi
            "rm -rf /data/system/usagestats/0/* "
            "/data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null",
        ]
        
        for cmd in wipe_commands:
            self._adb_shell(cmd, timeout=30)
        
        self._log(job_id, "Phase 1 — Wipe complete: all persona data cleared")
        self._update_phase(job_id, 1, "done", "cleared")

    async def _phase_stealth_patch(self, job_id: str, config: GenesisConfig):
        """Phase 2: Apply stealth patching (26 phases, 103+ vectors)."""
        self._update_phase(job_id, 2, "running")
        self._log(job_id, "Phase 2 — Stealth Patch: running 26 phases (3-6 min)...")
        
        try:
            from anomaly_patcher import AnomalyPatcher
            patcher = AnomalyPatcher(adb_target=self.adb_target)
            
            model = config.device.model
            carrier = config.device.carrier
            location = config.device.location
            
            # Use quick_repatch if config exists, otherwise full_patch
            if patcher.get_saved_patch_config():
                self._log(job_id, "Phase 2 — Using quick_repatch (saved config exists)")
                report = patcher.quick_repatch()
            else:
                # Use actual target age_days from config
                age_days = config.aging.age_days or 1
                report = patcher.full_patch(model, carrier, location, 
                                           lockdown=False, age_days=age_days)
            
            result = self._jobs[job_id]
            result.patch_score = report.score
            
            self._log(job_id, f"Phase 2 — Stealth Patch done: {report.score}% ({report.passed}/{report.total})")
            self._update_phase(job_id, 2, "done", 
                              f"{report.score}% {report.passed}/{report.total}",
                              data={"score": report.score, "passed": report.passed, "total": report.total})
        except Exception as e:
            self._log(job_id, f"Phase 2 — Stealth Patch FAILED: {e}")
            self._update_phase(job_id, 2, "failed", str(e)[:60])
            raise

    async def _phase_network(self, job_id: str, config: GenesisConfig):
        """Phase 3: Network configuration (proxy, IPv6 kill)."""
        self._update_phase(job_id, 3, "running")
        self._log(job_id, "Phase 3 — Network: IPv6 kill + proxy config...")
        
        # Kill IPv6
        self._adb_shell("sysctl -w net.ipv6.conf.all.disable_ipv6=1 2>/dev/null")
        self._adb_shell("ip6tables -P INPUT DROP 2>/dev/null")
        self._adb_shell("ip6tables -P OUTPUT DROP 2>/dev/null")
        
        proxy_method = "none"
        if config.device.proxy_url:
            try:
                from proxy_router import ProxyRouter
                pr = ProxyRouter(adb_target=self.adb_target)
                result = pr.configure_socks5(config.device.proxy_url)
                proxy_method = result.method or "configured"
                self._log(job_id, f"Phase 3 — Proxy configured: {result.external_ip or '?'}")
            except Exception as e:
                self._log(job_id, f"Phase 3 — Proxy config failed: {e}")
                proxy_method = f"failed: {e}"
        
        self._log(job_id, f"Phase 3 — Network complete: proxy={proxy_method}")
        self._update_phase(job_id, 3, "done", proxy_method if config.device.proxy_url else "ipv6 disabled")

    async def _phase_forge_profile(self, job_id: str, config: GenesisConfig) -> Dict[str, Any]:
        """Phase 4: Forge complete persona profile."""
        self._update_phase(job_id, 4, "running")
        self._log(job_id, f"Phase 4 — Forge: generating profile for {config.persona.name or 'auto'}...")
        
        try:
            from android_profile_forge import AndroidProfileForge
            forge = AndroidProfileForge()
            
            # Build address dict
            persona_address = None
            if config.persona.street or config.persona.city:
                persona_address = {
                    "address": config.persona.street,
                    "city": config.persona.city,
                    "state": config.persona.state,
                    "zip": config.persona.zip_code,
                    "country": config.persona.country,
                }
            
            # Get aging level config
            aging_config = AGING_LEVELS.get(config.aging.aging_level, AGING_LEVELS["medium"])
            age_days = config.aging.age_days or aging_config["age_days"]
            
            profile_data = forge.forge(
                persona_name=config.persona.name or "Auto User",
                persona_email=config.persona.email or "",
                persona_phone=config.persona.phone or "",
                country=config.persona.country or "US",
                archetype=config.persona.occupation or "professional",
                age_days=age_days,
                carrier=config.device.carrier or "tmobile_us",
                location=config.device.location or "la",
                device_model=config.device.model or "samsung_s24",
                persona_address=persona_address,
            )
            
            profile_id = profile_data.get("id", f"TITAN-{uuid.uuid4().hex[:8].upper()}")
            profile_data["id"] = profile_id
            
            # Persist profile
            profile_path = self._profiles_dir() / f"{profile_id}.json"
            profile_path.write_text(json.dumps(profile_data, indent=2))
            
            result = self._jobs[job_id]
            result.profile_id = profile_id
            
            stats = profile_data.get("stats", {})
            self._log(job_id, f"Phase 4 — Forge done: {profile_id} "
                     f"C:{stats.get('contacts', 0)} SMS:{stats.get('sms', 0)} "
                     f"Calls:{stats.get('call_logs', 0)} Cook:{stats.get('cookies', 0)}")
            
            self._update_phase(job_id, 4, "done", profile_id, data={"profile_id": profile_id})
            return profile_data
            
        except Exception as e:
            self._log(job_id, f"Phase 4 — Forge FAILED: {e}")
            self._update_phase(job_id, 4, "failed", str(e)[:80])
            raise

    async def _phase_payment_history(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 5: Generate payment transaction history."""
        self._update_phase(job_id, 5, "running")
        self._log(job_id, "Phase 5 — Payment History: generating transactions...")
        
        try:
            from payment_history_forge import PaymentHistoryForge
            forge = PaymentHistoryForge()
            
            # Get purchase frequency config
            freq_config = PURCHASE_FREQUENCIES.get(
                config.aging.purchase_frequency, 
                PURCHASE_FREQUENCIES["moderate"]
            )
            
            history = forge.forge(
                age_days=config.aging.age_days,
                card_network=config.payment.card_network,
                card_last4=config.payment.last4,
                persona_email=config.persona.email,
                persona_name=config.persona.name,
                country=config.persona.country,
            )
            
            profile_data["payment_history"] = history.get("transactions", [])
            profile_data["email_receipts"] = history.get("receipts", [])
            
            stats = history.get("stats", {})
            self._log(job_id, f"Phase 5 — Payment History done: "
                     f"{stats.get('total_transactions', 0)} transactions, "
                     f"{len(history.get('receipts', []))} receipts")
            
            self._update_phase(job_id, 5, "done", 
                              f"{stats.get('total_transactions', 0)} txns",
                              data={"transactions": stats.get("total_transactions", 0)})
            
        except Exception as e:
            self._log(job_id, f"Phase 5 — Payment History FAILED: {e}")
            self._update_phase(job_id, 5, "failed", str(e)[:60])

    async def _phase_google_account(self, job_id: str, config: GenesisConfig):
        """Phase 6: Inject Google account into 8 subsystems."""
        self._update_phase(job_id, 6, "running")
        self._log(job_id, f"Phase 6 — Google Account: injecting {config.google.email}...")
        
        try:
            from google_account_injector import GoogleAccountInjector
            gi = GoogleAccountInjector(adb_target=self.adb_target)
            
            gr = gi.inject_account(
                email=config.google.email,
                display_name=config.persona.name or config.google.email.split("@")[0],
            )
            
            ok_str = f"inject={gr.success_count}/8"
            
            # Attempt UI sign-in if password provided
            if config.google.password:
                try:
                    from google_account_creator import GoogleAccountCreator
                    gac = GoogleAccountCreator(adb_target=self.adb_target)
                    sr = gac.sign_in_existing(
                        email=config.google.email,
                        password=config.google.password,
                        phone_number=config.google.real_phone,
                        otp_code=config.google.otp_code,
                    )
                    ok_str += f" ui={'ok' if sr.success else 'fail'}"
                except Exception as ue:
                    self._log(job_id, f"Phase 6 — UI sign-in skipped: {ue}")
            
            self._log(job_id, f"Phase 6 — Google Account done: {ok_str}")
            self._update_phase(job_id, 6, "done", ok_str,
                              data={"success_count": gr.success_count})
            
        except Exception as e:
            self._log(job_id, f"Phase 6 — Google Account FAILED: {e}")
            self._update_phase(job_id, 6, "failed", str(e)[:60])

    async def _phase_inject_profile(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 7: Inject forged profile data into device."""
        self._update_phase(job_id, 7, "running")
        self._log(job_id, "Phase 7 — Profile Inject: pushing data to device...")
        
        try:
            from profile_injector import ProfileInjector
            
            # Build card data
            card_data = None
            if config.payment.cc_number:
                card_data = {
                    "number": config.payment.cc_number,
                    "exp_month": config.payment.cc_exp_month,
                    "exp_year": config.payment.cc_exp_year,
                    "cvv": config.payment.cc_cvv,
                    "cardholder": config.payment.cc_holder or config.persona.name,
                }
            
            # Attach gallery paths
            gallery_dir = TITAN_DATA / "forge_gallery"
            if gallery_dir.exists():
                profile_data["gallery_paths"] = [
                    str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]
                ]
            
            injector = ProfileInjector(adb_target=self.adb_target)
            inj_result = injector.inject_full_profile(profile_data, card_data=card_data)
            
            self._log(job_id, f"Phase 7 — Profile Inject done: trust={inj_result.trust_score}")
            self._update_phase(job_id, 7, "done", f"trust={inj_result.trust_score}",
                              data={"trust_score": inj_result.trust_score})
            
        except Exception as e:
            self._log(job_id, f"Phase 7 — Profile Inject FAILED: {e}")
            self._update_phase(job_id, 7, "failed", str(e)[:80])

    async def _phase_wallet_provision(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 8: Provision wallet (Google Pay, Chrome Autofill)."""
        self._update_phase(job_id, 8, "running")
        self._log(job_id, f"Phase 8 — Wallet: provisioning card ...{config.payment.last4}")
        
        try:
            from wallet_provisioner import WalletProvisioner
            wp = WalletProvisioner(adb_target=self.adb_target)
            
            wp_result = wp.provision_card(
                card_number=config.payment.cc_number,
                exp_month=config.payment.cc_exp_month,
                exp_year=config.payment.cc_exp_year,
                cardholder=config.payment.cc_holder or config.persona.name,
                cvv=config.payment.cc_cvv or "",
                persona_email=config.google.email or config.persona.email,
                persona_name=config.persona.name or "",
                country=config.persona.country or 'US',
                zero_auth=True,
            )
            
            wp_ok = sum([
                getattr(wp_result, 'google_pay_ok', False),
                getattr(wp_result, 'play_store_ok', False),
                getattr(wp_result, 'chrome_autofill_ok', False),
                getattr(wp_result, 'gms_billing_ok', False),
            ])
            
            result = self._jobs[job_id]
            result.wallet_score = int(wp_ok / 4 * 100)
            
            # Fix tapandpay.db ownership
            wallet_uid = self._adb_shell("stat -c '%U' /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
            if wallet_uid and wallet_uid != "root":
                self._adb_shell(f"chown -R {wallet_uid}:{wallet_uid} /data/data/com.google.android.apps.walletnfcrel/databases/")
                self._adb_shell("restorecon -R /data/data/com.google.android.apps.walletnfcrel/databases/ 2>/dev/null")
            
            # Inject purchase history bridge
            try:
                from purchase_history_bridge import generate_android_purchase_history
                from profile_injector import ProfileInjector
                
                phb_data = generate_android_purchase_history(
                    persona_name=config.persona.name,
                    persona_email=config.persona.email,
                    country=config.persona.country,
                    age_days=config.aging.age_days,
                    card_last4=config.payment.last4,
                    card_network=config.payment.card_network,
                )
                
                pi = ProfileInjector(adb_target=self.adb_target)
                if phb_data.get("chrome_history"):
                    pi._inject_history(phb_data["chrome_history"])
                if phb_data.get("chrome_cookies"):
                    pi._inject_cookies(phb_data["chrome_cookies"])
                    
            except Exception as phbe:
                self._log(job_id, f"Phase 8 — Purchase history bridge skipped: {phbe}")
            
            self._log(job_id, f"Phase 8 — Wallet done: {wp_ok}/4 subsystems OK")
            self._update_phase(job_id, 8, "done", f"wallet={wp_ok}/4",
                              data={"ok_count": wp_ok})
            
        except Exception as e:
            self._log(job_id, f"Phase 8 — Wallet FAILED: {e}")
            self._update_phase(job_id, 8, "failed", str(e)[:80])

    async def _phase_app_bypass(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 9: Provincial layering for app bypass."""
        self._update_phase(job_id, 9, "running")
        self._log(job_id, "Phase 9 — App Bypass: injecting V3 app bypass configs...")
        
        try:
            from app_data_forger import AppDataForger
            app_forger = AppDataForger(adb_target=self.adb_target)
            
            # Get country-specific apps
            country = config.persona.country.upper()
            country_profile = COUNTRY_PROFILES.get(country, COUNTRY_PROFILES["US"])
            
            targets = country_profile.get("popular_apps", [])[:5]
            
            persona_dict = {
                'email': config.google.email or config.persona.email or '',
                'name': config.persona.name or '',
                'phone': config.persona.phone or '',
                'country': country,
            }
            
            app_result = app_forger.forge_and_inject(
                installed_packages=targets,
                persona=persona_dict,
                play_purchases=profile_data.get('play_purchases'),
                app_installs=profile_data.get('app_installs'),
            )
            
            self._log(job_id, f"Phase 9 — App Bypass done: {app_result.apps_processed} apps")
            self._update_phase(job_id, 9, "done", f"{app_result.apps_processed} apps",
                              data={"apps_processed": app_result.apps_processed})
            
        except Exception as e:
            self._log(job_id, f"Phase 9 — App Bypass FAILED: {e}")
            self._update_phase(job_id, 9, "failed", str(e)[:80])

    async def _phase_browser_harden(self, job_id: str, config: GenesisConfig):
        """Phase 10: Browser hardening (Kiwi prefs, Chrome markers)."""
        self._update_phase(job_id, 10, "running")
        self._log(job_id, "Phase 10 — Browser Harden: Kiwi prefs + media scan...")
        
        try:
            # Write Kiwi preferences
            kiwi_path = "/data/data/com.kiwibrowser.browser/app_chrome/Default"
            self._adb_shell(f"mkdir -p {kiwi_path}")
            
            prefs = json.dumps({
                "account_info": [{
                    "email": config.google.email or config.persona.email,
                    "full_name": config.persona.name or "User",
                    "gaia": "117234567890",
                    "given_name": (config.persona.name or "User").split()[0],
                    "locale": "en-US",
                }],
                "signin": {"allowed": True, "allowed_on_next_startup": True},
                "sync": {"has_setup_completed": True},
                "browser": {"has_seen_welcome_page": True},
            })
            
            # Write via temp file
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(prefs)
                tf_path = tf.name
            
            # Use adb_utils.adb_push if available, fallback to subprocess
            try:
                from adb_utils import adb_push
                adb_push(self.adb_target, tf_path, f"{kiwi_path}/Preferences")
            except ImportError:
                import subprocess
                subprocess.run(f"adb -s {self.adb_target} push {tf_path} {kiwi_path}/Preferences",
                              shell=True, capture_output=True, timeout=10)
            os.unlink(tf_path)
            
            self._adb_shell(f"restorecon {kiwi_path}/Preferences 2>/dev/null")
            
            # Trigger media scanner
            self._adb_shell("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                           "-d file:///sdcard/DCIM/Camera/ 2>/dev/null")
            
            self._log(job_id, "Phase 10 — Browser Harden done")
            self._update_phase(job_id, 10, "done", "kiwi prefs + media scan")
            
        except Exception as e:
            self._log(job_id, f"Phase 10 — Browser Harden FAILED: {e}")
            self._update_phase(job_id, 10, "failed", str(e)[:60])

    async def _phase_play_integrity(self, job_id: str, config: GenesisConfig):
        """Phase 11: Play Integrity defense configuration."""
        self._update_phase(job_id, 11, "running")
        self._log(job_id, "Phase 11 — Play Integrity: checking attestation...")
        
        issues = []
        
        kb = self._adb_shell("getprop persist.titan.keybox.loaded")
        vbs = self._adb_shell("getprop ro.boot.verifiedbootstate")
        bt = self._adb_shell("getprop ro.build.type")
        qemu = self._adb_shell("getprop ro.kernel.qemu")
        
        if kb.strip() != "1":
            issues.append("keybox")
        if vbs.strip() != "green":
            issues.append(f"vbs={vbs.strip()}")
        if bt.strip() != "user":
            issues.append(f"build={bt.strip()}")
        if qemu.strip() not in ("0", ""):
            issues.append("qemu_exposed")
        
        result = self._jobs[job_id]
        result.attestation_ok = len(issues) == 0
        
        notes = "ok" if not issues else ", ".join(issues)
        status = "done" if not issues else "warn"
        
        self._log(job_id, f"Phase 11 — Play Integrity: {notes}")
        self._update_phase(job_id, 11, status, notes,
                          data={"issues": issues, "attestation_ok": result.attestation_ok})

    async def _phase_sensor_warmup(self, job_id: str, config: GenesisConfig):
        """Phase 12: Sensor warmup (OADEV-coupled noise)."""
        self._update_phase(job_id, 12, "running")
        self._log(job_id, "Phase 12 — Sensor Warmup: initializing OADEV-coupled sensors...")
        
        try:
            from sensor_simulator import SensorSimulator
            sim = SensorSimulator(adb_target=self.adb_target)
            
            # Run short warmup
            sim.start_daemon(duration=30)
            await asyncio.sleep(5)  # Let it run briefly
            
            self._log(job_id, "Phase 12 — Sensor Warmup done")
            self._update_phase(job_id, 12, "done", "sensors initialized")
            
        except Exception as e:
            self._log(job_id, f"Phase 12 — Sensor Warmup FAILED: {e}")
            self._update_phase(job_id, 12, "failed", str(e)[:60])

    async def _phase_immune_watchdog(self, job_id: str, config: GenesisConfig):
        """Phase 13: Deploy immune watchdog (honeypots, process cloaking)."""
        self._update_phase(job_id, 13, "running")
        self._log(job_id, "Phase 13 — Immune Watchdog: deploying defenses...")
        
        try:
            from immune_watchdog import ImmuneWatchdog
            watchdog = ImmuneWatchdog(adb_target=self.adb_target)
            
            result = watchdog.deploy_full_defense()
            
            self._log(job_id, f"Phase 13 — Immune Watchdog done: {result.defenses_active} defenses")
            self._update_phase(job_id, 13, "done", f"{result.defenses_active} defenses",
                              data={"defenses": result.defenses_active})
            
        except Exception as e:
            self._log(job_id, f"Phase 13 — Immune Watchdog FAILED: {e}")
            self._update_phase(job_id, 13, "failed", str(e)[:60])

    async def _phase_trust_audit(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 14: Run 14-check trust scoring."""
        self._update_phase(job_id, 14, "running")
        self._log(job_id, "Phase 14 — Trust Audit: running 14-check scorer...")
        
        try:
            from trust_scorer import compute_trust_score
            
            trust_result = compute_trust_score(self.adb_target, profile_data=profile_data)
            
            result = self._jobs[job_id]
            result.trust_score = trust_result.get("trust_score", 0)
            result.trust_grade = trust_result.get("grade", "?")
            result.trust_checks = trust_result.get("checks", {})
            
            self._log(job_id, f"Phase 14 — Trust Audit: {result.trust_score}/100 ({result.trust_grade})")
            self._update_phase(job_id, 14, "done", 
                              f"{result.trust_score}/100 {result.trust_grade}",
                              data={"score": result.trust_score, "grade": result.trust_grade})
            
        except Exception as e:
            self._log(job_id, f"Phase 14 — Trust Audit FAILED: {e}")
            self._update_phase(job_id, 14, "failed", str(e)[:60])

    async def _phase_final_verify(self, job_id: str, config: GenesisConfig, profile_data: Dict):
        """Phase 15: Final verification and report generation."""
        self._update_phase(job_id, 15, "running")
        self._log(job_id, "Phase 15 — Final Verify: generating report...")
        
        result = self._jobs[job_id]
        
        # Compile summary
        summary = {
            "profile_id": result.profile_id,
            "trust_score": result.trust_score,
            "trust_grade": result.trust_grade,
            "patch_score": result.patch_score,
            "wallet_score": result.wallet_score,
            "attestation_ok": result.attestation_ok,
            "phases_completed": sum(1 for p in result.phases if p.status == "done"),
            "phases_total": len(result.phases),
            "duration_seconds": time.time() - result.started_at,
        }
        
        self._log(job_id, f"Phase 15 — Complete! Trust: {result.trust_score}/100 "
                 f"Patch: {result.patch_score}% Profile: {result.profile_id}")
        self._update_phase(job_id, 15, "done", "report generated", data=summary)


# ═══════════════════════════════════════════════════════════════════════
# ALGORITHM INTERFACE FOR CONSOLE
# ═══════════════════════════════════════════════════════════════════════

def calculate_optimal_aging_profile(
    country: str,
    target_age_days: int,
    purchase_frequency: str = "moderate",
    occupation: str = "professional",
) -> Dict[str, Any]:
    """
    Calculate optimal aging profile parameters based on country and user inputs.
    
    This algorithm determines:
    - Recommended contact count range
    - Expected call/SMS volume
    - Browser activity level
    - Purchase history density
    - App installation patterns
    
    Returns configuration dict for use with GenesisConfig.
    """
    # Get country profile
    country_profile = COUNTRY_PROFILES.get(country.upper(), COUNTRY_PROFILES["US"])
    
    # Get purchase frequency config
    freq_config = PURCHASE_FREQUENCIES.get(purchase_frequency, PURCHASE_FREQUENCIES["moderate"])
    
    # Determine aging level based on target days
    if target_age_days <= 45:
        aging_level = "light"
    elif target_age_days <= 180:
        aging_level = "medium"
    else:
        aging_level = "heavy"
    
    aging_config = AGING_LEVELS.get(aging_level, AGING_LEVELS["medium"])
    
    # Calculate transaction count based on age and frequency
    months = target_age_days / 30
    tx_per_month_range = freq_config["transactions_per_month"]
    min_tx = int(months * tx_per_month_range[0])
    max_tx = int(months * tx_per_month_range[1])
    
    return {
        "aging_level": aging_level,
        "age_days": target_age_days,
        "country": country.upper(),
        "locale": country_profile["locale"],
        "timezone": country_profile["timezone"],
        "currency": country_profile["currency"],
        "default_carrier": country_profile["default_carrier"],
        "default_location": country_profile["default_location"],
        
        # Data volume ranges
        "contacts_range": aging_config["contacts_count"],
        "call_logs_range": aging_config["call_logs_count"],
        "sms_range": aging_config["sms_count"],
        "chrome_history_range": aging_config["chrome_history_count"],
        "chrome_cookies_range": aging_config["chrome_cookies_count"],
        "gallery_range": aging_config["gallery_count"],
        "app_installs_range": aging_config["app_installs_count"],
        "wifi_range": aging_config["wifi_networks_count"],
        
        # Purchase patterns
        "purchase_frequency": purchase_frequency,
        "transaction_range": (min_tx, max_tx),
        "avg_transaction_amount": freq_config["avg_transaction_amount"],
        "subscription_count": freq_config["subscription_count"],
        
        # Recommended merchants/apps
        "recommended_apps": country_profile["popular_apps"],
        "recommended_merchants": country_profile["purchase_merchants"],
        "recommended_banks": country_profile["popular_banks"],
    }


def get_pipeline_phases() -> List[Dict[str, str]]:
    """Return list of pipeline phases for UI display."""
    return GENESIS_PHASES


def get_supported_countries() -> List[Dict[str, str]]:
    """Return list of supported countries with details."""
    return [
        {"code": code, "name": code, **profile}
        for code, profile in COUNTRY_PROFILES.items()
    ]


def get_aging_levels() -> Dict[str, Dict]:
    """Return aging level configurations."""
    return AGING_LEVELS


def get_purchase_frequencies() -> Dict[str, Dict]:
    """Return purchase frequency configurations."""
    return PURCHASE_FREQUENCIES
