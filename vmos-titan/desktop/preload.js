// Preload — exposes platform info and setup IPC to renderer.
// The console runs entirely through the API on localhost.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('titanDesktop', {
  platform: process.platform,
  version: '13.0.0',
  backend: 'cuttlefish',
  // API auth bridge — fixes console→API auto-auth from Electron
  apiToken: process.env.TITAN_API_SECRET || '',
  apiBase: process.env.TITAN_API_BASE || 'http://127.0.0.1:8080/api',
  cvd: {
    binDir: process.env.CVD_BIN_DIR || '/opt/titan/cuttlefish/cf/bin',
    homeBase: process.env.CVD_HOME_BASE || '/opt/titan/cuttlefish',
    imagesDir: process.env.CVD_IMAGES_DIR || '/opt/titan/cuttlefish/images',
  },
  // Setup IPC
  getSystemInfo: () => ipcRenderer.invoke('setup:getInfo'),
  runSetup: () => ipcRenderer.invoke('setup:run'),
  launchConsole: () => ipcRenderer.invoke('setup:launch'),
  onSetupProgress: (callback) => {
    ipcRenderer.on('setup:progress', (_event, msg) => callback(msg));
  },
  // Device View IPC — launches standalone device-viewer app
  openDevice: () => ipcRenderer.invoke('titan:launchCuttlefishApp'),
});
