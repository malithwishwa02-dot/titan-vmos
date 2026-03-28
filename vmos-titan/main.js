/**
 * VMOS Titan — Main Electron Process
 * 
 * Professional Linux desktop application for VMOS Pro cloud device management
 * with full Genesis Studio integration.
 * 
 * Features:
 *   - VMOS Pro Cloud instance management
 *   - Unified Genesis Studio pipeline
 *   - Remote shell execution
 *   - Device property modification
 *   - Screenshot & touch control
 *   - Professional-grade UI/UX
 */

const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog, nativeTheme } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');

// ─── Path Resolution (packaged vs dev) ────────────────────────────────
const IS_PACKAGED = app.isPackaged;
const RESOURCES = IS_PACKAGED ? process.resourcesPath : path.resolve(__dirname, '..');
const USER_DATA = app.getPath('userData');        // ~/.config/vmos-titan
const TITAN_DATA = IS_PACKAGED
  ? (process.env.TITAN_DATA || '/opt/titan/data')
  : path.join(USER_DATA, 'data');
const VENV_DIR = path.join(USER_DATA, 'venv');
const SERVER_DIR = path.join(RESOURCES, 'server');
const CORE_DIR = path.join(RESOURCES, 'core');
const CONFIG_FILE = path.join(USER_DATA, 'config.json');
const SETUP_DONE = path.join(USER_DATA, '.setup-done');

// ─── Config ───────────────────────────────────────────────────────────
const API_PORT = process.env.TITAN_API_PORT || 8082;  // Unique port for VMOS Titan
const API_URL = `http://127.0.0.1:${API_PORT}`;
const VMOS_API_BASE = 'https://api.vmoscloud.com';

// Chromium flags for headless / xRDP / GPU-less environments
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');

let mainWindow = null;
let setupWindow = null;
let tray = null;
let serverProc = null;
let _serverRestarts = 0;
const MAX_SERVER_RESTARTS = 3;

// ─── Prevent duplicate instances ─────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = mainWindow || setupWindow;
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ─── Utilities ───────────────────────────────────────────────────────
function ensureDir(d) { 
  fs.mkdirSync(d, { recursive: true }); 
}

function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    }
  } catch (e) {
    console.warn('[config] Failed to load:', e.message);
  }
  return {};
}

function saveConfig(config) {
  try {
    ensureDir(path.dirname(CONFIG_FILE));
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
    return true;
  } catch (e) {
    console.warn('[config] Failed to save:', e.message);
    return false;
  }
}

function loadDotEnv(envPath) {
  const vars = {};
  try {
    if (!fs.existsSync(envPath)) return vars;
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq < 1) continue;
      const key = line.slice(0, eq).trim();
      let val = line.slice(eq + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (key && val) vars[key] = val;
    }
  } catch (e) {
    console.warn('[dotenv] Failed to load', envPath, e.message);
  }
  return vars;
}

function findPython() {
  // Prefer Python 3.11+ per Titan V13 coding guidelines
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { timeout: 5000 }).toString().trim();
      const match = ver.match(/Python\s+(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 11))) {
        return { cmd, version: ver };
      }
    } catch (_) { /* not found */ }
  }
  return null;
}

function getUvicornCmd() {
  const venvUvi = path.join(VENV_DIR, 'bin', 'uvicorn');
  if (fs.existsSync(venvUvi)) return venvUvi;
  const legacyUvi = path.join(RESOURCES, 'venv', 'bin', 'uvicorn');
  if (fs.existsSync(legacyUvi)) return legacyUvi;
  const optUvi = '/opt/titan-v13-device/venv/bin/uvicorn';
  if (fs.existsSync(optUvi)) return optUvi;
  return 'uvicorn';
}

function isSetupDone() {
  const config = loadConfig();
  return fs.existsSync(SETUP_DONE) || (config.vmos_ak && config.vmos_sk);
}

// ─── Server Management ───────────────────────────────────────────────
function startServer() {
  if (serverProc) return;

  const uvicorn = getUvicornCmd();
  console.log(`[server] Starting uvicorn at ${uvicorn} on port ${API_PORT}`);

  const config = loadConfig();
  const envPath = path.join(RESOURCES, '.env');
  const envVars = loadDotEnv(envPath);

  const env = {
    ...process.env,
    ...envVars,
    PYTHONPATH: `${CORE_DIR}:${SERVER_DIR}`,
    TITAN_DATA: TITAN_DATA,
    TITAN_API_PORT: String(API_PORT),
    VMOS_CLOUD_AK: config.vmos_ak || envVars.VMOS_CLOUD_AK || '',
    VMOS_CLOUD_SK: config.vmos_sk || envVars.VMOS_CLOUD_SK || '',
  };

  ensureDir(TITAN_DATA);

  serverProc = spawn(uvicorn, ['titan_api:app', '--host', '127.0.0.1', '--port', String(API_PORT)], {
    cwd: SERVER_DIR,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  serverProc.stdout.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.log('[server]', msg);
  });

  serverProc.stderr.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.warn('[server-err]', msg);
  });

  serverProc.on('close', (code) => {
    console.log(`[server] Exited with code ${code}`);
    serverProc = null;
    if (_serverRestarts < MAX_SERVER_RESTARTS && mainWindow && !mainWindow.isDestroyed()) {
      _serverRestarts++;
      console.log(`[server] Auto-restart attempt ${_serverRestarts}/${MAX_SERVER_RESTARTS}`);
      setTimeout(startServer, 2000);
    }
  });
}

function stopServer() {
  if (serverProc) {
    serverProc.kill('SIGTERM');
    serverProc = null;
  }
}

// ─── Main Window ─────────────────────────────────────────────────────
async function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.focus();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'VMOS Titan — Cloud Device Management',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true,
    },
    autoHideMenuBar: true,
    frame: true,
    show: false,
  });

  // Load the main HTML file
  mainWindow.loadFile(path.join(__dirname, 'index.html'));

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (process.env.NODE_ENV === 'development') {
      mainWindow.webContents.openDevTools();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Create application menu
  createMenu();
}

// ─── Setup Window ────────────────────────────────────────────────────
function showSetupWindow() {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.focus();
    return;
  }

  setupWindow = new BrowserWindow({
    width: 600,
    height: 550,
    title: 'VMOS Titan — Initial Setup',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
  });

  setupWindow.loadFile(path.join(__dirname, 'setup.html'));
  setupWindow.on('closed', () => { setupWindow = null; });
}

// ─── Application Menu ────────────────────────────────────────────────
function createMenu() {
  const template = [
    {
      label: 'VMOS Titan',
      submenu: [
        { label: 'About VMOS Titan', role: 'about' },
        { type: 'separator' },
        { label: 'Settings', accelerator: 'CmdOrCtrl+,', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'settings');
        }},
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', role: 'quit' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Dashboard', accelerator: 'CmdOrCtrl+1', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'dashboard');
        }},
        { label: 'Instances', accelerator: 'CmdOrCtrl+2', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'instances');
        }},
        { label: 'Genesis Studio', accelerator: 'CmdOrCtrl+3', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'genesis');
        }},
        { type: 'separator' },
        { label: 'Reload', accelerator: 'CmdOrCtrl+R', role: 'reload' },
        { label: 'Toggle DevTools', accelerator: 'F12', role: 'toggleDevTools' },
        { type: 'separator' },
        { label: 'Toggle Fullscreen', accelerator: 'F11', role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        { label: 'Documentation', click: () => shell.openExternal('https://github.com/titan-project/docs') },
        { label: 'Report Issue', click: () => shell.openExternal('https://github.com/titan-project/issues') },
        { type: 'separator' },
        { label: 'About', click: () => {
          dialog.showMessageBox(mainWindow, {
            type: 'info',
            title: 'About VMOS Titan',
            message: 'VMOS Titan v1.0.0',
            detail: 'Professional VMOS Pro cloud device management with Genesis Studio integration.\n\nBuilt on Electron + Alpine.js + Tailwind CSS.'
          });
        }}
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// ─── System Tray ─────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png');
  if (!fs.existsSync(iconPath)) {
    console.warn('[tray] Icon not found:', iconPath);
    return;
  }

  tray = new Tray(iconPath);
  tray.setToolTip('VMOS Titan — Cloud Device Manager');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open VMOS Titan', click: () => { 
      if (mainWindow) mainWindow.show(); 
      else createMainWindow(); 
    }},
    { type: 'separator' },
    { label: 'Dashboard', click: () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.webContents.send('navigate', 'dashboard');
      }
    }},
    { label: 'Genesis Studio', click: () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.webContents.send('navigate', 'genesis');
      }
    }},
    { type: 'separator' },
    { label: 'Restart Server', click: () => {
      stopServer();
      _serverRestarts = 0;
      setTimeout(startServer, 1000);
    }},
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() }
  ]));
  tray.on('double-click', () => { 
    if (mainWindow) mainWindow.show(); 
    else createMainWindow();
  });
}

// ─── IPC Handlers ────────────────────────────────────────────────────

// Setup IPC
ipcMain.handle('setup:getInfo', () => {
  const python = findPython();
  const config = loadConfig();
  return {
    python: python ? python : null,
    venvExists: fs.existsSync(path.join(VENV_DIR, 'bin', 'python3')),
    dataDir: TITAN_DATA,
    venvDir: VENV_DIR,
    isPackaged: IS_PACKAGED,
    hasCredentials: !!(config.vmos_ak && config.vmos_sk),
    vmosAk: config.vmos_ak || '',
  };
});

ipcMain.handle('setup:save', async (event, { vmos_ak, vmos_sk }) => {
  const config = loadConfig();
  config.vmos_ak = vmos_ak;
  config.vmos_sk = vmos_sk;
  config.setup_date = new Date().toISOString();
  
  if (saveConfig(config)) {
    ensureDir(path.dirname(SETUP_DONE));
    fs.writeFileSync(SETUP_DONE, new Date().toISOString());
    return { ok: true };
  }
  return { ok: false, error: 'Failed to save configuration' };
});

ipcMain.handle('setup:testCredentials', async (event, { vmos_ak, vmos_sk }) => {
  return new Promise((resolve) => {
    // Test VMOS Cloud API credentials by calling instance_list
    const body = JSON.stringify({ page: 1, rows: 1 });
    const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    
    // For now, just verify credentials are non-empty
    if (!vmos_ak || !vmos_sk) {
      resolve({ ok: false, error: 'Missing credentials' });
      return;
    }
    
    // Return success if credentials provided
    resolve({ ok: true, message: 'Credentials saved. API will be tested on first use.' });
  });
});

ipcMain.handle('config:get', () => {
  return loadConfig();
});

ipcMain.handle('config:set', (event, config) => {
  return saveConfig(config);
});

// Server status
ipcMain.handle('server:status', () => {
  return {
    running: serverProc !== null,
    port: API_PORT,
    restarts: _serverRestarts
  };
});

ipcMain.handle('server:restart', () => {
  stopServer();
  _serverRestarts = 0;
  setTimeout(startServer, 1000);
  return { ok: true };
});

// Open external links
ipcMain.on('shell:openExternal', (event, url) => {
  shell.openExternal(url);
});

// ─── App Lifecycle ───────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray();

  if (isSetupDone()) {
    // Normal launch — start server, show main window
    startServer();
    await createMainWindow();
  } else {
    // First run — show setup wizard
    showSetupWindow();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    // Keep running in tray on Linux
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    if (isSetupDone()) createMainWindow();
    else showSetupWindow();
  }
});

app.on('before-quit', () => {
  stopServer();
});

// Handle setup completion
ipcMain.on('setup:complete', () => {
  if (setupWindow) {
    setupWindow.close();
    setupWindow = null;
  }
  startServer();
  createMainWindow();
});
