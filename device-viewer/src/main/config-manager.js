const { app } = require('electron');
const path = require('path');
const fs = require('fs');

const DEFAULTS = {
  adbSerial: '0.0.0.0:6520',
  scrcpy: {
    maxFps: 60,
    videoBitRate: '8M',
    noAudio: true,
    stayAwake: true,
    renderDriver: 'software',
    displayBuffer: 0,
    audioBuffer: 50,
    videoCodec: 'h264',
    powerOffOnClose: false,
  },
  display: {
    deviceWidth: 720,
    deviceHeight: 1280,
    screenWidth: 360,
    screenHeight: 640,
    mode: 'phone',       // 'phone' | 'maximized' | 'fullscreen'
    autoFit: true,
  },
  logLevel: 'info',
  screenshotDir: '',  // empty = use system temp
  window: {
    x: null,
    y: null,
    width: null,
    height: null,
  },
};

class ConfigManager {
  constructor() {
    this._configPath = path.join(app.getPath('userData'), 'config.json');
    this._data = {};
    this._load();
  }

  _load() {
    try {
      if (fs.existsSync(this._configPath)) {
        const raw = fs.readFileSync(this._configPath, 'utf-8');
        const parsed = JSON.parse(raw);
        this._data = this._merge(DEFAULTS, parsed);
      } else {
        this._data = JSON.parse(JSON.stringify(DEFAULTS));
        this._save();
      }
    } catch {
      this._data = JSON.parse(JSON.stringify(DEFAULTS));
    }
  }

  _merge(defaults, overrides) {
    const result = JSON.parse(JSON.stringify(defaults));
    for (const key of Object.keys(overrides)) {
      if (!(key in defaults)) continue; // ignore unknown keys
      if (
        typeof defaults[key] === 'object' &&
        defaults[key] !== null &&
        !Array.isArray(defaults[key]) &&
        typeof overrides[key] === 'object' &&
        overrides[key] !== null
      ) {
        result[key] = this._merge(defaults[key], overrides[key]);
      } else {
        result[key] = overrides[key];
      }
    }
    return result;
  }

  _save() {
    try {
      const dir = path.dirname(this._configPath);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(this._configPath, JSON.stringify(this._data, null, 2), 'utf-8');
    } catch {
      // Logging not yet available during early init; fail silently
    }
  }

  get(keyPath) {
    const keys = keyPath.split('.');
    let val = this._data;
    for (const k of keys) {
      if (val === null || val === undefined || typeof val !== 'object') return undefined;
      val = val[k];
    }
    return val;
  }

  set(keyPath, value) {
    const keys = keyPath.split('.');
    let obj = this._data;
    for (let i = 0; i < keys.length - 1; i++) {
      if (!(keys[i] in obj) || typeof obj[keys[i]] !== 'object') {
        obj[keys[i]] = {};
      }
      obj = obj[keys[i]];
    }
    obj[keys[keys.length - 1]] = value;
    this._save();
  }

  getAll() {
    return JSON.parse(JSON.stringify(this._data));
  }
}

module.exports = ConfigManager;
