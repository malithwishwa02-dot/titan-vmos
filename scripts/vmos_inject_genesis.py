#!/usr/bin/env python3
"""
vmos_inject_genesis.py
──────────────────────────────────────────────────────────────────────────────
VMOS Pro: Full Genesis pipeline + gallery photo injection WITHOUT ADB push.

WHY ADB push fails on VMOS Cloud:
  • async_adb_cmd only accepts shell strings with a 4 KB body limit
  • adb push is a binary protocol command — not a shell command
  • Files over 4 KB cannot be sent as base64 heredoc chunks at scale
  • Direct upload endpoints (uploadFileV3) also require a public URL

GALLERY INJECTION — two-path strategy:
  PATH A  Local HTTP server + cloudflared / ngrok tunnel
    ├─ Starts python http.server on a random local port
    ├─ If cloudflared is installed: launches `cloudflared tunnel --url`
    │   and obtains a public https URL automatically
    ├─ If ngrok is installed: uses `ngrok http PORT`
    └─ Calls injectPicture API in batches of 10 (VMOS limit)
         ↓ rate-limited: 3 s between batches

  PATH B  On-device wget (zero-infrastructure fallback)
    ├─ Reads gallery_manifest.json for Picsum seed values
    ├─ Batches wget commands on the device to download each seeded image
    ├─ Applies `touch -t` filesystem backdating
    └─ Triggers media scan via am broadcast

GENESIS PIPELINE:
  Wraps VMOSGenesisEngine.run_pipeline() with environment loading.
  If --gallery-only is passed, skips genesis and just runs gallery injection.

Usage
─────
  # Full genesis + gallery injection
  python3 scripts/vmos_inject_genesis.py \\
      --pad ACP250329ACQRPDV \\
      --name "Jordan Hayes" \\
      --email jordan.hayes92@gmail.com \\
      --phone "+13105559812" \\
      --country US \\
      --card 4111111111111111 --exp 08/2029 --cvv 737 \\
      --age-days 365

  # Gallery injection only (genesis already ran)
  python3 scripts/vmos_inject_genesis.py \\
      --pad ACP250329ACQRPDV \\
      --gallery-only \\
      --gallery-dir /opt/titan/data/forge_gallery

  # Force on-device wget path (skip tunnel detection)
  python3 scripts/vmos_inject_genesis.py \\
      --pad ACP250329ACQRPDV \\
      --gallery-only \\
      --gallery-method wget
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── PYTHONPATH bootstrap ──────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
for _p in [str(_REPO / "core"), str(_REPO / "server")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── env loading ───────────────────────────────────────────────────────────────
_ENV_PATHS = [
    Path("/opt/titan-v13-device/.env"),
    _REPO / ".env",
    Path("/opt/titan/data/.env"),
]
for _env in _ENV_PATHS:
    if _env.exists():
        with open(_env) as _fh:
            for _line in _fh:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    k, _, v = _line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


# ── constants ─────────────────────────────────────────────────────────────────
DEFAULT_GALLERY_DIR  = Path("/opt/titan/data/forge_gallery")
BATCH_SIZE_INJECT    = 5    # injectPicture calls per batch
BATCH_DELAY_S        = 4.0  # seconds between inject batches (VMOS rate limit)
WGET_CHUNK_SIZE      = 15   # wget commands per async_adb_cmd call
WGET_CMD_DELAY_S     = 4.0  # seconds between wget batches (ADB pipeline safety)
PICSUM_BASE          = "https://picsum.photos/seed/{seed}/{w}/{h}"
DEFAULT_IMG_WIDTH    = 1920
DEFAULT_IMG_HEIGHT   = 1440
TUNNEL_WAIT_S        = 8    # seconds to wait for tunnel URL to appear in stdout


# ══════════════════════════════════════════════════════════════════════════════
# Tunnel helpers
# ══════════════════════════════════════════════════════════════════════════════

def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@contextmanager
def _local_http_server(directory: Path):
    """Start an HTTP server in `directory`, yield the port."""
    port = _find_free_port()
    os.chdir(directory)

    class _Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args): pass  # silence
        def log_error(self, fmt, *args): pass

    srv = HTTPServer(("", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()


def _launch_cloudflared(port: int, timeout: float = TUNNEL_WAIT_S) -> Optional[str]:
    """Launch cloudflared quick tunnel, return public URL or None."""
    if not shutil.which("cloudflared"):
        return None
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + timeout
    url = None
    while time.time() < deadline and proc.poll() is None:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        # cloudflared prints: https://xxxx.trycloudflare.com
        match = re.search(r"(https://[a-z0-9\-]+\.trycloudflare\.com)", line)
        if match:
            url = match.group(1)
            break
    if url:
        return url
    proc.terminate()
    return None


def _launch_ngrok(port: int, timeout: float = TUNNEL_WAIT_S) -> Optional[str]:
    """Launch ngrok tunnel, return public URL or None."""
    if not shutil.which("ngrok"):
        return None
    proc = subprocess.Popen(
        ["ngrok", "http", str(port), "--log=stdout", "--log-format=json"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline and proc.poll() is None:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        try:
            data = json.loads(line)
            if data.get("msg") == "started tunnel":
                url = data.get("url", "")
                if url.startswith("https://"):
                    return url
        except json.JSONDecodeError:
            pass
    proc.terminate()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# VMOS async_adb_cmd helper (polls task until done)
# ══════════════════════════════════════════════════════════════════════════════

async def _sh(client, pad: str, cmd: str, wait: float = 8.0,
              retries: int = 3) -> str:
    """Run a shell command on the VMOS device and return stdout."""
    for attempt in range(1, retries + 1):
        try:
            r = await client.async_adb_cmd([pad], cmd)
            if r.get("code") != 200:
                if attempt < retries:
                    await asyncio.sleep(5)
                    continue
                return ""
            task_id = r["data"][0]["taskId"]
            await asyncio.sleep(wait)
            d = await client.task_detail([task_id])
            if d.get("code") == 200:
                return d["data"][0].get("taskResult", "") or ""
            return ""
        except Exception:
            if attempt < retries:
                await asyncio.sleep(5)
    return ""


async def _sh_ok(client, pad: str, cmd: str, marker: str,
                 wait: float = 8.0) -> bool:
    result = await _sh(client, pad, cmd, wait=wait)
    return marker in result


# ══════════════════════════════════════════════════════════════════════════════
# Gallery injection — PATH A: tunnel + injectPicture
# ══════════════════════════════════════════════════════════════════════════════

async def inject_gallery_via_tunnel(
    client,
    pad: str,
    gallery_dir: Path,
    manifest: dict,
    log,
) -> int:
    """
    Serve EXIF-stamped JPEGs locally, expose via cloudflared/ngrok tunnel,
    inject via VMOS injectPicture API.
    Returns count of successfully injected photos.
    """
    photos = manifest.get("photos", [])
    if not photos:
        log("  Gallery-A: manifest has no photos")
        return 0

    with _local_http_server(gallery_dir) as port:
        log(f"  Gallery-A: HTTP server on port {port}, looking for tunnel...")

        base_url: Optional[str] = None
        tunnel_proc: Optional[subprocess.Popen] = None

        # Try cloudflared first, then ngrok
        base_url = _launch_cloudflared(port)
        if base_url:
            log(f"  Gallery-A: cloudflared tunnel → {base_url}")
        else:
            base_url = _launch_ngrok(port)
            if base_url:
                log(f"  Gallery-A: ngrok tunnel → {base_url}")

        if not base_url:
            log("  Gallery-A: no tunnel available (cloudflared/ngrok not found)")
            return 0

        injected = 0
        total    = len(photos)

        for i in range(0, total, BATCH_SIZE_INJECT):
            batch = photos[i : i + BATCH_SIZE_INJECT]
            for entry in batch:
                fname    = entry["filename"]
                img_url  = f"{base_url}/{fname}"
                try:
                    resp = await client.inject_picture([pad], img_url)
                    if resp.get("code") == 200:
                        injected += 1
                    else:
                        code = resp.get("code")
                        log(f"  Gallery-A: injectPicture failed for {fname}: code={code}")
                except Exception as exc:
                    log(f"  Gallery-A: error on {fname}: {exc}")

            pct = min(i + BATCH_SIZE_INJECT, total) / total * 100
            log(f"  Gallery-A: {min(i+BATCH_SIZE_INJECT, total)}/{total} ({pct:.0f}%)")

            if i + BATCH_SIZE_INJECT < total:
                await asyncio.sleep(BATCH_DELAY_S)  # rate limit

        log(f"  Gallery-A: {injected}/{total} photos injected via injectPicture")
        return injected


# ══════════════════════════════════════════════════════════════════════════════
# Gallery injection — PATH B: on-device wget from Picsum seeds
# ══════════════════════════════════════════════════════════════════════════════

async def inject_gallery_via_wget(
    client,
    pad: str,
    manifest: dict,
    log,
    img_w: int = DEFAULT_IMG_WIDTH,
    img_h: int = DEFAULT_IMG_HEIGHT,
) -> int:
    """
    Have the device shell wget each photo from Picsum using the seed recorded
    in gallery_manifest.json, then backdate filesystem timestamps.

    EXIF metadata not preserved (plain Picsum JPEG), but the gallery is
    populated with real photos at correct timestamps — sufficient for trust
    scoring and forensic gallery age checks.
    """
    photos = manifest.get("photos", [])
    if not photos:
        log("  Gallery-B: manifest has no photos — generating wget list from seed pool")
        # If manifest is empty, synthesise 50 entries
        photos = [
            {
                "filename": f"IMG_{time.strftime('%Y%m%d_%H%M%S', time.gmtime(time.time() - i * 86400))}.jpg",
                "timestamp": int(time.time()) - i * 86400,
                "seed": (i % 1084) + 1,
            }
            for i in range(50)
        ]

    # Ensure DCIM dir exists
    mkdir_ok = await _sh_ok(
        client, pad,
        "mkdir -p /sdcard/DCIM/Camera && echo DIR_OK",
        "DIR_OK", wait=6,
    )
    if not mkdir_ok:
        log("  Gallery-B: failed to create DCIM/Camera dir")
        return 0

    # Check if wget or curl is available
    wget_bin = ""
    for bin_ in ["wget", "curl"]:
        check = await _sh(client, pad, f"which {bin_} 2>/dev/null && echo {bin_.upper()}_OK", wait=5)
        if f"{bin_.upper()}_OK" in check:
            wget_bin = bin_
            break
    if not wget_bin:
        log("  Gallery-B: neither wget nor curl found on device")
        return 0
    log(f"  Gallery-B: using {wget_bin} for on-device download")

    injected = 0
    total    = len(photos)

    # Process in chunks to stay within ADB command spacing rules
    for chunk_start in range(0, total, WGET_CHUNK_SIZE):
        chunk = photos[chunk_start : chunk_start + WGET_CHUNK_SIZE]

        cmds: list[str] = []
        for entry in chunk:
            fname = entry["filename"]
            seed  = entry.get("seed", (chunk_start % 1084) + 1)
            ts    = entry.get("timestamp", int(time.time()))
            url   = PICSUM_BASE.format(seed=seed, w=img_w, h=img_h)
            dest  = f"/sdcard/DCIM/Camera/{fname}"
            touch = time.strftime("%Y%m%d%H%M.%S", time.gmtime(ts))

            if wget_bin == "wget":
                dl_cmd = f"wget -q -O '{dest}' '{url}' 2>/dev/null"
            else:
                dl_cmd = f"curl -sL -o '{dest}' '{url}' 2>/dev/null"

            cmds.append(f"{dl_cmd} && touch -t {touch} '{dest}' 2>/dev/null")

        # Join with & (background each download), wait at end
        shell_script = (
            " & ".join(cmds)
            + f" & wait && echo CHUNK_{chunk_start}_DONE"
        )
        result = await _sh(client, pad, shell_script, wait=max(8.0, len(chunk) * 2.0))
        done_marker = f"CHUNK_{chunk_start}_DONE"
        if done_marker in result:
            injected += len(chunk)

        pct = min(chunk_start + WGET_CHUNK_SIZE, total) / total * 100
        log(f"  Gallery-B: {min(chunk_start + WGET_CHUNK_SIZE, total)}/{total} ({pct:.0f}%)")

        if chunk_start + WGET_CHUNK_SIZE < total:
            await asyncio.sleep(WGET_CMD_DELAY_S)

    # Trigger media scan + restorecon
    await _sh(
        client, pad,
        "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
        "-d file:///sdcard/DCIM/Camera/ 2>/dev/null; "
        "restorecon -R /sdcard/DCIM/Camera/ 2>/dev/null; "
        "echo SCAN_DONE",
        wait=6,
    )

    log(f"  Gallery-B: {injected}/{total} photos downloaded + backdated")
    return injected


# ══════════════════════════════════════════════════════════════════════════════
# Gallery bootstrap (load or generate manifest)
# ══════════════════════════════════════════════════════════════════════════════

def _load_or_build_manifest(
    gallery_dir: Path,
    count: int = 565,
    age_days: int = 365,
    city: str = "new_york",
) -> dict:
    """
    Load existing gallery_manifest.json, or synthesise a minimal manifest
    by calling forge_gallery_downloader with --no-download (synthetic JPEGs).
    """
    manifest_path = gallery_dir / "gallery_manifest.json"

    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        print(f"  Manifest loaded: {data.get('count', '?')} photos, "
              f"camera={data.get('camera', '?')}, city={data.get('city', '?')}")
        return data

    # Run forge_gallery_downloader.py to build a manifest (synthetic = fast)
    print(f"  No manifest found — running forge_gallery_downloader "
          f"(synthetic, {count} photos)...")
    gallery_dir.mkdir(parents=True, exist_ok=True)
    script = _REPO / "scripts" / "forge_gallery_downloader.py"
    if not script.exists():
        print("  WARNING: forge_gallery_downloader.py not found, using stub manifest")
        # Return a minimal stub so wget path can still work with Picsum seeds
        photos = [
            {
                "filename": (
                    time.strftime(
                        "IMG_%Y%m%d_%H%M%S.jpg",
                        time.gmtime(int(time.time()) - i * 86400),
                    )
                ),
                "timestamp": int(time.time()) - i * 86400,
                "seed": (i % 1084) + 1,
            }
            for i in range(count)
        ]
        stub = {
            "count": count, "camera": "samsung", "age_days": age_days,
            "city": city, "photos": photos, "failures": [],
        }
        manifest_path.write_text(json.dumps(stub, indent=2))
        return stub

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{_REPO / 'core'}:{_REPO / 'server'}"
    result = subprocess.run(
        [
            sys.executable, str(script),
            "--count", str(count),
            "--age-days", str(age_days),
            "--city", city,
            "--no-download",
            "--output-dir", str(gallery_dir),
        ],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        print(f"  WARNING: forge_gallery_downloader failed:\n{result.stderr[:400]}")

    if manifest_path.exists():
        return json.loads(manifest_path.read_text())

    return {"photos": [], "failures": []}


# ══════════════════════════════════════════════════════════════════════════════
# Main gallery injection orchestrator
# ══════════════════════════════════════════════════════════════════════════════

async def run_gallery_injection(
    client,
    pad: str,
    gallery_dir: Path,
    method: str = "auto",       # "auto" | "tunnel" | "wget"
    count: int = 565,
    age_days: int = 365,
    city: str = "new_york",
    log=print,
) -> int:
    """
    Full gallery injection — tries PATH A (tunnel) then PATH B (wget).
    Returns number of photos successfully injected.
    """
    manifest = _load_or_build_manifest(gallery_dir, count=count,
                                        age_days=age_days, city=city)
    photos = manifest.get("photos", [])
    if not photos:
        log("  Gallery: manifest empty after load/build — cannot inject")
        return 0

    log(f"\n{'━'*50}")
    log(f"  Gallery Injection  ({len(photos)} photos, method={method})")
    log(f"{'━'*50}")

    injected = 0

    if method in ("auto", "tunnel"):
        log("  Attempting PATH A: local HTTP server + cloudflared/ngrok tunnel")
        injected = await inject_gallery_via_tunnel(client, pad, gallery_dir, manifest, log)

    if injected == 0 and method in ("auto", "wget"):
        log("  Attempting PATH B: on-device wget from Picsum seeds")
        injected = await inject_gallery_via_wget(client, pad, manifest, log)

    if injected == 0:
        log("  WARNING: gallery injection failed on both paths")
    else:
        log(f"  Gallery injection complete: {injected}/{len(photos)} photos")

    return injected


# ══════════════════════════════════════════════════════════════════════════════
# Genesis pipeline runner
# ══════════════════════════════════════════════════════════════════════════════

async def run_full_pipeline(args: argparse.Namespace) -> None:
    """Run genesis pipeline + gallery injection for the given pad code."""
    from vmos_cloud_api import VMOSCloudClient
    from vmos_genesis_engine import VMOSGenesisEngine, PipelineConfig

    log = lambda msg: print(f"[{time.strftime('%H:%M:%S')}] {msg}")

    client = VMOSCloudClient()
    pad    = args.pad
    engine = VMOSGenesisEngine(pad, client=client)

    # ── 1. Verify device is running ─────────────────────────────────────────
    log(f"Checking {pad} status...")
    status_resp = await client.instance_list(rows=200)
    pad_status = None
    if status_resp.get("code") == 200:
        for inst in (status_resp.get("data") or {}).get("rows", []):
            if inst.get("padCode") == pad:
                pad_status = inst.get("padStatus")
                break

    if pad_status != 10:
        log(f"WARNING: {pad} status={pad_status} (need 10/Running). "
            f"Attempting restart...")
        await client.instance_restart([pad])
        log("Waiting 30s for device to come back up...")
        await asyncio.sleep(30)
        for _ in range(10):
            r = await client.instance_list(rows=200)
            if r.get("code") == 200:
                for inst in (r.get("data") or {}).get("rows", []):
                    if inst.get("padCode") == pad:
                        if inst.get("padStatus") == 10:
                            log("Device is Running (10) — proceeding")
                            break
                else:
                    await asyncio.sleep(5)
                    continue
                break
        else:
            log("ERROR: Device did not reach Running status after restart")
            sys.exit(1)
    else:
        log(f"Device status: Running (10) — OK")

    # ── 2. Build PipelineConfig from CLI args ────────────────────────────────
    cfg = PipelineConfig(
        name         = args.name or "Alex Morgan",
        email        = args.email or "",
        google_email = args.email or "",
        phone        = args.phone or "+12125551001",
        country      = args.country.upper(),
        cc_number    = (args.card or "").replace(" ", "").replace("-", ""),
        cc_exp       = args.exp or "",
        cc_cvv       = args.cvv or "",
        cc_holder    = args.name or "",
        device_model = args.device or "samsung_s24",
        carrier      = args.carrier or "tmobile_us",
        location     = args.location or "la",
        age_days     = args.age_days,
        proxy_url    = args.proxy or "",
        skip_wipe    = args.skip_wipe,
        skip_patch   = args.skip_patch,
    )

    # ── 3. Run genesis pipeline (phases 0–10) ────────────────────────────────
    if not args.gallery_only:
        log(f"\n{'═'*60}")
        log(f"  VMOS Genesis Pipeline — {pad}")
        log(f"  Identity: {cfg.name} / {cfg.email}")
        log(f"  Device: {cfg.device_model} | Age: {cfg.age_days}d | Country: {cfg.country}")
        log(f"{'═'*60}\n")

        result = await engine.run_pipeline(cfg)
        log(f"\nGenesis complete: trust={result.trust_score}/100 ({result.grade})")
        log(f"Profile: {result.profile_id}")
        for ph in result.phases:
            status_icon = {"done": "✓", "failed": "✗", "warn": "⚠", "skipped": "·"}.get(
                ph.status, "?"
            )
            log(f"  {status_icon} Phase {ph.phase:2d} {ph.name:20s} [{ph.status}] {ph.notes[:60]}")

    # ── 4. Gallery injection ──────────────────────────────────────────────────
    gallery_dir = Path(args.gallery_dir) if args.gallery_dir else DEFAULT_GALLERY_DIR

    log(f"\n{'═'*60}")
    log(f"  Gallery Injection — {pad}")
    log(f"  Source:  {gallery_dir}")
    log(f"  Method:  {args.gallery_method}")
    log(f"  Count:   {args.gallery_count}")
    log(f"{'═'*60}")

    injected = await run_gallery_injection(
        client      = client,
        pad         = pad,
        gallery_dir = gallery_dir,
        method      = args.gallery_method,
        count       = args.gallery_count,
        age_days    = args.age_days,
        city        = args.city,
        log         = log,
    )

    # ── 5. Final trust audit (optional re-check after gallery) ───────────────
    if injected > 0 and not args.gallery_only:
        log("\nRe-running trust audit after gallery injection...")
        await asyncio.sleep(4)
        try:
            audit_cmd = (
                "echo PHOTOS=$(ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l); "
                "echo SCAN=$(am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                "-d file:///sdcard/DCIM/Camera/ 2>/dev/null | grep -c 'Broadcast completed' || echo 0)"
            )
            audit = await _sh(client, pad, audit_cmd, wait=8)
            for line in audit.strip().split("\n"):
                if "=" in line:
                    log(f"  {line.strip()}")
        except Exception as e:
            log(f"  Audit warning: {e}")

    # ── 6. Summary ────────────────────────────────────────────────────────────
    log(f"\n{'━'*60}")
    log(f"  DONE — {pad}")
    if not args.gallery_only:
        log(f"  Trust score : {result.trust_score}/100 ({result.grade})")
        log(f"  Profile ID  : {result.profile_id}")
    log(f"  Gallery     : {injected} photos injected")
    log(f"{'━'*60}\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="VMOS Pro: genesis + gallery injection (no ADB push)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Required ──────────────────────────────────────────────────────────────
    p.add_argument("--pad", required=True,
                   help="VMOS Cloud pad code (e.g. ACP250329ACQRPDV)")

    # ── Mode ──────────────────────────────────────────────────────────────────
    p.add_argument("--gallery-only", action="store_true",
                   help="Skip genesis pipeline, only inject gallery")

    # ── Identity ─────────────────────────────────────────────────────────────
    p.add_argument("--name",    default="Alex Morgan",       help="Full name")
    p.add_argument("--email",   default="",                  help="Gmail address")
    p.add_argument("--phone",   default="+12125551001",      help="E.164 phone")
    p.add_argument("--country", default="US",               help="ISO country code")
    p.add_argument("--city",    default="new_york",
                   choices=["new_york","los_angeles","chicago","miami","houston",
                            "london","paris","berlin","toronto","sydney","dubai",
                            "singapore","tokyo","amsterdam","madrid"],
                   help="Home city for GPS/gallery GPS anchor")
    p.add_argument("--age-days",type=int, default=365, help="Profile age in days")

    # ── Card ────────────────────────────────────────────────────────────────
    p.add_argument("--card",    default="", help="Credit card number (no spaces)")
    p.add_argument("--exp",     default="", help="Expiry MM/YYYY")
    p.add_argument("--cvv",     default="", help="CVV")

    # ── Device / network ─────────────────────────────────────────────────────
    p.add_argument("--device",  default="samsung_s24", help="Device preset key")
    p.add_argument("--carrier", default="tmobile_us",  help="Carrier preset key")
    p.add_argument("--location",default="la",          help="Location preset key")
    p.add_argument("--proxy",   default="",
                   help="Proxy URL: socks5://user:pass@host:port or http://host:port")

    # ── Genesis options ──────────────────────────────────────────────────────
    p.add_argument("--skip-wipe",  action="store_true", help="Skip phase 0 (wipe)")
    p.add_argument("--skip-patch", action="store_true", help="Skip phase 1 (stealth)")

    # ── Gallery options ──────────────────────────────────────────────────────
    p.add_argument("--gallery-dir",    default=str(DEFAULT_GALLERY_DIR),
                   help="Directory containing gallery_manifest.json + JPEGs")
    p.add_argument("--gallery-count",  type=int, default=565,
                   help="Number of photos to inject (used if building manifest)")
    p.add_argument("--gallery-method", default="auto",
                   choices=["auto", "tunnel", "wget"],
                   help="auto=try tunnel then wget | tunnel=force PATH A | wget=force PATH B")

    return p.parse_args()


if __name__ == "__main__":
    args = _parse()

    # Print banner
    print(f"\n{'━'*64}")
    print(f"  VMOS Inject + Genesis  v1.0")
    print(f"  Pad: {args.pad}  |  Mode: {'gallery-only' if args.gallery_only else 'full'}")
    print(f"{'━'*64}\n")

    # Check API keys
    if not os.environ.get("VMOS_CLOUD_AK") or not os.environ.get("VMOS_CLOUD_SK"):
        print("ERROR: VMOS_CLOUD_AK / VMOS_CLOUD_SK not set.")
        print("Load them first:  set -a && source .env && set +a")
        sys.exit(1)

    try:
        asyncio.run(run_full_pipeline(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
