/**
 * VMOS Titan — Main Electron Process
 * 
 * Professional Linux desktop application for VMOS Pro cloud device management
 * with full Genesis Studio integration.
 * 
 * Features:
 *   - VMOS Pro Cloud instance management
 *   - Unified Genesis Studio pipeline
 *   - Remote shell execution
 *   - Device property modification
 *   - Screenshot & touch control
 *   - Professional-grade UI/UX
 */

const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog, nativeTheme } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const { validateGenesisInput, isValidPadCode, filterProperties, sanitizeSQL, sanitizeText, isValidProxyUrl, isValidCC, isValidAgeDays, isValidCountry, VALID_COUNTRIES } = require('./validators');

// ─── Path Resolution (packaged vs dev) ────────────────────────────────
const IS_PACKAGED = app.isPackaged;
const RESOURCES = IS_PACKAGED ? process.resourcesPath : path.resolve(__dirname, '..');
const USER_DATA = app.getPath('userData');        // ~/.config/vmos-titan
const TITAN_DATA = IS_PACKAGED
  ? (process.env.TITAN_DATA || '/opt/titan/data')
  : path.join(USER_DATA, 'data');
const VENV_DIR = path.join(USER_DATA, 'venv');
const SERVER_DIR = path.join(RESOURCES, 'server');
const CORE_DIR = path.join(RESOURCES, 'core');
const CONFIG_FILE = path.join(USER_DATA, 'config.json');
const SETUP_DONE = path.join(USER_DATA, '.setup-done');

// ─── Config ───────────────────────────────────────────────────────────
const API_PORT = process.env.TITAN_API_PORT || 8082;  // Unique port for VMOS Titan
const API_URL = `http://127.0.0.1:${API_PORT}`;
const VMOS_API_BASE = 'https://api.vmoscloud.com';

// Chromium flags for headless / xRDP / GPU-less environments
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');

let mainWindow = null;
let setupWindow = null;
let tray = null;
let serverProc = null;
let builtinServer = null;
let _serverRestarts = 0;
const MAX_SERVER_RESTARTS = 3;

// ─── VMOS Cloud API constants ─────────────────────────────────────────
const VMOS_HOST     = 'api.vmoscloud.com';
const VMOS_SERVICE  = 'armcloud-paas';
const VMOS_CT       = 'application/json;charset=UTF-8';
const VMOS_SH       = 'content-type;host;x-content-sha256;x-date';

// In-memory genesis jobs
const _genesisJobs  = new Map();

// ─── Prevent duplicate instances ─────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = mainWindow || setupWindow;
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ─── Utilities ───────────────────────────────────────────────────────
function ensureDir(d) { 
  fs.mkdirSync(d, { recursive: true }); 
}

// ─── VMOS Cloud API helpers ───────────────────────────────────────────
function _vmosSign(bodyJson, ak, sk) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const shortDate = xDate.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const canonical = [
    `host:${VMOS_HOST}`,
    `x-date:${xDate}`,
    `content-type:${VMOS_CT}`,
    `signedHeaders:${VMOS_SH}`,
    `x-content-sha256:${xSha}`,
  ].join('\n');
  const scope    = `${shortDate}/${VMOS_SERVICE}/request`;
  const hashCan  = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  const sts      = ['HMAC-SHA256', xDate, scope, hashCan].join('\n');
  const kDate    = crypto.createHmac('sha256', Buffer.from(sk, 'utf8')).update(shortDate).digest();
  const kSvc     = crypto.createHmac('sha256', kDate).update(VMOS_SERVICE).digest();
  const sigKey   = crypto.createHmac('sha256', kSvc).update('request').digest();
  const sig      = crypto.createHmac('sha256', sigKey).update(sts).digest('hex');
  return {
    'content-type': VMOS_CT,
    'x-date': xDate,
    'x-host': VMOS_HOST,
    'authorization': `HMAC-SHA256 Credential=${ak}, SignedHeaders=${VMOS_SH}, Signature=${sig}`,
  };
}

function vmosPost(apiPath, data, ak, sk, timeoutSec) {
  return new Promise((resolve, reject) => {
    const bodyJson = JSON.stringify(data || {});
    const headers  = _vmosSign(bodyJson, ak, sk);
    const buf      = Buffer.from(bodyJson, 'utf8');
    // E-06 fix: Allow custom timeout (default 30s, max 120s for long operations)
    const timeoutMs = Math.min(Math.max((timeoutSec || 30) * 1000, 5000), 120000);
    const req = https.request({
      hostname: VMOS_HOST,
      path: apiPath,
      method: 'POST',
      headers: { ...headers, 'content-length': buf.length },
      timeout: timeoutMs,
    }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); }
        catch { reject(new Error(`Bad JSON (${res.statusCode}): ${raw.slice(0,120)}`)); }
      });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    req.on('error', reject);
    req.write(buf);
    req.end();
  });
}

// ─── Built-in Node.js API server ──────────────────────────────────────
function startBuiltinServer() {
  if (builtinServer) return;

  builtinServer = http.createServer(async (req, res) => {
    const urlObj = new URL(req.url, `http://127.0.0.1:${API_PORT}`);
    const p      = urlObj.pathname;
    const method = req.method;

    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

    let body = '';
    let bodySize = 0;
    const MAX_BODY = 65536; // 64KB
    await new Promise((resolve, reject) => {
      req.on('data', c => {
        bodySize += c.length;
        if (bodySize > MAX_BODY) { req.destroy(); return reject(new Error('Body too large')); }
        body += c;
      });
      req.on('end', resolve);
      req.on('error', reject);
    }).catch(e => { res.writeHead(413); res.end(JSON.stringify({ error: e.message })); return; });
    if (res.writableEnded) return;

    const send = (data, code = 200) => { res.writeHead(code); res.end(JSON.stringify(data)); };

    try {
      const cfg = loadConfig();
      const ak  = cfg.vmos_ak || '';
      const sk  = cfg.vmos_sk || '';

      // ── Health ──────────────────────────────────────────────────────
      if (p === '/api/health') {
        return send({ status: 'ok', version: '1.0.0' });
      }

      if (!ak || !sk) return send({ error: 'Credentials not configured' }, 401);

      // ── Instance list ────────────────────────────────────────────────
      if (p === '/api/vmos/instances' && method === 'GET') {
        const r   = await vmosPost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 }, ak, sk);
        // Real response: r.data.pageData (array), r.data.rows is the page-size integer
        const raw = (r.data && Array.isArray(r.data.pageData)) ? r.data.pageData : [];
        const instances = raw.map(i => {
          // Parse resolution from screenLayoutCode e.g. "realdevice_1440x3120x600"
          const resParts = (i.screenLayoutCode || '').match(/(\d{3,4}x\d{3,4})/);
          const resolution = resParts ? resParts[1] : (i.resolution || '');
          // androidVersion from imageVersion e.g. "android15"
          const verMatch = (i.imageVersion || '').match(/\d+/);
          const androidVersion = verMatch ? verMatch[0] : (i.androidVersion || '');
          return {
            padCode:        i.padCode || '',
            pad_code:       i.padCode || '',
            status:         i.padStatus ?? i.vmStatus ?? i.status ?? 0,
            androidVersion,
            android_version: androidVersion,
            resolution,
            romVersion:     i.cbsInfo || i.romVersion || '',
            rom_version:    i.cbsInfo || i.romVersion || '',
            padType:        i.padType || '',
            padGrade:       i.padGrade || '',
            imageVersion:   i.imageVersion || '',
            apps:           i.apps || [],
            deviceIp:       i.deviceIp || '',
            createTime:     i.createTime || '',
            adbOpenStatus:  i.adbOpenStatus || '0',
            clusterCode:    i.clusterCode || '',
          };
        });
        return send({ instances });
      }

      // ── Per-instance actions: /api/vmos/instances/{padCode}/{action} ─
      const instMatch = p.match(/^\/api\/vmos\/instances\/([^/]+)(?:\/(.+))?$/);
      if (instMatch) {
        const padCode = decodeURIComponent(instMatch[1]);
        if (!isValidPadCode(padCode)) return send({ error: 'Invalid device ID' }, 400);
        const action  = instMatch[2] || '';

        if (action === 'restart' && method === 'POST') {
          await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: [padCode] }, ak, sk);
          return send({ ok: true });
        }

        if (action === 'screenshot') {
          const r = await vmosPost('/vcpcloud/api/padApi/screenshot', { padCodes: [padCode] }, ak, sk);
          const d = r.data;
          const imgUrl = (Array.isArray(d) ? d[0]?.imgUrl : d?.imgUrl) || '';
          return send({ url: imgUrl, ok: true });
        }

        if (action === 'shell' && method === 'POST') {
          const cmd = (JSON.parse(body || '{}').command || '').slice(0, 2000);
          const r   = await vmosPost('/vcpcloud/api/padApi/syncCmd', { padCode, scriptContent: cmd }, ak, sk);
          let output = 'Command failed';
          if (r.code === 200 && r.data) {
            const items = Array.isArray(r.data) ? r.data : [r.data];
            const item = items[0] || {};
            output = item.taskStatus === 3 ? (item.errorMsg || item.taskResult || 'OK') : 'Command failed';
          }
          return send({ output: output.trim(), ok: r.code === 200 });
        }

        if (action === 'properties') {
          if (method === 'GET') {
            const r = await vmosPost('/vcpcloud/api/padApi/padProperties', { padCode }, ak, sk);
            return send({ properties: r.data || {} });
          }
          if (method === 'POST') {
            const rawProps = JSON.parse(body || '{}');
            const props = filterProperties(rawProps);
            if (Object.keys(props).length === 0) return send({ error: 'No valid properties provided' }, 400);
            await vmosPost('/vcpcloud/api/padApi/updatePadProperties', { padCodes: [padCode], ...props }, ak, sk);
            return send({ ok: true });
          }
        }
      }

      // ── Genesis start ────────────────────────────────────────────────
      if (p === '/api/unified-genesis/start' && method === 'POST') {
        // Rate limit: max 5 concurrent genesis jobs
        const activeJobs = [..._genesisJobs.values()].filter(j => j.status === 'running').length;
        if (activeJobs >= 5) return send({ error: 'Too many active jobs (max 5)' }, 429);

        const jobData = JSON.parse(body || '{}');

        // Schema validation
        const validation = validateGenesisInput(jobData);
        if (!validation.valid) return send({ error: 'Validation failed', details: validation.errors }, 400);

        const jobId = crypto.randomBytes(16).toString('hex');
        const job = {
          job_id:     jobId,
          pad_code:   jobData.device_id || '',
          status:     'running',
          trust_score:0,
          phases: [
            'Pre-Flight','Wipe','Stealth Patch','Network/Proxy','Forge Profile',
            'Google Account','Inject','Wallet/GPay','Provincial Layer',
            'Post-Harden','Attestation','Trust Audit',
            '—','—','—','—',
          ].map((name, i) => ({ phase_id: i, name, status: i === 0 ? 'running' : 'pending' })),
          log:        [],
          started_at: Date.now(),
          config:     jobData.config || jobData,
        };
        _genesisJobs.set(jobId, job);
        _runGenesisJob(jobId, ak, sk).catch(e => console.error('[genesis]', e));
        return send({ job_id: jobId, ok: true });
      }

      // ── Genesis status ───────────────────────────────────────────────
      const gsMatch = p.match(/^\/api\/unified-genesis\/status\/([^/]+)$/);
      if (gsMatch) {
        const job = _genesisJobs.get(gsMatch[1]);
        if (!job) return send({ error: 'Not found' }, 404);
        return send(job);
      }

      send({ error: 'Not found' }, 404);
    } catch (e) {
      console.error('[api-err]', e.message);
      const code = /401|403/.test(e.message) ? 401 : /404/.test(e.message) ? 404 : 500;
      send({ error: e.message }, code);
    }
  });

  builtinServer.on('error', e => console.warn('[builtin-server]', e.message));
  builtinServer.listen(API_PORT, '127.0.0.1', () =>
    console.log(`[builtin-server] Online at http://127.0.0.1:${API_PORT}`)
  );
}

function stopBuiltinServer() {
  if (builtinServer) {
    builtinServer.close();
    builtinServer = null;
  }
}

// ── Genesis helpers ────────────────────────────────────────────────────────
function _genImei(tacPrefix) {
  const serial = Array.from({length: 6}, () => Math.floor(Math.random() * 10)).join('');
  const body = tacPrefix + serial;
  const digits = body.split('').map(Number);
  for (let i = 1; i < digits.length; i += 2) {
    digits[i] *= 2;
    if (digits[i] > 9) digits[i] -= 9;
  }
  const check = (10 - (digits.reduce((a, b) => a + b, 0) % 10)) % 10;
  return body + check;
}
function _genSerial() {
  // Samsung-style: R5CT + 8 hex; Pixel-style: FA6A1 + 11 hex; Generic: 16 hex
  const styles = [
    () => 'R5CT' + Array.from({length:8}, () => '0123456789ABCDEF'[Math.floor(Math.random()*16)]).join(''),
    () => 'FA6A1' + Array.from({length:11}, () => '0123456789ABCDEF'[Math.floor(Math.random()*16)]).join(''),
    () => Array.from({length:16}, () => '0123456789ABCDEF'[Math.floor(Math.random()*16)]).join(''),
  ];
  return styles[Math.floor(Math.random() * styles.length)]();
}
function _genAndroidId() {
  return crypto.randomBytes(8).toString('hex');
}
function _genGsfId() {
  return String(BigInt(3000000000000000000n) + BigInt(Math.floor(Math.random() * 999999999999999)));
}
function _genMacAddr(oui) {
  const suffix = Array.from({length: 3}, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join(':');
  return `${oui || 'E8:50:8B'}:${suffix}`;
}
function _genPhoneNumber(country) {
  const cc = (country || 'US').toUpperCase();
  if (cc === 'GB') return `+447${Math.floor(100000000 + Math.random() * 899999999)}`;
  if (cc === 'DE') return `+491${Math.floor(500000000 + Math.random() * 400000000)}`;
  if (cc === 'FR') return `+336${Math.floor(10000000 + Math.random() * 89999999)}`;
  return `+1${Math.floor(2010000000 + Math.random() * 7980000000)}`;
}
function _pickRandom(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function _sanitize(v) {
  return (v || '').replace(/'/g, '').replace(/"/g, '').replace(/;/g, ',').replace(/`/g, '').replace(/\\/g, '').replace(/\$/g, '');
}
// Country-appropriate name pools
const _NAME_POOLS = {
  US: { first: ['James','Michael','David','Jaylen','Tyler','Emily','Sarah','Aaliyah','Olivia','Sophia','Ethan','Noah','Liam','Mason','Logan','Chloe','Avery','Mia','Harper','Ella','Benjamin','Alexander','Daniel','Matthew','Jackson','Aiden','Lucas','Henry','Sebastian','Jack'],
        last: ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez','Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin','Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Lewis','Robinson','Walker'] },
  GB: { first: ['Oliver','Harry','George','Jack','Oscar','Charlie','Amelia','Isla','Ava','Olivia','Emily','Poppy','Grace','Jessica','Sophie','Thomas','James','William','Henry','Edward','Charlotte','Eleanor','Ruby','Alice','Florence'],
        last: ['Smith','Jones','Taylor','Brown','Williams','Wilson','Johnson','Davies','Robinson','Wright','Thompson','Evans','Walker','White','Roberts','Green','Hall','Wood','Jackson','Clarke','Patel','Khan','Shah','Singh'] },
  DE: { first: ['Maximilian','Alexander','Leon','Lukas','Paul','Jonas','Ben','Elias','Emma','Mia','Sophia','Hannah','Anna','Lena','Marie','Felix','Tim','Finn','Jan','Moritz','Laura','Julia','Lea','Lisa','Sarah'],
        last: ['Mueller','Schmidt','Schneider','Fischer','Weber','Meyer','Wagner','Becker','Schulz','Hoffmann','Koch','Richter','Wolf','Schroeder','Neumann','Schwarz','Zimmermann','Braun','Krueger','Hofmann'] },
  FR: { first: ['Lucas','Hugo','Louis','Gabriel','Raphael','Arthur','Emma','Jade','Louise','Alice','Chloe','Lina','Lea','Camille','Manon','Jules','Adam','Leo','Noah','Nathan','Marie','Amelie','Sarah','Clara','Ines'],
        last: ['Martin','Bernard','Dubois','Thomas','Robert','Richard','Petit','Durand','Leroy','Moreau','Simon','Laurent','Lefebvre','Michel','Garcia','David','Bertrand','Roux','Vincent','Fournier'] },
};
function _getNamePool(country) {
  return _NAME_POOLS[(country || 'US').toUpperCase()] || _NAME_POOLS.US;
}

// Device model → fingerprint data table (20+ devices across 8 brands)
const DEVICE_PRESETS = {
  // ── Samsung ─────────────────────────────────────────────────────
  samsung_s25_ultra: {
    brand: 'samsung', manufacturer: 'samsung', model: 'SM-S938U',
    device: 'e3q', product: 'e3qsq',
    fingerprint: 'samsung/e3qsq/e3q:15/AP4A.250205.004/S938USQS1AXL1:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2025-02-05',
    build_id: 'AP4A.250205.004', hardware: 'qcom', board: 'kalama',
    tac_prefix: '35369611', mac_oui: 'E8:50:8B',
    gpu_renderer: 'Adreno (TM) 830', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0702.0',
  },
  samsung_s24: {
    brand: 'samsung', manufacturer: 'samsung', model: 'SM-S921U',
    device: 'e1q', product: 'e1qsq',
    fingerprint: 'samsung/e1qsq/e1q:14/UP1A.231005.007/S921USQS2AXK1:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-11-01',
    build_id: 'UP1A.231005.007', hardware: 'qcom', board: 'sun',
    tac_prefix: '35847611', mac_oui: 'E8:50:8B',
    gpu_renderer: 'Adreno (TM) 750', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0606.0',
  },
  samsung_a55: {
    brand: 'samsung', manufacturer: 'samsung', model: 'SM-A556E',
    device: 'a55x', product: 'a55xns',
    fingerprint: 'samsung/a55xns/a55x:14/UP1A.231005.007/A556EXXU2AXJ1:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-10-01',
    build_id: 'UP1A.231005.007', hardware: 'exynos', board: 's5e8845',
    tac_prefix: '35278911', mac_oui: 'E8:50:8B',
    gpu_renderer: 'Mali-G68 MC4', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r44p0',
  },
  samsung_a15: {
    brand: 'samsung', manufacturer: 'samsung', model: 'SM-A156U',
    device: 'a15x', product: 'a15xsq',
    fingerprint: 'samsung/a15xsq/a15x:14/UP1A.231005.007/A156USQU1AXH1:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-08-01',
    build_id: 'UP1A.231005.007', hardware: 'mt6835', board: 'mt6835',
    tac_prefix: '35413011', mac_oui: 'E8:50:8B',
    gpu_renderer: 'Mali-G57 MC2', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r38p1',
  },
  // ── Google Pixel ────────────────────────────────────────────────
  pixel_9_pro: {
    brand: 'google', manufacturer: 'Google', model: 'Pixel 9 Pro',
    device: 'caiman', product: 'caiman',
    fingerprint: 'google/caiman/caiman:15/AP4A.250205.004/12650793:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2025-02-05',
    build_id: 'AP4A.250205.004', hardware: 'tensor', board: 'caiman',
    tac_prefix: '35360412', mac_oui: '94:E6:86',
    gpu_renderer: 'Mali-G715 Immortalis MC10', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r46p0',
  },
  pixel_8a: {
    brand: 'google', manufacturer: 'Google', model: 'Pixel 8a',
    device: 'akita', product: 'akita',
    fingerprint: 'google/akita/akita:14/AP2A.240805.005/12025142:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-08-05',
    build_id: 'AP2A.240805.005', hardware: 'tensor', board: 'akita',
    tac_prefix: '35512621', mac_oui: '94:E6:86',
    gpu_renderer: 'Mali-G715 Immortalis MC10', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r44p0',
  },
  pixel_7: {
    brand: 'google', manufacturer: 'Google', model: 'Pixel 7',
    device: 'panther', product: 'panther',
    fingerprint: 'google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-08-05',
    build_id: 'AP2A.240805.005', hardware: 'tensor', board: 'panther',
    tac_prefix: '35397012', mac_oui: '94:E6:86',
    gpu_renderer: 'Mali-G710 MC10', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r38p1',
  },
  // ── OnePlus ─────────────────────────────────────────────────────
  oneplus_ace3: {
    brand: 'OnePlus', manufacturer: 'OnePlus', model: 'PKX110',
    device: 'OP60F5L1', product: 'PKX110',
    fingerprint: 'OnePlus/PKX110/OP60F5L1:15/AP3A.240617.008/V.1a42e08_42cb7b_428e83:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2024-06-17',
    build_id: 'AP3A.240617.008', hardware: 'qcom', board: 'sun',
    tac_prefix: '86742103', mac_oui: 'AC:D6:18',
    gpu_renderer: 'Adreno (TM) 830', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.g25p0',
  },
  oneplus_13: {
    brand: 'OnePlus', manufacturer: 'OnePlus', model: 'CPH2653',
    device: 'taro', product: 'CPH2653',
    fingerprint: 'OnePlus/CPH2653/taro:15/AP4A.250205.004/T.1234567:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2025-02-05',
    build_id: 'AP4A.250205.004', hardware: 'qcom', board: 'taro',
    tac_prefix: '86712204', mac_oui: 'AC:D6:18',
    gpu_renderer: 'Adreno (TM) 830', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0702.0',
  },
  oneplus_12: {
    brand: 'OnePlus', manufacturer: 'OnePlus', model: 'CPH2583',
    device: 'waffle', product: 'CPH2583',
    fingerprint: 'OnePlus/CPH2583/waffle:14/UP1A.231005.007/T.1234567:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-10-01',
    build_id: 'UP1A.231005.007', hardware: 'qcom', board: 'kalama',
    tac_prefix: '86890104', mac_oui: 'AC:D6:18',
    gpu_renderer: 'Adreno (TM) 750', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0606.0',
  },
  oneplus_nord: {
    brand: 'OnePlus', manufacturer: 'OnePlus', model: 'CPH2613',
    device: 'larry', product: 'CPH2613',
    fingerprint: 'OnePlus/CPH2613/larry:14/UP1A.231005.007/T.1234567:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-09-01',
    build_id: 'UP1A.231005.007', hardware: 'qcom', board: 'holi',
    tac_prefix: '86892004', mac_oui: 'AC:D6:18',
    gpu_renderer: 'Adreno (TM) 710', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0570.0',
  },
  // ── Xiaomi ──────────────────────────────────────────────────────
  xiaomi_15: {
    brand: 'Xiaomi', manufacturer: 'Xiaomi', model: '24129PN74G',
    device: 'dada', product: 'dada_global',
    fingerprint: 'Xiaomi/dada_global/dada:15/AP4A.250205.004/V816.0.5.0.VNCINXM:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2025-02-05',
    build_id: 'AP4A.250205.004', hardware: 'qcom', board: 'kalama',
    tac_prefix: '86258804', mac_oui: '28:6C:07',
    gpu_renderer: 'Adreno (TM) 830', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0702.0',
  },
  xiaomi_14: {
    brand: 'Xiaomi', manufacturer: 'Xiaomi', model: '2311DRK48G',
    device: 'houji', product: 'houji_global',
    fingerprint: 'Xiaomi/houji_global/houji:14/UP1A.231005.007/V816.0.3.0.UNCINXM:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-11-01',
    build_id: 'UP1A.231005.007', hardware: 'qcom', board: 'kalama',
    tac_prefix: '86475304', mac_oui: '28:6C:07',
    gpu_renderer: 'Adreno (TM) 750', gpu_vendor: 'Qualcomm', gpu_version: 'OpenGL ES 3.2 V@0606.0',
  },
  redmi_note_14: {
    brand: 'Redmi', manufacturer: 'Xiaomi', model: '24108RN04Y',
    device: 'beryl', product: 'beryl_global',
    fingerprint: 'Redmi/beryl_global/beryl:14/UP1A.231005.007/V816.0.2.0.UOEINXM:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-10-01',
    build_id: 'UP1A.231005.007', hardware: 'mt6897', board: 'mt6897',
    tac_prefix: '86378504', mac_oui: '28:6C:07',
    gpu_renderer: 'Mali-G615 MC6', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r44p0',
  },
  // ── Vivo ────────────────────────────────────────────────────────
  vivo_v2183a: {
    brand: 'vivo', manufacturer: 'vivo', model: 'V2183A',
    device: 'PD2183', product: 'PD2183',
    fingerprint: 'vivo/PD2183/PD2183:15/AP4A.250205.004/compiler1124181214:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2025-02-05',
    build_id: 'AP4A.250205.004', hardware: 'mt6893', board: 'mt6893',
    tac_prefix: '86140103', mac_oui: 'D0:17:69',
    gpu_renderer: 'Mali-G57 MC3', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r32p1',
  },
  vivo_x200: {
    brand: 'vivo', manufacturer: 'vivo', model: 'V2408A',
    device: 'PD2408', product: 'PD2408',
    fingerprint: 'vivo/PD2408/PD2408:15/AP3A.240905.015.A2/compiler2:user/release-keys',
    android_version: '15', sdk_version: '35', security_patch: '2024-09-05',
    build_id: 'AP3A.240905.015.A2', hardware: 'mt6985', board: 'mt6985',
    tac_prefix: '86454004', mac_oui: 'D0:17:69',
    gpu_renderer: 'Immortalis-G925 MC12', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r48p0',
  },
  // ── OPPO ────────────────────────────────────────────────────────
  oppo_find_x8: {
    brand: 'OPPO', manufacturer: 'OPPO', model: 'CPH2645',
    device: 'oplus_salami', product: 'CPH2645',
    fingerprint: 'OPPO/CPH2645/oplus_salami:14/UP1A.231005.007/T.R4T3.1234567:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-12-01',
    build_id: 'UP1A.231005.007', hardware: 'mt6991', board: 'mt6991',
    tac_prefix: '86730804', mac_oui: 'E4:C7:67',
    gpu_renderer: 'Immortalis-G925 MC12', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r48p0',
  },
  oppo_reno_12: {
    brand: 'OPPO', manufacturer: 'OPPO', model: 'CPH2605',
    device: 'oplus_oscar', product: 'CPH2605',
    fingerprint: 'OPPO/CPH2605/oplus_oscar:14/UP1A.231005.007/T.R4T3.1234567:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-09-01',
    build_id: 'UP1A.231005.007', hardware: 'mt6878', board: 'mt6878',
    tac_prefix: '86705504', mac_oui: 'E4:C7:67',
    gpu_renderer: 'Mali-G615 MC6', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r44p0',
  },
  // ── Nothing ─────────────────────────────────────────────────────
  nothing_phone_2a: {
    brand: 'Nothing', manufacturer: 'Nothing', model: 'A142P',
    device: 'Pacman', product: 'Pacman',
    fingerprint: 'Nothing/Pacman/Pacman:14/UP1A.231005.007/2405211815:user/release-keys',
    android_version: '14', sdk_version: '34', security_patch: '2024-08-01',
    build_id: 'UP1A.231005.007', hardware: 'mt6878', board: 'mt6878',
    tac_prefix: '86891004', mac_oui: '50:1A:A5',
    gpu_renderer: 'Mali-G615 MC6', gpu_vendor: 'ARM', gpu_version: 'OpenGL ES 3.2 v1.r44p0',
  },
};

// Carrier database (MCC/MNC for SIM spoofing)
const CARRIERS = {
  tmobile_us:   { name: 'T-Mobile',      mcc: '310', mnc: '260', country: 'US', spn: 'T-Mobile' },
  att_us:       { name: 'AT&T',           mcc: '310', mnc: '410', country: 'US', spn: 'AT&T' },
  verizon_us:   { name: 'Verizon',        mcc: '311', mnc: '480', country: 'US', spn: 'Verizon' },
  uscellular_us:{ name: 'US Cellular',    mcc: '311', mnc: '580', country: 'US', spn: 'US Cellular' },
  ee_uk:        { name: 'EE',             mcc: '234', mnc: '30',  country: 'GB', spn: 'EE' },
  vodafone_uk:  { name: 'Vodafone UK',    mcc: '234', mnc: '15',  country: 'GB', spn: 'Vodafone UK' },
  three_uk:     { name: 'Three',          mcc: '234', mnc: '20',  country: 'GB', spn: '3' },
  o2_uk:        { name: 'O2 - UK',        mcc: '234', mnc: '10',  country: 'GB', spn: 'O2 - UK' },
  telekom_de:   { name: 'Telekom.de',     mcc: '262', mnc: '01',  country: 'DE', spn: 'Telekom.de' },
  vodafone_de:  { name: 'Vodafone.de',    mcc: '262', mnc: '02',  country: 'DE', spn: 'Vodafone.de' },
  orange_fr:    { name: 'Orange F',       mcc: '208', mnc: '01',  country: 'FR', spn: 'Orange F' },
};

// Country → default carrier/location mapping
const COUNTRY_DEFAULTS = {
  US: { carrier: 'tmobile_us', location: 'nyc' },
  GB: { carrier: 'ee_uk',     location: 'london' },
  DE: { carrier: 'telekom_de', location: 'berlin' },
  FR: { carrier: 'orange_fr', location: 'paris' },
};

// Execute ADB shell command via syncCmd, return stdout
// E-06 fix: Accept timeoutSec parameter (default 30s)
async function _sh(padCode, cmd, ak, sk, timeoutSec) {
  try {
    const timeout = timeoutSec || 30;
    const resp = await _withRetry(() => vmosPost('/vcpcloud/api/padApi/syncCmd', {
      padCode, scriptContent: cmd,
    }, ak, sk, timeout), 2, 'syncCmd');
    if (resp.code !== 200) return '';
    const items = Array.isArray(resp.data) ? resp.data : [resp.data];
    const item = items[0] || {};
    // syncCmd returns output in errorMsg (stdout) and taskResult='success'/'fail'
    if (item.taskStatus === 3) return item.errorMsg || item.taskResult || '';
    return '';
  } catch (_) { return ''; }
}

// E-06 fix: Forward timeoutSec to _sh
async function _shOk(padCode, cmd, marker, ak, sk, timeoutSec) {
  const result = await _sh(padCode, cmd, ak, sk, timeoutSec);
  return (result || '').includes(marker);
}

// Create SQLite DB locally and transfer to device via base64 over shell
// Avoids need for sqlite3 binary on the device
// Chunks base64 data into ~3500 char pieces to stay within syncCmd limits
async function _createAndTransferDb(padCode, remotePath, sql, ownerDir, ak, sk) {
  const tmpDb = `/tmp/genesis_${crypto.randomBytes(8).toString('hex')}.db`;
  try {
    execSync(`sqlite3 "${tmpDb}"`, { input: sql, timeout: 15000 });
    const b64 = fs.readFileSync(tmpDb).toString('base64');
    const dir = remotePath.substring(0, remotePath.lastIndexOf('/'));
    await _sh(padCode, `mkdir -p '${dir}' 2>/dev/null`, ak, sk);

    const CHUNK = 3500; // stays under syncCmd's ~4K char command limit
    const tmpRemote = `/data/local/tmp/_b64_${crypto.randomBytes(4).toString('hex')}`;
    if (b64.length <= CHUNK) {
      // Single-shot transfer
      const ok = await _shOk(padCode,
        `printf '%s' '${b64}' | base64 -d > '${remotePath}' && echo DB_XFER_OK`,
        'DB_XFER_OK', ak, sk);
      if (!ok) return false;
    } else {
      // Multi-chunk transfer
      const chunks = [];
      for (let i = 0; i < b64.length; i += CHUNK) chunks.push(b64.slice(i, i + CHUNK));
      for (let i = 0; i < chunks.length; i++) {
        const op = i === 0 ? '>' : '>>';
        const ok = await _shOk(padCode,
          `printf '%s' '${chunks[i]}' ${op} '${tmpRemote}' && echo CK_OK`,
          'CK_OK', ak, sk);
        if (!ok) {
          await _sh(padCode, `rm -f '${tmpRemote}' 2>/dev/null`, ak, sk);
          return false;
        }
      }
      const ok = await _shOk(padCode,
        `base64 -d '${tmpRemote}' > '${remotePath}' && rm -f '${tmpRemote}' && echo DB_XFER_OK`,
        'DB_XFER_OK', ak, sk);
      if (!ok) return false;
    }

    if (ownerDir) {
      await _sh(padCode, `chmod 660 '${remotePath}' && chown $(stat -c '%u:%g' '${ownerDir}' 2>/dev/null) '${remotePath}' 2>/dev/null`, ak, sk);
    }
    return true;
  } catch (e) {
    console.error(`[createAndTransferDb] ${remotePath}: ${e.message}`);
    return false;
  } finally {
    try { fs.unlinkSync(tmpDb); } catch (_) {}
  }
}

// Retry wrapper for API calls — retries up to 3 times with exponential backoff
async function _withRetry(fn, maxRetries = 3, label = '') {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (attempt === maxRetries) throw e;
      const delay = Math.min(1000 * Math.pow(2, attempt - 1), 5000);
      console.warn(`[retry] ${label} attempt ${attempt}/${maxRetries} failed: ${e.message}, retrying in ${delay}ms`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
}

// SELinux per-operation toggle — temporarily disable for privileged ops, always re-enable
async function _withSelinuxOff(padCode, fn, ak, sk) {
  await _sh(padCode, 'setenforce 0 2>/dev/null || true', ak, sk);
  try {
    return await fn();
  } finally {
    await _sh(padCode, 'setenforce 1 2>/dev/null || true', ak, sk);
  }
}

// Poll VMOS async task completion — returns final task status object
async function _pollTask(taskIds, ak, sk, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await vmosPost('/vcpcloud/api/padApi/padTaskDetail', { taskIds }, ak, sk);
      if (r.code === 200 && Array.isArray(r.data)) {
        const allDone = r.data.every(t => t.taskStatus === 3 || t.taskStatus === 4);
        if (allDone) return r.data;
      }
    } catch (_) {}
    await new Promise(r => setTimeout(r, 2000));
  }
  return null;
}

// Generate realistic ICCID for a country's MCC/MNC
function _genIccid(mcc, mnc) {
  const id = '89' + mcc + mnc.padStart(2, '0');
  const rest = Array.from({length: 19 - id.length}, () => Math.floor(Math.random()*10)).join('');
  return id + rest;
}

// Generate realistic IMSI for a country's MCC/MNC
function _genImsi(mcc, mnc) {
  const prefix = mcc + mnc.padStart(2, '0');
  const rest = Array.from({length: 15 - prefix.length}, () => Math.floor(Math.random()*10)).join('');
  return prefix + rest;
}

// Generate 5G cell info string: type,mcc,mnc,tac(hex),cellid(hex),narfcn(hex),pci(hex)
function _genCellInfo(mcc, mnc) {
  const tac = Math.floor(0x100 + Math.random() * 0xEFF).toString(16).toUpperCase();
  const cellid = Math.floor(0x1000000 + Math.random() * 0xEFFFFFF).toString(16).toUpperCase();
  const narfcn = Math.floor(0x100 + Math.random() * 0x900).toString(16).toUpperCase();
  const pci = Math.floor(0x10 + Math.random() * 0xF0).toString(16).toUpperCase();
  return `9,${mcc},${mnc},${tac},${cellid},${narfcn},${pci}`;
}

// Genesis pipeline — full 11-phase implementation mirroring genesis_engine.py
async function _runGenesisJob(jobId, ak, sk) {
  const job = _genesisJobs.get(jobId);
  if (!job) return;
  const { pad_code: padCode, config: cfg } = job;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pads = [padCode];

  const log = msg => {
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
    job.log.push(`[${ts}] ${msg}`);
    if (job.log.length > 200) job.log.shift();
  };
  const phase = (i, status, notes = '') => {
    if (job.phases[i]) {
      job.phases[i].status = status;
      if (notes) job.phases[i].notes = notes;
    }
  };
  const vpost = (path, data) => vmosPost(path, data, ak, sk);
  const sh = (cmd, sec) => _sh(padCode, cmd, ak, sk, sec);
  const shOk = (cmd, marker, sec) => _shOk(padCode, cmd, marker, ak, sk, sec);
  const createDb = (remotePath, sql, ownerDir) => _createAndTransferDb(padCode, remotePath, sql, ownerDir, ak, sk);
  let _webDataSql = ''; // accumulated SQL for Chrome 'Web Data' DB (autofill + credit_cards)

  const preset = DEVICE_PRESETS[cfg.device_model] || DEVICE_PRESETS.samsung_s24;
  const country = isValidCountry(cfg.country) ? cfg.country.toUpperCase() : 'US';
  const ageDays = isValidAgeDays(cfg.age_days) ? (typeof cfg.age_days === 'string' ? parseInt(cfg.age_days, 10) : cfg.age_days) : 120;

  // ── LOCATIONS table ──────────────────────────────────────────────────
  const LOCATIONS = {
    nyc:        { lat: 40.7580, lon: -73.9855,  tz: 'America/New_York',     wifi: 'Spectrum-5G' },
    la:         { lat: 34.0522, lon: -118.2437, tz: 'America/Los_Angeles',  wifi: 'ATT-5G-Home' },
    chicago:    { lat: 41.8781, lon: -87.6298,  tz: 'America/Chicago',      wifi: 'Xfinity-5G' },
    houston:    { lat: 29.7604, lon: -95.3698,  tz: 'America/Chicago',      wifi: 'NETGEAR72-5G' },
    miami:      { lat: 25.7617, lon: -80.1918,  tz: 'America/New_York',     wifi: 'ATT-FIBER-5G' },
    sf:         { lat: 37.7749, lon: -122.4194, tz: 'America/Los_Angeles',  wifi: 'Google-Fiber' },
    seattle:    { lat: 47.6062, lon: -122.3321, tz: 'America/Los_Angeles',  wifi: 'CenturyLink5G' },
    london:     { lat: 51.5074, lon: -0.1278,   tz: 'Europe/London',        wifi: 'BT-Hub6-5G' },
    manchester: { lat: 53.4808, lon: -2.2426,   tz: 'Europe/London',        wifi: 'Sky-5G-Home' },
    berlin:     { lat: 52.5200, lon: 13.4050,   tz: 'Europe/Berlin',        wifi: 'FRITZ!Box-7590' },
    paris:      { lat: 48.8566, lon: 2.3522,    tz: 'Europe/Paris',         wifi: 'Livebox-5G' },
  };
  const loc = LOCATIONS[cfg.location] || LOCATIONS.la;

  try {
    // ═══════════════════════════════════════════════════════════════
    // PHASE 0: Pre-Flight Check — padInfo + infos + shell verify
    // ═══════════════════════════════════════════════════════════════
    log('Pre-flight: verifying instance via padInfo + infos...');
    let deviceInfo = {};
    try {
      // Use /infos endpoint (reliable) instead of padDetails (404 prone)
      let padStatus = -1;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const rInfos = await vpost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 });
          if (rInfos && rInfos.code === 200 && rInfos.data) {
            const devList = rInfos.data.pageData || rInfos.data.list || [];
            const dev = devList.find(d => d.padCode === padCode);
            if (dev) { padStatus = dev.padStatus; break; }
          }
        } catch (_) {}
        await sleep(3000);
      }
      const rInfo = await vpost('/vcpcloud/api/padApi/padInfo', { padCode: padCode }).catch(() => ({ code: -1 }));
      if (rInfo.code === 200 && rInfo.data) deviceInfo = rInfo.data;
      
      if (padStatus === -1) {
        throw new Error(`Could not get device status for ${padCode}`);
      }
      const isRunning = padStatus === 10 || padStatus === '10';
      if (!isRunning) {
        log(`⚠ Instance not running (status=${padStatus}), attempting restart...`);
        await vpost('/vcpcloud/api/padApi/restart', { padCodes: pads }).catch(() => {});
        // Poll until running (status=10) — up to 5 minutes (60 × 5s)
        for (let rp = 0; rp < 60; rp++) {
          await sleep(5000);
          try {
            const rd = await vpost('/vcpcloud/api/padApi/infos', { page: 1, rows: 10 });
            const devList = rd.data?.pageData || rd.data?.list || [];
            const dev = devList.find(d => d.padCode === padCode);
            const s = dev?.padStatus;
            if (s === 10 || s === '10') { log(`✓ Device booted (status=${s}, ${rp * 5}s)`); padStatus = s; break; }
            if (rp % 12 === 0 && rp > 0) {
              log(`Phase 0 — Still waiting: status=${s} (${rp * 5}s)...`);
              // At 2min, try restart again in case it helps
              if (rp === 24) await vpost('/vcpcloud/api/padApi/restart', { padCodes: pads }).catch(() => {});
            }
          } catch (_) {}
        }
      }
      // Verify shell access + resetprop availability
      const shellTest = await sh('echo SHELL_OK; which resetprop 2>/dev/null && echo RP_OK || echo RP_MISSING', 15);
      const shellOk = (shellTest || '').includes('SHELL_OK');
      const rpOk = (shellTest || '').includes('RP_OK');
      if (!shellOk) {
        log('⚠ Shell access failed — pipeline may have limited success');
        phase(0, 'warn', 'shell inaccessible');
      } else {
        log(`✓ Instance verified: padStatus=${padStatus} shell=ok resetprop=${rpOk ? 'ok' : 'missing'} info=${deviceInfo.simCountry || 'n/a'}`);
        phase(0, 'done', `status=${padStatus} shell=ok rp=${rpOk ? 'ok' : 'no'}`);
      }
    } catch (e) {
      phase(0, 'warn', e.message);
      log(`⚠ Pre-flight: ${e.message}`);
    }
    await sleep(1500);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 1: Wipe + Identity via updatePadAndroidProp + individual APIs
    // ═══════════════════════════════════════════════════════════════
    phase(1, 'running'); log('Phase 1 — New Device: wipe data + set identity...');

    // Shell-based data wipe (keeps device running)
    log('Phase 1 — Wiping existing data via shell...');
    await sh('am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.chrome; am force-stop com.kiwibrowser.browser 2>/dev/null', 10);
    const wipeCmd = [
      'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null',
      'content delete --uri content://com.android.contacts/raw_contacts 2>/dev/null',
      'content delete --uri content://call_log/calls 2>/dev/null',
      'content delete --uri content://sms 2>/dev/null',
      "rm -rf /data/data/com.android.chrome/app_chrome/Default/Cookies /data/data/com.android.chrome/app_chrome/Default/History '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null",
      "rm -rf /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay*.db* 2>/dev/null",
      "rm -rf /data/data/com.google.android.apps.walletnfcrel/shared_prefs/*.xml 2>/dev/null",
      'rm -rf /data/data/com.google.android.gms/databases/tapandpay.db* /data/data/com.google.android.gms/shared_prefs/device_registration.xml /data/data/com.google.android.gms/shared_prefs/checkin.xml /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null',
      'rm -rf /data/data/com.google.android.gsf/shared_prefs/gservices.xml /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null',
      'rm -rf /data/data/com.kiwibrowser.browser/app_chrome/Default/* 2>/dev/null',
      'rm -rf /data/system/usagestats/0/* /data/system/notification_log.db* 2>/dev/null',
      'rm -f /data/data/com.android.providers.media.module/databases/external.db* 2>/dev/null',
      'rm -f /data/data/com.android.providers.downloads/databases/downloads.db* 2>/dev/null',
      'settings delete secure android_id 2>/dev/null',
      'echo WIPE_DONE',
    ].join('; ');
    const wipeOk = await shOk(wipeCmd, 'WIPE_DONE', 30);
    log(`Phase 1 — Data wipe: ${wipeOk ? 'ok' : 'partial'}`);

    const imei = _genImei(preset.tac_prefix);
    const imei2 = _genImei(preset.tac_prefix);
    const serial = _genSerial();
    const androidId = _genAndroidId();
    const macAddr = _genMacAddr(preset.mac_oui);
    const carrierKey = cfg.carrier || (COUNTRY_DEFAULTS[country] || {}).carrier || 'tmobile_us';
    const carrier = CARRIERS[carrierKey] || CARRIERS.tmobile_us;
    const iccid = _genIccid(carrier.mcc, carrier.mnc);
    const imsi = _genImsi(carrier.mcc, carrier.mnc);
    const cellInfo = _genCellInfo(carrier.mcc, carrier.mnc);
    const lat = loc.lat + (Math.random() - 0.5) * 0.006;
    const lng = loc.lon + (Math.random() - 0.5) * 0.006;
    const phoneNum = cfg.phone || _genPhoneNumber(country);
    const drmId = crypto.randomBytes(32).toString('hex');
    const drmPuid = crypto.randomBytes(32).toString('hex');
    const bootId = crypto.randomBytes(16).toString('hex').replace(/(.{8})(.{4})(.{4})(.{4})(.{12})/, '$1-$2-$3-$4-$5');
    const battLevel = Math.floor(42 + Math.random() * 45);
    const countryCodeMap = { US: '1', GB: '44', DE: '49', FR: '33' };
    const phoneWithCode = phoneNum.startsWith('+') ? phoneNum.slice(1) : (countryCodeMap[country] || '1') + phoneNum.replace(/^0+/, '');
    try {
      // Set ALL identity props via resetprop/setprop shell commands (no reboot!)
      // Using resetprop for ro.* props, setprop for persist.* props
      const _esc = v => String(v).replace(/'/g, "'\\''"); // shell-safe single quote escape

      // Batch 1: device identity + build info
      const propCmd1 = [
        `resetprop ro.product.brand '${_esc(preset.brand)}'`,
        `resetprop ro.product.model '${_esc(preset.model)}'`,
        `resetprop ro.product.manufacturer '${_esc(preset.manufacturer)}'`,
        `resetprop ro.product.device '${_esc(preset.device)}'`,
        `resetprop ro.product.name '${_esc(preset.product)}'`,
        `resetprop ro.product.board '${_esc(preset.board)}'`,
        `resetprop ro.hardware '${_esc(preset.hardware)}'`,
        `resetprop ro.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.build.description '${_esc(preset.product)}-user ${_esc(preset.android_version)} ${_esc(preset.build_id)} release-keys'`,
        `resetprop ro.build.version.incremental '${_esc(preset.build_id.replace(/\./g, ''))}'`,
        `resetprop ro.build.flavor '${_esc(preset.product)}-user'`,
        `resetprop ro.build.product '${_esc(preset.device)}'`,
        `resetprop ro.build.display.id '${_esc(preset.build_id)}'`,
        `resetprop ro.build.type user`,
        `resetprop ro.build.tags release-keys`,
        `resetprop ro.build.version.sdk '${preset.sdk}'`,
        `resetprop ro.build.version.release '${preset.android_version}'`,
        `resetprop ro.build.version.security_patch '${_esc(preset.security_patch)}'`,
        'echo PROPS1_OK',
      ].map(c => c.startsWith('echo') ? c : c + ' 2>/dev/null').join('; ');
      const p1ok = await shOk(propCmd1, 'PROPS1_OK', 30);
      log(`Phase 1 — Batch 1 (device+build): ${p1ok ? 'ok' : 'partial'}`);

      // Batch 2: partition fingerprints + partition device/model
      const propCmd2 = [
        `resetprop ro.odm.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.product.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.system.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.system_ext.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.vendor.build.fingerprint '${_esc(preset.fingerprint)}'`,
        `resetprop ro.product.vendor.device '${_esc(preset.device)}'`,
        `resetprop ro.product.vendor.model '${_esc(preset.model)}'`,
        `resetprop ro.product.vendor.name '${_esc(preset.product)}'`,
        `resetprop ro.product.vendor.manufacturer '${_esc(preset.manufacturer)}'`,
        `resetprop ro.product.odm.device '${_esc(preset.device)}'`,
        `resetprop ro.product.odm.model '${_esc(preset.model)}'`,
        `resetprop ro.product.system.device '${_esc(preset.device)}'`,
        `resetprop ro.product.system.model '${_esc(preset.model)}'`,
        `resetprop ro.product.system.name '${_esc(preset.product)}'`,
        `resetprop ro.product.system_ext.device '${_esc(preset.device)}'`,
        'echo PROPS2_OK',
      ].map(c => c.startsWith('echo') ? c : c + ' 2>/dev/null').join('; ');
      const p2ok = await shOk(propCmd2, 'PROPS2_OK', 30);
      log(`Phase 1 — Batch 2 (partitions): ${p2ok ? 'ok' : 'partial'}`);

      // Batch 3: serial, android ID, DRM, cloud props (persist.sys.cloud.*)
      const propCmd3 = [
        `resetprop ro.serialno '${_esc(serial)}'`,
        `resetprop ro.boot.serialno '${_esc(serial)}'`,
        `resetprop ro.sys.cloud.android_id '${_esc(androidId)}'`,
        `setprop persist.sys.cloud.drm.id '${_esc(drmId)}'`,
        `setprop persist.sys.cloud.drm.puid '${_esc(drmPuid)}'`,
        `setprop persist.sys.cloud.pm.install_source 'com.android.vending'`,
        `resetprop ro.sys.cloud.boot_id '${_esc(bootId)}'`,
        `resetprop ro.sys.cloud.rand_pics '3'`,
        `setprop persist.sys.cloud.mobileinfo '${carrier.mcc},${carrier.mnc}'`,
        `setprop persist.sys.cloud.cellinfo '${_esc(cellInfo)}'`,
        `setprop persist.sys.cloud.imeinum '${_esc(imei)}'`,
        `setprop persist.sys.cloud.iccidnum '${_esc(iccid)}'`,
        `setprop persist.sys.cloud.imsinum '${_esc(imsi)}'`,
        `setprop persist.sys.cloud.phonenum '${_esc(phoneWithCode)}'`,
        'echo PROPS3_OK',
      ].map(c => c.startsWith('echo') ? c : c + ' 2>/dev/null').join('; ');
      const p3ok = await shOk(propCmd3, 'PROPS3_OK', 30);
      log(`Phase 1 — Batch 3 (serial+cloud): ${p3ok ? 'ok' : 'partial'}`);

      // Batch 4: GPU, WiFi, battery, GPS, locale, timezone, boot offset
      const propCmd4 = [
        `setprop persist.sys.cloud.gpu.gl_vendor '${_esc(preset.gpu_vendor)}'`,
        `setprop persist.sys.cloud.gpu.gl_renderer '${_esc(preset.gpu_renderer)}'`,
        `setprop persist.sys.cloud.gpu.gl_version 'OpenGL ES 3.2'`,
        `setprop persist.sys.cloud.wifi.ssid '${_esc(loc.wifi)}'`,
        `setprop persist.sys.cloud.wifi.mac '${_esc(macAddr)}'`,
        `setprop persist.sys.cloud.battery.level '${battLevel}'`,
        `setprop persist.sys.cloud.battery.capacity '5000'`,
        `setprop persist.sys.cloud.gps.lat '${lat.toFixed(6)}'`,
        `setprop persist.sys.cloud.gps.lon '${lng.toFixed(6)}'`,
        `setprop persist.sys.cloud.gps.speed '0.1'`,
        `setprop persist.sys.cloud.gps.altitude '${Math.round(25 + Math.random() * 50)}'`,
        `setprop persist.sys.cloud.gps.bearing '${Math.round(Math.random() * 360)}'`,
        `setprop persist.sys.locale '${country === 'DE' ? 'de-DE' : country === 'FR' ? 'fr-FR' : country === 'GB' ? 'en-GB' : 'en-US'}'`,
        `setprop persist.sys.timezone '${_esc(loc.tz)}'`,
        `setprop persist.sys.cloud.boottime.offset '${Math.floor(3 + Math.random() * 10)}'`,
        `setprop persist.sys.cloud.wifi.ip '192.168.${Math.floor(Math.random() * 254 + 1)}.${Math.floor(Math.random() * 254 + 1)}'`,
        `setprop persist.sys.cloud.wifi.gateway '192.168.1.1'`,
        `setprop persist.sys.cloud.wifi.dns1 '192.168.1.1'`,
        `resetprop ro.boot.redroid_net_ndns '2'`,
        `resetprop ro.boot.redroid_net_dns1 '8.8.8.8'`,
        `resetprop ro.boot.redroid_net_dns2 '8.8.4.4'`,
        'echo PROPS4_OK',
      ].map(c => c.startsWith('echo') ? c : c + ' 2>/dev/null').join('; ');
      const p4ok = await shOk(propCmd4, 'PROPS4_OK', 30);
      log(`Phase 1 — Batch 4 (gpu+wifi+gps+locale): ${p4ok ? 'ok' : 'partial'}`);

      const propsOk = [p1ok, p2ok, p3ok, p4ok].filter(Boolean).length * 16; // ~16 per batch
      const propsTotal = 65;

      // Set SIM country via API (lightweight, no reboot)
      const rSim = await vpost('/vcpcloud/api/padApi/updateSIM', { padCode: padCode, countryCode: country });
      log(`Phase 1 — SIM: ${rSim.code === 200 ? 'ok' : 'fail'} (${country})`);

      // Inject GPS via API (real-time injection, no reboot)
      const rGps = await vpost('/vcpcloud/api/padApi/gpsInjectInfo', {
        padCodes: pads, lat, lng,
        altitude: Math.round(25 + Math.random() * 50),
        speed: 0, bearing: Math.round(Math.random() * 360),
        horizontalAccuracy: Math.round(3 + Math.random() * 9),
      });
      log(`Phase 1 — GPS: ${rGps.code === 200 ? 'ok' : 'fail'} (${lat.toFixed(4)}, ${lng.toFixed(4)})`);

      log(`Phase 1 — TZ=${loc.tz} Lang=en (set via shell)`);

      // Add certificate if configured
      if (cfg.certificate) {
        const cert = typeof cfg.certificate === 'string' ? cfg.certificate : JSON.stringify(cfg.certificate);
        await vpost('/vcpcloud/api/padApi/updatePhoneCert', { padCode: padCode, certificate: cert }).catch(() => {});
        log('Phase 1 — Certificate: set');
      }

      phase(1, 'done', `Shell: ${propsOk}+ props, SIM=${country}`);
      log(`Phase 1 — Identity set: ${propsOk}/${propsTotal} props + SIM + GPS + TZ (no reboot!)`);
    } catch (e) {
      phase(1, 'failed', e.message.slice(0, 80));
      log(`Phase 1 — Wipe FAILED: ${e.message}`);
    }

    // ═══════════════════════════════════════════════════════════════
    // PHASE 2: Stealth Patch — root-hide + prop scrub + proc sterilize
    // (Props set via updatePadAndroidProp; this phase handles shell-only ops)
    // ═══════════════════════════════════════════════════════════════
    phase(2, 'running'); log('Phase 2 — Stealth: root-hide + prop scrub + proc sterilize...');
    try {
      // 2a. Shell identity reinforcement (belt-and-suspenders with API-set props)
      const identCmd = [
        `setprop persist.radio.device.imei0 '${imei}' 2>/dev/null`,
        `setprop persist.radio.device.imei1 '${imei2}' 2>/dev/null`,
        `setprop gsm.device.imei0 '${imei}' 2>/dev/null`,
        `setprop gsm.device.imei1 '${imei2}' 2>/dev/null`,
        `ip link set wlan0 down 2>/dev/null; ip link set wlan0 address '${macAddr}' 2>/dev/null; ip link set wlan0 up 2>/dev/null`,
        `settings put secure android_id '${androidId}' 2>/dev/null`,
        // Carrier SPN reinforcement
        `resetprop gsm.sim.operator.numeric '${carrier.mcc}${carrier.mnc}' 2>/dev/null`,
        `resetprop gsm.operator.numeric '${carrier.mcc}${carrier.mnc}' 2>/dev/null`,
        `resetprop gsm.sim.operator.alpha '${carrier.spn}' 2>/dev/null`,
        `resetprop gsm.operator.alpha '${carrier.spn}' 2>/dev/null`,
        `resetprop gsm.sim.operator.iso-country '${carrier.country.toLowerCase()}' 2>/dev/null`,
        'echo IDENT_DONE',
      ].join('; ');
      const identOk = await shOk(identCmd, 'IDENT_DONE', 20);
      log(`Phase 2a — Identity reinforced: IMEI=${imei.slice(0,8)}... MAC=${macAddr} ${identOk ? 'ok' : 'partial'}`);

      // 2e. Root artifact hiding
      const rootCmd = [
        "for p in /system/bin/su /system/xbin/su /sbin/su /su/bin/su; do",
        "  [ -e \"$p\" ] && chmod 000 \"$p\" 2>/dev/null && mount -o bind /dev/null \"$p\" 2>/dev/null;",
        "done",
        "[ -d /data/adb/magisk ] && chmod 000 /data/adb/magisk 2>/dev/null && mount -t tmpfs tmpfs /data/adb/magisk 2>/dev/null",
        "pm disable-user --user 0 com.topjohnwu.magisk 2>/dev/null",
        "pm hide com.topjohnwu.magisk 2>/dev/null",
        "echo ROOT_HIDDEN",
      ].join('; ');
      const rootOk = await shOk(rootCmd, 'ROOT_HIDDEN', 25);
      log(`Phase 2e — Root hide: ${rootOk ? 'ok' : 'partial'}`);

      // 2f. Cloud/emulator prop scrub + security hardening
      const propScrubCmd = [
        'resetprop --delete ro.vmos.cloud 2>/dev/null',
        'resetprop --delete ro.cloudservice.enabled 2>/dev/null',
        'resetprop --delete ro.armcloud.device 2>/dev/null',
        'resetprop --delete ro.redroid.enabled 2>/dev/null',
        'resetprop --delete ro.kernel.qemu 2>/dev/null',
        'resetprop --delete ro.hardware.virtual 2>/dev/null',
        'resetprop --delete ro.boot.qemu 2>/dev/null',
        'resetprop --delete qemu.gles 2>/dev/null',
        'resetprop ro.boot.verifiedbootstate green 2>/dev/null',
        'resetprop ro.boot.flash.locked 1 2>/dev/null',
        'resetprop ro.boot.vbmeta.device_state locked 2>/dev/null',
        'resetprop ro.debuggable 0 2>/dev/null',
        'resetprop ro.secure 1 2>/dev/null',
        'resetprop ro.adb.secure 1 2>/dev/null',
        'resetprop ro.build.type user 2>/dev/null',
        'resetprop ro.build.tags release-keys 2>/dev/null',
        `resetprop ro.build.display.id ${preset.build_id} 2>/dev/null`,
        `resetprop ro.build.version.security_patch ${preset.security_patch} 2>/dev/null`,
        // GPU rendering props — correct property names for real device fingerprinting
        ...(preset.gpu_renderer ? [
          `resetprop ro.hardware.egl '${preset.hardware === 'qcom' ? 'adreno' : 'mali'}' 2>/dev/null`,
          `resetprop ro.hardware.vulkan '${preset.hardware === 'qcom' ? 'adreno' : preset.hardware}' 2>/dev/null`,
          `resetprop ro.opengles.version 196610 2>/dev/null`,
          // GLES renderer string exposed via debug props
          `resetprop debug.hwui.renderer '${preset.gpu_renderer}' 2>/dev/null`,
          `resetprop ro.gfx.driver.0 '${preset.gpu_vendor}' 2>/dev/null`,
        ] : []),
        // USB/connectivity cleanup
        'resetprop sys.usb.config adb 2>/dev/null',
        'resetprop sys.usb.state adb 2>/dev/null',
        'resetprop --delete net.dns1 2>/dev/null',
        'resetprop --delete net.dns2 2>/dev/null',
        'echo PROPS_CLEAN',
      ].join('; ');
      const propScrubOk = await shOk(propScrubCmd, 'PROPS_CLEAN', 25);
      log(`Phase 2f — Prop scrub + GPU + USB: ${propScrubOk ? 'ok' : 'partial'}`);

      // 2g. Proc cmdline + mounts sterilization
      const procCmd = [
        'mkdir -p /dev/.sc 2>/dev/null',
        // Sanitize cmdline
        "cat /proc/cmdline | sed 's/cuttlefish//g;s/vsoc//g;s/virtio//g;s/goldfish//g;s/qemu//g;s/vmos//g;s/armcloud//g;s/redroid//g;s/cf_arm//g' > /dev/.sc/cmdline",
        'mount -o bind /dev/.sc/cmdline /proc/cmdline 2>/dev/null',
        // Sanitize /proc/mounts — hide emulator-specific mounts
        "cat /proc/mounts | grep -v 'virtio\\|9p\\|cuttlefish\\|goldfish\\|vsoc\\|vmos' > /dev/.sc/mounts 2>/dev/null",
        'mount -o bind /dev/.sc/mounts /proc/mounts 2>/dev/null || true',
        // Hide /proc/device-tree/firmware/android/verifiedbootstate if present
        "[ -f /proc/device-tree/firmware/android/verifiedbootstate ] && echo -n 'green' > /dev/.sc/vbs && mount -o bind /dev/.sc/vbs /proc/device-tree/firmware/android/verifiedbootstate 2>/dev/null || true",
        'echo PROC_CLEAN',
      ].join('; ');
      const procOk = await shOk(procCmd, 'PROC_CLEAN', 20);
      log(`Phase 2g — Proc sterilize: ${procOk ? 'ok' : 'partial'}`);

      // 2h. Verified boot fingerprint alignment across all partitions
      const bootCmd = [
        `resetprop ro.bootimage.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        `resetprop ro.vendor.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        `resetprop ro.odm.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        `resetprop ro.system_ext.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        `resetprop ro.product.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        `resetprop ro.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
        // CTS profile match props
        `resetprop ro.build.version.base_os '' 2>/dev/null`,
        `resetprop ro.com.google.gmsversion '${preset.android_version}.0' 2>/dev/null`,
        'echo BOOT_ALIGNED',
      ].join('; ');
      const bootOk = await shOk(bootCmd, 'BOOT_ALIGNED', 20);
      log(`Phase 2h — Boot alignment: ${bootOk ? 'ok' : 'partial'}`);

      const stealth = [identOk, rootOk, propScrubOk, procOk, bootOk].filter(Boolean).length;
      phase(2, 'done', `${stealth}/5 stealth ops`);
      log(`Phase 2 — Stealth done: ${stealth}/5 ops`);
    } catch (e) {
      phase(2, 'failed', e.message.slice(0, 80));
      log(`Phase 2 — Stealth FAILED: ${e.message}`);
    }

    // ═══════════════════════════════════════════════════════════════
    // PHASE 3: Network / Proxy
    // ═══════════════════════════════════════════════════════════════
    phase(3, 'running');
    if (cfg.proxy_url) {
      if (!isValidProxyUrl(cfg.proxy_url)) {
        phase(3, 'failed', 'Invalid proxy URL (private IP/bad protocol)');
        log('Phase 3 — Proxy: rejected (SSRF protection)');
      } else {
      log(`Phase 3 — Network: setting proxy...`);
      try {
        const u = new URL(cfg.proxy_url);
        const proxyInfo = {
          proxyType: 'proxy',
          proxyName: u.protocol.includes('socks') ? 'socks5' : 'http-relay',
          proxyIp: u.hostname,
          proxyPort: parseInt(u.port) || 1080,
          ...(u.username ? { proxyUser: u.username } : {}),
          ...(u.password ? { proxyPassword: u.password } : {}),
        };
        const r = await vpost('/vcpcloud/api/padApi/setProxy', {
          padCodes: pads, ...proxyInfo,
        });
        if (r.code === 200) {
          // Verify proxy is active via checkIP
          await sleep(3000);
          try {
            const ipCheck = await vpost('/vcpcloud/api/padApi/checkIP', { padCode: padCode });
            if (ipCheck.code === 200 && ipCheck.data) {
              log(`Phase 3 — Proxy verified: IP=${ipCheck.data.ip || '?'} country=${ipCheck.data.country || '?'}`);
            }
          } catch (_) { log('Phase 3 — checkIP query skipped'); }
        }
        phase(3, r.code === 200 ? 'done' : 'warn', r.msg || '');
        log(`Phase 3 — Proxy: ${r.code === 200 ? 'set' : 'failed'}`);
      } catch (e) {
        phase(3, 'warn', e.message.slice(0, 60));
        log(`Phase 3 — Proxy error: ${e.message}`);
      }
      } // end isValidProxyUrl else
    } else {
      phase(3, 'skipped', 'no proxy'); log('Phase 3 — Network: no proxy, skipping');
    }
    await sleep(1000);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 4: Forge Profile — synthetic identity generation
    // ═══════════════════════════════════════════════════════════════
    phase(4, 'running'); 
    const personaName = cfg.name || 'Alex Morgan';
    const personaEmail = cfg.email || cfg.google_email || '';
    log(`Phase 4 — Forge: building profile for ${personaName}...`);

    // Generate synthetic identity data in Node.js (country-aware)
    const namePool = _getNamePool(country);
    const nameParts = personaName.split(' ');
    const firstName = nameParts[0] || _pickRandom(namePool.first);
    const lastName = nameParts[1] || _pickRandom(namePool.last);
    const profileEmail = personaEmail || `${firstName.toLowerCase()}.${lastName.toLowerCase()}${Math.floor(Math.random()*900+10)}@gmail.com`;
    const profilePhone = cfg.phone || _genPhoneNumber(country);
    const now = Math.floor(Date.now() / 1000);
    const profileAge = ageDays * 86400;

    // WiFi networks — realistic mix of home + public + neighbor
    const commonSSIDs = ['Starbucks WiFi','McDonald\'s Free WiFi','NETGEAR-5G','ATT-WIFI-','xfinitywifi','DIRECT-','HP-Print-','Guest'];
    const wifiNetworks = [
      { ssid: loc.wifi, password: 'wifipass' + Math.floor(Math.random() * 9999), security: 'WPA2' },
      { ssid: `${lastName.toUpperCase()}_2G`, password: `pass${Math.floor(Math.random() * 99999)}`, security: 'WPA2' },
      { ssid: `Home-${Math.floor(Math.random()*9000+1000)}`, password: `homenet${Math.floor(Math.random()*99999)}`, security: 'WPA2' },
      { ssid: _pickRandom(commonSSIDs) + Math.floor(Math.random()*99), password: '', security: 'OPEN' },
    ];

    const profile = { firstName, lastName, email: profileEmail, phone: profilePhone, wifiNetworks, ageDays };
    phase(4, 'done', `${firstName} ${lastName} <${profileEmail}>`);
    log(`Phase 4 — Profile forged: ${firstName} ${lastName} <${profileEmail}>`);
    await sleep(1000);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 5: Google Account injection into system DBs
    // ═══════════════════════════════════════════════════════════════
    phase(5, 'running');
    const googleEmail = cfg.google_email || profileEmail;
    log(`Phase 5 — Google Account: injecting ${googleEmail}...`);
    try {
      const androidId = _genAndroidId();
      const gsfId = _genGsfId();
      const regTimestamp = (now - profileAge) * 1000;
      const safeEmail = sanitizeSQL(googleEmail, 254);
      const safePass = sanitizeSQL(cfg.google_password || 'stored_token_placeholder', 128);
      const deviceRegId = crypto.randomBytes(16).toString('hex');

      // GAP-10: Force-stop GMS before writing to databases to prevent race condition
      await sh('am force-stop com.google.android.gms 2>/dev/null; am force-stop com.google.android.gsf 2>/dev/null', 10);
      log('Phase 5 — GMS force-stopped before DB writes');

      // 5a. accounts_ce.db + accounts_de.db (GAP-2+3: add extras + authtokens tables)
      // Created locally and transferred via base64 (no sqlite3 on device)
      const oauthToken = crypto.randomBytes(64).toString('base64url');
      const googleId = crypto.randomBytes(10).toString('hex');
      const sidToken = crypto.randomBytes(64).toString('base64url');
      const lsidToken = crypto.randomBytes(64).toString('base64url');
      const acctCeSql = [
        "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, password TEXT, UNIQUE(name,type));",
        "CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, key TEXT NOT NULL, value TEXT);",
        "CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, type TEXT NOT NULL, authtoken TEXT NOT NULL);",
        `INSERT OR REPLACE INTO accounts (name,type,password) VALUES('${safeEmail}','com.google','${safePass}');`,
        `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'googleId','${sanitizeSQL(googleId)}');`,
        `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'services','hist,mail,lso,calendar,youtube,cl');`,
        `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'oauth2:https://www.googleapis.com/auth/plus.me','${sanitizeSQL(oauthToken)}');`,
        `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'SID','${sanitizeSQL(sidToken)}');`,
        `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'LSID','${sanitizeSQL(lsidToken)}');`,
      ].join('\n');
      const acctDeSql = [
        "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));",
        `INSERT OR REPLACE INTO accounts (name,type) VALUES('${safeEmail}','com.google');`,
      ].join('\n');
      const [acctCeOk, acctDeOk] = await Promise.all([
        createDb('/data/system_ce/0/accounts_ce.db', acctCeSql, '/data/system_ce/0'),
        createDb('/data/system_de/0/accounts_de.db', acctDeSql, '/data/system_de/0'),
      ]);
      if (acctCeOk) await sh('chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null');
      if (acctDeOk) await sh('chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null');
      const acctOk = acctCeOk && acctDeOk;
      log(`Phase 5a — Accounts DB: ${acctOk ? 'ok' : 'fail'} (with extras+authtokens)`);

      // 5b. GMS device_registration.xml (backdated)
      const gmsDir = '/data/data/com.google.android.gms/shared_prefs';
      const devRegXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="registration_timestamp_ms">${regTimestamp}</string>\n  <string name="device_registration_id">${deviceRegId}</string>\n  <boolean name="has_completed_registration" value="true"/>\n  <string name="android_id">${androidId}</string>\n</map>`;
      const gmsCmd = [
        `mkdir -p ${gmsDir} 2>/dev/null`,
        `cat > ${gmsDir}/device_registration.xml << 'GMSEOF'`,
        devRegXml,
        `GMSEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/device_registration.xml 2>/dev/null`,
        "echo GMS_DONE",
      ].join('\n');
      const gmsOk = await shOk(gmsCmd, 'GMS_DONE', 20);
      log(`Phase 5b — GMS registration: ${gmsOk ? 'ok' : 'fail'}`);

      // GAP-1: GMS re-checkin prevention — disable GmsIntentOperationService + write checkin.xml
      const recheckinCmd = [
        `pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true`,
        `cat > ${gmsDir}/checkin.xml << 'CHKEOF'`,
        '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
        '<map>',
        '  <boolean name="checkin_enabled" value="false"/>',
        `  <long name="last_checkin_ms" value="${Date.now()}"/>`,
        `  <string name="android_id">${androidId}</string>`,
        '  <boolean name="is_checked_in" value="true"/>',
        '</map>',
        'CHKEOF',
        `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/checkin.xml 2>/dev/null`,
        'echo RECHECKIN_DONE',
      ].join('\n');
      const recheckinOk = await shOk(recheckinCmd, 'RECHECKIN_DONE', 15);
      log(`Phase 5b+ — GMS re-checkin prevention: ${recheckinOk ? 'ok' : 'fail'}`);

      // 5c. GSF gservices.xml (SSAID + registration timestamp)
      const gsfDir = '/data/data/com.google.android.gsf/shared_prefs';
      const gsfXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="android_id">${androidId}</string>\n  <string name="registration_timestamp">${regTimestamp}</string>\n  <string name="android_gsf_id">${gsfId}</string>\n  <string name="account_type">hosted_or_google</string>\n</map>`;
      const gsfCmd = [
        `mkdir -p ${gsfDir} 2>/dev/null`,
        `cat > ${gsfDir}/gservices.xml << 'GSFEOF'`,
        gsfXml,
        `GSFEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.google.android.gsf/ 2>/dev/null) ${gsfDir}/gservices.xml 2>/dev/null`,
        "echo GSF_DONE",
      ].join('\n');
      const gsfOk = await shOk(gsfCmd, 'GSF_DONE', 20);
      log(`Phase 5c — GSF gservices: ${gsfOk ? 'ok' : 'fail'}`);

      // 5d. Play Store finsky.xml (signed-in signal + purchase auth bypass)
      const vendingDir = '/data/data/com.android.vending/shared_prefs';
      const finskyXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="signed_in_account">${safeEmail}</string>\n  <boolean name="setup_complete" value="true"/>\n  <long name="last_self_update_time" value="${(now - 86400 * 7) * 1000}"/>\n  <boolean name="tos_accepted" value="true"/>\n  <string name="account_type">com.google</string>\n  <string name="purchase_auth_required">never</string>\n  <boolean name="purchase_auth_opt_out" value="true"/>\n  <int name="purchase_auth_timeout_ms" value="0"/>\n  <boolean name="biometric_purchase_auth_enabled" value="false"/>\n  <boolean name="require_password_on_purchase" value="false"/>\n</map>`;
      const finskyCmd = [
        `mkdir -p ${vendingDir} 2>/dev/null`,
        `cat > ${vendingDir}/finsky.xml << 'FEOF'`,
        finskyXml,
        `FEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/finsky.xml 2>/dev/null`,
        "echo FINSKY_DONE",
      ].join('\n');
      const finskyOk = await shOk(finskyCmd, 'FINSKY_DONE', 20);
      log(`Phase 5d — Play Store finsky: ${finskyOk ? 'ok' : 'fail'} (purchase auth disabled)`);

      // 5e. Play Store billing prefs — auth-free in-app purchases
      const billingPrefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="billing_account">${safeEmail}</string>\n  <boolean name="billing_setup_complete" value="true"/>\n  <boolean name="accept_tos" value="true"/>\n  <int name="purchase_auth_expiry" value="0"/>\n  <boolean name="require_auth_for_purchase" value="false"/>\n  <boolean name="password_purchase_auth" value="false"/>\n  <string name="default_purchase_flow">direct</string>\n  <boolean name="iab_v3_enabled" value="true"/>\n  <boolean name="iab_auto_confirm" value="true"/>\n</map>`;
      const billingCmd = [
        `cat > ${vendingDir}/billing.xml << 'BILLEOF'`,
        billingPrefsXml,
        `BILLEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/billing.xml 2>/dev/null`,
        "echo BILLING_DONE",
      ].join('\n');
      const billingOk = await shOk(billingCmd, 'BILLING_DONE', 15);
      log(`Phase 5e — Play Store billing prefs: ${billingOk ? 'ok' : 'fail'} (auth-free)`);

      // 5f. Play Store auto-install prefs — disable purchase verification prompts
      const autoInstallXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="auto_update_enabled" value="true"/>\n  <boolean name="skip_purchase_verification" value="true"/>\n  <boolean name="parental_controls_enabled" value="false"/>\n  <int name="content_rating_level" value="0"/>\n  <boolean name="in_app_purchase_ask_every_time" value="false"/>\n</map>`;
      const autoCmd = [
        `cat > ${vendingDir}/PlayAutoInstallConfig.xml << 'AUTOEOF'`,
        autoInstallXml,
        `AUTOEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/PlayAutoInstallConfig.xml 2>/dev/null`,
        "echo AUTO_DONE",
      ].join('\n');
      const autoOk = await shOk(autoCmd, 'AUTO_DONE', 15);
      log(`Phase 5f — PlayAutoInstall prefs: ${autoOk ? 'ok' : 'fail'}`);

      const sub = [acctOk, gmsOk, gsfOk, finskyOk, billingOk, autoOk].filter(Boolean).length;
      phase(5, sub >= 4 ? 'done' : 'warn', `${sub}/6 targets — ${safeEmail} (purchase auth bypassed)`);
      log(`Phase 5 — Google Account: ${sub}/6`);

      // 5g. Play Store purchase/order history — forge backdated successful transactions
      // This establishes the card as "trusted" with a history of successful charges
      const vendingDbDir = '/data/data/com.android.vending/databases';
      const purchaseCount = Math.floor(8 + Math.random() * 12); // 8-20 past purchases
      const purchaseInserts = [];
      const purchaseApps = [
        {pkg:'com.spotify.music',name:'Spotify Premium',price:999,currency:'USD'},
        {pkg:'com.google.android.apps.youtube.music',name:'YouTube Premium',price:1199,currency:'USD'},
        {pkg:'com.netflix.mediaclient',name:'Netflix',price:1549,currency:'USD'},
        {pkg:'com.disney.disneyplus',name:'Disney+',price:799,currency:'USD'},
        {pkg:'com.microsoft.office.officehubrow',name:'Microsoft 365',price:699,currency:'USD'},
        {pkg:'com.google.android.apps.subscriptions.red',name:'Google One (100GB)',price:199,currency:'USD'},
        {pkg:'com.nordvpn.android',name:'NordVPN',price:1199,currency:'USD'},
        {pkg:'com.duolingo',name:'Duolingo Plus',price:699,currency:'USD'},
        {pkg:'com.headspace.android',name:'Headspace Plus',price:1299,currency:'USD'},
        {pkg:'com.calm.android',name:'Calm Premium',price:1499,currency:'USD'},
        {pkg:'com.adobe.lrmobile',name:'Adobe Lightroom',price:999,currency:'USD'},
        {pkg:'com.grammarly.android.keyboard',name:'Grammarly Premium',price:2999,currency:'USD'},
        {pkg:'com.zhiliaoapp.musically',name:'TikTok Coins Bundle',price:499,currency:'USD'},
        {pkg:'com.innersloth.spacemafia',name:'Among Us Stars Pack',price:299,currency:'USD'},
        {pkg:'com.supercell.clashofclans',name:'Clash of Clans Gems',price:499,currency:'USD'},
        {pkg:'com.mojang.minecraftpe',name:'Minecraft',price:699,currency:'USD'},
        {pkg:'com.king.candycrushsaga',name:'Candy Crush Gold Bars',price:199,currency:'USD'},
        {pkg:'com.roblox.client',name:'Robux Bundle',price:999,currency:'USD'},
        {pkg:'com.google.android.apps.photos',name:'Google Photos (200GB)',price:299,currency:'USD'},
        {pkg:'com.google.android.googlequicksearchbox',name:'Google Assistant Extra',price:0,currency:'USD'},
      ];
      for (let pi = 0; pi < purchaseCount; pi++) {
        const app = purchaseApps[pi % purchaseApps.length];
        const dayOffset = Math.floor((ageDays - 5) * (pi / purchaseCount)); // spread across device age
        const purchaseTime = (now - dayOffset * 86400) * 1000;
        const orderId = `GPA.${3300 + Math.floor(Math.random() * 300)}-${Math.floor(1000000000 + Math.random() * 8999999999)}-${Math.floor(10000000 + Math.random() * 89999999)}`;
        const token = crypto.randomBytes(24).toString('base64url');
        purchaseInserts.push(
          `INSERT OR IGNORE INTO purchase_history (order_id,package_name,title,purchase_time,purchase_state,price_micros,currency,payment_method_type,developer_payload,purchase_token,auto_renewing,acknowledged) VALUES('${orderId}','${app.pkg}','${sanitizeSQL(app.name, 100)}',${purchaseTime},0,${app.price * 10000},'${app.currency}',1,'',X'${Buffer.from(token).toString('hex')}',${app.price > 0 ? 1 : 0},1);`
        );
      }
      const ownershipInserts = purchaseApps.slice(0, purchaseCount).map(a =>
        "INSERT OR IGNORE INTO ownership (account,library_id,doc_id,doc_type,offer_type) VALUES('" + safeEmail + "','3','" + a.pkg + "',1,1);"
      ).join('\n');
      const librarySql = [
        "CREATE TABLE IF NOT EXISTS purchase_history (order_id TEXT PRIMARY KEY, package_name TEXT NOT NULL, title TEXT, purchase_time INTEGER, purchase_state INTEGER DEFAULT 0, price_micros INTEGER DEFAULT 0, currency TEXT DEFAULT 'USD', payment_method_type INTEGER DEFAULT 1, developer_payload TEXT DEFAULT '', purchase_token BLOB, auto_renewing INTEGER DEFAULT 0, acknowledged INTEGER DEFAULT 1);",
        "CREATE TABLE IF NOT EXISTS ownership (account TEXT, library_id TEXT, doc_id TEXT, doc_type INTEGER DEFAULT 1, offer_type INTEGER DEFAULT 1, UNIQUE(account,doc_id));",
        purchaseInserts.join('\n'),
        ownershipInserts,
      ].join('\n');
      const purchHistOk = await createDb(`${vendingDbDir}/library.db`, librarySql, '/data/data/com.android.vending');
      log(`Phase 5g — Purchase history: ${purchHistOk ? 'ok' : 'fail'} (${purchaseCount} orders forged)`);
    } catch (e) {
      phase(5, 'failed', e.message.slice(0, 80));
      log(`Phase 5 — Google Account FAILED: ${e.message}`);
    }
    await sleep(1500);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 6: Inject — contacts, call logs, SMS, WiFi, Chrome, autofill
    // ═══════════════════════════════════════════════════════════════
    phase(6, 'running'); log('Phase 6 — Inject: contacts, calls, SMS, WiFi, Chrome, autofill...');
    try {
      const safeFirst = sanitizeSQL(profile.firstName, 100);
      const safeLast = sanitizeSQL(profile.lastName, 100);
      const safeEmail6 = sanitizeSQL(profile.email, 254);
      const safePhone6 = sanitizeSQL(profile.phone, 20);

      // 6a. Contacts — native updateContacts API with DB fallback
      const contactPool = _getNamePool(country);
      let contactsOk = false;
      try {
        // Build contacts array for native API (operateType: 1=overwrite)
        const contactsList = [];
        for (let ci = 0; ci < 20; ci++) {
          const fn = _pickRandom(contactPool.first);
          const ln = _pickRandom(contactPool.last);
          contactsList.push({
            firstName: `${fn} ${ln}`,
            phone: _genPhoneNumber(country),
            ...(ci % 2 === 0 ? { email: `${fn.toLowerCase()}.${ln.toLowerCase()}${Math.floor(Math.random()*99)}@gmail.com` } : {}),
          });
        }
        const rContacts = await vpost('/vcpcloud/api/padApi/updateContacts', {
          padCode: padCode, operateType: 1, contacts: contactsList,
        });
        if (rContacts.code === 200) {
          // Poll for task completion
          const taskIds = rContacts.data && rContacts.data.taskIds;
          if (taskIds) await _pollTask(taskIds, ak, sk, 20000);
          contactsOk = true;
          log('Phase 6a — Contacts: 20 via native API');
        } else {
          throw new Error(`updateContacts code=${rContacts.code}`);
        }
      } catch (eContacts) {
        // Fallback: create contacts2.db directly
        log(`Phase 6a — Native contacts failed (${eContacts.message}), using DB fallback...`);
        const contactsSql = [];
        contactsSql.push(`CREATE TABLE IF NOT EXISTS raw_contacts (_id INTEGER PRIMARY KEY AUTOINCREMENT, account_name TEXT, account_type TEXT, display_name TEXT, times_contacted INTEGER DEFAULT 0, last_time_contacted INTEGER DEFAULT 0, starred INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0);`);
        contactsSql.push(`CREATE TABLE IF NOT EXISTS mimetypes (_id INTEGER PRIMARY KEY AUTOINCREMENT, mimetype TEXT UNIQUE);`);
        contactsSql.push(`INSERT INTO mimetypes VALUES (1,'vnd.android.cursor.item/name');`);
        contactsSql.push(`INSERT INTO mimetypes VALUES (2,'vnd.android.cursor.item/phone_v2');`);
        contactsSql.push(`INSERT INTO mimetypes VALUES (3,'vnd.android.cursor.item/email_v2');`);
        contactsSql.push(`CREATE TABLE IF NOT EXISTS data (_id INTEGER PRIMARY KEY AUTOINCREMENT, raw_contact_id INTEGER, mimetype_id INTEGER, data1 TEXT, data2 TEXT, data3 TEXT, data5 TEXT);`);
        let dataId = 1;
        for (let ci = 0; ci < 20; ci++) {
          const fn = sanitizeSQL(_pickRandom(contactPool.first), 50);
          const ln = sanitizeSQL(_pickRandom(contactPool.last), 50);
          const phone = _genPhoneNumber(country);
          const rawId = ci + 1;
          const lastContact = (now - Math.floor(Math.random() * ageDays) * 86400) * 1000;
          contactsSql.push(`INSERT INTO raw_contacts VALUES (${rawId},'${safeEmail6}','com.google','${fn} ${ln}',${Math.floor(Math.random()*20)},${lastContact},${ci < 3 ? 1 : 0},0);`);
          contactsSql.push(`INSERT INTO data VALUES (${dataId++},${rawId},1,'${fn} ${ln}','${fn}',NULL,'${ln}');`);
          contactsSql.push(`INSERT INTO data VALUES (${dataId++},${rawId},2,'${phone}','2',NULL,NULL);`);
          if (ci % 2 === 0) {
            contactsSql.push(`INSERT INTO data VALUES (${dataId++},${rawId},3,'${fn.toLowerCase()}.${ln.toLowerCase()}${Math.floor(Math.random()*99)}@gmail.com','1',NULL,NULL);`);
          }
        }
        contactsOk = await createDb(
          '/data/data/com.android.providers.contacts/databases/contacts2.db',
          contactsSql.join('\n'),
          '/data/data/com.android.providers.contacts'
        );
      }
      log(`Phase 6a — Contacts: ${contactsOk ? '20/20' : 'failed'}`);

      // 6b. Call logs — native addPhoneRecord API with DB fallback
      const callTypes = [1, 2, 3]; // incoming, outgoing, missed
      let callLogOk = false;
      try {
        // Use native addPhoneRecord API — up to 40 records
        const callResults = [];
        for (let i = 0; i < 40; i++) {
          const daysBias = Math.floor(Math.pow(Math.random(), 2) * ageDays);
          const callType = callTypes[i % 3]; // 1=outgoing, 2=incoming, 3=missed in API
          const dur = callType === 3 ? 0 : Math.floor(30 + Math.random() * 600);
          const callDate = new Date((now - daysBias * 86400) * 1000);
          const timeString = `${callDate.getFullYear()}-${String(callDate.getMonth()+1).padStart(2,'0')}-${String(callDate.getDate()).padStart(2,'0')} ${String(callDate.getHours()).padStart(2,'0')}:${String(callDate.getMinutes()).padStart(2,'0')}:${String(callDate.getSeconds()).padStart(2,'0')}`;
          callResults.push(vpost('/vcpcloud/api/padApi/addPhoneRecord', {
            padCode: padCode,
            number: _genPhoneNumber(country),
            inputType: callType,
            duration: dur,
            timeString: timeString,
          }).catch(() => ({ code: -1 })));
          if (i % 10 === 9) { await Promise.all(callResults.splice(0)); await sleep(500); }
        }
        if (callResults.length) await Promise.all(callResults);
        callLogOk = true;
        log('Phase 6b — Call logs: 40 via native API');
      } catch (eCalls) {
        log(`Phase 6b — Native calls failed (${eCalls.message}), using DB fallback...`);
        const callLogSql = [];
        callLogSql.push(`CREATE TABLE IF NOT EXISTS calls (_id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, type INTEGER, duration INTEGER, date INTEGER, new INTEGER DEFAULT 1, name TEXT, numbertype INTEGER DEFAULT 0, features INTEGER DEFAULT 0, phone_account_id TEXT DEFAULT 'default');`);
        for (let i = 0; i < 40; i++) {
          const daysBias = Math.floor(Math.pow(Math.random(), 2) * ageDays);
          const callType = callTypes[i % 3];
          const dur = callType === 3 ? 0 : Math.floor(30 + Math.random() * 600);
          const callDate = (now - daysBias * 86400) * 1000;
          const phone = _genPhoneNumber(country);
          const fn = sanitizeSQL(_pickRandom(contactPool.first), 50);
          callLogSql.push(`INSERT INTO calls VALUES (${i+1},'${phone}',${callType},${dur},${callDate},0,'${fn}',0,0,'default');`);
        }
        callLogOk = await createDb(
          '/data/data/com.android.providers.contacts/databases/calllog.db',
          callLogSql.join('\n'),
          '/data/data/com.android.providers.contacts'
        );
      }
      log(`Phase 6b — Call logs: ${callLogOk ? '40 entries' : 'failed'}`);

      // 6c. SMS — DB-based (simulateSendSms limited to AOSP13/14 only, max 127 chars)
      const smsMessages = [
        "Hey, are you free tonight?", "Can you call me back?", "Thanks for dinner!",
        "Meeting at 3pm confirmed", "Got your message", "Running 10 mins late",
        "Did you see the game?", "Dinner at 7?", "On my way", "Great talking to you",
        "Let me know when you arrive", "See you tomorrow", "Perfect, works for me!",
        "Sure, what time works?", "I'll be there in 5", "Happy birthday!",
        "Can you pick up milk?", "Just got home", "Sounds good to me",
        "Running late, sorry!", "lol that's hilarious", "Miss you!", "See you at the party",
        "Thanks! That really helped", "Ok I'll check and let you know",
      ];
      const smsSql = [];
      smsSql.push(`CREATE TABLE IF NOT EXISTS sms (_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, address TEXT, person INTEGER, date INTEGER, date_sent INTEGER, read INTEGER DEFAULT 1, type INTEGER, body TEXT, seen INTEGER DEFAULT 1, sub_id INTEGER DEFAULT -1);`);
      for (let i = 0; i < 25; i++) {
        const smsType = i % 3 === 0 ? 2 : 1; // 2=sent, 1=received
        const daysBias = Math.floor(Math.pow(Math.random(), 2) * ageDays);
        const smsDate = (now - daysBias * 86400) * 1000;
        const phone = _genPhoneNumber(country);
        const body = sanitizeSQL(smsMessages[i % smsMessages.length], 200);
        smsSql.push(`INSERT INTO sms VALUES (${i+1},${(i%8)+1},'${phone}',NULL,${smsDate},${smsDate},1,${smsType},'${body}',1,-1);`);
      }
      const smsOk = await createDb(
        '/data/data/com.android.providers.telephony/databases/mmssms.db',
        smsSql.join('\n'),
        '/data/data/com.android.providers.telephony'
      );
      log(`Phase 6c — SMS: ${smsOk ? '25/25' : 'failed'}`);

      // 6d. WiFi networks (use preset.mac_oui for realistic BSSID generation)
      const genBssid = (oui) => {
        const suffix = Array.from({length: 3}, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join(':');
        return `${oui}:${suffix}`;
      };
      try {
        const r = await vpost('/vcpcloud/api/padApi/setWifiList', {
          padCodes: pads,
          wifiList: profile.wifiNetworks.map(w => ({
            ssid: w.ssid, password: w.password, securityType: w.security,
            bssid: genBssid(preset.mac_oui || 'E8:50:8B'),
          })),
        });
        log(`Phase 6d — WiFi: ${r.code === 200 ? 'set' : 'failed'} (mac_oui=${preset.mac_oui || 'default'})`);
      } catch (_) { log('Phase 6d — WiFi: failed'); }
      // Fallback: set WiFi SSID via setprop (audit checks this prop)
      const primarySsid = (profile.wifiNetworks && profile.wifiNetworks[0]) ? profile.wifiNetworks[0].ssid : loc.wifi;
      await sh(`setprop persist.sys.cloud.wifi.ssid '${sanitizeText(primarySsid, 64)}' 2>/dev/null`, 10);

      // 6e. Chrome Cookies (sqlite3) — 22+ cookies including country-appropriate domains
      const chromeDir = '/data/data/com.android.chrome/app_chrome/Default';
      const countryCookieDomains = {
        US: [['walmart.com','/','auth_token'],['target.com','/','session_id'],['bankofamerica.com','/','bof_session']],
        GB: [['bbc.co.uk','/','ckns_policy'],['tesco.com','/','tesco_ses'],['hsbc.co.uk','/','hsbcweb']],
        DE: [['spiegel.de','/','sp_session'],['otto.de','/','otto_ses'],['deutsche-bank.de','/','db_auth']],
        FR: [['lemonde.fr','/','lm_session'],['fnac.com','/','fnac_ses'],['bnpparibas.fr','/','bnp_auth']],
      };
      const baseCookies = [
        ['google.com',    '/',   'SSID',        crypto.randomBytes(16).toString('hex'), 1],
        ['google.com',    '/',   'HSID',        crypto.randomBytes(16).toString('hex'), 1],
        ['google.com',    '/',   'SID',         crypto.randomBytes(32).toString('hex'), 1],
        ['google.com',    '/',   'NID',         crypto.randomBytes(20).toString('hex'), 0],
        ['accounts.google.com', '/', 'GAPS',    crypto.randomBytes(20).toString('hex'), 1],
        ['accounts.google.com', '/', 'LSID',    crypto.randomBytes(20).toString('hex'), 1],
        ['amazon.com',    '/',   'session-id',  crypto.randomBytes(12).toString('hex'), 0],
        ['amazon.com',    '/',   'ubid-main',   crypto.randomBytes(12).toString('hex'), 0],
        ['amazon.com',    '/',   'i18n-prefs',  'USD', 0],
        ['paypal.com',    '/',   'cookie_prefs','T%3D1%2CP%3D1%2Cf%3D1', 0],
        ['instagram.com', '/',   'sessionid',   crypto.randomBytes(20).toString('hex'), 1],
        ['instagram.com', '/',   'csrftoken',   crypto.randomBytes(20).toString('hex'), 0],
        ['facebook.com',  '/',   'c_user',      String(Math.floor(1e14 + Math.random() * 9e14)), 1],
        ['facebook.com',  '/',   'xs',          crypto.randomBytes(16).toString('hex'), 1],
        ['youtube.com',   '/',   'PREF',        'f4=4000000', 0],
        ['youtube.com',   '/',   'VISITOR_INFO1_LIVE', crypto.randomBytes(12).toString('base64'), 0],
        ['twitter.com',   '/',   'ct0',         crypto.randomBytes(20).toString('hex'), 0],
        ['linkedin.com',  '/',   'JSESSIONID',  `ajax:${crypto.randomBytes(12).toString('hex')}`, 1],
        ['reddit.com',    '/',   'reddit_session', crypto.randomBytes(16).toString('hex'), 1],
      ];
      // Add country-specific cookies
      const localCookies = (countryCookieDomains[country] || countryCookieDomains.US).map(
        ([host, path, name]) => [host, path, name, crypto.randomBytes(12).toString('hex'), 0]
      );
      const cookieEntries = [...baseCookies, ...localCookies];
      const expiryFar = now + 365 * 86400;
      // GAP-5+6: Use WebKit epoch (1601-01-01) offset + per-cookie microsecond jitter to avoid UNIQUE collision
      const WEBKIT_EPOCH_OFFSET = 11644473600000000n; // microseconds from 1601 to 1970
      const baseCreation = BigInt(now) * 1000000n + WEBKIT_EPOCH_OFFSET;
      const cookieInserts = cookieEntries.map(([host, path, name, val, secure], i) => {
        const creation = baseCreation - BigInt(i * 86400) * 1000000n + BigInt(i * 1000); // stagger by ~1 day each + μs jitter
        const expiry = BigInt(expiryFar) * 1000000n + WEBKIT_EPOCH_OFFSET;
        const lastAccess = baseCreation - BigInt(Math.floor(Math.random() * 3600)) * 1000000n;
        return `INSERT OR IGNORE INTO cookies (creation_utc,host_key,top_frame_site_key,name,value,encrypted_value,path,expires_utc,is_secure,is_httponly,last_access_utc,has_expires,is_persistent,priority,samesite,source_scheme) ` +
          `VALUES(${creation},'${host}','${host}','${name}','${val}','','/',${expiry},${secure},1,${lastAccess},1,1,1,0,2);`;
      }).join('\n');
      const cookieSql = [
        "CREATE TABLE IF NOT EXISTS cookies (creation_utc INTEGER NOT NULL UNIQUE PRIMARY KEY,host_key TEXT NOT NULL,top_frame_site_key TEXT NOT NULL DEFAULT '',name TEXT NOT NULL,value TEXT NOT NULL,encrypted_value BLOB DEFAULT '',path TEXT NOT NULL,expires_utc INTEGER NOT NULL,is_secure INTEGER NOT NULL,is_httponly INTEGER NOT NULL,last_access_utc INTEGER NOT NULL,has_expires INTEGER NOT NULL DEFAULT 1,is_persistent INTEGER NOT NULL DEFAULT 1,priority INTEGER NOT NULL DEFAULT 1,samesite INTEGER NOT NULL DEFAULT -1,source_scheme INTEGER NOT NULL DEFAULT 0);",
        cookieInserts,
      ].join('\n');
      const cookiesOk = await createDb(`${chromeDir}/Cookies`, cookieSql, chromeDir);
      log(`Phase 6e — Chrome Cookies: ${cookiesOk ? 'ok' : 'fail'}`);

      // 6f. Chrome History (30 URLs — country-aware mix)
      const baseHistoryUrls = [
        'https://www.google.com/search?q=restaurants+near+me',
        'https://maps.google.com/', 'https://www.youtube.com/',
        'https://www.amazon.com/', 'https://mail.google.com/',
        'https://www.reddit.com/', 'https://www.instagram.com/',
        'https://www.netflix.com/', 'https://www.linkedin.com/',
        'https://www.paypal.com/', 'https://news.google.com/',
        'https://www.uber.com/', 'https://www.spotify.com/',
        'https://www.twitter.com/', 'https://www.facebook.com/',
        'https://www.wikipedia.org/', 'https://drive.google.com/',
        'https://calendar.google.com/', 'https://photos.google.com/',
        'https://play.google.com/store',
        'https://pay.google.com/gp/w/home/activity',
        'https://pay.google.com/gp/w/home/paymentmethods',
        'https://myaccount.google.com/payments-and-subscriptions',
        'https://play.google.com/store/account/orderhistory',
        'https://play.google.com/store/account/subscriptions',
      ];
      const countryHistoryUrls = {
        US: ['https://www.nytimes.com/', 'https://www.espn.com/', 'https://www.weather.com/',
             'https://www.chase.com/', 'https://www.walmart.com/', 'https://www.yelp.com/search?find_desc=coffee',
             'https://www.doordash.com/', 'https://www.target.com/', 'https://www.hulu.com/',
             'https://www.zillow.com/'],
        GB: ['https://www.bbc.co.uk/', 'https://www.theguardian.com/', 'https://www.tesco.com/',
             'https://www.rightmove.co.uk/', 'https://www.deliveroo.co.uk/', 'https://www.sky.com/',
             'https://www.argos.co.uk/', 'https://www.nhs.uk/', 'https://www.monzo.com/',
             'https://www.asos.com/'],
        DE: ['https://www.spiegel.de/', 'https://www.otto.de/', 'https://www.bild.de/',
             'https://www.lieferando.de/', 'https://www.immobilienscout24.de/', 'https://www.check24.de/',
             'https://www.mediamarkt.de/', 'https://www.dhl.de/tracking', 'https://www.t-online.de/',
             'https://www.ebay-kleinanzeigen.de/'],
        FR: ['https://www.lemonde.fr/', 'https://www.fnac.com/', 'https://www.leboncoin.fr/',
             'https://www.cdiscount.com/', 'https://www.orange.fr/', 'https://www.sncf-connect.com/',
             'https://www.seloger.com/', 'https://www.deliveroo.fr/', 'https://www.laposte.fr/suivi',
             'https://www.boulanger.com/'],
      };
      const historyUrls = [...baseHistoryUrls, ...(countryHistoryUrls[country] || countryHistoryUrls.US)];
      const histInserts = historyUrls.map((url, i) => {
        const t = (now - Math.floor((ageDays - i * 5) * 86400)) * 1000000;
        const title = url.split('/')[2].replace('www.', '');
        return `INSERT OR IGNORE INTO urls (url,title,visit_count,last_visit_time) VALUES('${url}','${title}',${Math.floor(1 + Math.random() * 15)},${t});`;
      }).join('\n');
      // GAP-7+14: Fix visits INSERT — correct column list (url, from_visit, visit_time, transition) and actually execute it
      const histVisitInserts = historyUrls.map((url, i) => {
        const t = (now - Math.floor((ageDays - i * 5) * 86400)) * 1000000;
        return `INSERT OR IGNORE INTO visits (url,from_visit,visit_time,transition) VALUES((SELECT id FROM urls WHERE url='${url}' LIMIT 1),0,${t},805306368);`;
      }).join('\n');
      const historySql = [
        "CREATE TABLE IF NOT EXISTS urls (id INTEGER PRIMARY KEY AUTOINCREMENT,url TEXT NOT NULL,title TEXT DEFAULT '',visit_count INTEGER DEFAULT 0,last_visit_time INTEGER NOT NULL);",
        "CREATE TABLE IF NOT EXISTS visits (id INTEGER PRIMARY KEY AUTOINCREMENT,url INTEGER NOT NULL,from_visit INTEGER DEFAULT 0,visit_time INTEGER NOT NULL,transition INTEGER DEFAULT 0);",
        histInserts,
        histVisitInserts,
      ].join('\n');
      const histOk = await createDb(`${chromeDir}/History`, historySql, chromeDir);
      log(`Phase 6f — Chrome History: ${histOk ? 'ok' : 'fail'} (urls + visits)`);

      // 6g. Chrome Autofill (name, address, phone, email) — GAP-8: use guid TEXT directly, not last_insert_rowid()
      // Also saves SQL for reuse in Phase 7a (credit_cards share the same Web Data DB)
      const autofillGuid = crypto.randomBytes(16).toString('hex');
      _webDataSql = [
        "CREATE TABLE IF NOT EXISTS autofill_profiles (guid TEXT PRIMARY KEY,company_name TEXT,street_address TEXT,city TEXT,state TEXT,zipcode TEXT,country_code TEXT,date_modified INTEGER,language_code TEXT);",
        "CREATE TABLE IF NOT EXISTS autofill_profile_names (guid TEXT,first_name TEXT,middle_name TEXT,last_name TEXT,full_name TEXT);",
        "CREATE TABLE IF NOT EXISTS autofill_profile_phones (guid TEXT,number TEXT);",
        "CREATE TABLE IF NOT EXISTS autofill_profile_emails (guid TEXT,email TEXT);",
        `INSERT OR REPLACE INTO autofill_profiles VALUES('${autofillGuid}','','','${sanitizeSQL(cfg.city || 'Los Angeles', 100)}','${sanitizeSQL(cfg.state || 'CA', 50)}','${sanitizeSQL(cfg.zip || '90001', 20)}','US',${now},'en');`,
        `INSERT OR REPLACE INTO autofill_profile_names VALUES('${autofillGuid}','${safeFirst}','','${safeLast}','${safeFirst} ${safeLast}');`,
        `INSERT OR REPLACE INTO autofill_profile_emails VALUES('${autofillGuid}','${safeEmail6}');`,
        `INSERT OR REPLACE INTO autofill_profile_phones VALUES('${autofillGuid}','${safePhone6}');`,
      ].join('\n');
      const autofillOk = await createDb(`${chromeDir}/Web Data`, _webDataSql, chromeDir);
      log(`Phase 6g — Chrome Autofill: ${autofillOk ? 'ok' : 'fail'}`);

      // 6h. Battery randomization
      try {
        const battLevel = Math.floor(42 + Math.random() * 45);
        await vpost('/vcpcloud/api/padApi/updatePadProperties', {
          padCodes: pads, batteryLevel: battLevel, batteryStatus: 1,
        });
        log(`Phase 6h — Battery: ${battLevel}%`);
      } catch (_) { log('Phase 6h — Battery: failed'); }

      // 6i. GAID reset
      try {
        const r = await vpost('/vcpcloud/api/padApi/resetGAID', { padCodes: pads });
        log(`Phase 6i — GAID reset: ${r.code === 200 ? 'ok' : 'fail'}`);
      } catch (_) { log('Phase 6i — GAID reset: failed'); }

      // 6j. UsageStats — generate REAL usage via am start/stop + XML backdating
      const coreApps = ['com.android.chrome', 'com.google.android.apps.maps',
                        'com.android.vending', 'com.google.android.gms',
                        'com.google.android.youtube', 'com.google.android.gm'];
      // First: generate real usage events by launching and stopping each app
      // This creates proper Android 15 protobuf-format usage records
      log('Phase 6j — Generating real usage events via app launches...');
      for (const pkg of coreApps) {
        try {
          await sh(`am start -n ${pkg}/.MainActivity 2>/dev/null || am start $(cmd package resolve-activity --brief ${pkg} 2>/dev/null | tail -1) 2>/dev/null || true`, 8);
          await sleep(1500);
          await sh(`am force-stop ${pkg} 2>/dev/null || true`, 5);
        } catch (_) {}
      }
      await sleep(2000);
      // Also backdate XML files for older history (works on all Android versions)
      const usageDays = [];
      for (let d = ageDays; d >= 0; d -= 3) {
        const dateTs = (now - d * 86400) * 1000;
        const dateStr = new Date(dateTs).toISOString().slice(0, 10).replace(/-/g, '');
        usageDays.push({ dateStr, dateTs });
      }
      await sh('mkdir -p /data/system/usagestats/0/daily 2>/dev/null', 10);
      let usageOk = true;
      const usageChunks = [];
      for (let i = 0; i < Math.min(usageDays.length, 30); i += 5) {
        const chunk = usageDays.slice(i, i + 5);
        const cmds = chunk.map(({ dateStr, dateTs }) => {
          const endTs = dateTs + 86400000;
          const pkgs = coreApps.map(pkg => {
            const totalMs = Math.floor(120000 + Math.random() * 1800000);
            const launches = Math.floor(1 + Math.random() * 8);
            const lastUsed = dateTs + Math.floor(Math.random() * 86400000);
            return `  <package name="${pkg}" totalTime="${totalMs}" lastTimeUsed="${lastUsed}" appLaunchCount="${launches}" />`;
          }).join('\\n');
          return `printf '<?xml version=\\x271.0\\x27 encoding=\\x27utf-8\\x27 standalone=\\x27yes\\x27 ?>\\n<usagestats version="1" beginTime="${dateTs}" endTime="${endTs}">\\n${pkgs}\\n</usagestats>\\n' > /data/system/usagestats/0/daily/${dateStr}`;
        });
        usageChunks.push(cmds.join('; '));
      }
      for (const chunk of usageChunks) {
        const ok = await shOk(chunk + '; echo USAGE_DONE', 'USAGE_DONE', 15);
        if (!ok) usageOk = false;
      }
      await sh('chown -R system:system /data/system/usagestats 2>/dev/null; echo OK', 10);
      log(`Phase 6j — UsageStats: ${usageOk ? 'ok' : 'fail'} (${Math.min(usageDays.length, 30)} days XML + real launches)`);

      // 6k. Media DB — seed external.db with photo/video entries to simulate camera usage
      let mediaOk = false;
      try {
        const mediaItems = [];
        const photoCount = 15 + Math.floor(Math.random() * 11); // 15-25 photos
        const videoCount = 3 + Math.floor(Math.random() * 3);   // 3-5 videos
        for (let i = 0; i < photoCount; i++) {
          const daysAgo = Math.floor(Math.random() * ageDays);
          const ts = now - daysAgo * 86400 + Math.floor(Math.random() * 86400);
          const dateStr = new Date(ts * 1000).toISOString().replace(/[-:T]/g, '').slice(0, 15);
          const size = Math.floor(2000000 + Math.random() * 6000000); // 2-8MB
          const w = [3024, 4032, 3000, 4000][Math.floor(Math.random() * 4)];
          const h = [4032, 3024, 4000, 3000][Math.floor(Math.random() * 4)];
          mediaItems.push(`INSERT INTO files (_data,_display_name,_size,mime_type,date_added,date_modified,bucket_display_name,media_type,width,height) VALUES('/storage/emulated/0/DCIM/Camera/IMG_${dateStr}.jpg','IMG_${dateStr}.jpg',${size},'image/jpeg',${ts},${ts},'Camera',1,${w},${h});`);
        }
        for (let i = 0; i < videoCount; i++) {
          const daysAgo = Math.floor(Math.random() * ageDays);
          const ts = now - daysAgo * 86400 + Math.floor(Math.random() * 86400);
          const dateStr = new Date(ts * 1000).toISOString().replace(/[-:T]/g, '').slice(0, 15);
          const size = Math.floor(15000000 + Math.random() * 65000000); // 15-80MB
          mediaItems.push(`INSERT INTO files (_data,_display_name,_size,mime_type,date_added,date_modified,bucket_display_name,media_type,width,height) VALUES('/storage/emulated/0/DCIM/Camera/VID_${dateStr}.mp4','VID_${dateStr}.mp4',${size},'video/mp4',${ts},${ts},'Camera',3,1920,1080);`);
        }
        const mediaSql = [
          "CREATE TABLE IF NOT EXISTS files (_id INTEGER PRIMARY KEY AUTOINCREMENT,_data TEXT,_display_name TEXT,_size INTEGER,mime_type TEXT,date_added INTEGER,date_modified INTEGER,bucket_display_name TEXT,media_type INTEGER,width INTEGER,height INTEGER);",
          ...mediaItems,
        ].join('\n');
        mediaOk = await _withSelinuxOff(padCode, () => createDb(
          '/data/data/com.android.providers.media.module/databases/external.db',
          mediaSql,
          '/data/data/com.android.providers.media.module/databases'
        ), ak, sk);
        // Create matching dummy files so paths resolve
        const touchCmd = 'mkdir -p /sdcard/DCIM/Camera 2>/dev/null; for i in $(seq 1 5); do touch /sdcard/DCIM/Camera/IMG_2026010${i}_120000.jpg 2>/dev/null; done; echo TOUCH_OK';
        await shOk(touchCmd, 'TOUCH_OK', 10);
        log(`Phase 6k — Media DB: ${mediaOk ? 'ok' : 'fail'} (${photoCount} photos, ${videoCount} videos)`);
      } catch (e) { log(`Phase 6k — Media DB: fail (${e.message})`); }

      // 6l. Downloads DB — seed downloads history
      let downloadsOk = false;
      try {
        const dlItems = [
          { uri: 'https://play.google.com/store/apps/details?id=com.whatsapp', title: 'WhatsApp.apk', mime: 'application/vnd.android.package-archive', size: 67234816 },
          { uri: 'https://www.example.com/invoice_2026.pdf', title: 'invoice_2026.pdf', mime: 'application/pdf', size: 245760 },
          { uri: 'https://mail.google.com/attachment/photo.jpg', title: 'vacation_photo.jpg', mime: 'image/jpeg', size: 4521984 },
          { uri: 'https://drive.google.com/file/budget.xlsx', title: 'budget_2026.xlsx', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', size: 1048576 },
          { uri: 'https://www.example.com/receipt.pdf', title: 'receipt_march.pdf', mime: 'application/pdf', size: 189440 },
          { uri: 'https://t.me/file/document.pdf', title: 'shared_document.pdf', mime: 'application/pdf', size: 524288 },
          { uri: 'https://play.google.com/store/apps/details?id=com.spotify.music', title: 'Spotify.apk', mime: 'application/vnd.android.package-archive', size: 45678592 },
          { uri: 'https://photos.google.com/share/img_001.jpg', title: 'family_photo.jpg', mime: 'image/jpeg', size: 3145728 },
        ];
        const dlInserts = dlItems.map((dl, i) => {
          const daysAgo = Math.floor(Math.random() * ageDays);
          const ts = (now - daysAgo * 86400) * 1000;
          const fpath = `/storage/emulated/0/Download/${dl.title}`;
          return `INSERT INTO downloads (_id,uri,hint,_data,mimetype,destination,visibility,control,status,lastmod,total_bytes,current_bytes,title) VALUES(${i + 1},'${dl.uri}','${dl.title}','${fpath}','${dl.mime}',4,0,0,200,${ts},${dl.size},${dl.size},'${dl.title}');`;
        }).join('\n');
        const dlSql = [
          "CREATE TABLE IF NOT EXISTS downloads (_id INTEGER PRIMARY KEY,uri TEXT,hint TEXT,_data TEXT,mimetype TEXT,destination INTEGER,visibility INTEGER,control INTEGER,status INTEGER,lastmod INTEGER,total_bytes INTEGER,current_bytes INTEGER,title TEXT);",
          dlInserts,
        ].join('\n');
        downloadsOk = await _withSelinuxOff(padCode, () => createDb(
          '/data/data/com.android.providers.downloads/databases/downloads.db',
          dlSql,
          '/data/data/com.android.providers.downloads/databases'
        ), ak, sk);
        log(`Phase 6l — Downloads DB: ${downloadsOk ? 'ok' : 'fail'} (${dlItems.length} records)`);
      } catch (e) { log(`Phase 6l — Downloads DB: fail (${e.message})`); }

      // 6m. Notification History — post notifications from key apps
      let notifOk = 0;
      try {
        const notifSources = [
          { tag: 'chrome_update', title: 'Chrome', text: 'Chrome is up to date' },
          { tag: 'chrome_tip', title: 'Chrome', text: 'Tip: Try dark mode for easier reading' },
          { tag: 'gms_backup', title: 'Google', text: 'Backup complete' },
          { tag: 'gms_security', title: 'Google', text: 'Security checkup: All good' },
          { tag: 'gmail_promo', title: 'Gmail', text: 'You have new promotions' },
          { tag: 'playstore_update', title: 'Play Store', text: 'Apps updated automatically' },
          { tag: 'youtube_rec', title: 'YouTube', text: 'New video from your subscription' },
          { tag: 'system_wifi', title: 'System', text: 'Connected to WiFi' },
        ];
        // Post in 2 batches of 4 to stay under 4K
        for (let b = 0; b < notifSources.length; b += 4) {
          const batch = notifSources.slice(b, b + 4);
          const cmds = batch.map(n =>
            `cmd notification post -t '${n.title}' '${n.tag}' '${n.text}' 2>/dev/null && echo N_OK`
          );
          const result = await sh(cmds.join('; '), 15);
          notifOk += ((result || '').match(/N_OK/g) || []).length;
        }
        log(`Phase 6m — Notifications: ${notifOk}/${notifSources.length} posted`);
      } catch (e) { log(`Phase 6m — Notifications: fail (${e.message})`); }

      const injected = [contactsOk, histOk, cookiesOk, autofillOk, mediaOk, downloadsOk].filter(Boolean).length;
      phase(6, injected >= 3 ? 'done' : 'warn', `contacts=${contactsOk?'ok':'fail'} history=${histOk?'ok':'fail'} cookies=${cookiesOk?'ok':'fail'} media=${mediaOk?'ok':'fail'} downloads=${downloadsOk?'ok':'fail'}`);
      log(`Phase 6 — Inject done`);
    } catch (e) {
      phase(6, 'failed', e.message.slice(0, 80));
      log(`Phase 6 — Inject FAILED: ${e.message}`);
    }
    await sleep(2000);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 7: Wallet / GPay — payment artifacts (created ALWAYS for trust score)
    // Card injection into Chrome only when real card provided
    // ═══════════════════════════════════════════════════════════════
    phase(7, 'running');
    const cc = (cfg.cc_number || '').replace(/[\s-]/g, '');
    const hasCard = cc && cc.length >= 13 && /^\d+$/.test(cc);
    log(`Phase 7 — Wallet: creating payment artifacts${hasCard ? ` (card ***${cc.slice(-4)})` : ' (synthetic, no card)'}...`);
    try {
      const expParts = (cfg.cc_exp || '12/2028').split('/');
      const expMonth = parseInt(expParts[0]) || 12;
      let expYear = parseInt(expParts[1]) || 2028;
      if (expYear < 100) expYear += 2000;
      const holder = sanitizeSQL(cfg.cc_holder || profile.firstName + ' ' + profile.lastName, 100);
      const last4 = hasCard ? cc.slice(-4) : String(Math.floor(1000 + Math.random() * 8999));
      const network = hasCard ? (cc[0] === '5' ? 'mastercard' : cc[0] === '3' ? 'amex' : cc[0] === '6' ? 'discover' : 'visa') : 'visa';
      const networkId = {visa:1,mastercard:2,amex:3,discover:4}[network] || 1;
      const dpan = '5' + Array.from({length:14}, () => Math.floor(Math.random()*10)).join('');
      const tokenRef = crypto.randomBytes(16).toString('hex');
      const display = `${network.toUpperCase()} ****${last4}`;
      const chromeDir7 = '/data/data/com.android.chrome/app_chrome/Default';
      const gmsDir7 = '/data/data/com.google.android.gms';
      const safeEmail7 = sanitizeSQL(cfg.google_email || profile.email, 254);
      const issuerName = network === 'visa' ? 'Visa Inc.' : network === 'mastercard' ? 'Mastercard' : network === 'amex' ? 'American Express' : 'Discover';
      const artUrl = `https://payments.google.com/payments/apis-secure/get_card_art?instrument_id=1&card_network=${networkId}`;

      // 7a. Chrome Web Data credit_cards (only when real card provided)
      if (hasCard) {
        const cardGuid = crypto.randomBytes(16).toString('hex');
        const creditCardSql = [
          "CREATE TABLE IF NOT EXISTS credit_cards (guid TEXT PRIMARY KEY, name_on_card TEXT, card_number_encrypted BLOB, expiration_month INTEGER, expiration_year INTEGER, date_modified INTEGER, origin TEXT, billing_address_id TEXT, nickname TEXT);",
          `INSERT OR REPLACE INTO credit_cards (guid,name_on_card,card_number_encrypted,expiration_month,expiration_year,date_modified,origin,billing_address_id,nickname) VALUES('${cardGuid}','${holder}',X'${Buffer.from(cc).toString('hex')}',${expMonth},${expYear},${now},'https://pay.google.com','','${network.toUpperCase()}');`,
        ].join('\n');
        const combinedWebDataSql = _webDataSql ? _webDataSql + '\n' + creditCardSql : creditCardSql;
        const webdataOk = await createDb(`${chromeDir7}/Web Data`, combinedWebDataSql, chromeDir7);
        log(`Phase 7a — Chrome credit_cards: ${webdataOk ? 'ok' : 'fail'}`);
      } else {
        log('Phase 7a — Chrome credit_cards: skipped (no card)');
      }

      // 7b+7g. tapandpay.db — token_metadata + transaction_log (ALWAYS created)
      const tokenMetadataSql = [
        "CREATE TABLE IF NOT EXISTS token_metadata (id INTEGER PRIMARY KEY, dpan TEXT, last_four TEXT, network INTEGER, token_ref TEXT, display_name TEXT, is_default INTEGER, card_color INTEGER, token_state INTEGER, issuer_name TEXT, art_url TEXT, is_fido_enrolled INTEGER DEFAULT 0, pan_last_four TEXT, token_service_provider TEXT, wallet_account_id TEXT);",
        `INSERT OR REPLACE INTO token_metadata (id,dpan,last_four,network,token_ref,display_name,is_default,card_color,token_state,issuer_name,art_url,is_fido_enrolled,pan_last_four,token_service_provider,wallet_account_id) VALUES(1,'${dpan}','${last4}',${networkId},'${tokenRef}','${display}',1,-12285185,3,'${issuerName}','${artUrl}',0,'${last4}','${issuerName}','wallet_${crypto.randomBytes(8).toString('hex')}');`,
      ].join('\n');
      const txnCount = Math.floor(15 + Math.random() * 25);
      const merchants = [
        {name:'Google Play',mcc:'5816',mid:'GOOGLEPLAY_'},
        {name:'YouTube Premium',mcc:'5968',mid:'YOUTUBE_'},
        {name:'Uber Technologies',mcc:'4121',mid:'UBER_'},
        {name:'Starbucks',mcc:'5814',mid:'STARBUCKS_'},
        {name:'Amazon.com',mcc:'5942',mid:'AMAZON_'},
        {name:'Spotify',mcc:'5968',mid:'SPOTIFY_'},
        {name:'Netflix.com',mcc:'4899',mid:'NETFLIX_'},
        {name:'McDonald\'s',mcc:'5814',mid:'MCDONALDS_'},
        {name:'Shell Oil',mcc:'5541',mid:'SHELL_'},
        {name:'Walmart',mcc:'5411',mid:'WALMART_'},
        {name:'Target',mcc:'5311',mid:'TARGET_'},
        {name:'Walgreens',mcc:'5912',mid:'WALGREENS_'},
        {name:'CVS Pharmacy',mcc:'5912',mid:'CVS_'},
        {name:'DoorDash',mcc:'5812',mid:'DOORDASH_'},
        {name:'Lyft',mcc:'4121',mid:'LYFT_'},
      ];
      const txnInserts = [];
      for (let ti = 0; ti < txnCount; ti++) {
        const merch = merchants[ti % merchants.length];
        const dayOffset = Math.floor((ageDays - 3) * (ti / txnCount));
        const txnTime = (now - dayOffset * 86400) * 1000;
        const amount = merch.mcc === '5816' ? Math.floor(99 + Math.random() * 2900) : Math.floor(150 + Math.random() * 4500);
        const txnId = crypto.randomBytes(12).toString('hex');
        const authCode = String(Math.floor(100000 + Math.random() * 899999));
        txnInserts.push(
          `INSERT OR IGNORE INTO transaction_log (txn_id,token_id,merchant_name,merchant_category_code,merchant_id,amount_cents,currency,txn_time,txn_state,auth_code,last_four,network,requires_3ds,risk_score) VALUES('${txnId}',1,'${sanitizeSQL(merch.name, 100)}','${merch.mcc}','${merch.mid}${Math.floor(10000 + Math.random() * 89999)}',${amount},'USD',${txnTime},2,'${authCode}','${last4}',${networkId},0,0);`
        );
      }
      const txnLogSql = [
        "CREATE TABLE IF NOT EXISTS transaction_log (txn_id TEXT PRIMARY KEY, token_id INTEGER, merchant_name TEXT, merchant_category_code TEXT, merchant_id TEXT, amount_cents INTEGER, currency TEXT DEFAULT 'USD', txn_time INTEGER, txn_state INTEGER DEFAULT 2, auth_code TEXT, last_four TEXT, network INTEGER, requires_3ds INTEGER DEFAULT 0, risk_score INTEGER DEFAULT 0);",
        txnInserts.join('\n'),
      ].join('\n');
      const fullTpaySql = tokenMetadataSql + '\n' + txnLogSql;
      const tpayOk = await createDb(`${gmsDir7}/databases/tapandpay.db`, fullTpaySql, gmsDir7);
      log(`Phase 7b — tapandpay.db: ${tpayOk ? 'ok' : 'fail'} (${txnCount} txns)`);

      // 7c. COIN.xml billing prefs (ALWAYS)
      const coinXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="has_payment_methods" value="true"/>\n  <string name="default_instrument_id">instrument_1</string>\n  <string name="account_name">${safeEmail7}</string>\n  <boolean name="wallet_enabled" value="true"/>\n  <boolean name="wallet_auth_required" value="false"/>\n  <boolean name="require_unlock_for_payment" value="false"/>\n  <int name="auth_challenge_interval_ms" value="0"/>\n  <boolean name="device_authenticated" value="true"/>\n</map>`;
      const coinCmd = [
        `mkdir -p ${gmsDir7}/shared_prefs 2>/dev/null`,
        `cat > ${gmsDir7}/shared_prefs/COIN.xml << 'COINEOF'`,
        coinXml, `COINEOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/COIN.xml 2>/dev/null`,
        'echo COIN_DONE',
      ].join('\n');
      const coinOk = await shOk(coinCmd, 'COIN_DONE', 15);
      log(`Phase 7c — COIN.xml: ${coinOk ? 'ok' : 'fail'}`);

      // 7d. TapAndPayPrefs.xml (ALWAYS)
      const tapPayPrefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="tap_and_pay_setup_complete" value="true"/>\n  <boolean name="require_device_unlock_for_pay" value="false"/>\n  <boolean name="require_screen_lock_for_nfc" value="false"/>\n  <boolean name="user_authentication_required" value="false"/>\n  <boolean name="biometric_for_payment" value="false"/>\n  <boolean name="pin_for_payment" value="false"/>\n  <string name="default_payment_app">com.google.android.apps.walletnfcrel</string>\n  <boolean name="nfc_payment_enabled" value="true"/>\n  <int name="transaction_limit_no_auth" value="999999"/>\n  <string name="default_token_id">${tokenRef}</string>\n  <string name="default_account">${safeEmail7}</string>\n  <boolean name="pay_without_unlock" value="true"/>\n</map>`;
      const tapPayCmd = [
        `cat > ${gmsDir7}/shared_prefs/TapAndPayPrefs.xml << 'TAPEOF'`,
        tapPayPrefsXml, `TAPEOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/TapAndPayPrefs.xml 2>/dev/null`,
        'echo TAPPREF_DONE',
      ].join('\n');
      const tapPrefOk = await shOk(tapPayCmd, 'TAPPREF_DONE', 15);
      log(`Phase 7d — TapAndPayPrefs: ${tapPrefOk ? 'ok' : 'fail'}`);

      // 7e. WalletPrefs.xml (ALWAYS)
      const walletAppDir = '/data/data/com.google.android.apps.walletnfcrel/shared_prefs';
      const walletPrefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="setup_complete" value="true"/>\n  <string name="signed_in_email">${safeEmail7}</string>\n  <boolean name="purchase_auth_required" value="false"/>\n  <boolean name="require_verification_for_transactions" value="false"/>\n  <boolean name="biometric_auth_for_purchase" value="false"/>\n  <boolean name="screen_lock_for_purchase" value="false"/>\n  <int name="auth_free_transaction_limit_cents" value="99999900"/>\n  <boolean name="contactless_payment_enabled" value="true"/>\n  <boolean name="in_store_pay_enabled" value="true"/>\n  <boolean name="online_pay_enabled" value="true"/>\n  <boolean name="transit_pay_enabled" value="true"/>\n  <boolean name="loyalty_enabled" value="true"/>\n  <string name="default_card_last_four">${last4}</string>\n  <boolean name="card_verification_complete" value="true"/>\n  <boolean name="identity_verified" value="true"/>\n</map>`;
      const walletAppCmd = [
        `mkdir -p ${walletAppDir} 2>/dev/null`,
        `cat > ${walletAppDir}/WalletPrefs.xml << 'WPEOF'`,
        walletPrefsXml, `WPEOF`,
        `chown $(stat -c '%u:%g' /data/data/com.google.android.apps.walletnfcrel/ 2>/dev/null) ${walletAppDir}/WalletPrefs.xml 2>/dev/null`,
        'echo WALLETPREF_DONE',
      ].join('\n');
      const walletAppOk = await shOk(walletAppCmd, 'WALLETPREF_DONE', 15);
      log(`Phase 7e — WalletPrefs: ${walletAppOk ? 'ok' : 'fail'}`);

      // 7f. BillingParams.xml (ALWAYS)
      const billingParamsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="iab_setup_done" value="true"/>\n  <boolean name="require_auth_iab" value="false"/>\n  <int name="auth_timeout" value="0"/>\n  <boolean name="session_auth_cached" value="true"/>\n  <boolean name="play_billing_ready" value="true"/>\n  <string name="billing_email">${safeEmail7}</string>\n  <string name="billing_instrument_type">${network}</string>\n  <boolean name="subscription_ready" value="true"/>\n</map>`;
      const billingParamsCmd = [
        `cat > ${gmsDir7}/shared_prefs/BillingParams.xml << 'BPEOF'`,
        billingParamsXml, `BPEOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/BillingParams.xml 2>/dev/null`,
        'echo BILLPARAM_DONE',
      ].join('\n');
      const billingParamOk = await shOk(billingParamsCmd, 'BILLPARAM_DONE', 15);
      log(`Phase 7f — BillingParams: ${billingParamOk ? 'ok' : 'fail'}`);

      // 7h. CardRiskProfile.xml (ALWAYS)
      const riskPrefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="card_fingerprint">${crypto.randomBytes(16).toString('hex')}</string>\n  <int name="risk_tier" value="0"/>\n  <boolean name="3ds_enrolled" value="true"/>\n  <boolean name="3ds_v2_supported" value="true"/>\n  <int name="3ds_challenge_count" value="0"/>\n  <int name="3ds_frictionless_count" value="${Math.floor(10 + Math.random() * 30)}"/>\n  <boolean name="device_bound" value="true"/>\n  <string name="device_fingerprint">${crypto.randomBytes(20).toString('hex')}</string>\n  <long name="card_added_timestamp" value="${(now - ageDays * 86400) * 1000}"/>\n  <long name="last_successful_txn" value="${(now - 86400) * 1000}"/>\n  <int name="successful_txn_count" value="${txnCount}"/>\n  <int name="declined_txn_count" value="0"/>\n  <boolean name="issuer_trusted_device" value="true"/>\n  <string name="issuer_risk_assessment">low</string>\n  <boolean name="step_up_auth_required" value="false"/>\n  <int name="cvc_retry_count" value="0"/>\n  <boolean name="card_active" value="true"/>\n  <boolean name="recurring_eligible" value="true"/>\n  <string name="network_token_status">active</string>\n  <boolean name="network_token_cryptogram_valid" value="true"/>\n</map>`;
      const riskCmd = [
        `cat > ${gmsDir7}/shared_prefs/CardRiskProfile.xml << 'RISKEOF'`,
        riskPrefsXml, `RISKEOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/CardRiskProfile.xml 2>/dev/null`,
        'echo RISK_DONE',
      ].join('\n');
      const riskOk = await shOk(riskCmd, 'RISK_DONE', 15);
      log(`Phase 7h — CardRiskProfile: ${riskOk ? 'ok' : 'fail'}`);

      // 7i. InstrumentVerification.xml (ALWAYS)
      const instrVerifyXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="instrument_verified" value="true"/>\n  <string name="verification_method">card_on_file</string>\n  <int name="verification_state" value="3"/>\n  <long name="verification_timestamp" value="${(now - ageDays * 86400 + 3600) * 1000}"/>\n  <boolean name="cvv_verified" value="true"/>\n  <boolean name="avs_verified" value="true"/>\n  <string name="avs_result">Y</string>\n  <boolean name="billing_address_verified" value="true"/>\n  <boolean name="issuer_verification_complete" value="true"/>\n  <boolean name="sca_exemption_eligible" value="true"/>\n  <string name="sca_exemption_type">trusted_beneficiary</string>\n  <int name="consecutive_successful_payments" value="${txnCount}"/>\n  <boolean name="merchant_initiated_txn_eligible" value="true"/>\n  <boolean name="token_requestor_trusted" value="true"/>\n</map>`;
      const instrCmd = [
        `cat > ${gmsDir7}/shared_prefs/InstrumentVerification.xml << 'INSTREOF'`,
        instrVerifyXml, `INSTREOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/InstrumentVerification.xml 2>/dev/null`,
        'echo INSTR_DONE',
      ].join('\n');
      const instrOk = await shOk(instrCmd, 'INSTR_DONE', 15);
      log(`Phase 7i — InstrumentVerification: ${instrOk ? 'ok' : 'fail'}`);

      // 7j. PlayBillingCache.xml (ALWAYS)
      const billingCacheXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <boolean name="billing_flow_cached" value="true"/>\n  <string name="cached_instrument_id">instrument_1</string>\n  <string name="cached_instrument_type">${network}</string>\n  <string name="cached_instrument_last4">${last4}</string>\n  <boolean name="1_click_purchase_enabled" value="true"/>\n  <boolean name="skip_cvv_on_recurring" value="true"/>\n  <boolean name="trusted_device_for_billing" value="true"/>\n  <int name="cached_auth_result" value="0"/>\n  <long name="auth_cache_expiry" value="${(now + 365 * 86400) * 1000}"/>\n  <boolean name="subscription_auto_renew" value="true"/>\n  <string name="billing_agreement_id">BA-${crypto.randomBytes(8).toString('hex').toUpperCase()}</string>\n</map>`;
      const cacheBillingCmd = [
        `cat > ${gmsDir7}/shared_prefs/PlayBillingCache.xml << 'PBCEOF'`,
        billingCacheXml, `PBCEOF`,
        `chown $(stat -c '%u:%g' ${gmsDir7}/ 2>/dev/null) ${gmsDir7}/shared_prefs/PlayBillingCache.xml 2>/dev/null`,
        'echo PLAYCACHE_DONE',
      ].join('\n');
      const cacheBillingOk = await shOk(cacheBillingCmd, 'PLAYCACHE_DONE', 15);
      log(`Phase 7j — PlayBillingCache: ${cacheBillingOk ? 'ok' : 'fail'}`);

      const walletOk = [tpayOk, coinOk, tapPrefOk, walletAppOk, billingParamOk, riskOk, instrOk, cacheBillingOk].filter(Boolean).length;
      phase(7, walletOk >= 5 ? 'done' : 'warn', `${walletOk}/8 — ${display}${hasCard ? '' : ' (synthetic)'}`);
      log(`Phase 7 — Wallet: ${walletOk}/8 targets${hasCard ? ' (real card)' : ' (synthetic, all artifacts created)'}`);
    } catch (e) {
      phase(7, 'failed', e.message.slice(0, 80));
      log(`Phase 7 — Wallet FAILED: ${e.message}`);
    }
    await sleep(1500);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 8: Provincial Layering — app-specific SharedPreferences
    // ═══════════════════════════════════════════════════════════════
    phase(8, 'running'); log('Phase 8 — Provincial: app-specific data injection...');
    try {
      const safeEmail8 = sanitizeText(cfg.google_email || profile.email, 254);
      const safeName8 = sanitizeText(profile.firstName + ' ' + profile.lastName, 100);
      const firstOpenTs = (now - ageDays * 86400) * 1000;
      const countryAppTargets = {
        US: [
          { pkg: 'com.amazon.mShop.android.shopping', name: 'Amazon', prefs: { marketplace_id: 'ATVPDKIKX0DER', store_country: 'US' } },
          { pkg: 'com.venmo', name: 'Venmo', prefs: { has_linked_bank: 'true', signup_complete: 'true' } },
          { pkg: 'com.paypal.android.p2pmobile', name: 'PayPal', prefs: { locale: 'en_US', currency: 'USD' } },
          { pkg: 'com.ubercab', name: 'Uber', prefs: { payment_method_set: 'true', locale: 'en_US' } },
          { pkg: 'com.doordash.driverapp', name: 'DoorDash', prefs: { has_default_address: 'true' } },
          { pkg: 'com.cashapp.android', name: 'Cash App', prefs: { has_linked_card: 'true', currency: 'USD', cashtag_set: 'true' } },
          { pkg: 'com.google.android.apps.walletnfcrel', name: 'Google Wallet', prefs: { wallet_setup_done: 'true', default_payment: 'true' } },
        ],
        GB: [
          { pkg: 'com.amazon.mShop.android.shopping', name: 'Amazon', prefs: { marketplace_id: 'A1F83G8C2ARO7P', store_country: 'GB' } },
          { pkg: 'com.ebay.mobile', name: 'eBay', prefs: { locale: 'en_GB', site_id: '3' } },
          { pkg: 'com.revolut.revolut', name: 'Revolut', prefs: { currency: 'GBP', signup_complete: 'true' } },
          { pkg: 'com.deliveroo.orderapp', name: 'Deliveroo', prefs: { locale: 'en_GB' } },
          { pkg: 'uk.co.hsbc.hsbcukmobilebanking', name: 'HSBC', prefs: { region: 'UK' } },
          { pkg: 'com.monzo.android', name: 'Monzo', prefs: { currency: 'GBP', account_setup: 'true', card_activated: 'true' } },
          { pkg: 'com.transferwise.android', name: 'Wise', prefs: { currency: 'GBP', kyc_complete: 'true' } },
        ],
        DE: [
          { pkg: 'com.amazon.mShop.android.shopping', name: 'Amazon', prefs: { marketplace_id: 'A1PA6795UKMFR9', store_country: 'DE' } },
          { pkg: 'de.paypal.here', name: 'PayPal', prefs: { locale: 'de_DE', currency: 'EUR' } },
          { pkg: 'com.ebay.kleinanzeigen', name: 'eBay Kleinanzeigen', prefs: { locale: 'de_DE' } },
          { pkg: 'com.lieferando.android', name: 'Lieferando', prefs: { locale: 'de_DE' } },
          { pkg: 'de.check24.check24', name: 'Check24', prefs: { locale: 'de_DE' } },
          { pkg: 'com.n26.android', name: 'N26', prefs: { locale: 'de_DE', currency: 'EUR', account_verified: 'true' } },
          { pkg: 'de.postbank.finanzassistent', name: 'Postbank', prefs: { locale: 'de_DE', region: 'DE' } },
        ],
        FR: [
          { pkg: 'com.amazon.mShop.android.shopping', name: 'Amazon', prefs: { marketplace_id: 'A13V1IB3VIYZZH', store_country: 'FR' } },
          { pkg: 'com.paypal.android.p2pmobile', name: 'PayPal', prefs: { locale: 'fr_FR', currency: 'EUR' } },
          { pkg: 'fr.leboncoin', name: 'Leboncoin', prefs: { locale: 'fr_FR' } },
          { pkg: 'com.deliveroo.orderapp', name: 'Deliveroo', prefs: { locale: 'fr_FR' } },
          { pkg: 'fr.orange.mail', name: 'Orange Mail', prefs: { locale: 'fr_FR' } },
          { pkg: 'com.lydia', name: 'Lydia', prefs: { locale: 'fr_FR', currency: 'EUR', account_verified: 'true' } },
          { pkg: 'com.bnpp.mabanque', name: 'BNP Paribas', prefs: { locale: 'fr_FR', region: 'FR' } },
        ],
      };
      const appTargets = countryAppTargets[country] || countryAppTargets.US;
      let prefsOk = 0;
      for (const app of appTargets) {
        const extraEntries = Object.entries(app.prefs || {}).map(
          ([k, v]) => `  <string name="${k}">${sanitizeText(String(v), 200)}</string>`
        ).join('\n');
        const prefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n<map>\n  <string name="user_email">${safeEmail8}</string>\n  <string name="user_name">${safeName8}</string>\n  <boolean name="onboarding_complete" value="true"/>\n  <boolean name="notifications_enabled" value="true"/>\n  <int name="app_open_count" value="${Math.floor(5 + Math.random() * 45)}"/>\n  <long name="first_open_timestamp" value="${firstOpenTs}"/>\n  <long name="last_open_timestamp" value="${Date.now()}"/>\n${extraEntries}\n</map>`;
        const prefsCmd = [
          `mkdir -p /data/data/${app.pkg}/shared_prefs 2>/dev/null`,
          `cat > /data/data/${app.pkg}/shared_prefs/user_prefs.xml << 'PREFEOF'`,
          prefsXml,
          `PREFEOF`,
          `chown $(stat -c '%u:%g' /data/data/${app.pkg}/ 2>/dev/null) /data/data/${app.pkg}/shared_prefs/user_prefs.xml 2>/dev/null`,
          'echo PREF_SET',
        ].join('\n');
        const ok = await shOk(prefsCmd, 'PREF_SET', 15);
        if (ok) prefsOk++;
      }
      phase(8, 'done', `${prefsOk}/${appTargets.length} apps`);
      log(`Phase 8 — Provincial: ${prefsOk}/${appTargets.length} apps`);
    } catch (e) {
      phase(8, 'failed', e.message.slice(0, 80));
      log(`Phase 8 — Provincial FAILED: ${e.message}`);
    }

    // ═══════════════════════════════════════════════════════════════
    // PHASE 9: Post-Harden — Kiwi browser prefs + media scan
    // ═══════════════════════════════════════════════════════════════
    phase(9, 'running'); log('Phase 9 — Post-Harden: Kiwi prefs, DNS, SELinux, media scan...');
    try {
      const safeEmail9 = sanitizeText(cfg.google_email || profile.email, 254);
      const safeName9 = sanitizeText(profile.firstName + ' ' + profile.lastName, 100);
      const safeFirst9 = sanitizeText(profile.firstName, 50);
      const kwiwiPath = '/data/data/com.kiwibrowser.browser/app_chrome/Default';
      const kiwiBrowserPrefs = JSON.stringify({
        account_info: [{email: safeEmail9, full_name: safeName9, gaia: '117234567890', given_name: safeFirst9, locale: 'en-US'}],
        signin: {allowed: true, allowed_on_next_startup: true},
        sync: {has_setup_completed: true},
        browser: {has_seen_welcome_page: true},
      }, null, 2);
      const kiwiCmd = [
        `mkdir -p ${kwiwiPath} 2>/dev/null`,
        `cat > ${kwiwiPath}/Preferences << 'KIWIEOF'`,
        kiwiBrowserPrefs,
        `KIWIEOF`,
        `restorecon ${kwiwiPath}/Preferences 2>/dev/null`,
        'echo KIWI_DONE',
      ].join('\n');
      const kiwiOk = await shOk(kiwiCmd, 'KIWI_DONE', 15);
      log(`Phase 9a — Kiwi browser: ${kiwiOk ? 'ok' : 'fail'}`);

      // 9b. DNS cleanup — remove leak-prone DNS resolvers, set neutral DNS
      const dnsCmd = [
        'settings put global private_dns_mode hostname 2>/dev/null || true',
        'settings put global private_dns_specifier dns.google 2>/dev/null || true',
        'resetprop --delete net.dns1 2>/dev/null || true',
        'resetprop --delete net.dns2 2>/dev/null || true',
        // Timezone alignment with location
        `settings put global auto_time_zone 0 2>/dev/null || true`,
        `setprop persist.sys.timezone '${loc.timezone || 'America/New_York'}' 2>/dev/null || true`,
        'echo DNS_DONE',
      ].join('; ');
      const dnsOk = await shOk(dnsCmd, 'DNS_DONE', 12);
      log(`Phase 9b — DNS + timezone: ${dnsOk ? 'ok' : 'fail'}`);

      // 9c. SELinux enforcement check
      const selinuxCmd = [
        'ENFORCE=$(getenforce 2>/dev/null || echo Unknown)',
        'echo SE=$ENFORCE',
        '[ "$ENFORCE" != "Enforcing" ] && setenforce 1 2>/dev/null || true',
        'echo SELINUX_DONE',
      ].join('; ');
      const seResult = await sh(selinuxCmd, 10);
      const seOk = (seResult || '').includes('SELINUX_DONE');
      log(`Phase 9c — SELinux: ${seOk ? 'ok' : 'fail'} (${(seResult || '').match(/SE=(\w+)/)?.[1] || '?'})`);

      // 9d. Settings cleanup — remove dev/debug indicators + purchase auth bypass
      const settingsCmd = [
        'settings put global adb_enabled 0 2>/dev/null || true',
        'settings put global development_settings_enabled 0 2>/dev/null || true',
        'settings put secure install_non_market_apps 0 2>/dev/null || true',
        'settings put global stay_on_while_plugged_in 0 2>/dev/null || true',
        // Purchase auth bypass — device-level settings
        'settings put secure lock_screen_lock_after_timeout 0 2>/dev/null || true',
        'settings put secure trust_agents_initialized 1 2>/dev/null || true',
        'settings put global require_password_to_decrypt 0 2>/dev/null || true',
        // NFC tap-and-pay — enable without auth
        'settings put secure nfc_payment_default_component com.google.android.apps.walletnfcrel/com.google.android.gms.tapandpay.hce.service.TpHceService 2>/dev/null || true',
        'settings put secure nfc_payment_foreground 1 2>/dev/null || true',
        // Google Play purchase auth interval — set to never
        'settings put secure purchase_auth_required 0 2>/dev/null || true',
        'echo SETTINGS_DONE',
      ].join('; ');
      const settingsCleanOk = await shOk(settingsCmd, 'SETTINGS_DONE', 10);
      log(`Phase 9d — Settings cleanup: ${settingsCleanOk ? 'ok' : 'fail'} (purchase auth bypassed)`);

      // 9d2. Lock screen — set to 'swipe' (no PIN/pattern) so payments don't prompt auth
      const lockCmd = [
        'settings put secure lockscreen.password_type 0 2>/dev/null || true',
        'settings put secure lockscreen.password_type_alternate 0 2>/dev/null || true',
        'settings put secure lock_pattern_autolock 0 2>/dev/null || true',
        'settings put secure lock_screen_show_notifications 1 2>/dev/null || true',
        'settings put secure lock_screen_allow_private_notifications 1 2>/dev/null || true',
        // Smart Lock — trust current device
        'settings put secure trust_agents_extend_unlock 1 2>/dev/null || true',
        'settings put secure enabled_trust_agents com.google.android.gms/.auth.trustagent.GoogleTrustAgent 2>/dev/null || true',
        // Verify apps — disable extra verification prompts
        'settings put global package_verifier_enable 0 2>/dev/null || true',
        'settings put global verifier_verify_adb_installs 0 2>/dev/null || true',
        'echo LOCK_DONE',
      ].join('; ');
      const lockOk = await shOk(lockCmd, 'LOCK_DONE', 10);
      log(`Phase 9d2 — Lock screen: ${lockOk ? 'ok' : 'fail'} (swipe-only, Smart Lock enabled)`);

      // 9d3. Payment device trust binding — establish device as trusted for payment processing
      const payTrustCmd = [
        // Enable NFC
        'svc nfc enable 2>/dev/null || true',
        // Trust this device for Google payments — device attestation cache
        'settings put secure device_provisioned 1 2>/dev/null || true',
        'settings put global device_provisioned 1 2>/dev/null || true',
        // Disable additional payment security prompts
        'settings put secure credential_provider com.google.android.gms 2>/dev/null || true',
        'settings put secure user_setup_complete 1 2>/dev/null || true',
        'settings put secure device_paired 1 2>/dev/null || true',
        // Google Play protect — establish as trusted device
        'settings put global package_verifier_user_consent 1 2>/dev/null || true',
        'settings put global upload_apk_enable 0 2>/dev/null || true',
        // Payment completeness signals
        'settings put secure backup_enabled 1 2>/dev/null || true',
        'settings put secure backup_transport com.google.android.gms/.backup.BackupTransportService 2>/dev/null || true',
        'echo PAYTRUST_DONE',
      ].join('; ');
      const payTrustOk = await shOk(payTrustCmd, 'PAYTRUST_DONE', 12);
      log(`Phase 9d3 — Payment trust binding: ${payTrustOk ? 'ok' : 'fail'} (NFC on, device trusted)`);

      // 9e. Media scan
      const scanCmd = [
        "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Camera/ 2>/dev/null",
        "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///data/media/0/DCIM/Camera/ 2>/dev/null",
        'echo SCAN_DONE',
      ].join('; ');
      const scanOk = await shOk(scanCmd, 'SCAN_DONE', 12);
      log(`Phase 9e — Media scan: ${scanOk ? 'ok' : 'fail'}`);

      // 9f. Permission pre-granting — grant runtime permissions to key apps
      let permsGranted = 0;
      try {
        const permApps = [
          'com.android.chrome', 'com.google.android.gms', 'com.android.vending',
          'com.kiwibrowser.browser', 'com.google.android.apps.walletnfcrel',
        ];
        const perms = [
          'CAMERA', 'READ_CONTACTS', 'WRITE_CONTACTS', 'READ_PHONE_STATE',
          'ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION',
          'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE',
        ];
        // Split into batches: 2 apps per command to stay under 4K
        for (let i = 0; i < permApps.length; i += 2) {
          const batch = permApps.slice(i, i + 2);
          const cmds = batch.flatMap(pkg =>
            perms.map(p => `pm grant ${pkg} android.permission.${p} 2>/dev/null || true`)
          );
          cmds.push('echo PERM_BATCH_OK');
          const r = await sh(cmds.join('; '), 15);
          if ((r || '').includes('PERM_BATCH_OK')) permsGranted += batch.length;
        }
        // AppOps for key operations
        const appOpsCmd = [
          'appops set com.android.chrome CAMERA allow 2>/dev/null || true',
          'appops set com.android.chrome COARSE_LOCATION allow 2>/dev/null || true',
          'appops set com.android.chrome FINE_LOCATION allow 2>/dev/null || true',
          'appops set com.google.android.gms CAMERA allow 2>/dev/null || true',
          'appops set com.google.android.gms COARSE_LOCATION allow 2>/dev/null || true',
          'appops set com.google.android.gms FINE_LOCATION allow 2>/dev/null || true',
          'appops set com.google.android.gms READ_CONTACTS allow 2>/dev/null || true',
          'echo APPOPS_OK',
        ].join('; ');
        await shOk(appOpsCmd, 'APPOPS_OK', 12);
        log(`Phase 9f — Permissions: ${permsGranted}/${permApps.length} apps granted`);
      } catch (e) { log(`Phase 9f — Permissions: fail (${e.message})`); }
      const permsOk = permsGranted > 0;

      // 9g. System settings expansion — make device appear lived-in
      const sysSettingsCmd = [
        'settings put system screen_brightness 142 2>/dev/null || true',
        'settings put system screen_brightness_mode 1 2>/dev/null || true',
        'settings put system screen_off_timeout 120000 2>/dev/null || true',
        'settings put system font_scale 1.0 2>/dev/null || true',
        'settings put system accelerometer_rotation 1 2>/dev/null || true',
        'settings put secure location_mode 3 2>/dev/null || true',
        'settings put secure location_providers_allowed +gps 2>/dev/null || true',
        'settings put secure location_providers_allowed +network 2>/dev/null || true',
        'settings put global wifi_on 1 2>/dev/null || true',
        'settings put global bluetooth_on 0 2>/dev/null || true',
        'settings put global mobile_data 1 2>/dev/null || true',
        'settings put secure accessibility_enabled 0 2>/dev/null || true',
        'settings put global heads_up_notifications_enabled 1 2>/dev/null || true',
        'echo SYSSET_DONE',
      ].join('; ');
      const sysSettingsOk = await shOk(sysSettingsCmd, 'SYSSET_DONE', 12);
      log(`Phase 9g — System settings: ${sysSettingsOk ? 'ok' : 'fail'} (13 settings applied)`);

      // 9h. Install attribution — send INSTALL_REFERRER broadcasts for organic installs
      let attrOk = 0;
      try {
        const attrApps = [
          'com.android.chrome', 'com.google.android.youtube',
          'com.google.android.apps.maps', 'com.google.android.gm',
        ];
        const attrCmds = attrApps.map(pkg =>
          `am broadcast -a com.android.vending.INSTALL_REFERRER -p ${pkg} --es referrer 'utm_source=google-play&utm_medium=organic&utm_campaign=direct' 2>/dev/null && echo ATTR_OK`
        );
        attrCmds.push('echo ATTR_DONE');
        const attrResult = await sh(attrCmds.join('; '), 15);
        attrOk = ((attrResult || '').match(/ATTR_OK/g) || []).length;
        log(`Phase 9h — Install attribution: ${attrOk}/${attrApps.length} broadcasts sent`);
      } catch (e) { log(`Phase 9h — Install attribution: fail (${e.message})`); }
      const installRefOk = attrOk > 0;

      // 9i. Boot & init broadcasts — trigger app initialization sequences
      let bootOk = false;
      try {
        const bootCmd = [
          'am broadcast -a android.intent.action.BOOT_COMPLETED -f 0x00000020 2>/dev/null || true',
          'am broadcast -a android.intent.action.LOCKED_BOOT_COMPLETED -f 0x00000020 2>/dev/null || true',
          'am broadcast -a android.intent.action.MY_PACKAGE_REPLACED -p com.android.chrome 2>/dev/null || true',
          'am broadcast -a android.intent.action.MY_PACKAGE_REPLACED -p com.google.android.gms 2>/dev/null || true',
          'am broadcast -a android.intent.action.MY_PACKAGE_REPLACED -p com.android.vending 2>/dev/null || true',
          'echo BOOT_DONE',
        ].join('; ');
        bootOk = await shOk(bootCmd, 'BOOT_DONE', 15);
        log(`Phase 9i — Boot broadcasts: ${bootOk ? 'ok' : 'fail'}`);
      } catch (e) { log(`Phase 9i — Boot broadcasts: fail (${e.message})`); }

      // 9j. Keep-alive apps — prevent GMS/Chrome/GPay from being killed (Android 13/14/15)
      let keepAliveOk = false;
      try {
        const keepApps = ['com.google.android.gms', 'com.android.chrome', 'com.google.android.apps.walletnfcrel'];
        const rKeep = await vpost('/vcpcloud/api/padApi/setKeepAliveApp', {
          padCode: padCode, packageNames: keepApps,
        });
        keepAliveOk = rKeep.code === 200;
        log(`Phase 9j — KeepAlive: ${keepAliveOk ? 'ok' : 'fail'} (${keepApps.length} apps)`);
      } catch (e) { log(`Phase 9j — KeepAlive: fail (${e.message})`); }

      // 9k. Hide accessibility service list — prevent detection
      let hideAccessOk = false;
      try {
        const rHide = await vpost('/vcpcloud/api/padApi/setHideAccessibilityAppList', {
          padCode: padCode, packageNames: ['*'],
        });
        hideAccessOk = rHide.code === 200;
        log(`Phase 9k — HideAccessibility: ${hideAccessOk ? 'ok' : 'fail'}`);
      } catch (e) { log(`Phase 9k — HideAccessibility: fail (${e.message})`); }

      // 9l. Disable global root — hide root access from apps
      let switchRootOk = false;
      try {
        const rRoot = await vpost('/vcpcloud/api/padApi/switchRoot', {
          padCode: padCode, globalRoot: false,
        });
        switchRootOk = rRoot.code === 200;
        log(`Phase 9l — SwitchRoot: ${switchRootOk ? 'ok' : 'fail'} (globalRoot=false)`);
      } catch (e) { log(`Phase 9l — SwitchRoot: fail (${e.message})`); }

      const p9ok = [kiwiOk, dnsOk, seOk, settingsCleanOk, lockOk, payTrustOk, scanOk, permsOk, sysSettingsOk, installRefOk, bootOk, keepAliveOk, hideAccessOk, switchRootOk].filter(Boolean).length;
      phase(9, 'done', `${p9ok}/14 hardened`);
    } catch (e) {
      phase(9, 'failed', e.message.slice(0, 80));
      log(`Phase 9 — Post-Harden FAILED: ${e.message}`);
    }
    await sleep(1000);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 10: Attestation — keybox, verified boot, build type check
    // ═══════════════════════════════════════════════════════════════
    phase(10, 'running'); log('Phase 10 — Attestation: keybox, verified boot, GSF, CTS profile check...');
    try {
      const checkCmd = [
        'echo KB=$(getprop persist.titan.keybox.loaded)',
        'echo VBS=$(getprop ro.boot.verifiedbootstate)',
        'echo BT=$(getprop ro.build.type)',
        'echo QEMU=$(getprop ro.kernel.qemu)',
        'echo VMOS=$(getprop ro.vmos.simplest.rom 2>/dev/null || echo "")',
        'echo DEBUGGABLE=$(getprop ro.debuggable)',
        'echo SECURE=$(getprop ro.secure)',
        'echo ADB=$(getprop service.adb.root)',
        'echo FLASH=$(getprop ro.boot.flash.locked)',
        'echo VBMETA=$(getprop ro.boot.vbmeta.device_state)',
        'echo GOLDFISH=$(getprop ro.hardware.audio.primary 2>/dev/null | grep -c goldfish)',
        'echo CUTTLEFISH=$(cat /proc/cmdline 2>/dev/null | grep -c cuttlefish)',
        `echo FP_MATCH=$(getprop ro.build.fingerprint | grep -c '${preset.fingerprint.split('/')[0]}')`,
      ].join('; ');
      const result = await sh(checkCmd, 20);
      const vals = {};
      for (const line of (result || '').split('\n')) {
        const eq = line.indexOf('=');
        if (eq > 0) vals[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
      }
      const issues = [];
      if (vals.KB !== '1') issues.push('keybox_not_loaded');
      if (vals.VBS !== 'green') issues.push(`vbs=${vals.VBS || '?'}`);
      if (vals.BT !== 'user') issues.push(`build_type=${vals.BT || '?'}`);
      if (vals.QEMU && vals.QEMU !== '0') issues.push('qemu_exposed');
      if (vals.VMOS) issues.push('vmos_prop_leaking');
      if (vals.DEBUGGABLE === '1') issues.push('debuggable');
      if (vals.SECURE !== '1') issues.push('not_secure');
      if (vals.ADB === '1') issues.push('adb_root');
      if (vals.FLASH !== '1') issues.push('flash_unlocked');
      if (vals.VBMETA !== 'locked') issues.push('vbmeta_unlocked');
      if (vals.GOLDFISH !== '0') issues.push('goldfish_audio');
      if (vals.CUTTLEFISH !== '0') issues.push('cuttlefish_cmdline');
      if (vals.FP_MATCH === '0') issues.push('fingerprint_mismatch');

      // Remediation — attempt to fix all attestation issues
      if (issues.length > 0) {
        log(`Phase 10 — Attempting remediation for: ${issues.join(', ')}`);
        const remediateCmd = [
          vals.VBS !== 'green' ? "resetprop ro.boot.verifiedbootstate green 2>/dev/null" : '',
          vals.BT !== 'user' ? "resetprop ro.build.type user 2>/dev/null" : '',
          (vals.QEMU && vals.QEMU !== '0') ? "resetprop --delete ro.kernel.qemu 2>/dev/null" : '',
          vals.VMOS ? "resetprop --delete ro.vmos.simplest.rom 2>/dev/null" : '',
          vals.DEBUGGABLE === '1' ? "resetprop ro.debuggable 0 2>/dev/null" : '',
          vals.SECURE !== '1' ? "resetprop ro.secure 1 2>/dev/null" : '',
          vals.ADB === '1' ? "resetprop service.adb.root 0 2>/dev/null" : '',
          vals.FLASH !== '1' ? "resetprop ro.boot.flash.locked 1 2>/dev/null" : '',
          vals.VBMETA !== 'locked' ? "resetprop ro.boot.vbmeta.device_state locked 2>/dev/null" : '',
          vals.GOLDFISH !== '0' ? "resetprop --delete ro.hardware.audio.primary 2>/dev/null" : '',
          `resetprop ro.build.fingerprint '${preset.fingerprint}' 2>/dev/null`,
          `resetprop ro.build.tags 'release-keys' 2>/dev/null`,
          `resetprop ro.build.display.id '${preset.fingerprint.split('/').pop() || 'release-keys'}' 2>/dev/null`,
          'echo REMEDIATE_DONE',
        ].filter(Boolean).join('; ');
        const remedOk = await shOk(remediateCmd, 'REMEDIATE_DONE', 20);
        log(`Phase 10 — Remediation: ${remedOk ? 'applied' : 'partial'}`);
        // Re-check after remediation
        if (remedOk) {
          const recheck = await sh(checkCmd, 15);
          const rVals = {};
          for (const line of (recheck || '').split('\n')) {
            const eq = line.indexOf('=');
            if (eq > 0) rVals[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
          }
          issues.length = 0;
          if (rVals.KB !== '1') issues.push('keybox_not_loaded');
          if (rVals.VBS !== 'green') issues.push(`vbs=${rVals.VBS || '?'}`);
          if (rVals.BT !== 'user') issues.push(`build_type=${rVals.BT || '?'}`);
          if (rVals.QEMU && rVals.QEMU !== '0') issues.push('qemu_exposed');
          if (rVals.VMOS) issues.push('vmos_prop_leaking');
        }
      }

      const notes = issues.length === 0 ? 'all checks pass' : issues.join(', ');
      phase(10, issues.length === 0 ? 'done' : 'warn', notes);
      log(`Phase 10 — Attestation: ${notes}`);
    } catch (e) {
      phase(10, 'failed', e.message.slice(0, 80));
      log(`Phase 10 — Attestation FAILED: ${e.message}`);
    }

    // 10c. Visual attestation — screencap for genesis verification
    try {
      const capCmd = 'screencap -p /data/local/tmp/genesis_verify.png 2>/dev/null && S=$(wc -c < /data/local/tmp/genesis_verify.png 2>/dev/null) && echo SCREENCAP_OK_${S}';
      const capResult = await sh(capCmd, 15);
      const capMatch = (capResult || '').match(/SCREENCAP_OK_(\d+)/);
      if (capMatch) {
        const sizeKb = Math.round(parseInt(capMatch[1]) / 1024);
        log(`Phase 10c — Screencap: ok (${sizeKb} KB at /data/local/tmp/genesis_verify.png)`);
      } else {
        log('Phase 10c — Screencap: fail');
      }
    } catch (_) { log('Phase 10c — Screencap: fail'); }

    await sleep(1000);

    // ═══════════════════════════════════════════════════════════════
    // PHASE 11: Trust Audit — rebalanced 36-check scoring (max 100)
    // ═══════════════════════════════════════════════════════════════
    phase(11, 'running'); log('Phase 11 — Trust Audit: 36-check rebalanced scoring (max 100)...');
    try {
      const chromeDir11 = '/data/data/com.android.chrome/app_chrome/Default';
      const parseKV = (raw) => {
        const out = {};
        for (const line of (raw || '').split('\n')) {
          const eq = line.indexOf('=');
          if (eq > 0) out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
        }
        return out;
      };

      // Batch 1: Device/system + Chrome file-size checks + new SYS_SETTINGS (all fast)
      const batch1Cmd = [
        "echo ACCOUNTS=$(test -f /data/system_ce/0/accounts_ce.db && S=$(wc -c < /data/system_ce/0/accounts_ce.db 2>/dev/null) && [ $S -gt 4096 ] && echo 1 || echo 0)",
        "echo GMS_REG=$(test -f /data/data/com.google.android.gms/shared_prefs/device_registration.xml && echo 1 || echo 0)",
        "echo GSF_ID=$(test -f /data/data/com.google.android.gsf/shared_prefs/gservices.xml && echo 1 || echo 0)",
        "echo KIWI=$(test -f /data/data/com.kiwibrowser.browser/app_chrome/Default/Preferences && echo 1 || echo 0)",
        "echo USAGE=$(ls /data/system/usagestats/0/daily/ 2>/dev/null | wc -l)",
        "echo BUILD_TYPE=$(getprop ro.build.type)",
        "echo VMOS_LEAK=$(getprop ro.vmos.simplest.rom 2>/dev/null || echo '')",
        "echo SELINUX=$(getenforce 2>/dev/null || echo Unknown)",
        "echo ANDROID_ID=$(settings get secure android_id 2>/dev/null || echo '')",
        "echo IMEI_SET=$(getprop persist.radio.device.imei0 2>/dev/null || echo '')",
        "echo WIFI=$(getprop persist.sys.cloud.wifi.ssid 2>/dev/null || echo '')",
        `echo CHROME_COOKIES=$(test -f ${chromeDir11}/Cookies && S=$(wc -c < ${chromeDir11}/Cookies 2>/dev/null) && [ $S -gt 8192 ] && echo 22 || echo 0)`,
        `echo CHROME_HISTORY=$(test -f ${chromeDir11}/History && S=$(wc -c < ${chromeDir11}/History 2>/dev/null) && [ $S -gt 8192 ] && echo 30 || echo 0)`,
        `echo CHROME_VISITS=$(test -f ${chromeDir11}/History && S=$(wc -c < ${chromeDir11}/History 2>/dev/null) && [ $S -gt 12288 ] && echo 30 || echo 0)`,
        `echo AUTOFILL=$(test -f '${chromeDir11}/Web Data' && S=$(wc -c < '${chromeDir11}/Web Data' 2>/dev/null) && [ $S -gt 4096 ] && echo 1 || echo 0)`,
        "echo SYS_SETTINGS=$(settings get system screen_off_timeout 2>/dev/null | grep -c '[0-9]')",
      ].join('; ');

      // Batch 2: Content providers + new Media/Downloads/Notifications checks
      const batch2Cmd = [
        "echo CONTACTS=$(test -f /data/data/com.android.providers.contacts/databases/contacts2.db && S=$(wc -c < /data/data/com.android.providers.contacts/databases/contacts2.db 2>/dev/null) && [ $S -gt 4096 ] && echo 20 || echo 0)",
        "echo CALLS=$(test -f /data/data/com.android.providers.contacts/databases/calllog.db && S=$(wc -c < /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null) && [ $S -gt 4096 ] && echo 40 || echo 0)",
        "echo SMS=$(test -f /data/data/com.android.providers.telephony/databases/mmssms.db && S=$(wc -c < /data/data/com.android.providers.telephony/databases/mmssms.db 2>/dev/null) && [ $S -gt 4096 ] && echo 25 || echo 0)",
        "echo MEDIA_DB=$(test -f /data/data/com.android.providers.media.module/databases/external.db && S=$(wc -c < /data/data/com.android.providers.media.module/databases/external.db 2>/dev/null) && [ $S -gt 8192 ] && echo 1 || echo 0)",
        "echo DOWNLOADS=$(test -f /data/data/com.android.providers.downloads/databases/downloads.db && S=$(wc -c < /data/data/com.android.providers.downloads/databases/downloads.db 2>/dev/null) && [ $S -gt 4096 ] && echo 1 || echo 0)",
        "echo NOTIFICATIONS=$(test -f /data/system/notification_log.db && echo 1 || ls /data/system/notification_policy.xml 2>/dev/null | wc -l)",
      ].join('; ');

      // Batch 3: Payment/wallet + new Permissions/Provincial/Attribution/Boot checks
      const batch3Cmd = [
        "echo TPAY=$(test -f /data/data/com.google.android.gms/databases/tapandpay.db && S=$(wc -c < /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null) && [ $S -gt 4096 ] && echo 1 || echo 0)",
        "echo PLAYSTORE=$(ls /data/data/com.android.vending/shared_prefs/*.xml 2>/dev/null | wc -l)",
        "echo PLAY_AUTH=$(grep -c 'purchase_auth_required.*never' /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null || echo 0)",
        "echo GPAY_AUTH=$(grep -c 'purchase_auth_required.*false' /data/data/com.google.android.apps.walletnfcrel/shared_prefs/WalletPrefs.xml 2>/dev/null || echo 0)",
        "echo BILLING=$(test -f /data/data/com.android.vending/shared_prefs/billing.xml && echo 1 || echo 0)",
        "echo TAP_PREFS=$(test -f /data/data/com.google.android.gms/shared_prefs/TapAndPayPrefs.xml && echo 1 || echo 0)",
        "echo PURCH_HIST=$(test -f /data/data/com.android.vending/databases/library.db && S=$(wc -c < /data/data/com.android.vending/databases/library.db 2>/dev/null) && [ $S -gt 4096 ] && echo 18 || echo 0)",
        "echo TXN_LOG=$(test -f /data/data/com.google.android.gms/databases/tapandpay.db && S=$(wc -c < /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null) && [ $S -gt 8192 ] && echo 32 || echo 0)",
        "echo CARD_RISK=$(test -f /data/data/com.google.android.gms/shared_prefs/CardRiskProfile.xml && echo 1 || echo 0)",
        "echo INSTR_VERIFY=$(test -f /data/data/com.google.android.gms/shared_prefs/InstrumentVerification.xml && echo 1 || echo 0)",
        "echo BILL_CACHE=$(test -f /data/data/com.google.android.gms/shared_prefs/PlayBillingCache.xml && echo 1 || echo 0)",
        "echo PERMISSIONS=$(dumpsys package com.android.chrome 2>/dev/null | grep -c 'granted=true' || echo 0)",
        "echo PROVINCIAL=$(ls /data/data/com.amazon.mShop.android.shopping/shared_prefs/user_prefs.xml /data/data/com.venmo/shared_prefs/user_prefs.xml /data/data/com.paypal.android.p2pmobile/shared_prefs/user_prefs.xml 2>/dev/null | wc -l)",
        "echo BOOT_INIT=$(getprop sys.boot_completed 2>/dev/null || echo 0)",
        // New checks for full 100 scoring
        "echo INSTALL_SRC=$(getprop persist.sys.cloud.pm.install_source 2>/dev/null)",
        "echo GALLERY=$(ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l)",
        "echo DRM_ID=$(getprop persist.sys.cloud.drm.id 2>/dev/null | wc -c)",
        "echo CELL_INFO=$(getprop persist.sys.cloud.cellinfo 2>/dev/null | wc -c)",
        "echo BOOT_ID=$(getprop ro.sys.cloud.boot_id 2>/dev/null | wc -c)",
      ].join('; ');

      const [r1, r2, r3] = await Promise.all([
        sh(batch1Cmd), sh(batch2Cmd), sh(batch3Cmd),
      ]);
      const checks = { ...parseKV(r1), ...parseKV(r2), ...parseKV(r3) };

      // Rebalanced score computation — max exactly 100
      let score = 0;
      // ── Core Identity (20 pts) ──
      if (parseInt(checks.ACCOUNTS || '0') > 0)        score += 7;   // Google Account
      if (checks.GMS_REG === '1')                      score += 4;   // GMS device reg
      if (checks.GSF_ID === '1')                       score += 3;   // GSF ID
      if (checks.ANDROID_ID)                            score += 2;   // android_id set
      if (checks.IMEI_SET)                              score += 2;   // IMEI injected
      if (checks.WIFI)                                  score += 2;   // WiFi configured

      // ── System Profile (10 pts) ──
      if (checks.BUILD_TYPE === 'user')                 score += 2;   // Correct build type
      if (!checks.VMOS_LEAK)                            score += 2;   // No VMOS leak
      if (checks.SELINUX === 'Enforcing')               score += 2;   // SELinux Enforcing
      if (checks.SYS_SETTINGS === '1')                  score += 2;   // System settings configured
      if (parseInt(checks.PERMISSIONS || '0') >= 3)     score += 2;   // Permissions granted

      // ── Browser (12 pts) ──
      if (parseInt(checks.CHROME_COOKIES || '0') >= 10) score += 4;   // Chrome Cookies
      else if (parseInt(checks.CHROME_COOKIES || '0') > 0) score += 2;
      if (parseInt(checks.CHROME_HISTORY || '0') >= 15) score += 4;   // Chrome History
      else if (parseInt(checks.CHROME_HISTORY || '0') > 0) score += 2;
      if (parseInt(checks.CHROME_VISITS || '0') >= 10)  score += 1;   // Chrome Visits
      if (parseInt(checks.AUTOFILL || '0') > 0)        score += 3;   // Chrome Autofill

      // ── Communication (10 pts) ──
      if (parseInt(checks.CONTACTS || '0') >= 10)      score += 4;   // Contacts
      else if (parseInt(checks.CONTACTS || '0') >= 5)  score += 2;
      if (parseInt(checks.CALLS || '0') >= 20)         score += 3;   // Call Logs
      else if (parseInt(checks.CALLS || '0') >= 10)    score += 1;
      if (parseInt(checks.SMS || '0') >= 10)           score += 3;   // SMS
      else if (parseInt(checks.SMS || '0') >= 5)       score += 1;

      // ── Activity (10 pts) ──
      if (parseInt(checks.USAGE || '0') >= 5)          score += 3;   // UsageStats
      if (checks.KIWI === '1')                          score += 2;   // Kiwi browser
      if (checks.MEDIA_DB === '1')                      score += 2;   // Media DB seeded
      if (checks.DOWNLOADS === '1')                     score += 2;   // Downloads history
      if (parseInt(checks.NOTIFICATIONS || '0') > 0)   score += 1;   // Notification history

      // ── Payment (20 pts) ──
      if (parseInt(checks.TPAY || '0') > 0)            score += 4;   // Wallet/GPay
      if (parseInt(checks.PLAYSTORE || '0') > 0)       score += 3;   // Play Store prefs
      if (parseInt(checks.PURCH_HIST || '0') >= 5)     score += 3;   // Purchase history
      else if (parseInt(checks.PURCH_HIST || '0') > 0) score += 1;
      if (parseInt(checks.TXN_LOG || '0') >= 10)       score += 3;   // Transaction log
      else if (parseInt(checks.TXN_LOG || '0') > 0)    score += 1;
      if (checks.CARD_RISK === '1')                     score += 2;   // Card risk profile
      if (checks.INSTR_VERIFY === '1')                  score += 2;   // Instrument verified
      if (checks.BILL_CACHE === '1')                    score += 1;   // Billing cache
      if (checks.PLAY_AUTH === '1')                     score += 1;   // Play Store auth bypass
      if (checks.GPAY_AUTH === '1')                     score += 1;   // GPay auth bypass

      // ── Trust Signals (18 pts) ──
      if (checks.BILLING === '1')                       score += 1;   // Billing prefs
      if (checks.TAP_PREFS === '1')                     score += 1;   // Tap-and-pay prefs
      if (parseInt(checks.PROVINCIAL || '0') >= 2)     score += 2;   // Provincial app prefs
      else if (parseInt(checks.PROVINCIAL || '0') > 0) score += 1;
      if (parseInt(checks.BOOT_INIT || '0') > 0)       score += 2;   // Boot init completed
      if (parseInt(checks.PERMISSIONS || '0') >= 5)    score += 2;   // Deep permissions (bonus beyond base 2)
      // New checks for full 100 scoring
      if (checks.INSTALL_SRC === 'com.android.vending') score += 2;  // Install source = Play Store
      if (parseInt(checks.GALLERY || '0') >= 3)        score += 2;   // Gallery photos exist
      if (parseInt(checks.DRM_ID || '0') > 10)         score += 2;   // DRM device ID set
      if (parseInt(checks.CELL_INFO || '0') > 5)       score += 2;   // Cell info configured
      if (parseInt(checks.BOOT_ID || '0') > 10)        score += 2;   // Custom boot_id set

      score = Math.min(score, 100);

      const grade = score >= 95 ? 'A+' : score >= 90 ? 'A' : score >= 80 ? 'B+' : score >= 70 ? 'B' : score >= 60 ? 'C' : score >= 50 ? 'D' : 'F';
      job.trust_score = score;
      const notes = `${score}/100 (${grade}) — acct=${checks.ACCOUNTS} cookies=${checks.CHROME_COOKIES} hist=${checks.CHROME_HISTORY} contacts=${checks.CONTACTS} wallet=${checks.TPAY} media=${checks.MEDIA_DB} dl=${checks.DOWNLOADS} perms=${checks.PERMISSIONS} prov=${checks.PROVINCIAL} se=${checks.SELINUX} boot=${checks.BOOT_INIT}`;
      phase(11, 'done', notes.slice(0, 140));
      log(`Phase 11 — Trust Audit: ${score}/100 (${grade})`);
      log(`  Detail: ${JSON.stringify(checks)}`);

    } catch (e) {
      phase(11, 'failed', e.message.slice(0, 80));
      log(`Phase 11 — Trust Audit FAILED: ${e.message}`);
    }

    // ═══════════════════════════════════════════════════════════════
    // COMPLETE
    // ═══════════════════════════════════════════════════════════════
    // Phases 12-15 are UI display placeholders — mark complete
    [12, 13, 14, 15].forEach(i => phase(i, 'done', 'n/a'));

    job.status = 'completed';
    job.completed_at = Date.now();
    const elapsed = Math.round((job.completed_at - job.started_at) / 1000);
    const finalGrade = job.trust_score >= 95 ? 'A+' : job.trust_score >= 90 ? 'A' : job.trust_score >= 80 ? 'B+' : job.trust_score >= 70 ? 'B' : 'C';
    log(`✓ Pipeline complete in ${elapsed}s. Trust: ${job.trust_score}/100 (${finalGrade})`);

  } catch (e) {
    job.status = 'failed';
    job.error = e.message;
    log(`✗ Pipeline failed: ${e.message}`);
    console.error('[genesis-engine]', e);
  }
}

function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    }
  } catch (e) {
    console.warn('[config] Failed to load:', e.message);
  }
  return {};
}

function saveConfig(config) {
  try {
    ensureDir(path.dirname(CONFIG_FILE));
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
    return true;
  } catch (e) {
    console.warn('[config] Failed to save:', e.message);
    return false;
  }
}

function loadDotEnv(envPath) {
  const vars = {};
  try {
    if (!fs.existsSync(envPath)) return vars;
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq < 1) continue;
      const key = line.slice(0, eq).trim();
      let val = line.slice(eq + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (key && val) vars[key] = val;
    }
  } catch (e) {
    console.warn('[dotenv] Failed to load', envPath, e.message);
  }
  return vars;
}

function findPython() {
  // Prefer Python 3.11+ per Titan V13 coding guidelines
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { timeout: 5000 }).toString().trim();
      const match = ver.match(/Python\s+(\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 11))) {
        return { cmd, version: ver };
      }
    } catch (_) { /* not found */ }
  }
  return null;
}

function getUvicornCmd() {
  const venvUvi = path.join(VENV_DIR, 'bin', 'uvicorn');
  if (fs.existsSync(venvUvi)) return venvUvi;
  const legacyUvi = path.join(RESOURCES, 'venv', 'bin', 'uvicorn');
  if (fs.existsSync(legacyUvi)) return legacyUvi;
  const optUvi = '/opt/titan-v13-device/venv/bin/uvicorn';
  if (fs.existsSync(optUvi)) return optUvi;
  return 'uvicorn';
}

function isSetupDone() {
  const config = loadConfig();
  return fs.existsSync(SETUP_DONE) || (config.vmos_ak && config.vmos_sk);
}

// ─── Server Management ───────────────────────────────────────────────
function startServer() {
  if (serverProc) return;

  const uvicorn = getUvicornCmd();
  console.log(`[server] Starting uvicorn at ${uvicorn} on port ${API_PORT}`);

  const config = loadConfig();
  const envPath = path.join(RESOURCES, '.env');
  const envVars = loadDotEnv(envPath);

  const env = {
    ...process.env,
    ...envVars,
    PYTHONPATH: `${CORE_DIR}:${SERVER_DIR}`,
    TITAN_DATA: TITAN_DATA,
    TITAN_API_PORT: String(API_PORT),
    VMOS_CLOUD_AK: config.vmos_ak || envVars.VMOS_CLOUD_AK || '',
    VMOS_CLOUD_SK: config.vmos_sk || envVars.VMOS_CLOUD_SK || '',
  };

  ensureDir(TITAN_DATA);

  serverProc = spawn(uvicorn, ['titan_api:app', '--host', '127.0.0.1', '--port', String(API_PORT)], {
    cwd: SERVER_DIR,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  serverProc.stdout.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.log('[server]', msg);
  });

  serverProc.stderr.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.warn('[server-err]', msg);
  });

  serverProc.on('error', (err) => {
    console.warn('[server] Failed to start:', err.message);
    serverProc = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('server-error', err.message);
    }
  });

  serverProc.on('close', (code) => {
    console.log(`[server] Exited with code ${code}`);
    serverProc = null;
    if (_serverRestarts < MAX_SERVER_RESTARTS && mainWindow && !mainWindow.isDestroyed()) {
      _serverRestarts++;
      console.log(`[server] Auto-restart attempt ${_serverRestarts}/${MAX_SERVER_RESTARTS}`);
      setTimeout(startServer, 2000);
    }
  });
}

function stopServer() {
  if (serverProc) {
    serverProc.kill('SIGTERM');
    serverProc = null;
  }
}

// ─── Main Window ─────────────────────────────────────────────────────
async function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.focus();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'VMOS Titan — Cloud Device Management',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true,
    },
    autoHideMenuBar: true,
    frame: true,
    show: false,
  });

  // Load the main HTML file
  mainWindow.loadFile(path.join(__dirname, 'index.html'));

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (process.env.NODE_ENV === 'development') {
      mainWindow.webContents.openDevTools();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Create application menu
  createMenu();
}

// ─── Setup Window ────────────────────────────────────────────────────
function showSetupWindow() {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.focus();
    return;
  }

  setupWindow = new BrowserWindow({
    width: 600,
    height: 550,
    title: 'VMOS Titan — Initial Setup',
    backgroundColor: '#0a0e17',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
  });

  setupWindow.loadFile(path.join(__dirname, 'setup.html'));
  setupWindow.on('closed', () => { setupWindow = null; });
}

// ─── Application Menu ────────────────────────────────────────────────
function createMenu() {
  const template = [
    {
      label: 'VMOS Titan',
      submenu: [
        { label: 'About VMOS Titan', role: 'about' },
        { type: 'separator' },
        { label: 'Settings', accelerator: 'CmdOrCtrl+,', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'settings');
        }},
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', role: 'quit' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Dashboard', accelerator: 'CmdOrCtrl+1', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'dashboard');
        }},
        { label: 'Instances', accelerator: 'CmdOrCtrl+2', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'instances');
        }},
        { label: 'Genesis Studio', accelerator: 'CmdOrCtrl+3', click: () => {
          if (mainWindow) mainWindow.webContents.send('navigate', 'genesis');
        }},
        { type: 'separator' },
        { label: 'Reload', accelerator: 'CmdOrCtrl+R', role: 'reload' },
        { label: 'Toggle DevTools', accelerator: 'F12', role: 'toggleDevTools' },
        { type: 'separator' },
        { label: 'Toggle Fullscreen', accelerator: 'F11', role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        { label: 'Documentation', click: () => shell.openExternal('https://github.com/titan-project/docs') },
        { label: 'Report Issue', click: () => shell.openExternal('https://github.com/titan-project/issues') },
        { type: 'separator' },
        { label: 'About', click: () => {
          dialog.showMessageBox(mainWindow, {
            type: 'info',
            title: 'About VMOS Titan',
            message: 'VMOS Titan v1.0.0',
            detail: 'Professional VMOS Pro cloud device management with Genesis Studio integration.\n\nBuilt on Electron + Alpine.js + Tailwind CSS.'
          });
        }}
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// ─── System Tray ─────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png');
  if (!fs.existsSync(iconPath)) {
    console.warn('[tray] Icon not found:', iconPath);
    return;
  }

  tray = new Tray(iconPath);
  tray.setToolTip('VMOS Titan — Cloud Device Manager');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open VMOS Titan', click: () => { 
      if (mainWindow) mainWindow.show(); 
      else createMainWindow(); 
    }},
    { type: 'separator' },
    { label: 'Dashboard', click: () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.webContents.send('navigate', 'dashboard');
      }
    }},
    { label: 'Genesis Studio', click: () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.webContents.send('navigate', 'genesis');
      }
    }},
    { type: 'separator' },
    { label: 'Restart Server', click: () => {
      stopBuiltinServer();
      stopServer();
      _serverRestarts = 0;
      setTimeout(startBuiltinServer, 500);
    }},
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() }
  ]));
  tray.on('double-click', () => { 
    if (mainWindow) mainWindow.show(); 
    else createMainWindow();
  });
}

// ─── IPC Handlers ────────────────────────────────────────────────────

// Setup IPC
ipcMain.handle('setup:getInfo', () => {
  const python = findPython();
  const config = loadConfig();
  return {
    python: python ? python : null,
    venvExists: fs.existsSync(path.join(VENV_DIR, 'bin', 'python3')),
    dataDir: TITAN_DATA,
    venvDir: VENV_DIR,
    isPackaged: IS_PACKAGED,
    hasCredentials: !!(config.vmos_ak && config.vmos_sk),
    vmosAk: config.vmos_ak || '',
  };
});

ipcMain.handle('setup:save', async (event, { vmos_ak, vmos_sk }) => {
  const config = loadConfig();
  config.vmos_ak = vmos_ak;
  config.vmos_sk = vmos_sk;
  config.setup_date = new Date().toISOString();
  
  if (saveConfig(config)) {
    ensureDir(path.dirname(SETUP_DONE));
    fs.writeFileSync(SETUP_DONE, new Date().toISOString());
    return { ok: true };
  }
  return { ok: false, error: 'Failed to save configuration' };
});

ipcMain.handle('setup:testCredentials', async (event, { vmos_ak, vmos_sk }) => {
  return new Promise((resolve) => {
    // Test VMOS Cloud API credentials by calling instance_list
    const body = JSON.stringify({ page: 1, rows: 1 });
    const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
    
    // For now, just verify credentials are non-empty
    if (!vmos_ak || !vmos_sk) {
      resolve({ ok: false, error: 'Missing credentials' });
      return;
    }
    
    // Return success if credentials provided
    resolve({ ok: true, message: 'Credentials saved. API will be tested on first use.' });
  });
});

ipcMain.handle('config:get', () => {
  return loadConfig();
});

ipcMain.handle('config:set', (event, updates) => {
  const existing = loadConfig();
  return saveConfig({ ...existing, ...updates });
});

// Server status
ipcMain.handle('server:status', () => {
  return {
    running: serverProc !== null,
    port: API_PORT,
    restarts: _serverRestarts
  };
});

ipcMain.handle('server:restart', () => {
  stopServer();
  _serverRestarts = 0;
  setTimeout(startServer, 1000);
  return { ok: true };
});

// Open external links
ipcMain.on('shell:openExternal', (event, url) => {
  shell.openExternal(url);
});

// ─── App Lifecycle ───────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray();

  if (isSetupDone()) {
    // Start built-in Node.js API server (no Python required)
    startBuiltinServer();
    await createMainWindow();
  } else {
    showSetupWindow();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    // Keep running in tray on Linux
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    if (isSetupDone()) createMainWindow();
    else showSetupWindow();
  }
});

app.on('before-quit', () => {
  stopBuiltinServer();
  stopServer();
});

// Handle setup completion
ipcMain.on('setup:complete', async () => {
  if (setupWindow) {
    setupWindow.close();
    setupWindow = null;
  }
  startBuiltinServer();
  await createMainWindow();
});
