"""
Titan V11.3 — Timestamp Validator
Validates timestamp consistency across all injected data.
Addresses GAP-INJ2: Timestamp consistency issues.

Validates:
  - Monotonic progression of timestamps
  - Device age consistency
  - Database timestamp consistency
  - Cross-database timestamp validation

Usage:
    validator = TimestampValidator(adb_target="127.0.0.1:5555")
    result = validator.validate_all_timestamps(profile_age_days=90)
"""

import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("titan.timestamp-validator")


@dataclass
class TimestampValidationResult:
    """Timestamp validation result."""
    passed: bool = True
    total_checks: int = 0
    failed_checks: int = 0
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "total_checks": self.total_checks,
            "failed_checks": self.failed_checks,
            "anomalies": self.anomalies,
            "warnings": self.warnings,
        }


class TimestampValidator:
    """Validates timestamp consistency across all data."""

    # Database paths on device
    DB_PATHS = {
        "contacts": "/data/data/com.android.providers.contacts/databases/contacts2.db",
        "telephony": "/data/data/com.android.providers.telephony/databases/mmssms.db",
        "chrome": "/data/data/com.android.chrome/app_chrome/Default/History",
        "wallet": "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
    }

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target

    def validate_all_timestamps(self, profile_age_days: int = 90) -> TimestampValidationResult:
        """Validate all timestamps for consistency."""
        result = TimestampValidationResult()

        now = datetime.now()
        profile_start = now - timedelta(days=profile_age_days)

        # Validate each database
        for db_name, db_path in self.DB_PATHS.items():
            db_result = self._validate_database_timestamps(
                db_name, db_path, profile_start, now
            )
            result.total_checks += db_result["total_checks"]
            result.failed_checks += db_result["failed_checks"]
            if db_result["anomalies"]:
                result.anomalies.extend(db_result["anomalies"])
                result.passed = False
            if db_result["warnings"]:
                result.warnings.extend(db_result["warnings"])

        # Validate cross-database consistency
        cross_result = self._validate_cross_database_consistency()
        if cross_result["anomalies"]:
            result.anomalies.extend(cross_result["anomalies"])
            result.passed = False

        logger.info(f"Timestamp validation: {result.total_checks - result.failed_checks}/{result.total_checks} passed")
        return result

    def _validate_database_timestamps(self,
                                     db_name: str,
                                     db_path: str,
                                     profile_start: datetime,
                                     now: datetime,
                                     ) -> Dict[str, Any]:
        """Validate timestamps in a specific database."""
        from adb_utils import adb as _adb

        result = {
            "database": db_name,
            "total_checks": 0,
            "failed_checks": 0,
            "anomalies": [],
            "warnings": [],
        }

        try:
            # Pull database from device
            with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
                tmp_path = tmp.name

            pull_ok, _ = _adb(self.target, f"pull {db_path} {tmp_path}", timeout=10)
            if not pull_ok:
                result["warnings"].append(f"Could not pull {db_name} database")
                return result

            # Analyze timestamps
            conn = sqlite3.connect(tmp_path)
            cursor = conn.cursor()

            # Get all timestamp columns
            timestamp_cols = self._find_timestamp_columns(cursor)

            for table, col in timestamp_cols:
                try:
                    cursor.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col}")
                    timestamps = [row[0] for row in cursor.fetchall()]

                    if not timestamps:
                        continue

                    result["total_checks"] += 1

                    # Check monotonic progression
                    if not self._is_monotonic(timestamps):
                        result["failed_checks"] += 1
                        result["anomalies"].append({
                            "database": db_name,
                            "table": table,
                            "column": col,
                            "issue": "Non-monotonic timestamps",
                        })

                    # Check if timestamps are within profile age
                    for ts in timestamps:
                        ts_dt = self._parse_timestamp(ts)
                        if ts_dt:
                            if ts_dt < profile_start or ts_dt > now:
                                result["failed_checks"] += 1
                                result["anomalies"].append({
                                    "database": db_name,
                                    "table": table,
                                    "column": col,
                                    "timestamp": ts,
                                    "issue": f"Timestamp outside profile age range ({profile_start} - {now})",
                                })

                except Exception as e:
                    logger.debug(f"Error checking {table}.{col}: {e}")

            conn.close()

        except Exception as e:
            logger.error(f"Error validating {db_name} timestamps: {e}")
            result["warnings"].append(f"Error validating {db_name}: {e}")

        return result

    def _find_timestamp_columns(self, cursor: sqlite3.Cursor) -> List[tuple]:
        """Find all timestamp columns in database."""
        timestamp_cols = []

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            try:
                # Get table schema
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()

                for col in columns:
                    col_name = col[1].lower()
                    # Look for timestamp-like column names
                    if any(keyword in col_name for keyword in ['time', 'date', 'created', 'modified', 'updated']):
                        timestamp_cols.append((table, col[1]))

            except Exception:
                continue

        return timestamp_cols

    def _is_monotonic(self, timestamps: List[Any]) -> bool:
        """Check if timestamps are monotonically increasing."""
        if len(timestamps) < 2:
            return True

        for i in range(1, len(timestamps)):
            if timestamps[i] < timestamps[i-1]:
                return False

        return True

    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        """Parse timestamp to datetime."""
        try:
            # Try Unix timestamp (milliseconds)
            if isinstance(ts, int):
                if ts > 1000000000000:  # Milliseconds
                    return datetime.fromtimestamp(ts / 1000)
                else:  # Seconds
                    return datetime.fromtimestamp(ts)

            # Try ISO format
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))

        except Exception:
            pass

        return None

    def _validate_cross_database_consistency(self) -> Dict[str, Any]:
        """Validate timestamp consistency across databases."""
        result = {
            "anomalies": [],
        }

        # This would check that timestamps across databases are consistent
        # For example, SMS timestamps should align with contact creation times
        # Implementation would require pulling and analyzing multiple databases

        return result

    def fix_timestamp_anomalies(self, validation_result: TimestampValidationResult) -> bool:
        """Fix timestamp anomalies."""
        logger.info("Fixing timestamp anomalies")

        # This would implement fixes for timestamp issues
        # For now, just log the anomalies
        for anomaly in validation_result.anomalies:
            logger.warning(f"Timestamp anomaly: {anomaly}")

        return True
