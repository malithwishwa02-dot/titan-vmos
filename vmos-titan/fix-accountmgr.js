#!/usr/bin/env node
// Fix AccountManager cache for APP5B54EI0Z1EOEA
// Problem: accounts_ce.db has the account but system_server hasn't read it
// Solution: Re-enable GMS auth, restart device so system_server reads DB at boot,
//           then re-apply iptables + disable authenticator

const https = require('https'), crypto = require('crypto');
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi', SK = 'Q2SgcSwEfuwoedY0cijp6Mce', HOST = 'api.vmoscloud.com';
const PAD = 'APP5B54EI0Z1EOEA';
const GMS_UID = '10035';

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
      if (r.code !== 200) return '';
      const it = Array.isArray(r.data) ? r.data : [r.data];
      const i = it[0] || {};
      if (i.taskStatus === 3) return i.errorMsg || i.taskResult || '';
      return '';
    } catch (e) { if (a === 1) return ''; await sleep(2000); }
  }
  return '';
}

async function shOk(pad, cmd, marker, sec) {
  const r = await sh(pad, cmd, sec);
  return (r || '').includes(marker);
}

async function waitForRunning(pad, maxWait) {
  const deadline = Date.now() + (maxWait || 300000);
  while (Date.now() < deadline) {
    await sleep(10000);
    const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [pad] });
    let status = 0;
    if (info.data && Array.isArray(info.data) && info.data.length) {
      status = info.data[0].padStatus;
    } else if (info.data && info.data.pageData && info.data.pageData.length) {
      status = info.data.pageData[0].padStatus;
    }
    process.stdout.write('  status=' + status + ' ');
    if (status === 10) {
      console.log('RUNNING!');
      return true;
    }
  }
  console.log('TIMEOUT');
  return false;
}

(async () => {
  console.log('=== FIX ACCOUNTMANAGER CACHE: ' + PAD + ' ===\n');

  // Step 1: Re-enable GMS services before restart
  console.log('[1] Re-enabling GMS authenticator services...');
  await sh(PAD, [
    'pm enable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
    'pm enable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticatorService 2>/dev/null || true',
    'pm enable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true',
  ].join('; '), 15);
  console.log('  Services re-enabled');
  await sleep(3500);

  // Step 2: Verify DB is intact before restart
  console.log('[2] Verifying DB before restart...');
  const dbCheck = await sh(PAD, 'sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;" 2>/dev/null');
  console.log('  DB: ' + (dbCheck || 'EMPTY').trim());
  await sleep(3500);

  // Step 3: Restart device (system_server will re-read accounts_ce.db at boot)
  console.log('[3] Restarting device via API...');
  const restartResult = await vpost('/vcpcloud/api/padApi/restart', { padCode: PAD });
  console.log('  restart API response code:', restartResult.code, restartResult.msg);
  
  if (restartResult.code !== 200) {
    console.log('  Restart failed. Trying alternative...');
    // Try force-stopping system processes to trigger a soft restart
    // Actually, try killing zygote to restart Android
    console.log('[3b] Killing zygote for soft restart...');
    await sh(PAD, 'kill -9 $(pidof zygote64) 2>/dev/null; kill -9 $(pidof zygote) 2>/dev/null', 10);
    console.log('  zygote killed, waiting for recovery...');
  }

  // Step 4: Wait for device to come back online
  console.log('[4] Waiting for device to boot (status=10)...');
  const online = await waitForRunning(PAD, 300000);
  if (!online) {
    console.log('FATAL: Device did not come back online');
    process.exit(1);
  }
  // Give extra time for system_server to fully initialize
  console.log('  Extra 15s for system_server to stabilize...');
  await sleep(15000);

  // Step 5: Apply iptables blocks IMMEDIATELY
  console.log('[5] Applying iptables blocks (GMS UID ' + GMS_UID + ')...');
  const blockOk = await shOk(PAD, [
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d accounts.google.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d android.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d www.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d oauth2.googleapis.com -j DROP',
    'echo BLOCK_OK'
  ].join('; '), 'BLOCK_OK', 20);
  console.log('  iptables: ' + (blockOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // Step 6: Disable authenticator + sync
  console.log('[6] Disabling authenticator + sync...');
  await sh(PAD, [
    'pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
    'pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true',
    'settings put global account_sync_enabled 0 2>/dev/null || true',
  ].join('; '), 15);
  console.log('  Disabled');
  await sleep(3500);

  // Step 7: Final verification
  console.log('\n[7] FINAL VERIFICATION');
  const accts = await sh(PAD, 'dumpsys account 2>/dev/null | head -15', 15);
  console.log('  AccountManager:');
  console.log('  ' + (accts || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  const ipt = await sh(PAD, 'iptables -L OUTPUT -n 2>/dev/null | grep DROP | head -6', 10);
  console.log('\n  iptables DROP rules:');
  console.log('  ' + (ipt || 'NONE').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  const finsky = await sh(PAD, 'grep signed_in_account /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null', 10);
  console.log('\n  finsky.xml: ' + (finsky || 'NOT FOUND').trim());

  const coin = await sh(PAD, 'grep purchase_requires_auth /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null', 10);
  console.log('  COIN.xml: ' + (coin || 'NOT FOUND').trim());

  console.log('\n=== DONE ===');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
