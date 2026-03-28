"""
Titan V11.3 — ADB Connection Pooling
Maintains persistent ADB connections to reduce overhead.
"""

import logging
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("titan.adb-connection-pool")


class ADBConnection:
    """Represents a persistent ADB connection."""
    
    def __init__(self, target: str):
        self.target = target
        self.created_at = time.time()
        self.last_used = time.time()
        self.command_count = 0
        self.is_connected = False
        self._connect()
    
    def _connect(self):
        """Establish ADB connection."""
        try:
            result = subprocess.run(
                ["adb", "connect", self.target],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.is_connected = result.returncode == 0 and "connected" in result.stdout.lower()
            if self.is_connected:
                logger.debug(f"Connected to {self.target}")
            else:
                logger.warning(f"Failed to connect to {self.target}: {result.stdout}")
        except Exception as e:
            logger.error(f"Connection error for {self.target}: {e}")
            self.is_connected = False
    
    def execute(self, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
        """Execute command on connected device."""
        if not self.is_connected:
            return False, "not_connected"
        
        try:
            result = subprocess.run(
                ["adb", "-s", self.target, "shell"] + cmd.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            self.last_used = time.time()
            self.command_count += 1
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f"Command timeout on {self.target}")
            return False, "timeout"
        except Exception as e:
            logger.error(f"Command error on {self.target}: {e}")
            return False, str(e)
    
    def disconnect(self):
        """Disconnect from device."""
        try:
            subprocess.run(
                ["adb", "disconnect", self.target],
                capture_output=True,
                timeout=5,
            )
            self.is_connected = False
            logger.debug(f"Disconnected from {self.target}")
        except Exception as e:
            logger.error(f"Disconnect error for {self.target}: {e}")
    
    def is_stale(self, max_age: int = 3600) -> bool:
        """Check if connection is stale."""
        return time.time() - self.last_used > max_age
    
    def get_stats(self) -> Dict:
        """Get connection statistics."""
        return {
            "target": self.target,
            "connected": self.is_connected,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "command_count": self.command_count,
            "uptime_seconds": time.time() - self.created_at,
        }


class ADBConnectionPool:
    """Pool of persistent ADB connections."""
    
    def __init__(self, max_connections: int = 16, max_age: int = 3600):
        """
        Initialize connection pool.
        
        Args:
            max_connections: Maximum concurrent connections
            max_age: Maximum connection age in seconds
        """
        self.max_connections = max_connections
        self.max_age = max_age
        self._connections: Dict[str, ADBConnection] = {}
        self._lock = threading.RLock()
        self._cleanup_thread = None
        self._running = False
    
    def start(self):
        """Start cleanup thread."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="adb-pool-cleanup",
        )
        self._cleanup_thread.start()
        logger.info("ADB connection pool started")
    
    def stop(self):
        """Stop cleanup thread and close all connections."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        
        with self._lock:
            for conn in self._connections.values():
                conn.disconnect()
            self._connections.clear()
        
        logger.info("ADB connection pool stopped")
    
    def get_connection(self, target: str) -> Optional[ADBConnection]:
        """Get or create connection to target."""
        with self._lock:
            # Return existing connection if available
            if target in self._connections:
                conn = self._connections[target]
                if conn.is_connected:
                    return conn
                else:
                    # Reconnect stale connection
                    conn._connect()
                    return conn if conn.is_connected else None
            
            # Create new connection if under limit
            if len(self._connections) < self.max_connections:
                conn = ADBConnection(target)
                if conn.is_connected:
                    self._connections[target] = conn
                    return conn
            
            logger.warning(f"Connection pool full, cannot connect to {target}")
            return None
    
    def execute(self, target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
        """Execute command on pooled connection."""
        conn = self.get_connection(target)
        if not conn:
            return False, "no_connection"
        
        return conn.execute(cmd, timeout)
    
    def release_connection(self, target: str):
        """Release connection back to pool."""
        # Connections are kept in pool for reuse
        pass
    
    def _cleanup_loop(self):
        """Periodically clean up stale connections."""
        while self._running:
            try:
                time.sleep(300)  # Check every 5 minutes
                self._cleanup_stale_connections()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    def _cleanup_stale_connections(self):
        """Remove stale connections."""
        with self._lock:
            stale = [
                target for target, conn in self._connections.items()
                if conn.is_stale(self.max_age)
            ]
            
            for target in stale:
                conn = self._connections.pop(target)
                conn.disconnect()
                logger.info(f"Cleaned up stale connection: {target}")
    
    def get_stats(self) -> Dict:
        """Get pool statistics."""
        with self._lock:
            return {
                "total_connections": len(self._connections),
                "max_connections": self.max_connections,
                "connections": {
                    target: conn.get_stats()
                    for target, conn in self._connections.items()
                },
            }


# Global connection pool
_pool: Optional[ADBConnectionPool] = None


def get_pool() -> ADBConnectionPool:
    """Get or create global connection pool."""
    global _pool
    if _pool is None:
        _pool = ADBConnectionPool(max_connections=16, max_age=3600)
        _pool.start()
    return _pool


def execute_pooled(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    """Execute command using pooled connection."""
    pool = get_pool()
    return pool.execute(target, cmd, timeout)
