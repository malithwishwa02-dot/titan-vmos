"""
Titan V11.3 — Circuit Breaker Pattern
Prevents cascading failures by stopping requests to failing services.
"""

import logging
import time
from enum import Enum
from typing import Callable, Optional, Any
import core.auto_env  # Auto-load .env for VASTAI_CODING_* variables

logger = logging.getLogger("titan.circuit-breaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for external service calls.
    
    Prevents cascading failures by:
    1. Tracking consecutive failures
    2. Opening circuit after threshold (reject requests)
    3. Half-opening after timeout (test recovery)
    4. Closing on success
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        expected_exception: type = Exception,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
    
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        if self.state == CircuitState.CLOSED:
            return False
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if self.last_failure_time and time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return False
            return True
        
        # HALF_OPEN state: allow requests
        return False
    
    def record_success(self):
        """Record successful call."""
        self.failure_count = 0
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:  # 2 successes to close
                logger.info(f"Circuit breaker '{self.name}' CLOSED (recovered)")
                self.state = CircuitState.CLOSED
    
    def record_failure(self):
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    f"Circuit breaker '{self.name}' OPEN after {self.failure_count} failures"
                )
            self.state = CircuitState.OPEN
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        if self.is_open():
            raise RuntimeError(
                f"Circuit breaker '{self.name}' is OPEN. Service unavailable."
            )
        
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except self.expected_exception as e:
            self.record_failure()
            raise
    
    def get_status(self) -> dict:
        """Get circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failure_count,
            "threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class CircuitBreakerManager:
    """Manages multiple circuit breakers."""
    
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
    
    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
    ) -> CircuitBreaker:
        """Get existing or create new circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return self._breakers[name]
    
    def get_status(self) -> dict:
        """Get status of all circuit breakers."""
        return {
            name: breaker.get_status()
            for name, breaker in self._breakers.items()
        }


# Global circuit breaker manager
_manager = CircuitBreakerManager()


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create circuit breaker by name."""
    return _manager.get_or_create(name, **kwargs)


def get_all_breakers_status() -> dict:
    """Get status of all circuit breakers."""
    return _manager.get_status()
