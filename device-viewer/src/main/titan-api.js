'use strict';
/**
 * Titan API Client — lightweight bridge between Titan Console and Titan API backend.
 * Keeps the apps connected but separate: Console monitors health, device state,
 * and system info from the API without embedding any API UI.
 */

const http = require('http');
const path = require('path');
const fs   = require('fs');

const DEFAULT_BASE = 'http://127.0.0.1:8080';
const HEALTH_INTERVAL = 10_000;   // poll health every 10s
const REQUEST_TIMEOUT  = 5_000;   // 5s per request

class TitanApi {
  constructor(logger, notify) {
    this._log = logger;
    this._notify = notify;           // (channel, data) => mainWindow.webContents.send(...)
    this._base = DEFAULT_BASE;
    this._token = '';
    this._healthTimer = null;
    this._lastHealth = null;
    this._connected = false;

    this._loadEnv();
  }

  /* ── Bootstrap ──────────────────────────────────────────────────────── */

  /** Read API URL + token from /opt/titan/.env or process.env */
  _loadEnv() {
    // Try reading .env file directly (same as start.sh)
    const envPaths = ['/opt/titan/.env', path.join(process.env.TITAN_DIR || '/opt/titan', '.env')];
    for (const p of envPaths) {
      try {
        const lines = fs.readFileSync(p, 'utf8').split('\n');
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith('#')) continue;
          const eq = trimmed.indexOf('=');
          if (eq < 1) continue;
          const key = trimmed.slice(0, eq).trim();
          const val = trimmed.slice(eq + 1).trim();
          if (key === 'TITAN_API_SECRET' && val) this._token = val;
          if (key === 'TITAN_API_PORT' && val)   this._base = `http://127.0.0.1:${val}`;
        }
        break;
      } catch { /* file not found, try next */ }
    }

    // Env vars override file
    if (process.env.TITAN_API_SECRET) this._token = process.env.TITAN_API_SECRET;
    if (process.env.TITAN_API_PORT)   this._base = `http://127.0.0.1:${process.env.TITAN_API_PORT}`;

    this._log.info(`API base: ${this._base}, token: ${this._token ? '***' + this._token.slice(-6) : 'none'}`);
  }

  /** Start periodic health polling */
  startHealthPoll() {
    this._pollHealth();
    this._healthTimer = setInterval(() => this._pollHealth(), HEALTH_INTERVAL);
  }

  /** Stop polling (on app quit) */
  stop() {
    if (this._healthTimer) {
      clearInterval(this._healthTimer);
      this._healthTimer = null;
    }
  }

  /* ── Health ─────────────────────────────────────────────────────────── */

  async _pollHealth() {
    try {
      const data = await this._get('/health');
      const wasConnected = this._connected;
      this._connected = true;
      this._lastHealth = data;
      this._notify('titan:health', {
        connected: true,
        status: data.status,
        adb:    data.checks?.adb || {},
        ollama: data.checks?.ollama || {},
        disk:   data.checks?.disk || {},
        memory: data.checks?.memory || {},
      });
      if (!wasConnected) this._log.info('Titan API connected');
    } catch (err) {
      const wasConnected = this._connected;
      this._connected = false;
      this._lastHealth = null;
      this._notify('titan:health', { connected: false });
      if (wasConnected) this._log.warn('Titan API disconnected:', err.message);
    }
  }

  /** Return cached health (for sync IPC) */
  getHealth() {
    if (!this._connected || !this._lastHealth) return { connected: false };
    return {
      connected: true,
      status: this._lastHealth.status,
      adb:    this._lastHealth.checks?.adb || {},
      ollama: this._lastHealth.checks?.ollama || {},
      disk:   this._lastHealth.checks?.disk || {},
      memory: this._lastHealth.checks?.memory || {},
    };
  }

  /* ── Device info ────────────────────────────────────────────────────── */

  /** Get the permanent desktop Cuttlefish device info */
  async getDevice() {
    return this._get('/api/devices/permanent');
  }

  /** Get all devices */
  async getDevices() {
    return this._get('/api/devices');
  }

  /* ── Admin ──────────────────────────────────────────────────────────── */

  /** Get the web console URL (for "Open in Browser" action) */
  getConsoleUrl() {
    return this._base;
  }

  /* ── HTTP primitives ────────────────────────────────────────────────── */

  _get(urlPath) {
    return this._request('GET', urlPath);
  }

  _request(method, urlPath) {
    return new Promise((resolve, reject) => {
      const url = new URL(urlPath, this._base);
      const headers = { 'Accept': 'application/json' };
      if (this._token && !urlPath.startsWith('/health')) {
        headers['Authorization'] = `Bearer ${this._token}`;
      }

      const req = http.request(url, { method, headers, timeout: REQUEST_TIMEOUT }, (res) => {
        let body = '';
        res.on('data', chunk => { body += chunk; });
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try { resolve(JSON.parse(body)); }
            catch { resolve(body); }
          } else {
            reject(new Error(`API ${res.statusCode}: ${body.slice(0, 200)}`));
          }
        });
      });

      req.on('error', reject);
      req.on('timeout', () => { req.destroy(); reject(new Error('API request timeout')); });
      req.end();
    });
  }
}

module.exports = TitanApi;
