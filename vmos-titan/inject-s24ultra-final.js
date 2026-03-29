/**
 * inject-s24ultra-final.js — Gmail injection for APP5B54EI0Z1EOEA
 * 
 * Handles the sqlite3-missing issue by building DBs locally and
 * pushing as chunked base64 binary blobs.
 * 
 * Three phases:
 *   Phase 1: Push accounts_ce.db + accounts_de.db via chunked b64 + write XML prefs
 *   Phase 2: Restart device so AccountManagerService reads accounts at boot
 *   Phase 3: Post-boot hardening (iptables + disable authenticator)
 * 
 * UIDs (confirmed post-reset):
 *   GMS/GSF = 10036, Vending = 10041, Chrome = 10058
 */

const https = require('https'), crypto = require('crypto'), fs = require('fs');
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi', SK = 'Q2SgcSwEfuwoedY0cijp6Mce', HOST = 'api.vmoscloud.com';
const PAD = 'APP5B54EI0Z1EOEA';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const GMS_UID = 10036, GSF_UID = 10036, VEND_UID = 10041;
const EMAIL = 'epolusamuel682@gmail.com';
const GAIA_ID = '117055532876027983082';
const CHUNK_SIZE = 3000; // base64 chars per chunk (fits in 4KB scriptContent with command overhead)
const CMD_DELAY = 4000;  // 4s between commands

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
      timeout: (t || 60) * 1000
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

async function cmd(script) {
  const r = await vpost('/vcpcloud/api/padApi/syncCmd', { padCode: PAD, scriptContent: script });
  if (r.code === 200) {
    const d = Array.isArray(r.data) ? r.data[0] : r.data;
    return { ok: d && d.taskStatus === 3, out: (d && (d.errorMsg || d.taskResult)) || '' };
  }
  return { ok: false, out: '[API ' + r.code + ': ' + r.msg + ']' };
}

// Push a file to the device via chunked base64
async function pushFile(localB64Path, remotePath, ownerUid, label) {
  const b64 = fs.readFileSync(localB64Path, 'utf8');
  const totalChunks = Math.ceil(b64.length / CHUNK_SIZE);
  console.log(`  Pushing ${label} (${b64.length} b64 chars, ${totalChunks} chunks)...`);

  // Clear staging file
  const staging = '/tmp/' + label.replace(/[^a-zA-Z0-9]/g, '_') + '.b64';
  const r0 = await cmd(`rm -f ${staging} && echo CLEAR`);
  if (!r0.ok) { console.log(`  Failed to clear staging: ${r0.out}`); return false; }
  await sleep(CMD_DELAY);

  // Push chunks
  for (let i = 0; i < totalChunks; i++) {
    const chunk = b64.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    const op = i === 0 ? '>' : '>>';
    const r = await cmd(`printf '%s' '${chunk}' ${op} ${staging} && echo C${i}`);
    if (!r.ok || !r.out.includes('C' + i)) {
      console.log(`  Chunk ${i}/${totalChunks} FAILED: ${r.out}`);
      return false;
    }
    process.stdout.write(`  [${i + 1}/${totalChunks}]`);
    await sleep(CMD_DELAY);
  }
  console.log(' chunks done');

  // Decode + place + own + restorecon
  const r1 = await cmd(`base64 -d ${staging} > ${remotePath} && chown ${ownerUid}:${ownerUid} ${remotePath} && chmod 600 ${remotePath} && restorecon ${remotePath} && ls -la ${remotePath} && echo PLACED`);
  if (!r1.ok || !r1.out.includes('PLACED')) {
    console.log(`  Place failed: ${r1.out}`);
    return false;
  }
  console.log(`  ${r1.out.trim()}`);
  await sleep(CMD_DELAY);

  // Cleanup
  await cmd(`rm -f ${staging}`);
  await sleep(CMD_DELAY);
  return true;
}

function b64(s) { return Buffer.from(s).toString('base64'); }

// XML payloads
const DEVICE_REGISTRATION_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <long name="google_services_framework_id" value="4832901745216837401" />
  <long name="deviceId" value="4832901745216837401" />
  <int name="deviceVersion" value="15" />
</map>`;

const CHECKIN_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <long name="lastCheckin" value="${Date.now()}" />
  <long name="lastCheckinAndroidId" value="4832901745216837401" />
  <long name="lastCheckinSecurityToken" value="7291038456123789" />
  <boolean name="hasCheckedIn" value="true" />
</map>`;

const COIN_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="billing_preferences_key">${EMAIL}</string>
  <int name="accepted_tos_version" value="8" />
  <boolean name="has_accepted_tos" value="true" />
</map>`;

const GSERVICES_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="account_name">${EMAIL}</string>
  <string name="account_type">com.google</string>
  <long name="android_id" value="4832901745216837401" />
  <boolean name="checkin_completed" value="true" />
</map>`;

const FINSKY_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="finsky.logged_in_account">${EMAIL}</string>
  <boolean name="finsky.setup_complete" value="true" />
  <int name="finsky.setup_wizard_launch_count" value="1" />
  <boolean name="finsky.daily_hygiene_has_run" value="true" />
  <boolean name="finsky.tos_accepted" value="true" />
  <int name="finsky.tos_version" value="8" />
</map>`;

const BILLING_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="billing_account">${EMAIL}</string>
  <boolean name="billing_setup_complete" value="true" />
</map>`;

(async () => {
  const results = [];
  let step = 0;
  function log(name, ok, detail) {
    step++;
    console.log(`[${step}] ${ok ? '✓' : '✗'} ${name}: ${detail}`);
    results.push({ name, ok });
  }

  // =============================================
  // PHASE 1: Write all data files
  // =============================================
  console.log('\n========== PHASE 1: WRITE DATA ==========\n');

  // 1. Force-stop GMS
  const r1 = await cmd('am force-stop com.google.android.gms && echo STOPPED');
  log('Force-stop GMS', r1.ok && r1.out.includes('STOPPED'), r1.out.trim());
  await sleep(CMD_DELAY);

  // 2. Push accounts_ce.db (chunked binary — v2 with correct Android 15 schema + user_version=10)
  const ceOk = await pushFile('/tmp/accounts_ce_v2.b64', '/data/system_ce/0/accounts_ce.db', 'system', 'accounts_ce');
  log('accounts_ce.db', ceOk, ceOk ? 'binary push OK' : 'FAILED');

  // 3. Push accounts_de.db (chunked binary — v2 with correct Android 15 schema + user_version=3)
  const deOk = await pushFile('/tmp/accounts_de_v2.b64', '/data/system_de/0/accounts_de.db', 'system', 'accounts_de');
  log('accounts_de.db', deOk, deOk ? 'binary push OK' : 'FAILED');

  // 4-9: XML preferences
  const xmlTargets = [
    { name: 'device_registration.xml', xml: DEVICE_REGISTRATION_XML, path: '/data/data/com.google.android.gsf/shared_prefs/device_registration.xml', uid: GSF_UID },
    { name: 'CheckinService.xml', xml: CHECKIN_XML, path: '/data/data/com.google.android.gsf/shared_prefs/CheckinService.xml', uid: GSF_UID },
    { name: 'COIN.xml', xml: COIN_XML, path: '/data/data/com.android.vending/shared_prefs/COIN.xml', uid: VEND_UID },
    { name: 'gservices.xml', xml: GSERVICES_XML, path: '/data/data/com.google.android.gms/shared_prefs/gservices.xml', uid: GMS_UID },
    { name: 'finsky.xml', xml: FINSKY_XML, path: '/data/data/com.android.vending/shared_prefs/finsky.xml', uid: VEND_UID },
    { name: 'billing.xml', xml: BILLING_XML, path: '/data/data/com.google.android.gms/shared_prefs/billing.xml', uid: GMS_UID },
  ];

  for (const t of xmlTargets) {
    const encoded = b64(t.xml);
    const r = await cmd(`echo '${encoded}' | base64 -d > ${t.path} && chown ${t.uid}:${t.uid} ${t.path} && chmod 660 ${t.path} && restorecon ${t.path} && echo OK`);
    log(t.name, r.ok && r.out.includes('OK'), r.out.trim().slice(0, 100));
    await sleep(CMD_DELAY);
  }

  // Quick verification
  console.log('\n--- Pre-restart verification ---');
  const vCe = await cmd('ls -la /data/system_ce/0/accounts_ce.db');
  console.log('CE file:', vCe.out.trim());
  await sleep(CMD_DELAY);
  const vDe = await cmd('ls -la /data/system_de/0/accounts_de.db');
  console.log('DE file:', vDe.out.trim());
  await sleep(CMD_DELAY);

  // =============================================
  // PHASE 2: Restart for AccountManager
  // =============================================
  const fileOk = results.filter(r => r.ok).length;
  if (fileOk < 7) {
    console.log(`\nOnly ${fileOk}/9 files written. ABORTING.`);
    process.exit(1);
  }

  console.log('\n========== PHASE 2: RESTART ==========\n');
  console.log('Restarting device via API...');
  const restart = await vpost('/vcpcloud/api/padApi/restart', { padCodes: [PAD] });
  console.log('Restart:', restart.code, restart.msg);

  if (restart.code !== 200) {
    console.log('Restart FAILED. Aborting.');
    process.exit(1);
  }

  // Wait for boot cycle
  let sawBooting = false;
  for (let i = 0; i < 30; i++) {
    await sleep(10000);
    const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
    let s = 0;
    if (info.data && info.data.pageData && info.data.pageData.length) s = info.data.pageData[0].padStatus;
    const label = { 10: 'Running', 11: 'Booting', 12: 'Resetting', 14: 'Stopped' }[s] || 'Unknown(' + s + ')';
    process.stdout.write('[' + ((i + 1) * 10) + 's] ' + label);
    if (s === 11 || s === 12) { sawBooting = true; console.log(''); }
    else if (s === 10 && sawBooting) { console.log(' -> Booted!'); break; }
    else { console.log(''); }
  }

  // CBS init wait — 150s proven minimum
  console.log('Waiting 180s for full CBS init...');
  await sleep(180000);

  // Test connectivity
  let ready = false;
  for (let attempt = 0; attempt < 5; attempt++) {
    const t = await cmd('echo ALIVE');
    if (t.ok && t.out.includes('ALIVE')) { ready = true; break; }
    console.log('Not ready yet, waiting 30s more...');
    await sleep(30000);
  }
  if (!ready) {
    console.log('Device not ready after extended wait. Aborting.');
    process.exit(1);
  }
  console.log('Device is READY');
  await sleep(CMD_DELAY);

  // =============================================
  // PHASE 3: Post-boot hardening
  // =============================================
  console.log('\n========== PHASE 3: HARDENING ==========\n');

  // Check AccountManager
  const acct = await cmd('dumpsys account 2>/dev/null | head -20');
  console.log('AccountManager status:');
  console.log(acct.out.trim());
  await sleep(CMD_DELAY);

  // Apply iptables
  const ipt = await cmd(`iptables -C OUTPUT -m owner --uid-owner ${GMS_UID} -j DROP 2>/dev/null || iptables -A OUTPUT -m owner --uid-owner ${GMS_UID} -j DROP && echo IPT_OK`);
  log('iptables GMS DROP', ipt.ok && ipt.out.includes('IPT_OK'), ipt.out.trim());
  await sleep(CMD_DELAY);

  // 12. Disable authenticator (only if accounts visible)
  if (acct.out.includes('Accounts: 1') || acct.out.includes('com.google')) {
    const auth = await cmd('pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticatorService 2>&1 && echo AUTH_DIS');
    log('Disable authenticator', auth.ok && auth.out.includes('AUTH_DIS'), auth.out.trim().slice(0, 120));
    await sleep(CMD_DELAY);
  } else {
    console.log('Skipping authenticator disable — accounts not yet visible');
  }

  // Verify iptables
  const iptV = await cmd('iptables -L OUTPUT -n 2>/dev/null | head -5');
  console.log('iptables:', iptV.out.trim());
  await sleep(CMD_DELAY);

  // Final account check
  const finalAcct = await cmd('dumpsys account 2>/dev/null | head -20');
  console.log('\nFinal account status:');
  console.log(finalAcct.out.trim());

  // =============================================
  // SUMMARY
  // =============================================
  console.log('\n========== SUMMARY ==========');
  const passed = results.filter(r => r.ok).length;
  console.log(`${passed}/${results.length} operations succeeded`);
  results.forEach(r => console.log(`  ${r.ok ? '✓' : '✗'} ${r.name}`));
})().catch(e => console.error('Fatal:', e.message));
