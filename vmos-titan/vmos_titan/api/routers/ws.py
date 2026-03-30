"""
Titan V12.0 — WebSocket Router (High-Performance)
/ws/* — Screen streaming, touch input, log streaming

Screen streaming uses ScreenStreamer for 8-15+ FPS (vs old 2 FPS).
Touch input uses persistent ADB shell for <10ms latency (vs 80ms).
Bidirectional: client sends JSON touch commands, server sends JPEG frames.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from device_manager import DeviceManager
from screen_streamer import get_streamer, remove_streamer

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("titan.ws")

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.websocket("/ws/screen/{device_id}")
async def ws_screen(websocket: WebSocket, device_id: str):
    """High-performance bidirectional screen + touch WebSocket.

    Server → Client: binary JPEG frames (continuous stream)
    Client → Server: JSON touch commands:
        {"type": "tap", "x": 540, "y": 1200}
        {"type": "swipe", "x1": 540, "y1": 1800, "x2": 540, "y2": 600, "duration": 300}
        {"type": "key", "code": "KEYCODE_BACK"}
        {"type": "text", "value": "hello"}
        {"type": "longpress", "x": 540, "y": 1200, "duration": 800}
    """
    await websocket.accept()
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    streamer = get_streamer(
        device_id, dev.adb_target,
        dev.config.get("screen_width", 1080),
        dev.config.get("screen_height", 2400),
    )

    # Send initial stats
    try:
        await websocket.send_text(json.dumps({
            "type": "stream_info",
            "stats": streamer.get_stats(),
        }))
    except Exception:
        pass

    async def send_frames():
        """Stream JPEG frames to client."""
        try:
            async for frame in streamer.stream_jpeg():
                await websocket.send_bytes(frame)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"WS frame send error: {e}")

    async def recv_touch():
        """Receive and execute touch commands from client."""
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    cmd = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                cmd_type = cmd.get("type", "")
                if cmd_type == "tap":
                    streamer.touch_tap(int(cmd["x"]), int(cmd["y"]))
                elif cmd_type == "swipe":
                    streamer.touch_swipe(
                        int(cmd["x1"]), int(cmd["y1"]),
                        int(cmd["x2"]), int(cmd["y2"]),
                        int(cmd.get("duration", 300)),
                    )
                elif cmd_type == "key":
                    streamer.touch_key(str(cmd["code"]))
                elif cmd_type == "text":
                    streamer.touch_text(str(cmd["value"]))
                elif cmd_type == "longpress":
                    streamer.touch_long_press(
                        int(cmd["x"]), int(cmd["y"]),
                        int(cmd.get("duration", 800)),
                    )
                elif cmd_type == "sendevent_tap":
                    streamer.sendevent_tap(int(cmd["x"]), int(cmd["y"]))
                elif cmd_type == "get_stats":
                    await websocket.send_text(json.dumps({
                        "type": "stream_info",
                        "stats": streamer.get_stats(),
                    }))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"WS touch recv error: {e}")

    # Run frame sending and touch receiving concurrently
    try:
        send_task = asyncio.create_task(send_frames())
        recv_task = asyncio.create_task(recv_touch())
        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception as e:
        logger.warning(f"WS screen session error: {e}")
    finally:
        streamer.stop()


@router.websocket("/ws/logs/{device_id}")
async def ws_logs(websocket: WebSocket, device_id: str):
    """Stream device logcat over WebSocket."""
    await websocket.accept()
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "-s", dev.adb_target, "logcat", "-v", "time",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS logs error: {e}")
    finally:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
