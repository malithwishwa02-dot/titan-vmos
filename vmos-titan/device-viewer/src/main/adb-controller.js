const { execFile } = require('child_process');
const path = require('path');
const { AppError } = require('./error-handler');

// Characters/patterns that must never appear in shell commands
const DANGEROUS_PATTERNS = /[;|&`$(){}!><\n\r\\]/;

class AdbController {
  constructor(serial, log) {
    this.serial = serial;
    this._log = log || { debug() {}, info() {}, warn() {}, error() {} };
    this._queue = Promise.resolve();
  }

  // Queue commands so only one ADB call runs at a time per device
  _enqueue(fn) {
    this._queue = this._queue.then(fn, fn);
    return this._queue;
  }

  _exec(args, retries = 2) {
    return new Promise((resolve, reject) => {
      const attempt = (remaining) => {
        execFile('adb', ['-s', this.serial, ...args], { timeout: 15000 }, (err, stdout, _stderr) => {
          if (!err) return resolve(stdout.trim());
          if (remaining > 0) {
            this._log.warn(`ADB retry (${retries - remaining + 1}/${retries}):`, args.join(' '));
            setTimeout(() => attempt(remaining - 1), 500);
          } else {
            this._log.error('ADB command failed:', args.join(' '), err.message);
            reject(new AppError('ADB_EXEC', 'ADB command failed', err.message));
          }
        });
      };
      attempt(retries);
    });
  }

  _run(args) {
    return this._enqueue(() => this._exec(args));
  }

  _key(code) { return this._run(['shell', 'input', 'keyevent', String(code)]); }

  pressHome()   { return this._key(3);   }
  pressBack()   { return this._key(4);   }
  pressRecent() { return this._key(187); }
  pressPower()  { return this._key(26);  }
  volumeUp()    { return this._key(24);  }
  volumeDown()  { return this._key(25);  }

  async rotate() {
    await this._run(['shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0']);
    const cur = await this._run(['shell', 'settings', 'get', 'system', 'user_rotation']);
    const next = (parseInt(cur, 10) || 0) === 0 ? 1 : 0;
    return this._run(['shell', 'settings', 'put', 'system', 'user_rotation', String(next)]);
  }

  async screenshot(saveDir) {
    const ts = Date.now();
    const remote = `/sdcard/screenshot_${ts}.png`;
    const dir = saveDir || require('os').tmpdir();
    const local = path.join(dir, `cuttlefish_screenshot_${ts}.png`);
    await this._run(['shell', 'screencap', '-p', remote]);
    await this._run(['pull', remote, local]);
    await this._run(['shell', 'rm', remote]);
    this._log.info('Screenshot saved:', local);
    return local;
  }

  shell(cmd) {
    if (typeof cmd !== 'string' || cmd.length === 0) {
      return Promise.reject(new AppError('ADB_SHELL', 'Empty command', 'shell() called with empty input'));
    }
    if (DANGEROUS_PATTERNS.test(cmd)) {
      return Promise.reject(new AppError('ADB_SHELL', 'Command rejected', `Unsafe characters in: ${cmd}`));
    }
    return this._run(['shell', ...cmd.split(/\s+/).filter(Boolean)]);
  }

  // Install an APK on the device
  install(apkPath) {
    this._log.info('Installing APK:', apkPath);
    return this._run(['install', '-r', apkPath]);
  }

  // Push a file to the device
  push(localPath, remotePath = '/sdcard/Download/') {
    this._log.info('Pushing file:', localPath, '→', remotePath);
    return this._run(['push', localPath, remotePath]);
  }

  // Check if device is reachable
  async getState() {
    try {
      const state = await this._exec(['get-state'], 1);
      return state; // 'device', 'offline', 'unauthorized', etc.
    } catch {
      return 'unreachable';
    }
  }
}

module.exports = AdbController;
