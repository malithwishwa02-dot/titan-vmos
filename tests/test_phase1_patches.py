"""
Titan V11.3 — Phase 1 Patch Test Suite
Unit and integration tests for all 8 critical patches.
"""

import asyncio
import json
import logging
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Add core to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

logger = logging.getLogger("titan.test-phase1")


class TestADBErrorClassifier(unittest.TestCase):
    """Test ADB error classification (P0-3)."""
    
    def setUp(self):
        from adb_error_classifier import classify_adb_error, ADBErrorType, should_retry, get_recovery_strategy
        self.classify = classify_adb_error
        self.ADBErrorType = ADBErrorType
        self.should_retry = should_retry
        self.get_recovery_strategy = get_recovery_strategy
    
    def test_classify_timeout_error(self):
        """Test timeout error classification."""
        result = self.classify("timeout", 1)
        self.assertEqual(result, self.ADBErrorType.TIMEOUT)
    
    def test_classify_offline_error(self):
        """Test offline error classification."""
        result = self.classify("device offline", 1)
        self.assertEqual(result, self.ADBErrorType.OFFLINE)
    
    def test_classify_permission_error(self):
        """Test permission denied error classification."""
        result = self.classify("permission denied", 1)
        self.assertEqual(result, self.ADBErrorType.PERMISSION)
    
    def test_classify_connection_refused(self):
        """Test connection refused error classification."""
        result = self.classify("connection refused", 1)
        self.assertEqual(result, self.ADBErrorType.CONNECTION_REFUSED)
    
    def test_classify_device_not_found(self):
        """Test device not found error classification."""
        result = self.classify("no devices found", 1)
        self.assertEqual(result, self.ADBErrorType.DEVICE_NOT_FOUND)
    
    def test_classify_unknown_error(self):
        """Test unknown error classification."""
        result = self.classify("some random error", 1)
        self.assertEqual(result, self.ADBErrorType.UNKNOWN)
    
    def test_should_retry_timeout(self):
        """Test that timeout errors are retryable."""
        self.assertTrue(self.should_retry(self.ADBErrorType.TIMEOUT))
    
    def test_should_not_retry_permission(self):
        """Test that permission errors are not retryable."""
        self.assertFalse(self.should_retry(self.ADBErrorType.PERMISSION))
    
    def test_recovery_strategy_timeout(self):
        """Test recovery strategy for timeout."""
        strategy = self.get_recovery_strategy(self.ADBErrorType.TIMEOUT)
        self.assertEqual(strategy, "reconnect_with_backoff")
    
    def test_recovery_strategy_permission(self):
        """Test recovery strategy for permission."""
        strategy = self.get_recovery_strategy(self.ADBErrorType.PERMISSION)
        self.assertEqual(strategy, "escalate_to_root")


class TestCircuitBreaker(unittest.TestCase):
    """Test circuit breaker pattern (P0-4)."""
    
    def setUp(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        self.CircuitBreaker = CircuitBreaker
        self.CircuitState = CircuitState
    
    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in CLOSED state."""
        breaker = self.CircuitBreaker("test", failure_threshold=3)
        self.assertEqual(breaker.state, self.CircuitState.CLOSED)
    
    def test_circuit_breaker_opens_after_threshold(self):
        """Test circuit breaker opens after failure threshold."""
        breaker = self.CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            breaker.record_failure()
        self.assertEqual(breaker.state, self.CircuitState.OPEN)
    
    def test_circuit_breaker_is_open(self):
        """Test is_open() returns True when OPEN."""
        breaker = self.CircuitBreaker("test", failure_threshold=1)
        breaker.record_failure()
        self.assertTrue(breaker.is_open())
    
    def test_circuit_breaker_half_open_after_timeout(self):
        """Test circuit breaker transitions to HALF_OPEN after timeout."""
        breaker = self.CircuitBreaker("test", failure_threshold=1, recovery_timeout=1)
        breaker.record_failure()
        self.assertEqual(breaker.state, self.CircuitState.OPEN)
        
        # Wait for recovery timeout
        time.sleep(1.1)
        
        # Check state should transition to HALF_OPEN
        self.assertFalse(breaker.is_open())
        self.assertEqual(breaker.state, self.CircuitState.HALF_OPEN)
    
    def test_circuit_breaker_closes_after_success(self):
        """Test circuit breaker closes after successful calls in HALF_OPEN."""
        breaker = self.CircuitBreaker("test", failure_threshold=1, recovery_timeout=1)
        breaker.record_failure()
        time.sleep(1.1)
        
        # Transition to HALF_OPEN by checking is_open()
        self.assertFalse(breaker.is_open())
        self.assertEqual(breaker.state, self.CircuitState.HALF_OPEN)
        
        # Record successes to close
        breaker.record_success()
        breaker.record_success()
        
        self.assertEqual(breaker.state, self.CircuitState.CLOSED)
    
    def test_circuit_breaker_call_raises_when_open(self):
        """Test circuit breaker raises when open."""
        breaker = self.CircuitBreaker("test", failure_threshold=1)
        breaker.record_failure()
        
        with self.assertRaises(RuntimeError):
            breaker.call(lambda: "test")
    
    def test_circuit_breaker_call_succeeds_when_closed(self):
        """Test circuit breaker allows calls when closed."""
        breaker = self.CircuitBreaker("test")
        result = breaker.call(lambda: "success")
        self.assertEqual(result, "success")


class TestDeviceStateDB(unittest.TestCase):
    """Test SQLite device state persistence (P0-6)."""
    
    def setUp(self):
        from device_state_db import DeviceStateDB
        self.DeviceStateDB = DeviceStateDB
        
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.temp_db.name
        self.temp_db.close()
        
        self.db = DeviceStateDB(self.db_path)
    
    def tearDown(self):
        """Clean up temporary database."""
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
    
    def test_database_initialization(self):
        """Test database schema is created."""
        self.assertTrue(os.path.exists(self.db_path))
        
        # Verify schema
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
            )
            self.assertIsNotNone(cursor.fetchone())
    
    def test_save_and_load_device(self):
        """Test saving and loading device state."""
        device_dict = {
            "id": "test-device-1",
            "adb_target": "127.0.0.1:5555",
            "state": "ready",
            "device_type": "cuttlefish",
            "instance_num": 1,
            "adb_port": 6520,
            "vnc_port": 6444,
            "config": {"model": "samsung_s25"},
            "patch_result": {"score": 95},
            "stealth_score": 95,
            "created_at": time.time(),
            "error": "",
        }
        
        # Save device
        self.assertTrue(self.db.save_device(device_dict))
        
        # Load device
        loaded = self.db.load_device("test-device-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"], "test-device-1")
        self.assertEqual(loaded["state"], "ready")
        self.assertEqual(loaded["stealth_score"], 95)
    
    def test_load_all_devices(self):
        """Test loading all devices."""
        for i in range(3):
            device_dict = {
                "id": f"device-{i}",
                "adb_target": f"127.0.0.1:{5555+i}",
                "state": "ready",
                "device_type": "cuttlefish",
                "instance_num": i,
                "adb_port": 6520 + i,
                "vnc_port": 6444 + i,
                "config": {},
                "patch_result": {},
                "stealth_score": 90,
                "created_at": time.time(),
                "error": "",
            }
            self.db.save_device(device_dict)
        
        devices = self.db.load_all_devices()
        self.assertEqual(len(devices), 3)
    
    def test_delete_device(self):
        """Test deleting device."""
        device_dict = {
            "id": "test-delete",
            "adb_target": "127.0.0.1:5555",
            "state": "ready",
            "device_type": "cuttlefish",
            "instance_num": 1,
            "adb_port": 6520,
            "vnc_port": 6444,
            "config": {},
            "patch_result": {},
            "stealth_score": 90,
            "created_at": time.time(),
            "error": "",
        }
        
        self.db.save_device(device_dict)
        self.assertTrue(self.db.delete_device("test-delete"))
        
        loaded = self.db.load_device("test-delete")
        self.assertIsNone(loaded)
    
    def test_get_devices_by_state(self):
        """Test filtering devices by state."""
        for state in ["ready", "booting", "error"]:
            device_dict = {
                "id": f"device-{state}",
                "adb_target": "127.0.0.1:5555",
                "state": state,
                "device_type": "cuttlefish",
                "instance_num": 1,
                "adb_port": 6520,
                "vnc_port": 6444,
                "config": {},
                "patch_result": {},
                "stealth_score": 90,
                "created_at": time.time(),
                "error": "",
            }
            self.db.save_device(device_dict)
        
        ready_devices = self.db.get_devices_by_state("ready")
        self.assertEqual(len(ready_devices), 1)
        self.assertEqual(ready_devices[0]["state"], "ready")


class TestJSONLogger(unittest.TestCase):
    """Test structured JSON logging (P0-7)."""
    
    def setUp(self):
        from json_logger import JSONFormatter
        self.JSONFormatter = JSONFormatter
    
    def test_json_formatter_output(self):
        """Test JSON formatter produces valid JSON."""
        formatter = self.JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        output = formatter.format(record)
        
        # Verify it's valid JSON
        data = json.loads(output)
        self.assertEqual(data["logger"], "test.logger")
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["message"], "Test message")
        self.assertEqual(data["line"], 42)
    
    def test_json_formatter_includes_timestamp(self):
        """Test JSON formatter includes timestamp."""
        formatter = self.JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        
        output = json.loads(formatter.format(record))
        self.assertIn("timestamp", output)
        self.assertIn("timestamp_iso", output)


class TestAuthMiddleware(unittest.TestCase):
    """Test authentication middleware (P0-1)."""
    
    def test_auth_bypass_removed(self):
        """Test that default secret no longer bypasses auth."""
        # This test verifies the code change was made
        # In production, this would be an integration test
        import inspect
        from pathlib import Path
        
        auth_file = Path(__file__).parent.parent / "server" / "middleware" / "auth.py"
        content = auth_file.read_text()
        
        # Verify bypass code is removed
        self.assertNotIn('if not secret or secret == "change-me-to-a-secure-random-string":', content)
        self.assertIn('if not secret:', content)
        self.assertIn('TITAN_API_SECRET environment variable not set', content)


class TestADBParameterization(unittest.TestCase):
    """Test parameterized ADB commands (P0-2)."""
    
    def test_adb_parameterization_in_devices_router(self):
        """Test that devices router uses parameterized ADB calls."""
        import inspect
        from pathlib import Path
        
        devices_file = Path(__file__).parent.parent / "server" / "routers" / "devices.py"
        content = devices_file.read_text()
        
        # Verify parameterized calls are used
        self.assertIn('["adb", "-s", t, "shell", "input", "tap"', content)
        self.assertIn('["adb", "-s", t, "shell", "input", "text"', content)
        
        # Verify old shell concatenation is removed
        self.assertNotIn('f\'shell "input tap', content)


class TestDeviceRecoveryManager(unittest.TestCase):
    """Test device recovery manager (P0-8)."""
    
    def setUp(self):
        from device_recovery import DeviceRecoveryManager
        self.DeviceRecoveryManager = DeviceRecoveryManager
    
    def test_recovery_manager_initialization(self):
        """Test recovery manager initializes correctly."""
        mock_dm = MagicMock()
        manager = self.DeviceRecoveryManager(mock_dm, check_interval=60, boot_timeout=300)
        
        self.assertEqual(manager.check_interval, 60)
        self.assertEqual(manager.boot_timeout, 300)
        self.assertFalse(manager._running)
    
    async def test_recovery_manager_start_stop(self):
        """Test recovery manager start and stop."""
        mock_dm = MagicMock()
        mock_dm.list_devices.return_value = []
        
        manager = self.DeviceRecoveryManager(mock_dm)
        
        await manager.start()
        self.assertTrue(manager._running)
        
        await manager.stop()
        self.assertFalse(manager._running)
    
    def test_recovery_manager_start_stop_async(self):
        """Test recovery manager async start/stop."""
        asyncio.run(self.test_recovery_manager_start_stop())


class TestIntegration(unittest.TestCase):
    """Integration tests for Phase 1 patches."""
    
    def test_all_imports_successful(self):
        """Test that all new modules can be imported."""
        try:
            from adb_error_classifier import classify_adb_error
            from circuit_breaker import CircuitBreaker
            from device_state_db import DeviceStateDB
            from json_logger import JSONFormatter
            from device_recovery import DeviceRecoveryManager
        except ImportError as e:
            self.fail(f"Failed to import module: {e}")
    
    def test_no_circular_imports(self):
        """Test that there are no circular import dependencies."""
        # This is a smoke test
        import sys
        
        # Clear any cached imports
        modules_to_clear = [m for m in sys.modules if m.startswith("titan")]
        for m in modules_to_clear:
            del sys.modules[m]
        
        # Try importing main modules
        try:
            import device_manager
            import adb_utils
        except ImportError as e:
            self.fail(f"Circular import detected: {e}")


def run_tests():
    """Run all Phase 1 tests."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestADBErrorClassifier))
    suite.addTests(loader.loadTestsFromTestCase(TestCircuitBreaker))
    suite.addTests(loader.loadTestsFromTestCase(TestDeviceStateDB))
    suite.addTests(loader.loadTestsFromTestCase(TestJSONLogger))
    suite.addTests(loader.loadTestsFromTestCase(TestAuthMiddleware))
    suite.addTests(loader.loadTestsFromTestCase(TestADBParameterization))
    suite.addTests(loader.loadTestsFromTestCase(TestDeviceRecoveryManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
