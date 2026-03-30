#!/usr/bin/env python3
"""
forge_gallery_downloader.py
────────────────────────────
Download and EXIF-stamp 565 mobile-camera-style photos for device gallery
injection.  Replaces the piexif-dependent download_camera_photos.py with a
zero-extra-library implementation (only requests + Pillow, already in
requirements.txt).  EXIF is built with pure struct — same approach as
profile_injector._build_exif_jpeg() but with a richer field set.

Source   : Picsum Photos (https://picsum.photos) — free, no auth, seed-stable
EXIF     : DateTimeOriginal · GPS (lat/lon/altitude/datum)
           Make / Model / Software · Orientation
           ExposureTime · FNumber · ISO · FocalLength
           PixelXDimension / PixelYDimension (read from actual JPEG)
Naming   : Samsung/OnePlus → IMG_YYYYMMDD_HHMMSS.jpg
           Pixel  → PXL_YYYYMMDD_HHMMSSSS.jpg
           iPhone → IMG_NNNN.jpg
Output   : /opt/titan/data/forge_gallery/  (or --output-dir)
Manifest : <output_dir>/gallery_manifest.json  (consumed by profile_injector)

Usage
─────
  # Defaults: 565 photos, NYC, Samsung, 365 days, 12 workers
  python3 scripts/forge_gallery_downloader.py

  # Full control
  python3 scripts/forge_gallery_downloader.py \\
      --count 565 --age-days 365 --city london --model samsung \\
      --workers 16 --output-dir /opt/titan/data/forge_gallery

  # Custom GPS (overrides --city)
  python3 scripts/forge_gallery_downloader.py --lat 33.9249 --lon -118.3350

  # Synthetic mode: generate without downloading (fast, no network)
  python3 scripts/forge_gallery_downloader.py --no-download
"""

from __future__ import annotations

import argparse
import json
import os
import random
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

# ── device profiles ────────────────────────────────────────────────────────────

DEVICE_PROFILES: dict[str, dict] = {
    "samsung": {
        "makes":    ["samsung"],
        "models":   ["SM-S928B", "SM-S918B", "SM-S908B", "SM-A546B", "SM-A346B"],
        "software": ["samsung/KBOX S928B1 a54", "samsung/KBOX S918B1 a52", "samsung/KBOX S908B1 a53"],
        "focal_n":  [24, 24, 13, 230, 130],   # focal mm ×10 numerators
        "focal_d":  [10, 10, 10, 10, 10],
        "fnum_n":   [18, 22, 24, 35],          # f-stop ×10 numerators
        "fnum_d":   [10, 10, 10, 10],
        "iso":      [50, 64, 100, 125, 200, 400, 800, 1600],
        "exp_d":    [60, 100, 120, 250, 500, 1000, 2000],
        "dims":     [(4032, 3024), (8064, 6048)],
        "fmt":      "samsung",   # IMG_YYYYMMDD_HHMMSS.jpg
    },
    "pixel": {
        "makes":    ["Google"],
        "models":   ["Pixel 7 Pro", "Pixel 8 Pro", "Pixel 8", "Pixel 7"],
        "software": [
            "google/cheetah/cheetah:14/UP1A.231105.003",
            "google/shiba/shiba:14/UP1A.231105.004",
        ],
        "focal_n":  [25, 50, 120],
        "focal_d":  [10, 10, 10],
        "fnum_n":   [18, 21, 24],
        "fnum_d":   [10, 10, 10],
        "iso":      [50, 64, 100, 200, 400, 800, 1600],
        "exp_d":    [60, 120, 250, 500, 1000],
        "dims":     [(4080, 3072), (8160, 6144)],
        "fmt":      "pixel",     # PXL_YYYYMMDD_HHMMSSSS.jpg
    },
    "oneplus": {
        "makes":    ["OnePlus"],
        "models":   ["CPH2651", "PHK110", "CPH2609", "PJZ110"],
        "software": [
            "OnePlus/CPH2651GL/OP5956L1:14/UP1A.231005.007",
            "OnePlus/PHK110/OP5913L1:14/UP1A.231005.007",
        ],
        "focal_n":  [24, 50, 160],
        "focal_d":  [10, 10, 10],
        "fnum_n":   [18, 24, 35],
        "fnum_d":   [10, 10, 10],
        "iso":      [64, 100, 200, 400, 800],
        "exp_d":    [60, 100, 250, 500, 1000],
        "dims":     [(4032, 3024), (8064, 6048)],
        "fmt":      "samsung",
    },
    "iphone": {
        "makes":    ["Apple"],
        "models":   ["iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 14 Pro Max", "iPhone 14 Pro"],
        "software": ["17.2.1", "17.3.1", "17.4"],
        "focal_n":  [24, 28, 48, 120, 150],
        "focal_d":  [10, 10, 10, 10, 10],
        "fnum_n":   [18, 200, 28, 280],
        "fnum_d":   [10, 100, 10, 100],
        "iso":      [32, 50, 64, 100, 200, 400, 800, 1600],
        "exp_d":    [60, 100, 120, 250, 500, 1000, 2000],
        "dims":     [(4032, 3024), (4096, 3072)],
        "fmt":      "iphone",    # IMG_NNNN.jpg
    },
}

# ── city GPS anchors ─────────────────────────────────────────────────────────

CITY_LOCATIONS: dict[str, tuple[float, float]] = {
    "new_york":     (40.7128, -74.0060),
    "los_angeles":  (34.0522, -118.2437),
    "chicago":      (41.8781, -87.6298),
    "houston":      (29.7604, -95.3698),
    "miami":        (25.7617, -80.1918),
    "london":       (51.5074, -0.1278),
    "paris":        (48.8566,  2.3522),
    "berlin":       (52.5200, 13.4050),
    "toronto":      (43.6532, -79.3832),
    "sydney":       (-33.8688, 151.2093),
    "dubai":        (25.2048,  55.2708),
    "singapore":    (1.3521,  103.8198),
    "tokyo":        (35.6762,  139.6503),
    "amsterdam":    (52.3676,   4.9041),
    "madrid":       (40.4168,  -3.7038),
}

# Picsum Photos seed pool (1–1084 unique photos in their library)
_PICSUM_POOL = list(range(1, 1085))

# ── EXIF builder (pure struct, no piexif) ─────────────────────────────────────

def _build_exif_app1(
    ts: float,
    lat: float,
    lon: float,
    make: str,
    model: str,
    software: str,
    focal_n: int,
    focal_d: int,
    fnum_n: int,
    fnum_d: int,
    iso: int,
    px_w: int,
    px_h: int,
    exp_n: int = 1,
    exp_d: int = 120,
    altitude_m: int = 35,
) -> bytes:
    """Build a complete EXIF APP1 segment (big-endian Motorola TIFF).

    IFD layout (offsets relative to TIFF header start = 0):
      TIFF header  : 8 bytes          offset 0
      IFD0         : 7 entries → 90  offset 8
      ExifIFD      : 8 entries → 102  offset 98
      GPSIFD       : 6 entries → 78   offset 200
      Data area    :                   offset 278+
    """
    S = struct

    # ── string data ─────────────────────────────────────────────────────────
    dt_str = time.strftime("%Y:%m:%d %H:%M:%S", time.gmtime(ts))
    make_b  = make.encode("ascii")    + b"\x00"
    model_b = model.encode("ascii")   + b"\x00"
    soft_b  = software.encode("ascii") + b"\x00"
    dt_b    = dt_str.encode("ascii")  + b"\x00"   # always 20 bytes

    # ── GPS encoding ─────────────────────────────────────────────────────────
    lat_ref = b"N\x00" if lat >= 0 else b"S\x00"
    lon_ref = b"E\x00" if lon >= 0 else b"W\x00"
    abs_lat, abs_lon = abs(lat), abs(lon)

    def _deg_rat(deg: float) -> bytes:
        d  = int(deg)
        m  = int((deg - d) * 60)
        sv = int(((deg - d) * 60 - m) * 60 * 10000)
        return S.pack(">IIIIII", d, 1, m, 1, sv, 10000)

    lat_rat = _deg_rat(abs_lat)   # 24 bytes
    lon_rat = _deg_rat(abs_lon)   # 24 bytes

    # ── fixed IFD offsets (derived from entry counts) ─────────────────────
    IFD0_N   = 7
    EXIF_N   = 8
    GPS_N    = 6

    IFD0_OFF = 8
    EXIF_OFF = IFD0_OFF + 2 + IFD0_N  * 12 + 4   # = 98
    GPS_OFF  = EXIF_OFF + 2 + EXIF_N  * 12 + 4   # = 200
    DATA_OFF = GPS_OFF  + 2 + GPS_N   * 12 + 4   # = 278

    # ── data area accumulator ────────────────────────────────────────────────
    data: bytearray = bytearray()

    def _add(raw: bytes) -> int:
        """Append raw bytes (word-padded) and return absolute TIFF offset."""
        off = DATA_OFF + len(data)
        data.extend(raw)
        if len(raw) % 2:
            data.append(0)
        return off

    make_off    = _add(make_b)
    model_off   = _add(model_b)
    soft_off    = _add(soft_b)
    dt_off      = _add(dt_b)
    lat_off     = _add(lat_rat)
    lon_off     = _add(lon_rat)
    datum_off   = _add(b"WGS-84\x00")   # 7 bytes → padded to 8
    alt_off     = _add(S.pack(">II", abs(altitude_m), 1))
    exp_off     = _add(S.pack(">II", exp_n, exp_d))
    fnum_off    = _add(S.pack(">II", fnum_n, fnum_d))
    focal_off   = _add(S.pack(">II", focal_n, focal_d))

    # ── IFD entry helper ─────────────────────────────────────────────────────
    def _e(tag: int, typ: int, count: int, val: int) -> bytes:
        return S.pack(">HHII", tag, typ, count, val)

    ASCII    = 2
    SHORT    = 3
    LONG     = 4
    RATIONAL = 5
    BYTE     = 1

    def _sh(v: int) -> int:
        """Encode a SHORT value inline (left-align in 4-byte big-endian field)."""
        return v << 16

    def _ascii_inline(b: bytes) -> int:
        """Encode ≤4-byte ASCII string inline (left-align)."""
        padded = (b + b"\x00\x00\x00\x00")[:4]
        return int.from_bytes(padded, "big")

    # ── IFD0 (sorted by tag) ─────────────────────────────────────────────────
    ifd0  = S.pack(">H", IFD0_N)
    ifd0 += _e(0x010F, ASCII,    len(make_b),  make_off)          # Make
    ifd0 += _e(0x0110, ASCII,    len(model_b), model_off)         # Model
    ifd0 += _e(0x0112, SHORT,    1, _sh(1))                       # Orientation = normal
    ifd0 += _e(0x0131, ASCII,    len(soft_b),  soft_off)          # Software
    ifd0 += _e(0x0132, ASCII,    len(dt_b),    dt_off)            # DateTime
    ifd0 += _e(0x8769, LONG,     1, EXIF_OFF)                     # ExifIFD pointer
    ifd0 += _e(0x8825, LONG,     1, GPS_OFF)                      # GPSIFD pointer
    ifd0 += S.pack(">I", 0)                                        # no more IFDs

    # ── ExifIFD (sorted by tag) ──────────────────────────────────────────────
    exif  = S.pack(">H", EXIF_N)
    exif += _e(0x829A, RATIONAL, 1, exp_off)                      # ExposureTime
    exif += _e(0x829D, RATIONAL, 1, fnum_off)                     # FNumber
    exif += _e(0x8827, SHORT,    1, _sh(iso))                     # ISOSpeedRatings
    exif += _e(0x9003, ASCII,    len(dt_b), dt_off)               # DateTimeOriginal
    exif += _e(0x9004, ASCII,    len(dt_b), dt_off)               # DateTimeDigitized
    exif += _e(0x920A, RATIONAL, 1, focal_off)                    # FocalLength
    exif += _e(0xA002, SHORT,    1, _sh(px_w))                    # PixelXDimension (SHORT fits ≤65535)
    exif += _e(0xA003, SHORT,    1, _sh(px_h))                    # PixelYDimension
    exif += S.pack(">I", 0)

    # ── GPSIFD (sorted by tag) ───────────────────────────────────────────────
    gps_ver = int.from_bytes(b"\x02\x03\x00\x00", "big")         # GPSVersionID [2,3,0,0]
    alt_ref  = 0 if altitude_m >= 0 else 1                        # 0=above sea level

    gps  = S.pack(">H", GPS_N)
    gps += _e(0x0000, BYTE,      4, gps_ver)                       # GPSVersionID
    gps += _e(0x0001, ASCII,     2, _ascii_inline(lat_ref))        # GPSLatitudeRef
    gps += _e(0x0002, RATIONAL,  3, lat_off)                       # GPSLatitude
    gps += _e(0x0003, ASCII,     2, _ascii_inline(lon_ref))        # GPSLongitudeRef
    gps += _e(0x0004, RATIONAL,  3, lon_off)                       # GPSLongitude
    gps += _e(0x0006, RATIONAL,  1, alt_off)                       # GPSAltitude
    gps += S.pack(">I", 0)

    # ── assemble TIFF + APP1 ─────────────────────────────────────────────────
    tiff = (
        b"MM"
        + S.pack(">HI", 42, IFD0_OFF)
        + ifd0
        + exif
        + gps
        + bytes(data)
    )

    app1_data = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + S.pack(">H", len(app1_data) + 2) + app1_data
    return app1


def _inject_exif(jpeg_data: bytes, app1: bytes) -> bytes:
    """Replace (or insert) EXIF APP1 in a downloaded JPEG.

    Keeps APP0/JFIF if present, removes any existing APP1, inserts ours.
    """
    if not jpeg_data.startswith(b"\xff\xd8"):
        return jpeg_data

    pos      = 2            # skip SOI
    prefix   = bytearray(b"\xff\xd8")

    while pos + 3 < len(jpeg_data):
        if jpeg_data[pos] != 0xFF:
            break
        marker = jpeg_data[pos : pos + 2]
        seg_len = int.from_bytes(jpeg_data[pos + 2 : pos + 4], "big")

        if marker == b"\xff\xe0":            # APP0 / JFIF — keep, then insert our EXIF after it
            prefix.extend(jpeg_data[pos : pos + 2 + seg_len])
            pos += 2 + seg_len
            break
        elif marker == b"\xff\xe1":          # APP1 / existing EXIF — discard
            pos += 2 + seg_len
            break
        elif 0xE2 <= marker[1] <= 0xEF:     # APP2–APPF — skip other app markers
            pos += 2 + seg_len
        else:
            break

    return bytes(prefix) + app1 + jpeg_data[pos:]


def _read_jpeg_dims(jpeg_data: bytes) -> tuple[int, int]:
    """Return (width, height) from a JPEG SOF marker, or (1920, 1440) fallback."""
    pos = 2  # skip SOI
    while pos + 7 < len(jpeg_data):
        if jpeg_data[pos] != 0xFF:
            break
        mid = jpeg_data[pos + 1]
        if mid in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                   0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = int.from_bytes(jpeg_data[pos + 5 : pos + 7], "big")
            w = int.from_bytes(jpeg_data[pos + 7 : pos + 9], "big")
            return w, h
        seg_len = int.from_bytes(jpeg_data[pos + 2 : pos + 4], "big")
        pos += 2 + seg_len
    return 1920, 1440


# ── timestamp helpers ─────────────────────────────────────────────────────────

def _circadian_hour() -> int:
    """Return a photo-taking hour biased towards daytime (7 am – 10 pm)."""
    weights = [1, 1, 1, 1, 1, 2, 3, 6, 8, 8, 8, 8, 7, 7, 8, 8, 8, 9, 9, 8, 7, 5, 3, 2]
    return random.choices(range(24), weights=weights)[0]


def _generate_timestamps(count: int, age_days: int) -> list[float]:
    """Spread `count` photo timestamps over `age_days`, circadian-weighted.

    Distribution: more photos in recent 30% of the window, less further back,
    to simulate typical phone usage patterns.
    """
    now = time.time()
    ts_list: list[float] = []
    for _ in range(count):
        # Skew towards recent: use triangular distribution biased to low values
        frac = random.triangular(0, 1, 0.15)
        days_ago = frac * age_days
        # Add circadian hour offset
        snap_ts = now - days_ago * 86400
        # Align to day boundary then add circadian hour
        day0 = snap_ts - (snap_ts % 86400)
        hour = _circadian_hour()
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        ts_list.append(day0 + hour * 3600 + minute * 60 + second)
    ts_list.sort()
    return ts_list


# ── filename generators ────────────────────────────────────────────────────────

_iphone_seq = 1001


def _make_filename(fmt: str, ts: float, idx: int) -> str:
    global _iphone_seq
    dt = time.gmtime(ts)
    if fmt == "pixel":
        ms = random.randint(0, 999)
        return time.strftime(f"PXL_%Y%m%d_%H%M%S{ms:03d}.jpg", dt)
    elif fmt == "iphone":
        name = f"IMG_{_iphone_seq:04d}.jpg"
        _iphone_seq += 1
        return name
    else:
        # Samsung / OnePlus
        return time.strftime("IMG_%Y%m%d_%H%M%S.jpg", dt)


# ── downloading ───────────────────────────────────────────────────────────────

_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 14; SM-S928B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Mobile Safari/537.36"
        )
    return _SESSION


def _download_picsum(seed: int, width: int = 1920, height: int = 1440,
                     retries: int = 3) -> Optional[bytes]:
    """Download a seeded Picsum photo. Returns JPEG bytes or None on failure."""
    url = f"https://picsum.photos/seed/{seed}/{width}/{height}"
    session = _get_session()
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=30, stream=False)
            resp.raise_for_status()
            if len(resp.content) < 4096:
                raise ValueError(f"suspiciously small payload: {len(resp.content)}B")
            return resp.content
        except Exception as exc:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                return None


def _synthetic_jpeg(px_w: int, px_h: int) -> bytes:
    """Generate a synthetic JPEG using Pillow vectorised ops (fast, no network)."""
    import numpy as np
    from PIL import ImageFilter

    # Build a small noise tile (8×8) then resize — fast and looks textured
    tile_size = 8
    arr = np.random.randint(40, 220, (tile_size, tile_size, 3), dtype=np.uint8)
    small = Image.fromarray(arr, "RGB")
    img = small.resize((px_w, px_h), Image.BILINEAR)
    img = img.filter(ImageFilter.GaussianBlur(radius=2))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=random.randint(78, 92))
    return buf.getvalue()


# ── per-photo worker ──────────────────────────────────────────────────────────

def _process_photo(
    idx: int,
    seed: int,
    ts: float,
    profile: dict,
    home_lat: float,
    home_lon: float,
    output_dir: Path,
    no_download: bool,
    img_width: int,
    img_height: int,
) -> dict:
    """
    Download (or synthesise) one photo, inject EXIF, save to output_dir.
    Returns a manifest entry dict.
    """
    # ── pick camera params ────────────────────────────────────────────────────
    make     = random.choice(profile["makes"])
    model    = random.choice(profile["models"])
    software = random.choice(profile["software"])
    focal_idx = random.randrange(len(profile["focal_n"]))
    focal_n  = profile["focal_n"][focal_idx]
    focal_d  = profile["focal_d"][focal_idx]
    fnum_idx = random.randrange(len(profile["fnum_n"]))
    fnum_n   = profile["fnum_n"][fnum_idx]
    fnum_d   = profile["fnum_d"][fnum_idx]
    iso      = random.choice(profile["iso"])
    exp_d    = random.choice(profile["exp_d"])
    dim      = random.choice(profile["dims"])

    # ── GPS: walk around home location (simulate going out) ──────────────────
    # Wider drift for older photos, tighter for recent
    drift = random.gauss(0, 0.015)   # ~1.5 km std dev
    photo_lat = home_lat + drift + random.uniform(-0.003, 0.003)
    photo_lon = home_lon + drift + random.uniform(-0.003, 0.003)
    altitude  = random.randint(0, 250)

    # ── download or synthesise ────────────────────────────────────────────────
    if no_download:
        jpeg_raw = _synthetic_jpeg(img_width, img_height)
        px_w, px_h = img_width, img_height
    else:
        jpeg_raw = _download_picsum(seed, img_width, img_height)
        if jpeg_raw is None:
            # Fallback to synthetic on download failure
            jpeg_raw = _synthetic_jpeg(img_width, img_height)
            px_w, px_h = img_width, img_height
        else:
            px_w, px_h = _read_jpeg_dims(jpeg_raw)

    # ── build and inject EXIF ─────────────────────────────────────────────────
    app1 = _build_exif_app1(
        ts=ts,
        lat=photo_lat,
        lon=photo_lon,
        make=make,
        model=model,
        software=software,
        focal_n=focal_n,
        focal_d=focal_d,
        fnum_n=fnum_n,
        fnum_d=fnum_d,
        iso=iso,
        px_w=px_w,
        px_h=px_h,
        exp_n=1,
        exp_d=exp_d,
        altitude_m=altitude,
    )

    final_jpeg = _inject_exif(jpeg_raw, app1)

    # ── filename + save ───────────────────────────────────────────────────────
    fname = _make_filename(profile["fmt"], ts, idx)
    # Avoid collisions when multiple photos have the same second
    out_path = output_dir / fname
    if out_path.exists():
        stem, ext = fname.rsplit(".", 1)
        fname = f"{stem}_{idx:04d}.{ext}"
        out_path = output_dir / fname

    out_path.write_bytes(final_jpeg)

    # Backdate filesystem mtime to match EXIF timestamp
    os.utime(out_path, (ts, ts))

    return {
        "filename":  fname,
        "timestamp": int(ts),
        "datetime":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "lat":       round(photo_lat, 6),
        "lon":       round(photo_lon, 6),
        "altitude":  altitude,
        "make":      make,
        "model":     model,
        "iso":       iso,
        "focal_mm":  f"{focal_n}/{focal_d}",
        "f_stop":    f"f/{fnum_n / fnum_d:.1f}",
        "dims":      f"{px_w}x{px_h}",
        "seed":      seed,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download 565 mobile-cam photos with backdated EXIF for device injection",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--count",       type=int, default=565,
                   help="Number of photos to download/generate")
    p.add_argument("--age-days",    type=int, default=365,
                   help="Spread timestamps over this many past days")
    p.add_argument("--city",        choices=sorted(CITY_LOCATIONS), default="new_york",
                   help="Home city for GPS anchor (ignored if --lat/--lon set)")
    p.add_argument("--lat",         type=float, default=None,
                   help="Home GPS latitude (overrides --city)")
    p.add_argument("--lon",         type=float, default=None,
                   help="Home GPS longitude (overrides --city)")
    p.add_argument("--model",       choices=sorted(DEVICE_PROFILES), default="samsung",
                   help="Camera device profile for EXIF Make/Model")
    p.add_argument("--workers",     type=int, default=12,
                   help="Parallel download workers")
    p.add_argument("--width",       type=int, default=1920,
                   help="Download width in pixels (Picsum will resize)")
    p.add_argument("--height",      type=int, default=1440,
                   help="Download height in pixels")
    p.add_argument("--output-dir",  type=Path,
                   default=Path("/opt/titan/data/forge_gallery"),
                   help="Directory to save photos and manifest")
    p.add_argument("--no-download", action="store_true",
                   help="Skip network — generate synthetic JPEG bodies (fast, offline)")
    p.add_argument("--seed-offset", type=int, default=0,
                   help="Add offset to Picsum seed indices (vary content sets)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Resolve home GPS
    if args.lat is not None and args.lon is not None:
        home_lat, home_lon = args.lat, args.lon
    else:
        home_lat, home_lon = CITY_LOCATIONS[args.city]

    profile = DEVICE_PROFILES[args.model]
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pick seed pool (cycle if count > pool)
    pool_size = len(_PICSUM_POOL)
    raw_seeds = [
        _PICSUM_POOL[(i + args.seed_offset) % pool_size]
        for i in range(args.count)
    ]
    random.shuffle(raw_seeds)    # randomise order within the set

    # Generate backdated timestamps
    timestamps = _generate_timestamps(args.count, args.age_days)

    mode_str = "synthetic (offline)" if args.no_download else "Picsum Photos"
    print(f"\n{'━'*62}")
    print(f"  Titan Gallery Forge — {args.count} photos")
    print(f"{'━'*62}")
    print(f"  Source     : {mode_str}")
    print(f"  Camera     : {args.model} ({', '.join(profile['models'][:2])}…)")
    print(f"  Home GPS   : {home_lat:.4f}, {home_lon:.4f}  ({args.city})")
    print(f"  Age span   : {args.age_days} days")
    print(f"  Workers    : {args.workers}")
    print(f"  Resolution : {args.width}×{args.height}")
    print(f"  Output     : {output_dir}")
    print(f"{'━'*62}\n")

    jobs = [
        dict(
            idx=i,
            seed=raw_seeds[i],
            ts=timestamps[i],
            profile=profile,
            home_lat=home_lat,
            home_lon=home_lon,
            output_dir=output_dir,
            no_download=args.no_download,
            img_width=args.width,
            img_height=args.height,
        )
        for i in range(args.count)
    ]

    manifest_entries: list[dict] = [None] * args.count  # type: ignore[list-item]
    done = 0
    failed = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_photo, **j): j["idx"] for j in jobs}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                entry = fut.result()
                manifest_entries[idx] = entry
                done += 1
            except Exception as exc:
                failed += 1
                manifest_entries[idx] = {"error": str(exc), "idx": idx}

            total_done = done + failed
            if total_done % 20 == 0 or total_done == args.count:
                elapsed = time.time() - t_start
                rate = total_done / elapsed if elapsed > 0 else 0
                eta = (args.count - total_done) / rate if rate > 0 else 0
                pct = total_done / args.count * 100
                bar_len = 30
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(
                    f"\r  [{bar}] {pct:5.1f}%  "
                    f"{done} ok / {failed} fail  "
                    f"{rate:.1f} img/s  ETA {eta:.0f}s   ",
                    end="",
                    flush=True,
                )

    print(f"\n\n  Done in {time.time() - t_start:.1f}s — {done} photos saved, {failed} failed.\n")

    # Write manifest JSON (consumed by profile_injector / forge pipeline)
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count":        done,
        "camera":       args.model,
        "age_days":     args.age_days,
        "home_lat":     home_lat,
        "home_lon":     home_lon,
        "city":         args.city,
        "output_dir":   str(output_dir),
        "photos":       [e for e in manifest_entries if e and "error" not in e],
        "failures":     [e for e in manifest_entries if e and "error" in e],
    }

    manifest_path = output_dir / "gallery_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  Manifest   : {manifest_path}  ({done} entries)\n")

    # Print summary of date range
    good = manifest["photos"]
    if good:
        oldest = min(e["datetime"] for e in good)
        newest = max(e["datetime"] for e in good)
        print(f"  Date range : {oldest}  →  {newest}")
        span = (max(e["timestamp"] for e in good) - min(e["timestamp"] for e in good)) / 86400
        print(f"  Span       : {span:.0f} days")
        print(f"  Rate       : {len(good) / max(span, 1):.1f} photos/day avg\n")

    if failed > 0:
        print(f"  WARNING: {failed} photo(s) failed. Check network or use --no-download.\n")

    print(f"  Gallery ready for inject:")
    print(f"    profile['gallery_paths'] = sorted(Path('{output_dir}').glob('*.jpg'))")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
