const https = require('https');
const crypto = require('crypto');

const path = require('path');
const fs = require('fs');
const envPath = path.resolve(__dirname, '..', '.env');
const envLines = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8').split('\n') : [];
const envGet = (k) => { const l = envLines.find(l => l.startsWith(k + '=')); return l ? l.split('=').slice(1).join('=').trim() : ''; };
const ak = envGet('VMOS_CLOUD_AK');
const sk = envGet('VMOS_CLOUD_SK');
if (!ak || !sk) { console.error('Missing VMOS_CLOUD_AK or VMOS_CLOUD_SK in ../.env'); process.exit(1); }

const VMOS_HOST    = 'api.vmoscloud.com';
const VMOS_SERVICE = 'armcloud-paas';
const VMOS_CT      = 'application/json;charset=UTF-8';
const VMOS_SH      = 'content-type;host;x-content-sha256;x-date';

function _vmosSign(bodyJson, ak, sk) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '');
  const xDateClean = xDate.replace(/\.\d{3}Z$/, 'Z');
  const shortDate = xDateClean.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const canonical = [
    `host:${VMOS_HOST}`,
    `x-date:${xDateClean}`,
    `content-type:${VMOS_CT}`,
    `signedHeaders:${VMOS_SH}`,
    `x-content-sha256:${xSha}`
  ].join('\n');
  const scope    = `${shortDate}/${VMOS_SERVICE}/request`;
  const hashCan  = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  const sts      = ['HMAC-SHA256', xDateClean, scope, hashCan].join('\n');
  const kDate    = crypto.createHmac('sha256', Buffer.from(sk, 'utf8')).update(shortDate).digest();
  const kSvc     = crypto.createHmac('sha256', kDate).update(VMOS_SERVICE).digest();
  const sigKey   = crypto.createHmac('sha256', kSvc).update('request').digest();
  const sig      = crypto.createHmac('sha256', sigKey).update(sts).digest('hex');
  return {
    'content-type': VMOS_CT,
    'x-date': xDateClean,
    'x-host': VMOS_HOST,
    'authorization': `HMAC-SHA256 Credential=${ak}, SignedHeaders=${VMOS_SH}, Signature=${sig}`,
  };
}

function vmosPost(apiPath, data) {
  return new Promise((resolve, reject) => {
    const bodyJson = JSON.stringify(data || {});
    const headers  = _vmosSign(bodyJson, ak, sk);
    const buf      = Buffer.from(bodyJson, 'utf8');
    const req = https.request({
      hostname: VMOS_HOST,
      path: apiPath,
      method: 'POST',
      headers: { ...headers, 'content-length': buf.length },
      timeout: 30000,
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

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function getDeviceStatus() {
    const res = await vmosPost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 });
    const statuses = {};
    if (res && res.data && res.data.pageData) {
        res.data.pageData.forEach(d => {
            statuses[d.padCode] = d.padStatus;
        });
    }
    return statuses;
}

async function fix() {
    console.log("Checking current devices states...");
    let statuses = await getDeviceStatus();
    
    // ACP2509244LGV1MV — safe recovery (NEVER use replacePad — causes unpredictable resets)
    const s1 = statuses['ACP2509244LGV1MV'];
    if (s1 === 10) {
        console.log(`[ACP2509244LGV1MV] is already status 10 (Running).`);
    } else if (s1 === 14) {
        console.log(`[ACP2509244LGV1MV] is in status 14 (Stopped). Sending ONE restart...`);
        const r1 = await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: ['ACP2509244LGV1MV'] });
        console.log(`-> restart response: ${JSON.stringify(r1)}`);
    } else if (s1 === 11) {
        console.log(`[ACP2509244LGV1MV] is in status 11 (Booting). DO NOT restart — wait for 11→10 transition.`);
    } else if (s1 !== undefined) {
        console.log(`[ACP2509244LGV1MV] is in status ${s1}. Waiting — no action taken.`);
    }

    // ACP251008CRDQZPF stopped at 14
    if (statuses['ACP251008CRDQZPF'] === 14) {
        console.log(`[ACP251008CRDQZPF] is in status 14 (Stopped). Attempting restart...`);
        const r2 = await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: ['ACP251008CRDQZPF'] });
        console.log(`-> restart response: ${JSON.stringify(r2)}`);
    } else if (statuses['ACP251008CRDQZPF'] !== 10) {
        console.log(`[ACP251008CRDQZPF] is in status ${statuses['ACP251008CRDQZPF']}. Not taking action yet, let's wait.`);
    }

    console.log("Waiting for devices to become fully available (Status 10)...");
    
    // Polling loop
    for (let i = 0; i < 40; i++) { // wait up to ~200s (20000ms if 10 but 5000 is 5s)
        await sleep(5000);
        statuses = await getDeviceStatus();
        console.log(`Polling... ACP2509244LGV1MV: ${statuses['ACP2509244LGV1MV']} | ACP251008CRDQZPF: ${statuses['ACP251008CRDQZPF']}`);
        if (statuses['ACP2509244LGV1MV'] == 10 && statuses['ACP251008CRDQZPF'] == 10) {
            console.log("SUCCESS: Both devices are now Status 10 (Running)!");
            break;
        }
        
        // If device reached 14, send ONE restart to boot it
        if (statuses['ACP2509244LGV1MV'] === 14) {
             console.log(`[ACP2509244LGV1MV] reached status 14. Sending ONE restart...`);
             await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: ['ACP2509244LGV1MV'] });
        }
    }
}

fix().catch(err => {
    console.error("Error occurred:", err);
});