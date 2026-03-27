/**
 * Titan VMOS Console — Main Electron Process
 * 
 * Standalone desktop application for VMOS Pro cloud device management
 * with full Genesis Studio integration.
 */

const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

// ─── Path Resolution (packaged vs dev) ────────────────────────────────
const IS_PACKAGED = app.isPackaged;
const RESOURCES = IS_PACKAGED ? process.resourcesPath : path.resolve(__dirname, '..');
const USER_DATA = app.getPath('userData');        // ~/.config/titan-vmos-console
const TITAN_DATA = IS_PACKAGED
  ? (process.env.TITAN_DATA || '/opt/titan/data')
  : path.join(USER_DATA, 'data');
const VENV_DIR = path.join(USER_DATA, 'venv');
const SERVER_DIR = path.join(RESOURCES, 'server');
const CORE_DIR = path.join(RESOURCES, 'core');
const SETUP_DONE = path.join(USER_DATA, '.setup-done');

// ─── Config ───────────────────────────────────────────────────────────
const API_PORT = process.env.TITAN_API_PORT || 8081;  // Different port to avoid conflicts
const API_URL = `http://127.0.0.1:${API_PORT}`;

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
function ensureDir(d) { fs.mkdirSync(d, { recursive: true }); }

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
      // Strip surrounding quotes
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
  // Only allow standard Python executable names to prevent path injection
  const allowedPythonCmds = ['python3', 'python'];
  for (const cmd of allowedPythonCmds) {
    try {
      // Use execFileSync with explicit arguments to avoid shell injection
      const whichResult = execFileSync('/usr/bin/which', [cmd], { timeout: 5000 }).toString().trim();
      if (!whichResult || !whichResult.startsWith('/')) {
        continue;  // Skip if not an absolute path
      }
      // Use the absolute path for version check
      const ver = execFileSync(whichResult, ['--version'], { timeout: 5000 }).toString().trim();
      const match = ver.match(/Python\s+(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 10))) {
        return { cmd, version: ver, path: whichResult };
      }
    } catch (_) { /* not found */ }
  }
  return null;
}

function getUvicornCmd() {
  // Prefer venv uvicorn if it exists
  const venvUvi = path.join(VENV_DIR, 'bin', 'uvicorn');
  if (fs.existsSync(venvUvi)) return venvUvi;
  // Fallback: system-installed or legacy /opt/titan/venv
  const legacyUvi = path.join(RESOURCES, 'venv', 'bin', 'uvicorn');
  if (fs.existsSync(legacyUvi)) return legacyUvi;
  return 'uvicorn';
}

function isSetupDone() {
  return fs.existsSync(SETUP_DONE) && fs.existsSync(path.join(VENV_DIR, 'bin', 'uvicorn'));
}

// ─── Poll until the API server is accepting connections ───────────────
function waitForServer(retries = 40, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      const req = http.get(API_URL, (res) => { resolve(); req.destroy(); });
      req.on('error', () => {
        attempts++;
        if (attempts >= retries) return reject(new Error('Server did not start'));
        setTimeout(check, interval);
      });
      req.setTimeout(400, () => req.destroy());
    };
    check();
  });
}

// ─── Start the uvicorn/FastAPI backend ───────────────────────────────
function startServer() {
  return new Promise((resolve) => {
    // If something is already listening on the port, skip.
    const probe = http.get(API_URL, (res) => {
      probe.destroy();
      resolve(true);
    });
    probe.on('error', () => {
      // Nothing listening — start it ourselves
      const dotEnvVars = loadDotEnv(path.join(USER_DATA, '.env'));
      // Also try project-level .env.example fallback
      const projEnv = loadDotEnv(path.join(RESOURCES, '.env.example'));
      const env = {
        ...process.env,
        ...projEnv,
        ...dotEnvVars,
        // Build PYTHONPATH from available directories only
        PYTHONPATH: [SERVER_DIR, CORE_DIR].filter(d => fs.existsSync(d)).join(':'),
        TITAN_DATA,
        TITAN_API_PORT: String(API_PORT),
        // VMOS Pro specific environment variables
        VMOS_API_HOST: dotEnvVars.VMOS_API_HOST || process.env.VMOS_API_HOST || 'api.vmoscloud.com',
      };

      serverProc = spawn(
        getUvicornCmd(),
        [
          'titan_api:app',
          '--host', '127.0.0.1',
          '--port', String(API_PORT),
          '--workers', '1',
        ],
        { cwd: SERVER_DIR, env, detached: false }
      );
      serverProc.stdout.on('data', (d) => console.log('[server]', d.toString().trim()));
      serverProc.stderr.on('data', (d) => console.error('[server]', d.toString().trim()));
      serverProc.on('exit', (code) => {
        if (code !== 0 && code !== null) {
          if (_serverRestarts < MAX_SERVER_RESTARTS) {
            _serverRestarts++;
            const delay = Math.pow(2, _serverRestarts) * 1000;
            console.error(`[server] Crashed (code ${code}), restarting in ${delay}ms (attempt ${_serverRestarts}/${MAX_SERVER_RESTARTS})`);
            setTimeout(() => {
              startServer().then(() => {
                if (mainWindow && !mainWindow.isDestroyed()) mainWindow.reload();
              });
            }, delay);
          } else {
            dialog.showErrorBox('Titan Server Error',
              `The backend server crashed ${MAX_SERVER_RESTARTS} times (last code ${code}).\nCheck the terminal for details.`);
          }
        }
      });
      resolve(false);
    });
    probe.setTimeout(2000, () => { probe.destroy(); });
  });
}

// ─── Setup Window (first-run) ────────────────────────────────────────
function showSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 680,
    height: 600,
    title: 'Titan VMOS Console — Setup',
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

// ─── IPC Handlers ────────────────────────────────────────────────────
ipcMain.handle('setup:getInfo', () => {
  const python = findPython();
  let adbFound = false;
  try {
    // Use execFileSync to avoid shell injection
    execFileSync('/usr/bin/which', ['adb'], { timeout: 3000 });
    adbFound = true;
  } catch (_) {}
  return {
    python: python ? python : null,
    adb: adbFound,
    venvExists: fs.existsSync(path.join(VENV_DIR, 'bin', 'python3')),
    dataDir: TITAN_DATA,
    venvDir: VENV_DIR,
    isPackaged: IS_PACKAGED,
    apiPort: API_PORT,
    vmosHost: process.env.VMOS_API_HOST || 'api.vmoscloud.com',
  };
});

ipcMain.handle('setup:run', async (event) => {
  const python = findPython();
  if (!python) return { ok: false, error: 'Python 3.10+ not found. Install python3 and try again.' };

  const send = (msg) => {
    if (setupWindow && !setupWindow.isDestroyed()) {
      setupWindow.webContents.send('setup:progress', msg);
    }
  };

  try {
    // 1. Create data directories
    send('Creating data directories...');
    ensureDir(TITAN_DATA);
    ensureDir(path.join(TITAN_DATA, 'devices'));
    ensureDir(path.join(TITAN_DATA, 'profiles'));
    ensureDir(path.join(TITAN_DATA, 'config'));
    ensureDir(path.join(TITAN_DATA, 'forge_gallery'));
    ensureDir(path.join(TITAN_DATA, 'vmos_sessions'));

    // 2. Copy .env if not exists
    const envPath = path.join(USER_DATA, '.env');
    if (!fs.existsSync(envPath)) {
      const envExample = path.join(RESOURCES, '.env.example');
      if (fs.existsSync(envExample)) {
        fs.copyFileSync(envExample, envPath);
        send('Created .env from template');
      }
    }

    // 3. Create Python virtual environment
    send('Creating Python virtual environment...');
    if (!fs.existsSync(path.join(VENV_DIR, 'bin', 'python3'))) {
      // Use execFileSync with absolute path from findPython
      execFileSync(python.path, ['-m', 'venv', VENV_DIR], { timeout: 60000 });
    }
    send('Virtual environment ready');

    // 4. Install pip dependencies
    send('Installing Python dependencies (this may take a minute)...');
    const pipCmd = path.join(VENV_DIR, 'bin', 'pip');
    const reqFile = path.join(RESOURCES, 'server', 'requirements.txt');
    if (fs.existsSync(reqFile)) {
      execFileSync(pipCmd, ['install', '--upgrade', 'pip', '-q'], { timeout: 120000 });
      execFileSync(pipCmd, ['install', '-r', reqFile, '-q'], { timeout: 300000 });
    }
    send('Dependencies installed');

    // 5. Mark setup as done
    fs.writeFileSync(SETUP_DONE, JSON.stringify({
      version: '13.0.0',
      python: python.version,
      mode: 'vmos-pro',
      timestamp: new Date().toISOString(),
    }));
    send('Setup complete!');
    return { ok: true };
  } catch (err) {
    send('Error: ' + err.message);
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('setup:saveVmosCredentials', async (event, credentials) => {
  try {
    const envPath = path.join(USER_DATA, '.env');
    let envContent = '';
    if (fs.existsSync(envPath)) {
      envContent = fs.readFileSync(envPath, 'utf-8');
    }

    // Validate and sanitize credentials to prevent env injection
    const sanitizeEnvValue = (val) => {
      if (typeof val !== 'string') return '';
      // Remove newlines, quotes, and special characters that could break .env format
      return val.replace(/[\n\r"'\\`$]/g, '').trim();
    };

    const apiKey = sanitizeEnvValue(credentials.apiKey || '');
    const apiSecret = sanitizeEnvValue(credentials.apiSecret || '');
    const apiHost = sanitizeEnvValue(credentials.apiHost || 'api.vmoscloud.com');

    // Validate API key format (alphanumeric with common special chars)
    if (apiKey && !/^[A-Za-z0-9_\-]{8,64}$/.test(apiKey)) {
      return { ok: false, error: 'Invalid API key format' };
    }

    // Validate API secret format (alphanumeric with common special chars)
    if (apiSecret && !/^[A-Za-z0-9_\-]{8,128}$/.test(apiSecret)) {
      return { ok: false, error: 'Invalid API secret format' };
    }

    // Validate API host format
    if (apiHost && !/^[a-z0-9][a-z0-9\-\.]{0,62}\.[a-z]{2,}$/i.test(apiHost)) {
      return { ok: false, error: 'Invalid API host format' };
    }

    // Update or add VMOS credentials
    const lines = envContent.split('\n');
    const updates = {
      'VMOS_API_KEY': apiKey,
      'VMOS_API_SECRET': apiSecret,
      'VMOS_API_HOST': apiHost,
    };

    for (const [key, value] of Object.entries(updates)) {
      const idx = lines.findIndex(l => l.startsWith(`${key}=`));
      const line = `${key}=${value}`;
      if (idx >= 0) {
        lines[idx] = line;
      } else {
        lines.push(line);
      }
    }

    fs.writeFileSync(envPath, lines.join('\n'));
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('setup:launch', async () => {
  // Close setup window, start server, open main console
  if (setupWindow) setupWindow.close();
  startServer();
  await createMainWindow();
});

// ─── VMOS-specific IPC Handlers ──────────────────────────────────────
ipcMain.handle('vmos:testConnection', async () => {
  try {
    const dotEnvVars = loadDotEnv(path.join(USER_DATA, '.env'));
    const apiKey = dotEnvVars.VMOS_API_KEY || process.env.VMOS_API_KEY;
    const apiSecret = dotEnvVars.VMOS_API_SECRET || process.env.VMOS_API_SECRET;
    
    if (!apiKey || !apiSecret) {
      return { ok: false, error: 'VMOS API credentials not configured' };
    }
    
    // Return success if credentials exist - actual test happens via API
    return { ok: true, hasCredentials: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('app:openExternal', (_, url) => {
  shell.openExternal(url).catch(console.error);
});

ipcMain.handle('app:getEnv', () => {
  const dotEnvVars = loadDotEnv(path.join(USER_DATA, '.env'));
  return {
    vmosApiKey: dotEnvVars.VMOS_API_KEY || '',
    vmosApiHost: dotEnvVars.VMOS_API_HOST || 'api.vmoscloud.com',
    apiPort: API_PORT,
  };
});

// ─── Main Console Window ─────────────────────────────────────────────
async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    minWidth: 1000,
    minHeight: 700,
    title: 'Titan V13.0 — VMOS Pro Cloud Console',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      // webSecurity is enabled by default - we load local files only
    },
    show: false,
    autoHideMenuBar: true,
  });

  // Add debug logging
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('Main window page loaded successfully');
  });
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    console.error('Main window failed to load:', errorCode, errorDescription);
  });

  // Show a loading screen while the server starts
  mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        body { margin:0; background:#0a0e17; display:flex; flex-direction:column;
               align-items:center; justify-content:center; height:100vh; font-family:system-ui; }
        .logo { width:72px; height:72px; background:linear-gradient(135deg,#8b5cf6,#a855f7);
                border-radius:18px; display:flex; align-items:center; justify-content:center;
                font-size:36px; font-weight:800; color:#fff; margin-bottom:24px; }
        h1 { color:#a855f7; font-size:24px; margin:0 0 8px; }
        p  { color:#64748b; font-size:14px; margin:0 0 24px; }
        .spinner { width:40px; height:40px; border:3px solid #1e293b;
                   border-top-color:#a855f7; border-radius:50%; animation:spin 0.8s linear infinite; }
        @keyframes spin { to { transform:rotate(360deg); } }
      </style>
    </head>
    <body>
      <div class="logo">V</div>
      <h1>Titan VMOS Console</h1>
      <p>Connecting to VMOS Pro Cloud backend…</p>
      <div class="spinner"></div>
    </body>
    </html>
  `));
  mainWindow.show();

  // Wait for server then load the console (with retry)
  const MAX_LOAD_RETRIES = 3;
  let loaded = false;
  try {
    console.log('[titan-vmos] Waiting for server...');
    await waitForServer();
    console.log('[titan-vmos] Server ready, loading console at', API_URL + '/');

    for (let attempt = 1; attempt <= MAX_LOAD_RETRIES && !loaded; attempt++) {
      if (!mainWindow || mainWindow.isDestroyed()) {
        console.error('[titan-vmos] Window destroyed before load, recreating...');
        return;
      }
      try {
        // Load the VMOS-specific console page
        await mainWindow.loadFile(path.join(__dirname, 'vmos-console.html'));
        loaded = true;
        console.log('[titan-vmos] Console loaded successfully');
      } catch (loadErr) {
        console.warn(`[titan-vmos] Load attempt ${attempt}/${MAX_LOAD_RETRIES} failed: ${loadErr.message}`);
        if (attempt < MAX_LOAD_RETRIES) {
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    }
  } catch (err) {
    console.error('[titan-vmos] Error during server wait:', err.message);
  }

  if (!loaded && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
      <!DOCTYPE html>
      <html>
      <head><meta charset="UTF-8">
      <style>body{margin:0;background:#0a0e17;display:flex;flex-direction:column;
        align-items:center;justify-content:center;height:100vh;font-family:system-ui;}
        h1{color:#ef4444;font-size:20px;} p{color:#94a3b8;font-size:13px;max-width:480px;text-align:center;}</style>
      </head>
      <body>
        <h1>⚠ Server not reachable</h1>
        <p>Could not connect to the Titan API on port ${API_PORT}.<br>
        Start the server manually with:<br><code style="color:#a855f7">uvicorn titan_api:app --port ${API_PORT}</code>
        then relaunch the app.</p>
      </body></html>
    `));
  }

  mainWindow.on('closed', () => { mainWindow = null; });

  // Open external links in the system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(`http://127.0.0.1:${API_PORT}`)) {
      // Validate URL before opening
      try {
        const parsed = new URL(url);
        if (!['http:', 'https:'].includes(parsed.protocol)) {
          console.warn('[titan-vmos] Blocked non-http URL:', url);
          return { action: 'deny' };
        }
      } catch (_) {
        console.warn('[titan-vmos] Invalid URL blocked:', url);
        return { action: 'deny' };
      }
      
      // Use shell.openExternal exclusively (no shell fallback)
      shell.openExternal(url).catch((err) => {
        console.warn('[titan-vmos] shell.openExternal failed', err && err.message ? err.message : err);
      });
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
}

// ─── System tray ─────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png');
  if (!fs.existsSync(iconPath)) return;
  tray = new Tray(iconPath);
  tray.setToolTip('Titan V13.0 VMOS Pro Console');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open Console', click: () => { if (mainWindow) mainWindow.show(); else createMainWindow(); } },
    { type: 'separator' },
    { label: 'VMOS Cloud Portal', click: () => shell.openExternal('https://www.vmoscloud.com/') },
    { type: 'separator' },
    { label: 'Quit Titan', click: () => app.quit() },
  ]));
  tray.on('double-click', () => { if (mainWindow) mainWindow.show(); });
}

// ─── App lifecycle ───────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray();

  if (isSetupDone()) {
    // Normal launch — start server, show console
    startServer();
    await createMainWindow();
  } else {
    // First run — show setup wizard
    showSetupWindow();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    if (isSetupDone()) createMainWindow();
    else showSetupWindow();
  }
});

app.on('before-quit', () => {
  if (serverProc) {
    serverProc.kill('SIGTERM');
    serverProc = null;
  }
});
