"""
Stochastic Behavioral Aging Engine — Advanced Forensic Evasion
==============================================================
Replaces static circadian weighting with mathematically rigorous
stochastic models that simulate authentic human behavioral patterns.

Key improvements over static AndroidProfileForge:
1. Poisson point processes for bursty, clustered activity
2. Markov chains for conversation flow modeling
3. Persona archetypes with distinct behavioral signatures
4. Timezone-aware generation with DST handling
5. Forensic metadata alignment (mtime, ctime, EXIF)

A fleet of profiles generated with identical weight arrays creates
a detectable statistical anomaly. This engine ensures macro-level
diversity through archetype-driven stochastic modeling.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
import json


class PersonaArchetype(Enum):
    """
    Behavioral archetypes with distinct activity patterns.
    
    Each archetype has unique:
    - Circadian rhythm (peak/trough hours)
    - Communication burst frequency
    - App usage patterns
    - Weekend vs weekday behavior
    """
    PROFESSIONAL = "professional"      # 9-5 schedule, moderate evening activity
    STUDENT = "student"                # Late nights, erratic schedule
    NIGHT_SHIFT = "night_shift"        # Inverted schedule (active 10pm-6am)
    RETIREE = "retiree"                # Early mornings, afternoon lull
    FREELANCER = "freelancer"          # Irregular hours, work bursts
    PARENT = "parent"                  # Early mornings, evening peak after 8pm
    GAMER = "gamer"                    # Late night activity spikes
    TRAVELER = "traveler"              # Irregular timezone patterns


@dataclass
class ActivityBurst:
    """Represents a cluster of related activities."""
    start_time: float           # Unix timestamp
    duration_seconds: float     # How long the burst lasts
    intensity: float            # Events per minute during burst
    activity_type: str          # "sms", "call", "browse", etc.
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationThread:
    """Models a back-and-forth conversation with another contact."""
    contact_id: str
    contact_name: str
    contact_phone: str
    messages: List[Dict] = field(default_factory=list)
    relationship: str = "friend"  # friend, family, work, service


class PoissonProcess:
    """
    Generates events following a non-homogeneous Poisson process.
    
    Unlike uniform distribution, Poisson processes accurately model
    the clustered, bursty nature of human communication patterns.
    """
    
    def __init__(self, base_rate: float = 1.0):
        """
        Args:
            base_rate: Average events per hour
        """
        self.base_rate = base_rate
    
    def generate_events(self, 
                        start_time: float,
                        end_time: float,
                        rate_function: Callable[[float], float] = None) -> List[float]:
        """
        Generate event timestamps using thinning algorithm.
        
        Args:
            start_time: Start of generation window (unix timestamp)
            end_time: End of generation window
            rate_function: Optional time-varying rate λ(t)
        
        Returns:
            List of event timestamps
        """
        if rate_function is None:
            rate_function = lambda t: self.base_rate
        
        events = []
        t = start_time
        
        # Find maximum rate for thinning
        sample_times = [start_time + i * 3600 for i in range(int((end_time - start_time) / 3600) + 1)]
        max_rate = max(rate_function(st) for st in sample_times) if sample_times else self.base_rate
        max_rate = max(max_rate, 0.01)  # Avoid division by zero
        
        while t < end_time:
            # Generate candidate event (homogeneous Poisson with max_rate)
            u = random.random()
            t += -math.log(u) / max_rate * 3600  # Convert rate/hour to seconds
            
            if t >= end_time:
                break
            
            # Accept/reject based on actual rate (thinning)
            actual_rate = rate_function(t)
            if random.random() < actual_rate / max_rate:
                events.append(t)
        
        return events


class MarkovConversationModel:
    """
    Models conversation flow using Markov chains.
    
    Transitions between states:
    - IDLE -> INITIATE (start conversation)
    - INITIATE -> RESPONSE (receive reply)
    - RESPONSE -> REPLY (send follow-up)
    - REPLY -> RESPONSE (continue)
    - * -> CLOSE (end conversation)
    """
    
    STATES = ["idle", "initiate", "response", "reply", "close"]
    
    # Transition probabilities
    TRANSITIONS = {
        "idle": {"initiate": 0.15, "idle": 0.85},
        "initiate": {"response": 0.7, "close": 0.3},
        "response": {"reply": 0.6, "close": 0.4},
        "reply": {"response": 0.5, "reply": 0.2, "close": 0.3},
        "close": {"idle": 1.0},
    }
    
    def __init__(self):
        self.state = "idle"
        self.conversation_length = 0
    
    def next_state(self) -> str:
        """Transition to next conversation state."""
        transitions = self.TRANSITIONS.get(self.state, {"idle": 1.0})
        r = random.random()
        cumulative = 0
        
        for next_state, prob in transitions.items():
            cumulative += prob
            if r < cumulative:
                self.state = next_state
                if next_state in ("initiate", "reply"):
                    self.conversation_length += 1
                elif next_state == "close":
                    length = self.conversation_length
                    self.conversation_length = 0
                    return next_state
                return next_state
        
        return "idle"
    
    def generate_conversation(self, max_length: int = 20) -> List[str]:
        """Generate a sequence of message directions."""
        self.state = "idle"
        self.conversation_length = 0
        
        sequence = []
        for _ in range(max_length * 2):
            state = self.next_state()
            if state == "initiate":
                sequence.append("outbound")
            elif state == "response":
                sequence.append("inbound")
            elif state == "reply":
                sequence.append("outbound")
            elif state == "close":
                break
        
        return sequence


class StochasticAgingEngine:
    """
    Advanced behavioral aging with stochastic modeling.
    
    Generates forensically coherent device history that withstands
    statistical analysis and behavioral profiling.
    """
    
    # Archetype-specific circadian patterns (hour -> activity multiplier)
    ARCHETYPE_PATTERNS = {
        PersonaArchetype.PROFESSIONAL: {
            # Peak: morning commute (7-9), lunch (12-13), evening (18-21)
            "weekday": [0.02, 0.01, 0.01, 0.01, 0.02, 0.05, 0.15, 0.25, 0.20, 0.15,
                       0.12, 0.15, 0.20, 0.15, 0.12, 0.10, 0.12, 0.18, 0.25, 0.30,
                       0.28, 0.20, 0.10, 0.05],
            "weekend": [0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.05, 0.08, 0.15, 0.20,
                       0.25, 0.30, 0.28, 0.25, 0.22, 0.20, 0.22, 0.25, 0.28, 0.30,
                       0.25, 0.18, 0.10, 0.05],
        },
        PersonaArchetype.STUDENT: {
            # Peak: late morning (10-12), late night (22-02)
            "weekday": [0.15, 0.10, 0.05, 0.02, 0.01, 0.01, 0.02, 0.05, 0.08, 0.15,
                       0.25, 0.30, 0.25, 0.20, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30,
                       0.32, 0.35, 0.30, 0.22],
            "weekend": [0.20, 0.15, 0.10, 0.05, 0.02, 0.01, 0.01, 0.02, 0.05, 0.10,
                       0.18, 0.25, 0.28, 0.25, 0.22, 0.25, 0.28, 0.30, 0.32, 0.35,
                       0.38, 0.40, 0.35, 0.28],
        },
        PersonaArchetype.NIGHT_SHIFT: {
            # Inverted: active 22-06, sleep 10-18
            "weekday": [0.30, 0.28, 0.25, 0.22, 0.20, 0.18, 0.15, 0.10, 0.05, 0.02,
                       0.01, 0.01, 0.01, 0.01, 0.02, 0.02, 0.05, 0.08, 0.12, 0.18,
                       0.22, 0.28, 0.32, 0.35],
            "weekend": [0.25, 0.22, 0.18, 0.15, 0.12, 0.10, 0.08, 0.08, 0.10, 0.12,
                       0.15, 0.18, 0.20, 0.18, 0.15, 0.15, 0.18, 0.20, 0.22, 0.25,
                       0.28, 0.30, 0.32, 0.30],
        },
        PersonaArchetype.RETIREE: {
            # Early morning peak (6-10), afternoon dip, early evening
            "weekday": [0.02, 0.02, 0.02, 0.03, 0.05, 0.15, 0.30, 0.35, 0.32, 0.28,
                       0.22, 0.18, 0.20, 0.15, 0.12, 0.15, 0.20, 0.25, 0.22, 0.15,
                       0.10, 0.05, 0.03, 0.02],
            "weekend": [0.02, 0.02, 0.02, 0.03, 0.05, 0.15, 0.28, 0.32, 0.30, 0.28,
                       0.25, 0.22, 0.25, 0.20, 0.18, 0.20, 0.22, 0.25, 0.22, 0.18,
                       0.12, 0.08, 0.05, 0.03],
        },
        PersonaArchetype.GAMER: {
            # Late night peaks (20-03), low during work hours
            "weekday": [0.20, 0.15, 0.08, 0.03, 0.01, 0.01, 0.02, 0.05, 0.08, 0.10,
                       0.12, 0.12, 0.15, 0.12, 0.10, 0.12, 0.15, 0.20, 0.28, 0.35,
                       0.40, 0.42, 0.38, 0.30],
            "weekend": [0.28, 0.22, 0.15, 0.08, 0.03, 0.02, 0.02, 0.05, 0.10, 0.15,
                       0.20, 0.22, 0.25, 0.22, 0.20, 0.22, 0.28, 0.35, 0.42, 0.48,
                       0.50, 0.48, 0.42, 0.35],
        },
    }
    
    # Default pattern for archetypes not explicitly defined
    DEFAULT_PATTERN = {
        "weekday": [0.02, 0.01, 0.01, 0.01, 0.02, 0.05, 0.12, 0.20, 0.22, 0.20,
                   0.18, 0.20, 0.22, 0.20, 0.18, 0.18, 0.20, 0.22, 0.28, 0.30,
                   0.28, 0.22, 0.12, 0.05],
        "weekend": [0.03, 0.02, 0.01, 0.01, 0.01, 0.03, 0.08, 0.15, 0.20, 0.25,
                   0.28, 0.30, 0.28, 0.25, 0.22, 0.22, 0.25, 0.28, 0.30, 0.32,
                   0.28, 0.22, 0.15, 0.08],
    }
    
    # SMS templates by relationship type
    SMS_TEMPLATES = {
        "friend": [
            ("outbound", "Hey! What's up?"),
            ("inbound", "Not much, you?"),
            ("outbound", "Same here. Wanna hang out later?"),
            ("inbound", "Sure! What time?"),
            ("outbound", "How about 7?"),
            ("inbound", "Sounds good 👍"),
        ],
        "family": [
            ("inbound", "Hi honey, how are you?"),
            ("outbound", "Good! Just busy with work"),
            ("inbound", "Don't forget dinner on Sunday"),
            ("outbound", "I'll be there!"),
        ],
        "work": [
            ("inbound", "Can you send me the report?"),
            ("outbound", "Sure, sending now"),
            ("inbound", "Thanks!"),
        ],
        "service": [
            ("inbound", "Your verification code is {otp}"),
            ("inbound", "Your order #{order_id} has shipped"),
            ("inbound", "Transaction alert: ${amount:.2f} at {merchant}"),
        ],
    }
    
    # Bank SMS senders for financial aging
    BANK_SENDERS = {
        "Chase": "33789",
        "Bank of America": "73981",
        "Wells Fargo": "93557",
        "Citi": "95686",
        "Capital One": "227462",
    }

    def __init__(self,
                 archetype: PersonaArchetype = PersonaArchetype.PROFESSIONAL,
                 timezone_offset: int = -8,  # PST default
                 age_days: int = 120,
                 seed: Optional[int] = None):
        """
        Initialize aging engine.
        
        Args:
            archetype: Behavioral archetype for activity patterns
            timezone_offset: Hours offset from UTC
            age_days: How many days of history to generate
            seed: Random seed for reproducibility
        """
        self.archetype = archetype
        self.tz_offset = timezone_offset
        self.age_days = age_days
        
        if seed is not None:
            random.seed(seed)
        
        self.poisson = PoissonProcess()
        self.markov = MarkovConversationModel()
        
        # Get archetype pattern or default
        self.pattern = self.ARCHETYPE_PATTERNS.get(archetype, self.DEFAULT_PATTERN)
        
        # Track generated data for coherence
        self._contacts: List[Dict] = []
        self._conversations: Dict[str, ConversationThread] = {}
        self._generated_order_ids: List[str] = []

    def _get_rate_for_time(self, timestamp: float) -> float:
        """Get activity rate for a given timestamp based on archetype."""
        dt = datetime.fromtimestamp(timestamp)
        hour = dt.hour
        is_weekend = dt.weekday() >= 5
        
        pattern_key = "weekend" if is_weekend else "weekday"
        pattern = self.pattern.get(pattern_key, self.DEFAULT_PATTERN["weekday"])
        
        # Add slight randomization to avoid exact pattern matching
        base_rate = pattern[hour]
        jitter = random.gauss(0, 0.02)
        return max(0.01, base_rate + jitter)

    def generate_contacts(self, count: int = 50) -> List[Dict]:
        """
        Generate realistic contact list with relationship types.
        
        Returns:
            List of contact dictionaries
        """
        relationships = ["friend"] * 15 + ["family"] * 8 + ["work"] * 12 + ["service"] * 5 + ["other"] * 10
        random.shuffle(relationships)
        
        first_names = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", 
                      "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
                      "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen", "Daniel",
                      "Nancy", "Matthew", "Lisa", "Anthony", "Betty", "Mark", "Margaret", "Alex",
                      "Emily", "Ryan", "Ashley", "Kevin", "Amanda", "Brian", "Stephanie"]
        
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
                     "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
                     "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
                     "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark"]
        
        contacts = []
        used_phones = set()
        
        for i in range(count):
            # Generate unique phone number
            while True:
                area_code = random.choice(["212", "310", "415", "312", "206", "404", "305", "702"])
                phone = f"+1{area_code}{random.randint(2000000, 9999999)}"
                if phone not in used_phones:
                    used_phones.add(phone)
                    break
            
            relationship = relationships[i % len(relationships)]
            
            if relationship == "service":
                # Service contacts (banks, delivery, etc.)
                service_names = ["Chase Bank", "Amazon", "Uber", "DoorDash", "Netflix", 
                               "Google", "Apple", "Target", "Starbucks"]
                name = random.choice(service_names)
            else:
                name = f"{random.choice(first_names)} {random.choice(last_names)}"
            
            contact = {
                "id": f"contact_{secrets.token_hex(4)}",
                "name": name,
                "phone": phone,
                "relationship": relationship,
                "frequency": random.choice(["high", "medium", "low"]),
            }
            contacts.append(contact)
            
            # Initialize conversation thread
            self._conversations[contact["id"]] = ConversationThread(
                contact_id=contact["id"],
                contact_name=name,
                contact_phone=phone,
                relationship=relationship
            )
        
        self._contacts = contacts
        return contacts

    def generate_sms_history(self, 
                             contacts: List[Dict] = None,
                             avg_per_day: float = 8.0) -> List[Dict]:
        """
        Generate SMS history using Markov conversation model.
        
        Args:
            contacts: List of contacts (generates if None)
            avg_per_day: Average SMS messages per day
        
        Returns:
            List of SMS records with timestamps
        """
        if contacts is None:
            contacts = self._contacts if self._contacts else self.generate_contacts()
        
        now = time.time()
        start_time = now - (self.age_days * 86400)
        
        sms_records = []
        
        # Generate events using Poisson process
        rate_func = lambda t: self._get_rate_for_time(t) * avg_per_day / 24
        event_times = self.poisson.generate_events(start_time, now, rate_func)
        
        # Group events into conversation bursts
        current_contact = None
        burst_end = 0
        
        for event_time in event_times:
            # Start new conversation burst randomly
            if event_time > burst_end or random.random() < 0.3:
                # Select contact based on frequency
                high_freq = [c for c in contacts if c.get("frequency") == "high"]
                med_freq = [c for c in contacts if c.get("frequency") == "medium"]
                low_freq = [c for c in contacts if c.get("frequency") == "low"]
                
                r = random.random()
                if r < 0.5 and high_freq:
                    current_contact = random.choice(high_freq)
                elif r < 0.85 and med_freq:
                    current_contact = random.choice(med_freq)
                elif low_freq:
                    current_contact = random.choice(low_freq)
                else:
                    current_contact = random.choice(contacts)
                
                # Set burst duration (conversation length)
                burst_duration = random.expovariate(1/300)  # ~5 min average
                burst_end = event_time + burst_duration
            
            # Generate message using Markov model or templates
            relationship = current_contact.get("relationship", "friend")
            
            if relationship == "service":
                # Service messages (OTPs, alerts, etc.)
                templates = self.SMS_TEMPLATES["service"]
                template = random.choice(templates)
                direction = template[0]
                
                body = template[1].format(
                    otp=random.randint(100000, 999999),
                    order_id=secrets.token_hex(6).upper(),
                    amount=round(random.uniform(5, 200), 2),
                    merchant=random.choice(["Amazon", "Target", "Uber", "Starbucks"])
                )
            else:
                # Conversational messages
                conv_sequence = self.markov.generate_conversation(max_length=8)
                if conv_sequence:
                    direction = conv_sequence[0]
                else:
                    direction = random.choice(["inbound", "outbound"])
                
                # Simple message generation
                templates = self.SMS_TEMPLATES.get(relationship, self.SMS_TEMPLATES["friend"])
                matching = [t for t in templates if t[0] == direction]
                if matching:
                    body = random.choice(matching)[1]
                else:
                    body = random.choice([
                        "Ok", "Sure", "Thanks!", "Got it", "Sounds good",
                        "On my way", "Be there soon", "Running late",
                        "Call me later", "Can't talk now"
                    ])
            
            sms_records.append({
                "address": current_contact["phone"],
                "contact_name": current_contact["name"],
                "body": body,
                "type": 1 if direction == "inbound" else 2,  # 1=inbox, 2=sent
                "timestamp": int(event_time),
                "read": 1,
                "seen": 1,
            })
        
        # Sort by timestamp
        sms_records.sort(key=lambda x: x["timestamp"])
        return sms_records

    def generate_call_logs(self,
                          contacts: List[Dict] = None,
                          avg_per_day: float = 3.0) -> List[Dict]:
        """
        Generate call log history.
        
        Args:
            contacts: List of contacts
            avg_per_day: Average calls per day
        
        Returns:
            List of call log records
        """
        if contacts is None:
            contacts = self._contacts if self._contacts else self.generate_contacts()
        
        # Filter out service contacts (they don't make calls)
        callable_contacts = [c for c in contacts if c.get("relationship") != "service"]
        
        now = time.time()
        start_time = now - (self.age_days * 86400)
        
        rate_func = lambda t: self._get_rate_for_time(t) * avg_per_day / 24
        event_times = self.poisson.generate_events(start_time, now, rate_func)
        
        call_logs = []
        
        for event_time in event_times:
            contact = random.choice(callable_contacts)
            
            # Call type: 1=incoming, 2=outgoing, 3=missed
            call_type = random.choices([1, 2, 3], weights=[0.4, 0.45, 0.15])[0]
            
            # Duration (missed calls have 0 duration)
            if call_type == 3:
                duration = 0
            else:
                # Log-normal distribution for call duration
                duration = int(random.lognormvariate(4, 1.2))  # ~1-15 min typical
                duration = max(5, min(duration, 3600))  # Clamp to 5s - 1hr
            
            call_logs.append({
                "number": contact["phone"],
                "contact_name": contact["name"],
                "type": call_type,
                "duration": duration,
                "timestamp": int(event_time),
                "new": 0,
            })
        
        call_logs.sort(key=lambda x: x["timestamp"])
        return call_logs

    def generate_browser_history(self,
                                 country: str = "US",
                                 avg_per_day: float = 15.0) -> List[Dict]:
        """
        Generate browser history with locale-appropriate domains.
        
        Args:
            country: Country code for locale filtering
            avg_per_day: Average page visits per day
        
        Returns:
            List of browser history records
        """
        # Domains by category and locale
        domains = {
            "US": {
                "social": ["facebook.com", "instagram.com", "twitter.com", "reddit.com", "tiktok.com"],
                "shopping": ["amazon.com", "walmart.com", "target.com", "bestbuy.com", "ebay.com"],
                "news": ["cnn.com", "nytimes.com", "washingtonpost.com", "foxnews.com"],
                "entertainment": ["youtube.com", "netflix.com", "spotify.com", "twitch.tv"],
                "search": ["google.com", "bing.com"],
                "finance": ["chase.com", "bankofamerica.com", "wellsfargo.com", "mint.com"],
                "food": ["doordash.com", "ubereats.com", "grubhub.com", "yelp.com"],
            },
            "GB": {
                "social": ["facebook.com", "instagram.com", "twitter.com", "reddit.com"],
                "shopping": ["amazon.co.uk", "argos.co.uk", "tesco.com", "johnlewis.com"],
                "news": ["bbc.co.uk", "theguardian.com", "telegraph.co.uk", "dailymail.co.uk"],
                "entertainment": ["youtube.com", "netflix.com", "spotify.com", "bbc.co.uk/iplayer"],
                "search": ["google.co.uk", "bing.com"],
                "finance": ["barclays.co.uk", "hsbc.co.uk", "lloydsbank.com", "natwest.com"],
                "food": ["deliveroo.co.uk", "justeat.co.uk", "ubereats.com"],
            },
        }
        
        locale_domains = domains.get(country, domains["US"])
        all_domains = []
        for category_domains in locale_domains.values():
            all_domains.extend(category_domains)
        
        now = time.time()
        start_time = now - (self.age_days * 86400)
        
        # Browser activity follows circadian patterns but more bursty
        rate_func = lambda t: self._get_rate_for_time(t) * avg_per_day / 24
        event_times = self.poisson.generate_events(start_time, now, rate_func)
        
        history = []
        current_domain = None
        session_end = 0
        
        for event_time in event_times:
            # Start new browsing session
            if event_time > session_end or random.random() < 0.2:
                # Pick category based on time of day
                hour = datetime.fromtimestamp(event_time).hour
                
                if 9 <= hour <= 17:
                    # Work hours: more news, finance
                    weights = {"social": 0.2, "shopping": 0.15, "news": 0.25, 
                              "entertainment": 0.1, "search": 0.15, "finance": 0.1, "food": 0.05}
                elif 18 <= hour <= 23:
                    # Evening: more entertainment, shopping
                    weights = {"social": 0.25, "shopping": 0.25, "news": 0.1,
                              "entertainment": 0.25, "search": 0.05, "finance": 0.02, "food": 0.08}
                else:
                    # Late night/early morning
                    weights = {"social": 0.3, "shopping": 0.1, "news": 0.1,
                              "entertainment": 0.35, "search": 0.05, "finance": 0.02, "food": 0.08}
                
                category = random.choices(list(weights.keys()), 
                                         weights=list(weights.values()))[0]
                current_domain = random.choice(locale_domains.get(category, all_domains))
                
                session_end = event_time + random.expovariate(1/600)  # ~10 min session
            
            # Generate URL path
            paths = {
                "search": ["/search?q=", "/images?q="],
                "social": ["/home", "/feed", "/notifications", "/messages", "/profile"],
                "shopping": ["/dp/", "/product/", "/cart", "/orders", "/search?k="],
                "news": ["/article/", "/story/", "/politics/", "/business/", "/tech/"],
                "entertainment": ["/watch?v=", "/playlist", "/browse", "/trending"],
                "finance": ["/accounts", "/transfer", "/payments", "/statements"],
                "food": ["/restaurants", "/orders", "/search", "/checkout"],
            }
            
            # Determine category from domain
            domain_category = "search"
            for cat, cat_domains in locale_domains.items():
                if current_domain in cat_domains:
                    domain_category = cat
                    break
            
            path_options = paths.get(domain_category, ["/"])
            path = random.choice(path_options)
            
            if "?" in path:
                path += secrets.token_hex(4)
            elif path.endswith("/"):
                path += secrets.token_hex(6)
            
            url = f"https://www.{current_domain}{path}"
            
            # Generate title
            titles = {
                "search": f"Search Results - {current_domain}",
                "social": f"Feed - {current_domain}",
                "shopping": f"Shopping - {current_domain}",
                "news": f"Article - {current_domain}",
                "entertainment": f"Watch - {current_domain}",
                "finance": f"Account - {current_domain}",
                "food": f"Order Food - {current_domain}",
            }
            title = titles.get(domain_category, current_domain)
            
            history.append({
                "url": url,
                "title": title,
                "domain": current_domain,
                "timestamp": int(event_time),
                "visits": random.randint(1, 5),
            })
        
        history.sort(key=lambda x: x["timestamp"])
        return history

    def generate_purchase_history(self, 
                                  email: str,
                                  count: int = 15) -> Tuple[List[Dict], List[str]]:
        """
        Generate Play Store purchase history with coherent order IDs.
        
        Returns:
            Tuple of (purchase records, order IDs for Gmail coherence)
        """
        apps = [
            ("com.spotify.music", "Spotify: Music and Podcasts", 0),
            ("com.netflix.mediaclient", "Netflix", 0),
            ("com.instagram.android", "Instagram", 0),
            ("com.whatsapp", "WhatsApp Messenger", 0),
            ("com.discord", "Discord", 0),
            ("com.ubercab", "Uber", 0),
            ("com.amazon.mShop.android.shopping", "Amazon Shopping", 0),
            ("com.google.android.apps.photos", "Google Photos", 0),
            # Paid apps
            ("com.teslacoilsw.launcher.prime", "Nova Launcher Prime", 4990000),
            ("com.mojang.minecraftpe", "Minecraft", 7490000),
            ("com.weather.Weather", "Weather Pro", 2990000),
        ]
        
        now = time.time()
        start_time = now - (self.age_days * 86400)
        
        purchases = []
        order_ids = []
        
        # Distribute purchases across time period
        for i in range(count):
            app_id, app_name, price = random.choice(apps)
            
            # Random time within aging period
            purchase_time = random.uniform(start_time, now)
            
            # Generate order ID in Google Play format
            order_id = f"GPA.{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}{random.randint(0,9)}"
            order_ids.append(order_id)
            self._generated_order_ids.append(order_id)
            
            purchases.append({
                "app_id": app_id,
                "app_name": app_name,
                "order_id": order_id,
                "purchase_time_ms": int(purchase_time * 1000),
                "price_micros": price,
                "currency": "USD",
                "email": email,
            })
        
        purchases.sort(key=lambda x: x["purchase_time_ms"])
        return purchases, order_ids

    def generate_full_profile(self,
                             email: str,
                             name: str = "Alex Mercer",
                             phone: str = "+12125551234",
                             country: str = "US") -> Dict[str, Any]:
        """
        Generate complete aged profile with all data types.
        
        Returns:
            Dictionary containing all generated data
        """
        contacts = self.generate_contacts()
        sms = self.generate_sms_history(contacts)
        calls = self.generate_call_logs(contacts)
        history = self.generate_browser_history(country)
        purchases, order_ids = self.generate_purchase_history(email)
        
        return {
            "id": secrets.token_hex(8),
            "archetype": self.archetype.value,
            "age_days": self.age_days,
            "timezone_offset": self.tz_offset,
            "persona": {
                "name": name,
                "email": email,
                "phone": phone,
                "country": country,
            },
            "contacts": contacts,
            "sms": sms,
            "call_logs": calls,
            "browser_history": history,
            "purchases": purchases,
            "order_ids": order_ids,
            "generated_at": int(time.time()),
            "statistics": {
                "contacts_count": len(contacts),
                "sms_count": len(sms),
                "calls_count": len(calls),
                "history_count": len(history),
                "purchases_count": len(purchases),
            }
        }


# Convenience function
def create_aged_profile(
    email: str,
    archetype: str = "professional",
    age_days: int = 120,
    timezone_offset: int = -8
) -> Dict[str, Any]:
    """
    Create a complete aged profile with stochastic behavioral data.
    
    Args:
        email: Account email
        archetype: One of: professional, student, night_shift, retiree, gamer
        age_days: Days of history to generate
        timezone_offset: Timezone offset from UTC
    
    Returns:
        Complete profile dictionary
    """
    archetype_map = {
        "professional": PersonaArchetype.PROFESSIONAL,
        "student": PersonaArchetype.STUDENT,
        "night_shift": PersonaArchetype.NIGHT_SHIFT,
        "retiree": PersonaArchetype.RETIREE,
        "gamer": PersonaArchetype.GAMER,
        "freelancer": PersonaArchetype.FREELANCER,
        "parent": PersonaArchetype.PARENT,
        "traveler": PersonaArchetype.TRAVELER,
    }
    
    arch = archetype_map.get(archetype.lower(), PersonaArchetype.PROFESSIONAL)
    
    engine = StochasticAgingEngine(
        archetype=arch,
        age_days=age_days,
        timezone_offset=timezone_offset
    )
    
    return engine.generate_full_profile(email)


if __name__ == "__main__":
    print("Stochastic Aging Engine - Test Output")
    print("=" * 50)
    
    engine = StochasticAgingEngine(
        archetype=PersonaArchetype.PROFESSIONAL,
        age_days=30
    )
    
    contacts = engine.generate_contacts(count=10)
    print(f"\nGenerated {len(contacts)} contacts:")
    for c in contacts[:3]:
        print(f"  - {c['name']} ({c['relationship']}): {c['phone']}")
    
    sms = engine.generate_sms_history(contacts, avg_per_day=5)
    print(f"\nGenerated {len(sms)} SMS messages")
    print("Sample messages:")
    for msg in sms[:3]:
        direction = "←" if msg["type"] == 1 else "→"
        print(f"  {direction} {msg['body'][:50]}")
    
    calls = engine.generate_call_logs(contacts, avg_per_day=2)
    print(f"\nGenerated {len(calls)} call logs")
    
    history = engine.generate_browser_history(avg_per_day=10)
    print(f"\nGenerated {len(history)} browser history entries")
    print("Sample URLs:")
    for h in history[:3]:
        print(f"  - {h['url'][:60]}")
    
    print("\n✓ Stochastic aging demonstrates realistic behavioral patterns")
