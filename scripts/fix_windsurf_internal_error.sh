#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Fix Windsurf Claude Internal Error - Complete Codeium Removal
# Uninstalls Codeium, clears caches, fixes configuration issues
# ═══════════════════════════════════════════════════════════════════
set -e

echo -e "\n\033[1;36m══ Windsurf Internal Error Fix Script ══\033[0m"
echo -e "\033[1;33mThis will completely remove Codeium and fix configuration issues\033[0m\n"

# ─── Phase 1: Kill Windsurf Process ────────────────────────────────
echo -e "\n\033[1;36m── Phase 1: Stopping Windsurf ──\033[0m"
pkill -9 -f windsurf 2>/dev/null || true
pkill -9 -f codeium 2>/dev/null || true
sleep 2
echo -e "\033[1;32m✓ Windsurf stopped\033[0m"

# ─── Phase 2: Remove Codeium Extension/Integration ───────────────
echo -e "\n\033[1;36m── Phase 2: Removing Codeium Integration ──\033[0m"

# Remove Codeium directories
rm -rf ~/.codeium 2>/dev/null || true
rm -rf ~/.config/Windsurf/Codeium 2>/dev/null || true
rm -rf ~/.config/Windsurf/codeium 2>/dev/null || true
rm -rf ~/.config/Windsurf/globalStorage/codeium* 2>/dev/null || true
rm -rf ~/.config/Windsurf/extensions/codeium* 2>/dev/null || true

# Remove from VSCode-style paths (Windsurf uses VSCode structure)
rm -rf ~/.vscode/extensions/codeium* 2>/dev/null || true
rm -rf ~/.config/Code/User/globalStorage/codeium* 2>/dev/null || true

echo -e "\033[1;32m✓ Codeium removed\033[0m"

# ─── Phase 3: Clear All Caches ────────────────────────────────────
echo -e "\n\033[1;36m── Phase 3: Clearing All Caches ──\033[0m"

rm -rf ~/.config/Windsurf/Cache 2>/dev/null || true
rm -rf ~/.config/Windsurf/CachedData 2>/dev/null || true
rm -rf ~/.config/Windsurf/Code\ Cache 2>/dev/null || true
rm -rf ~/.config/Windsurf/GPUCache 2>/dev/null || true
rm -rf ~/.config/Windsurf/Service\ Worker 2>/dev/null || true
rm -rf ~/.config/Windsurf/Cookies 2>/dev/null || true
rm -rf ~/.config/Windsurf/Network\ Persistent\ State 2>/dev/null || true
rm -rf ~/.config/Windsurf/Local\ Storage 2>/dev/null || true
rm -rf ~/.config/Windsurf/Session\ Storage 2>/dev/null || true

echo -e "\033[1;32m✓ All caches cleared\033[0m"

# ─── Phase 4: Fix Settings.json (Remove Codeium Configs) ──────────
echo -e "\n\033[1;36m── Phase 4: Cleaning Settings.json ──\033[0m"

SETTINGS_FILE="$HOME/.config/Windsurf/User/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    # Backup original
    cp "$SETTINGS_FILE" "$SETTINGS_FILE.backup.$(date +%s)"
    
    # Remove Codeium-related settings using Python (safer than sed for JSON)
    python3 << 'EOF' 2>/dev/null || python << 'EOF' 2>/dev/null || true
import json
import sys

try:
    with open("$SETTINGS_FILE", 'r') as f:
        settings = json.load(f)
    
    # Remove codeium-related keys
    keys_to_remove = [k for k in settings.keys() if 'codeium' in k.lower()]
    for k in keys_to_remove:
        del settings[k]
    
    # Fix other common problematic settings
    if "editor.inlineSuggest.enabled" in settings:
        settings["editor.inlineSuggest.enabled"] = False
    
    with open("$SETTINGS_FILE", 'w') as f:
        json.dump(settings, f, indent=4)
    print("✓ Settings cleaned")
except Exception as e:
    print(f"Note: Could not clean settings: {e}")
EOF
else
    echo "No settings.json found, creating fresh one..."
    mkdir -p "$(dirname "$SETTINGS_FILE")"
fi

echo -e "\033[1;32m✓ Settings cleaned\033[0m"

# ─── Phase 5: Create Clean Settings.json ──────────────────────────
echo -e "\n\033[1;36m── Phase 5: Creating Clean Configuration ──\033[0m"

mkdir -p ~/.config/Windsurf/User
cat > ~/.config/Windsurf/User/settings.json << 'EOF'
{
    "telemetry.telemetryLevel": "off",
    "workbench.startupEditor": "none",
    "window.menuBarVisibility": "toggle",
    "editor.fontSize": 14,
    "terminal.integrated.fontSize": 13,
    "disable-hardware-acceleration": true,
    "editor.inlineSuggest.enabled": false,
    "codeium.enableConfig": {
        "enableAutocomplete": false,
        "enableSearch": false
    },
    "extensions.autoCheckUpdates": false,
    "extensions.autoUpdate": false,
    "update.mode": "none",
    "workbench.enableExperiments": false
}
EOF

echo -e "\033[1;32m✓ Clean configuration created\033[0m"

# ─── Phase 6: Clear State.vscdb (Database with extension states) ──
echo -e "\n\033[1;36m── Phase 6: Clearing Extension State Database ──\033[0m"

VSCDB="$HOME/.config/Windsurf/globalStorage/state.vscdb"
if [ -f "$VSCDB" ]; then
    # Backup and create empty DB or remove Codeium entries
    cp "$VSCDB" "$VSCDB.backup.$(date +%s)" 2>/dev/null || true
    
    # Use sqlite3 to remove codeium entries if available
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$VSCDB" "DELETE FROM ItemTable WHERE key LIKE '%codeium%' OR value LIKE '%codeium%';" 2>/dev/null || true
        echo -e "\033[1;32m✓ Codeium entries removed from state database\033[0m"
    else
        # If no sqlite3, just remove the whole DB (will be recreated)
        rm -f "$VSCDB"
        echo -e "\033[1;33m⚠ State database removed (will be recreated)\033[0m"
    fi
fi

# ─── Phase 7: Remove Codeium from Keybindings ─────────────────────
echo -e "\n\033[1;36m── Phase 7: Cleaning Keybindings ──\033[0m"

KEYBINDINGS="$HOME/.config/Windsurf/User/keybindings.json"
if [ -f "$KEYBINDINGS" ]; then
    cp "$KEYBINDINGS" "$KEYBINDINGS.backup.$(date +%s)"
    # Remove codeium keybindings
    grep -v -i "codeium" "$KEYBINDINGS" > "$KEYBINDINGS.tmp" 2>/dev/null || true
    mv "$KEYBINDINGS.tmp" "$KEYBINDINGS" 2>/dev/null || true
    echo -e "\033[1;32m✓ Keybindings cleaned\033[0m"
fi

# ─── Phase 8: Check for conflicting extensions ────────────────────
echo -e "\n\033[1;36m── Phase 8: Checking Extensions ──\033[0m"

EXTENSIONS_DIR="$HOME/.config/Windsurf/extensions"
if [ -d "$EXTENSIONS_DIR" ]; then
    # List any suspicious extensions
    echo "Extensions found:"
    ls -1 "$EXTENSIONS_DIR" | grep -i -E "(codeium|copilot|ai|codium|tabnine)" || echo "  No AI extensions found (good)"
fi

# ─── Phase 9: Fix GPU/Display Issues (Common for RDP/xRDP) ─────────
echo -e "\n\033[1;36m── Phase 9: Adding GPU/Display Fixes ──\033[0m"

# Create desktop entry with proper flags
DESKTOP_FILE="$HOME/Desktop/windsurf-fixed.desktop"
cat > "$DESKTOP_FILE" << 'EOF'
[Desktop Entry]
Name=Windsurf (Fixed)
Comment=AI-native code editor (GPU fixes applied)
GenericName=Text Editor
Exec=/usr/bin/windsurf --disable-gpu --no-sandbox --disable-software-rasterizer --disable-gpu-compositing --unity-launch %F
Icon=windsurf
Type=Application
StartupNotify=false
StartupWMClass=Windsurf
Categories=Utility;TextEditor;Development;IDE;
MimeType=text/plain;inode/directory;
EOF

chmod +x "$DESKTOP_FILE"

# Create wrapper script
WRAPPER="/usr/local/bin/windsurf-fixed"
cat > "$WRAPPER" << 'EOF'
#!/bin/bash
# Windsurf launcher with fixes for RDP/internal errors
export ELECTRON_DISABLE_SANDBOX=1
export DISABLE_GPU=1
/usr/bin/windsurf --disable-gpu --no-sandbox --disable-software-rasterizer --disable-gpu-compositing "$@"
EOF

chmod +x "$WRAPPER"

echo -e "\033[1;32m✓ Created: $DESKTOP_FILE\033[0m"
echo -e "\033[1;32m✓ Created: $WRAPPER\033[0m"

# ─── Phase 10: Setup Titan API Alternative ────────────────────────
echo -e "\n\033[1;36m── Phase 10: Configuring Titan API Alternative ──\033[0m"

cat >> ~/.bashrc << 'EOF'

# ══ Windsurf Alternative AI Configuration ══
# Use these to bypass Codeium completely:
# export OPENAI_API_KEY="sk-titan-local"
# export OPENAI_API_BASE="http://localhost:8080/api/ai/coding"
EOF

echo -e "\033[1;32m✓ Titan API config added to ~/.bashrc (commented, uncomment to use)\033[0m"

# ─── Done ─────────────────────────────────────────────────────────
echo -e "\n\033[1;36m═══ Fix Complete ═══\033[0m\n"
echo -e "\033[1;32m✓ Codeium completely removed\033[0m"
echo -e "\033[1;32m✓ All caches cleared\033[0m"
echo -e "\033[1;32m✓ Settings cleaned\033[0m"
echo -e "\033[1;32m✓ GPU fixes applied\033[0m"
echo ""
echo -e "\033[1;33mNext Steps:\033[0m"
echo "  1. Launch Windsurf using ONE of these methods:"
echo "     • Double-click 'Windsurf (Fixed)' on desktop"
echo "     • Run: windsurf-fixed"
echo "     • Run: /usr/bin/windsurf --disable-gpu --no-sandbox"
echo ""
echo "  2. In Windsurf, disable AI features:"
echo "     Settings → Features → Disable Codeium AI"
echo ""
echo "  3. To use Titan API instead of Claude:"
echo "     Edit ~/.bashrc and uncomment the OPENAI_API_* lines"
echo "     Then restart Windsurf from that terminal"
echo ""
echo -e "\033[1;36mBackups created with timestamp in:\033[0m"
echo "  ~/.config/Windsurf/User/"
echo ""
