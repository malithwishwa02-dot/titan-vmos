"""
Titan V11.3 — ADB Error Classification
Categorizes ADB failures for targeted recovery strategies.
"""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("titan.adb-error-classifier")


class ADBErrorType(Enum):
    """ADB error categories for recovery routing."""
    TIMEOUT = "timeout"
    OFFLINE = "offline"
    PERMISSION = "permission"
    CONNECTION_REFUSED = "connection_refused"
    DEVICE_NOT_FOUND = "device_not_found"
    UNKNOWN = "unknown"


def classify_adb_error(output: str, returncode: int) -> ADBErrorType:
    """
    Classify ADB error from command output and return code.
    
    Args:
        output: stderr/stdout from ADB command
        returncode: Process return code
        
    Returns:
        ADBErrorType enum value
    """
    output_lower = output.lower()
    
    # Timeout errors
    if "timeout" in output_lower or returncode == 124:
        return ADBErrorType.TIMEOUT
    
    # Device offline
    if "offline" in output_lower or "device offline" in output_lower:
        return ADBErrorType.OFFLINE
    
    # Permission denied
    if "permission denied" in output_lower or returncode == 13:
        return ADBErrorType.PERMISSION
    
    # Connection refused
    if "connection refused" in output_lower or "refused" in output_lower:
        return ADBErrorType.CONNECTION_REFUSED
    
    # Device not found
    if "no devices" in output_lower or "device not found" in output_lower:
        return ADBErrorType.DEVICE_NOT_FOUND
    
    # Unknown error
    return ADBErrorType.UNKNOWN


def should_retry(error_type: ADBErrorType) -> bool:
    """Determine if error is retryable."""
    retryable = {
        ADBErrorType.TIMEOUT,
        ADBErrorType.OFFLINE,
        ADBErrorType.CONNECTION_REFUSED,
    }
    return error_type in retryable


def get_recovery_strategy(error_type: ADBErrorType) -> str:
    """Get recommended recovery action for error type."""
    strategies = {
        ADBErrorType.TIMEOUT: "reconnect_with_backoff",
        ADBErrorType.OFFLINE: "reconnect_immediately",
        ADBErrorType.PERMISSION: "escalate_to_root",
        ADBErrorType.CONNECTION_REFUSED: "reconnect_with_backoff",
        ADBErrorType.DEVICE_NOT_FOUND: "mark_device_lost",
        ADBErrorType.UNKNOWN: "log_and_fail",
    }
    return strategies.get(error_type, "log_and_fail")
