const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cuttlefish', {
  // Device controls
  home:       () => ipcRenderer.invoke('adb:home'),
  back:       () => ipcRenderer.invoke('adb:back'),
  recent:     () => ipcRenderer.invoke('adb:recent'),
  power:      () => ipcRenderer.invoke('adb:power'),
  volumeUp:   () => ipcRenderer.invoke('adb:volumeUp'),
  volumeDown: () => ipcRenderer.invoke('adb:volumeDown'),
  rotate:     () => ipcRenderer.invoke('adb:rotate'),
  screenshot: () => ipcRenderer.invoke('adb:screenshot'),
  shell:    (cmd) => ipcRenderer.invoke('adb:shell', cmd),

  // Window controls
  closeWindow:      () => ipcRenderer.invoke('window:close'),
  minimizeWindow:   () => ipcRenderer.invoke('window:minimize'),
  maximizeWindow:   () => ipcRenderer.invoke('window:maximize'),
  fullscreenWindow: () => ipcRenderer.invoke('window:fullscreen'),
  setDisplayMode:  (mode) => ipcRenderer.invoke('window:setDisplayMode', mode),
  getDisplayMode:   () => ipcRenderer.invoke('window:getDisplayMode'),
  isMaximized:      () => ipcRenderer.invoke('window:isMaximized'),
  isFullScreen:     () => ipcRenderer.invoke('window:isFullScreen'),

  // Scrcpy controls
  restartScrcpy: () => ipcRenderer.invoke('scrcpy:restart'),

  // Titan API (backend connection — separate service)
  titanHealth:     () => ipcRenderer.invoke('titan:health'),
  titanDevice:     () => ipcRenderer.invoke('titan:device'),
  titanDevices:    () => ipcRenderer.invoke('titan:devices'),
  titanConsoleUrl: () => ipcRenderer.invoke('titan:consoleUrl'),

  // Config
  configGet:    (key) => ipcRenderer.invoke('config:get', key),
  configSet:    (key, value) => ipcRenderer.invoke('config:set', key, value),
  configGetAll: () => ipcRenderer.invoke('config:getAll'),

  // Events from main process
  onStatus:      (cb) => ipcRenderer.on('scrcpy:status', (_, s) => cb(s)),
  onError:       (cb) => ipcRenderer.on('scrcpy:error',  (_, e) => cb(e)),
  onAppError:    (cb) => ipcRenderer.on('app:error', (_, e) => cb(e)),
  onLayout:      (cb) => ipcRenderer.on('display:layout', (_, l) => cb(l)),
  onTitanHealth: (cb) => ipcRenderer.on('titan:health', (_, h) => cb(h)),
});
