"""
Titan V11.3 — Mock ADB Layer
Intercepts subprocess.run calls matching `adb -s` patterns so that
all core modules can be unit-tested offline without a live device.

Usage:
    mock = MockADB()
    mock.set_response("shell getprop ro.product.model", "SM-S928U")
    mock.set_response("shell echo ok", "ok")

    with mock.patch():
        from adb_utils import adb_shell
        result = adb_shell("127.0.0.1:6520", "getprop ro.product.model")
        assert result == "SM-S928U"

    assert mock.was_called("shell getprop ro.product.model")
"""

import contextlib
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from unittest.mock import patch as _mock_patch


@dataclass
class ADBCall:
    """Recorded ADB call."""
    full_cmd: str
    target: str
    adb_args: str
    returned: Any = None


@dataclass
class MockResponse:
    """Configurable response for a command pattern."""
    stdout: str = ""
    returncode: int = 0
    stderr: str = ""
    raw_stdout: bytes = b""
    side_effect: Optional[Callable] = None


class MockADB:
    """Mock ADB layer that intercepts subprocess.run for `adb -s <target>` calls.

    Non-ADB subprocess calls pass through to the real subprocess.run.
    """

    def __init__(self, default_target: str = "127.0.0.1:6520") -> None:
        self._default_target = default_target
        self._responses: Dict[str, MockResponse] = {}
        self._calls: List[ADBCall] = []
        self._real_run = subprocess.run

        # Default responses for common commands
        self.set_response("shell echo ok", "ok")
        self.set_response("root", "adbd is already running as root")
        self.set_response("shell id", "uid=0(root) gid=0(root)")
        self.set_response("shell getprop ro.product.model", "Cuttlefish")
        self.set_response("shell getprop ro.build.type", "userdebug")
        self.set_response("shell getprop gsm.sim.state", "READY")

    def set_response(self, cmd_pattern: str, stdout: str = "",
                     returncode: int = 0, stderr: str = "",
                     raw_stdout: Optional[bytes] = None) -> None:
        """Register a response for an ADB command pattern.

        Args:
            cmd_pattern: Substring to match in the ADB args (after `adb -s <target>`)
            stdout: Text stdout to return
            returncode: Process return code
            stderr: Text stderr to return
            raw_stdout: Raw bytes stdout (for adb_raw calls)
        """
        self._responses[cmd_pattern] = MockResponse(
            stdout=stdout,
            returncode=returncode,
            stderr=stderr,
            raw_stdout=raw_stdout if raw_stdout is not None else stdout.encode(),
        )

    def set_side_effect(self, cmd_pattern: str, fn: Callable) -> None:
        """Register a side-effect function for a command pattern.
        The function receives (cmd_string,) and should return a MockResponse or raise."""
        self._responses[cmd_pattern] = MockResponse(side_effect=fn)

    def set_timeout(self, cmd_pattern: str) -> None:
        """Make a command pattern raise TimeoutExpired."""
        def _raise(cmd):
            raise subprocess.TimeoutExpired(cmd, 15)
        self.set_side_effect(cmd_pattern, _raise)

    def set_failure(self, cmd_pattern: str, stderr: str = "error") -> None:
        """Make a command pattern return failure (returncode=1)."""
        self.set_response(cmd_pattern, stdout="", returncode=1, stderr=stderr)

    def _find_response(self, adb_args: str) -> Optional[MockResponse]:
        """Find the best matching response for the given ADB args."""
        # Exact match first
        if adb_args in self._responses:
            return self._responses[adb_args]
        # Substring match (longest match wins)
        matches = [(k, v) for k, v in self._responses.items() if k in adb_args]
        if matches:
            matches.sort(key=lambda x: len(x[0]), reverse=True)
            return matches[0][1]
        return None

    def _mock_run(self, cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        """Replacement for subprocess.run — intercepts ADB calls."""
        cmd_str = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)

        # Only intercept ADB commands
        if "adb" not in cmd_str.lower():
            return self._real_run(cmd, **kwargs)

        # Parse target and args
        m = re.search(r"adb\s+-s\s+(\S+)\s+(.*)", cmd_str)
        if m:
            target = m.group(1)
            adb_args = m.group(2).strip().strip('"').strip("'")
        else:
            # adb without -s (e.g., adb devices, adb connect)
            m2 = re.search(r"adb\s+(.*)", cmd_str)
            target = ""
            adb_args = m2.group(1).strip() if m2 else cmd_str

        # Find matching response
        resp = self._find_response(adb_args)

        if resp and resp.side_effect:
            call = ADBCall(full_cmd=cmd_str, target=target, adb_args=adb_args)
            self._calls.append(call)
            resp.side_effect(cmd_str)

        if resp is None:
            # Default: return empty success for unknown ADB commands
            resp = MockResponse(stdout="", returncode=0)

        result = subprocess.CompletedProcess(
            args=cmd_str,
            returncode=resp.returncode,
            stdout=resp.raw_stdout if kwargs.get("capture_output") and not kwargs.get("text") else resp.stdout,
            stderr=resp.stderr.encode() if kwargs.get("capture_output") and not kwargs.get("text") else resp.stderr,
        )

        call = ADBCall(full_cmd=cmd_str, target=target, adb_args=adb_args, returned=result)
        self._calls.append(call)
        return result

    @contextlib.contextmanager
    def patch(self):
        """Context manager that patches subprocess.run with the mock."""
        with _mock_patch("subprocess.run", side_effect=self._mock_run):
            yield self

    def was_called(self, pattern: str) -> bool:
        """Check if any recorded call matches the given pattern."""
        return any(pattern in c.adb_args or pattern in c.full_cmd for c in self._calls)

    def call_count(self, pattern: str = "") -> int:
        """Count calls matching pattern (empty = all calls)."""
        if not pattern:
            return len(self._calls)
        return sum(1 for c in self._calls if pattern in c.adb_args or pattern in c.full_cmd)

    def get_calls(self, pattern: str = "") -> List[ADBCall]:
        """Get all calls matching pattern."""
        if not pattern:
            return list(self._calls)
        return [c for c in self._calls if pattern in c.adb_args or pattern in c.full_cmd]

    def reset(self) -> None:
        """Clear all recorded calls (keeps registered responses)."""
        self._calls.clear()

    def reset_all(self) -> None:
        """Clear calls and responses."""
        self._calls.clear()
        self._responses.clear()


def patch_adb(**responses: str):
    """Convenience context manager.

    Usage:
        with patch_adb(**{"shell getprop ro.product.model": "SM-S928U"}):
            ...
    """
    mock = MockADB()
    for pattern, stdout in responses.items():
        mock.set_response(pattern, stdout)
    return mock.patch()
