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

function vmosPost(apiPath, data, ak, sk) {
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

async function main() {
  console.log("Fetching pad infos...");
  try {
    const res = await vmosPost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 }, ak, sk);
    if (!res.data || !res.data.pageData) {
      console.log("No devices found or error: ", res);
      return;
    }
    const devices = res.data.pageData;
    console.log(`Found ${devices.length} devices:`);
    devices.forEach(d => {
      console.log(`- Device: ${d.padCode}, Status: ${d.padStatus} (${d.padStatus === 10 ? 'Running' : d.padStatus === 11 ? 'Booting' : d.padStatus === 12 ? 'Resetting' : d.padStatus === 14 ? 'Stopped' : 'Unknown'})`);
    });
  } catch (err) {
    console.error("Error:", err);
  }
}

main();