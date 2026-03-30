#!/usr/bin/env python3
"""
Titan — Web-Based Phone Scanner
================================
Opens a web link on your phone browser → automatically scans device → sends results to server.
NO ADB, NO ROOT, NO APP INSTALL needed. Works on carrier-locked phones.

Usage:
    python3 scripts/web_phone_scanner.py
    python3 scripts/web_phone_scanner.py --port 9090

Then open the displayed link on your phone browser.
"""

import http.server
import json
import os
import ssl
import sys
import threading
import time
import urllib.parse
from datetime import datetime

PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 9090
HOST = "0.0.0.0"
SERVER_IP = "51.68.33.34"
RESULTS_DIR = "/tmp/titan_phone_scans"
os.makedirs(RESULTS_DIR, exist_ok=True)

# Track received scans
received_scans = []

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scale=no">
<title>Titan Device Scan</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0a0a0a; color:#e0e0e0; padding:16px; min-height:100vh; }
.header { text-align:center; padding:20px 0; border-bottom:1px solid #333; margin-bottom:20px; }
.header h1 { font-size:22px; color:#00d4ff; margin-bottom:8px; }
.header p { font-size:13px; color:#888; }
.status { text-align:center; padding:30px 10px; }
.status .icon { font-size:48px; margin-bottom:16px; }
.status .msg { font-size:16px; margin-bottom:8px; }
.status .sub { font-size:12px; color:#888; }
.progress { width:100%; max-width:300px; height:6px; background:#222; border-radius:3px; margin:20px auto; overflow:hidden; }
.progress .bar { height:100%; background:linear-gradient(90deg,#00d4ff,#00ff88); border-radius:3px; transition:width 0.3s; }
.results { margin-top:20px; }
.section { background:#111; border:1px solid #222; border-radius:8px; padding:14px; margin-bottom:12px; }
.section h3 { font-size:14px; color:#00d4ff; margin-bottom:10px; border-bottom:1px solid #222; padding-bottom:6px; }
.row { display:flex; justify-content:space-between; padding:4px 0; font-size:12px; border-bottom:1px solid #1a1a1a; }
.row .label { color:#888; flex-shrink:0; }
.row .value { color:#e0e0e0; text-align:right; word-break:break-all; max-width:60%; }
.ok { color:#00ff88; }
.warn { color:#ffaa00; }
.err { color:#ff4444; }
.btn { display:block; width:100%; max-width:300px; margin:20px auto; padding:14px; background:#00d4ff; color:#000; font-weight:bold; border:none; border-radius:8px; font-size:16px; cursor:pointer; text-align:center; }
.btn:active { background:#00a0cc; }
.btn.secondary { background:#333; color:#ddd; }
.permission-note { font-size:11px; color:#666; text-align:center; margin-top:8px; }
</style>
</head>
<body>

<div class="header">
<h1>TITAN Device Scanner</h1>
<p>Read-only analysis &mdash; zero modifications</p>
</div>

<div id="status" class="status">
<div class="icon">&#128270;</div>
<div class="msg">Ready to scan your device</div>
<div class="sub">Tap the button below to start</div>
</div>

<div class="progress" id="progressWrap" style="display:none">
<div class="bar" id="progressBar" style="width:0%"></div>
</div>

<button class="btn" id="startBtn" onclick="startScan()">Start Device Scan</button>

<div id="results" class="results" style="display:none"></div>

<script>
const SERVER = window.location.origin;
let scanData = {};

function setStatus(icon, msg, sub, cls) {
  document.getElementById('status').innerHTML =
    '<div class="icon">'+icon+'</div><div class="msg '+(cls||'')+'">'+msg+'</div><div class="sub">'+sub+'</div>';
}

function setProgress(pct) {
  document.getElementById('progressWrap').style.display = 'block';
  document.getElementById('progressBar').style.width = pct+'%';
}

async function startScan() {
  document.getElementById('startBtn').style.display = 'none';
  setStatus('&#9881;', 'Scanning...', 'Collecting device information', '');
  setProgress(5);

  try {
    // 1. Basic navigator info
    setProgress(10);
    scanData.basic = {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      vendor: navigator.vendor,
      language: navigator.language,
      languages: navigator.languages ? [...navigator.languages] : [],
      cookieEnabled: navigator.cookieEnabled,
      doNotTrack: navigator.doNotTrack,
      maxTouchPoints: navigator.maxTouchPoints || 0,
      hardwareConcurrency: navigator.hardwareConcurrency || 0,
      deviceMemory: navigator.deviceMemory || 'unknown',
      pdfViewerEnabled: navigator.pdfViewerEnabled,
      onLine: navigator.onLine,
    };

    // Parse user agent for device info
    let ua = navigator.userAgent;
    let androidMatch = ua.match(/Android\s+([\d.]+)/);
    let deviceMatch = ua.match(/;\s*([^;)]+)\s+Build\//);
    let chromeMatch = ua.match(/Chrome\/([\d.]+)/);
    scanData.parsed = {
      android_version: androidMatch ? androidMatch[1] : 'unknown',
      device_model: deviceMatch ? deviceMatch[1].trim() : 'unknown',
      chrome_version: chromeMatch ? chromeMatch[1] : 'unknown',
      is_mobile: /Mobile|Android/.test(ua),
      is_tablet: /Tablet/.test(ua),
    };

    // 2. Screen info
    setProgress(20);
    scanData.screen = {
      width: screen.width,
      height: screen.height,
      availWidth: screen.availWidth,
      availHeight: screen.availHeight,
      colorDepth: screen.colorDepth,
      pixelDepth: screen.pixelDepth,
      devicePixelRatio: window.devicePixelRatio,
      orientation: screen.orientation ? screen.orientation.type : 'unknown',
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
    };

    // 3. WebGL — GPU info (very valuable)
    setProgress(30);
    scanData.gpu = getWebGLInfo();

    // 4. Battery
    setProgress(40);
    scanData.battery = await getBatteryInfo();

    // 5. Network
    setProgress(50);
    scanData.network = getNetworkInfo();

    // 6. Media devices (cameras/mics count)
    setProgress(55);
    scanData.media = await getMediaDevices();

    // 7. Storage estimate
    setProgress(60);
    scanData.storage = await getStorageInfo();

    // 8. Sensors availability
    setProgress(65);
    scanData.sensors = await getSensorInfo();

    // 9. Canvas fingerprint
    setProgress(70);
    scanData.canvas = getCanvasFingerprint();

    // 10. WebRTC local IPs
    setProgress(75);
    scanData.webrtc = await getWebRTCInfo();

    // 11. Media codecs
    setProgress(80);
    scanData.codecs = getMediaCodecs();

    // 12. Feature detection
    setProgress(85);
    scanData.features = {
      bluetooth: 'bluetooth' in navigator,
      usb: 'usb' in navigator,
      nfc: 'NDEFReader' in window,
      geolocation: 'geolocation' in navigator,
      notifications: 'Notification' in window,
      serviceWorker: 'serviceWorker' in navigator,
      webGL2: !!document.createElement('canvas').getContext('webgl2'),
      webGPU: 'gpu' in navigator,
      sharedArrayBuffer: typeof SharedArrayBuffer !== 'undefined',
      crossOriginIsolated: window.crossOriginIsolated || false,
      touchEvents: 'ontouchstart' in window,
      pointerEvents: 'PointerEvent' in window,
      vibration: 'vibrate' in navigator,
      wakeLock: 'wakeLock' in navigator,
      credentials: 'credentials' in navigator,
      payment: 'PaymentRequest' in window,
      biometric: 'PublicKeyCredential' in window,
      clipboard: 'clipboard' in navigator,
      speech: 'speechSynthesis' in window,
      midi: 'requestMIDIAccess' in navigator,
      xr: 'xr' in navigator,
      serial: 'serial' in navigator,
      hid: 'hid' in navigator,
      presentation: 'presentation' in navigator,
      contacts: 'ContactsManager' in window,
      share: 'share' in navigator,
    };

    // 13. Performance info
    setProgress(88);
    scanData.performance = {
      memory: performance.memory ? {
        jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
        totalJSHeapSize: performance.memory.totalJSHeapSize,
        usedJSHeapSize: performance.memory.usedJSHeapSize,
      } : 'unavailable',
      timing_type: performance.timing ? 'available' : 'unavailable',
    };

    // 14. Timezone & locale
    scanData.locale = {
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      locale: Intl.DateTimeFormat().resolvedOptions().locale,
      hour_cycle: Intl.DateTimeFormat().resolvedOptions().hourCycle,
      calendar: Intl.DateTimeFormat().resolvedOptions().calendar,
      date_now: new Date().toString(),
      utc_offset: new Date().getTimezoneOffset(),
    };

    // 15. Installed fonts (basic check)
    setProgress(92);
    scanData.fonts = detectFonts();

    // 16. Plugin/extension detection
    scanData.plugins = {
      count: navigator.plugins ? navigator.plugins.length : 0,
      list: [],
    };
    if (navigator.plugins) {
      for (let i = 0; i < Math.min(navigator.plugins.length, 20); i++) {
        scanData.plugins.list.push(navigator.plugins[i].name);
      }
    }

    scanData.scan_timestamp = new Date().toISOString();
    scanData.scan_url = window.location.href;

    // Send to server
    setProgress(95);
    setStatus('&#128640;', 'Sending results...', 'Uploading to analysis server', '');
    
    let resp = await fetch(SERVER + '/api/scan-result', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scanData),
    });
    let result = await resp.json();

    setProgress(100);
    setStatus('&#9989;', 'Scan Complete!', 'Results received by server', 'ok');
    displayResults(scanData);

  } catch (err) {
    setStatus('&#10060;', 'Scan Error', err.message, 'err');
    // Try to send partial results
    try {
      scanData.error = err.message;
      await fetch(SERVER + '/api/scan-result', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scanData),
      });
    } catch(e) {}
  }
}

function getWebGLInfo() {
  try {
    let canvas = document.createElement('canvas');
    let gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return { supported: false };
    let dbg = gl.getExtension('WEBGL_debug_renderer_info');
    return {
      supported: true,
      renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'unknown',
      vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : 'unknown',
      version: gl.getParameter(gl.VERSION),
      shadingVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
      maxViewportDims: gl.getParameter(gl.MAX_VIEWPORT_DIMS),
      maxRenderbufferSize: gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
      aliasedLineWidthRange: gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE),
      aliasedPointSizeRange: gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE),
      maxVertexAttribs: gl.getParameter(gl.MAX_VERTEX_ATTRIBS),
      maxVaryingVectors: gl.getParameter(gl.MAX_VARYING_VECTORS),
      maxFragmentUniformVectors: gl.getParameter(gl.MAX_FRAGMENT_UNIFORM_VECTORS),
      maxVertexUniformVectors: gl.getParameter(gl.MAX_VERTEX_UNIFORM_VECTORS),
      extensions: gl.getSupportedExtensions() ? gl.getSupportedExtensions().length : 0,
    };
  } catch(e) { return { supported: false, error: e.message }; }
}

async function getBatteryInfo() {
  try {
    if (!navigator.getBattery) return { supported: false };
    let b = await navigator.getBattery();
    return {
      supported: true,
      level: Math.round(b.level * 100),
      charging: b.charging,
      chargingTime: b.chargingTime,
      dischargingTime: b.dischargingTime,
    };
  } catch(e) { return { supported: false }; }
}

function getNetworkInfo() {
  try {
    let conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!conn) return { supported: false };
    return {
      supported: true,
      effectiveType: conn.effectiveType,
      downlink: conn.downlink,
      rtt: conn.rtt,
      saveData: conn.saveData,
      type: conn.type || 'unknown',
    };
  } catch(e) { return { supported: false }; }
}

async function getMediaDevices() {
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return { supported: false };
    let devices = await navigator.mediaDevices.enumerateDevices();
    let cameras = devices.filter(d => d.kind === 'videoinput').length;
    let mics = devices.filter(d => d.kind === 'audioinput').length;
    let speakers = devices.filter(d => d.kind === 'audiooutput').length;
    return { supported: true, cameras, microphones: mics, speakers, total: devices.length };
  } catch(e) { return { supported: false }; }
}

async function getStorageInfo() {
  try {
    if (!navigator.storage || !navigator.storage.estimate) return { supported: false };
    let est = await navigator.storage.estimate();
    return {
      supported: true,
      quota_gb: (est.quota / (1024*1024*1024)).toFixed(2),
      usage_mb: (est.usage / (1024*1024)).toFixed(2),
      usage_percent: ((est.usage / est.quota) * 100).toFixed(1),
    };
  } catch(e) { return { supported: false }; }
}

async function getSensorInfo() {
  let sensors = {};
  let sensorList = [
    ['Accelerometer', 'Accelerometer'],
    ['Gyroscope', 'Gyroscope'],
    ['Magnetometer', 'Magnetometer'],
    ['AbsoluteOrientationSensor', 'AbsoluteOrientationSensor'],
    ['RelativeOrientationSensor', 'RelativeOrientationSensor'],
    ['LinearAccelerationSensor', 'LinearAccelerationSensor'],
    ['GravitySensor', 'GravitySensor'],
    ['AmbientLightSensor', 'AmbientLightSensor'],
  ];
  for (let [name, cls] of sensorList) {
    try {
      if (cls in window) {
        let s = new window[cls]({ frequency: 1 });
        sensors[name] = 'available';
        s.stop && s.stop();
      } else {
        sensors[name] = 'not_available';
      }
    } catch(e) {
      sensors[name] = e.name === 'SecurityError' ? 'blocked_by_permissions' : 'error';
    }
  }
  // DeviceMotion/Orientation (older API)
  sensors.deviceMotion = 'DeviceMotionEvent' in window;
  sensors.deviceOrientation = 'DeviceOrientationEvent' in window;
  return sensors;
}

function getCanvasFingerprint() {
  try {
    let canvas = document.createElement('canvas');
    canvas.width = 200; canvas.height = 50;
    let ctx = canvas.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillStyle = '#f60';
    ctx.fillRect(0, 0, 200, 50);
    ctx.fillStyle = '#069';
    ctx.fillText('Titan Scanner 2026', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('Device Fingerprint', 4, 30);
    let hash = 0;
    let data = canvas.toDataURL();
    for (let i = 0; i < data.length; i++) {
      hash = ((hash << 5) - hash) + data.charCodeAt(i);
      hash |= 0;
    }
    return { hash: hash.toString(16), length: data.length };
  } catch(e) { return { error: e.message }; }
}

async function getWebRTCInfo() {
  try {
    if (!window.RTCPeerConnection) return { supported: false };
    return new Promise((resolve) => {
      let ips = new Set();
      let pc = new RTCPeerConnection({ iceServers: [] });
      pc.createDataChannel('');
      pc.createOffer().then(o => pc.setLocalDescription(o));
      pc.onicecandidate = (e) => {
        if (!e.candidate) {
          pc.close();
          resolve({ supported: true, local_ips: [...ips] });
          return;
        }
        let parts = e.candidate.candidate.split(' ');
        let ip = parts[4];
        if (ip && !ip.endsWith('.local')) ips.add(ip);
      };
      setTimeout(() => { pc.close(); resolve({ supported: true, local_ips: [...ips], timeout: true }); }, 3000);
    });
  } catch(e) { return { supported: false, error: e.message }; }
}

function getMediaCodecs() {
  let codecs = {};
  let tests = {
    'H.264': 'video/mp4; codecs="avc1.42E01E"',
    'H.265/HEVC': 'video/mp4; codecs="hev1.1.6.L93.B0"',
    'VP8': 'video/webm; codecs="vp8"',
    'VP9': 'video/webm; codecs="vp9"',
    'AV1': 'video/mp4; codecs="av01.0.01M.08"',
    'AAC': 'audio/mp4; codecs="mp4a.40.2"',
    'Opus': 'audio/webm; codecs="opus"',
    'FLAC': 'audio/flac',
    'Vorbis': 'audio/ogg; codecs="vorbis"',
  };
  for (let [name, mime] of Object.entries(tests)) {
    try {
      let v = document.createElement('video');
      codecs[name] = v.canPlayType(mime) || 'no';
    } catch(e) { codecs[name] = 'error'; }
  }
  return codecs;
}

function detectFonts() {
  let testFonts = ['Arial','Helvetica','Times New Roman','Courier New','Georgia',
    'Verdana','Trebuchet MS','Comic Sans MS','Impact','Roboto','Noto Sans',
    'Samsung Sans','OnePlus Sans','MiSans','OPPO Sans'];
  let detected = [];
  try {
    let canvas = document.createElement('canvas');
    let ctx = canvas.getContext('2d');
    let baseline = 'monospace';
    let testStr = 'mmmmmmmmlli';
    ctx.font = '72px ' + baseline;
    let baseWidth = ctx.measureText(testStr).width;
    for (let font of testFonts) {
      ctx.font = '72px "' + font + '", ' + baseline;
      let w = ctx.measureText(testStr).width;
      if (w !== baseWidth) detected.push(font);
    }
  } catch(e) {}
  return { detected, count: detected.length };
}

function displayResults(data) {
  let html = '';
  // Device info
  html += '<div class="section"><h3>&#128241; Device Identity</h3>';
  html += row('Model', data.parsed.device_model);
  html += row('Android', data.parsed.android_version);
  html += row('Chrome', data.parsed.chrome_version);
  html += row('Platform', data.basic.platform);
  html += row('CPU Cores', data.basic.hardwareConcurrency);
  html += row('RAM', data.basic.deviceMemory !== 'unknown' ? data.basic.deviceMemory + ' GB' : 'hidden');
  html += row('Touch Points', data.basic.maxTouchPoints);
  html += '</div>';

  // Screen
  html += '<div class="section"><h3>&#128187; Screen</h3>';
  html += row('Resolution', data.screen.width + ' x ' + data.screen.height);
  html += row('Pixel Ratio', data.screen.devicePixelRatio);
  html += row('Color Depth', data.screen.colorDepth + '-bit');
  html += row('Orientation', data.screen.orientation);
  html += '</div>';

  // GPU
  if (data.gpu && data.gpu.supported) {
    html += '<div class="section"><h3>&#127912; GPU</h3>';
    html += row('Renderer', data.gpu.renderer);
    html += row('Vendor', data.gpu.vendor);
    html += row('WebGL Version', data.gpu.version);
    html += row('Max Texture', data.gpu.maxTextureSize);
    html += row('Extensions', data.gpu.extensions);
    html += '</div>';
  }

  // Battery
  if (data.battery && data.battery.supported) {
    html += '<div class="section"><h3>&#128267; Battery</h3>';
    html += row('Level', data.battery.level + '%');
    html += row('Charging', data.battery.charging ? 'Yes' : 'No');
    html += '</div>';
  }

  // Network
  if (data.network && data.network.supported) {
    html += '<div class="section"><h3>&#127760; Network</h3>';
    html += row('Type', data.network.effectiveType);
    html += row('Downlink', data.network.downlink + ' Mbps');
    html += row('RTT', data.network.rtt + ' ms');
    html += row('Data Saver', data.network.saveData ? 'ON' : 'OFF');
    html += row('Connection', data.network.type);
    html += '</div>';
  }

  // Storage
  if (data.storage && data.storage.supported) {
    html += '<div class="section"><h3>&#128190; Storage</h3>';
    html += row('Total Quota', data.storage.quota_gb + ' GB');
    html += row('Used', data.storage.usage_mb + ' MB');
    html += row('Used %', data.storage.usage_percent + '%');
    html += '</div>';
  }

  // Media
  if (data.media && data.media.supported) {
    html += '<div class="section"><h3>&#127909; Media Devices</h3>';
    html += row('Cameras', data.media.cameras);
    html += row('Microphones', data.media.microphones);
    html += row('Speakers', data.media.speakers);
    html += '</div>';
  }

  // Sensors
  if (data.sensors) {
    html += '<div class="section"><h3>&#129518; Sensors</h3>';
    for (let [k,v] of Object.entries(data.sensors)) {
      let cls = v === 'available' || v === true ? 'ok' : (v === 'blocked_by_permissions' ? 'warn' : '');
      html += row(k, '<span class="'+cls+'">' + v + '</span>');
    }
    html += '</div>';
  }

  // Features
  if (data.features) {
    html += '<div class="section"><h3>&#9881; Capabilities</h3>';
    let important = ['bluetooth','nfc','payment','biometric','geolocation','usb','vibration','share'];
    for (let k of important) {
      if (k in data.features) {
        let v = data.features[k];
        let cls = v ? 'ok' : '';
        html += row(k, '<span class="'+cls+'">' + (v ? 'YES' : 'NO') + '</span>');
      }
    }
    html += '</div>';
  }

  // Locale
  if (data.locale) {
    html += '<div class="section"><h3>&#127758; Locale</h3>';
    html += row('Timezone', data.locale.timezone);
    html += row('Locale', data.locale.locale);
    html += row('UTC Offset', (data.locale.utc_offset / -60) + 'h');
    html += '</div>';
  }

  // Codecs
  if (data.codecs) {
    html += '<div class="section"><h3>&#127916; Media Codecs</h3>';
    for (let [k,v] of Object.entries(data.codecs)) {
      let cls = v === 'probably' ? 'ok' : (v === 'maybe' ? 'warn' : 'err');
      html += row(k, '<span class="'+cls+'">' + v + '</span>');
    }
    html += '</div>';
  }

  document.getElementById('results').innerHTML = html;
  document.getElementById('results').style.display = 'block';
}

function row(label, value) {
  return '<div class="row"><span class="label">'+label+'</span><span class="value">'+value+'</span></div>';
}
</script>
</body>
</html>"""


class ScanHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for the scanner web app."""

    def log_message(self, format, *args):
        # Custom log format
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready", "scans": len(received_scans)}).encode())
        elif self.path.startswith("/api/results"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(received_scans, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/scan-result":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 5_000_000:  # 5MB limit
                self.send_response(413)
                self.end_headers()
                return
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "invalid JSON"}).encode())
                return

            # Add server-side metadata
            data["_server_received"] = datetime.now().isoformat()
            data["_client_ip"] = self.client_address[0]

            # Save to file
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{RESULTS_DIR}/phone_scan_{ts}.json"
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, default=str)

            received_scans.append(data)

            print(f"\n{'='*60}")
            print(f"  SCAN RECEIVED from {self.client_address[0]}")
            print(f"  Saved: {filename}")
            print(f"{'='*60}")
            print_scan_summary(data)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "received", "file": filename}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        # CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def print_scan_summary(data):
    """Print a readable summary of the scan."""
    parsed = data.get("parsed", {})
    basic = data.get("basic", {})
    screen = data.get("screen", {})
    gpu = data.get("gpu", {})
    battery = data.get("battery", {})
    network = data.get("network", {})
    storage = data.get("storage", {})
    media = data.get("media", {})
    sensors = data.get("sensors", {})
    features = data.get("features", {})
    locale = data.get("locale", {})
    codecs = data.get("codecs", {})
    webrtc = data.get("webrtc", {})
    canvas = data.get("canvas", {})
    fonts = data.get("fonts", {})

    print(f"\n  DEVICE IDENTITY")
    print(f"  {'─'*50}")
    print(f"  Model          : {parsed.get('device_model', '?')}")
    print(f"  Android        : {parsed.get('android_version', '?')}")
    print(f"  Chrome         : {parsed.get('chrome_version', '?')}")
    print(f"  Platform       : {basic.get('platform', '?')}")
    print(f"  CPU Cores      : {basic.get('hardwareConcurrency', '?')}")
    print(f"  RAM            : {basic.get('deviceMemory', '?')} GB")
    print(f"  Language       : {basic.get('language', '?')}")
    print(f"  Touch Points   : {basic.get('maxTouchPoints', '?')}")

    print(f"\n  SCREEN")
    print(f"  {'─'*50}")
    print(f"  Resolution     : {screen.get('width', '?')} x {screen.get('height', '?')}")
    print(f"  Pixel Ratio    : {screen.get('devicePixelRatio', '?')}")
    print(f"  Color Depth    : {screen.get('colorDepth', '?')}-bit")

    if gpu.get("supported"):
        print(f"\n  GPU")
        print(f"  {'─'*50}")
        print(f"  Renderer       : {gpu.get('renderer', '?')}")
        print(f"  Vendor         : {gpu.get('vendor', '?')}")
        print(f"  WebGL          : {gpu.get('version', '?')}")
        print(f"  Max Texture    : {gpu.get('maxTextureSize', '?')}")
        print(f"  Extensions     : {gpu.get('extensions', '?')}")

    if battery.get("supported"):
        print(f"\n  BATTERY")
        print(f"  {'─'*50}")
        print(f"  Level          : {battery.get('level', '?')}%")
        print(f"  Charging       : {'Yes' if battery.get('charging') else 'No'}")

    if network.get("supported"):
        print(f"\n  NETWORK")
        print(f"  {'─'*50}")
        print(f"  Type           : {network.get('effectiveType', '?')}")
        print(f"  Downlink       : {network.get('downlink', '?')} Mbps")
        print(f"  RTT            : {network.get('rtt', '?')} ms")
        print(f"  Connection     : {network.get('type', '?')}")

    if storage.get("supported"):
        print(f"\n  STORAGE")
        print(f"  {'─'*50}")
        print(f"  Quota          : {storage.get('quota_gb', '?')} GB")
        print(f"  Used           : {storage.get('usage_mb', '?')} MB ({storage.get('usage_percent', '?')}%)")

    if media.get("supported"):
        print(f"\n  MEDIA DEVICES")
        print(f"  {'─'*50}")
        print(f"  Cameras        : {media.get('cameras', '?')}")
        print(f"  Microphones    : {media.get('microphones', '?')}")
        print(f"  Speakers       : {media.get('speakers', '?')}")

    if sensors:
        print(f"\n  SENSORS")
        print(f"  {'─'*50}")
        for name, status in sensors.items():
            icon = "+" if status in ("available", True) else ("-" if status in ("not_available", False) else "?")
            print(f"  [{icon}] {name:30s}: {status}")

    if features:
        print(f"\n  KEY FEATURES")
        print(f"  {'─'*50}")
        important = ["bluetooth", "nfc", "payment", "biometric", "geolocation",
                      "usb", "vibration", "share", "webGL2", "webGPU"]
        for f in important:
            if f in features:
                icon = "+" if features[f] else "-"
                print(f"  [{icon}] {f}")

    if locale:
        print(f"\n  LOCALE")
        print(f"  {'─'*50}")
        print(f"  Timezone       : {locale.get('timezone', '?')}")
        print(f"  Locale         : {locale.get('locale', '?')}")

    if webrtc.get("local_ips"):
        print(f"\n  LOCAL IPs (WebRTC)")
        print(f"  {'─'*50}")
        for ip in webrtc["local_ips"]:
            print(f"  {ip}")

    if canvas:
        print(f"\n  CANVAS FINGERPRINT")
        print(f"  {'─'*50}")
        print(f"  Hash           : {canvas.get('hash', '?')}")

    if fonts.get("detected"):
        print(f"\n  DETECTED FONTS")
        print(f"  {'─'*50}")
        print(f"  {', '.join(fonts['detected'])}")

    if codecs:
        print(f"\n  MEDIA CODECS")
        print(f"  {'─'*50}")
        for name, support in codecs.items():
            icon = "+" if support == "probably" else ("?" if support == "maybe" else "-")
            print(f"  [{icon}] {name:15s}: {support}")

    print(f"\n  {'='*50}")
    print(f"  Full JSON: {RESULTS_DIR}/")
    print()


def main():
    # Open firewall port
    os.system(f"iptables -I INPUT -p tcp --dport {PORT} -j ACCEPT 2>/dev/null")

    server = http.server.HTTPServer((HOST, PORT), ScanHandler)

    print()
    print("=" * 60)
    print("  TITAN — Web Phone Scanner")
    print("=" * 60)
    print()
    print(f"  Open this link on your phone browser:")
    print()
    print(f"    http://{SERVER_IP}:{PORT}")
    print()
    print(f"  Or scan this URL. Works on ANY phone — no ADB needed.")
    print(f"  Carrier-locked? No problem. Just open the link.")
    print()
    print(f"  Waiting for scan results...")
    print(f"  Press Ctrl+C to stop.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
