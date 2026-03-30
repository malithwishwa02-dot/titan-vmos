"""
Titan V13 — Poisson Aging Model
================================
Dynamic stochastic device-aging model based on Poisson point processes.

Models realistic temporal patterns for:
  - Purchase transactions  (inhomogeneous Poisson, circadian-weighted)
  - Contact additions      (Poisson, archetype-dependent rate)
  - App install events     (Poisson with burst clusters)
  - SMS / call activity    (Poisson, social-role dependent)
  - WiFi network encounters (Poisson, mobility-dependent)

Persona archetypes define the per-event-type Poisson rate λ and circadian
intensity profiles so that activity timelines look plausible for each role.

Usage:
    model = PoissonAgingModel(archetype="professional", country="US", age_days=90)
    timeline = model.generate_full_timeline()
    config   = model.recommend_aging_config()
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "PersonaArchetype",
    "PERSONA_ARCHETYPES",
    "PoissonAgingModel",
]


# ═══════════════════════════════════════════════════════════════════════
# PERSONA ARCHETYPES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PersonaArchetype:
    """Poisson rate parameters (λ events per day) for a persona type."""
    name: str

    # Daily event rates (λ)
    purchases_per_day: float = 1.5       # transactions/day
    contact_adds_per_week: float = 0.5   # new contacts/week
    app_installs_per_month: float = 3.0  # app installs/month
    sms_per_day: float = 12.0            # SMS sent/received per day
    calls_per_day: float = 4.0           # calls per day
    wifi_encounters_per_day: float = 2.0 # new SSIDs per day

    # Circadian profile weights (24 hours, relative)
    # Values will be normalised to a probability distribution
    purchase_hours: Tuple[float, ...] = field(default_factory=lambda: (
        0.1, 0.05, 0.02, 0.01, 0.01, 0.05,  # 00-05
        0.2,  0.5,  0.8,  1.0, 1.2, 1.5,    # 06-11
        2.0, 1.5, 1.0, 1.2, 1.5, 2.0,       # 12-17
        1.8, 1.5, 1.2, 0.8, 0.5, 0.3,       # 18-23
    ))

    # Average transaction amount range (min, max) USD
    avg_amount_range: Tuple[float, float] = (25.0, 80.0)

    # Burst probability: chance that an install/purchase comes in a cluster
    burst_probability: float = 0.15
    burst_size_range: Tuple[int, int] = (2, 4)


PERSONA_ARCHETYPES: Dict[str, PersonaArchetype] = {
    "student": PersonaArchetype(
        name="student",
        purchases_per_day=0.8,
        contact_adds_per_week=1.5,
        app_installs_per_month=8.0,
        sms_per_day=20.0,
        calls_per_day=3.0,
        wifi_encounters_per_day=3.0,
        purchase_hours=(
            0.05, 0.02, 0.01, 0.01, 0.02, 0.1,
            0.3,  0.4,  0.5,  0.8,  1.0, 1.2,
            1.5, 1.0, 1.2, 1.5, 1.5, 2.0,
            2.0, 1.8, 1.5, 1.2, 0.8, 0.3,
        ),
        avg_amount_range=(8.0, 35.0),
        burst_probability=0.20,
    ),
    "professional": PersonaArchetype(
        name="professional",
        purchases_per_day=1.8,
        contact_adds_per_week=0.8,
        app_installs_per_month=2.5,
        sms_per_day=15.0,
        calls_per_day=8.0,
        wifi_encounters_per_day=2.0,
        purchase_hours=(
            0.1, 0.05, 0.02, 0.01, 0.05, 0.3,
            0.8,  1.2,  1.0,  1.0,  1.5, 1.8,
            2.0, 1.2, 1.0, 1.2, 1.5, 1.8,
            1.5, 1.2, 0.8, 0.5, 0.3, 0.2,
        ),
        avg_amount_range=(30.0, 120.0),
        burst_probability=0.10,
    ),
    "parent": PersonaArchetype(
        name="parent",
        purchases_per_day=2.5,
        contact_adds_per_week=0.3,
        app_installs_per_month=1.5,
        sms_per_day=18.0,
        calls_per_day=6.0,
        wifi_encounters_per_day=1.5,
        purchase_hours=(
            0.05, 0.02, 0.01, 0.01, 0.1, 0.5,
            1.0,  0.8,  0.5,  0.5,  1.0, 1.5,
            2.0, 1.2, 1.0, 1.5, 2.0, 2.0,
            1.8, 1.5, 1.0, 0.8, 0.5, 0.2,
        ),
        avg_amount_range=(20.0, 90.0),
        burst_probability=0.25,
    ),
    "retired": PersonaArchetype(
        name="retired",
        purchases_per_day=1.0,
        contact_adds_per_week=0.1,
        app_installs_per_month=0.5,
        sms_per_day=5.0,
        calls_per_day=4.0,
        wifi_encounters_per_day=0.8,
        purchase_hours=(
            0.02, 0.01, 0.01, 0.01, 0.05, 0.2,
            0.5,  0.8,  1.5,  2.0,  2.0, 2.0,
            1.5, 1.5, 2.0, 1.8, 1.2, 1.0,
            0.8, 0.5, 0.3, 0.2, 0.1, 0.05,
        ),
        avg_amount_range=(15.0, 60.0),
        burst_probability=0.05,
    ),
    "entrepreneur": PersonaArchetype(
        name="entrepreneur",
        purchases_per_day=3.0,
        contact_adds_per_week=2.0,
        app_installs_per_month=6.0,
        sms_per_day=25.0,
        calls_per_day=12.0,
        wifi_encounters_per_day=4.0,
        purchase_hours=(
            0.2, 0.1, 0.05, 0.05, 0.1, 0.5,
            1.0, 1.5, 1.5, 1.5, 1.8, 2.0,
            1.8, 1.5, 1.5, 1.5, 1.5, 2.0,
            2.0, 1.8, 1.5, 1.2, 0.8, 0.5,
        ),
        avg_amount_range=(40.0, 200.0),
        burst_probability=0.20,
    ),
    "traveler": PersonaArchetype(
        name="traveler",
        purchases_per_day=2.2,
        contact_adds_per_week=1.0,
        app_installs_per_month=4.0,
        sms_per_day=10.0,
        calls_per_day=5.0,
        wifi_encounters_per_day=6.0,
        purchase_hours=(
            0.1, 0.05, 0.05, 0.05, 0.2, 0.5,
            1.0, 1.5, 1.5, 1.5, 1.5, 1.8,
            1.5, 1.5, 1.5, 1.5, 1.5, 2.0,
            2.0, 1.5, 1.2, 0.8, 0.5, 0.3,
        ),
        avg_amount_range=(35.0, 150.0),
        burst_probability=0.15,
    ),
}

# Map persona/occupation strings to archetype keys
_OCCUPATION_MAP: Dict[str, str] = {
    "student": "student",
    "college": "student",
    "university": "student",
    "teacher": "professional",
    "software_engineer": "professional",
    "engineer": "professional",
    "manager": "professional",
    "doctor": "professional",
    "lawyer": "professional",
    "professional": "professional",
    "auto": "professional",
    "parent": "parent",
    "homemaker": "parent",
    "retired": "retired",
    "senior": "retired",
    "entrepreneur": "entrepreneur",
    "business_owner": "entrepreneur",
    "freelancer": "entrepreneur",
    "traveler": "traveler",
    "influencer": "traveler",
}


def _resolve_archetype(occupation: str) -> PersonaArchetype:
    """Map occupation string to PersonaArchetype."""
    key = _OCCUPATION_MAP.get(occupation.lower(), "professional")
    return PERSONA_ARCHETYPES[key]


# ═══════════════════════════════════════════════════════════════════════
# POISSON SAMPLING UTILITIES
# ═══════════════════════════════════════════════════════════════════════

def _sample_poisson_arrivals(rate_per_day: float, total_days: int) -> List[float]:
    """
    Sample event arrival times using a homogeneous Poisson process.

    Returns a sorted list of fractional days (0.0 to total_days) when
    events occur.  Inter-arrival times ~ Exponential(λ).

    Args:
        rate_per_day: λ — average number of events per day
        total_days:   total observation window in days

    Returns:
        Sorted list of fractional day values.
    """
    if rate_per_day <= 0:
        return []
    arrivals: List[float] = []
    t = random.expovariate(rate_per_day)  # time until first event
    while t < total_days:
        arrivals.append(t)
        t += random.expovariate(rate_per_day)
    return arrivals


def _circadian_sample(hour_weights: Tuple[float, ...]) -> int:
    """
    Sample an hour of the day using provided circadian weights.

    Args:
        hour_weights: 24-element tuple of relative weights.

    Returns:
        Integer hour (0-23).
    """
    total = sum(hour_weights)
    r = random.uniform(0, total)
    cumulative = 0.0
    for h, w in enumerate(hour_weights):
        cumulative += w
        if r <= cumulative:
            return h
    return 23


def _days_to_timestamp(base_dt: datetime, fractional_days: float,
                       circadian_weights: Tuple[float, ...]) -> datetime:
    """Convert fractional day offset to a full datetime with realistic hour."""
    day_offset = int(fractional_days)
    hour = _circadian_sample(circadian_weights)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return base_dt + timedelta(days=day_offset, hours=hour,
                               minutes=minute, seconds=second)


# ═══════════════════════════════════════════════════════════════════════
# POISSON AGING MODEL
# ═══════════════════════════════════════════════════════════════════════

class PoissonAgingModel:
    """
    Stochastic device aging model using Poisson point processes.

    Each activity type (purchases, contacts, app installs, SMS, calls,
    WiFi encounters) is modelled as an independent Poisson process with
    archetype-specific rate λ.  The resulting event timelines are
    temporally realistic and vary naturally across runs.

    Args:
        archetype:   Persona occupation/type string or archetype key.
        country:     ISO country code (affects currency/merchant selection).
        age_days:    Observation window (simulated device lifetime in days).
        seed:        Optional random seed for reproducibility.
    """

    def __init__(self, archetype: str = "professional",
                 country: str = "US", age_days: int = 90,
                 seed: Optional[int] = None):
        self.archetype_key = _OCCUPATION_MAP.get(archetype.lower(), "professional")
        self.archetype = PERSONA_ARCHETYPES[self.archetype_key]
        self.country = country.upper()
        self.age_days = max(1, age_days)
        self._base_dt = datetime.now() - timedelta(days=self.age_days)
        if seed is not None:
            random.seed(seed)

    # ── Core Poisson event generators ────────────────────────────────

    def generate_purchase_timeline(self) -> List[Dict[str, Any]]:
        """
        Generate purchase transaction events using a Poisson process.

        Burst events (e.g., grocery run + coffee + gas in one morning) are
        modelled by a compound Poisson process where a fraction of arrivals
        spawn a small cluster of additional events.
        """
        arrivals = _sample_poisson_arrivals(
            self.archetype.purchases_per_day, self.age_days
        )

        events: List[Dict[str, Any]] = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            amount = random.uniform(*self.archetype.avg_amount_range)
            events.append({
                "timestamp": dt.isoformat(),
                "amount": round(amount, 2),
                "type": "purchase",
            })

            # Compound Poisson burst
            if random.random() < self.archetype.burst_probability:
                cluster_size = random.randint(*self.archetype.burst_size_range) - 1
                for _ in range(cluster_size):
                    offset_minutes = random.randint(5, 120)
                    burst_dt = dt + timedelta(minutes=offset_minutes)
                    burst_amount = random.uniform(
                        self.archetype.avg_amount_range[0] * 0.3,
                        self.archetype.avg_amount_range[0] * 0.8,
                    )
                    events.append({
                        "timestamp": burst_dt.isoformat(),
                        "amount": round(burst_amount, 2),
                        "type": "purchase",
                    })

        return sorted(events, key=lambda e: e["timestamp"])

    def generate_contact_timeline(self) -> List[Dict[str, Any]]:
        """Generate contact creation events."""
        rate_per_day = self.archetype.contact_adds_per_week / 7.0
        arrivals = _sample_poisson_arrivals(rate_per_day, self.age_days)
        events = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            events.append({"timestamp": dt.isoformat(), "type": "contact_add"})
        return events

    def generate_app_install_timeline(self) -> List[Dict[str, Any]]:
        """Generate app install events (with burst clusters for discovery days)."""
        rate_per_day = self.archetype.app_installs_per_month / 30.0
        arrivals = _sample_poisson_arrivals(rate_per_day, self.age_days)
        events = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            events.append({"timestamp": dt.isoformat(), "type": "app_install"})
            if random.random() < self.archetype.burst_probability:
                extra = random.randint(1, 3)
                for _ in range(extra):
                    offset = random.randint(2, 30)
                    events.append({
                        "timestamp": (dt + timedelta(minutes=offset)).isoformat(),
                        "type": "app_install",
                    })
        return sorted(events, key=lambda e: e["timestamp"])

    def generate_sms_timeline(self) -> List[Dict[str, Any]]:
        """Generate SMS send/receive events."""
        arrivals = _sample_poisson_arrivals(
            self.archetype.sms_per_day, self.age_days
        )
        events = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            events.append({
                "timestamp": dt.isoformat(),
                "type": "sms",
                "direction": random.choice(["sent", "received"]),
            })
        return events

    def generate_call_timeline(self) -> List[Dict[str, Any]]:
        """Generate call log events."""
        arrivals = _sample_poisson_arrivals(
            self.archetype.calls_per_day, self.age_days
        )
        events = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            duration_s = int(random.expovariate(1 / 180.0))  # mean 3 min
            events.append({
                "timestamp": dt.isoformat(),
                "type": "call",
                "direction": random.choice(["incoming", "outgoing", "missed"]),
                "duration_seconds": min(duration_s, 3600),
            })
        return events

    def generate_wifi_timeline(self) -> List[Dict[str, Any]]:
        """Generate WiFi network encounter events."""
        arrivals = _sample_poisson_arrivals(
            self.archetype.wifi_encounters_per_day, self.age_days
        )
        events = []
        for t in arrivals:
            dt = _days_to_timestamp(self._base_dt, t,
                                    self.archetype.purchase_hours)
            events.append({"timestamp": dt.isoformat(), "type": "wifi_encounter"})
        return events

    # ── Aggregate timeline ────────────────────────────────────────────

    def generate_full_timeline(self) -> Dict[str, List[Dict[str, Any]]]:
        """Generate all event timelines for this persona."""
        return {
            "purchases": self.generate_purchase_timeline(),
            "contacts": self.generate_contact_timeline(),
            "app_installs": self.generate_app_install_timeline(),
            "sms": self.generate_sms_timeline(),
            "calls": self.generate_call_timeline(),
            "wifi": self.generate_wifi_timeline(),
        }

    # ── Configuration recommendation ──────────────────────────────────

    def recommend_aging_config(self) -> Dict[str, Any]:
        """
        Derive `AgingConfig`-compatible parameter ranges from the Poisson model.

        Monte Carlo estimates expected counts over the aging window so that
        the profile forge receives statistically consistent data volumes.
        """
        # Expected counts from Poisson process: E[N] = λ × T
        expected_purchases = self.archetype.purchases_per_day * self.age_days
        expected_contacts = (self.archetype.contact_adds_per_week / 7.0) * self.age_days
        expected_apps = (self.archetype.app_installs_per_month / 30.0) * self.age_days
        expected_sms = self.archetype.sms_per_day * self.age_days
        expected_calls = self.archetype.calls_per_day * self.age_days
        expected_wifi = self.archetype.wifi_encounters_per_day * self.age_days

        # Add ±25% Poisson variance (stddev = sqrt(E[N]))
        def _range(mean: float) -> Tuple[int, int]:
            variance = math.sqrt(max(mean, 1.0))
            lo = max(1, int(mean - variance))
            hi = max(lo + 1, int(mean + variance))
            return (lo, hi)

        # Derive purchase_frequency label
        daily_rate = self.archetype.purchases_per_day
        if daily_rate < 1.0:
            purchase_frequency = "low"
        elif daily_rate < 2.5:
            purchase_frequency = "moderate"
        else:
            purchase_frequency = "high"

        # Derive aging_level
        if self.age_days <= 45:
            aging_level = "light"
        elif self.age_days <= 180:
            aging_level = "medium"
        else:
            aging_level = "heavy"

        avg_lo, avg_hi = self.archetype.avg_amount_range
        avg_amount = (avg_lo + avg_hi) / 2.0

        return {
            "archetype": self.archetype_key,
            "aging_level": aging_level,
            "age_days": self.age_days,
            "purchase_frequency": purchase_frequency,
            "average_purchase_amount": round(avg_amount, 2),

            # Count ranges (lo, hi) suitable for profile forge
            "contacts_range": _range(expected_contacts),
            "call_logs_range": _range(expected_calls),
            "sms_range": _range(expected_sms),
            "app_installs_range": _range(expected_apps),
            "wifi_networks_range": _range(expected_wifi),
            "purchase_count_range": _range(expected_purchases),

            # Raw Poisson parameters (informational)
            "poisson_rates": {
                "purchases_per_day": self.archetype.purchases_per_day,
                "contacts_per_week": self.archetype.contact_adds_per_week,
                "apps_per_month": self.archetype.app_installs_per_month,
                "sms_per_day": self.archetype.sms_per_day,
                "calls_per_day": self.archetype.calls_per_day,
                "wifi_per_day": self.archetype.wifi_encounters_per_day,
            },
        }
