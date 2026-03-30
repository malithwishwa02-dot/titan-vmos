const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const ConfigManager = require('./config-manager');
const Logger = require('./logger');
const { ErrorHandler } = require('./error-handler');
const ScrcpyManager = require('./scrcpy-manager');
const AdbController = require('./adb-controller');
const TitanApi = require('./titan-api');
const { isRemoteSession, getScreenSize, calculateOptimalSize, calculateFullscreenSize } = require('./display-utils');
const C = require('../shared/constants');

app.commandLine.appendSwitch('no-sandbox');

let mainWindow;
let scrcpyManager;
let adbController;
let titanApi;
let config;
let logger;
let _errorHandler; // eslint-disable-line no-unused-vars
let _displayMode = 'phone'; // 'phone' | 'maximized' | 'fullscreen'
let _currentLayout = null;
let _isRemote = false;
let _saveGeometryTimer = null;
let _focusRaiseTimer = null;

function notifyRenderer(channel, data) {
  try {
    if (mainWindow && !mainWindow.isDestroyed() && mainWindow.webContents && !mainWindow.webContents.isDestroyed()) {
      mainWindow.webContents.send(channel, data);
    }
  } catch {
    // Renderer not available
  }
}

function _saveGeometry() {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMaximized() || mainWindow.isFullScreen()) return;
  const [x, y] = mainWindow.getPosition();
  const [w, h] = mainWindow.getSize();
  config.set('window.x', x);
  config.set('window.y', y);
  config.set('window.width', w);
  config.set('window.height', h);
}

function _scheduleSaveGeometry() {
  if (_saveGeometryTimer) clearTimeout(_saveGeometryTimer);
  _saveGeometryTimer = setTimeout(_saveGeometry, 500);
}

function _computeLayout(mode, winW, winH) {
  if (mode === 'fullscreen') {
    return calculateFullscreenSize(winW, winH, C);
  }
  return calculateOptimalSize(winW, winH, C);
}

function _setDisplayMode(mode) {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  if (mode === 'phone') {
    if (mainWindow.isFullScreen()) {
      mainWindow.setFullScreen(false);
      return;
    }
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
      return;
    }

    _displayMode = 'phone';
    config.set('display.mode', 'phone');
    const [w, h] = mainWindow.getSize();
    _applyLayout(_computeLayout('phone', w, h));
    return;
  }

  if (mode === 'fullscreen') {
    if (mainWindow.isFullScreen()) {
      _displayMode = 'fullscreen';
      config.set('display.mode', 'fullscreen');
      const [w, h] = mainWindow.getSize();
      _applyLayout(_computeLayout('fullscreen', w, h));
      return;
    }
    if (!mainWindow.isMaximized()) {
      mainWindow.maximize();
      return;
    }

    _displayMode = 'fullscreen';
    config.set('display.mode', 'fullscreen');
    const [w, h] = mainWindow.getSize();
    _applyLayout(_computeLayout('fullscreen', w, h));
  }
}

function _applyLayout(layout) {
  _currentLayout = layout;
  scrcpyManager.updateLayout({
    screenWidth: layout.screenWidth,
    screenHeight: layout.screenHeight,
    xOffset: layout.xOffset,
    yOffset: layout.yOffset,
  });
  notifyRenderer('display:layout', {
    mode: _displayMode,
    ...layout,
  });
}

function _determineInitialSize(log) {
  _isRemote = isRemoteSession();
  if (_isRemote) {
    log.info('Remote/RDP session detected — optimizing display settings');
  }

  const savedMode = config.get('display.mode') || 'phone';
  const autoFit = config.get('display.autoFit') !== false;

  // For remote sessions: auto-maximize with fullscreen layout (no bezels, fills screen)
  if (_isRemote && autoFit) {
    _displayMode = 'fullscreen';
    // Adjust scrcpy settings for RDP bandwidth
    const currentFps = config.get('scrcpy.maxFps');
    if (currentFps > 30) {
      log.info('RDP: reducing maxFps to 30 for bandwidth');
    }
    return { width: C.WINDOW_WIDTH, height: C.WINDOW_HEIGHT, maximize: true };
  }

  // Restore saved geometry if available
  const savedW = config.get('window.width');
  const savedH = config.get('window.height');
  const savedX = config.get('window.x');
  const savedY = config.get('window.y');

  if (savedW && savedH && savedMode !== 'phone') {
    _displayMode = savedMode;
    return { width: savedW, height: savedH, x: savedX, y: savedY };
  }

  // Auto-fit: if screen is large enough, use default phone size
  if (autoFit) {
    try {
      const scr = getScreenSize();
      if (scr.width >= C.WINDOW_WIDTH && scr.height >= C.WINDOW_HEIGHT) {
        _displayMode = 'phone';
        return { width: C.WINDOW_WIDTH, height: C.WINDOW_HEIGHT };
      }
      // Screen too small for default phone — scale down
      _displayMode = 'phone';
      const layout = calculateOptimalSize(scr.width, scr.height, C);
      return { width: layout.windowWidth, height: layout.windowHeight };
    } catch (_) {}
  }

  _displayMode = 'phone';
  return { width: C.WINDOW_WIDTH, height: C.WINDOW_HEIGHT };
}

function createWindow() {
  const log = logger.child('main');

  const initSize = _determineInitialSize(log);

  const winOpts = {
    width: initSize.width,
    height: initSize.height,
    frame: false,
    resizable: true,
    maximizable: true,
    minWidth: C.MIN_WINDOW_WIDTH,
    minHeight: C.MIN_WINDOW_HEIGHT,
    backgroundColor: '#0c0c0e',
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  };

  if (initSize.x != null && initSize.y != null) {
    winOpts.x = initSize.x;
    winOpts.y = initSize.y;
  }

  mainWindow = new BrowserWindow(winOpts);

  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  const serial = config.get('adbSerial') || C.ADB_SERIAL;
  adbController = new AdbController(serial, logger.child('adb'));

  // Get effective scrcpy config (override fps/bitrate for RDP)
  const effectiveConfig = _isRemote ? _createRdpConfig(config) : config;
  scrcpyManager = new ScrcpyManager(mainWindow, C, effectiveConfig, logger.child('scrcpy'));

  log.info('Window created, serial:', serial, 'mode:', _displayMode, 'remote:', _isRemote);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (initSize.maximize) {
      mainWindow.maximize();
    }
  });

  // Start scrcpy only after renderer is fully loaded to avoid IPC race
  mainWindow.webContents.once('did-finish-load', () => {
    // Compute initial layout based on actual window size
    const [w, h] = mainWindow.getSize();
    _currentLayout = _computeLayout(_displayMode, w, h);

    // Send initial layout to renderer
    notifyRenderer('display:layout', { mode: _displayMode, ..._currentLayout });

    setTimeout(() => scrcpyManager.start(), 300);
  });

  // ── Window events ──────────────────────────────────────────────────────
  mainWindow.on('move', () => {
    scrcpyManager.syncPosition();
    _scheduleSaveGeometry();
  });
  mainWindow.on('minimize', () => scrcpyManager.hide());
  mainWindow.on('restore', () => {
    scrcpyManager.show();
    scrcpyManager.syncPosition();
  });
  mainWindow.on('focus', () => {
    if (_focusRaiseTimer) clearTimeout(_focusRaiseTimer);
    _focusRaiseTimer = setTimeout(() => {
      _focusRaiseTimer = null;
      scrcpyManager.raise();
    }, 300);
  });

  mainWindow.on('resize', () => {
    const [w, h] = mainWindow.getSize();
    const layout = _computeLayout(_displayMode, w, h);
    _applyLayout(layout);
    _scheduleSaveGeometry();
  });

  mainWindow.on('maximize', () => {
    _displayMode = 'fullscreen';
    config.set('display.mode', 'fullscreen');
    const [w, h] = mainWindow.getSize();
    const layout = _computeLayout('fullscreen', w, h);
    _applyLayout(layout);
  });

  mainWindow.on('unmaximize', () => {
    _displayMode = 'phone';
    config.set('display.mode', 'phone');
    const [w, h] = mainWindow.getSize();
    const layout = _computeLayout('phone', w, h);
    _applyLayout(layout);
  });

  mainWindow.on('enter-full-screen', () => {
    _displayMode = 'fullscreen';
    config.set('display.mode', 'fullscreen');
    const [w, h] = mainWindow.getSize();
    const layout = _computeLayout('fullscreen', w, h);
    _applyLayout(layout);
  });

  mainWindow.on('leave-full-screen', () => {
    _displayMode = mainWindow.isMaximized() ? 'maximized' : 'phone';
    config.set('display.mode', _displayMode);
    const [w, h] = mainWindow.getSize();
    const layout = _computeLayout(_displayMode, w, h);
    _applyLayout(layout);
  });

  mainWindow.on('close', () => scrcpyManager.stop());
  mainWindow.on('closed', () => { mainWindow = null; });
}

/**
 * Create a config-like overlay that returns RDP-optimized scrcpy values.
 */
function _createRdpConfig(baseConfig) {
  return {
    get(key) {
      if (key === 'scrcpy') {
        const base = baseConfig.get('scrcpy') || {};
        return {
          ...base,
          maxFps: Math.min(base.maxFps || 60, 30),
          videoBitRate: '4M',
        };
      }
      return baseConfig.get(key);
    },
  };
}

// ── IPC handlers ─────────────────────────────────────────────────────────────
ipcMain.handle('adb:home',       () => adbController.pressHome());
ipcMain.handle('adb:back',       () => adbController.pressBack());
ipcMain.handle('adb:recent',     () => adbController.pressRecent());
ipcMain.handle('adb:power',      () => adbController.pressPower());
ipcMain.handle('adb:volumeUp',   () => adbController.volumeUp());
ipcMain.handle('adb:volumeDown', () => adbController.volumeDown());
ipcMain.handle('adb:rotate',     () => adbController.rotate());
ipcMain.handle('adb:screenshot', () => adbController.screenshot(config.get('screenshotDir')));
ipcMain.handle('adb:shell',    (_, cmd) => adbController.shell(cmd));

ipcMain.handle('window:close',    () => { scrcpyManager.stop(); app.quit(); });
ipcMain.handle('window:minimize', () => mainWindow && mainWindow.minimize());
ipcMain.handle('window:maximize', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
});
ipcMain.handle('window:fullscreen', () => {
  if (!mainWindow) return;
  mainWindow.setFullScreen(!mainWindow.isFullScreen());
});
ipcMain.handle('window:setDisplayMode', (_, mode) => _setDisplayMode(mode));
ipcMain.handle('window:getDisplayMode', () => _displayMode);
ipcMain.handle('window:isMaximized', () => mainWindow && mainWindow.isMaximized());
ipcMain.handle('window:isFullScreen', () => mainWindow && mainWindow.isFullScreen());

ipcMain.handle('scrcpy:restart',  () => {
  scrcpyManager.restart();
});

// Config IPC
ipcMain.handle('config:get',    (_, key) => config.get(key));
ipcMain.handle('config:set',    (_, key, value) => config.set(key, value));
ipcMain.handle('config:getAll', () => config.getAll());

// ── Titan API IPC ──────────────────────────────────────────────────────────
ipcMain.handle('titan:health',     () => titanApi ? titanApi.getHealth() : { connected: false });
ipcMain.handle('titan:device',     () => titanApi ? titanApi.getDevice() : null);
ipcMain.handle('titan:devices',    () => titanApi ? titanApi.getDevices() : null);
ipcMain.handle('titan:consoleUrl', () => titanApi ? titanApi.getConsoleUrl() : null);

// ── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  config = new ConfigManager();
  logger = new Logger(config);
  // ErrorHandler installs process-level listeners in its constructor
  // eslint-disable-next-line no-unused-vars
  _errorHandler = new ErrorHandler(logger, notifyRenderer);

  const log = logger.child('main');
  log.info('Titan Console v13.0.0 starting');
  log.info('Config path:', app.getPath('userData'));

  // Connect to Titan API backend (separate service at 127.0.0.1:8080)
  titanApi = new TitanApi(logger.child('api'), notifyRenderer);
  titanApi.startHealthPoll();

  createWindow();
});

app.on('window-all-closed', () => {
  if (titanApi) titanApi.stop();
  if (scrcpyManager) scrcpyManager.stop();
  if (logger) logger.close();
  app.quit();
});
