"""
Titan V11.3 — Prometheus Metrics
Exposes system and application metrics for monitoring.
"""

import logging
import time
from typing import Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("titan.metrics")


@dataclass
class MetricsCollector:
    """Collects and exposes Prometheus metrics."""
    
    # Device metrics
    devices_total: int = 0
    devices_ready: int = 0
    devices_booting: int = 0
    devices_patched: int = 0
    devices_error: int = 0
    
    # Request metrics
    requests_total: int = 0
    requests_success: int = 0
    requests_error: int = 0
    request_latency_sum: float = 0.0
    request_latency_count: int = 0
    
    # ADB metrics
    adb_commands_total: int = 0
    adb_commands_success: int = 0
    adb_commands_failed: int = 0
    adb_reconnects: int = 0
    
    # Ollama metrics
    ollama_calls_total: int = 0
    ollama_calls_success: int = 0
    ollama_calls_failed: int = 0
    ollama_fallbacks: int = 0
    
    # Device creation metrics
    device_creations_total: int = 0
    device_creations_success: int = 0
    device_creations_failed: int = 0
    device_creation_time_sum: float = 0.0
    
    # Injection metrics
    injections_total: int = 0
    injections_success: int = 0
    injections_failed: int = 0
    injection_time_sum: float = 0.0
    
    # Circuit breaker metrics
    circuit_breakers_open: int = 0
    circuit_breakers_half_open: int = 0
    
    # Timestamps
    start_time: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    
    def record_request(self, latency: float, success: bool = True):
        """Record HTTP request."""
        self.requests_total += 1
        if success:
            self.requests_success += 1
        else:
            self.requests_error += 1
        self.request_latency_sum += latency
        self.request_latency_count += 1
        self.last_update = time.time()
    
    def record_adb_command(self, success: bool = True):
        """Record ADB command execution."""
        self.adb_commands_total += 1
        if success:
            self.adb_commands_success += 1
        else:
            self.adb_commands_failed += 1
        self.last_update = time.time()
    
    def record_adb_reconnect(self):
        """Record ADB reconnection attempt."""
        self.adb_reconnects += 1
        self.last_update = time.time()
    
    def record_ollama_call(self, success: bool = True, fallback: bool = False):
        """Record Ollama API call."""
        self.ollama_calls_total += 1
        if success:
            self.ollama_calls_success += 1
        else:
            self.ollama_calls_failed += 1
        if fallback:
            self.ollama_fallbacks += 1
        self.last_update = time.time()
    
    def record_device_creation(self, success: bool = True, duration: float = 0.0):
        """Record device creation."""
        self.device_creations_total += 1
        if success:
            self.device_creations_success += 1
        else:
            self.device_creations_failed += 1
        self.device_creation_time_sum += duration
        self.last_update = time.time()
    
    def record_injection(self, success: bool = True, duration: float = 0.0):
        """Record profile injection."""
        self.injections_total += 1
        if success:
            self.injections_success += 1
        else:
            self.injections_failed += 1
        self.injection_time_sum += duration
        self.last_update = time.time()
    
    def update_device_states(self, states: Dict[str, int]):
        """Update device state counts."""
        self.devices_total = sum(states.values())
        self.devices_ready = states.get("ready", 0)
        self.devices_booting = states.get("booting", 0)
        self.devices_patched = states.get("patched", 0)
        self.devices_error = states.get("error", 0)
        self.last_update = time.time()
    
    def update_circuit_breakers(self, open_count: int, half_open_count: int):
        """Update circuit breaker state counts."""
        self.circuit_breakers_open = open_count
        self.circuit_breakers_half_open = half_open_count
        self.last_update = time.time()
    
    def get_uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self.start_time
    
    def get_request_latency_avg(self) -> float:
        """Get average request latency."""
        if self.request_latency_count == 0:
            return 0.0
        return self.request_latency_sum / self.request_latency_count
    
    def get_device_creation_time_avg(self) -> float:
        """Get average device creation time."""
        if self.device_creations_total == 0:
            return 0.0
        return self.device_creation_time_sum / self.device_creations_total
    
    def get_injection_time_avg(self) -> float:
        """Get average injection time."""
        if self.injections_total == 0:
            return 0.0
        return self.injection_time_sum / self.injections_total
    
    def to_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        
        # Help and type comments
        lines.append("# HELP titan_devices_total Total number of devices")
        lines.append("# TYPE titan_devices_total gauge")
        lines.append(f"titan_devices_total {self.devices_total}")
        
        lines.append("# HELP titan_devices_ready Number of ready devices")
        lines.append("# TYPE titan_devices_ready gauge")
        lines.append(f"titan_devices_ready {self.devices_ready}")
        
        lines.append("# HELP titan_devices_booting Number of booting devices")
        lines.append("# TYPE titan_devices_booting gauge")
        lines.append(f"titan_devices_booting {self.devices_booting}")
        
        lines.append("# HELP titan_devices_patched Number of patched devices")
        lines.append("# TYPE titan_devices_patched gauge")
        lines.append(f"titan_devices_patched {self.devices_patched}")
        
        lines.append("# HELP titan_devices_error Number of error devices")
        lines.append("# TYPE titan_devices_error gauge")
        lines.append(f"titan_devices_error {self.devices_error}")
        
        lines.append("# HELP titan_requests_total Total HTTP requests")
        lines.append("# TYPE titan_requests_total counter")
        lines.append(f"titan_requests_total {self.requests_total}")
        
        lines.append("# HELP titan_requests_success Successful HTTP requests")
        lines.append("# TYPE titan_requests_success counter")
        lines.append(f"titan_requests_success {self.requests_success}")
        
        lines.append("# HELP titan_requests_error Failed HTTP requests")
        lines.append("# TYPE titan_requests_error counter")
        lines.append(f"titan_requests_error {self.requests_error}")
        
        lines.append("# HELP titan_request_latency_avg Average request latency (seconds)")
        lines.append("# TYPE titan_request_latency_avg gauge")
        lines.append(f"titan_request_latency_avg {self.get_request_latency_avg():.4f}")
        
        lines.append("# HELP titan_adb_commands_total Total ADB commands")
        lines.append("# TYPE titan_adb_commands_total counter")
        lines.append(f"titan_adb_commands_total {self.adb_commands_total}")
        
        lines.append("# HELP titan_adb_commands_success Successful ADB commands")
        lines.append("# TYPE titan_adb_commands_success counter")
        lines.append(f"titan_adb_commands_success {self.adb_commands_success}")
        
        lines.append("# HELP titan_adb_commands_failed Failed ADB commands")
        lines.append("# TYPE titan_adb_commands_failed counter")
        lines.append(f"titan_adb_commands_failed {self.adb_commands_failed}")
        
        lines.append("# HELP titan_adb_reconnects ADB reconnection attempts")
        lines.append("# TYPE titan_adb_reconnects counter")
        lines.append(f"titan_adb_reconnects {self.adb_reconnects}")
        
        lines.append("# HELP titan_ollama_calls_total Total Ollama API calls")
        lines.append("# TYPE titan_ollama_calls_total counter")
        lines.append(f"titan_ollama_calls_total {self.ollama_calls_total}")
        
        lines.append("# HELP titan_ollama_calls_success Successful Ollama calls")
        lines.append("# TYPE titan_ollama_calls_success counter")
        lines.append(f"titan_ollama_calls_success {self.ollama_calls_success}")
        
        lines.append("# HELP titan_ollama_calls_failed Failed Ollama calls")
        lines.append("# TYPE titan_ollama_calls_failed counter")
        lines.append(f"titan_ollama_calls_failed {self.ollama_calls_failed}")
        
        lines.append("# HELP titan_ollama_fallbacks Ollama fallback to CPU")
        lines.append("# TYPE titan_ollama_fallbacks counter")
        lines.append(f"titan_ollama_fallbacks {self.ollama_fallbacks}")
        
        lines.append("# HELP titan_device_creations_total Total device creations")
        lines.append("# TYPE titan_device_creations_total counter")
        lines.append(f"titan_device_creations_total {self.device_creations_total}")
        
        lines.append("# HELP titan_device_creations_success Successful device creations")
        lines.append("# TYPE titan_device_creations_success counter")
        lines.append(f"titan_device_creations_success {self.device_creations_success}")
        
        lines.append("# HELP titan_device_creations_failed Failed device creations")
        lines.append("# TYPE titan_device_creations_failed counter")
        lines.append(f"titan_device_creations_failed {self.device_creations_failed}")
        
        lines.append("# HELP titan_device_creation_time_avg Average device creation time (seconds)")
        lines.append("# TYPE titan_device_creation_time_avg gauge")
        lines.append(f"titan_device_creation_time_avg {self.get_device_creation_time_avg():.2f}")
        
        lines.append("# HELP titan_injections_total Total profile injections")
        lines.append("# TYPE titan_injections_total counter")
        lines.append(f"titan_injections_total {self.injections_total}")
        
        lines.append("# HELP titan_injections_success Successful injections")
        lines.append("# TYPE titan_injections_success counter")
        lines.append(f"titan_injections_success {self.injections_success}")
        
        lines.append("# HELP titan_injections_failed Failed injections")
        lines.append("# TYPE titan_injections_failed counter")
        lines.append(f"titan_injections_failed {self.injections_failed}")
        
        lines.append("# HELP titan_injection_time_avg Average injection time (seconds)")
        lines.append("# TYPE titan_injection_time_avg gauge")
        lines.append(f"titan_injection_time_avg {self.get_injection_time_avg():.2f}")
        
        lines.append("# HELP titan_circuit_breakers_open Open circuit breakers")
        lines.append("# TYPE titan_circuit_breakers_open gauge")
        lines.append(f"titan_circuit_breakers_open {self.circuit_breakers_open}")
        
        lines.append("# HELP titan_circuit_breakers_half_open Half-open circuit breakers")
        lines.append("# TYPE titan_circuit_breakers_half_open gauge")
        lines.append(f"titan_circuit_breakers_half_open {self.circuit_breakers_half_open}")
        
        lines.append("# HELP titan_uptime_seconds Server uptime in seconds")
        lines.append("# TYPE titan_uptime_seconds gauge")
        lines.append(f"titan_uptime_seconds {self.get_uptime_seconds():.0f}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "devices": {
                "total": self.devices_total,
                "ready": self.devices_ready,
                "booting": self.devices_booting,
                "patched": self.devices_patched,
                "error": self.devices_error,
            },
            "requests": {
                "total": self.requests_total,
                "success": self.requests_success,
                "error": self.requests_error,
                "latency_avg": self.get_request_latency_avg(),
            },
            "adb": {
                "commands_total": self.adb_commands_total,
                "commands_success": self.adb_commands_success,
                "commands_failed": self.adb_commands_failed,
                "reconnects": self.adb_reconnects,
            },
            "ollama": {
                "calls_total": self.ollama_calls_total,
                "calls_success": self.ollama_calls_success,
                "calls_failed": self.ollama_calls_failed,
                "fallbacks": self.ollama_fallbacks,
            },
            "device_creation": {
                "total": self.device_creations_total,
                "success": self.device_creations_success,
                "failed": self.device_creations_failed,
                "time_avg": self.get_device_creation_time_avg(),
            },
            "injection": {
                "total": self.injections_total,
                "success": self.injections_success,
                "failed": self.injections_failed,
                "time_avg": self.get_injection_time_avg(),
            },
            "circuit_breakers": {
                "open": self.circuit_breakers_open,
                "half_open": self.circuit_breakers_half_open,
            },
            "uptime_seconds": self.get_uptime_seconds(),
        }


# Global metrics instance
_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    return _metrics
