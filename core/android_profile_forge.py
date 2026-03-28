"""
Titan V11.3 — Android Device Profile Forge
Generates complete, persona-consistent Android device profile data
for injection into Cuttlefish Android VMs via ProfileInjector.

Unlike the V11 genesis_core (browser-only), this forges the FULL device:
  - Contacts (persona-tied names + locale-matched phone numbers)
  - Call logs (circadian-weighted, in/out/missed over profile age)
  - SMS threads (realistic conversation snippets with contacts)
  - Chrome mobile cookies (trust anchors + commerce + social)
  - Chrome mobile history (locale-aware, mobile-pattern browsing)
  - Gallery photos (EXIF-dated placeholder JPEGs)
  - App install dates (backdated for bundled apps)
  - WiFi saved networks (matching location profile)
  - Autofill data (name, email, phone, address)
  - Purchase history (email receipts, order confirmations)

All data is temporally distributed across the profile age using
circadian weighting so the device looks genuinely lived-in.

Usage:
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name="Alex Mercer",
        persona_email="alex.mercer@gmail.com",
        persona_phone="+12125551234",
        country="US",
        archetype="professional",
        age_days=90,
        carrier="tmobile_us",
        location="nyc",
    )
    # profile dict has: cookies, history, contacts, call_logs, sms,
    #                   gallery_paths, autofill, wifi_networks, app_installs
"""

import hashlib
import json
import logging
import os
import random
import secrets
import string
import struct
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from exceptions import ProfileForgeError

logger = logging.getLogger("titan.android-forge")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))


# ═══════════════════════════════════════════════════════════════════════
# PERSONA NAME POOLS (by locale)
# ═══════════════════════════════════════════════════════════════════════

NAME_POOLS = {
    "US": {
        "first_male": [
            # White/European (40%)
            "James", "Robert", "John", "Michael", "David", "William", "Thomas", "Christopher",
            "Daniel", "Matthew", "Andrew", "Ryan", "Brandon", "Tyler", "Connor", "Ethan",
            # Hispanic/Latino (22%)
            "Carlos", "Luis", "Miguel", "Diego", "Alejandro", "José", "Juan", "Santiago",
            "Mateo", "Andrés", "Gabriel", "Rafael",
            # Black/African American (14%)
            "Jaylen", "DeShawn", "Malik", "Terrence", "Darius", "Lamar", "Tyrone", "Jamal",
            "Marcus", "André",
            # Asian American (7%)
            "Wei", "Jin", "Hiroshi", "Raj", "Arjun", "Vinh", "Hiro", "Sanjay",
            "Kevin", "Jason",
        ],
        "first_female": [
            # White/European (40%)
            "Jennifer", "Jessica", "Sarah", "Ashley", "Emily", "Hannah", "Megan", "Rachel",
            "Lauren", "Olivia", "Sophia", "Emma", "Chloe", "Abigail", "Natalie", "Grace",
            # Hispanic/Latina (22%)
            "María", "Camila", "Valentina", "Isabella", "Lucía", "Sofía", "Gabriela",
            "Carmen", "Rosa", "Elena", "Diana", "Ana",
            # Black/African American (14%)
            "Aaliyah", "Imani", "Jasmine", "Destiny", "Shaniqua", "Keisha", "Tamika",
            "Aisha", "Naomi", "Zuri",
            # Asian American (7%)
            "Mei", "Yuki", "Priya", "Ananya", "Lin", "Sakura", "Kavya", "Michelle",
        ],
        "last": [
            # Census-weighted mix: White + Hispanic + Black + Asian
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
            "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
            "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
            "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Lewis",
            "Nguyen", "Patel", "Kim", "Chen", "Wang", "Singh", "Reyes", "Cruz",
            "Torres", "Ramirez", "Flores", "Rivera", "Morales", "Ortiz",
            "Diaz", "Gutierrez", "Woods", "Washington", "Freeman", "Banks",
        ],
        "area_codes": ["212", "646", "718", "917", "310", "323", "415", "312",
                       "713", "214", "404", "305", "202", "617", "503", "206",
                       "469", "832", "678", "786", "347", "929", "424", "628"],
    },
    "GB": {
        "first_male": ["Oliver", "George", "Harry", "Jack", "Charlie", "Thomas",
                       "James", "William", "Daniel", "Henry", "Alexander", "Edward"],
        "first_female": ["Olivia", "Amelia", "Isla", "Ava", "Emily", "Sophia",
                         "Grace", "Mia", "Poppy", "Ella", "Lily", "Jessica"],
        "last": ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Evans",
                 "Wilson", "Thomas", "Roberts", "Johnson", "Lewis", "Walker", "Robinson"],
        "area_codes": ["020", "0121", "0131", "0141", "0161", "0113", "0117", "01onal"],
    },
    "DE": {
        "first_male": ["Lukas", "Leon", "Finn", "Jonas", "Noah", "Elias", "Paul",
                       "Ben", "Felix", "Max", "Liam", "Moritz"],
        "first_female": ["Emma", "Mia", "Hannah", "Sofia", "Lina", "Emilia",
                         "Marie", "Lea", "Anna", "Lena", "Clara", "Ella"],
        "last": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer",
                 "Wagner", "Becker", "Schulz", "Hoffmann", "Koch", "Richter"],
        "area_codes": ["030", "089", "040", "0221", "069", "0211", "0711", "0341"],
    },
    "FR": {
        "first_male": ["Gabriel", "Louis", "Raphaël", "Jules", "Adam", "Lucas",
                       "Léo", "Hugo", "Arthur", "Nathan", "Liam", "Ethan"],
        "first_female": ["Emma", "Jade", "Louise", "Alice", "Chloé", "Lina",
                         "Rose", "Léa", "Anna", "Mila", "Ambre", "Julia"],
        "last": ["Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard",
                 "Durand", "Dubois", "Moreau", "Laurent", "Simon", "Michel"],
        "area_codes": ["01", "04", "06", "09"],
    },
}

# ═══════════════════════════════════════════════════════════════════════
# SMS CONVERSATION TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

SMS_TEMPLATES = {
    "casual": [
        ("Hey, you free tonight?", "in"),
        ("Yeah what's up?", "out"),
        ("Want to grab dinner? That new place on Main St", "in"),
        ("Sure, 7pm?", "out"),
        ("Perfect see you there", "in"),
    ],
    "work": [
        ("Can you send me the updated report?", "in"),
        ("Just sent it to your email", "out"),
        ("Got it, thanks!", "in"),
    ],
    "family": [
        ("Hi sweetie, are you coming for dinner Sunday?", "in"),
        ("Yes! What time should I be there?", "out"),
        ("Around 2pm. Dad is grilling", "in"),
        ("Sounds great, I'll bring dessert", "out"),
        ("Love you ❤️", "in"),
    ],
    "delivery": [
        ("Your DoorDash order is on the way!", "in"),
        ("Driver is arriving in 5 minutes", "in"),
    ],
    "bank": [
        ("Alert: Purchase of $47.82 at WALMART approved on card ending 4521", "in"),
        ("Alert: Purchase of $12.99 at SPOTIFY approved on card ending 4521", "in"),
    ],
    "otp": [
        ("Your verification code is 847291. Don't share it with anyone.", "in"),
        ("Your code is 529163. Expires in 10 minutes.", "in"),
    ],
    "friend_plan": [
        ("Bro did you see the game last night??", "in"),
        ("Yeah that last quarter was insane", "out"),
        ("We should watch the next one at Dave's", "in"),
        ("I'm down, what day?", "out"),
        ("Saturday 6pm", "in"),
        ("👍", "out"),
    ],
    "appointment": [
        ("Reminder: Your appointment is tomorrow at 10:30 AM", "in"),
        ("Thank you, I'll be there", "out"),
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# MOBILE BROWSING DOMAINS (locale-aware)
# ═══════════════════════════════════════════════════════════════════════

MOBILE_DOMAINS = {
    "global": [
        ("youtube.com", "YouTube"),
        ("instagram.com", "Instagram"),
        ("x.com", "X"),
        ("reddit.com", "Reddit"),
        ("tiktok.com", "TikTok"),
        ("facebook.com", "Facebook"),
        ("linkedin.com", "LinkedIn"),
        ("whatsapp.com", "WhatsApp Web"),
        ("maps.google.com", "Google Maps"),
        ("gmail.com", "Gmail"),
        ("drive.google.com", "Google Drive"),
        ("docs.google.com", "Google Docs"),
        ("wikipedia.org", "Wikipedia"),
        ("stackoverflow.com", "Stack Overflow"),
        ("threads.net", "Threads"),
        ("chatgpt.com", "ChatGPT"),
        ("perplexity.ai", "Perplexity"),
    ],
    "US": [
        ("amazon.com", "Amazon"),
        ("walmart.com", "Walmart"),
        ("target.com", "Target"),
        ("doordash.com", "DoorDash"),
        ("ubereats.com", "Uber Eats"),
        ("weather.com", "The Weather Channel"),
        ("cnn.com", "CNN"),
        ("espn.com", "ESPN"),
        ("chase.com", "Chase"),
        ("venmo.com", "Venmo"),
        ("zillow.com", "Zillow"),
        ("yelp.com", "Yelp"),
    ],
    "GB": [
        ("amazon.co.uk", "Amazon UK"),
        ("bbc.co.uk", "BBC"),
        ("deliveroo.co.uk", "Deliveroo"),
        ("monzo.com", "Monzo"),
        ("rightmove.co.uk", "Rightmove"),
        ("sky.com", "Sky"),
        ("tesco.com", "Tesco"),
    ],
    "DE": [
        ("amazon.de", "Amazon DE"),
        ("spiegel.de", "Spiegel"),
        ("lieferando.de", "Lieferando"),
        ("n26.com", "N26"),
        ("idealo.de", "Idealo"),
    ],
    "FR": [
        ("amazon.fr", "Amazon FR"),
        ("lemonde.fr", "Le Monde"),
        ("leboncoin.fr", "Leboncoin"),
        ("deliveroo.fr", "Deliveroo"),
    ],
}

# Mobile-specific paths (people browse differently on phones)
MOBILE_PATHS = [
    "/", "/search", "/login", "/account", "/orders", "/cart",
    "/notifications", "/messages", "/feed", "/trending", "/explore",
    "/settings", "/profile", "/app/download",
]

# ═══════════════════════════════════════════════════════════════════════
# TRUST ANCHOR COOKIES (Android Chrome)
# ═══════════════════════════════════════════════════════════════════════

COOKIE_ANCHORS = {
    "google.com": [
        ("SID", 32), ("HSID", 16), ("SSID", 16), ("APISID", 16),
        ("SAPISID", 16), ("NID", 64),
        ("1P_JAR", 0),  # 0 = date-formatted
    ],
    "youtube.com": [
        ("VISITOR_INFO1_LIVE", 16), ("YSC", 8), ("PREF", 0),
    ],
    "facebook.com": [
        ("c_user", 0), ("xs", 32), ("fr", 24), ("datr", 16),
    ],
    "instagram.com": [
        ("sessionid", 32), ("csrftoken", 24), ("mid", 16),
    ],
    "x.com": [
        ("auth_token", 24), ("ct0", 32), ("guest_id", 0),
    ],
    "threads.net": [
        ("sessionid", 32), ("csrftoken", 24),
    ],
}

COMMERCE_COOKIES = [
    (".stripe.com", "__stripe_mid", 32),
    (".stripe.com", "__stripe_sid", 16),
    (".paypal.com", "TLTSID", 32),
    (".paypal.com", "ts", 16),
    (".shopify.com", "_shopify_y", 32),
    (".amazon.com", "at-main", 40),
    (".amazon.com", "session-id", 16),
    (".amazon.com", "ubid-main", 16),
    (".klarna.com", "klarna_client_id", 0),
]


# ═══════════════════════════════════════════════════════════════════════
# ARCHETYPE-DRIVEN CIRCADIAN PROFILES
# ═══════════════════════════════════════════════════════════════════════

# Per-archetype activity patterns replace the single static CIRCADIAN_WEIGHTS
# Each array: 24 hourly weights (0=midnight). ±15% random perturbation
# is applied per profile instance for macro-diversity.

ARCHETYPE_PROFILES = {
    "professional": [
        0.03, 0.02, 0.01, 0.01, 0.01, 0.03,   # 00-05 (sleeping)
        0.08, 0.18, 0.25, 0.22, 0.18, 0.15,   # 06-11 (morning commute + work)
        0.28, 0.20, 0.16, 0.14, 0.15, 0.18,   # 12-17 (lunch + afternoon)
        0.25, 0.30, 0.28, 0.18, 0.10, 0.05,   # 18-23 (evening wind-down)
    ],
    "student": [
        0.12, 0.08, 0.05, 0.02, 0.01, 0.01,   # 00-05 (late night active)
        0.02, 0.05, 0.10, 0.15, 0.20, 0.22,   # 06-11 (late morning ramp)
        0.18, 0.15, 0.20, 0.25, 0.18, 0.15,   # 12-17 (afternoon classes)
        0.20, 0.28, 0.35, 0.38, 0.30, 0.20,   # 18-23 (evening peak)
    ],
    "night_shift": [
        0.25, 0.28, 0.30, 0.28, 0.25, 0.20,   # 00-05 (active at work)
        0.15, 0.08, 0.03, 0.02, 0.02, 0.03,   # 06-11 (going to sleep)
        0.02, 0.02, 0.03, 0.05, 0.08, 0.10,   # 12-17 (waking up)
        0.15, 0.18, 0.20, 0.22, 0.25, 0.28,   # 18-23 (evening prep + commute)
    ],
    "retiree": [
        0.02, 0.01, 0.01, 0.01, 0.02, 0.05,   # 00-05 (early to bed)
        0.15, 0.25, 0.28, 0.25, 0.22, 0.20,   # 06-11 (early riser)
        0.22, 0.18, 0.15, 0.12, 0.10, 0.12,   # 12-17 (afternoon quiet)
        0.15, 0.12, 0.08, 0.05, 0.03, 0.02,   # 18-23 (early evening taper)
    ],
    "gamer": [
        0.15, 0.10, 0.05, 0.02, 0.01, 0.01,   # 00-05 (late night gaming)
        0.02, 0.05, 0.08, 0.10, 0.12, 0.14,   # 06-11 (slow morning)
        0.16, 0.15, 0.14, 0.16, 0.18, 0.20,   # 12-17 (afternoon sessions)
        0.25, 0.32, 0.38, 0.35, 0.30, 0.22,   # 18-23 (peak gaming hours)
    ],
}

# Legacy fallback
CIRCADIAN_WEIGHTS = ARCHETYPE_PROFILES["professional"]


def _get_archetype_weights(archetype: str, rng: random.Random) -> List[float]:
    """Get circadian weights for an archetype with ±15% random perturbation."""
    base = ARCHETYPE_PROFILES.get(archetype, ARCHETYPE_PROFILES["professional"])
    # Apply per-instance macro-diversity
    perturbed = [max(0.001, w * rng.uniform(0.85, 1.15)) for w in base]
    return perturbed


def _circadian_hour(rng: random.Random, weights: Optional[List[float]] = None) -> int:
    """Pick an hour weighted by circadian rhythm."""
    if weights is None:
        weights = CIRCADIAN_WEIGHTS
    return rng.choices(range(24), weights=weights, k=1)[0]


def _apply_weekend_multiplier(weights: List[float], is_weekend: bool) -> List[float]:
    """Apply weekend multiplier to circadian weights.

    Weekends: lower early morning (sleeping in), boost late evening (leisure).
    Weekdays: boost early morning (commute), lower late evening.
    """
    if not is_weekend:
        return weights
    adjusted = list(weights)
    # Hours 6-9: lower weight on weekends (sleeping in) — 0.6x
    for h in range(6, 10):
        adjusted[h] *= 0.6
    # Hours 19-23: higher weight on weekends (leisure) — 1.3x
    for h in range(19, 24):
        adjusted[h] *= 1.3
    # Hours 10-12: slightly higher on weekends (brunch/social) — 1.1x
    for h in range(10, 13):
        adjusted[h] *= 1.1
    return adjusted


def _random_datetime(rng: random.Random, base: datetime, days_ago_min: int,
                     days_ago_max: int, weights: Optional[List[float]] = None,
                     tz_offset_hours: float = 0.0) -> datetime:
    """Generate a random datetime within a day range, circadian-weighted.

    Args:
        tz_offset_hours: UTC offset for the profile's locale (e.g. -5 for EST).
            Circadian weights are applied in local time.
    """
    day_offset = rng.randint(days_ago_min, days_ago_max)
    dt = base - timedelta(days=day_offset)
    # Apply weekend multiplier if date falls on Saturday/Sunday
    is_weekend = dt.weekday() >= 5  # 5=Saturday, 6=Sunday
    effective_weights = _apply_weekend_multiplier(weights or CIRCADIAN_WEIGHTS, is_weekend)
    # Pick hour in local time, then convert to UTC
    local_hour = _circadian_hour(rng, effective_weights)
    utc_hour = int((local_hour - tz_offset_hours) % 24)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return dt.replace(hour=utc_hour, minute=minute, second=second)


# ═══════════════════════════════════════════════════════════════════════
# ANDROID PROFILE FORGE
# ═══════════════════════════════════════════════════════════════════════

class AndroidProfileForge:
    """Forges complete Android device profiles tied to a persona."""

    def __init__(self):
        self._rng: Optional[random.Random] = None

    def forge(self,
              persona_name: str = "Alex Mercer",
              persona_email: str = "alex.mercer@gmail.com",
              persona_phone: str = "+12125551234",
              country: str = "US",
              archetype: str = "professional",
              age_days: int = 90,
              carrier: str = "tmobile_us",
              location: str = "nyc",
              device_model: str = "samsung_s25_ultra",
              persona_address: Optional[Dict[str, str]] = None,
              persona_area_code: str = "",
              city_area_codes: Optional[List[str]] = None,
              variant_seed: Optional[str] = None,
              ) -> Dict[str, Any]:
        """
        Forge a complete Android device profile.

        Returns a dict containing all data needed by ProfileInjector:
            cookies, history, contacts, call_logs, sms, gallery_paths,
            autofill, wifi_networks, app_installs, local_storage,
            samsung_health, sensor_traces, lifepath_events
        
        Args:
            variant_seed: Optional entropy to generate profile variants.
                Same persona with different variant_seed produces different
                but coherent profiles. None = deterministic by persona.
        """
        # Seed RNG from persona for deterministic output; variant_seed adds entropy
        seed_str = f"{persona_name}:{persona_email}:{age_days}"
        if variant_seed:
            seed_str = f"{seed_str}:{variant_seed}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:16], 16)
        self._rng = random.Random(seed)

        profile_id = f"TITAN-{secrets.token_hex(4).upper()}"
        now = datetime.now()
        profile_birth = now - timedelta(days=age_days)

        logger.info(f"Forging Android profile: {profile_id} for {persona_name}")
        logger.info(f"  Country: {country}, Age: {age_days}d, Archetype: {archetype}")

        # Compute archetype-driven circadian weights with per-instance diversity
        circadian_weights = _get_archetype_weights(archetype, self._rng)

        # Timezone offset for locale-aware datetime generation
        TZ_OFFSETS = {
            "US": -5.0, "GB": 0.0, "DE": 1.0, "FR": 1.0,
        }
        tz_offset = TZ_OFFSETS.get(country.upper()[:2], -5.0)

        # Parse persona
        parts = persona_name.split(None, 1)
        first_name = parts[0] if parts else "Alex"
        last_name = parts[1] if len(parts) > 1 else "Mercer"

        locale = country.upper()[:2]
        name_pool = NAME_POOLS.get(locale, NAME_POOLS["US"])

        # ─── Generate contacts (with persona area codes) ──────────────
        extra_area_codes = []
        if persona_area_code:
            extra_area_codes.append(persona_area_code)
        if city_area_codes:
            extra_area_codes.extend(city_area_codes[:4])
        contacts = self._forge_contacts(name_pool, locale, age_days, extra_area_codes=extra_area_codes)

        # ─── Generate call logs ───────────────────────────────────────
        call_logs = self._forge_call_logs(contacts, now, age_days,
                                           circadian_weights, tz_offset)

        # ─── Generate SMS ─────────────────────────────────────────────
        sms = self._forge_sms(contacts, now, age_days, circadian_weights, tz_offset)

        # ─── Generate Chrome mobile cookies ───────────────────────────
        cookies = self._forge_cookies(now, profile_birth, locale)

        # ─── Generate Chrome mobile history ───────────────────────────
        history = self._forge_history(now, age_days, locale)

        # ─── Generate gallery photos ──────────────────────────────────
        gallery_paths = self._forge_gallery(now, age_days, device_model=device_model,
                                             location=location)

        # ─── Generate autofill (use persona's real address if provided) ─
        if persona_address and persona_address.get("address"):
            address = persona_address
        else:
            address = self._forge_address(locale)
        autofill = {
            "name": persona_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": persona_email,
            "phone": persona_phone,
            "address": address,
        }

        # ─── WiFi networks ───────────────────────────────────────────
        wifi_networks = self._forge_wifi(locale, location, age_days=age_days)

        # ─── App install timestamps ───────────────────────────────────
        app_installs = self._forge_app_installs(now, age_days, locale)

        # ─── Play Store purchase history ─────────────────────────────
        play_purchases = self._forge_play_purchases(now, age_days, persona_email, locale)

        # ─── App usage stats ─────────────────────────────────────────
        app_usage = self._forge_app_usage(now, age_days, locale)

        # ─── Notification history ────────────────────────────────────
        notifications = self._forge_notifications(now, age_days, locale)

        # ─── Email receipts ──────────────────────────────────────────
        email_receipts = self._forge_email_receipts(now, age_days, persona_email, locale)

        # ─── Google Maps history ─────────────────────────────────────
        maps_history = self._forge_maps_history(now, age_days, location, locale)

        # ─── Samsung Health data ─────────────────────────────────────
        samsung_health = self._forge_samsung_health(now, age_days, archetype)

        # ─── Local Storage (Chrome) ─────────────────────────────────
        local_storage = self._forge_local_storage(now, age_days, locale, persona_email)

        # ─── Sensor trace metadata ───────────────────────────────────
        sensor_traces = self._forge_sensor_traces(now, age_days, archetype)

        # ─── Build raw profile ────────────────────────────────────────
        raw_profile = {
            "contacts": contacts,
            "call_logs": call_logs,
            "sms": sms,
            "cookies": cookies,
            "history": history,
            "gallery_paths": gallery_paths,
            "autofill": autofill,
            "wifi_networks": wifi_networks,
            "app_installs": app_installs,
            "play_purchases": play_purchases,
            "app_usage": app_usage,
            "notifications": notifications,
            "email_receipts": email_receipts,
            "maps_history": maps_history,
            "local_storage": local_storage,
            "samsung_health": samsung_health,
            "sensor_traces": sensor_traces,
        }

        # ─── V12 Life-Path Coherence Engine ──────────────────────────
        # Cross-correlate independently generated data into a coherent
        # timeline: purchases→history, contacts→calls, GPS→maps, etc.
        correlated = self._correlate_lifepath(
            raw_profile, now, age_days, location, locale,
            circadian_weights, tz_offset, persona_email,
        )

        # ─── Build final profile ──────────────────────────────────────
        profile = {
            "id": profile_id,
            "uuid": profile_id,
            "persona_name": persona_name,
            "persona_email": persona_email,
            "persona_phone": persona_phone,
            "country": country,
            "archetype": archetype,
            "age_days": age_days,
            "carrier": carrier,
            "location": location,
            "device_model": device_model,
            "created_at": now.isoformat(),
            "profile_birth": profile_birth.isoformat(),
            "persona_address": persona_address or {},
            # Injection data (post-correlation)
            "contacts": correlated["contacts"],
            "call_logs": correlated["call_logs"],
            "sms": correlated["sms"],
            "cookies": correlated["cookies"],
            "history": correlated["history"],
            "gallery_paths": correlated["gallery_paths"],
            "autofill": autofill,
            "wifi_networks": correlated["wifi_networks"],
            "app_installs": app_installs,
            "play_purchases": correlated["play_purchases"],
            "app_usage": app_usage,
            "notifications": correlated["notifications"],
            "email_receipts": correlated["email_receipts"],
            "maps_history": correlated["maps_history"],
            "local_storage": correlated["local_storage"],
            "samsung_health": correlated["samsung_health"],
            "sensor_traces": correlated["sensor_traces"],
            "lifepath_events": correlated.get("lifepath_events", []),
            # Stats
            "stats": {
                "contacts": len(correlated["contacts"]),
                "call_logs": len(correlated["call_logs"]),
                "sms": len(correlated["sms"]),
                "cookies": len(correlated["cookies"]),
                "history": len(correlated["history"]),
                "gallery": len(correlated["gallery_paths"]),
                "apps": len(app_installs),
                "wifi": len(correlated["wifi_networks"]),
                "play_purchases": len(correlated["play_purchases"]),
                "app_usage": len(app_usage),
                "notifications": len(correlated["notifications"]),
                "email_receipts": len(correlated["email_receipts"]),
                "maps_history": len(correlated["maps_history"]),
                "lifepath_events": len(correlated.get("lifepath_events", [])),
            },
        }

        # ─── V12 Payment History Injection ─────────────────────────────
        # Generate realistic transaction history for behavioral trust scoring
        try:
            from payment_history_forge import PaymentHistoryForge
            ph_forge = PaymentHistoryForge()
            payment_history = ph_forge.forge(
                age_days=age_days,
                card_network="visa",
                card_last4="0000",
                persona_email=persona_email,
            )
            profile["payment_history"] = payment_history.get("transactions", [])
            profile["stats"]["payment_history"] = len(profile["payment_history"])
        except Exception as e:
            logger.debug(f"PaymentHistoryForge not available: {e}")
            profile["payment_history"] = []
            profile["stats"]["payment_history"] = 0

        # Save to disk
        self._save_profile(profile)

        logger.info(f"Profile forged: {profile_id}")
        logger.info(f"  Contacts: {len(contacts)}, Calls: {len(call_logs)}, SMS: {len(sms)}")
        logger.info(f"  Cookies: {len(cookies)}, History: {len(history)}, Gallery: {len(gallery_paths)}")
        return profile

    # ─── CONTACTS ─────────────────────────────────────────────────────

    def _forge_contacts(self, name_pool: dict, locale: str, age_days: int,
                         extra_area_codes: Optional[List[str]] = None) -> List[Dict]:
        """Generate persona-consistent contacts, scaled to device age.

        Real device contact accumulation (from Samsung Health / ContactsDB audits):
          90d  → 25-60 contacts
          180d → 50-100 contacts
          365d → 80-180 contacts
          500d → 100-220 contacts
        """
        rng = self._rng
        # Scale contact count with device age — people accumulate contacts over time
        lo = max(15, min(age_days // 8, 100))
        hi = max(lo + 10, min(age_days // 3, 220))
        num_contacts = rng.randint(lo, hi)
        area_codes = name_pool.get("area_codes", ["212", "646", "718"])
        # Mix in persona's area codes (from their phone + city)
        if extra_area_codes:
            area_codes = list(extra_area_codes) + [c for c in area_codes if c not in extra_area_codes]
        contacts = []

        # Mix of male and female names
        for i in range(num_contacts):
            if rng.random() < 0.5:
                first = rng.choice(name_pool.get("first_male", ["John"]))
            else:
                first = rng.choice(name_pool.get("first_female", ["Jane"]))
            last = rng.choice(name_pool.get("last", ["Smith"]))

            area = rng.choice(area_codes)
            if locale == "US":
                phone = f"+1{area}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "GB":
                phone = f"+44{area[1:]}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "DE":
                phone = f"+49{area[1:]}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "FR":
                phone = f"+33{area}{''.join([str(rng.randint(0,9)) for _ in range(8)])}"
            else:
                phone = f"+1{area}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"

            email = ""
            if rng.random() < 0.4:  # 40% have email
                email_user = f"{first.lower()}.{last.lower()}{rng.randint(1,99)}"
                email = f"{email_user}@{rng.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'icloud.com'])}"

            contacts.append({
                "name": f"{first} {last}",
                "phone": phone,
                "email": email,
                "relationship": rng.choice(["friend", "friend", "friend", "family", "work", "work", "other"]),
            })

        # Add special contacts
        contacts.append({"name": "Mom", "phone": contacts[0]["phone"].replace(contacts[0]["phone"][-4:], str(rng.randint(1000,9999))), "email": "", "relationship": "family"})
        contacts.append({"name": "Voicemail", "phone": "*86", "email": "", "relationship": "other"})

        return contacts

    # ─── CALL LOGS ────────────────────────────────────────────────────

    def _forge_call_logs(self, contacts: List[Dict], now: datetime, age_days: int,
                          circadian_weights: Optional[List[float]] = None,
                          tz_offset: float = 0.0) -> List[Dict]:
        """Generate realistic call history spread over profile age."""
        rng = self._rng
        # ~1.5 calls/day on average
        _lo = max(20, age_days)
        _hi = max(_lo, min(age_days * 3, 1500))
        num_calls = rng.randint(_lo, _hi)
        logs = []

        # Weight: more calls to frequent contacts (Pareto)
        contact_weights = [1.0 / (i + 1) ** 0.8 for i in range(len(contacts))]

        # Phase 1: Distributed calls (Poisson-distributed across timeline)
        distributed_count = int(num_calls * 0.7)
        for _ in range(distributed_count):
            contact = rng.choices(contacts, weights=contact_weights[:len(contacts)], k=1)[0]
            dt = _random_datetime(rng, now, 0, age_days, circadian_weights, tz_offset)
            call_type = rng.choices([1, 2, 3], weights=[35, 45, 20], k=1)[0]  # in/out/missed

            duration = 0
            if call_type == 1:  # incoming
                duration = rng.choices(
                    [rng.randint(5, 30), rng.randint(30, 180), rng.randint(180, 900)],
                    weights=[40, 40, 20], k=1
                )[0]
            elif call_type == 2:  # outgoing
                duration = rng.choices(
                    [rng.randint(5, 20), rng.randint(20, 120), rng.randint(120, 600)],
                    weights=[30, 50, 20], k=1
                )[0]
            # missed = 0

            logs.append({
                "number": contact["phone"],
                "type": call_type,
                "duration": duration,
                "date": int(dt.timestamp() * 1000),
            })

        # Phase 2: Poisson burst clusters — humans exhibit clustered calling
        # patterns (e.g., 3-5 rapid calls coordinating an event, followed by
        # hours of silence). Without bursts, call logs show unnaturally even
        # distribution that behavioral analyzers flag.
        burst_count = num_calls - distributed_count
        num_bursts = max(1, burst_count // 5)
        for _ in range(num_bursts):
            burst_contact = rng.choices(contacts, weights=contact_weights[:len(contacts)], k=1)[0]
            burst_start = _random_datetime(rng, now, 0, min(age_days, 60),
                                            circadian_weights, tz_offset)
            cluster_size = rng.randint(2, 6)
            for c in range(min(cluster_size, burst_count)):
                # Inter-call gap within burst: 1-15 minutes (redial, callback patterns)
                gap_minutes = rng.choices([1, 2, 5, 10, 15], weights=[30, 25, 20, 15, 10], k=1)[0]
                call_dt = burst_start + timedelta(minutes=c * gap_minutes + rng.randint(0, 2))
                call_type = rng.choices([1, 2, 3], weights=[30, 50, 20], k=1)[0]

                duration = 0
                if call_type == 1:
                    duration = rng.randint(5, 60)
                elif call_type == 2:
                    duration = rng.randint(5, 45)

                logs.append({
                    "number": burst_contact["phone"],
                    "type": call_type,
                    "duration": duration,
                    "date": int(call_dt.timestamp() * 1000),
                })
                burst_count -= 1
                if burst_count <= 0:
                    break
            if burst_count <= 0:
                break

        logs.sort(key=lambda x: x["date"], reverse=True)
        return logs

    # ─── SMS ──────────────────────────────────────────────────────────

    def _forge_sms(self, contacts: List[Dict], now: datetime, age_days: int,
                    circadian_weights: Optional[List[float]] = None,
                    tz_offset: float = 0.0) -> List[Dict]:
        """Generate SMS conversation threads with Poisson burst clustering."""
        rng = self._rng
        messages = []

        # Scale SMS thread contacts with device age: older devices have more threads
        # 500-day device: 12-20 active contacts vs 4-8 for 90-day device
        min_threads = min(4 + age_days // 100, 12)
        max_threads = min(8 + age_days // 60, 20)
        num_threads = rng.randint(min_threads, max_threads)
        sms_contacts = rng.sample(contacts[:min(max_threads + 5, len(contacts))],
                                   min(num_threads, len(contacts)))

        for contact in sms_contacts:
            # Pick 1-3 conversation templates for this contact
            relationship = contact.get("relationship", "friend")
            if relationship == "family":
                templates = rng.sample(["family", "casual", "appointment"], min(2, 3))
            elif relationship == "work":
                templates = rng.sample(["work", "appointment"], min(1, 2))
            else:
                templates = rng.sample(["casual", "friend_plan", "otp", "delivery"], min(2, 4))

            for tmpl_key in templates:
                tmpl = SMS_TEMPLATES.get(tmpl_key, SMS_TEMPLATES["casual"])
                # Spread threads across the FULL device age (was capped at 60 days)
                thread_start = _random_datetime(rng, now, 1, age_days,
                                                 circadian_weights, tz_offset)

                # Relational dialogue: messages in a thread are sequential
                # with natural inter-message timing (1-15 minutes)
                for idx, (body, direction) in enumerate(tmpl):
                    msg_time = thread_start + timedelta(minutes=idx * rng.randint(1, 15))
                    msg_type = 1 if direction == "in" else 2  # 1=received, 2=sent

                    messages.append({
                        "address": contact["phone"],
                        "body": body,
                        "type": msg_type,
                        "date": int(msg_time.timestamp() * 1000),
                    })

            # Poisson burst: 20% chance of a rapid-fire burst with this contact
            if rng.random() < 0.20:
                burst_size = rng.randint(5, 25)
                burst_start = _random_datetime(rng, now, 0, min(age_days, 30),
                                                circadian_weights, tz_offset)
                for b in range(burst_size):
                    # 15-120 second gaps within a burst
                    msg_time = burst_start + timedelta(seconds=b * rng.randint(15, 120))
                    direction = rng.choice(["in", "out"])
                    # Quick burst messages
                    burst_bodies = [
                        "lol", "yeah", "ok", "😂", "no way", "fr", "bet",
                        "omg", "same", "haha", "facts", "wya", "otw",
                        "yep", "nah", "👍", "bruh", "one sec", "?",
                    ]
                    messages.append({
                        "address": contact["phone"],
                        "body": rng.choice(burst_bodies),
                        "type": 1 if direction == "in" else 2,
                        "date": int(msg_time.timestamp() * 1000),
                    })

        # Add bank/OTP messages from short codes — scale volume with age
        num_shortcode = rng.randint(max(3, age_days // 50), max(8, age_days // 20))
        for _ in range(num_shortcode):
            tmpl = rng.choice([SMS_TEMPLATES["bank"], SMS_TEMPLATES["otp"]])
            for body, direction in tmpl:
                # Spread across full age, not just last 30 days
                dt = _random_datetime(rng, now, 0, age_days,
                                       circadian_weights, tz_offset)
                messages.append({
                    "address": rng.choice(["72000", "33663", "89203", "22395", "CHASE", "PAYPAL"]),
                    "body": body,
                    "type": 1,
                    "date": int(dt.timestamp() * 1000),
                })

        messages.sort(key=lambda x: x["date"], reverse=True)
        return messages

    # ─── CHROME COOKIES ───────────────────────────────────────────────

    def _forge_cookies(self, now: datetime, birth: datetime, locale: str) -> List[Dict]:
        """Generate Chrome mobile trust anchor + commerce cookies."""
        rng = self._rng
        cookies = []

        # Trust anchors
        for domain, cookie_defs in COOKIE_ANCHORS.items():
            for name, hex_len in cookie_defs:
                if hex_len == 0:
                    if name == "1P_JAR":
                        value = f"{now.year}-{now.month:02d}-{now.day:02d}-{rng.randint(10,23)}"
                    elif name == "c_user":
                        value = str(rng.randint(100000000, 999999999))
                    elif name == "guest_id":
                        value = f"v1%3A{int(now.timestamp() * 1000)}"
                    elif name == "PREF":
                        value = f"tz=America.New_York&f6={rng.randint(10000,99999)}"
                    elif name == "klarna_client_id":
                        value = str(uuid.uuid4())
                    else:
                        value = secrets.token_hex(16)
                else:
                    value = secrets.token_hex(hex_len)

                creation_days_ago = rng.randint(7, min(90, max(7, int(
                    (now - birth).days * 0.8
                ))))

                cookies.append({
                    "domain": f".{domain}",
                    "name": name,
                    "value": value,
                    "path": "/",
                    "secure": True,
                    "httponly": name not in ("1P_JAR", "PREF", "guest_id"),
                    "samesite": -1,
                    "max_age": 31536000,
                    "creation_days_ago": creation_days_ago,
                })

        # Commerce cookies (pick 5-8 randomly)
        selected_commerce = rng.sample(COMMERCE_COOKIES, min(rng.randint(5, 8), len(COMMERCE_COOKIES)))
        for domain, name, hex_len in selected_commerce:
            value = str(uuid.uuid4()) if hex_len == 0 else secrets.token_hex(hex_len)
            cookies.append({
                "domain": domain,
                "name": name,
                "value": value,
                "path": "/",
                "secure": True,
                "httponly": False,
                "samesite": -1,
                "max_age": 31536000,
                "creation_days_ago": rng.randint(14, min(60, max(14, int((now - birth).days * 0.6)))),
            })

        return cookies

    # ─── CHROME HISTORY ───────────────────────────────────────────────

    def _forge_history(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate Chrome mobile browsing history."""
        rng = self._rng
        entries = []

        # Combine global + locale-specific domains
        domains = MOBILE_DOMAINS["global"] + MOBILE_DOMAINS.get(locale, MOBILE_DOMAINS["US"])

        # Pareto: 80% of visits go to 20% of domains
        top_domains = domains[:max(3, len(domains) // 5)]
        other_domains = domains[len(top_domains):]

        # ~8-15 mobile browsing sessions per day
        lo = max(100, age_days * 5)
        hi = max(lo, min(age_days * 15, 800))
        target_entries = rng.randint(lo, hi)

        for _ in range(target_entries):
            # 80% from top domains, 20% from others
            if rng.random() < 0.8 and top_domains:
                domain, title_base = rng.choice(top_domains)
            elif other_domains:
                domain, title_base = rng.choice(other_domains)
            else:
                domain, title_base = rng.choice(domains)

            path = rng.choice(MOBILE_PATHS)
            dt = _random_datetime(rng, now, 0, age_days)
            visits = rng.choices([1, 2, 3, 5, 8], weights=[30, 30, 20, 15, 5], k=1)[0]

            entries.append({
                "url": f"https://www.{domain}{path}",
                "title": f"{title_base} - {path.strip('/').replace('/', ' ').title() or 'Home'}",
                "visits": visits,
                "timestamp": int(dt.timestamp()),
            })

        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        return entries

    # ─── GALLERY PHOTOS ───────────────────────────────────────────────

    def _forge_gallery(self, now: datetime, age_days: int,
                        device_model: str = "", location: str = "nyc") -> List[Dict]:
        """Generate placeholder JPEG photos scaled to device age.

        Samsung camera filename format: YYYYMMDD_HHMMSS.jpg (no IMG_ prefix).
        Pixel/AOSP format: PXL_YYYYMMDD_HHMMSSXXX.jpg.
        Other/generic: IMG_YYYYMMDD_XXXXXX.jpg.

        Returns list of dicts with path + GPS metadata for lifepath correlation.
        """
        rng = self._rng

        # Resolve GPS center from location
        try:
            from core.device_presets import LOCATIONS
            loc = LOCATIONS.get(location, LOCATIONS.get("nyc", {}))
            center_lat = loc.get("lat", 40.7580)
            center_lon = loc.get("lon", -73.9855)
        except Exception:
            center_lat, center_lon = 40.7580, -73.9855

        # Scale photo count with device age
        lo = max(20, int(age_days * 1.2))
        hi = max(lo + 50, min(int(age_days * 4.5), 2500))
        num_photos = rng.randint(lo, hi)
        gallery_dir = TITAN_DATA / "forge_gallery"
        gallery_dir.mkdir(parents=True, exist_ok=True)

        is_samsung = "samsung" in device_model.lower()
        is_pixel = "pixel" in device_model.lower()

        photos = []
        for i in range(num_photos):
            dt = _random_datetime(rng, now, 1, age_days)
            if is_samsung:
                fname = f"{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
            elif is_pixel:
                fname = f"PXL_{dt.strftime('%Y%m%d_%H%M%S')}{rng.randint(0, 999):03d}.jpg"
            else:
                fname = f"IMG_{dt.strftime('%Y%m%d')}_{rng.randint(100000, 999999)}.jpg"
            fpath = gallery_dir / fname

            # Jitter GPS: ±0.02° (~2km) from home for 70% of photos,
            # ±0.15° (~15km) for 25% (errands/work), ±1.0° for 5% (travel)
            r = rng.random()
            if r < 0.70:
                jitter = 0.02
            elif r < 0.95:
                jitter = 0.15
            else:
                jitter = 1.0
            gps_lat = center_lat + rng.uniform(-jitter, jitter)
            gps_lon = center_lon + rng.uniform(-jitter, jitter)

            if not fpath.exists():
                self._create_placeholder_jpeg(fpath, dt, gps_lat, gps_lon)

            photos.append({
                "path": str(fpath),
                "lat": round(gps_lat, 6),
                "lon": round(gps_lon, 6),
                "timestamp": int(dt.timestamp()),
            })

        return photos

    def _create_placeholder_jpeg(self, path: Path, dt: datetime,
                                  gps_lat: float = 0.0, gps_lon: float = 0.0):
        """Create a minimal valid JPEG file with EXIF date + GPS metadata."""
        try:
            # SOI marker
            data = b'\xff\xd8'
            # APP0 JFIF
            data += b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'

            # APP1 EXIF header with DateTimeOriginal and GPS
            exif_data = self._build_exif_segment(dt, gps_lat, gps_lon)
            data += exif_data

            # DQT
            data += b'\xff\xdb\x00C\x00'
            data += bytes([8] * 64)
            # SOF0 (1x1, 1 component)
            data += b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
            # DHT (minimal)
            data += b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b'
            # SOS + data + EOI
            data += b'\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x7b\x40'
            data += b'\xff\xd9'

            # Add random bytes to vary file size (look more like real photos)
            padding_size = self._rng.randint(30000, 80000)
            data = data[:-2] + os.urandom(padding_size) + data[-2:]

            path.write_bytes(data)
        except Exception:
            # Fallback: just write random bytes
            path.write_bytes(os.urandom(self._rng.randint(30000, 80000)))

    def _build_exif_segment(self, dt: datetime, gps_lat: float = 0.0, gps_lon: float = 0.0) -> bytes:
        """Build EXIF APP1 segment with DateTimeOriginal + GPSInfo IFD.

        Produces valid TIFF structure with:
          - IFD0: DateTimeOriginal (0x9003), ExifIFDPointer (0x8769), GPSInfoIFDPointer (0x8825)
          - GPS IFD: GPSLatitudeRef, GPSLatitude, GPSLongitudeRef, GPSLongitude
        """
        date_str = dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii") + b'\x00'  # 20 bytes

        def _deg_to_rational(deg: float):
            """Convert decimal degrees to (degrees, minutes, seconds) as RATIONAL pairs."""
            d = int(abs(deg))
            m = int((abs(deg) - d) * 60)
            s = int(((abs(deg) - d) * 60 - m) * 60 * 100)  # ×100 for precision
            return (d, 1, m, 1, s, 100)

        # === Pre-compute GPS rational data ===
        lat_ref = b'N\x00' if gps_lat >= 0 else b'S\x00'
        lon_ref = b'E\x00' if gps_lon >= 0 else b'W\x00'
        lat_rationals = _deg_to_rational(gps_lat)
        lon_rationals = _deg_to_rational(gps_lon)

        # === Build TIFF structure ===
        # We'll build: TIFF header (8) | IFD0 | IFD0 data | GPS IFD | GPS data
        # IFD0: 3 entries (DateTimeOriginal, ExifIFD ptr, GPS IFD ptr)
        ifd0_count = 3
        ifd0_size = 2 + ifd0_count * 12 + 4  # count + entries + next_ifd_ptr
        ifd0_offset = 8  # right after TIFF header

        # Data area starts after IFD0
        data_offset = ifd0_offset + ifd0_size

        # DateTimeOriginal value (20 bytes) at data_offset
        dt_value_offset = data_offset
        dt_value = date_str  # 20 bytes

        # GPS IFD at dt_value_offset + 20
        gps_ifd_offset = dt_value_offset + len(dt_value)
        gps_count = 4  # LatRef, Lat, LonRef, Lon
        gps_ifd_size = 2 + gps_count * 12 + 4
        gps_data_offset = gps_ifd_offset + gps_ifd_size

        # GPS data: lat_rationals (24 bytes) + lon_rationals (24 bytes)
        lat_data_offset = gps_data_offset
        lon_data_offset = lat_data_offset + 24

        # === Assemble IFD0 ===
        ifd0 = struct.pack(">H", ifd0_count)
        # Entry 1: DateTimeOriginal (0x9003), ASCII, 20 chars
        ifd0 += struct.pack(">HHII", 0x9003, 2, 20, dt_value_offset)
        # Entry 2: ExifIFDPointer — point to ourselves (simplification; not strictly needed)
        ifd0 += struct.pack(">HHII", 0x8769, 4, 1, ifd0_offset)
        # Entry 3: GPSInfoIFDPointer
        ifd0 += struct.pack(">HHII", 0x8825, 4, 1, gps_ifd_offset)
        # Next IFD: none
        ifd0 += struct.pack(">I", 0)

        # === Assemble GPS IFD ===
        gps_ifd = struct.pack(">H", gps_count)
        # GPSLatitudeRef (0x0001): ASCII, 2 bytes — inline
        gps_ifd += struct.pack(">HHI", 0x0001, 2, 2)
        gps_ifd += lat_ref + b'\x00\x00'  # pad to 4 bytes
        # GPSLatitude (0x0002): RATIONAL×3, 24 bytes at lat_data_offset
        gps_ifd += struct.pack(">HHII", 0x0002, 5, 3, lat_data_offset)
        # GPSLongitudeRef (0x0003): ASCII, 2 bytes — inline
        gps_ifd += struct.pack(">HHI", 0x0003, 2, 2)
        gps_ifd += lon_ref + b'\x00\x00'
        # GPSLongitude (0x0004): RATIONAL×3, 24 bytes at lon_data_offset
        gps_ifd += struct.pack(">HHII", 0x0004, 5, 3, lon_data_offset)
        # Next IFD: none
        gps_ifd += struct.pack(">I", 0)

        # === GPS data: 3 RATIONALs each (numerator/denominator pairs) ===
        lat_data = b''
        for i in range(0, 6, 2):
            lat_data += struct.pack(">II", lat_rationals[i], lat_rationals[i + 1])
        lon_data = b''
        for i in range(0, 6, 2):
            lon_data += struct.pack(">II", lon_rationals[i], lon_rationals[i + 1])

        # === Assemble full TIFF ===
        tiff = b'MM'
        tiff += struct.pack(">H", 42)
        tiff += struct.pack(">I", ifd0_offset)
        tiff += ifd0
        tiff += dt_value
        tiff += gps_ifd
        tiff += lat_data
        tiff += lon_data

        # APP1 segment
        exif_header = b'Exif\x00\x00'
        payload = exif_header + tiff
        segment = b'\xff\xe1' + struct.pack(">H", len(payload) + 2) + payload
        return segment

    # ─── AUTOFILL ADDRESS ─────────────────────────────────────────────

    def _forge_address(self, locale: str) -> Dict[str, str]:
        """Generate a realistic billing/shipping address."""
        rng = self._rng
        if locale == "US":
            streets = ["Oak St", "Main St", "Maple Ave", "Cedar Ln", "Park Blvd",
                       "Washington Ave", "Broadway", "Market St", "Pine St", "Elm Dr"]
            cities = [("New York", "NY", "10001"), ("Los Angeles", "CA", "90001"),
                      ("Chicago", "IL", "60601"), ("Houston", "TX", "77001"),
                      ("Miami", "FL", "33101"), ("Seattle", "WA", "98101"),
                      ("San Francisco", "CA", "94102"), ("Austin", "TX", "78701")]
            city, state, zip_base = rng.choice(cities)
            return {
                "address": f"{rng.randint(100, 9999)} {rng.choice(streets)}",
                "apt": f"Apt {rng.randint(1, 12)}{'ABCDEF'[rng.randint(0,5)]}" if rng.random() < 0.3 else "",
                "city": city, "state": state,
                "zip": f"{int(zip_base) + rng.randint(0, 99):05d}",
                "country": "US",
            }
        elif locale == "GB":
            return {
                "address": f"{rng.randint(1, 200)} {rng.choice(['High Street', 'Church Road', 'Station Road', 'Victoria Street'])}",
                "city": rng.choice(["London", "Manchester", "Birmingham", "Leeds"]),
                "state": "", "zip": f"{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))}{rng.randint(1,9)} {rng.randint(1,9)}{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))}",
                "country": "GB",
            }
        else:
            return {"address": f"{rng.randint(1, 100)} Hauptstr.", "city": "Berlin",
                    "state": "", "zip": f"{rng.randint(10000, 99999)}", "country": locale}

    # ─── WIFI NETWORKS ────────────────────────────────────────────────

    def _forge_wifi(self, locale: str, location: str, age_days: int = 90) -> List[Dict]:
        """Generate saved WiFi network list, scaled to device age."""
        rng = self._rng

        home_ssids = {
            "US": ["NETGEAR72-5G", "Xfinity-Home", "ATT-FIBER-5G", "Spectrum-5G-Plus",
                   "Google-Fiber", "Verizon-5G-Home", "TP-Link_5G_A3B2"],
            "GB": ["BT-Hub6-5G", "Sky-WiFi-Home", "Virgin-Media-5G", "TalkTalk-5G"],
            "DE": ["FRITZ!Box-7590", "Telekom-5G", "Vodafone-Home-5G", "o2-WLAN"],
            "FR": ["Livebox-5G", "Freebox-5G", "SFR-Home", "Bouygues-5G"],
        }

        ssid_pool = home_ssids.get(locale, home_ssids["US"])

        # Coffeehouse/restaurant chains — public networks accumulated over device life
        public_chains = [
            "Starbucks", "Starbucks-Guest", "XFINITY WiFi",
            "McDonald's Free WiFi", "Panera Bread", "attwifi",
            "BoingoBFlight", "CableWiFi", "Google Starbucks",
            "TWCWiFi", "Optimum WiFi",
        ]
        # Work/venue SSIDs
        work_prefix = "".join(rng.choices(string.ascii_uppercase, k=4))
        venue_ssids = [
            f"{work_prefix}-Corp", f"{work_prefix}-Office", f"{work_prefix}-Guest",
            "Hotel_WiFi", "Hampton Inn WiFi", "Marriott_GUEST",
            f"{''.join(rng.choices(string.ascii_letters[:26], k=3)).upper()}_Guest",
        ]

        # Core networks everyone has
        networks = [
            {"ssid": rng.choice(ssid_pool), "type": "home", "frequency": "5GHz"},
            {"ssid": f"{''.join(rng.choices(string.ascii_uppercase+string.digits, k=4))}-{rng.choice(['5G', 'WiFi', 'Plus'])}",
             "type": "home_secondary", "frequency": "2.4GHz"},
        ]

        # Scale number of saved networks with device age
        # 90d → 8-15 networks, 365d → 20-40 networks, 500d → 30-55 networks
        extra_count = min(age_days // 10, 50)
        num_public = rng.randint(max(3, extra_count // 4), max(8, extra_count // 2))
        num_venue = rng.randint(1, max(3, extra_count // 6))

        # Sample public/venue networks without repeating
        for ssid in rng.sample(public_chains, min(num_public, len(public_chains))):
            networks.append({"ssid": ssid, "type": "public", "frequency": "2.4GHz"})
        for ssid in rng.sample(venue_ssids, min(num_venue, len(venue_ssids))):
            networks.append({"ssid": ssid, "type": "venue", "frequency": "5GHz"})

        # Friends/family home networks (1 per ~100 days)
        num_friends = rng.randint(0, max(1, age_days // 100))
        friend_routers = ["NETGEAR", "TP-LINK", "Linksys", "ASUS", "XFINITY", "Spectrum"]
        for _ in range(num_friends):
            suffix = "".join(rng.choices(string.ascii_uppercase + string.digits, k=4))
            networks.append({
                "ssid": f"{rng.choice(friend_routers)}_{suffix}",
                "type": "friend", "frequency": rng.choice(["2.4GHz", "5GHz"]),
            })

        return networks

    # ─── APP INSTALLS ─────────────────────────────────────────────────

    def _forge_app_installs(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate backdated app install timestamps."""
        rng = self._rng

        # Core apps that come with the device (day 0)
        core_apps = [
            ("com.android.chrome", "Chrome", 0),
            ("com.google.android.gms", "Google Play services", 0),
            ("com.android.vending", "Play Store", 0),
            ("com.google.android.youtube", "YouTube", 0),
            ("com.google.android.apps.maps", "Maps", 0),
            ("com.google.android.gm", "Gmail", 0),
        ]

        # User-installed apps (installed over time)
        user_apps_us = [
            ("com.instagram.android", "Instagram", rng.randint(1, 10)),
            ("com.whatsapp", "WhatsApp", rng.randint(1, 5)),
            ("com.snapchat.android", "Snapchat", rng.randint(3, 20)),
            ("com.venmo", "Venmo", rng.randint(5, 30)),
            ("com.squareup.cash", "Cash App", rng.randint(10, 40)),
            ("com.ubercab", "Uber", rng.randint(5, 25)),
            ("com.dd.doordash", "DoorDash", rng.randint(7, 35)),
            ("com.spotify.music", "Spotify", rng.randint(2, 15)),
            ("com.amazon.mShop.android.shopping", "Amazon", rng.randint(3, 20)),
            ("com.chase.sig.android", "Chase", rng.randint(5, 25)),
            ("org.telegram.messenger", "Telegram", rng.randint(10, 40)),
        ]

        user_apps_gb = [
            ("com.instagram.android", "Instagram", rng.randint(1, 10)),
            ("com.whatsapp", "WhatsApp", rng.randint(1, 3)),
            ("com.monzo.android", "Monzo", rng.randint(5, 20)),
            ("com.revolut.revolut", "Revolut", rng.randint(5, 25)),
            ("com.deliveroo.orderapp", "Deliveroo", rng.randint(7, 30)),
            ("com.spotify.music", "Spotify", rng.randint(2, 15)),
            ("com.bbc.iplayer", "BBC iPlayer", rng.randint(3, 20)),
        ]

        app_pool = user_apps_us if locale == "US" else user_apps_gb if locale == "GB" else user_apps_us

        # Not everyone installs all apps — pick 6-10
        selected = rng.sample(app_pool, min(rng.randint(6, 10), len(app_pool)))

        # Extended app pools for long-tenure devices
        extended_apps_us = [
            ("com.netflix.mediaclient", "Netflix", rng.randint(5, 30)),
            ("com.twitter.android", "X (Twitter)", rng.randint(3, 25)),
            ("com.tiktok.android", "TikTok", rng.randint(5, 40)),
            ("com.google.android.apps.fitness", "Google Fit", rng.randint(10, 60)),
            ("com.shazam.android", "Shazam", rng.randint(15, 80)),
            ("com.duolingo", "Duolingo", rng.randint(20, 100)),
            ("com.google.android.apps.photos", "Google Photos", rng.randint(1, 10)),
            ("com.lyft.android", "Lyft", rng.randint(10, 60)),
            ("com.ebay.mobile", "eBay", rng.randint(10, 50)),
            ("com.reddit.frontpage", "Reddit", rng.randint(5, 30)),
            ("org.videolan.vlc", "VLC", rng.randint(20, 90)),
            ("com.airbnb.android", "Airbnb", rng.randint(30, 120)),
            ("com.booking", "Booking.com", rng.randint(40, 150)),
            ("com.google.android.apps.tachyon", "Google Meet", rng.randint(10, 50)),
            ("com.facebook.katana", "Facebook", rng.randint(2, 20)),
        ]
        extended_apps_gb = [
            ("com.netflix.mediaclient", "Netflix", rng.randint(5, 30)),
            ("com.twitter.android", "X (Twitter)", rng.randint(3, 25)),
            ("com.bbc.news", "BBC News", rng.randint(5, 20)),
            ("uk.co.bbc.sport", "BBC Sport", rng.randint(10, 40)),
            ("com.google.android.apps.photos", "Google Photos", rng.randint(1, 10)),
            ("com.duolingo", "Duolingo", rng.randint(20, 100)),
        ]

        # Scale how many extra apps a device accumulates over time
        # 90d → pick 2-4 extra, 500d → pick 8-14 extra
        extra_count = min(rng.randint(max(2, age_days // 80), max(6, age_days // 35)),
                          len(extended_apps_us))
        extra_pool = extended_apps_us if locale == "US" else extended_apps_gb if locale == "GB" else extended_apps_us
        extra_selected = rng.sample(extra_pool, min(extra_count, len(extra_pool)))

        # Not everyone installs all apps — scale with age
        min_user = min(6, len(app_pool))
        max_user = min(8 + age_days // 80, len(app_pool))
        selected = rng.sample(app_pool, rng.randint(min_user, max_user))

        installs = []
        for pkg, name, install_day in core_apps:
            dt = now - timedelta(days=age_days)
            installs.append({
                "package": pkg, "name": name,
                "install_time": int(dt.timestamp() * 1000),
                "is_system": True,
            })

        for pkg, name, install_day_offset in selected + extra_selected:
            actual_day = min(install_day_offset, age_days - 1)
            dt = now - timedelta(days=age_days - actual_day)
            installs.append({
                "package": pkg, "name": name,
                "install_time": int(dt.timestamp() * 1000),
                "is_system": False,
            })

        return installs

    # ─── PLAY STORE PURCHASES ──────────────────────────────────────────

    def _forge_play_purchases(self, now: datetime, age_days: int,
                              persona_email: str, locale: str) -> List[Dict]:
        """Generate Play Store purchase history (apps, subscriptions, IAPs)."""
        rng = self._rng
        purchases = []

        # Free app installs (lots of these — 30-80 over profile age)
        free_apps = [
            ("com.whatsapp", "WhatsApp Messenger", 0),
            ("com.instagram.android", "Instagram", 0),
            ("com.spotify.music", "Spotify: Music and Podcasts", 0),
            ("com.netflix.mediaclient", "Netflix", 0),
            ("com.twitter.android", "X", 0),
            ("com.zhiliaoapp.musically", "TikTok", 0),
            ("com.snapchat.android", "Snapchat", 0),
            ("com.ubercab", "Uber - Request a ride", 0),
            ("com.dd.doordash", "DoorDash - Food Delivery", 0),
            ("com.weather.Weather", "The Weather Channel", 0),
            ("com.shazam.android", "Shazam: Find Music & Concerts", 0),
            ("com.duolingo", "Duolingo: Language Lessons", 0),
            ("com.google.android.apps.fitness", "Google Fit", 0),
            ("com.amazon.mShop.android.shopping", "Amazon Shopping", 0),
            ("com.ebay.mobile", "eBay: Online Shopping Deals", 0),
            ("org.telegram.messenger", "Telegram", 0),
            ("com.google.android.keep", "Google Keep", 0),
            ("com.google.android.apps.photos", "Google Photos", 0),
        ]

        num_free = rng.randint(30, min(80, len(free_apps) + 60))
        selected_free = rng.sample(free_apps, min(num_free, len(free_apps)))
        for pkg, name, _ in selected_free:
            install_day = rng.randint(1, max(2, age_days - 1))
            dt = now - timedelta(days=install_day)
            purchases.append({
                "account": persona_email,
                "doc_id": pkg,
                "doc_type": 1,  # app
                "title": name,
                "offer_type": 1,  # free
                "price_micros": 0,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(dt.timestamp() * 1000),
            })

        # Paid app purchases (1-4)
        paid_apps = [
            ("com.weather.forecast.channel.smart", "Weather Forecast Pro", 299),
            ("com.nianticlabs.pokemongo", "Pokémon GO (coins)", 999),
            ("com.mojang.minecraftpe", "Minecraft", 699),
            ("org.videolan.vlc", "VLC for Android (donate)", 199),
            ("com.teslacoilsw.launcher.prime", "Nova Launcher Prime", 499),
        ]
        num_paid = rng.randint(1, min(4, len(paid_apps)))
        for pkg, name, price in rng.sample(paid_apps, num_paid):
            dt = _random_datetime(rng, now, 5, min(age_days, 60))
            purchases.append({
                "account": persona_email,
                "doc_id": pkg,
                "doc_type": 1,
                "title": name,
                "offer_type": 2,  # paid
                "price_micros": price * 1000,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(dt.timestamp() * 1000),
            })

        # Subscriptions (1-3)
        subs = [
            ("com.spotify.music", "Spotify Premium", 999, 30),
            ("com.google.android.youtube", "YouTube Premium", 1399, 30),
            ("com.google.android.apps.subscriptions.red", "Google One (100GB)", 199, 30),
        ]
        num_subs = rng.randint(1, min(3, len(subs)))
        for pkg, name, price, interval in rng.sample(subs, num_subs):
            # First purchase backdated, then recurring
            first_dt = now - timedelta(days=rng.randint(min(30, age_days), max(30, min(age_days, 90))))
            purchases.append({
                "account": persona_email,
                "doc_id": f"{pkg}:subs",
                "doc_type": 4,  # subscription
                "title": name,
                "offer_type": 3,  # subscription
                "price_micros": price * 1000,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(first_dt.timestamp() * 1000),
                "auto_renewing": True,
                "renewal_interval_days": interval,
            })

        purchases.sort(key=lambda x: x["purchase_time"], reverse=True)
        return purchases

    # ─── APP USAGE STATS ───────────────────────────────────────────────

    def _forge_app_usage(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate per-app usage statistics (daily open counts, screen time)."""
        rng = self._rng

        # App usage patterns: (package, avg_daily_minutes, open_frequency)
        usage_patterns = [
            ("com.android.chrome", rng.randint(15, 45), 0.85),
            ("com.instagram.android", rng.randint(20, 60), 0.75),
            ("com.whatsapp", rng.randint(15, 40), 0.90),
            ("com.google.android.youtube", rng.randint(20, 50), 0.70),
            ("com.google.android.gm", rng.randint(5, 15), 0.80),
            ("com.google.android.apps.maps", rng.randint(3, 10), 0.30),
            ("com.spotify.music", rng.randint(30, 90), 0.60),
            ("com.android.vending", rng.randint(2, 8), 0.40),
        ]

        if locale == "US":
            usage_patterns.extend([
                ("com.venmo", rng.randint(2, 8), 0.25),
                ("com.dd.doordash", rng.randint(3, 10), 0.20),
                ("com.amazon.mShop.android.shopping", rng.randint(5, 15), 0.35),
                ("com.chase.sig.android", rng.randint(2, 5), 0.30),
            ])
        elif locale == "GB":
            usage_patterns.extend([
                ("com.monzo.android", rng.randint(2, 8), 0.35),
                ("com.deliveroo.orderapp", rng.randint(3, 8), 0.20),
                ("com.revolut.revolut", rng.randint(2, 5), 0.25),
            ])

        usage_stats = []
        # Usage window: Android UsageStats keeps 365 days but 90 days is typical
        # query range. For a 500-day device, generate 90 days of rich history.
        usage_window = min(90, age_days)
        for pkg, avg_minutes, frequency in usage_patterns:
            # Generate daily stats for the usage window
            daily_stats = []
            for day_offset in range(usage_window):
                if rng.random() > frequency:
                    continue  # Didn't use app that day
                dt = now - timedelta(days=day_offset)
                opens = rng.randint(1, max(2, int(avg_minutes / 5)))
                minutes = max(1, int(avg_minutes * rng.uniform(0.3, 1.8)))
                daily_stats.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "opens": opens,
                    "minutes": minutes,
                    "last_open": int(dt.replace(
                        hour=_circadian_hour(rng),
                        minute=rng.randint(0, 59),
                    ).timestamp() * 1000),
                })

            if daily_stats:
                total_minutes = sum(d["minutes"] for d in daily_stats)
                total_opens = sum(d["opens"] for d in daily_stats)
                usage_stats.append({
                    "package": pkg,
                    "total_minutes": total_minutes,
                    "total_opens": total_opens,
                    "avg_daily_minutes": total_minutes // max(len(daily_stats), 1),
                    "days_active": len(daily_stats),
                    "last_used": max(d["last_open"] for d in daily_stats),
                    "daily": daily_stats,
                })

        usage_stats.sort(key=lambda x: x["total_minutes"], reverse=True)
        return usage_stats

    # ─── NOTIFICATION HISTORY ──────────────────────────────────────────

    def _forge_notifications(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate recent notification records (last 7 days)."""
        rng = self._rng
        notifications = []

        # Notification templates: (package, title_template, body_template, frequency_per_day)
        notif_templates = [
            ("com.google.android.gm", "New email from {sender}",
             "{subject}", 3.0),
            ("com.whatsapp", "{contact}: {message}",
             "", 5.0),
            ("com.instagram.android", "{user} liked your photo",
             "", 2.0),
            ("com.android.vending", "Update available",
             "{app} update ready to install", 0.5),
        ]

        if locale == "US":
            notif_templates.extend([
                ("com.chase.sig.android", "Transaction alert",
                 "Purchase of ${amount} at {merchant} approved", 0.8),
                ("com.dd.doordash", "Your order is on the way!",
                 "Estimated arrival: {time}", 0.3),
                ("com.venmo", "{person} paid you ${amount}",
                 "", 0.2),
            ])
        elif locale == "GB":
            notif_templates.extend([
                ("com.monzo.android", "Payment",
                 "You spent £{amount} at {merchant}", 0.8),
                ("com.deliveroo.orderapp", "Your food is being prepared",
                 "Estimated delivery: {time}", 0.3),
            ])

        # Generic fillers
        senders = ["Sarah", "Mike", "Amazon", "LinkedIn", "DoorDash", "Mom", "Work"]
        subjects = ["Meeting tomorrow", "Your order shipped", "Weekly summary",
                    "New connection request", "Receipt for your purchase"]
        contacts = ["Mom", "Sarah", "Mike", "Dave", "Work Group"]
        merchants = ["WALMART", "STARBUCKS", "TARGET", "AMAZON", "SHELL", "UBER"]
        apps_to_update = ["Instagram", "WhatsApp", "Chrome", "YouTube", "Spotify"]

        for day_offset in range(min(30, age_days)):
            dt_base = now - timedelta(days=day_offset)
            for pkg, title_tmpl, body_tmpl, freq in notif_templates:
                # Poisson-like: some days more, some less
                count = max(0, int(freq * rng.uniform(0.2, 2.0)))
                for _ in range(count):
                    dt = dt_base.replace(
                        hour=_circadian_hour(rng),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                    )
                    title = title_tmpl.format(
                        sender=rng.choice(senders),
                        contact=rng.choice(contacts),
                        user=rng.choice(contacts),
                        person=rng.choice(contacts),
                        message="Hey! Are you free?",
                        app=rng.choice(apps_to_update),
                        amount=f"{rng.randint(5, 200)}.{rng.randint(0, 99):02d}",
                        merchant=rng.choice(merchants),
                        time=f"{rng.randint(15, 45)} min",
                        subject=rng.choice(subjects),
                    )
                    body = body_tmpl.format(
                        sender=rng.choice(senders),
                        subject=rng.choice(subjects),
                        amount=f"{rng.randint(5, 200)}.{rng.randint(0, 99):02d}",
                        merchant=rng.choice(merchants),
                        time=f"{rng.randint(15, 45)} min",
                        app=rng.choice(apps_to_update),
                    ) if body_tmpl else ""

                    notifications.append({
                        "package": pkg,
                        "title": title,
                        "body": body,
                        "timestamp": int(dt.timestamp() * 1000),
                        "seen": rng.random() < 0.8,
                    })

        notifications.sort(key=lambda x: x["timestamp"], reverse=True)
        return notifications

    # ─── EMAIL RECEIPTS ────────────────────────────────────────────────

    def _forge_email_receipts(self, now: datetime, age_days: int,
                              persona_email: str, locale: str) -> List[Dict]:
        """Generate purchase confirmation email records for cross-validation."""
        rng = self._rng
        receipts = []

        if locale == "US":
            merchants = [
                ("Amazon.com", "order@amazon.com", "Your Amazon.com order of {item}",
                 ["Echo Dot", "USB-C Cable", "Phone Case", "Bluetooth Earbuds", "Kindle Book"]),
                ("DoorDash", "no-reply@doordash.com", "Your DoorDash order receipt",
                 ["Chipotle", "McDonald's", "Panda Express", "Subway", "Pizza Hut"]),
                ("Uber", "uber.us@uber.com", "Your trip with Uber",
                 ["Trip to Downtown", "Trip to Airport", "Trip to Home"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium", "Google One", "In-app purchase"]),
                ("Walmart", "help@walmart.com", "Your Walmart order confirmation",
                 ["Groceries", "Electronics", "Household items"]),
            ]
        elif locale == "GB":
            merchants = [
                ("Amazon.co.uk", "order@amazon.co.uk", "Your Amazon.co.uk order of {item}",
                 ["Phone Case", "USB Cable", "Kindle Book", "Echo Dot"]),
                ("Deliveroo", "no-reply@deliveroo.co.uk", "Your Deliveroo receipt",
                 ["Nando's", "Wagamama", "Domino's", "McDonald's"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium"]),
            ]
        else:
            merchants = [
                ("Amazon", "order@amazon.com", "Your order of {item}",
                 ["Phone Case", "USB Cable", "Book"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium"]),
            ]

        # Generate receipts proportional to age — 500-day device: 80-150 receipts
        # Real Gmail inboxes have 1-3 order receipts/week
        receipts_per_week = rng.uniform(0.8, 2.5)
        total_weeks = age_days / 7.0
        num_receipts = rng.randint(
            max(5, int(total_weeks * 0.5)),
            min(200, max(10, int(total_weeks * receipts_per_week)))
        )
        for _ in range(num_receipts):
            merchant = rng.choice(merchants)
            item = rng.choice(merchant[3])
            dt = _random_datetime(rng, now, 1, age_days)

            if locale == "US":
                amount = f"${rng.randint(5, 150)}.{rng.randint(0, 99):02d}"
                currency = "USD"
            elif locale == "GB":
                amount = f"£{rng.randint(5, 100)}.{rng.randint(0, 99):02d}"
                currency = "GBP"
            else:
                amount = f"€{rng.randint(5, 120)}.{rng.randint(0, 99):02d}"
                currency = "EUR"

            receipts.append({
                "from": merchant[1],
                "to": persona_email,
                "merchant": merchant[0],
                "subject": merchant[2].format(item=item),
                "item": item,
                "amount": amount,
                "currency": currency,
                "date": dt.isoformat(),
                "timestamp": int(dt.timestamp() * 1000),
                "order_id": f"#{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}",
            })

        receipts.sort(key=lambda x: x["timestamp"], reverse=True)
        return receipts

    # ─── GOOGLE MAPS HISTORY ──────────────────────────────────────────

    def _forge_maps_history(self, now: datetime, age_days: int,
                             location: str, locale: str) -> List[Dict]:
        """Generate Google Maps search + navigation history.

        500-day device: 400-1200 map searches, 200-600 navigations.
        Empty Maps history is a strong emulator signal for risk engines.
        """
        rng = self._rng

        # Location-keyed POI pools
        POI_POOLS = {
            "nyc": [
                "Times Square", "Central Park", "JFK Airport", "Penn Station",
                "Brooklyn Bridge", "Yankee Stadium", "Madison Square Garden",
                "Empire State Building", "Grand Central Terminal",
                "Columbia University", "NYU Medical Center",
            ],
            "la": [
                "LAX Airport", "Santa Monica Pier", "Hollywood Bowl",
                "Dodger Stadium", "Getty Center", "Venice Beach",
                "Universal Studios Hollywood", "Griffith Observatory",
            ],
            "london": [
                "Heathrow Airport", "King's Cross Station", "Oxford Street",
                "Canary Wharf", "London Bridge", "Hyde Park", "Waterloo Station",
                "British Museum", "Paddington Station",
            ],
            "berlin": [
                "Berlin Hauptbahnhof", "Alexanderplatz", "Brandenburg Gate",
                "Berlin Tegel Airport", "Potsdamer Platz", "Unter den Linden",
            ],
            "paris": [
                "Gare du Nord", "Eiffel Tower", "Champs-Élysées",
                "Charles de Gaulle Airport", "Louvre Museum", "Montmartre",
            ],
        }

        GENERIC_POIS = {
            "US": [
                "Walmart", "Target", "Costco", "Home Depot", "CVS Pharmacy",
                "Walgreens", "Starbucks", "McDonald's", "Chipotle",
                "Planet Fitness", "AMC Theatre",
            ],
            "GB": [
                "Tesco Extra", "Sainsbury's", "Boots Pharmacy", "Costa Coffee",
                "Primark", "Marks & Spencer", "Lidl", "ASDA Superstore",
            ],
            "DE": [
                "REWE", "Edeka", "Aldi", "dm-drogerie markt",
                "Saturn Electronics", "MediaMarkt",
            ],
            "FR": [
                "Carrefour", "Monoprix", "Decathlon", "Fnac", "Casino",
            ],
        }

        location_pois = POI_POOLS.get(location, POI_POOLS.get("nyc", []))
        generic_pois = GENERIC_POIS.get(locale, GENERIC_POIS["US"])
        all_pois = location_pois + generic_pois

        # Scale search volume with age
        # ~1-3 searches/day + ~0.5 navigations/day on avg
        searches_lo = max(50, int(age_days * 0.8))
        searches_hi = max(searches_lo + 50, min(int(age_days * 2.5), 1500))
        num_searches = rng.randint(searches_lo, searches_hi)

        nav_lo = max(20, int(age_days * 0.3))
        nav_hi = max(nav_lo + 20, min(int(age_days * 1.2), 700))
        num_navigations = rng.randint(nav_lo, nav_hi)

        entries = []

        for _ in range(num_searches):
            poi = rng.choice(all_pois)
            dt = _random_datetime(rng, now, 0, age_days)
            entries.append({
                "type": "search",
                "query": poi,
                "timestamp": int(dt.timestamp() * 1000),
                "lat": None,
                "lon": None,
            })

        for _ in range(num_navigations):
            destination = rng.choice(all_pois)
            dt = _random_datetime(rng, now, 0, age_days)
            duration_min = rng.randint(5, 60)
            distance_km = round(rng.uniform(0.5, 30.0), 1)
            entries.append({
                "type": "navigation",
                "destination": destination,
                "duration_min": duration_min,
                "distance_km": distance_km,
                "timestamp": int(dt.timestamp() * 1000),
            })

        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        return entries

    # ─── SAMSUNG HEALTH ──────────────────────────────────────────────

    def _forge_samsung_health(self, now: datetime, age_days: int,
                               archetype: str) -> Dict[str, Any]:
        """Generate Samsung Health steps + sleep data correlated with archetype."""
        rng = self._rng
        steps_daily = []
        sleep_records = []

        # Archetype-driven base activity levels
        ACTIVITY_BASES = {
            "professional": (6000, 12000),  # moderate walker
            "student": (4000, 9000),        # campus walking
            "night_shift": (3000, 7000),    # sedentary shift
            "retiree": (3000, 8000),        # light walking
            "gamer": (2000, 5000),          # sedentary
        }
        step_lo, step_hi = ACTIVITY_BASES.get(archetype, (5000, 10000))

        for day_offset in range(min(age_days, 365)):
            dt = now - timedelta(days=day_offset)
            is_weekend = dt.weekday() >= 5

            # Weekend modifier: ±20% 
            if is_weekend:
                daily_steps = rng.randint(int(step_lo * 0.8), int(step_hi * 1.2))
            else:
                daily_steps = rng.randint(step_lo, step_hi)

            # Occasional highly active days (gym, travel)
            if rng.random() < 0.08:
                daily_steps = int(daily_steps * rng.uniform(1.5, 2.5))
            # Occasional sick/lazy days
            if rng.random() < 0.05:
                daily_steps = int(daily_steps * rng.uniform(0.1, 0.3))

            steps_daily.append({
                "date": dt.strftime("%Y-%m-%d"),
                "steps": daily_steps,
                "distance_m": int(daily_steps * rng.uniform(0.65, 0.85)),
                "calories": int(daily_steps * rng.uniform(0.035, 0.055)),
            })

            # Sleep: 85% chance of recorded sleep per night
            if rng.random() < 0.85:
                # Archetype sleep patterns
                if archetype == "night_shift":
                    sleep_start_h = rng.randint(6, 9)
                elif archetype == "student":
                    sleep_start_h = rng.randint(0, 3)
                elif archetype == "retiree":
                    sleep_start_h = rng.randint(21, 23)
                else:
                    sleep_start_h = rng.randint(22, 24) % 24

                sleep_duration_min = rng.randint(300, 540)  # 5-9 hours
                sleep_start = dt.replace(hour=sleep_start_h, minute=rng.randint(0, 59))
                sleep_end = sleep_start + timedelta(minutes=sleep_duration_min)

                # Sleep stages: light, deep, REM proportions
                deep_pct = rng.uniform(0.15, 0.25)
                rem_pct = rng.uniform(0.2, 0.3)
                light_pct = 1.0 - deep_pct - rem_pct

                sleep_records.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "start": int(sleep_start.timestamp() * 1000),
                    "end": int(sleep_end.timestamp() * 1000),
                    "duration_min": sleep_duration_min,
                    "deep_min": int(sleep_duration_min * deep_pct),
                    "light_min": int(sleep_duration_min * light_pct),
                    "rem_min": int(sleep_duration_min * rem_pct),
                    "efficiency": round(rng.uniform(0.78, 0.96), 2),
                })

        return {
            "steps_daily": steps_daily,
            "sleep_records": sleep_records,
        }

    # ─── LOCAL STORAGE (Chrome) ──────────────────────────────────────

    def _forge_local_storage(self, now: datetime, age_days: int,
                              locale: str, persona_email: str) -> Dict[str, Any]:
        """Generate Chrome localStorage entries for key domains.
        
        Real devices have localStorage populated by visited sites.
        Empty localStorage is an emulator signal.
        """
        rng = self._rng
        storage = {}

        # Google localStorage
        storage["https://www.google.com"] = {
            "gads:cid": secrets.token_hex(16),
            "NID": f"{rng.randint(100, 300)}={secrets.token_hex(32)}",
            "DV": secrets.token_hex(8),
            "__Secure-ENID": secrets.token_hex(24),
        }

        # YouTube localStorage
        yt_volume = rng.randint(20, 80)
        storage["https://www.youtube.com"] = {
            "yt-player-quality": rng.choice(["medium", "hd720", "hd1080"]),
            "yt-player-volume": json.dumps({"data": str(yt_volume), "creation": int((now - timedelta(days=rng.randint(1, age_days))).timestamp() * 1000)}),
            "yt-remote-connected-devices": json.dumps({"data": "[]", "creation": int(now.timestamp() * 1000)}),
            "yt.innertube::nextId": str(rng.randint(1, 500)),
            "yt.innertube::requests": str(rng.randint(100, 5000)),
        }

        # Amazon localStorage (if US/GB)
        if locale in ("US", "GB"):
            storage["https://www.amazon.com" if locale == "US" else "https://www.amazon.co.uk"] = {
                "csm-hit": f"tb:{secrets.token_hex(12)}+s-{secrets.token_hex(12)}|{int(now.timestamp()*1000)}",
                "session-id": f"{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}-{rng.randint(1000000, 9999999)}",
                "ubid-main": f"{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}-{rng.randint(1000000, 9999999)}",
            }

        # Instagram localStorage
        storage["https://www.instagram.com"] = {
            "ig-set-ig-did": str(uuid.uuid4()),
            "ig-set-ig-pr": str(rng.choice([1, 2, 3])),
        }

        # Twitter/X localStorage
        storage["https://x.com"] = {
            "rweb-setting-key-guest-id": str(rng.randint(10**17, 10**18)),
            "rweb-setting-key-d_prefs": json.dumps({"dark_mode": rng.choice([True, False])}),
        }

        # Reddit localStorage
        storage["https://www.reddit.com"] = {
            "recent_srs": json.dumps([f"r/{s}" for s in rng.sample(
                ["AskReddit", "funny", "gaming", "news", "worldnews", "pics",
                 "todayilearned", "movies", "technology", "science"],
                k=rng.randint(3, 7))]),
        }

        # Google Account localStorage
        storage["https://accounts.google.com"] = {
            "accountChooserSaved": persona_email,
            "ACCOUNT_CHOOSER": persona_email,
        }

        return storage

    # ─── SENSOR TRACE METADATA ───────────────────────────────────────

    def _forge_sensor_traces(self, now: datetime, age_days: int,
                              archetype: str) -> List[Dict[str, Any]]:
        """Generate historical sensor trace metadata for profile age.
        
        Produces daily summaries of accelerometer/gyro activity that 
        correlate with Samsung Health steps and archetype circadian pattern.
        Used by sensor_simulator for warm-start calibration.
        """
        rng = self._rng
        traces = []

        for day_offset in range(min(age_days, 180)):
            dt = now - timedelta(days=day_offset)
            is_weekend = dt.weekday() >= 5

            # Active hours per day based on archetype
            if archetype == "gamer":
                active_hours = rng.randint(2, 6)
            elif archetype == "retiree":
                active_hours = rng.randint(3, 8)
            elif archetype == "night_shift":
                active_hours = rng.randint(4, 8)
            else:
                active_hours = rng.randint(5, 12)

            if is_weekend:
                active_hours = max(2, active_hours + rng.randint(-2, 2))

            # Aggregate sensor stats for the day
            avg_accel = round(rng.uniform(0.02, 0.15) * (active_hours / 8.0), 4)
            avg_gyro = round(rng.uniform(0.1, 1.5) * (active_hours / 8.0), 4)
            max_accel = round(avg_accel * rng.uniform(3.0, 8.0), 4)

            traces.append({
                "date": dt.strftime("%Y-%m-%d"),
                "active_hours": active_hours,
                "avg_accel_g": avg_accel,
                "avg_gyro_dps": avg_gyro,
                "peak_accel_g": max_accel,
                "total_gesture_events": rng.randint(active_hours * 50, active_hours * 200),
                "gps_fixes": rng.randint(active_hours * 2, active_hours * 10),
            })

        return traces

    # ═══════════════════════════════════════════════════════════════════
    # V12: LIFE-PATH COHERENCE ENGINE
    # Cross-correlates independently generated data into a coherent
    # timeline. This is the core v12 differentiator.
    # ═══════════════════════════════════════════════════════════════════

    def _correlate_lifepath(self, raw: Dict[str, Any], now: datetime,
                            age_days: int, location: str, locale: str,
                            circadian_weights: List[float],
                            tz_offset: float,
                            persona_email: str) -> Dict[str, Any]:
        """Post-process all forged data to create cross-data correlations.
        
        Correlation rules implemented:
        1. Email receipts → Chrome history visits on same day
        2. Maps navigation → Chrome search for destination ±2h before
        3. Frequent contacts → Call log clusters at consistent hours
        4. Purchase notifications → Cookie session refresh on merchant domain
        5. Gallery photos GPS → Maps history location on same day
        6. SMS conversations → Contact call log temporal proximity
        7. Samsung Health steps → Sensor traces active hours correlation
        8. WiFi networks → Maps history geographic consistency
        """
        rng = self._rng
        result = {k: list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v
                  for k, v in raw.items()}
        lifepath_events = []

        # ── 1. Email receipt → Chrome history correlation ──
        for receipt in result.get("email_receipts", []):
            ts = receipt.get("timestamp", 0)
            if ts <= 0:
                continue
            merchant = receipt.get("merchant", "")
            domain_map = {
                "Amazon": "https://www.amazon.com/gp/css/order-history",
                "DoorDash": "https://www.doordash.com/orders",
                "Uber": "https://riders.uber.com/trips",
                "Google Play": "https://play.google.com/store/account/orderhistory",
                "Walmart": "https://www.walmart.com/orders",
            }
            url = domain_map.get(merchant)
            if url and rng.random() < 0.7:  # 70% chance of correlated visit
                # Visit ±4h from receipt timestamp
                offset_ms = rng.randint(-4 * 3600000, 4 * 3600000)
                visit_ts = ts + offset_ms
                result["history"].append({
                    "url": url,
                    "title": f"Order History - {merchant}",
                    "visit_count": rng.randint(1, 3),
                    "timestamp": visit_ts,
                })
                lifepath_events.append({
                    "type": "purchase_browse",
                    "timestamp": visit_ts,
                    "merchant": merchant,
                    "correlation": "email_receipt→chrome_history",
                })

        # ── 2. Maps navigation → Chrome search before trip ──
        for entry in result.get("maps_history", []):
            if entry.get("type") != "navigation":
                continue
            ts = entry.get("timestamp", 0)
            dest = entry.get("destination", "")
            if ts <= 0 or not dest:
                continue
            if rng.random() < 0.5:  # 50% searched before navigating
                search_offset_ms = rng.randint(30 * 60000, 3 * 3600000)  # 30min-3h before
                search_ts = ts - search_offset_ms
                result["history"].append({
                    "url": f"https://www.google.com/search?q={dest.replace(' ', '+')}+directions",
                    "title": f"{dest} - Google Search",
                    "visit_count": 1,
                    "timestamp": search_ts,
                })

        # ── 3. Frequent contacts → consistent call windows ──
        # Identify top 5 contacts by call frequency
        contact_call_counts: Dict[str, int] = {}
        for call in result.get("call_logs", []):
            cname = call.get("contact_name", "")
            if cname:
                contact_call_counts[cname] = contact_call_counts.get(cname, 0) + 1
        top_contacts = sorted(contact_call_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        for contact_name, count in top_contacts:
            # Assign a preferred call hour for this contact (relationship pattern)
            preferred_hour = rng.randint(8, 22)
            calls_for_contact = [c for c in result["call_logs"] if c.get("contact_name") == contact_name]
            # Nudge 60% of calls toward preferred hour
            for call in calls_for_contact:
                if rng.random() < 0.6:
                    ts = call.get("timestamp", 0)
                    if ts > 0:
                        dt = datetime.fromtimestamp(ts / 1000)
                        dt = dt.replace(hour=preferred_hour, minute=rng.randint(0, 59))
                        call["timestamp"] = int(dt.timestamp() * 1000)

        # ── 4. Purchase notifications → Cookie session refresh ──
        for receipt in result.get("email_receipts", []):
            ts = receipt.get("timestamp", 0)
            merchant = receipt.get("merchant", "")
            cookie_domain_map = {
                "Amazon": ".amazon.com",
                "Walmart": ".walmart.com",
                "Google Play": ".google.com",
            }
            domain = cookie_domain_map.get(merchant)
            if domain and rng.random() < 0.6:
                # Refresh session cookie near purchase time
                for cookie in result.get("cookies", []):
                    if cookie.get("domain") == domain and "session" in cookie.get("name", "").lower():
                        cookie["last_access_utc"] = ts // 1000
                        break

        # ── 5. Gallery photos → Maps history location proximity ──
        # For photos with EXIF GPS, ensure a Maps search exists near same location/day
        for photo in result.get("gallery_paths", []):
            if isinstance(photo, dict) and photo.get("lat") and photo.get("lon"):
                photo_ts = photo.get("timestamp", 0)
                if photo_ts > 0 and rng.random() < 0.4:
                    result["maps_history"].append({
                        "type": "search",
                        "query": f"{photo.get('lat', 0):.4f},{photo.get('lon', 0):.4f}",
                        "timestamp": photo_ts - rng.randint(0, 3600000),
                        "lat": photo.get("lat"),
                        "lon": photo.get("lon"),
                    })

        # ── 6. SMS threads → Contact call temporal proximity ──
        # If a contact has both SMS and calls, cluster some on same day
        sms_contacts = set()
        for sms in result.get("sms", []):
            sms_contacts.add(sms.get("contact_name", ""))
        call_contacts = set()
        for call in result.get("call_logs", []):
            call_contacts.add(call.get("contact_name", ""))
        overlap = sms_contacts & call_contacts - {""}

        for contact_name in list(overlap)[:10]:
            contact_sms = [s for s in result["sms"] if s.get("contact_name") == contact_name]
            contact_calls = [c for c in result["call_logs"] if c.get("contact_name") == contact_name]
            # For 30% of SMS, add a call within ±2h
            for sms in contact_sms:
                if rng.random() < 0.3 and contact_calls:
                    sms_ts = sms.get("timestamp", 0)
                    if sms_ts > 0:
                        nearest_call = min(contact_calls, key=lambda c: abs(c.get("timestamp", 0) - sms_ts))
                        # Nudge call closer to SMS
                        offset = rng.randint(-2 * 3600000, 2 * 3600000)
                        nearest_call["timestamp"] = sms_ts + offset

        # ── 7. Samsung Health steps → Sensor traces correlation ──
        steps_by_date = {}
        for step in result.get("samsung_health", {}).get("steps_daily", []):
            steps_by_date[step["date"]] = step["steps"]

        for trace in result.get("sensor_traces", []):
            date_str = trace.get("date", "")
            if date_str in steps_by_date:
                steps = steps_by_date[date_str]
                # Correlate: more steps → more active hours, higher avg accel
                step_factor = min(steps / 10000.0, 2.0)
                trace["active_hours"] = max(2, int(trace["active_hours"] * (0.5 + 0.5 * step_factor)))
                trace["avg_accel_g"] = round(trace["avg_accel_g"] * (0.7 + 0.3 * step_factor), 4)
                trace["total_gesture_events"] = int(trace["total_gesture_events"] * (0.6 + 0.4 * step_factor))

        # ── 8. WiFi networks → Maps history geographic consistency ──
        # Ensure "home" wifi appears in Maps searches near home-like POIs
        home_wifi = [w for w in result.get("wifi_networks", []) if w.get("type") == "home"]
        if home_wifi and result.get("maps_history"):
            home_ssid = home_wifi[0].get("ssid", "Home WiFi")
            # Tag some maps searches as "near home"
            for entry in result["maps_history"][:20]:
                if entry.get("type") == "search" and rng.random() < 0.2:
                    lifepath_events.append({
                        "type": "home_activity",
                        "timestamp": entry.get("timestamp", 0),
                        "wifi": home_ssid,
                        "correlation": "wifi_home→maps_proximity",
                    })

        # ── Re-sort modified lists ──
        result["history"].sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        result["maps_history"].sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        result["call_logs"].sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        result["sms"].sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        lifepath_events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        result["lifepath_events"] = lifepath_events

        logger.info(f"Life-Path correlation: {len(lifepath_events)} cross-data events generated")
        return result

    # ─── SAVE ─────────────────────────────────────────────────────────

    def _save_profile(self, profile: Dict[str, Any]):
        """Save profile JSON to disk."""
        profiles_dir = TITAN_DATA / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_file = profiles_dir / f"{profile['id']}.json"

        # Don't save gallery_paths in JSON (they're file paths)
        save_data = {k: v for k, v in profile.items() if k != "gallery_paths"}
        save_data["gallery_count"] = len(profile.get("gallery_paths", []))

        profile_file.write_text(json.dumps(save_data, indent=2, default=str))
        logger.info(f"Profile saved: {profile_file}")
