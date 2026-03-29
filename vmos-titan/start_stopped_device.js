const https = require('https');
const crypto = require('crypto');

const ak = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi";
const sk = "Q2SgcSwEfuwoedY0cijp6Mce";

const VMOS_HOST    = 'api.vmoscloud.com';
const VMOS_SERVICE = 'armcloud-paas';
const VMOS_CT      = 'application/json;charset=UTF-8';
const VMOS_SH      = 'content-type;host;x-content-sha256;x-date';

function _vmosSign(bodyJson, ak, sk) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '');
  const xDateClean = xDate.replace(/\.\d{3}Z$/, 'Z');
  const shortDate = xDateClean.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const canonical = [`host:${VMOS_HOST}`, `x-date:${xDateClean}`, `content-type:${VMOS_CT}`, `signedHeaders:${VMOS_SH}`, `x-content-sha256:${xSha}`].join('\n');
  const scope    = `${shortDate}/${VMOS_SERVICE}/request`;
  const hashCan  = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  const sts      = ['HMAC-SHA256', xDateClean, scope, hashCan].join('\n');
  const kDate    = crypto.createHmac('sha256', Buffer.from(sk, 'utf8')).update(shortDate).digest();
  const kSvc     = crypto.createHmac('sha256', kDate).update(VMOS_SERVICE).digest();
  const sigKey   = crypto.createHmac('sha256', kSvc).update('request').digest();
  const sig      = crypto.createHmac('sha256', sigKey).update(sts).digest('hex');
  return { 'content-type': VMOS_CT, 'x-date': xDateClean, 'x-host': VMOS_HOST, 'authorization': `HMAC-SHA256 Credential=${ak}, SignedHeaders=${VMOS_SH}, Signature=${sig}` };
}

function vmosPost(apiPath, data) {
  return new Promise((resolve, reject) => {
    const bodyJson = JSON.stringify(data || {});
    const headers  = _vmosSign(bodyJson, ak, sk);
    const buf      = Buffer.from(bodyJson, 'utf8');
    const req = https.request({ hostname: VMOS_HOST, path: apiPath, method: 'POST', headers: { ...headers, 'content-length': buf.length } }, res => {
      let raw = ''; res.on('data', c => raw += c); res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { resolve(raw); } });
    });
    req.write(buf); req.end();
  });
}

(async () => {
  const res = await vmosPost('/vcpcloud/api/padApi/infos', { page: 1, rows: 100 });
  const p = res.data.pageData;
  for (const d of p) {
    if (d.padStatus === 14) {
      console.log(`Device ${d.padCode} is Stopped (14). Restarting...`);
      const r = await vmosPost('/vcpcloud/api/padApi/restart', { padCodes: [d.padCode] });
      console.log(`Restart response:`, r);
    } else {
      console.log(`Device ${d.padCode} is Status ${d.padStatus}.`);
    }
  }
})();
