const https = require('https'), crypto = require('crypto');
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi', SK = 'Q2SgcSwEfuwoedY0cijp6Mce', HOST = 'api.vmoscloud.com';
const PAD = 'APP5B54EI0Z1EOEA';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function _sign(b) {
  const dt = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z/, 'Z');
  const sd = dt.slice(0, 8);
  const xs = crypto.createHash('sha256').update(b, 'utf8').digest('hex');
  const SH = 'content-type;host;x-content-sha256;x-date';
  const CT = 'application/json;charset=UTF-8';
  const c = ['host:' + HOST, 'x-date:' + dt, 'content-type:' + CT, 'signedHeaders:' + SH, 'x-content-sha256:' + xs].join('\n');
  const sc = sd + '/armcloud-paas/request';
  const hc = crypto.createHash('sha256').update(c, 'utf8').digest('hex');
  const st = ['HMAC-SHA256', dt, sc, hc].join('\n');
  const kd = crypto.createHmac('sha256', Buffer.from(SK)).update(sd).digest();
  const ks = crypto.createHmac('sha256', kd).update('armcloud-paas').digest();
  const kr = crypto.createHmac('sha256', ks).update('request').digest();
  const sg = crypto.createHmac('sha256', kr).update(st).digest('hex');
  return {
    'content-type': CT, 'x-date': dt, 'x-host': HOST,
    'authorization': 'HMAC-SHA256 Credential=' + AK + ', SignedHeaders=' + SH + ', Signature=' + sg
  };
}

function vpost(p, d, t) {
  return new Promise((r, j) => {
    const b = JSON.stringify(d || {});
    const h = _sign(b);
    const buf = Buffer.from(b);
    const req = https.request({
      hostname: HOST, path: p, method: 'POST',
      headers: { ...h, 'content-length': buf.length },
      timeout: (t || 30) * 1000
    }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => { try { r(JSON.parse(raw)); } catch { r({ raw }); } });
    });
    req.on('timeout', () => { req.destroy(); j(new Error('timeout')); });
    req.on('error', j);
    req.write(buf);
    req.end();
  });
}

(async () => {
  // Check current status
  console.log('Checking current status...');
  const info0 = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
  let s0 = 0;
  if (info0.data && info0.data.pageData && info0.data.pageData.length) s0 = info0.data.pageData[0].padStatus;
  console.log('Current status:', s0);

  // Send restart
  console.log('Sending restart command...');
  const r = await vpost('/vcpcloud/api/padApi/restart', { padCodes: [PAD] });
  console.log('Restart API:', r.code, r.msg);

  if (r.code !== 200) {
    console.log('Restart failed. Full response:', JSON.stringify(r));
    return;
  }

  // Wait for boot cycle
  console.log('Waiting for boot cycle (12→11→10)...');
  let sawBooting = false;
  for (let i = 0; i < 40; i++) {
    await sleep(10000);
    const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
    let s = 0;
    if (info.data && info.data.pageData && info.data.pageData.length) s = info.data.pageData[0].padStatus;
    process.stdout.write('[' + ((i + 1) * 10) + 's] status=' + s);

    if (s === 11 || s === 12) {
      sawBooting = true;
      console.log(' (booting)');
    } else if (s === 10 && sawBooting) {
      console.log(' BOOTED! Waiting 60s for full CBS init...');
      await sleep(60000);

      // Test with a simple command
      console.log('Testing syncCmd...');
      const t = await vpost('/vcpcloud/api/padApi/syncCmd', { padCode: PAD, scriptContent: 'echo READY && id && getprop ro.product.model' });
      if (t.code === 200) {
        const d = Array.isArray(t.data) ? t.data[0] : t.data;
        if (d && d.taskStatus === 3) {
          console.log('SUCCESS:', d.errorMsg || d.taskResult);
        } else {
          console.log('Task status:', d ? d.taskStatus : 'no data');
        }
      } else {
        console.log('Error:', t.code, t.msg);
      }
      return;
    } else if (s === 10 && !sawBooting) {
      console.log(' (still 10, no boot cycle seen yet)');
    } else {
      console.log(' (status=' + s + ')');
    }
  }
  console.log('TIMEOUT - device did not complete boot in 400s');
})().catch(e => console.error('Fatal:', e.message));
