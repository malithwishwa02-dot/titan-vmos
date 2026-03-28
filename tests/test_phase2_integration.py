"""
Titan V11.3 — Phase 2 Integration Tests
Tests for observability, alerting, and operational resilience.
"""

import asyncio
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Add core to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

logger = logging.getLogger("titan.test-phase2")


class TestPrometheusMetrics(unittest.TestCase):
    """Test Prometheus metrics endpoint (P1-1)."""
    
    def setUp(self):
        from metrics import MetricsCollector
        self.MetricsCollector = MetricsCollector
    
    def test_metrics_initialization(self):
        """Test metrics collector initializes correctly."""
        metrics = self.MetricsCollector()
        self.assertEqual(metrics.devices_total, 0)
        self.assertEqual(metrics.requests_total, 0)
        self.assertGreater(metrics.start_time, 0)
    
    def test_record_request(self):
        """Test recording HTTP request."""
        metrics = self.MetricsCollector()
        metrics.record_request(latency=0.5, success=True)
        
        self.assertEqual(metrics.requests_total, 1)
        self.assertEqual(metrics.requests_success, 1)
        self.assertEqual(metrics.request_latency_sum, 0.5)
    
    def test_record_adb_command(self):
        """Test recording ADB command."""
        metrics = self.MetricsCollector()
        metrics.record_adb_command(success=True)
        
        self.assertEqual(metrics.adb_commands_total, 1)
        self.assertEqual(metrics.adb_commands_success, 1)
    
    def test_record_device_creation(self):
        """Test recording device creation."""
        metrics = self.MetricsCollector()
        metrics.record_device_creation(success=True, duration=120.0)
        
        self.assertEqual(metrics.device_creations_total, 1)
        self.assertEqual(metrics.device_creations_success, 1)
        self.assertEqual(metrics.device_creation_time_sum, 120.0)
    
    def test_update_device_states(self):
        """Test updating device state counts."""
        metrics = self.MetricsCollector()
        metrics.update_device_states({
            "ready": 3,
            "booting": 1,
            "patched": 2,
            "error": 1,
        })
        
        self.assertEqual(metrics.devices_total, 7)
        self.assertEqual(metrics.devices_ready, 3)
        self.assertEqual(metrics.devices_error, 1)
    
    def test_prometheus_format_output(self):
        """Test Prometheus format output."""
        metrics = self.MetricsCollector()
        metrics.record_request(latency=0.1)
        metrics.update_device_states({"ready": 2})
        
        output = metrics.to_prometheus_format()
        
        # Verify output contains expected metrics
        self.assertIn("titan_devices_total 2", output)
        self.assertIn("titan_requests_total 1", output)
        self.assertIn("# TYPE titan_devices_total gauge", output)
    
    def test_metrics_to_dict(self):
        """Test metrics export to dictionary."""
        metrics = self.MetricsCollector()
        metrics.record_request(latency=0.1)
        metrics.update_device_states({"ready": 2})
        
        data = metrics.to_dict()
        
        self.assertEqual(data["devices"]["ready"], 2)
        self.assertEqual(data["requests"]["total"], 1)
        self.assertIn("uptime_seconds", data)


class TestAlertingSystem(unittest.TestCase):
    """Test alerting system (P1-2)."""
    
    def setUp(self):
        from alerting import AlertManager, AlertSeverity
        self.AlertManager = AlertManager
        self.AlertSeverity = AlertSeverity
    
    def test_alert_manager_initialization(self):
        """Test alert manager initializes correctly."""
        manager = self.AlertManager()
        self.assertEqual(len(manager.alerts), 0)
        self.assertIsNotNone(manager.webhook_url)
    
    async def test_send_alert_without_webhook(self):
        """Test sending alert without webhook configured."""
        manager = self.AlertManager(webhook_url="")
        result = await manager.send_alert(
            self.AlertSeverity.WARNING,
            "Test alert",
            "Test message",
        )
        self.assertFalse(result)
    
    def test_get_recent_alerts(self):
        """Test retrieving recent alerts."""
        manager = self.AlertManager(webhook_url="")
        
        # Add alerts directly (bypass webhook)
        for i in range(5):
            from alerting import Alert
            alert = Alert(
                severity=self.AlertSeverity.WARNING,
                title=f"Alert {i}",
                message=f"Message {i}",
                timestamp=time.time(),
                component="test",
                metadata={},
            )
            manager.alerts.append(alert)
        
        recent = manager.get_recent_alerts(limit=3)
        self.assertEqual(len(recent), 3)
    
    def test_get_alerts_by_severity(self):
        """Test filtering alerts by severity."""
        manager = self.AlertManager(webhook_url="")
        
        from alerting import Alert
        for severity in [self.AlertSeverity.INFO, self.AlertSeverity.WARNING, self.AlertSeverity.CRITICAL]:
            alert = Alert(
                severity=severity,
                title=f"Alert {severity.value}",
                message="Test",
                timestamp=time.time(),
                component="test",
                metadata={},
            )
            manager.alerts.append(alert)
        
        critical_alerts = manager.get_alerts_by_severity(self.AlertSeverity.CRITICAL)
        self.assertEqual(len(critical_alerts), 1)
        self.assertEqual(critical_alerts[0]["severity"], "critical")


class TestIdempotentInjection(unittest.TestCase):
    """Test idempotent profile injection (P1-3)."""
    
    def setUp(self):
        from injection_idempotency import IdempotentInjector, InjectionChecksum
        self.IdempotentInjector = IdempotentInjector
        self.InjectionChecksum = InjectionChecksum
    
    def test_checksum_computation(self):
        """Test checksum computation."""
        tracker = self.InjectionChecksum()
        data = {"name": "John", "phone": "555-1234"}
        
        checksum1 = tracker.compute_checksum(data)
        checksum2 = tracker.compute_checksum(data)
        
        # Same data should produce same checksum
        self.assertEqual(checksum1, checksum2)
        self.assertEqual(len(checksum1), 64)  # SHA256 hex length
    
    def test_duplicate_detection(self):
        """Test duplicate data detection."""
        tracker = self.InjectionChecksum()
        data = {"name": "John"}
        
        # Record injection
        tracker.record_injection("contact", data)
        
        # Check if duplicate
        self.assertTrue(tracker.is_duplicate("contact", data))
    
    def test_injection_stats(self):
        """Test injection statistics."""
        injector = self.IdempotentInjector("127.0.0.1:5555")
        
        # Record injections
        injector.checksum_tracker.record_injection("contact", {"name": "John"})
        injector.checksum_tracker.record_injection("contact", {"name": "Jane"})
        injector.checksum_tracker.record_injection("sms", {"text": "Hello"})
        
        stats = injector.get_injection_stats()
        
        self.assertEqual(stats["contacts"], 2)
        self.assertEqual(stats["sms"], 1)


class TestExponentialBackoff(unittest.TestCase):
    """Test exponential backoff retry (P1-4)."""
    
    def setUp(self):
        from exponential_backoff import ExponentialBackoff
        self.ExponentialBackoff = ExponentialBackoff
    
    def test_backoff_delay_calculation(self):
        """Test delay calculation."""
        backoff = self.ExponentialBackoff(
            initial_delay=1.0,
            max_delay=60.0,
            multiplier=2.0,
            jitter=False,
        )
        
        # Verify exponential growth
        self.assertEqual(backoff.get_delay(0), 1.0)
        self.assertEqual(backoff.get_delay(1), 2.0)
        self.assertEqual(backoff.get_delay(2), 4.0)
        self.assertEqual(backoff.get_delay(3), 8.0)
    
    def test_backoff_max_delay(self):
        """Test max delay enforcement."""
        backoff = self.ExponentialBackoff(
            initial_delay=1.0,
            max_delay=10.0,
            multiplier=2.0,
            jitter=False,
        )
        
        # Delay should not exceed max
        self.assertLessEqual(backoff.get_delay(10), 10.0)
    
    def test_backoff_with_jitter(self):
        """Test jitter application."""
        backoff = self.ExponentialBackoff(
            initial_delay=10.0,
            max_delay=60.0,
            multiplier=2.0,
            jitter=True,
        )
        
        # Delays should vary due to jitter
        delays = [backoff.get_delay(0) for _ in range(10)]
        unique_delays = len(set(delays))
        
        # Should have some variation
        self.assertGreater(unique_delays, 1)
    
    async def _test_async_retry_impl(self):
        """Test async retry with backoff implementation."""
        backoff = self.ExponentialBackoff(
            initial_delay=0.01,
            max_delay=0.1,
            max_retries=2,
        )
        
        call_count = 0
        
        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Test error")
            return "success"
        
        result = await backoff.call_async(failing_func)
        
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
    
    def test_async_retry(self):
        """Test async retry."""
        asyncio.run(self._test_async_retry_impl())


class TestADBConnectionPool(unittest.TestCase):
    """Test ADB connection pooling (P1-5)."""
    
    def setUp(self):
        from adb_connection_pool import ADBConnectionPool
        self.ADBConnectionPool = ADBConnectionPool
    
    def test_pool_initialization(self):
        """Test connection pool initializes correctly."""
        pool = self.ADBConnectionPool(max_connections=8)
        
        self.assertEqual(pool.max_connections, 8)
        self.assertEqual(len(pool._connections), 0)
    
    def test_pool_start_stop(self):
        """Test pool start and stop."""
        pool = self.ADBConnectionPool()
        
        pool.start()
        self.assertTrue(pool._running)
        
        pool.stop()
        self.assertFalse(pool._running)
    
    def test_pool_stats(self):
        """Test pool statistics."""
        pool = self.ADBConnectionPool()
        
        stats = pool.get_stats()
        
        self.assertEqual(stats["total_connections"], 0)
        self.assertEqual(stats["max_connections"], 16)
        self.assertIn("connections", stats)


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for real-world scenarios."""
    
    def test_metrics_and_alerts_integration(self):
        """Test metrics and alerting work together."""
        from metrics import MetricsCollector
        from alerting import AlertManager
        
        metrics = MetricsCollector()
        alert_manager = AlertManager(webhook_url="")
        
        # Simulate device creation
        metrics.record_device_creation(success=True, duration=120.0)
        metrics.update_device_states({"ready": 1})
        
        # Verify metrics recorded
        self.assertEqual(metrics.device_creations_total, 1)
        self.assertEqual(metrics.devices_total, 1)
    
    def test_all_phase2_modules_import(self):
        """Test all Phase 2 modules can be imported."""
        try:
            from metrics import MetricsCollector
            from alerting import AlertManager, HealthMonitor
            from injection_idempotency import IdempotentInjector
            from exponential_backoff import ExponentialBackoff, WorkflowRetryPolicy
            from adb_connection_pool import ADBConnectionPool
        except ImportError as e:
            self.fail(f"Failed to import Phase 2 module: {e}")


def run_tests():
    """Run all Phase 2 tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPrometheusMetrics))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertingSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestIdempotentInjection))
    suite.addTests(loader.loadTestsFromTestCase(TestExponentialBackoff))
    suite.addTests(loader.loadTestsFromTestCase(TestADBConnectionPool))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
