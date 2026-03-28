"""
Titan V12 — Hive Coordinator (Synthetic Social Graph)
Cross-device coordination for interconnected persona clusters.

Creates a "social graph" across multiple Titan devices where:
  - Devices in the same cluster share contacts (bidirectional)
  - Shared WiFi BSSIDs match geographic proximity (±50m GPS cluster)
  - Cross-device SMS/call logs have matching entries on both sides
  - Shared Chrome cookies for family/workplace Google accounts
  - Trust elevation: Google graph analysis sees "family"/"office" cluster

Architecture:
  - Cluster state stored in TITAN_DATA/hive/<cluster_name>.json
  - Each device gets a HiveMembership with its role and shared data
  - Coordinator generates shared data, then ProfileInjector pulls
    the device-specific portion during injection

Cluster types:
  - "family": 2-5 devices, shared home WiFi, frequent cross-calls
  - "office": 3-8 devices, shared office WiFi, business-hours calls
  - "friends": 2-6 devices, shared social WiFi, evening SMS

Usage:
    hive = HiveCoordinator("mercer_family")
    hive.register_device("titan-cvd-1", persona={"name": "Alex Mercer", ...})
    hive.register_device("titan-cvd-2", persona={"name": "Sarah Mercer", ...})
    shared = hive.generate_shared_data()
    device1_data = hive.get_device_data("titan-cvd-1")
"""

import hashlib
import json
import logging
import os
import random
import secrets
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.hive")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))


# ═══════════════════════════════════════════════════════════════════════
# CLUSTER TYPES
# ═══════════════════════════════════════════════════════════════════════

CLUSTER_PROFILES = {
    "family": {
        "max_devices": 5,
        "shared_wifi_count": 2,     # home + parents/in-laws
        "cross_call_daily": 1.5,    # avg calls between members/day
        "cross_sms_daily": 3.0,     # avg SMS between members/day
        "shared_contacts_pct": 0.3, # 30% of contacts shared
        "call_hour_range": (7, 22), # family calls: morning to evening
        "relationship_types": ["spouse", "parent", "sibling", "child"],
    },
    "office": {
        "max_devices": 8,
        "shared_wifi_count": 1,     # office WiFi only
        "cross_call_daily": 0.5,    # business calls
        "cross_sms_daily": 1.0,     # slack/teams replacement
        "shared_contacts_pct": 0.15,
        "call_hour_range": (8, 18), # business hours
        "relationship_types": ["colleague", "manager", "direct_report"],
    },
    "friends": {
        "max_devices": 6,
        "shared_wifi_count": 3,     # cafe, gym, friend's house
        "cross_call_daily": 0.3,
        "cross_sms_daily": 2.0,
        "shared_contacts_pct": 0.2,
        "call_hour_range": (11, 23),
        "relationship_types": ["friend", "roommate", "classmate"],
    },
}


@dataclass
class HiveMember:
    """A device registered in a Hive cluster."""
    device_id: str
    persona_name: str
    persona_email: str
    persona_phone: str
    role: str = "member"  # "anchor" | "member"
    relationship: str = "friend"
    registered_at: float = 0.0

    def __post_init__(self):
        if not self.registered_at:
            self.registered_at = time.time()


@dataclass
class SharedWiFi:
    """A WiFi network shared across cluster members."""
    ssid: str
    bssid: str
    security: str = "WPA2"
    frequency: int = 5180
    signal_level: int = -55
    center_lat: float = 0.0
    center_lon: float = 0.0
    radius_m: float = 50.0


@dataclass 
class CrossDeviceLog:
    """A call or SMS log entry that exists on two devices."""
    from_device: str
    to_device: str
    from_phone: str
    to_phone: str
    from_name: str
    to_name: str
    log_type: str  # "call" | "sms"
    timestamp_ms: int = 0
    duration_sec: int = 0  # calls only
    sms_body: str = ""     # sms only


class HiveCoordinator:
    """Coordinates synthetic social graphs across multiple Titan devices."""

    def __init__(self, cluster_name: str, cluster_type: str = "family"):
        self.cluster_name = cluster_name
        self.cluster_type = cluster_type
        self.profile = CLUSTER_PROFILES.get(cluster_type, CLUSTER_PROFILES["family"])
        self.members: List[HiveMember] = []
        self.shared_wifi: List[SharedWiFi] = []
        self.cross_logs: List[CrossDeviceLog] = []
        self._rng = random.Random(
            int(hashlib.sha256(cluster_name.encode()).hexdigest()[:16], 16)
        )
        self._state_file = TITAN_DATA / "hive" / f"{cluster_name}.json"

        # Load existing state
        self._load_state()

    def register_device(self, device_id: str,
                        persona: Dict[str, str],
                        role: str = "member") -> HiveMember:
        """Register a device in the Hive cluster.
        
        Args:
            device_id: Titan device ID (e.g., "titan-cvd-1")
            persona: Dict with name, email, phone
            role: "anchor" (first device) or "member"
        """
        if len(self.members) >= self.profile["max_devices"]:
            logger.warning(f"Cluster {self.cluster_name} full ({len(self.members)}/{self.profile['max_devices']})")

        # Check for duplicate
        for m in self.members:
            if m.device_id == device_id:
                logger.info(f"Device {device_id} already in cluster, updating")
                m.persona_name = persona.get("name", m.persona_name)
                m.persona_email = persona.get("email", m.persona_email)
                m.persona_phone = persona.get("phone", m.persona_phone)
                self._save_state()
                return m

        # Assign relationship based on order
        relationships = self.profile["relationship_types"]
        rel_idx = len(self.members) % len(relationships)
        relationship = relationships[rel_idx]

        if not self.members:
            role = "anchor"

        member = HiveMember(
            device_id=device_id,
            persona_name=persona.get("name", "Unknown"),
            persona_email=persona.get("email", "unknown@example.com"),
            persona_phone=persona.get("phone", "+10000000000"),
            role=role,
            relationship=relationship,
        )
        self.members.append(member)
        self._save_state()

        logger.info(f"Device {device_id} registered in cluster '{self.cluster_name}' "
                    f"as {relationship} ({len(self.members)} members)")
        return member

    def unregister_device(self, device_id: str):
        """Remove a device from the cluster."""
        self.members = [m for m in self.members if m.device_id != device_id]
        self._save_state()
        logger.info(f"Device {device_id} removed from cluster '{self.cluster_name}'")

    def generate_shared_data(self, age_days: int = 90,
                              center_lat: float = 40.7128,
                              center_lon: float = -74.0060) -> Dict[str, Any]:
        """Generate all shared data for the cluster.
        
        Returns dict keyed by device_id with each device's shared data.
        Must be called after all devices are registered.
        """
        if len(self.members) < 2:
            logger.warning("Need at least 2 members to generate shared data")
            return {}

        rng = self._rng
        result: Dict[str, Any] = {}

        # 1. Generate shared WiFi networks
        self.shared_wifi = self._generate_shared_wifi(center_lat, center_lon)

        # 2. Generate cross-device contacts
        shared_contacts = self._generate_shared_contacts()

        # 3. Generate cross-device call logs
        cross_calls = self._generate_cross_calls(age_days)

        # 4. Generate cross-device SMS
        cross_sms = self._generate_cross_sms(age_days)

        self.cross_logs = cross_calls + cross_sms

        # 5. Build per-device data packages
        for member in self.members:
            device_contacts = []
            device_calls = []
            device_sms = []

            # Add other cluster members as contacts
            for other in self.members:
                if other.device_id == member.device_id:
                    continue
                device_contacts.append({
                    "name": other.persona_name,
                    "phone": other.persona_phone,
                    "email": other.persona_email,
                    "relationship": other.relationship,
                    "source": "hive_cluster",
                })

            # Add shared contacts (mutual friends/colleagues)
            for contact in shared_contacts:
                if member.device_id in contact["shared_with"]:
                    device_contacts.append({
                        "name": contact["name"],
                        "phone": contact["phone"],
                        "relationship": "mutual",
                        "source": "hive_shared",
                    })

            # Add cross-device calls for this device
            for log in cross_calls:
                if log.from_device == member.device_id:
                    device_calls.append({
                        "contact_name": log.to_name,
                        "phone": log.to_phone,
                        "type": "outgoing",
                        "duration_sec": log.duration_sec,
                        "timestamp": log.timestamp_ms,
                        "source": "hive_cross",
                    })
                elif log.to_device == member.device_id:
                    device_calls.append({
                        "contact_name": log.from_name,
                        "phone": log.from_phone,
                        "type": "incoming",
                        "duration_sec": log.duration_sec,
                        "timestamp": log.timestamp_ms,
                        "source": "hive_cross",
                    })

            # Add cross-device SMS for this device
            for log in cross_sms:
                if log.from_device == member.device_id:
                    device_sms.append({
                        "contact_name": log.to_name,
                        "phone": log.to_phone,
                        "type": "sent",
                        "body": log.sms_body,
                        "timestamp": log.timestamp_ms,
                        "source": "hive_cross",
                    })
                elif log.to_device == member.device_id:
                    device_sms.append({
                        "contact_name": log.from_name,
                        "phone": log.from_phone,
                        "type": "received",
                        "body": log.sms_body,
                        "timestamp": log.timestamp_ms,
                        "source": "hive_cross",
                    })

            result[member.device_id] = {
                "cluster_name": self.cluster_name,
                "cluster_type": self.cluster_type,
                "member_count": len(self.members),
                "shared_wifi": [asdict(w) for w in self.shared_wifi],
                "shared_contacts": device_contacts,
                "cross_calls": device_calls,
                "cross_sms": device_sms,
            }

        self._save_state()
        logger.info(f"Hive shared data generated: {len(self.members)} members, "
                    f"{len(self.shared_wifi)} WiFi, {len(cross_calls)} calls, "
                    f"{len(cross_sms)} SMS")
        return result

    def get_device_data(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get shared data for a specific device. Call after generate_shared_data()."""
        all_data = self.generate_shared_data()
        return all_data.get(device_id)

    # ─── GENERATORS ──────────────────────────────────────────────────

    def _generate_shared_wifi(self, center_lat: float,
                               center_lon: float) -> List[SharedWiFi]:
        """Generate WiFi networks shared across cluster members."""
        rng = self._rng
        count = self.profile["shared_wifi_count"]
        networks = []

        SSID_TEMPLATES = {
            "family": ["NETGEAR-{hex}", "xfinity-{hex}", "ATT-{hex}", "HOME-{hex}"],
            "office": ["CorpNet-{floor}", "OFFICE-{hex}", "WeWork-{n}"],
            "friends": ["Starbucks WiFi", "Planet Fitness", "xfinity-{hex}"],
        }

        templates = SSID_TEMPLATES.get(self.cluster_type, SSID_TEMPLATES["family"])

        for i in range(count):
            template = rng.choice(templates)
            ssid = template.format(
                hex=secrets.token_hex(2).upper(),
                floor=rng.randint(1, 15),
                n=rng.randint(100, 999),
            )

            # Generate realistic BSSID (OUI + random)
            oui_choices = ["D8:47:32", "44:D9:E7", "F0:72:EA", "AC:84:C6", "00:1A:2B"]
            oui = rng.choice(oui_choices)
            bssid = f"{oui}:{secrets.token_hex(1).upper()}:{secrets.token_hex(1).upper()}:{secrets.token_hex(1).upper()}"

            # GPS jitter within cluster radius (±50m ≈ ±0.00045°)
            lat = center_lat + rng.uniform(-0.00045, 0.00045)
            lon = center_lon + rng.uniform(-0.00045, 0.00045)

            networks.append(SharedWiFi(
                ssid=ssid,
                bssid=bssid,
                frequency=rng.choice([2437, 5180, 5240, 5745]),
                signal_level=rng.randint(-70, -40),
                center_lat=lat,
                center_lon=lon,
                radius_m=50.0,
            ))

        return networks

    def _generate_shared_contacts(self) -> List[Dict[str, Any]]:
        """Generate contacts that appear on multiple devices (mutual friends)."""
        rng = self._rng
        pct = self.profile["shared_contacts_pct"]
        num_shared = max(3, int(pct * 20 * len(self.members)))

        SHARED_NAMES = [
            "Mike Peters", "Sarah Kim", "David Lee", "Jessica Brown",
            "Chris Taylor", "Amanda White", "Ryan Garcia", "Emily Davis",
            "Jason Wilson", "Laura Martinez", "Brian Moore", "Rachel Clark",
            "Kevin Hall", "Nicole Young", "Patrick King", "Samantha Wright",
        ]

        contacts = []
        for i in range(min(num_shared, len(SHARED_NAMES))):
            name = SHARED_NAMES[i]
            phone = f"+1{rng.randint(200, 999)}{rng.randint(1000000, 9999999)}"

            # Shared with 2+ random members
            shared_count = min(len(self.members), rng.randint(2, len(self.members)))
            shared_with = [m.device_id for m in rng.sample(self.members, shared_count)]

            contacts.append({
                "name": name,
                "phone": phone,
                "shared_with": shared_with,
            })

        return contacts

    def _generate_cross_calls(self, age_days: int) -> List[CrossDeviceLog]:
        """Generate call logs between cluster members."""
        rng = self._rng
        calls_per_day = self.profile["cross_call_daily"]
        hour_lo, hour_hi = self.profile["call_hour_range"]
        now = datetime.now()

        calls = []
        total_calls = int(calls_per_day * age_days * len(self.members) * 0.5)

        for _ in range(total_calls):
            # Pick random pair
            if len(self.members) < 2:
                break
            pair = rng.sample(self.members, 2)
            caller, callee = pair[0], pair[1]

            # Random timestamp within age_days
            day_offset = rng.randint(0, age_days)
            dt = now - timedelta(days=day_offset)
            hour = rng.randint(hour_lo, hour_hi)
            dt = dt.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))

            duration = rng.choices(
                [0, rng.randint(5, 30), rng.randint(30, 300), rng.randint(300, 1800)],
                weights=[0.15, 0.35, 0.35, 0.15],
                k=1
            )[0]

            calls.append(CrossDeviceLog(
                from_device=caller.device_id,
                to_device=callee.device_id,
                from_phone=caller.persona_phone,
                to_phone=callee.persona_phone,
                from_name=caller.persona_name,
                to_name=callee.persona_name,
                log_type="call",
                timestamp_ms=int(dt.timestamp() * 1000),
                duration_sec=duration,
            ))

        return calls

    def _generate_cross_sms(self, age_days: int) -> List[CrossDeviceLog]:
        """Generate SMS between cluster members with realistic content."""
        rng = self._rng
        sms_per_day = self.profile["cross_sms_daily"]
        now = datetime.now()

        SMS_TEMPLATES = {
            "family": [
                "On my way home", "What's for dinner?", "Can you pick up milk?",
                "Running late, be there in 20", "Love you!", "Call me when you're free",
                "Don't forget the appointment tomorrow", "Kids are at practice",
                "Heading out now", "Almost there", "Just left work",
                "Want me to grab anything?", "How was your day?",
            ],
            "office": [
                "Running 5 min late to the meeting", "Can you review the doc?",
                "Sounds good, thanks", "I'll send it over", "In a meeting, call you back",
                "Sure, let's sync at 3", "Got it, thanks!", "Free for a quick call?",
                "Heading to lunch, want to join?", "The client approved it",
            ],
            "friends": [
                "You free tonight?", "Check this out lol", "Haha that's hilarious",
                "Let's grab drinks later", "Did you see the game?",
                "Down for pizza?", "Movie at 8?", "I'm in!",
                "Just saw this and thought of you", "We still on for Saturday?",
            ],
        }

        templates = SMS_TEMPLATES.get(self.cluster_type, SMS_TEMPLATES["friends"])
        messages = []
        total_sms = int(sms_per_day * age_days * len(self.members) * 0.5)

        for _ in range(total_sms):
            if len(self.members) < 2:
                break
            pair = rng.sample(self.members, 2)
            sender, receiver = pair[0], pair[1]

            day_offset = rng.randint(0, age_days)
            dt = now - timedelta(days=day_offset)
            hour = rng.randint(7, 23)
            dt = dt.replace(hour=hour, minute=rng.randint(0, 59))

            messages.append(CrossDeviceLog(
                from_device=sender.device_id,
                to_device=receiver.device_id,
                from_phone=sender.persona_phone,
                to_phone=receiver.persona_phone,
                from_name=sender.persona_name,
                to_name=receiver.persona_name,
                log_type="sms",
                timestamp_ms=int(dt.timestamp() * 1000),
                sms_body=rng.choice(templates),
            ))

        return messages

    # ─── PERSISTENCE ─────────────────────────────────────────────────

    def _save_state(self):
        """Save cluster state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "cluster_name": self.cluster_name,
            "cluster_type": self.cluster_type,
            "members": [asdict(m) for m in self.members],
            "shared_wifi": [asdict(w) for w in self.shared_wifi],
            "updated_at": time.time(),
        }
        self._state_file.write_text(json.dumps(state, indent=2, default=str))

    def _load_state(self):
        """Load cluster state from disk."""
        if not self._state_file.exists():
            return

        try:
            state = json.loads(self._state_file.read_text())
            self.members = [
                HiveMember(**m) for m in state.get("members", [])
            ]
            self.shared_wifi = [
                SharedWiFi(**w) for w in state.get("shared_wifi", [])
            ]
            logger.info(f"Loaded Hive cluster '{self.cluster_name}': "
                       f"{len(self.members)} members")
        except Exception as e:
            logger.warning(f"Failed to load Hive state: {e}")

    def get_cluster_info(self) -> Dict[str, Any]:
        """Get cluster summary."""
        return {
            "cluster_name": self.cluster_name,
            "cluster_type": self.cluster_type,
            "member_count": len(self.members),
            "members": [
                {
                    "device_id": m.device_id,
                    "persona_name": m.persona_name,
                    "role": m.role,
                    "relationship": m.relationship,
                }
                for m in self.members
            ],
            "shared_wifi_count": len(self.shared_wifi),
            "total_cross_logs": len(self.cross_logs),
        }
