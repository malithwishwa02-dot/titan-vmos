"""
Titan V12.0 — Built-in Device Viewer Router
Serves live device screenshots and forwards touch/key input via ADB.
Eliminates dependency on ws-scrcpy for basic visual device access.

Endpoints:
    GET  /api/viewer/{device_id}/screen    — PNG screenshot
    GET  /api/viewer/{device_id}/screen.jpg — JPEG screenshot (smaller)
    POST /api/viewer/{device_id}/tap        — Send tap at x,y
    POST /api/viewer/{device_id}/key        — Send keyevent
    POST /api/viewer/{device_id}/swipe      — Send swipe gesture
    GET  /api/viewer/{device_id}/           — Interactive HTML viewer
"""

import logging
import subprocess
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

logger = logging.getLogger("titan.viewer")
router = APIRouter(prefix="/api/viewer", tags=["viewer"])


def _get_device_manager():
    from device_manager import DeviceManager
    from server.deps import get_device_manager
    return get_device_manager()


def _adb_target(device_id: str) -> str:
    """Resolve ADB target for a device, or raise 404."""
    mgr = _get_device_manager()
    dev = mgr.get_device(device_id)
    if not dev:
        raise HTTPException(404, f"Device {device_id} not found")
    if dev.state not in ("ready", "patched", "running", "booting"):
        raise HTTPException(409, f"Device {device_id} is in state '{dev.state}'")
    return dev.adb_target


def _screencap_png(adb_target: str) -> Optional[bytes]:
    """Capture device screen as raw PNG bytes via ADB."""
    try:
        proc = subprocess.run(
            ["adb", "-s", adb_target, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0 and len(proc.stdout) > 100:
            return proc.stdout
    except Exception as e:
        logger.warning(f"screencap failed for {adb_target}: {e}")
    return None


def _screencap_jpeg(adb_target: str, quality: int = 70) -> Optional[bytes]:
    """Capture device screen as JPEG bytes (smaller than PNG)."""
    png = _screencap_png(adb_target)
    if not png:
        return None
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        # Half resolution for bandwidth
        img = img.resize((w // 2, h // 2), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except ImportError:
        return png  # Return raw PNG if PIL unavailable
    except Exception:
        return png


def _send_input_async(adb_target: str, cmd: str):
    """Fire-and-forget ADB input command in a background thread."""
    def _do():
        try:
            subprocess.run(
                ["adb", "-s", adb_target, "shell", "input"] + cmd.split(),
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


# ─── Screenshot Endpoints ────────────────────────────────────────────

@router.get("/{device_id}/screen")
async def get_screen_png(device_id: str):
    """Get device screenshot as PNG."""
    target = _adb_target(device_id)
    png = _screencap_png(target)
    if not png:
        raise HTTPException(503, "Screenshot capture failed")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/{device_id}/screen.jpg")
async def get_screen_jpeg(device_id: str, quality: int = Query(70, ge=10, le=100)):
    """Get device screenshot as JPEG (smaller, faster)."""
    target = _adb_target(device_id)
    jpg = _screencap_jpeg(target, quality)
    if not jpg:
        raise HTTPException(503, "Screenshot capture failed")
    media = "image/jpeg" if jpg[:2] == b'\xff\xd8' else "image/png"
    return Response(content=jpg, media_type=media,
                    headers={"Cache-Control": "no-store"})


# ─── Input Endpoints ─────────────────────────────────────────────────

class TapRequest(BaseModel):
    x: int
    y: int


class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = 300


class KeyRequest(BaseModel):
    keycode: str = "KEYCODE_HOME"


@router.post("/{device_id}/tap")
async def send_tap(device_id: str, body: TapRequest):
    """Send tap event at (x, y) coordinates."""
    target = _adb_target(device_id)
    _send_input_async(target, f"tap {body.x} {body.y}")
    return {"ok": True}


@router.post("/{device_id}/key")
async def send_key(device_id: str, body: KeyRequest):
    """Send keyevent (e.g. KEYCODE_HOME, KEYCODE_BACK)."""
    target = _adb_target(device_id)
    _send_input_async(target, f"keyevent {body.keycode}")
    return {"ok": True}


@router.post("/{device_id}/swipe")
async def send_swipe(device_id: str, body: SwipeRequest):
    """Send swipe gesture from (x1,y1) to (x2,y2)."""
    target = _adb_target(device_id)
    _send_input_async(target, f"swipe {body.x1} {body.y1} {body.x2} {body.y2} {body.duration_ms}")
    return {"ok": True}


# ─── Interactive HTML Viewer ──────────────────────────────────────────

@router.get("/{device_id}/", response_class=HTMLResponse)
async def viewer_html(device_id: str):
    """Interactive device viewer with live screenshot refresh and touch input."""
    # Verify device exists
    _adb_target(device_id)

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><title>Titan Device Viewer — {device_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0e17;display:flex;flex-direction:column;align-items:center;height:100vh;font-family:system-ui,-apple-system,sans-serif;overflow:hidden}}
#frame{{position:relative;height:calc(100vh - 60px);margin-top:8px}}
#screen{{height:100%;border-radius:12px;cursor:pointer;image-rendering:auto}}
#bar{{display:flex;gap:8px;padding:8px 0}}
.btn{{background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:6px 18px;border-radius:8px;cursor:pointer;font:13px system-ui;transition:all .15s}}
.btn:hover{{background:#334155;color:#e2e8f0}}
.btn:active{{background:#475569}}
#status{{position:fixed;top:8px;right:12px;color:#22c55e;font:11px monospace;background:#0a0e17cc;padding:4px 10px;border-radius:6px}}
#title{{color:#00d4ff;font-size:13px;font-weight:600;position:fixed;top:8px;left:12px}}
</style></head><body>
<div id="title">Titan V12 — {device_id}</div>
<div id="status">connecting...</div>
<div id="frame">
  <img id="screen" src="/api/viewer/{device_id}/screen.jpg?quality=60" draggable="false"
       onclick="handleClick(event)" oncontextmenu="return false">
</div>
<div id="bar">
  <button class="btn" onclick="sendKey('KEYCODE_BACK')">&#9664; Back</button>
  <button class="btn" onclick="sendKey('KEYCODE_HOME')">&#9679; Home</button>
  <button class="btn" onclick="sendKey('KEYCODE_APP_SWITCH')">&#9744; Recents</button>
  <button class="btn" onclick="sendKey('KEYCODE_WAKEUP')">&#9728; Wake</button>
  <button class="btn" onclick="sendKey('KEYCODE_POWER')">&#9211; Power</button>
</div>
<script>
const img = document.getElementById('screen');
const status = document.getElementById('status');
const BASE = '/api/viewer/{device_id}';
let fps = 0, frames = 0, errCount = 0;
setInterval(() => {{ status.textContent = fps + ' fps'; fps = frames; frames = 0; }}, 1000);

function refresh() {{
  const i = new Image();
  i.onload = () => {{
    img.src = i.src;
    frames++;
    errCount = 0;
    setTimeout(refresh, 200);
  }};
  i.onerror = () => {{
    errCount++;
    status.textContent = 'reconnecting...';
    setTimeout(refresh, Math.min(errCount * 500, 3000));
  }};
  i.src = BASE + '/screen.jpg?quality=60&t=' + Date.now();
}}
refresh();

function handleClick(e) {{
  const rect = img.getBoundingClientRect();
  const natW = img.naturalWidth, natH = img.naturalHeight;
  const scaleX = natW * 2 / rect.width;  // *2 because JPEG is half-res
  const scaleY = natH * 2 / rect.height;
  const x = Math.round((e.clientX - rect.left) * scaleX);
  const y = Math.round((e.clientY - rect.top) * scaleY);
  fetch(BASE + '/tap', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{x, y}})
  }});
}}

function sendKey(k) {{
  fetch(BASE + '/key', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{keycode: k}})
  }});
}}

// Swipe support via drag
let dragStart = null;
img.addEventListener('mousedown', e => {{
  const rect = img.getBoundingClientRect();
  dragStart = {{x: e.clientX - rect.left, y: e.clientY - rect.top, rect}};
}});
img.addEventListener('mouseup', e => {{
  if (!dragStart) return;
  const rect = dragStart.rect;
  const dx = (e.clientX - rect.left) - dragStart.x;
  const dy = (e.clientY - rect.top) - dragStart.y;
  if (Math.abs(dx) > 20 || Math.abs(dy) > 20) {{
    const natW = img.naturalWidth, natH = img.naturalHeight;
    const scaleX = natW * 2 / rect.width;
    const scaleY = natH * 2 / rect.height;
    fetch(BASE + '/swipe', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        x1: Math.round(dragStart.x * scaleX),
        y1: Math.round(dragStart.y * scaleY),
        x2: Math.round((e.clientX - rect.left) * scaleX),
        y2: Math.round((e.clientY - rect.top) * scaleY),
        duration_ms: 300
      }})
    }});
  }}
  dragStart = null;
}});
</script></body></html>"""
