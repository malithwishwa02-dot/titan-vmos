"""
Titan V11.3 — Exponential Backoff
Implements exponential backoff with jitter for retries.
"""

import asyncio
import logging
import random
import time
from typing import Callable, Optional, Any, TypeVar

logger = logging.getLogger("titan.exponential-backoff")

T = TypeVar('T')


class ExponentialBackoff:
    """Exponential backoff with jitter for retries."""
    
    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        jitter: bool = True,
        max_retries: int = 5,
    ):
        """
        Initialize exponential backoff.
        
        Args:
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            multiplier: Multiplier for each retry
            jitter: Add random jitter to delays
            max_retries: Maximum number of retries
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.max_retries = max_retries
    
    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for attempt number.
        
        Args:
            attempt: Attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        delay = self.initial_delay * (self.multiplier ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            # Add random jitter: ±20% of delay
            jitter_amount = delay * 0.2
            delay = delay + random.uniform(-jitter_amount, jitter_amount)
            delay = max(0, delay)  # Ensure non-negative
        
        return delay
    
    async def call_async(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs,
    ) -> Any:
        """
        Call async function with exponential backoff retry.
        
        Args:
            func: Async callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If all retries exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All {self.max_retries + 1} attempts exhausted: {e}"
                    )
        
        raise last_exception
    
    def call_sync(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Call sync function with exponential backoff retry.
        
        Args:
            func: Callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If all retries exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"All {self.max_retries + 1} attempts exhausted: {e}"
                    )
        
        raise last_exception


class WorkflowRetryPolicy:
    """Retry policy for workflow stages."""
    
    def __init__(self):
        # Stage-specific retry policies
        self.policies = {
            "bootstrap_gapps": ExponentialBackoff(
                initial_delay=2.0,
                max_delay=30.0,
                max_retries=2,
            ),
            "forge_profile": ExponentialBackoff(
                initial_delay=1.0,
                max_delay=20.0,
                max_retries=2,
            ),
            "inject_profile": ExponentialBackoff(
                initial_delay=3.0,
                max_delay=60.0,
                max_retries=3,
            ),
            "install_apps": ExponentialBackoff(
                initial_delay=5.0,
                max_delay=60.0,
                max_retries=3,
            ),
            "setup_wallet": ExponentialBackoff(
                initial_delay=2.0,
                max_delay=30.0,
                max_retries=2,
            ),
            "warmup_browse": ExponentialBackoff(
                initial_delay=3.0,
                max_delay=45.0,
                max_retries=2,
            ),
            "warmup_youtube": ExponentialBackoff(
                initial_delay=3.0,
                max_delay=45.0,
                max_retries=2,
            ),
            "verify_report": ExponentialBackoff(
                initial_delay=2.0,
                max_delay=30.0,
                max_retries=2,
            ),
        }
    
    def get_policy(self, stage_name: str) -> ExponentialBackoff:
        """Get retry policy for stage."""
        return self.policies.get(
            stage_name,
            ExponentialBackoff(initial_delay=2.0, max_delay=30.0, max_retries=2),
        )
    
    async def execute_with_retry(
        self,
        stage_name: str,
        func: Callable[..., Any],
        *args,
        **kwargs,
    ) -> Any:
        """Execute stage with appropriate retry policy."""
        policy = self.get_policy(stage_name)
        return await policy.call_async(func, *args, **kwargs)


# Global retry policy
_retry_policy = WorkflowRetryPolicy()


def get_retry_policy() -> WorkflowRetryPolicy:
    """Get global workflow retry policy."""
    return _retry_policy
