/**
 * VMOS Titan — Preload Script
 * 
 * Securely exposes platform info and IPC channels to the renderer process.
 * All API communication goes through the local Titan API server.
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose safe APIs to renderer
contextBridge.exposeInMainWorld('vmosAPI', {
  // Platform info
  platform: process.platform,
  version: '1.0.0',
  
  // Setup IPC
  getSystemInfo: () => ipcRenderer.invoke('setup:getInfo'),
  saveSetup: (data) => ipcRenderer.invoke('setup:save', data),
  testCredentials: (data) => ipcRenderer.invoke('setup:testCredentials', data),
  completeSetup: () => ipcRenderer.send('setup:complete'),
  
  // Config IPC
  getConfig: () => ipcRenderer.invoke('config:get'),
  setConfig: (config) => ipcRenderer.invoke('config:set', config),
  
  // Server IPC
  getServerStatus: () => ipcRenderer.invoke('server:status'),
  restartServer: () => ipcRenderer.invoke('server:restart'),
  
  // Navigation events from menu
  onNavigate: (callback) => {
    ipcRenderer.on('navigate', (event, section) => callback(section));
  },
  
  // External links
  openExternal: (url) => ipcRenderer.send('shell:openExternal', url),
});

// Also expose as titanDesktop for compatibility with existing console code
contextBridge.exposeInMainWorld('titanDesktop', {
  platform: process.platform,
  version: '1.0.0',
  backend: 'vmos-pro',
  
  // API configuration
  apiToken: process.env.TITAN_API_SECRET || '',
  apiBase: process.env.TITAN_API_BASE || 'http://127.0.0.1:8082/api',
  
  // VMOS Cloud config (credentials stored securely)
  vmosCloud: {
    baseUrl: 'https://api.vmoscloud.com',
  },
  
  // Setup IPC
  getSystemInfo: () => ipcRenderer.invoke('setup:getInfo'),
  runSetup: () => ipcRenderer.invoke('setup:run'),
});
