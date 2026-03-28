/**
 * VMOS Titan Ops-Web — Localhost Operations Server
 *
 * Standalone Node.js HTTP server (zero external deps) that proxies to VMOS Cloud API
 * and serves a full operations dashboard at http://localhost:3000
 *
 * Features:
 *   - VMOS Cloud API proxy with HMAC-SHA256 signing
 *   - Instance management (list, restart, reset, screenshot, shell)
 *   - Genesis pipeline trigger + status polling
 *   - Device property inspection & modification
 *   - Real-time log streaming
 *   - Proxy configuration
 *   - Full dashboard UI
 */

'use strict';

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

// ─── Config ────────────────────────────────────────────────────────
const PORT = parseInt(process.env.OPS_PORT || '3000', 10);
const VERBOSE = process.argv.includes('--verbose');

// Load credentials from parent .env or env vars
function loadEnv() {
  const envPaths = [
    path.join(__dirname, '..', '..', '.env'),           // /opt/titan-v13-device/.env
    path.join(__dirname, '..', '.env'),                  // vmos-titan/.env
    '/opt/titan-v13-device/.env',
  ];
  const vars = {};
  for (const p of envPaths) {
    try {
      if (!fs.existsSync(p)) continue;
      for (const line of fs.readFileSync(p, 'utf-8').split('\n')) {
        const l = line.trim();
        if (!l || l.startsWith('#')) continue;
        const eq = l.indexOf('=');
        if (eq < 1) continue;
        const k = l.slice(0, eq).trim();
        let v = l.slice(eq + 1).trim();
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
          v = v.slice(1, -1);
        vars[k] = v;
      }
      if (VERBOSE) console.log(`[env] Loaded ${p}`);
      break;
    } catch (_) {}
  }
  return vars;
}

const envVars = loadEnv();
const VMOS_AK = process.env.VMOS_CLOUD_AK || envVars.VMOS_CLOUD_AK || '';
const VMOS_SK = process.env.VMOS_CLOUD_SK || envVars.VMOS_CLOUD_SK || '';
const VMOS_HOST = 'api.vmoscloud.com';
const VMOS_SERVICE = 'armcloud-paas';
const VMOS_CT = 'application/json;charset=UTF-8';
const VMOS_SH = 'content-type;host;x-content-sha256;x-date';

// In-memory state
const genesisJobs = new Map();

// ─── VMOS Cloud HMAC Signing ──────────────────────────────────────
function vmosSign(bodyJson) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const shortDate = xDate.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const canonical = [
    `host:${VMOS_HOST}`, `x-date:${xDate}`, `content-type:${VMOS_CT}`,
    `signedHeaders:${VMOS_SH}`, `x-content-sha256:${xSha}`,
  ].join('\n');
  const scope = `${shortDate}/${VMOS_SERVICE}/request`;
  const hashCan = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  const sts = ['HMAC-SHA256', xDate, scope, hashCan].join('\n');
  const kDate = crypto.createHmac('sha256', Buffer.from(VMOS_SK, 'utf8')).update(shortDate).digest();
  const kSvc = crypto.createHmac('sha256', kDate).update(VMOS_SERVICE).digest();
  const sigKey = crypto.createHmac('sha256', kSvc).update('request').digest();
  const sig = crypto.createHmac('sha256', sigKey).update(sts).digest('hex');
  return {
    'content-type': VMOS_CT,
    'x-date': xDate,
    'x-host': VMOS_HOST,
    'authorization': `HMAC-SHA256 Credential=${VMOS_AK}, SignedHeaders=${VMOS_SH}, Signature=${sig}`,
  };
}

function vmosPost(apiPath, data, timeoutSec) {
  return new Promise((resolve, reject) => {
    const bodyJson = JSON.stringify(data || {});
    const headers = vmosSign(bodyJson);
    const buf = Buffer.from(bodyJson, 'utf8');
    const timeoutMs = Math.min(Math.max((timeoutSec || 30) * 1000, 5000), 120000);
    const req = https.request({
      hostname: VMOS_HOST, path: apiPath, method: 'POST',
      headers: { ...headers, 'content-length': buf.length },
      timeout: timeoutMs,
    }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); }
        catch { reject(new Error(`Bad JSON (${res.statusCode}): ${raw.slice(0, 200)}`)); }
      });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('Timeout')); });
    req.on('error', reject);
    req.write(buf);
    req.end();
  });
}

// ─── API Routes ───────────────────────────────────────────────────
async function handleAPI(pathname, method, body, res) {
  const send = (data, code = 200) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };

  if (!VMOS_AK || !VMOS_SK) return send({ error: 'VMOS credentials not configured. Set VMOS_CLOUD_AK/VMOS_CLOUD_SK in .env' }, 401);

  try {
    // Health
    if (pathname === '/api/health') return send({ status: 'ok', version: '2.0.0', mode: 'ops-web', uptime: process.uptime() | 0 });

    // List instances
    if (pathname === '/api/instances' && method === 'GET') {
      const r = await vmosPost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 });
      const raw = (r.data && Array.isArray(r.data.pageData)) ? r.data.pageData : [];
      const instances = raw.map(i => {
        const verMatch = (i.imageVersion || '').match(/\d+/);
        return {
          padCode: i.padCode || '',
          status: i.padStatus ?? 0,
          model: i.padGrade || '',
          androidVersion: verMatch ? verMatch[0] : '',
          imageVersion: i.imageVersion || '',
          adbOpen: i.adbOpenStatus || '0',
          createTime: i.createTime || '',
          cluster: i.clusterCode || '',
        };
      });
      return send({ instances, count: instances.length });
    }

    // Instance actions: /api/instances/:padCode/:action
    const instMatch = pathname.match(/^\/api\/instances\/([^/]+)(?:\/(.+))?$/);
    if (instMatch) {
      const padCode = decodeURIComponent(instMatch[1]);
      const action = instMatch[2] || 'info';

      if (action === 'info' && method === 'GET') {
        const [rProps, rInfo] = await Promise.all([
          vmosPost('/vcpcloud/api/padApi/padProperties', { padCode }).catch(() => ({ data: {} })),
          vmosPost('/vcpcloud/api/padApi/padInfo', { padCode }).catch(() => ({ data: {} })),
        ]);
        return send({ properties: rProps.data || {}, info: rInfo.data || {} });
      }

      if (action === 'restart' && method === 'POST') {
        const r = await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: [padCode] });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      if (action === 'reset' && method === 'POST') {
        const r = await vmosPost('/vcpcloud/api/padApi/replacePad', {
          padCodes: [padCode], countryCode: 'US', wipeData: 1, androidPropMap: {},
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      if (action === 'screenshot' && method === 'GET') {
        const r = await vmosPost('/vcpcloud/api/padApi/screenshot', { padCodes: [padCode] });
        const d = r.data;
        const imgUrl = (Array.isArray(d) ? d[0]?.imgUrl : d?.imgUrl) || '';
        return send({ url: imgUrl });
      }

      if (action === 'shell' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const cmd = (parsed.command || '').slice(0, 4000);
        if (!cmd) return send({ error: 'No command provided' }, 400);
        const r = await vmosPost('/vcpcloud/api/padApi/syncCmd', { padCode, scriptContent: cmd }, 60);
        let output = '';
        if (r.code === 200 && r.data) {
          const items = Array.isArray(r.data) ? r.data : [r.data];
          const item = items[0] || {};
          output = item.taskStatus === 3 ? (item.errorMsg || item.taskResult || 'OK') : `Failed (status=${item.taskStatus})`;
        }
        return send({ output: output.trim(), ok: r.code === 200 });
      }

      if (action === 'properties' && method === 'GET') {
        const r = await vmosPost('/vcpcloud/api/padApi/padProperties', { padCode });
        return send({ properties: r.data || {} });
      }

      if (action === 'properties' && method === 'POST') {
        const props = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updatePadProperties', { padCodes: [padCode], ...props });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      if (action === 'adb-enable' && method === 'POST') {
        const r = await vmosPost('/vcpcloud/api/padApi/openAdb', { padCodes: [padCode] });
        return send({ ok: r.code === 200, data: r.data });
      }

      if (action === 'adb-disable' && method === 'POST') {
        const r = await vmosPost('/vcpcloud/api/padApi/closeAdb', { padCodes: [padCode] });
        return send({ ok: r.code === 200 });
      }

      if (action === 'gps' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/gpsInjectInfo', {
          padCodes: [padCode], lat: parsed.lat, lng: parsed.lng,
          altitude: parsed.altitude || 30, speed: parsed.speed || 0,
          bearing: parsed.bearing || 0, horizontalAccuracy: 5,
        });
        return send({ ok: r.code === 200 });
      }

      if (action === 'proxy' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/setProxy', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      if (action === 'one-key-new' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/changePhoneInfo', {
          padCodes: [padCode], countryCode: parsed.country || 'US',
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── SIM card modification ──
      if (action === 'sim' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateSimProperties', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── WiFi configuration ──
      if (action === 'wifi' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateWifiProperties', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Timezone / Language ──
      if (action === 'locale' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateTimeZone', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Battery simulation ──
      if (action === 'battery' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateBatteryStatus', {
          padCodes: [padCode], level: parsed.level || 75, charging: parsed.charging ?? false,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Bluetooth ──
      if (action === 'bluetooth' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateBluetoothProperties', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── GAID Reset ──
      if (action === 'reset-gaid' && method === 'POST') {
        const r = await vmosPost('/vcpcloud/api/padApi/resetGaid', { padCodes: [padCode] });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Bandwidth control ──
      if (action === 'bandwidth' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateBandwidth', {
          padCodes: [padCode], upBandwidth: parsed.up ?? 0, downBandwidth: parsed.down ?? 0,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Proxy query ──
      if (action === 'proxy' && method === 'GET') {
        const r = await vmosPost('/vcpcloud/api/padApi/queryProxy', { padCodes: [padCode] });
        return send({ ok: r.code === 200, data: r.data });
      }

      // ── Touch simulation ──
      if (action === 'touch' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/touch', {
          padCode, ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Text input ──
      if (action === 'input-text' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/inputText', {
          padCode, text: parsed.text || '',
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Contacts injection ──
      if (action === 'contacts' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/importContacts', {
          padCodes: [padCode], contacts: parsed.contacts || [],
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Call log injection ──
      if (action === 'call-logs' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/importCallLogs', {
          padCodes: [padCode], callLogs: parsed.callLogs || [],
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── SMS injection ──
      if (action === 'sms' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/sendSms', {
          padCodes: [padCode], ...parsed,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── Process hiding ──
      if (action === 'process-hide' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/processShow', {
          padCodes: [padCode], packageName: parsed.packageName, show: parsed.show ?? false,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      // ── ADI template ──
      if (action === 'adi-template' && method === 'POST') {
        const parsed = JSON.parse(body || '{}');
        const r = await vmosPost('/vcpcloud/api/padApi/updateAdiTemplate', {
          padCodes: [padCode], adiId: parsed.adiId, wipeData: parsed.wipeData ?? 0,
        });
        return send({ ok: r.code === 200, msg: r.msg });
      }

      return send({ error: `Unknown action: ${action}` }, 404);
    }

    // ── App management ────────────────────────────────────────────
    if (pathname === '/api/apps/install' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length || !parsed.url) return send({ error: 'padCodes[] and url required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/installApk', {
        padCodes: parsed.padCodes, apkUrl: parsed.url,
        isAuthorization: parsed.autoGrant ? 1 : 0,
      });
      return send({ ok: r.code === 200, data: r.data, msg: r.msg });
    }

    if (pathname === '/api/apps/uninstall' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length || !parsed.packageName) return send({ error: 'padCodes[] and packageName required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/uninstallApk', {
        padCodes: parsed.padCodes, packageName: parsed.packageName,
      });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    if (pathname === '/api/apps/start' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length || !parsed.packageName) return send({ error: 'padCodes[] and packageName required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/startApp', {
        padCodes: parsed.padCodes, packageName: parsed.packageName,
      });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    if (pathname === '/api/apps/stop' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length || !parsed.packageName) return send({ error: 'padCodes[] and packageName required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/stopApp', {
        padCodes: parsed.padCodes, packageName: parsed.packageName,
      });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    if (pathname === '/api/apps/list' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCode) return send({ error: 'padCode required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/queryApps', { padCode: parsed.padCode });
      return send({ ok: r.code === 200, apps: r.data || [] });
    }

    if (pathname === '/api/apps/clear-processes' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length) return send({ error: 'padCodes[] required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/clearProcesses', { padCodes: parsed.padCodes });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    // ── Batch model info ──
    if (pathname === '/api/models' && method === 'GET') {
      const r = await vmosPost('/vcpcloud/api/padApi/batchModelInfo', {});
      return send({ ok: r.code === 200, data: r.data });
    }

    // ── ADI template list ──
    if (pathname === '/api/adi-templates' && method === 'GET') {
      const r = await vmosPost('/vcpcloud/api/padApi/queryAdiTemplates', {});
      return send({ ok: r.code === 200, data: r.data });
    }

    // ── Smart IP (proxy auto-config by IP) ──
    if (pathname === '/api/smart-ip' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length) return send({ error: 'padCodes[] required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/smartIp', {
        padCodes: parsed.padCodes, ...parsed,
      });
      return send({ ok: r.code === 200, data: r.data, msg: r.msg });
    }

    // ── Check IP availability ──
    if (pathname === '/api/check-ip' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      const r = await vmosPost('/vcpcloud/api/padApi/checkIp', parsed);
      return send({ ok: r.code === 200, data: r.data });
    }

    // ── Android prop modification ──
    if (pathname === '/api/android-props' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.padCodes?.length) return send({ error: 'padCodes[] required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/updateAndroidProp', {
        padCodes: parsed.padCodes, androidPropMap: parsed.props || {},
        needRestart: parsed.needRestart ?? true,
      });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    // ── Task tracking ──
    const taskMatch = pathname.match(/^\/api\/task\/([^/]+)$/);
    if (taskMatch && method === 'GET') {
      const r = await vmosPost('/vcpcloud/api/padApi/queryTaskDetail', { taskId: taskMatch[1] });
      return send({ ok: r.code === 200, data: r.data });
    }

    // Genesis: start
    if (pathname === '/api/genesis/start' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      if (!parsed.device_id) return send({ error: 'device_id required' }, 400);
      const jobId = crypto.randomBytes(16).toString('hex');
      genesisJobs.set(jobId, {
        job_id: jobId, pad_code: parsed.device_id,
        status: 'queued', started_at: Date.now(), config: parsed,
        log: [`[${new Date().toISOString()}] Genesis job queued for ${parsed.device_id}`],
      });
      return send({ job_id: jobId, status: 'queued', message: 'Use the Electron app or Titan API for full genesis pipeline execution. This endpoint tracks job state.' });
    }

    // Genesis: status
    const gsMatch = pathname.match(/^\/api\/genesis\/status\/([^/]+)$/);
    if (gsMatch) {
      const job = genesisJobs.get(gsMatch[1]);
      if (!job) return send({ error: 'Job not found' }, 404);
      return send(job);
    }

    // Genesis: list jobs
    if (pathname === '/api/genesis/jobs' && method === 'GET') {
      const jobs = [...genesisJobs.values()].map(j => ({
        job_id: j.job_id, pad_code: j.pad_code, status: j.status,
        started_at: j.started_at, trust_score: j.trust_score || 0,
      }));
      return send({ jobs });
    }

    // Batch operations
    if (pathname === '/api/batch/restart' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      const codes = parsed.padCodes || [];
      if (!codes.length) return send({ error: 'padCodes[] required' }, 400);
      const r = await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: codes });
      return send({ ok: r.code === 200, msg: r.msg });
    }

    if (pathname === '/api/batch/screenshot' && method === 'POST') {
      const parsed = JSON.parse(body || '{}');
      const codes = parsed.padCodes || [];
      const r = await vmosPost('/vcpcloud/api/padApi/screenshot', { padCodes: codes });
      return send({ ok: r.code === 200, data: r.data });
    }

    return send({ error: 'Not found' }, 404);

  } catch (e) {
    if (VERBOSE) console.error('[api-err]', e.message);
    return send({ error: e.message }, 500);
  }
}

// ─── Static File Server ────────────────────────────────────────────
const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function serveStatic(pathname, res) {
  let filePath = pathname === '/' ? '/index.html' : pathname;
  filePath = path.join(__dirname, filePath);

  // Security: prevent path traversal
  if (!filePath.startsWith(__dirname)) {
    res.writeHead(403); res.end('Forbidden'); return;
  }

  const ext = path.extname(filePath);
  const mime = MIME[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not Found'); return; }
    res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

// ─── HTTP Server ──────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const urlObj = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = urlObj.pathname;
  const method = req.method;

  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,Authorization');
  if (method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // API routes
  if (pathname.startsWith('/api/')) {
    let body = '';
    await new Promise((resolve, reject) => {
      let size = 0;
      req.on('data', c => { size += c.length; if (size > 65536) { req.destroy(); return reject(); } body += c; });
      req.on('end', resolve);
      req.on('error', reject);
    }).catch(() => {});
    if (res.writableEnded) return;
    return handleAPI(pathname, method, body, res);
  }

  // Static files
  serveStatic(pathname, res);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('');
  console.log('═══════════════════════════════════════════════════════════');
  console.log('  VMOS Titan Ops-Web v2.0');
  console.log(`  Running at http://localhost:${PORT}`);
  console.log('═══════════════════════════════════════════════════════════');
  console.log('');
  console.log(`  Credentials: ${VMOS_AK ? 'Loaded (AK=' + VMOS_AK.slice(0, 8) + '...)' : '⚠ NOT SET — configure VMOS_CLOUD_AK/SK in .env'}`);
  console.log(`  Mode: ops-web standalone`);
  console.log('');
});


