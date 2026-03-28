"""
Titan V11.3 — Injection Idempotency
Ensures profile injection operations are idempotent (safe to retry).
"""

import hashlib
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("titan.injection-idempotency")


class InjectionChecksum:
    """Tracks checksums of injected data to prevent duplicates."""
    
    def __init__(self):
        self.checksums: Dict[str, str] = {}
    
    def compute_checksum(self, data: Any) -> str:
        """Compute SHA256 checksum of data."""
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def record_injection(self, injection_type: str, data: Any):
        """Record injected data checksum."""
        checksum = self.compute_checksum(data)
        key = f"{injection_type}:{checksum}"
        self.checksums[key] = checksum
        logger.debug(f"Recorded injection: {injection_type} -> {checksum[:8]}")
    
    def is_duplicate(self, injection_type: str, data: Any) -> bool:
        """Check if data has already been injected."""
        checksum = self.compute_checksum(data)
        key = f"{injection_type}:{checksum}"
        return key in self.checksums
    
    def get_injected_checksums(self, injection_type: str) -> list:
        """Get all checksums for injection type."""
        prefix = f"{injection_type}:"
        return [v for k, v in self.checksums.items() if k.startswith(prefix)]


class IdempotentInjector:
    """Wrapper for idempotent profile injection."""
    
    def __init__(self, adb_target: str):
        self.adb_target = adb_target
        self.checksum_tracker = InjectionChecksum()
    
    def inject_contacts(self, contacts: list, skip_duplicates: bool = True) -> Dict[str, Any]:
        """
        Inject contacts idempotently.
        
        Args:
            contacts: List of contact dicts
            skip_duplicates: Skip contacts that were already injected
            
        Returns:
            Injection result with counts
        """
        result = {
            "type": "contacts",
            "total": len(contacts),
            "injected": 0,
            "skipped": 0,
            "failed": 0,
        }
        
        for contact in contacts:
            if skip_duplicates and self.checksum_tracker.is_duplicate("contact", contact):
                logger.debug(f"Skipping duplicate contact: {contact.get('name')}")
                result["skipped"] += 1
                continue
            
            try:
                # Inject contact via ADB
                self._inject_contact_adb(contact)
                self.checksum_tracker.record_injection("contact", contact)
                result["injected"] += 1
            except Exception as e:
                logger.error(f"Failed to inject contact: {e}")
                result["failed"] += 1
        
        return result
    
    def inject_sms(self, messages: list, skip_duplicates: bool = True) -> Dict[str, Any]:
        """
        Inject SMS messages idempotently.
        
        Args:
            messages: List of SMS message dicts
            skip_duplicates: Skip messages that were already injected
            
        Returns:
            Injection result with counts
        """
        result = {
            "type": "sms",
            "total": len(messages),
            "injected": 0,
            "skipped": 0,
            "failed": 0,
        }
        
        for message in messages:
            if skip_duplicates and self.checksum_tracker.is_duplicate("sms", message):
                logger.debug(f"Skipping duplicate SMS from {message.get('sender')}")
                result["skipped"] += 1
                continue
            
            try:
                # Inject SMS via ADB
                self._inject_sms_adb(message)
                self.checksum_tracker.record_injection("sms", message)
                result["injected"] += 1
            except Exception as e:
                logger.error(f"Failed to inject SMS: {e}")
                result["failed"] += 1
        
        return result
    
    def inject_call_logs(self, calls: list, skip_duplicates: bool = True) -> Dict[str, Any]:
        """
        Inject call logs idempotently.
        
        Args:
            calls: List of call log dicts
            skip_duplicates: Skip calls that were already injected
            
        Returns:
            Injection result with counts
        """
        result = {
            "type": "call_logs",
            "total": len(calls),
            "injected": 0,
            "skipped": 0,
            "failed": 0,
        }
        
        for call in calls:
            if skip_duplicates and self.checksum_tracker.is_duplicate("call", call):
                logger.debug(f"Skipping duplicate call from {call.get('number')}")
                result["skipped"] += 1
                continue
            
            try:
                # Inject call log via ADB
                self._inject_call_log_adb(call)
                self.checksum_tracker.record_injection("call", call)
                result["injected"] += 1
            except Exception as e:
                logger.error(f"Failed to inject call log: {e}")
                result["failed"] += 1
        
        return result
    
    def _inject_contact_adb(self, contact: Dict[str, Any]):
        """Inject single contact via ADB."""
        # Implementation would use ADB to insert into contacts database
        # This is a placeholder for the actual implementation
        logger.debug(f"Injecting contact: {contact.get('name')}")
    
    def _inject_sms_adb(self, message: Dict[str, Any]):
        """Inject single SMS via ADB."""
        # Implementation would use ADB to insert into SMS database
        logger.debug(f"Injecting SMS from {message.get('sender')}")
    
    def _inject_call_log_adb(self, call: Dict[str, Any]):
        """Inject single call log via ADB."""
        # Implementation would use ADB to insert into call logs database
        logger.debug(f"Injecting call from {call.get('number')}")
    
    def get_injection_stats(self) -> Dict[str, Any]:
        """Get injection statistics."""
        return {
            "contacts": len(self.checksum_tracker.get_injected_checksums("contact")),
            "sms": len(self.checksum_tracker.get_injected_checksums("sms")),
            "calls": len(self.checksum_tracker.get_injected_checksums("call")),
        }
