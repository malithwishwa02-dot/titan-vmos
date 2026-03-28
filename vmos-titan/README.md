# VMOS Titan

Professional Linux desktop application for VMOS Pro cloud device management with full Genesis Studio integration.

![VMOS Titan](assets/icon.png)

## Features

### 📱 Cloud Instance Management
- View all VMOS Pro cloud instances
- Start, stop, and restart devices
- Monitor device status in real-time
- Multi-device batch operations

### 🧬 Genesis Studio (Full Integration)
- **16-Phase Pipeline**: Pre-flight → Wipe → Stealth Patch → Network → Forge Profile → Payment History → Google Account → Profile Inject → Wallet → App Bypass → Browser Harden → Play Integrity → Sensors → Immune Watch → Trust Audit → Final Verify
- **Quick Presets**: US/UK Standard 90-Day, US Heavy 365-Day, Quick 30-Day
- **Country Support**: US, GB, DE, FR, CA, AU with locale-specific configurations
- **Identity Forge**: Full persona generation (name, email, phone, DOB, address)
- **Payment Injection**: Card data, Google Pay, Chrome Autofill
- **Trust Scoring**: 14-check trust audit with A+/A/B/C/F grading

### ⌨️ Remote Shell
- Execute ADB commands on cloud devices
- Real-time output display
- Command history

### 📋 Device Properties
- View/edit device fingerprints
- Modify brand, model, Android ID
- SIM, GPS, WiFi configuration

### 📷 Screenshot & Control
- Capture device screenshots
- Touch simulation
- UI interaction

### ⚙️ Settings
- VMOS Cloud API credentials (AK/SK)
- Server configuration
- Theme preferences

## Installation

### Prerequisites
- Linux (Ubuntu 20.04+, Debian 11+, or similar)
- Node.js 18+
- npm

### Quick Start

```bash
cd vmos-titan
npm install
npm start
```

### Build Packages

```bash
./build.sh
```

This creates:
- `dist/vmos-titan_1.0.0_amd64.deb` — Debian/Ubuntu package
- `dist/VMOS Titan-1.0.0.AppImage` — Universal Linux AppImage

### Install DEB Package

```bash
sudo dpkg -i dist/vmos-titan_1.0.0_amd64.deb
```

## Configuration

### First Run Setup

On first launch, VMOS Titan will prompt for:
1. **VMOS Cloud Access Key (AK)** — Get from your VMOS Pro dashboard
2. **VMOS Cloud Secret Key (SK)** — Get from your VMOS Pro dashboard

Credentials are stored securely in `~/.config/vmos-titan/config.json`.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TITAN_API_PORT` | Local API server port | 8082 |
| `TITAN_DATA` | Data storage directory | /opt/titan/data |
| `VMOS_CLOUD_AK` | VMOS Cloud Access Key | (from config) |
| `VMOS_CLOUD_SK` | VMOS Cloud Secret Key | (from config) |

## Architecture

```
vmos-titan/
├── main.js          # Electron main process
├── preload.js       # Secure IPC bridge
├── index.html       # Main UI (Alpine.js + Tailwind)
├── setup.html       # First-run setup wizard
├── package.json     # Electron config
├── assets/          # Icons, Tailwind, Alpine.js
├── start.sh         # Dev launch script
├── build.sh         # Build script
└── vmos-titan.desktop  # Linux desktop entry
```

## API Integration

VMOS Titan connects to:
1. **Local Titan API** (`http://127.0.0.1:8082`) — Manages Genesis Studio, device operations
2. **VMOS Cloud API** (`https://api.vmoscloud.com`) — VMOS Pro instance management

All VMOS Cloud API calls use HMAC-SHA256 signature authentication.

## License

MIT

## Support

- GitHub Issues: [Report bugs or request features]
- Documentation: See `/docs` folder in the main repository
