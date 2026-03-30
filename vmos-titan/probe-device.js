#!/usr/bin/env node
const https = require('https'), crypto = require('crypto');
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi', SK = 'Q2SgcSwEfuwoedY0cijp6Mce', HOST = 'api.vmoscloud.com';

function _sign(b) {
  const dt = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const sd = dt.slice(0, 8);
  const xs = crypto.createHash('sha256').update(b, 'utf8').digest('hex');
  const SH = 'content-type;host;x-content-sha256;x-date';
  const CT = 'application/json;charset=UTF-8';
  const c = ['host:' + HOST, 'x-date:' + dt, 'content-type:' + CT, 'signedHeaders:' + SH, 'x-content-sha256:' + xs].join('\n');
  const sc = sd + '/armcloud-paas/request';
  const hc = crypto.createHash('sha256').update(c, 'utf8').digest('hex');
  const st = ['HMAC-SHA256', dt, sc, hc].join('\n');
  const kd = crypto.createHmac('sha256', Buffer.from(SK, 'utf8')).update(sd).digest();
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
    const buf = Buffer.from(b, 'utf8');
    const req = https.request({
      hostname: HOST, path: p, method: 'POST',
      headers: { ...h, 'content-length': buf.length },
      timeout: (t || 30) * 1000
    }, res => {
      let raw = ''; res.on('data', c => raw += c);
      res.on('end', () => { try { r(JSON.parse(raw)); } catch { r({ raw }); } });
    });
    req.on('timeout', () => { req.destroy(); j(new Error('timeout')); });
    req.on('error', j);
    req.write(buf); req.end();
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function sh(pad, cmd, sec) {
  for (let a = 0; a < 2; a++) {
    try {
      const r = await vpost('/vcpcloud/api/padApi/syncCmd', { padCode: pad, scriptContent: cmd }, sec || 30);
      if (r.code !== 200) return '(api-err:' + r.code + ')';
      const it = Array.isArray(r.data) ? r.data : [r.data];
      const i = it[0] || {};
      if (i.taskStatus === 3) return i.errorMsg || i.taskResult || '';
      return '(ts:' + i.taskStatus + ')';
    } catch (e) { if (a === 1) return '(err:' + e.message + ')'; await sleep(2000); }
  }
  return '';
}

const PAD = 'APP5B54EI0Z1EOEA';

(async () => {
  // 1. Device status
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║  DEEP PROBE: ' + PAD + '               ║');
  console.log('╚══════════════════════════════════════════════════╝');

  const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
  let d = null;
  if (info.code === 200) {
    if (info.data && Array.isArray(info.data) && info.data.length) {
      d = info.data[0];
    } else if (info.data && info.data.pageData && info.data.pageData.length) {
      d = info.data.pageData[0];
    }
  }
  if (d) {
    console.log('\n[1] DEVICE INFO');
    console.log('  padCode:', d.padCode);
    console.log('  padStatus:', d.padStatus, '(' + (d.padStatus === 10 ? 'Running' : d.padStatus === 11 ? 'Booting' : d.padStatus === 14 ? 'Stopped' : 'Other') + ')');
    console.log('  padModel:', d.padModel || '(not set)');
    console.log('  padType:', d.padType);
    console.log('  imageVersion:', d.imageVersion);
    console.log('  screenLayout:', d.screenLayoutCode);
    console.log('  apps:', JSON.stringify(d.apps));
    console.log('  deviceIp:', d.deviceIp);
    console.log('  dns:', d.dns);
    console.log('  cbsInfo:', d.cbsInfo);
    console.log('  createTime:', d.createTime);
    if (d.padStatus !== 10) {
      console.log('  *** DEVICE NOT RUNNING - cannot probe further ***');
      process.exit(1);
    }
  } else {
    console.log('Device not found:', JSON.stringify(info));
    process.exit(1);
  }
  await sleep(3500);

  // 2. Build identity
  console.log('\n[2] BUILD IDENTITY');
  const id = await sh(PAD, 'echo "model=$(getprop ro.product.model)"; echo "brand=$(getprop ro.product.brand)"; echo "manufacturer=$(getprop ro.product.manufacturer)"; echo "device=$(getprop ro.product.device)"; echo "name=$(getprop ro.product.name)"; echo "sdk=$(getprop ro.build.version.sdk)"; echo "release=$(getprop ro.build.version.release)"; echo "fingerprint=$(getprop ro.build.fingerprint)"; echo "display=$(getprop ro.build.display.id)"; echo "build_type=$(getprop ro.build.type)"; echo "timezone=$(getprop persist.sys.timezone)"; echo "secure=$(getprop ro.secure)"; echo "debuggable=$(getprop ro.debuggable)"', 20);
  console.log('  ' + (id || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 3. Existing accounts
  console.log('\n[3] EXISTING ACCOUNTS');
  const accts = await sh(PAD, 'dumpsys account 2>/dev/null | head -25', 15);
  console.log('  ' + (accts || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 4. Account DB state
  console.log('\n[4] ACCOUNT DB STATE');
  const dbs = await sh(PAD, 'echo "--- accounts_ce.db ---"; ls -la /data/system_ce/0/accounts_ce.db 2>/dev/null; sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;" 2>/dev/null; echo "--- accounts_de.db ---"; ls -la /data/system_de/0/accounts_de.db 2>/dev/null; sqlite3 /data/system_de/0/accounts_de.db "SELECT name,type FROM accounts;" 2>/dev/null; echo "--- done ---"', 15);
  console.log('  ' + (dbs || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 5. Filesystem paths + existing prefs
  console.log('\n[5] GMS SHARED_PREFS');
  const gmsP = await sh(PAD, 'ls /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null | head -25', 10);
  console.log('  ' + (gmsP || 'EMPTY').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  console.log('\n[6] GSF SHARED_PREFS');
  const gsfP = await sh(PAD, 'ls /data/data/com.google.android.gsf/shared_prefs/ 2>/dev/null | head -10', 10);
  console.log('  ' + (gsfP || 'EMPTY').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  console.log('\n[7] VENDING SHARED_PREFS');
  const venP = await sh(PAD, 'ls /data/data/com.android.vending/shared_prefs/ 2>/dev/null | head -10', 10);
  console.log('  ' + (venP || 'EMPTY').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 6. Package UIDs
  console.log('\n[8] PACKAGE UIDs');
  const uids = await sh(PAD, 'stat -c "GMS=%u:%g" /data/data/com.google.android.gms/ 2>/dev/null; stat -c "GSF=%u:%g" /data/data/com.google.android.gsf/ 2>/dev/null; stat -c "Vending=%u:%g" /data/data/com.android.vending/ 2>/dev/null; stat -c "Chrome=%u:%g" /data/data/com.android.chrome/ 2>/dev/null; stat -c "Gmail=%u:%g" /data/data/com.google.android.gm/ 2>/dev/null; stat -c "YouTube=%u:%g" /data/data/com.google.android.youtube/ 2>/dev/null; stat -c "Maps=%u:%g" /data/data/com.google.android.apps.maps/ 2>/dev/null; stat -c "WalletNFC=%u:%g" /data/data/com.google.android.apps.walletnfcrel/ 2>/dev/null', 15);
  console.log('  ' + (uids || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 7. system_ce/0 contents
  console.log('\n[9] SYSTEM_CE DIRECTORY');
  const sce = await sh(PAD, 'ls -la /data/system_ce/0/ 2>/dev/null | head -20', 10);
  console.log('  ' + (sce || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 8. iptables + network
  console.log('\n[10] IPTABLES STATE');
  const ipt = await sh(PAD, 'iptables -L OUTPUT -n 2>/dev/null | head -15', 10);
  console.log('  ' + (ipt || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 9. Disk space
  console.log('\n[11] DISK SPACE');
  const df = await sh(PAD, 'df -h /data 2>/dev/null', 10);
  console.log('  ' + (df || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 10. Running processes
  console.log('\n[12] RUNNING GMS PROCESSES');
  const ps = await sh(PAD, 'ps -A 2>/dev/null | grep -E "gms|vending|gsf" | head -12', 10);
  console.log('  ' + (ps || 'none').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // 11. Check existing GMS prefs content
  console.log('\n[13] EXISTING PREFS CONTENT');
  const prefs = await sh(PAD, 'echo "=== device_registration ==="; cat /data/data/com.google.android.gms/shared_prefs/device_registration.xml 2>/dev/null; echo "=== checkin ==="; cat /data/data/com.google.android.gms/shared_prefs/checkin.xml 2>/dev/null; echo "=== finsky ==="; cat /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null; echo "=== gservices ==="; cat /data/data/com.google.android.gsf/shared_prefs/gservices.xml 2>/dev/null; echo "=== COIN ==="; cat /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null; echo "=== end ==="', 20);
  console.log('  ' + (prefs || '').trim().replace(/\n/g, '\n  '));

  // 12. Check Chrome/browser data paths
  console.log('\n[14] BROWSER PATHS');
  await sleep(3500);
  const chr = await sh(PAD, 'ls /data/data/com.android.chrome/app_chrome/Default/ 2>/dev/null | head -15; echo "---"; ls /data/data/com.kiwibrowser.browser/app_chrome/Default/ 2>/dev/null | head -10', 10);
  console.log('  ' + (chr || 'no browser data').trim().replace(/\n/g, '\n  '));

  console.log('\n══════════ PROBE COMPLETE ══════════');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
