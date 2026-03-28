"""
Titan V11.3 — Structured JSON Logging
Provides JSON-formatted logging for centralized log aggregation.
"""

import json
import logging
import sys
import time
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": record.created,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        return json.dumps(log_data, default=str)


class StructuredLogger:
    """Wrapper for structured logging with extra fields."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def _log(self, level: int, message: str, extra_fields: Optional[Dict[str, Any]] = None):
        """Log with extra fields."""
        record = self.logger.makeRecord(
            self.logger.name,
            level,
            "(unknown file)",
            0,
            message,
            (),
            None,
        )
        if extra_fields:
            record.extra_fields = extra_fields
        self.logger.handle(record)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log(logging.DEBUG, message, kwargs if kwargs else None)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log(logging.INFO, message, kwargs if kwargs else None)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log(logging.WARNING, message, kwargs if kwargs else None)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log(logging.ERROR, message, kwargs if kwargs else None)
    
    def critical(self, message: str, **kwargs):
        """Log critical message."""
        self._log(logging.CRITICAL, message, kwargs if kwargs else None)


def setup_json_logging(name: str = "titan") -> StructuredLogger:
    """
    Setup JSON logging for a logger.
    
    Args:
        name: Logger name
        
    Returns:
        StructuredLogger instance
    """
    logger = logging.getLogger(name)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create JSON handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    
    return StructuredLogger(logger)


def configure_all_loggers():
    """Configure all loggers to use JSON formatting."""
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Create JSON handler for root
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)
    
    # Configure all titan loggers
    for logger_name in [
        "titan",
        "titan.api",
        "titan.device-manager",
        "titan.adb",
        "titan.adb-error-classifier",
        "titan.circuit-breaker",
        "titan.ai-intelligence",
        "titan.devices",
        "titan.stealth",
        "titan.genesis",
        "titan.wallet",
        "titan.profile-injector",
    ]:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
