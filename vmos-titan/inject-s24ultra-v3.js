/**
 * inject-s24ultra-v3.js — Gmail injection for APP5B54EI0Z1EOEA
 * Two-phase approach:
 *   Phase 1: Write all data files (accounts, registration, prefs)
 *   Phase 2: Restart device so AccountManagerService reads accounts_ce.db at boot
 *   Phase 3: Post-boot hardening (iptables, disable authenticator/sync)
 *
 * UIDs (confirmed post-reset probe):
 *   GMS  = 10036
 *   GSF  = 10036
 *   Vending = 10041
 *   Chrome  = 10058
 */

const https = require('https'), crypto = require('crypto');
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi', SK = 'Q2SgcSwEfuwoedY0cijp6Mce', HOST = 'api.vmoscloud.com';
const PAD = 'APP5B54EI0Z1EOEA';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const GMS_UID  = 10036;
const GSF_UID  = 10036;
const VEND_UID = 10041;

const EMAIL = 'epolusamuel682@gmail.com';
const GAIA_ID = '117055532876027983082';

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
  return { ok: false, out: '[API error ' + r.code + ': ' + r.msg + ']' };
}

// ===== DATA PAYLOADS =====

// accounts_ce.db — SQLite with the Google account
const ACCOUNTS_CE_SQL = `
CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, previous_name TEXT);
CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, key TEXT NOT NULL, value TEXT);
CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, type TEXT NOT NULL, authtoken TEXT);
CREATE TABLE IF NOT EXISTS grants (accounts_id INTEGER, auth_token_type TEXT, uid INTEGER);
CREATE TABLE IF NOT EXISTS shared_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ceDb (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO accounts (_id, name, type) VALUES (1, '${EMAIL}', 'com.google');
INSERT OR REPLACE INTO shared_accounts (_id, name, type) VALUES (1, '${EMAIL}', 'com.google');
INSERT OR REPLACE INTO extras (accounts_id, key, value) VALUES (1, 'gaia_id', '${GAIA_ID}');
`.trim();

// accounts_de.db — device-encrypted accounts store
const ACCOUNTS_DE_SQL = `
CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, previous_name TEXT, last_password_entry_time_millis_epoch INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS authtokentype_to_visibility (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, auth_token_type TEXT NOT NULL, is_visible INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS deDb (key TEXT PRIMARY KEY, value TEXT);
INSERT OR REPLACE INTO accounts (_id, name, type) VALUES (1, '${EMAIL}', 'com.google');
`.trim();

// device_registration.xml — GSF device registration
const DEVICE_REGISTRATION_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <long name="google_services_framework_id" value="4832901745216837401" />
  <long name="deviceId" value="4832901745216837401" />
  <int name="deviceVersion" value="15" />
</map>`;

// CheckinService.xml — GSF checkin
const CHECKIN_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <long name="lastCheckin" value="${Date.now()}" />
  <long name="lastCheckinAndroidId" value="4832901745216837401" />
  <long name="lastCheckinSecurityToken" value="7291038456123789" />
  <boolean name="hasCheckedIn" value="true" />
</map>`;

// COIN.xml — Play Store billing
const COIN_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="billing_preferences_key">${EMAIL}</string>
  <int name="accepted_tos_version" value="8" />
  <boolean name="has_accepted_tos" value="true" />
</map>`;

// gservices.xml — GMS configuration flags
const GSERVICES_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="account_name">${EMAIL}</string>
  <string name="account_type">com.google</string>
  <long name="android_id" value="4832901745216837401" />
  <boolean name="checkin_completed" value="true" />
</map>`;

// finsky.xml — Vending (Play Store) preferences
const FINSKY_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="finsky.logged_in_account">${EMAIL}</string>
  <boolean name="finsky.setup_complete" value="true" />
  <int name="finsky.setup_wizard_launch_count" value="1" />
  <boolean name="finsky.daily_hygiene_has_run" value="true" />
  <boolean name="finsky.tos_accepted" value="true" />
  <int name="finsky.tos_version" value="8" />
</map>`;

// billing prefs for GMS
const BILLING_XML = `<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="billing_account">${EMAIL}</string>
  <boolean name="billing_setup_complete" value="true" />
</map>`;

function b64(s) { return Buffer.from(s).toString('base64'); }

(async () => {
  const results = [];
  let step = 0;

  function log(name, ok, detail) {
    step++;
    const mark = ok ? '✓' : '✗';
    console.log(`[${step}] ${mark} ${name}: ${detail}`);
    results.push({ name, ok, detail });
  }

  // =============================================
  // PHASE 1: Write all data files
  // =============================================
  console.log('\n========== PHASE 1: WRITE DATA ==========\n');

  // 1. Force-stop GMS to prevent interference
  const r1 = await cmd('am force-stop com.google.android.gms && echo STOPPED');
  log('Force-stop GMS', r1.ok && r1.out.includes('STOPPED'), r1.out.trim());
  await sleep(4000);

  // 2. Write accounts_ce.db
  const ceB64 = b64(ACCOUNTS_CE_SQL);
  const r2 = await cmd(`echo '${ceB64}' | base64 -d > /tmp/ce.sql && sqlite3 /data/system_ce/0/accounts_ce.db < /tmp/ce.sql && chown system:system /data/system_ce/0/accounts_ce.db && chmod 600 /data/system_ce/0/accounts_ce.db && restorecon /data/system_ce/0/accounts_ce.db && echo CE_OK`);
  log('accounts_ce.db', r2.ok && r2.out.includes('CE_OK'), r2.out.trim());
  await sleep(4000);

  // 3. Write accounts_de.db
  const deB64 = b64(ACCOUNTS_DE_SQL);
  const r3 = await cmd(`echo '${deB64}' | base64 -d > /tmp/de.sql && sqlite3 /data/system_de/0/accounts_de.db < /tmp/de.sql && chown system:system /data/system_de/0/accounts_de.db && chmod 600 /data/system_de/0/accounts_de.db && restorecon /data/system_de/0/accounts_de.db && echo DE_OK`);
  log('accounts_de.db', r3.ok && r3.out.includes('DE_OK'), r3.out.trim());
  await sleep(4000);

  // 4. Device registration XML
  const regB64 = b64(DEVICE_REGISTRATION_XML);
  const r4 = await cmd(`echo '${regB64}' | base64 -d > /data/data/com.google.android.gsf/shared_prefs/device_registration.xml && chown ${GSF_UID}:${GSF_UID} /data/data/com.google.android.gsf/shared_prefs/device_registration.xml && chmod 660 /data/data/com.google.android.gsf/shared_prefs/device_registration.xml && restorecon /data/data/com.google.android.gsf/shared_prefs/device_registration.xml && echo REG_OK`);
  log('device_registration.xml', r4.ok && r4.out.includes('REG_OK'), r4.out.trim());
  await sleep(4000);

  // 5. CheckinService XML (merge into existing)
  const chkB64 = b64(CHECKIN_XML);
  const r5 = await cmd(`echo '${chkB64}' | base64 -d > /data/data/com.google.android.gsf/shared_prefs/CheckinService.xml && chown ${GSF_UID}:${GSF_UID} /data/data/com.google.android.gsf/shared_prefs/CheckinService.xml && chmod 660 /data/data/com.google.android.gsf/shared_prefs/CheckinService.xml && restorecon /data/data/com.google.android.gsf/shared_prefs/CheckinService.xml && echo CHK_OK`);
  log('CheckinService.xml', r5.ok && r5.out.includes('CHK_OK'), r5.out.trim());
  await sleep(4000);

  // 6. COIN.xml (Play Store billing)
  const coinB64 = b64(COIN_XML);
  const r6 = await cmd(`echo '${coinB64}' | base64 -d > /data/data/com.android.vending/shared_prefs/COIN.xml && chown ${VEND_UID}:${VEND_UID} /data/data/com.android.vending/shared_prefs/COIN.xml && chmod 660 /data/data/com.android.vending/shared_prefs/COIN.xml && restorecon /data/data/com.android.vending/shared_prefs/COIN.xml && echo COIN_OK`);
  log('COIN.xml', r6.ok && r6.out.includes('COIN_OK'), r6.out.trim());
  await sleep(4000);

  // 7. gservices.xml (GMS config)
  const gsvcB64 = b64(GSERVICES_XML);
  const r7 = await cmd(`mkdir -p /data/data/com.google.android.gms/shared_prefs && echo '${gsvcB64}' | base64 -d > /data/data/com.google.android.gms/shared_prefs/gservices.xml && chown ${GMS_UID}:${GMS_UID} /data/data/com.google.android.gms/shared_prefs/gservices.xml && chmod 660 /data/data/com.google.android.gms/shared_prefs/gservices.xml && restorecon /data/data/com.google.android.gms/shared_prefs/gservices.xml && echo GSVC_OK`);
  log('gservices.xml', r7.ok && r7.out.includes('GSVC_OK'), r7.out.trim());
  await sleep(4000);

  // 8. finsky.xml (Play Store prefs)
  const finB64 = b64(FINSKY_XML);
  const r8 = await cmd(`echo '${finB64}' | base64 -d > /data/data/com.android.vending/shared_prefs/finsky.xml && chown ${VEND_UID}:${VEND_UID} /data/data/com.android.vending/shared_prefs/finsky.xml && chmod 660 /data/data/com.android.vending/shared_prefs/finsky.xml && restorecon /data/data/com.android.vending/shared_prefs/finsky.xml && echo FIN_OK`);
  log('finsky.xml', r8.ok && r8.out.includes('FIN_OK'), r8.out.trim());
  await sleep(4000);

  // 9. Billing preferences in GMS
  const bilB64 = b64(BILLING_XML);
  const r9 = await cmd(`echo '${bilB64}' | base64 -d > /data/data/com.google.android.gms/shared_prefs/billing.xml && chown ${GMS_UID}:${GMS_UID} /data/data/com.google.android.gms/shared_prefs/billing.xml && chmod 660 /data/data/com.google.android.gms/shared_prefs/billing.xml && restorecon /data/data/com.google.android.gms/shared_prefs/billing.xml && echo BIL_OK`);
  log('billing.xml', r9.ok && r9.out.includes('BIL_OK'), r9.out.trim());
  await sleep(4000);

  // Verify files
  console.log('\n--- Verification ---');
  const v1 = await cmd("sqlite3 /data/system_ce/0/accounts_ce.db \"SELECT name,type FROM accounts;\"");
  console.log('accounts_ce check:', v1.out.trim());
  await sleep(4000);

  const v2 = await cmd("sqlite3 /data/system_de/0/accounts_de.db \"SELECT name,type FROM accounts;\"");
  console.log('accounts_de check:', v2.out.trim());
  await sleep(4000);

  const v3 = await cmd("cat /data/data/com.google.android.gsf/shared_prefs/device_registration.xml | grep google_services");
  console.log('device_reg check:', v3.out.trim());
  await sleep(4000);

  // =============================================
  // PHASE 2: Restart device for AccountManager
  // =============================================
  console.log('\n========== PHASE 2: RESTART FOR ACCOUNTMANAGER ==========\n');

  const filesPassed = results.filter(r => r.ok).length;
  if (filesPassed < 7) {
    console.log(`Only ${filesPassed}/9 files written. Aborting restart.`);
    process.exit(1);
  }

  console.log('Restarting device via API...');
  const restart = await vpost('/vcpcloud/api/padApi/restart', { padCodes: [PAD] });
  console.log('Restart:', restart.code, restart.msg);

  if (restart.code !== 200) {
    console.log('Restart failed! Cannot proceed.');
    process.exit(1);
  }

  // Wait for boot cycle
  let sawBooting = false;
  for (let i = 0; i < 30; i++) {
    await sleep(10000);
    const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
    let s = 0;
    if (info.data && info.data.pageData && info.data.pageData.length) s = info.data.pageData[0].padStatus;
    const label = s === 10 ? 'Running' : s === 11 ? 'Booting' : s === 12 ? 'Resetting' : s === 14 ? 'Stopped' : 'Unknown(' + s + ')';
    process.stdout.write('[' + ((i + 1) * 10) + 's] ' + label);

    if (s === 11 || s === 12) {
      sawBooting = true;
      console.log('');
    } else if (s === 10 && sawBooting) {
      console.log(' -> Booted!');
      break;
    } else {
      console.log('');
    }
  }

  // Wait for CBS initialization (learned: 120s minimum needed)
  console.log('Waiting 150s for full CBS initialization...');
  await sleep(150000);

  // Test
  const bootTest = await cmd('echo ALIVE && id');
  if (!bootTest.ok) {
    console.log('Device not ready after restart:', bootTest.out);
    // Try waiting more
    console.log('Waiting additional 60s...');
    await sleep(60000);
    const bootTest2 = await cmd('echo ALIVE && id');
    if (!bootTest2.ok) {
      console.log('Device still not ready. Aborting.');
      process.exit(1);
    }
  }
  console.log('Device ready:', bootTest.out.trim());
  await sleep(4000);

  // =============================================
  // PHASE 3: Post-boot hardening
  // =============================================
  console.log('\n========== PHASE 3: POST-BOOT HARDENING ==========\n');

  // 10. Check AccountManager
  const acctCheck = await cmd('dumpsys account 2>/dev/null | head -5');
  console.log('AccountManager:', acctCheck.out.trim());
  await sleep(4000);

  // 11. Apply iptables DROP rules for GMS
  const r10 = await cmd(`iptables -C OUTPUT -m owner --uid-owner ${GMS_UID} -j DROP 2>/dev/null || iptables -A OUTPUT -m owner --uid-owner ${GMS_UID} -j DROP && echo IPT_OK`);
  log('iptables GMS DROP', r10.ok && r10.out.includes('IPT_OK'), r10.out.trim());
  await sleep(4000);

  // 12. Disable authenticator service
  const r11 = await cmd('pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticatorService 2>&1 && echo AUTH_DIS');
  log('Disable authenticator', r11.ok && r11.out.includes('AUTH_DIS'), r11.out.trim());
  await sleep(4000);

  // 13. Disable sync adapters
  const r12 = await cmd('pm disable com.google.android.gms/com.google.android.gms.auth.be.accountsync.AccountSyncService 2>&1; pm disable com.google.android.gms/com.google.android.gms.auth.be.accountsync.PeopleAccountDiffSyncService 2>&1; echo SYNC_DIS');
  log('Disable sync', r12.ok && r12.out.includes('SYNC_DIS'), r12.out.trim());
  await sleep(4000);

  // 14. Verify iptables rules
  const iptV = await cmd('iptables -L OUTPUT -n 2>/dev/null');
  console.log('iptables rules:', iptV.out.trim());
  await sleep(4000);

  // 15. Final account verification
  const finalAcct = await cmd('dumpsys account 2>/dev/null | head -15');
  console.log('\nFinal account status:');
  console.log(finalAcct.out.trim());

  // Summary
  console.log('\n========== SUMMARY ==========');
  const passed = results.filter(r => r.ok).length;
  const total = results.length;
  console.log(`${passed}/${total} operations succeeded`);
  results.forEach(r => console.log(`  ${r.ok ? '✓' : '✗'} ${r.name}`));

  if (passed === total) {
    console.log('\nINJECTION COMPLETE — All targets deployed successfully.');
  } else {
    console.log('\nWARNING — Some targets failed. Review above output.');
  }
})().catch(e => console.error('Fatal:', e.message));
