/**
 * Titan VMOS Console — Preload Script
 * 
 * Exposes secure IPC bridge to renderer for VMOS Pro cloud operations.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('titanVMOS', {
  platform: process.platform,
  version: '13.0.0',
  backend: 'vmos-pro',
  
  // API configuration
  apiBase: process.env.TITAN_API_BASE || 'http://127.0.0.1:8081/api',
  
  // Setup IPC
  getSystemInfo: () => ipcRenderer.invoke('setup:getInfo'),
  runSetup: () => ipcRenderer.invoke('setup:run'),
  saveVmosCredentials: (creds) => ipcRenderer.invoke('setup:saveVmosCredentials', creds),
  launchConsole: () => ipcRenderer.invoke('setup:launch'),
  onSetupProgress: (callback) => {
    ipcRenderer.on('setup:progress', (_event, msg) => callback(msg));
  },
  
  // VMOS-specific operations
  testConnection: () => ipcRenderer.invoke('vmos:testConnection'),
  
  // App operations
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  getEnv: () => ipcRenderer.invoke('app:getEnv'),
});
