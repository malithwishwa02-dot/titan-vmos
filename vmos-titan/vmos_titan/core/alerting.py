"""
Titan V11.3 — Alerting System
Sends alerts via webhooks for health degradation and critical events.
"""

import asyncio
import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any

logger = logging.getLogger("titan.alerting")


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Alert event."""
    severity: AlertSeverity
    title: str
    message: str
    timestamp: float
    component: str
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp,
            "component": self.component,
            "metadata": self.metadata,
        }


class AlertManager:
    """Manages alerts and webhook notifications."""
    
    def __init__(self, webhook_url: Optional[str] = None):
        """
        Initialize alert manager.
        
        Args:
            webhook_url: Webhook URL for alerts (from TITAN_ALERT_WEBHOOK env var)
        """
        self.webhook_url = webhook_url or os.environ.get("TITAN_ALERT_WEBHOOK", "")
        self.alerts: List[Alert] = []
        self.max_alerts = 1000
        self._last_alert_time: Dict[str, float] = {}
        self._alert_cooldown = 300  # 5 minutes between same alerts
    
    async def send_alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        component: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send alert via webhook.
        
        Args:
            severity: Alert severity level
            title: Alert title
            message: Alert message
            component: Component that triggered alert
            metadata: Additional metadata
            
        Returns:
            True if alert sent successfully
        """
        if not self.webhook_url:
            logger.debug(f"No webhook configured, skipping alert: {title}")
            return False
        
        # Check cooldown to prevent alert spam
        alert_key = f"{component}:{title}"
        last_time = self._last_alert_time.get(alert_key, 0)
        if time.time() - last_time < self._alert_cooldown:
            logger.debug(f"Alert cooldown active for {alert_key}, skipping")
            return False
        
        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            timestamp=time.time(),
            component=component,
            metadata=metadata or {},
        )
        
        # Store alert
        self.alerts.append(alert)
        if len(self.alerts) > self.max_alerts:
            self.alerts.pop(0)
        
        # Send webhook
        try:
            await self._send_webhook(alert)
            self._last_alert_time[alert_key] = time.time()
            logger.info(f"Alert sent: {title}")
            return True
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False
    
    async def _send_webhook(self, alert: Alert):
        """Send alert via webhook."""
        payload = {
            "alert": alert.to_dict(),
            "server": os.environ.get("HOSTNAME", "unknown"),
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                response = resp.read().decode()
                logger.debug(f"Webhook response: {response}")
        except urllib.error.URLError as e:
            logger.error(f"Webhook connection error: {e}")
            raise
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            raise
    
    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        return [a.to_dict() for a in self.alerts[-limit:]]
    
    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[Dict[str, Any]]:
        """Get alerts by severity."""
        return [a.to_dict() for a in self.alerts if a.severity == severity]


class HealthMonitor:
    """Monitors system health and triggers alerts."""
    
    def __init__(self, alert_manager: AlertManager, device_manager: Any):
        """
        Initialize health monitor.
        
        Args:
            alert_manager: AlertManager instance
            device_manager: DeviceManager instance
        """
        self.alert_manager = alert_manager
        self.dm = device_manager
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._error_count: Dict[str, int] = {}
        self._error_threshold = 3
    
    async def start(self):
        """Start health monitoring."""
        if self._running:
            logger.warning("Health monitor already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started")
    
    async def stop(self):
        """Stop health monitoring."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_health()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(60)
    
    async def _check_health(self):
        """Check system health."""
        devices = self.dm.list_devices()
        
        # Check for too many error devices
        error_devices = [d for d in devices if d.state == "error"]
        if len(error_devices) > 2:
            await self.alert_manager.send_alert(
                AlertSeverity.CRITICAL,
                "Multiple devices in error state",
                f"{len(error_devices)} devices are in error state",
                component="device-manager",
                metadata={"error_device_count": len(error_devices)},
            )
        
        # Check for stuck booting devices
        booting_devices = [d for d in devices if d.state == "booting"]
        for dev in booting_devices:
            elapsed = time.time() - (dev.created_at if isinstance(dev.created_at, float) 
                                    else time.time())
            if elapsed > 600:  # 10 minutes
                await self.alert_manager.send_alert(
                    AlertSeverity.WARNING,
                    f"Device {dev.id} stuck in booting",
                    f"Device has been booting for {elapsed:.0f} seconds",
                    component="device-manager",
                    metadata={"device_id": dev.id, "elapsed_seconds": elapsed},
                )
        
        # Check device creation rate
        if len(devices) > 7:  # Near capacity
            await self.alert_manager.send_alert(
                AlertSeverity.WARNING,
                "Device capacity near limit",
                f"{len(devices)}/8 devices active",
                component="device-manager",
                metadata={"active_devices": len(devices), "max_devices": 8},
            )


# Global alert manager
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get or create global alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


def get_health_monitor(device_manager: Any) -> HealthMonitor:
    """Create health monitor."""
    return HealthMonitor(get_alert_manager(), device_manager)
