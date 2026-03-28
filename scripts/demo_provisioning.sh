#!/usr/bin/env bash
# Titan V12 — 90-Day Device Provisioning Demo & Verification Script
# This script demonstrates the provisioning workflow and lists available options

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Titan V12 — 90-Day Device Provisioning Demo                 ║"
echo "║   Create realistic Android devices with 90 days of activity   ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}\n"

CD_PATH=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
cd "$CD_PATH"

# Check Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}✗ Python not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python available${NC}"

# Check script exists
if [ ! -f "provision_90day_device.py" ]; then
    echo -e "${RED}✗ provision_90day_device.py not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Provisioning script ready${NC}"

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[1] AVAILABLE DEVICE MODELS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

python provision_90day_device.py list-presets 2>/dev/null | tail -20

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[2] AVAILABLE CARRIERS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

python provision_90day_device.py list-carriers 2>/dev/null | tail -20

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[3] AVAILABLE LOCATIONS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

python provision_90day_device.py list-locations 2>/dev/null | tail -20

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[4] QUICK START EXAMPLES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

cat << 'EOF'

Example 1: Create 90-day device with defaults
─────────────────────────────────────────────
python provision_90day_device.py provision

Creates: Samsung S25 Ultra, T-Mobile US, NYC location, 90 days old


Example 2: Create with custom persona
───────────────────────────────────────
python provision_90day_device.py provision \
  --persona-name "Alice Johnson" \
  --persona-email "alice@acme.com" \
  --persona-phone "+1-415-555-0123"


Example 3: Create different ages
─────────────────────────────────
# New 30-day device
python provision_90day_device.py provision --age-days 30

# 1-year-old device  
python provision_90day_device.py provision --age-days 365


Example 4: Specific model + carrier + country
──────────────────────────────────────────────
python provision_90day_device.py provision \
  --model google_pixel_9_pro \
  --country GB \
  --carrier vodafone_uk \
  --location london


Example 5: List available options
──────────────────────────────────
python provision_90day_device.py list-presets
python provision_90day_device.py list-carriers
python provision_90day_device.py list-locations

EOF

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[5] PROVISIONING STAGES${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

cat << 'EOF'

[1/5] Device Creation       → Launches Cuttlefish KVM (~15 seconds)
[2/5] Boot Wait            → Waits for Android boot (~60-120 seconds)
[3/5] Profile Forge        → Generates 90 days of data (~10 seconds)
[4/5] Profile Injection    → Pushes data to device (~60 seconds)
[5/5] Device Ready         → Complete, device info saved

Total Time: ~3-4 minutes per device

EOF

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[6] DEVICE ACCESS${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

cat << 'EOF'

After provisioning, device is accessible via:

ADB Command Line:
  adb devices                                # List devices
  adb -s 127.0.0.1:6520 shell getprop ...   # Run commands

VNC Desktop (if configured):
  vncviewer 127.0.0.1:6444

Device Info JSON:
  /opt/titan/data/devices/{device_id}_info.json

ADB Connect String:
  127.0.0.1:6520 (or auto-detected in adb devices list)

EOF

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}[7] DOCUMENTATION${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

cat << 'EOF'

Full documentation available at:
  • PROVISION_90_DAY_DEVICE.md              [50+ page guide]
  • TITANV12_90DAY_PROVISIONING_SUMMARY.md  [Quick reference]

In the files, find:
  • Prerequisites & system requirements
  • Advanced options & API endpoints
  • 6 troubleshooting scenarios
  • Performance benchmarks
  • Integration with Titan AI agent

EOF

echo -e "\n${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "Demo complete! Ready to provision your first 90-day device."
echo -e "Run: python provision_90day_device.py provision"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}\n"

