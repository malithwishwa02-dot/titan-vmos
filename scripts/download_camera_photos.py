#!/usr/bin/env python3
"""
Download 567 realistic camera photos with authentic EXIF metadata.
Simulates photos taken by real smartphone cameras with proper metadata.
"""

import os
import sys
import random
import requests
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS
import piexif
from io import BytesIO
import time

PHOTO_COUNT = 567
OUTPUT_DIR = Path("downloaded_photos")

CAMERA_MODELS = [
    ("Samsung", "SM-S928U", "Galaxy S24 Ultra"),
    ("Samsung", "SM-S918U", "Galaxy S23 Ultra"),
    ("Apple", "iPhone 15 Pro Max", "iPhone 15 Pro Max"),
    ("Apple", "iPhone 14 Pro", "iPhone 14 Pro"),
    ("Google", "Pixel 8 Pro", "Pixel 8 Pro"),
    ("OnePlus", "CPH2609", "OnePlus 12"),
    ("Xiaomi", "2311DRN6C", "Xiaomi 14 Pro"),
]

PHOTO_SOURCES = [
    "https://picsum.photos/4000/3000",
    "https://picsum.photos/3840/2160",
    "https://picsum.photos/4032/3024",
    "https://picsum.photos/3264/2448",
]

def generate_realistic_exif(index, timestamp):
    """Generate realistic EXIF data for a camera photo."""
    make, model, model_name = random.choice(CAMERA_MODELS)
    
    exif_dict = {
        "0th": {},
        "Exif": {},
        "GPS": {},
        "1st": {},
    }
    
    exif_dict["0th"][piexif.ImageIFD.Make] = make.encode()
    exif_dict["0th"][piexif.ImageIFD.Model] = model.encode()
    exif_dict["0th"][piexif.ImageIFD.Software] = f"{make} Camera".encode()
    exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
    exif_dict["0th"][piexif.ImageIFD.XResolution] = (72, 1)
    exif_dict["0th"][piexif.ImageIFD.YResolution] = (72, 1)
    exif_dict["0th"][piexif.ImageIFD.ResolutionUnit] = 2
    
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = timestamp.strftime("%Y:%m:%d %H:%M:%S").encode()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = timestamp.strftime("%Y:%m:%d %H:%M:%S").encode()
    exif_dict["0th"][piexif.ImageIFD.DateTime] = timestamp.strftime("%Y:%m:%d %H:%M:%S").encode()
    
    exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, random.choice([60, 120, 250, 500, 1000]))
    exif_dict["Exif"][piexif.ExifIFD.FNumber] = (random.choice([18, 20, 22, 24]), 10)
    exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = random.choice([50, 100, 200, 400, 800])
    exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (random.choice([24, 28, 35, 50, 70]), 10)
    exif_dict["Exif"][piexif.ExifIFD.Flash] = random.choice([0, 16])
    exif_dict["Exif"][piexif.ExifIFD.WhiteBalance] = random.choice([0, 1])
    exif_dict["Exif"][piexif.ExifIFD.ExposureMode] = 0
    exif_dict["Exif"][piexif.ExifIFD.SceneCaptureType] = 0
    exif_dict["Exif"][piexif.ExifIFD.ColorSpace] = 1
    
    lat = random.uniform(34.0, 40.0)
    lon = random.uniform(-118.0, -74.0)
    
    lat_deg = int(lat)
    lat_min = int((lat - lat_deg) * 60)
    lat_sec = int(((lat - lat_deg) * 60 - lat_min) * 60 * 100)
    
    lon_deg = int(abs(lon))
    lon_min = int((abs(lon) - lon_deg) * 60)
    lon_sec = int(((abs(lon) - lon_deg) * 60 - lon_min) * 60 * 100)
    
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N"
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = [(lat_deg, 1), (lat_min, 1), (lat_sec, 100)]
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"W"
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = [(lon_deg, 1), (lon_min, 1), (lon_sec, 100)]
    exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = (random.randint(0, 500), 1)
    exif_dict["GPS"][piexif.GPSIFD.GPSTimeStamp] = [
        (timestamp.hour, 1),
        (timestamp.minute, 1),
        (timestamp.second, 1)
    ]
    exif_dict["GPS"][piexif.GPSIFD.GPSDateStamp] = timestamp.strftime("%Y:%m:%d").encode()
    
    return piexif.dump(exif_dict)

def generate_realistic_filename(index, timestamp):
    """Generate realistic camera filename patterns."""
    patterns = [
        f"IMG_{timestamp.strftime('%Y%m%d')}_{random.randint(100000, 999999)}.jpg",
        f"DSC_{random.randint(1000, 9999)}.jpg",
        f"DCIM_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg",
        f"IMG_{random.randint(10000, 99999)}.jpg",
        f"PXL_{timestamp.strftime('%Y%m%d_%H%M%S')}_{random.randint(100, 999)}.jpg",
        f"{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg",
    ]
    return random.choice(patterns)

def download_and_process_photo(index):
    """Download a photo and add realistic EXIF metadata."""
    try:
        start_date = datetime.now() - timedelta(days=random.randint(1, 365))
        timestamp = start_date + timedelta(
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59)
        )
        
        source_url = random.choice(PHOTO_SOURCES)
        response = requests.get(source_url, timeout=30)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        exif_bytes = generate_realistic_exif(index, timestamp)
        
        filename = generate_realistic_filename(index, timestamp)
        output_path = OUTPUT_DIR / filename
        
        img.save(output_path, "JPEG", quality=random.randint(85, 95), exif=exif_bytes)
        
        os.utime(output_path, (timestamp.timestamp(), timestamp.timestamp()))
        
        return True, filename
    except Exception as e:
        return False, str(e)

def main():
    """Main execution function."""
    print(f"📸 Camera Photo Downloader")
    print(f"=" * 60)
    print(f"Target: {PHOTO_COUNT} photos")
    print(f"Output: {OUTPUT_DIR.absolute()}")
    print(f"=" * 60)
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    successful = 0
    failed = 0
    
    for i in range(1, PHOTO_COUNT + 1):
        success, result = download_and_process_photo(i)
        
        if success:
            successful += 1
            print(f"✓ [{i}/{PHOTO_COUNT}] {result}")
        else:
            failed += 1
            print(f"✗ [{i}/{PHOTO_COUNT}] Failed: {result}")
        
        if i % 10 == 0:
            print(f"\n📊 Progress: {i}/{PHOTO_COUNT} ({(i/PHOTO_COUNT)*100:.1f}%)")
            print(f"   Success: {successful} | Failed: {failed}\n")
        
        time.sleep(random.uniform(0.1, 0.5))
    
    print(f"\n" + "=" * 60)
    print(f"✅ Download Complete!")
    print(f"   Total: {PHOTO_COUNT}")
    print(f"   Successful: {successful}")
    print(f"   Failed: {failed}")
    print(f"   Location: {OUTPUT_DIR.absolute()}")
    print(f"=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
