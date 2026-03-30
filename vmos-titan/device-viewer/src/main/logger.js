const { app } = require('electron');
const path = require('path');
const fs = require('fs');

const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 };
const MAX_LOG_SIZE = 5 * 1024 * 1024; // 5 MB
const MAX_LOG_FILES = 3;

class Logger {
  constructor(config) {
    this._level = LEVELS[(config && config.get('logLevel')) || 'info'] ?? LEVELS.info;
    this._logDir = path.join(app.getPath('userData'), 'logs');
    this._logFile = path.join(this._logDir, 'titan.log');
    this._stream = null;
    this._initDir();
  }

  _initDir() {
    try {
      if (!fs.existsSync(this._logDir)) fs.mkdirSync(this._logDir, { recursive: true });
      this._stream = fs.createWriteStream(this._logFile, { flags: 'a' });
    } catch {
      // Can't write logs — continue without file logging
    }
  }

  _format(level, module, ...args) {
    const ts = new Date().toISOString();
    const msg = args.map(a =>
      typeof a === 'string' ? a : JSON.stringify(a)
    ).join(' ');
    return `${ts} [${level.toUpperCase()}] [${module}] ${msg}`;
  }

  _write(level, module, args) {
    if (LEVELS[level] < this._level) return;

    const line = this._format(level, module, ...args);

    // Console output
    const consoleFn = level === 'error' ? console.error
      : level === 'warn' ? console.warn
      : console.log;
    consoleFn(line);

    // File output
    if (this._stream) {
      this._stream.write(line + '\n');
      this._maybeRotate();
    }
  }

  _maybeRotate() {
    try {
      const stat = fs.statSync(this._logFile);
      if (stat.size < MAX_LOG_SIZE) return;

      this._stream.end();

      // Rotate: titan.2.log → titan.3.log, titan.1.log → titan.2.log, etc.
      for (let i = MAX_LOG_FILES - 1; i >= 1; i--) {
        const src = path.join(this._logDir, `titan.${i}.log`);
        const dst = path.join(this._logDir, `titan.${i + 1}.log`);
        if (fs.existsSync(src)) fs.renameSync(src, dst);
      }

      fs.renameSync(this._logFile, path.join(this._logDir, 'titan.1.log'));
      this._stream = fs.createWriteStream(this._logFile, { flags: 'a' });
    } catch {
      // Rotation failed; continue
    }
  }

  child(module) {
    const self = this;
    return {
      debug: (...args) => self._write('debug', module, args),
      info:  (...args) => self._write('info', module, args),
      warn:  (...args) => self._write('warn', module, args),
      error: (...args) => self._write('error', module, args),
    };
  }

  close() {
    if (this._stream) {
      this._stream.end();
      this._stream = null;
    }
  }
}

module.exports = Logger;
