#!/bin/bash
# Post-install script for Titan VMOS Console DEB package

set -e

# Create data directories
mkdir -p /opt/titan/data
mkdir -p /opt/titan/data/vmos_sessions
mkdir -p /opt/titan/data/profiles

# Set permissions
chmod 755 /opt/titan/data

# Create desktop entry if not exists
DESKTOP_FILE="/usr/share/applications/titan-vmos-console.desktop"
if [ ! -f "$DESKTOP_FILE" ]; then
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Titan VMOS Console
Comment=Titan V13.0 VMOS Pro Cloud Console
Exec=/opt/Titan VMOS Console/titan-vmos-console --no-sandbox
Icon=/opt/Titan VMOS Console/resources/app/assets/icon.png
Terminal=false
Type=Application
Categories=Development;Utility;
Keywords=titan;android;vmos;cloud;antidetect;console;
StartupWMClass=titan-vmos-console
EOF
fi

echo "Titan VMOS Console installed successfully."
echo "Launch from your applications menu or run: titan-vmos-console"
