"""
Titan V11.3 — Payment Pattern Forge
Generates realistic payment patterns for fraud detection evasion.
Addresses GAP-PH3: No payment pattern modeling.

Creates:
  - Realistic spending patterns by time-of-day
  - Merchant category clustering
  - Location-based spending patterns
  - Recurring transactions (subscriptions)
  - Amount distribution modeling

Usage:
    forge = PaymentPatternForge()
    patterns = forge.generate_patterns(
        age_days=90,
        persona_profile={"archetype": "professional", "location": "nyc"}
    )
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger("titan.payment-pattern-forge")


class PaymentPatternForge:
    """Generates realistic payment patterns for fraud detection evasion."""

    def __init__(self):
        self._rng = random.Random()

    def generate_patterns(self,
                         age_days: int = 90,
                         persona_profile: Optional[Dict[str, Any]] = None,
                         ) -> Dict[str, Any]:
        """
        Generate realistic payment patterns.

        Args:
            age_days: Device age in days
            persona_profile: Persona profile with archetype, location, etc.

        Returns:
            Dict with payment patterns
        """
        profile = persona_profile or {}
        archetype = profile.get("archetype", "professional")
        location = profile.get("location", "nyc")

        # Generate circadian spending pattern
        circadian = self._generate_circadian_pattern(archetype)

        # Generate merchant clustering
        merchant_clusters = self._generate_merchant_clusters(location)

        # Generate location-based spending
        location_spending = self._generate_location_spending(location)

        # Generate recurring transactions
        recurring = self._generate_recurring_transactions(archetype)

        # Generate amount distribution
        amount_dist = self._generate_amount_distribution(archetype)

        patterns = {
            "circadian_pattern": circadian,
            "merchant_clusters": merchant_clusters,
            "location_spending": location_spending,
            "recurring_transactions": recurring,
            "amount_distribution": amount_dist,
        }

        logger.info(f"Payment patterns generated for {archetype} in {location}")
        return patterns

    def _generate_circadian_pattern(self, archetype: str) -> Dict[str, float]:
        """Generate time-of-day spending pattern."""
        if archetype == "professional":
            # Professionals: lunch spending, evening shopping
            return {
                "0-6": 0.02,    # Late night: minimal
                "6-9": 0.08,    # Morning: coffee, breakfast
                "9-12": 0.15,   # Mid-morning: online shopping
                "12-14": 0.25,  # Lunch: restaurants, food delivery
                "14-17": 0.12,  # Afternoon: minimal
                "17-20": 0.28,  # Evening: dinner, shopping
                "20-24": 0.10,  # Night: entertainment
            }
        elif archetype == "student":
            # Students: late night, irregular patterns
            return {
                "0-6": 0.05,
                "6-9": 0.05,
                "9-12": 0.12,
                "12-14": 0.18,
                "14-17": 0.15,
                "17-20": 0.22,
                "20-24": 0.23,
            }
        else:  # Default
            return {
                "0-6": 0.03,
                "6-9": 0.10,
                "9-12": 0.18,
                "12-14": 0.20,
                "14-17": 0.15,
                "17-20": 0.24,
                "20-24": 0.10,
            }

    def _generate_merchant_clusters(self, location: str) -> List[Dict[str, Any]]:
        """Generate merchant clustering by category."""
        clusters = [
            {
                "category": "grocery",
                "merchants": ["Whole Foods", "Trader Joe's", "Safeway"],
                "frequency": "weekly",
                "avg_amount": 85.0,
            },
            {
                "category": "restaurants",
                "merchants": ["Chipotle", "Starbucks", "Local Cafe"],
                "frequency": "daily",
                "avg_amount": 15.0,
            },
            {
                "category": "gas",
                "merchants": ["Shell", "Chevron"],
                "frequency": "weekly",
                "avg_amount": 45.0,
            },
            {
                "category": "retail",
                "merchants": ["Amazon", "Target", "Best Buy"],
                "frequency": "monthly",
                "avg_amount": 120.0,
            },
        ]
        return clusters

    def _generate_location_spending(self, location: str) -> Dict[str, Any]:
        """Generate location-based spending patterns."""
        # Location-specific merchant preferences
        location_patterns = {
            "nyc": {
                "subway": 0.15,
                "uber": 0.25,
                "restaurants": 0.35,
                "retail": 0.25,
            },
            "la": {
                "gas": 0.30,
                "restaurants": 0.30,
                "retail": 0.25,
                "entertainment": 0.15,
            },
            "chicago": {
                "transit": 0.10,
                "restaurants": 0.30,
                "retail": 0.35,
                "utilities": 0.25,
            },
        }

        return location_patterns.get(location, location_patterns["nyc"])

    def _generate_recurring_transactions(self, archetype: str) -> List[Dict[str, Any]]:
        """Generate recurring subscription transactions."""
        recurring = [
            {
                "merchant": "Netflix",
                "amount": 15.99,
                "frequency": "monthly",
                "day_of_month": 15,
            },
            {
                "merchant": "Spotify",
                "amount": 9.99,
                "frequency": "monthly",
                "day_of_month": 1,
            },
        ]

        if archetype == "professional":
            recurring.extend([
                {
                    "merchant": "LinkedIn Premium",
                    "amount": 29.99,
                    "frequency": "monthly",
                    "day_of_month": 10,
                },
                {
                    "merchant": "Adobe Creative Cloud",
                    "amount": 52.99,
                    "frequency": "monthly",
                    "day_of_month": 5,
                },
            ])

        return recurring

    def _generate_amount_distribution(self, archetype: str) -> Dict[str, Any]:
        """Generate realistic amount distribution."""
        if archetype == "professional":
            return {
                "small": {"range": [5, 25], "probability": 0.40},
                "medium": {"range": [25, 100], "probability": 0.35},
                "large": {"range": [100, 300], "probability": 0.20},
                "very_large": {"range": [300, 1000], "probability": 0.05},
            }
        elif archetype == "student":
            return {
                "small": {"range": [5, 20], "probability": 0.60},
                "medium": {"range": [20, 50], "probability": 0.30},
                "large": {"range": [50, 150], "probability": 0.08},
                "very_large": {"range": [150, 500], "probability": 0.02},
            }
        else:
            return {
                "small": {"range": [5, 30], "probability": 0.45},
                "medium": {"range": [30, 100], "probability": 0.35},
                "large": {"range": [100, 250], "probability": 0.15},
                "very_large": {"range": [250, 800], "probability": 0.05},
            }
