"""
Titan V11.3 — Payment History Forge
Generates realistic transaction history for device aging.
Addresses GAP-PH1: No transaction history injection.

Creates:
  - Transaction history (50-200 based on age_days)
  - Merchant category diversity
  - Refunds/chargebacks (2-5% of transactions)
  - Realistic spending patterns
  - Payment receipt emails

Usage:
    forge = PaymentHistoryForge()
    history = forge.forge(
        age_days=90,
        card_network="visa",
        card_last4="4532",
        persona_email="alex.mercer@gmail.com",
    )
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger("titan.payment-history-forge")


# Merchant categories with realistic spending patterns
MERCHANT_CATEGORIES = {
    "grocery": {
        "merchants": ["Whole Foods", "Safeway", "Kroger", "Trader Joe's", "Costco", "Walmart", "Target"],
        "amount_range": (20, 150),
        "frequency_per_month": 4,
        "time_of_day": "morning",  # 7am-12pm
    },
    "gas": {
        "merchants": ["Shell", "Chevron", "BP", "Exxon", "Speedway", "Circle K"],
        "amount_range": (30, 80),
        "frequency_per_month": 2,
        "time_of_day": "evening",  # 5pm-8pm
    },
    "restaurants": {
        "merchants": ["Chipotle", "Starbucks", "McDonald's", "Subway", "Panera", "Olive Garden", "Chili's"],
        "amount_range": (8, 50),
        "frequency_per_month": 6,
        "time_of_day": "lunch_dinner",  # 12pm-2pm, 6pm-8pm
    },
    "retail": {
        "merchants": ["Amazon", "Best Buy", "Gap", "H&M", "Zara", "Forever 21", "ASOS"],
        "amount_range": (25, 200),
        "frequency_per_month": 2,
        "time_of_day": "afternoon",  # 2pm-6pm
    },
    "utilities": {
        "merchants": ["Electric Company", "Water Utility", "Gas Company", "Internet Provider"],
        "amount_range": (50, 200),
        "frequency_per_month": 1,
        "time_of_day": "any",
    },
    "entertainment": {
        "merchants": ["Netflix", "Spotify", "Hulu", "Disney+", "AMC Theaters", "Regal Cinemas"],
        "amount_range": (10, 50),
        "frequency_per_month": 3,
        "time_of_day": "evening",  # 6pm-10pm
    },
    "healthcare": {
        "merchants": ["CVS Pharmacy", "Walgreens", "Rite Aid", "Doctor's Office", "Hospital"],
        "amount_range": (15, 300),
        "frequency_per_month": 1,
        "time_of_day": "afternoon",  # 2pm-5pm
    },
    "travel": {
        "merchants": ["Uber", "Lyft", "Airbnb", "Hotels.com", "United Airlines", "Delta"],
        "amount_range": (15, 500),
        "frequency_per_month": 1,
        "time_of_day": "any",
    },
    "subscriptions": {
        "merchants": ["Apple", "Google", "Microsoft", "Adobe", "Slack"],
        "amount_range": (5, 100),
        "frequency_per_month": 1,  # Recurring
        "time_of_day": "any",
    },
}


class PaymentHistoryForge:
    """Generates realistic payment transaction history."""

    def __init__(self):
        self._rng = random.Random()

    def forge(self,
              age_days: int = 90,
              card_network: str = "visa",
              card_last4: str = "4532",
              persona_email: str = "user@gmail.com",
              persona_name: str = "User",
              country: str = "US",
              ) -> Dict[str, Any]:
        """
        Generate realistic payment transaction history.

        Args:
            age_days: Device age in days
            card_network: Card network (visa, mastercard, amex, discover)
            card_last4: Last 4 digits of card
            persona_email: Email for receipts
            persona_name: Name for receipts
            country: Country for locale-specific merchants

        Returns:
            Dict with transaction history, receipts, patterns
        """
        # Seed RNG for deterministic output
        seed_str = f"{persona_email}:{card_last4}:{age_days}"
        seed = int(persona_email.encode('utf-8').hex()[:16], 16)
        self._rng.seed(seed)

        logger.info(f"Forging payment history: {age_days}d for {persona_email}")

        # Calculate transaction count based on age
        # Real user patterns: 50-200 transactions over 90 days
        lo = max(30, min(age_days // 2, 100))
        hi = max(lo + 20, min(age_days, 250))
        num_transactions = self._rng.randint(lo, hi)

        # Generate transactions
        transactions = self._generate_transactions(
            num_transactions, age_days, card_network, card_last4
        )

        # Generate receipts
        receipts = self._generate_receipts(transactions, persona_email, persona_name)

        # Generate spending patterns
        patterns = self._analyze_patterns(transactions)

        # Generate refunds/chargebacks (2-5%)
        refunds = self._generate_refunds(transactions, card_last4)

        history = {
            "card_last4": card_last4,
            "card_network": card_network,
            "age_days": age_days,
            "persona_email": persona_email,
            "persona_name": persona_name,
            "country": country,
            "transactions": transactions,
            "receipts": receipts,
            "patterns": patterns,
            "refunds": refunds,
            "stats": {
                "total_transactions": len(transactions),
                "total_amount": sum(t["amount"] for t in transactions),
                "average_transaction": sum(t["amount"] for t in transactions) / len(transactions) if transactions else 0,
                "refund_count": len(refunds),
                "merchant_categories": len(set(t["category"] for t in transactions)),
            },
        }

        logger.info(f"Payment history forged: {len(transactions)} transactions, "
                   f"${history['stats']['total_amount']:.2f} total")
        return history

    def _generate_transactions(self,
                              num_transactions: int,
                              age_days: int,
                              card_network: str,
                              card_last4: str,
                              ) -> List[Dict[str, Any]]:
        """Generate realistic transactions distributed across age_days."""
        transactions = []
        now = datetime.now()
        profile_start = now - timedelta(days=age_days)

        # GAP-W3: Generate recurring subscription transactions first
        # Real subscriptions hit on a fixed day each month (e.g., always the 15th)
        sub_info = MERCHANT_CATEGORIES.get("subscriptions", {})
        sub_merchants = sub_info.get("merchants", [])
        if sub_merchants and age_days >= 30:
            # Pick 1-3 subscriptions for this persona
            num_subs = self._rng.randint(1, min(3, len(sub_merchants)))
            chosen_subs = self._rng.sample(sub_merchants, num_subs)
            for sub_merchant in chosen_subs:
                # Fixed billing day (1-28 to avoid month-length issues)
                billing_day = self._rng.randint(1, 28)
                sub_amount = round(self._rng.uniform(*sub_info["amount_range"]), 2)
                # Generate one charge per month for the entire age
                months = age_days // 30
                for m in range(months):
                    sub_date = now - timedelta(days=m * 30)
                    try:
                        sub_date = sub_date.replace(day=billing_day,
                                                     hour=self._rng.randint(0, 5),
                                                     minute=self._rng.randint(0, 59))
                    except ValueError:
                        sub_date = sub_date.replace(day=min(billing_day, 28),
                                                     hour=self._rng.randint(0, 5),
                                                     minute=self._rng.randint(0, 59))
                    if sub_date < profile_start:
                        continue
                    txn_idx = len(transactions)
                    transactions.append({
                        "id": f"txn_{txn_idx:06d}",
                        "timestamp": sub_date.isoformat(),
                        "merchant": sub_merchant,
                        "category": "subscriptions",
                        "amount": sub_amount,
                        "currency": "USD",
                        "card_last4": card_last4,
                        "card_network": card_network,
                        "status": "completed",
                        "mcc": self._get_mcc_code("subscriptions"),
                        "recurring": True,
                    })
                    num_transactions -= 1  # Count against total budget

        # Generate remaining transactions with realistic distribution
        # Exclude subscriptions category (already handled above)
        non_sub_categories = [k for k in MERCHANT_CATEGORIES.keys() if k != "subscriptions"]
        non_sub_weights = [1, 1, 2, 1.5, 0.5, 1, 0.5, 0.5]  # Restaurants more common

        for i in range(max(0, num_transactions)):
            # Bias towards more recent transactions
            days_ago = int(self._rng.expovariate(1.0 / (age_days / 3)))
            days_ago = min(days_ago, age_days - 1)

            transaction_time = now - timedelta(days=days_ago)

            # Select category with weighted distribution (no subscriptions)
            category = self._rng.choices(
                non_sub_categories,
                weights=non_sub_weights[:len(non_sub_categories)],
                k=1
            )[0]

            category_info = MERCHANT_CATEGORIES[category]
            merchant = self._rng.choice(category_info["merchants"])
            amount = self._rng.uniform(*category_info["amount_range"])

            # Add circadian weighting for time-of-day
            hour = self._get_circadian_hour(category_info["time_of_day"])

            transaction_time = transaction_time.replace(hour=hour, minute=self._rng.randint(0, 59))

            txn_idx = len(transactions)
            transactions.append({
                "id": f"txn_{txn_idx:06d}",
                "timestamp": transaction_time.isoformat(),
                "merchant": merchant,
                "category": category,
                "amount": round(amount, 2),
                "currency": "USD",
                "card_last4": card_last4,
                "card_network": card_network,
                "status": "completed",
                "mcc": self._get_mcc_code(category),
            })

        # Sort by timestamp
        transactions.sort(key=lambda x: x["timestamp"])
        return transactions

    def _generate_receipts(self,
                          transactions: List[Dict[str, Any]],
                          persona_email: str,
                          persona_name: str,
                          ) -> List[Dict[str, Any]]:
        """Generate email receipts for transactions."""
        receipts = []

        for txn in transactions:
            # Not all transactions generate receipts (cash-only merchants, etc.)
            if self._rng.random() > 0.7:
                continue

            receipt = {
                "id": f"receipt_{txn['id']}",
                "timestamp": txn["timestamp"],
                "from": f"noreply@{txn['merchant'].lower().replace(' ', '')}.com",
                "to": persona_email,
                "subject": f"Receipt for {txn['merchant']} - ${txn['amount']:.2f}",
                "amount": txn["amount"],
                "merchant": txn["merchant"],
                "category": txn["category"],
                "body": self._generate_receipt_body(
                    txn, persona_name
                ),
            }
            receipts.append(receipt)

        return receipts

    def _generate_receipt_body(self,
                              transaction: Dict[str, Any],
                              persona_name: str,
                              ) -> str:
        """Generate realistic receipt email body."""
        return f"""
Thank you for your purchase at {transaction['merchant']}!

Transaction Details:
  Date: {transaction['timestamp']}
  Merchant: {transaction['merchant']}
  Amount: ${transaction['amount']:.2f}
  Card: {transaction['card_network']} ****{transaction['card_last4']}
  Status: {transaction['status']}

Order Number: ORD-{self._rng.randint(100000, 999999)}
Reference: {transaction['id']}

If you have any questions, please contact customer service.

Thank you for your business!
"""

    def _generate_refunds(self,
                         transactions: List[Dict[str, Any]],
                         card_last4: str,
                         ) -> List[Dict[str, Any]]:
        """Generate refunds/chargebacks (2-5% of transactions)."""
        refunds = []
        refund_rate = self._rng.uniform(0.02, 0.05)
        num_refunds = max(1, int(len(transactions) * refund_rate))

        # Select random transactions for refunds
        refund_txns = self._rng.sample(transactions, min(num_refunds, len(transactions)))

        for i, txn in enumerate(refund_txns):
            refund_time = datetime.fromisoformat(txn["timestamp"]) + timedelta(days=self._rng.randint(1, 30))

            refund = {
                "id": f"refund_{i:04d}",
                "original_transaction_id": txn["id"],
                "timestamp": refund_time.isoformat(),
                "merchant": txn["merchant"],
                "amount": txn["amount"],
                "reason": self._rng.choice([
                    "Item returned",
                    "Duplicate charge",
                    "Item not received",
                    "Quality issue",
                    "Changed mind",
                ]),
                "status": "completed",
                "card_last4": card_last4,
            }
            refunds.append(refund)

        return refunds

    def _analyze_patterns(self,
                         transactions: List[Dict[str, Any]],
                         ) -> Dict[str, Any]:
        """Analyze spending patterns from transactions."""
        if not transactions:
            return {}

        # Category distribution
        category_counts = {}
        category_amounts = {}
        for txn in transactions:
            cat = txn["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
            category_amounts[cat] = category_amounts.get(cat, 0) + txn["amount"]

        # Time-of-day distribution
        hour_counts = {}
        for txn in transactions:
            hour = int(datetime.fromisoformat(txn["timestamp"]).hour)
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        # Day-of-week distribution
        dow_counts = {}
        for txn in transactions:
            dow = datetime.fromisoformat(txn["timestamp"]).strftime("%A")
            dow_counts[dow] = dow_counts.get(dow, 0) + 1

        return {
            "category_distribution": category_counts,
            "category_spending": category_amounts,
            "time_of_day_distribution": hour_counts,
            "day_of_week_distribution": dow_counts,
            "average_daily_spending": sum(t["amount"] for t in transactions) / max(1, len(set(
                datetime.fromisoformat(t["timestamp"]).date() for t in transactions
            ))),
        }

    def _get_circadian_hour(self, time_of_day: str) -> int:
        """Get realistic hour based on circadian pattern."""
        if time_of_day == "morning":
            return self._rng.randint(7, 12)
        elif time_of_day == "afternoon":
            return self._rng.randint(13, 17)
        elif time_of_day == "evening":
            return self._rng.randint(17, 21)
        elif time_of_day == "lunch_dinner":
            if self._rng.random() < 0.5:
                return self._rng.randint(12, 14)
            else:
                return self._rng.randint(18, 20)
        else:  # "any"
            return self._rng.randint(0, 23)

    def _get_mcc_code(self, category: str) -> str:
        """Get MCC (Merchant Category Code) for category."""
        mcc_map = {
            "grocery": "5411",
            "gas": "5542",
            "restaurants": "5812",
            "retail": "5411",
            "utilities": "4900",
            "entertainment": "7832",
            "healthcare": "5912",
            "travel": "4511",
            "subscriptions": "5815",
        }
        return mcc_map.get(category, "5411")
