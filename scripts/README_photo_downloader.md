# Camera Photo Downloader

Downloads 567 realistic photos with authentic camera EXIF metadata, simulating photos taken by real smartphone cameras.

## Features

- **Realistic EXIF Metadata**: Includes camera make/model, GPS coordinates, timestamps, exposure settings
- **Multiple Camera Models**: Samsung Galaxy S24/S23 Ultra, iPhone 15/14 Pro, Google Pixel 8 Pro, OnePlus 12, Xiaomi 14 Pro
- **Authentic Filenames**: Various camera naming patterns (IMG_, DSC_, DCIM_, PXL_)
- **Random Timestamps**: Photos dated within the last year with realistic time distribution
- **GPS Coordinates**: Random US locations embedded in EXIF
- **File Timestamps**: Modified dates match EXIF capture dates

## Installation

```bash
pip install -r requirements_photo_downloader.txt
```

## Usage

```bash
cd /root/Titan-android-v13/scripts
python download_camera_photos.py
```

Photos will be saved to `downloaded_photos/` directory.

## Output

- **567 JPEG files** with realistic camera metadata
- File sizes: ~500KB - 2MB per photo
- Resolutions: 3264x2448 to 4032x3024 pixels
- EXIF data includes: Make, Model, DateTime, GPS, Exposure, ISO, Focal Length

## Example Filenames

- `IMG_20250328_143052.jpg`
- `DSC_5847.jpg`
- `PXL_20250315_091234_456.jpg`
- `DCIM_20250301_183045.jpg`
