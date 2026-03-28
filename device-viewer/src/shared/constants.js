// Cuttlefish device: 720x1280 (9:16 aspect ratio, Android 14)
// Display scale: 1:1 → 360x640

const SCREEN_WIDTH = 360;
const SCREEN_HEIGHT = 640;

// Phone bezel dimensions
const BEZEL_LEFT = 10;
const BEZEL_RIGHT = 10;
const BEZEL_TOP = 28;
const BEZEL_BOTTOM = 20;

// Layout
const TITLEBAR_HEIGHT = 36;
const CONTAINER_PAD_X = 16;
const CONTAINER_PAD_Y = 8;
const TOOLBAR_WIDTH = 84;
const TOOLBAR_GAP = 14;
const STATUS_BAR_HEIGHT = 24;

// Derived: phone body
const PHONE_WIDTH = SCREEN_WIDTH + BEZEL_LEFT + BEZEL_RIGHT;       // 380
const PHONE_HEIGHT = SCREEN_HEIGHT + BEZEL_TOP + BEZEL_BOTTOM;      // 688

// Derived: window
const WINDOW_WIDTH = CONTAINER_PAD_X + PHONE_WIDTH + TOOLBAR_GAP + TOOLBAR_WIDTH + CONTAINER_PAD_X; // 510
const WINDOW_HEIGHT = TITLEBAR_HEIGHT + CONTAINER_PAD_Y + PHONE_HEIGHT + CONTAINER_PAD_Y + STATUS_BAR_HEIGHT; // 764

// Exact pixel offsets from Electron window top-left to scrcpy screen area top-left
const SCREEN_X_OFFSET = CONTAINER_PAD_X + BEZEL_LEFT;                              // 26
const SCREEN_Y_OFFSET = TITLEBAR_HEIGHT + CONTAINER_PAD_Y + BEZEL_TOP;             // 72

// Default layout object (phone mode at base resolution)
const DEFAULT_LAYOUT = {
  DEVICE_WIDTH: 720,
  DEVICE_HEIGHT: 1280,
  SCREEN_WIDTH,
  SCREEN_HEIGHT,
  BEZEL_LEFT,
  BEZEL_RIGHT,
  BEZEL_TOP,
  BEZEL_BOTTOM,
  PHONE_WIDTH,
  PHONE_HEIGHT,
  WINDOW_WIDTH,
  WINDOW_HEIGHT,
  SCREEN_X_OFFSET,
  SCREEN_Y_OFFSET,
  TITLEBAR_HEIGHT,
  CONTAINER_PAD_X,
  CONTAINER_PAD_Y,
  TOOLBAR_WIDTH,
  TOOLBAR_GAP,
  STATUS_BAR_HEIGHT,
  ADB_SERIAL: '0.0.0.0:6520',
  // Minimum window size (phone mode at base resolution)
  MIN_WINDOW_WIDTH: WINDOW_WIDTH,
  MIN_WINDOW_HEIGHT: WINDOW_HEIGHT,
};

module.exports = DEFAULT_LAYOUT;
