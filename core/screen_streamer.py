"""
Titan V11.3 — High-Performance Screen Streamer
================================================
Replaces slow ADB screencap polling (~2 FPS) with optimized streaming.

Three modes (auto-selected):
  1. SCRCPY   — scrcpy-server H.264 stream (30-60 FPS, lowest latency)
  2. RECORD   — `screenrecord --output-format=h264 -` pipe (15-30 FPS)
  3. FAST_CAP — Optimized screencap with double-buffering (8-12 FPS)

Touch input uses persistent ADB shell to eliminate per-command process
spawn overhead (80ms → <10ms).

Usage:
    streamer = ScreenStreamer(adb_target="127.0.0.1:6520")
    async for frame in streamer.stream_jpeg():
        await websocket.send_bytes(frame)

    # Low-latency touch
    streamer.touch_tap(540, 1200)
    streamer.touch_swipe(540, 1800, 540, 600, 300)
"""

import asyncio
import io
import logging
import os
import struct
import subprocess
import threading
import time
from typing import AsyncIterator, Optional, Tuple

logger = logging.getLogger("titan.screen-streamer")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# JPEG quality for WebSocket frames (lower = faster, smaller)
JPEG_QUALITY = int(os.environ.get("TITAN_STREAM_QUALITY", "55"))
# Max dimension for streamed frames (width or height)
MAX_DIM = int(os.environ.get("TITAN_STREAM_MAX_DIM", "540"))
# Target FPS cap for fast_cap mode
TARGET_FPS = int(os.environ.get("TITAN_STREAM_FPS", "15"))
# Scrcpy server path on host
SCRCPY_SERVER_PATH = os.environ.get(
    "TITAN_SCRCPY_SERVER",
    "/opt/titan/bin/scrcpy-server"
)
# Scrcpy server path on device
SCRCPY_DEVICE_PATH = "/data/local/tmp/scrcpy-server.jar"


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT ADB SHELL — eliminates process-spawn overhead for touch
# ═══════════════════════════════════════════════════════════════════════

class PersistentADBShell:
    """Maintains a long-lived `adb shell` process for low-latency commands.

    Instead of spawning a new process per touch/key (~80ms overhead),
    this pipes commands into a single persistent shell (~5-10ms).
    """

    def __init__(self, adb_target: str):
        self.target = adb_target
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._last_use = 0.0
        self._healthy = False

    def _ensure_alive(self) -> bool:
        """Start or restart the persistent shell if needed."""
        if self._proc and self._proc.poll() is None:
            return True
        try:
            self._proc = subprocess.Popen(
                ["adb", "-s", self.target, "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._healthy = True
            logger.debug(f"Persistent ADB shell started for {self.target}")
            return True
        except Exception as e:
            logger.error(f"Failed to start persistent shell: {e}")
            self._healthy = False
            return False

    def execute(self, cmd: str, timeout: float = 5.0) -> Tuple[bool, str]:
        """Execute a command on the persistent shell.

        Returns (success, output). Uses a sentinel marker to detect
        command completion without closing the shell.
        """
        with self._lock:
            if not self._ensure_alive():
                return False, "shell_dead"

            sentinel = f"__TITAN_{int(time.time() * 1000) & 0xFFFF}__"
            full_cmd = f"{cmd}; echo {sentinel}\n"
            try:
                self._proc.stdin.write(full_cmd.encode())
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._healthy = False
                self._proc = None
                return False, "pipe_broken"

            # Read until sentinel
            output_lines = []
            deadline = time.time() + timeout
            try:
                while time.time() < deadline:
                    # Non-blocking read with select
                    import select
                    ready, _, _ = select.select([self._proc.stdout], [], [], 0.1)
                    if ready:
                        line = self._proc.stdout.readline()
                        if not line:
                            self._healthy = False
                            return False, "shell_closed"
                        decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if sentinel in decoded:
                            break
                        output_lines.append(decoded)
            except Exception as e:
                return False, str(e)

            self._last_use = time.time()
            return True, "\n".join(output_lines)

    def fire_and_forget(self, cmd: str):
        """Send command without waiting for output. Fastest possible path."""
        with self._lock:
            if not self._ensure_alive():
                return
            try:
                self._proc.stdin.write(f"{cmd}\n".encode())
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._healthy = False
                self._proc = None

    def close(self):
        """Terminate the persistent shell."""
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy and self._proc is not None and self._proc.poll() is None


# ═══════════════════════════════════════════════════════════════════════
# SCREEN STREAMER
# ═══════════════════════════════════════════════════════════════════════

class ScreenStreamer:
    """High-performance screen capture and touch input for Android devices."""

    def __init__(self, adb_target: str, screen_width: int = 1080,
                 screen_height: int = 2400):
        self.target = adb_target
        self.sw = screen_width
        self.sh = screen_height
        self._shell = PersistentADBShell(adb_target)
        self._capture_proc: Optional[subprocess.Popen] = None
        self._mode = "fast_cap"  # auto-detected
        self._running = False
        self._frame_buffer: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._frame_event = asyncio.Event()
        self._fps_counter = 0
        self._fps_time = time.time()
        self._actual_fps = 0.0

    # ─── MODE DETECTION ───────────────────────────────────────────────

    def detect_best_mode(self) -> str:
        """Auto-detect the best streaming mode available."""
        # Check for scrcpy-server
        if os.path.isfile(SCRCPY_SERVER_PATH):
            try:
                r = subprocess.run(
                    ["adb", "-s", self.target, "shell",
                     f"ls {SCRCPY_DEVICE_PATH} 2>/dev/null"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and SCRCPY_DEVICE_PATH in r.stdout:
                    self._mode = "scrcpy"
                    logger.info(f"Stream mode: scrcpy (best)")
                    return self._mode
                # Push scrcpy-server to device
                r = subprocess.run(
                    ["adb", "-s", self.target, "push",
                     SCRCPY_SERVER_PATH, SCRCPY_DEVICE_PATH],
                    capture_output=True, timeout=15,
                )
                if r.returncode == 0:
                    self._mode = "scrcpy"
                    logger.info(f"Stream mode: scrcpy (pushed)")
                    return self._mode
            except Exception:
                pass

        # NOTE: screenrecord mode returns raw H.264 frames. console/mobile expects JPEG blobs.
        # To avoid mismatched format (black/blank screen), prefer fast_cap path.
        self._mode = "fast_cap"
        logger.info(f"Stream mode: fast_cap (optimized screencap)")
        return self._mode

    # ─── FAST SCREENCAP (OPTIMIZED) ──────────────────────────────────

    async def _fast_cap_frame(self) -> Optional[bytes]:
        """Capture a single frame using optimized screencap pipeline.

        Optimizations vs original:
          - exec-out (no temp file on device)
          - Aggressive downscale (1080→540 or lower)
          - JPEG quality 55 (vs 70)
          - No intermediate PNG save
          - Timeout reduced to 3s
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", self.target, "exec-out", "screencap", "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)

            if proc.returncode != 0 or len(stdout) < 100:
                return None

            return self._png_to_jpeg(stdout)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.debug(f"fast_cap error: {e}")
            return None

    def _png_to_jpeg(self, png_bytes: bytes) -> bytes:
        """Convert PNG screencap to compact JPEG with downscale."""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(png_bytes))
            img = img.convert("RGB")

            # Aggressive downscale — maintain aspect ratio
            w, h = img.size
            scale = min(MAX_DIM / w, MAX_DIM / h, 1.0)
            if scale < 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.BILINEAR)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=False)
            return buf.getvalue()
        except Exception:
            return png_bytes

    # ─── SCREENRECORD PIPE ────────────────────────────────────────────

    async def _start_screenrecord_pipe(self):
        """Start screenrecord in pipe mode for continuous H.264 stream."""
        self._capture_proc = await asyncio.create_subprocess_exec(
            "adb", "-s", self.target, "shell",
            f"screenrecord --output-format=h264 --size {MAX_DIM}x{int(MAX_DIM * self.sh / self.sw)} --bit-rate 2000000 -",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("screenrecord H.264 pipe started")

    # ─── MAIN STREAM GENERATOR ───────────────────────────────────────

    async def stream_jpeg(self) -> AsyncIterator[bytes]:
        """Async generator yielding JPEG frames as fast as possible.

        Auto-selects the best available capture method.
        """
        self._running = True
        min_interval = 1.0 / TARGET_FPS

        if self._mode == "fast_cap":
            while self._running:
                t0 = time.monotonic()
                frame = await self._fast_cap_frame()
                if frame:
                    self._update_fps()
                    yield frame
                elapsed = time.monotonic() - t0
                # Only sleep if we're ahead of target FPS
                remaining = min_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
                else:
                    # Yield control to event loop even when behind
                    await asyncio.sleep(0)
        else:
            # scrcpy or fallback mode, always generate JPEG frames via fast_cap
            if self._mode != "fast_cap":
                logger.warning(f"Stream mode '{self._mode}' not JPEG-compatible; falling back to fast_cap")
            self._mode = "fast_cap"
            while self._running:
                t0 = time.monotonic()
                frame = await self._fast_cap_frame()
                if frame:
                    self._update_fps()
                    yield frame
                elapsed = time.monotonic() - t0
                remaining = min_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
                else:
                    await asyncio.sleep(0)

    def _update_fps(self):
        """Track actual FPS for diagnostics."""
        self._fps_counter += 1
        now = time.time()
        elapsed = now - self._fps_time
        if elapsed >= 2.0:
            self._actual_fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_time = now
            logger.debug(f"Stream FPS: {self._actual_fps:.1f}")

    def stop(self):
        """Stop streaming and cleanup."""
        self._running = False
        self._stop_capture()
        self._shell.close()

    def _stop_capture(self):
        if self._capture_proc:
            try:
                self._capture_proc.terminate()
                self._capture_proc = None
            except Exception:
                pass

    # ─── LOW-LATENCY TOUCH INPUT ──────────────────────────────────────

    def touch_tap(self, x: int, y: int) -> bool:
        """Tap via persistent shell (~5-10ms vs ~80ms)."""
        ok, _ = self._shell.execute(f"input tap {x} {y}", timeout=2.0)
        return ok

    def touch_swipe(self, x1: int, y1: int, x2: int, y2: int,
                    duration_ms: int = 300) -> bool:
        """Swipe via persistent shell."""
        ok, _ = self._shell.execute(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", timeout=3.0)
        return ok

    def touch_key(self, keycode: str) -> bool:
        """Send keyevent via persistent shell."""
        ok, _ = self._shell.execute(f"input keyevent {keycode}", timeout=2.0)
        return ok

    def touch_text(self, text: str) -> bool:
        """Type text via persistent shell."""
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        ok, _ = self._shell.execute(f"input text '{escaped}'", timeout=5.0)
        return ok

    def touch_long_press(self, x: int, y: int, duration_ms: int = 800) -> bool:
        """Long press via persistent shell."""
        ok, _ = self._shell.execute(
            f"input swipe {x} {y} {x} {y} {duration_ms}", timeout=3.0)
        return ok

    # ─── SENDEVENT (FASTEST — BYPASSES ANDROID INPUT FRAMEWORK) ──────

    def _detect_input_device(self) -> str:
        """Find the touch input device path."""
        ok, out = self._shell.execute(
            "getevent -lp 2>/dev/null | grep -B5 ABS_MT_POSITION | head -1",
            timeout=3.0,
        )
        if ok and "/dev/input/" in out:
            import re
            m = re.search(r'(/dev/input/event\d+)', out)
            if m:
                return m.group(1)
        return "/dev/input/event0"

    def sendevent_tap(self, x: int, y: int) -> bool:
        """Ultra-low-latency tap via direct sendevent (~2-3ms).

        Bypasses Android input framework entirely. Uses the touchscreen
        input device directly via Linux input subsystem.
        """
        dev = self._detect_input_device()
        # ABS_MT_TRACKING_ID, ABS_MT_POSITION_X/Y, BTN_TOUCH, SYN_REPORT
        cmds = (
            f"sendevent {dev} 3 57 0;"      # ABS_MT_TRACKING_ID = 0
            f"sendevent {dev} 3 53 {x};"    # ABS_MT_POSITION_X
            f"sendevent {dev} 3 54 {y};"    # ABS_MT_POSITION_Y
            f"sendevent {dev} 1 330 1;"     # BTN_TOUCH DOWN
            f"sendevent {dev} 0 0 0;"       # SYN_REPORT
            f"sendevent {dev} 3 57 -1;"     # ABS_MT_TRACKING_ID = -1 (release)
            f"sendevent {dev} 1 330 0;"     # BTN_TOUCH UP
            f"sendevent {dev} 0 0 0"        # SYN_REPORT
        )
        self._shell.fire_and_forget(cmds)
        return True

    # ─── DIAGNOSTICS ──────────────────────────────────────────────────

    @property
    def fps(self) -> float:
        return self._actual_fps

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def shell_healthy(self) -> bool:
        return self._shell.is_healthy

    def get_stats(self) -> dict:
        return {
            "mode": self._mode,
            "fps": round(self._actual_fps, 1),
            "running": self._running,
            "shell_healthy": self._shell.is_healthy,
            "target": self.target,
            "max_dim": MAX_DIM,
            "jpeg_quality": JPEG_QUALITY,
            "target_fps": TARGET_FPS,
        }


# ═══════════════════════════════════════════════════════════════════════
# MODULE-LEVEL CACHE — one streamer per device
# ═══════════════════════════════════════════════════════════════════════

_streamers: dict = {}
_streamers_lock = threading.Lock()


def get_streamer(device_id: str, adb_target: str,
                 screen_width: int = 1080, screen_height: int = 2400) -> ScreenStreamer:
    """Get or create a ScreenStreamer for a device (cached)."""
    with _streamers_lock:
        if device_id in _streamers:
            s = _streamers[device_id]
            if s.target == adb_target and s.shell_healthy:
                return s
            # Target changed or shell died — recreate
            s.stop()

        s = ScreenStreamer(adb_target, screen_width, screen_height)
        s.detect_best_mode()
        _streamers[device_id] = s
        return s


def remove_streamer(device_id: str):
    """Stop and remove a cached streamer."""
    with _streamers_lock:
        s = _streamers.pop(device_id, None)
        if s:
            s.stop()
