/**
 * Titan VMOS Console — Preload Script
 * 
 * Exposes secure IPC bridge to renderer for VMOS Pro cloud operations.
 */
const { contextBridge, ipcRenderer } = require('electron');
const path = require('path');

// Determine API base from environment, with fallback
const API_PORT = process.env.TITAN_API_PORT || '8081';
const API_BASE = process.env.TITAN_API_BASE || `http://127.0.0.1:${API_PORT}/api`;

contextBridge.exposeInMainWorld('titanVMOS', {
  platform: process.platform,
  version: '13.0.0',
  backend: 'vmos-pro',
  
  // API configuration
  apiBase: API_BASE,
  
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
