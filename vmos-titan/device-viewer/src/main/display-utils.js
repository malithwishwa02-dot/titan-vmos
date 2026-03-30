const { screen } = require('electron');
const { execSync } = require('child_process');

/**
 * Detect if running inside an RDP / remote desktop session.
 */
function isRemoteSession() {
  try {
    // Check common environment indicators
    const sessionType = process.env.XDG_SESSION_TYPE || '';
    const display = process.env.DISPLAY || '';

    // xrdp sets XDG_SESSION_TYPE=x11 and runs xrdp-sesman
    if (sessionType === 'x11') {
      try {
        execSync('pgrep -x xrdp-sesman', { timeout: 2000, stdio: 'pipe' });
        return true;
      } catch (_) {}
    }

    // Check for xrdp or xfreerdp processes
    try {
      execSync('pgrep -f "xrdp|xfreerdp|rdesktop"', { timeout: 2000, stdio: 'pipe' });
      return true;
    } catch (_) {}

    // Check for remote DISPLAY (e.g., :10+)
    const m = display.match(/:(\d+)/);
    if (m && parseInt(m[1], 10) >= 10) return true;
  } catch (_) {}
  return false;
}

/**
 * Get the usable screen area from the primary display.
 * Returns { width, height } of the workArea (excludes taskbars/panels).
 */
function getScreenSize() {
  const primary = screen.getPrimaryDisplay();
  return {
    width: primary.workAreaSize.width,
    height: primary.workAreaSize.height,
    scaleFactor: primary.scaleFactor || 1,
  };
}

/**
 * Calculate the optimal scrcpy screen dimensions and window size for a given
 * available area while maintaining 9:16 aspect ratio.
 *
 * @param {number} availW  Available width (e.g. display workArea width)
 * @param {number} availH  Available height (e.g. display workArea height)
 * @param {object} baseLayout  The base constants from constants.js
 * @returns {object} Computed layout dimensions
 */
function calculateOptimalSize(availW, availH, baseLayout) {
  const C = baseLayout;
  const ASPECT = 9 / 16;

  // Reserve space for titlebar, status bar, padding, toolbar
  const chromeH = C.TITLEBAR_HEIGHT + C.CONTAINER_PAD_Y * 2 + C.STATUS_BAR_HEIGHT;
  const chromeW = C.CONTAINER_PAD_X * 2 + C.TOOLBAR_GAP + C.TOOLBAR_WIDTH;

  // Available area for the phone body
  const bodyAvailW = availW - chromeW;
  const bodyAvailH = availH - chromeH;

  // Phone body includes bezels around the screen
  const bezelW = C.BEZEL_LEFT + C.BEZEL_RIGHT;
  const bezelH = C.BEZEL_TOP + C.BEZEL_BOTTOM;

  // Available area for the screen within the phone body
  const screenAvailW = bodyAvailW - bezelW;
  const screenAvailH = bodyAvailH - bezelH;

  // Fit the 9:16 screen into the available space
  let screenW = Math.floor(screenAvailH * ASPECT);
  let screenH = screenAvailH;
  if (screenW > screenAvailW) {
    screenW = screenAvailW;
    screenH = Math.floor(screenW / ASPECT);
  }

  // Ensure even dimensions (helps with video codec alignment)
  screenW = Math.max(180, screenW & ~1);
  screenH = Math.max(320, screenH & ~1);

  // Derive all dependent dimensions
  const phoneW = screenW + bezelW;
  const phoneH = screenH + bezelH;
  const windowW = C.CONTAINER_PAD_X + phoneW + C.TOOLBAR_GAP + C.TOOLBAR_WIDTH + C.CONTAINER_PAD_X;
  const windowH = C.TITLEBAR_HEIGHT + C.CONTAINER_PAD_Y + phoneH + C.CONTAINER_PAD_Y + C.STATUS_BAR_HEIGHT;

  // Horizontal: phone is flush-left within the padded container (container exactly holds phone + gap + toolbar)
  const xOffset = C.CONTAINER_PAD_X + C.BEZEL_LEFT;

  // Vertical: phone is vertically centered inside device-container
  // device-container height = availH - titlebar - status-bar
  const containerH = availH - C.TITLEBAR_HEIGHT - C.STATUS_BAR_HEIGHT;
  const phoneTopInContainer = Math.max(C.CONTAINER_PAD_Y, Math.floor((containerH - phoneH) / 2));
  const yOffset = C.TITLEBAR_HEIGHT + phoneTopInContainer + C.BEZEL_TOP;

  // Scale factor relative to default 360×640
  const scale = screenH / C.SCREEN_HEIGHT;

  return {
    screenWidth: screenW,
    screenHeight: screenH,
    phoneWidth: phoneW,
    phoneHeight: phoneH,
    windowWidth: windowW,
    windowHeight: windowH,
    xOffset,
    yOffset,
    scale,
    bezelTop: C.BEZEL_TOP,
    bezelBottom: C.BEZEL_BOTTOM,
    bezelSide: C.BEZEL_LEFT,
    bezelRadius: Math.round(38 * scale),
    screenRadius: Math.round(30 * scale),
  };
}

/**
 * Calculate fullscreen layout — no phone bezel, scrcpy fills the window.
 * scrcpy is centered both horizontally and vertically within the content area.
 */
function calculateFullscreenSize(availW, availH, baseLayout) {
  const C = baseLayout;
  const ASPECT = 9 / 16;
  const railReserve = C.TOOLBAR_WIDTH + C.TOOLBAR_GAP + C.CONTAINER_PAD_X;

  // In fullscreen mode the status-bar is position:fixed, so only titlebar is chrome
  const contentH = availH - C.TITLEBAR_HEIGHT;
  const contentW = Math.max(180, availW - railReserve);

  // Fill width first (scrcpy fills the full window width for portrait phone on portrait display)
  let screenW = contentW;
  let screenH = Math.floor(screenW / ASPECT);
  if (screenH > contentH) {
    // Width would make it too tall — constrain by height instead
    screenH = contentH;
    screenW = Math.floor(screenH * ASPECT);
  }

  screenW = Math.max(180, screenW & ~1);
  screenH = Math.max(320, screenH & ~1);

  // Center both horizontally and vertically within the content area
  const xOffset = Math.floor((contentW - screenW) / 2);
  const yOffset = C.TITLEBAR_HEIGHT + Math.floor((contentH - screenH) / 2);

  return {
    screenWidth: screenW,
    screenHeight: screenH,
    phoneWidth: screenW,
    phoneHeight: screenH,
    windowWidth: availW,
    windowHeight: availH,
    xOffset,
    yOffset,
    scale: screenH / C.SCREEN_HEIGHT,
    bezelTop: 0,
    bezelBottom: 0,
    bezelSide: 0,
    bezelRadius: 0,
    screenRadius: 0,
  };
}

module.exports = { isRemoteSession, getScreenSize, calculateOptimalSize, calculateFullscreenSize };
