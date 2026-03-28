const { spawn, execSync } = require('child_process');

class ScrcpyManager {
  constructor(parentWindow, constants, config, log) {
    this.win = parentWindow;
    this.C = constants;
    this._config = config;
    this._log = log || { debug() {}, info() {}, warn() {}, error() {} };
    this.proc = null;
    this.wid = null;
    this.title = 'CuttlefishScreen_' + process.pid;
    this._syncTimer = null;
    this._alive = true;
    this._stopping = false;
    this._restartPending = false;
    this._errorThrottleUntil = 0;
    this._startGen = 0;        // generation counter to cancel stale window searches
    this._scrcpyVersion = this._detectScrcpyVersion();
    // Current display dimensions (mutable for resize/fullscreen)
    this._screenW = this.C.SCREEN_WIDTH;
    this._screenH = this.C.SCREEN_HEIGHT;
    this._xOffset = this.C.SCREEN_X_OFFSET;
    this._yOffset = this.C.SCREEN_Y_OFFSET;
  }

  _detectScrcpyVersion() {
    try {
      const out = execSync('scrcpy --version 2>&1', { encoding: 'utf-8', timeout: 3000 });
      const m = out.match(/(\d+)\.(\d+)/);
      if (m) {
        const ver = { major: parseInt(m[1], 10), minor: parseInt(m[2], 10) };
        this._log.info(`scrcpy version: ${ver.major}.${ver.minor}`);
        return ver;
      }
    } catch (_) {}
    return { major: 1, minor: 0 };
  }

  _isScrcpy2() {
    return this._scrcpyVersion.major >= 2;
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────
  start() {
    if (!this._alive || this.proc) return;
    this._stopping = false;
    this._startGen++;          // invalidate any pending window searches from prior start()

    const [wx, wy] = this.win.getPosition();
    const sx = wx + this._xOffset;
    const sy = wy + this._yOffset;

    const serial = (this._config && this._config.get('adbSerial')) || this.C.ADB_SERIAL;
    const scrcpyCfg = (this._config && this._config.get('scrcpy')) || {};

    const args = [
      '-s', serial,
      '--window-borderless',
      '--window-title=' + this.title,
      '--window-x=' + sx,
      '--window-y=' + sy,
      '--window-width=' + this._screenW,
      '--window-height=' + this._screenH,
      '--max-fps=' + (scrcpyCfg.maxFps || 60),
      '--video-bit-rate=' + (scrcpyCfg.videoBitRate || '8M'),
      ...(scrcpyCfg.noAudio !== false ? ['--no-audio'] : []),
      ...(scrcpyCfg.stayAwake !== false ? ['--stay-awake'] : []),
      '--render-driver=' + (scrcpyCfg.renderDriver || 'software'),
    ];

    // Low-latency buffer flags — flag name changed in scrcpy 3.0
    if (this._isScrcpy2()) {
      const buf = scrcpyCfg.displayBuffer != null ? scrcpyCfg.displayBuffer : 0;
      const bufFlag = this._scrcpyVersion.major >= 3 ? '--video-buffer=' : '--display-buffer=';
      args.push(bufFlag + buf);
      if (scrcpyCfg.noAudio === false) {
        args.push('--audio-buffer=' + (scrcpyCfg.audioBuffer != null ? scrcpyCfg.audioBuffer : 50));
      }
    }

    // Video codec (h264 default, h265 for lower bandwidth)
    const codec = scrcpyCfg.videoCodec || 'h264';
    if (codec !== 'h264') {
      args.push('--video-codec=' + codec);
    }

    // Clean shutdown
    if (scrcpyCfg.powerOffOnClose) {
      args.push('--power-off-on-close');
    }

    this._log.info('Starting scrcpy:', args.join(' '));
    this.proc = spawn('scrcpy', args, { stdio: 'pipe', detached: false });

    this.proc.stderr.on('data', (d) => {
      const msg = d.toString().trim();
      if (!msg.includes('ERROR')) return;
      this._log.error(msg);
      // Suppress known transient errors that auto-restart handles
      if (/DeadSystemException|BadWindow|bad window|InvocationTargetException|Could not invoke method/i.test(msg)) return;
      // Throttle error notifications — max one every 5 seconds
      const now = Date.now();
      if (now < this._errorThrottleUntil) return;
      this._errorThrottleUntil = now + 5000;
      // Map raw stderr to user-friendly messages
      let userMsg = 'Display session interrupted';
      if (/connection refused|cannot connect|device not found/i.test(msg)) {
        userMsg = 'Device connection lost';
      } else if (/timeout|timed out/i.test(msg)) {
        userMsg = 'Device connection timed out';
      }
      this._notify('error', userMsg);
    });

    this.proc.on('error', (err) => {
      this._log.error('Spawn error:', err.message);
      this._notify('error', err.message);
    });

    this.proc.on('exit', (code) => {
      this._log.info('Exited with code', code);
      const wasStopping = this._stopping;
      const restartPending = this._restartPending;
      this._stopping = false;
      this._restartPending = false;
      this.proc = null;
      this.wid = null;
      // Suppress error toasts during restart recovery
      this._errorThrottleUntil = Date.now() + 5000;
      if (restartPending && this._alive) {
        this._notify('status', 'recovering');
        setTimeout(() => this.start(), 250);
        return;
      }
      // Auto-restart on any unexpected exit, including code 0 after device-side failures.
      if (!wasStopping && this._alive) {
        this._notify('status', 'recovering');
        setTimeout(() => this.start(), 2000);
        return;
      }
      this._notify('status', 'disconnected');
    });

    this._waitForWindow(0, this._startGen);
  }

  stop(permanent = true) {
    this._alive = !permanent;
    this._stopping = true;
    if (this._syncTimer) clearInterval(this._syncTimer);
    this._syncTimer = null;
    if (this.proc) {
      try { this.proc.kill('SIGTERM'); } catch (_) {}
    }
    if (this.wid) {
      try { this._xdo('windowclose', this.wid); } catch (_) {}
      this.wid = null;
    }
  }

  restart() {
    this._alive = true;
    if (!this.proc) {
      this.start();
      return;
    }

    this._restartPending = true;
    this.stop(false);
  }

  // ── Window discovery ─────────────────────────────────────────────────────
  _waitForWindow(attempt, gen) {
    if (attempt > 60 || !this._alive || gen !== this._startGen) {
      if (attempt > 60) {
        this._notify('error', 'Timed out waiting for scrcpy window');
      }
      return;
    }

    setTimeout(() => {
      if (gen !== this._startGen) return;     // stale chain — abort
      try {
        const res = execSync(
          `xdotool search --name "${this.title}"`,
          { encoding: 'utf-8', timeout: 2000 }
        ).trim();

        if (res) {
          const ids = res.split('\n').filter(Boolean);
          this.wid = ids[ids.length - 1];
          this._log.info('Found window', this.wid);
          this._onWindowReady();
          return;
        }
      } catch (_) {}

      this._waitForWindow(attempt + 1, gen);
    }, 200);
  }

  _onWindowReady() {
    this.syncPosition();
    this._resizeWindow();
    this.raise();
    this._notify('status', 'connected');

    // Periodic position sync as a safety net (500ms for responsive tracking)
    if (this._syncTimer) clearInterval(this._syncTimer);
    this._syncTimer = setInterval(() => this.syncPosition(), 500);
  }

  // ── Position & Window management ─────────────────────────────────────────
  syncPosition() {
    if (!this.wid || !this.win || this.win.isDestroyed()) return;
    try {
      const [wx, wy] = this.win.getPosition();
      const x = wx + this._xOffset;
      const y = wy + this._yOffset;
      this._xdo('windowmove', this.wid, x, y);
    } catch (_) {}
  }

  _resizeWindow() {
    if (!this.wid) return;
    try {
      this._xdo('windowsize', this.wid, this._screenW, this._screenH);
    } catch (_) {}
  }

  /**
   * Update layout dimensions and reposition/resize the scrcpy window.
   * Called by main process when Electron window is resized or display mode changes.
   */
  updateLayout(layout) {
    this._screenW = layout.screenWidth;
    this._screenH = layout.screenHeight;
    this._xOffset = layout.xOffset;
    this._yOffset = layout.yOffset;
    if (this.wid) {
      this._resizeWindow();
      this.syncPosition();
    }
  }

  getScreenDimensions() {
    return { width: this._screenW, height: this._screenH };
  }

  raise() {
    if (!this.wid) return;
    try {
      this._xdo('windowactivate', this.wid);
      this._xdo('windowraise', this.wid);
    } catch (_) {}
  }

  hide() {
    if (!this.wid) return;
    try {
      this._xdo('windowminimize', this.wid);
    } catch (_) {}
  }

  show() {
    if (!this.wid) return;
    try {
      this._xdo('windowactivate', this.wid);
    } catch (_) {}
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  _xdo(...args) {
    execSync('xdotool ' + args.join(' '), { timeout: 2000 });
  }

  _notify(channel, data) {
    try {
      if (this.win && !this.win.isDestroyed() && this.win.webContents && !this.win.webContents.isDestroyed()) {
        this.win.webContents.send('scrcpy:' + channel, data);
      }
    } catch (_) {}
  }
}

module.exports = ScrcpyManager;
