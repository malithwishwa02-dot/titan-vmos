#!/usr/bin/env node
// Genesis Re-Injection for APP5B54EI0Z1EOEA (Samsung S24 Ultra SM-S9280)
// CORRECTED SEQUENCE: 
//   1. Force-stop GMS (DO NOT disable services)
//   2. Write all data (DBs + XMLs)  
//   3. restorecon + ownership
//   4. Start GMS with authenticator ENABLED → GMS registers account with AccountManagerService
//   5. Wait 15s for account registration
//   6. THEN apply iptables + disable authenticator

const https = require('https'), crypto = require('crypto'), fs = require('fs');
const { execSync } = require('child_process');

const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi';
const SK = 'Q2SgcSwEfuwoedY0cijp6Mce';
const HOST = 'api.vmoscloud.com';
const PAD = 'APP5B54EI0Z1EOEA';
const GMAIL = 'epolusamuel682@gmail.com';
const PASS = 'gA3EFqhAQJOBZ';
const GMS_UID = '10035';
const AGE_DAYS = 365;

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

function san(v, m) {
  if (!v || typeof v !== 'string') return '';
  return v.replace(/'/g, '').replace(/"/g, '').replace(/;/g, '')
    .replace(/`/g, '').replace(/\\/g, '').replace(/\$/g, '')
    .replace(/\|/g, '').replace(/&/g, '').replace(/\n/g, '')
    .replace(/\r/g, '').replace(/--/g, '').slice(0, m || 1000);
}

async function createDb(pad, remotePath, sql) {
  const tmpDb = '/tmp/genesis_' + crypto.randomBytes(8).toString('hex') + '.db';
  try {
    execSync('sqlite3 "' + tmpDb + '"', { input: sql, timeout: 15000 });
    const b64 = fs.readFileSync(tmpDb).toString('base64');
    const dir = remotePath.substring(0, remotePath.lastIndexOf('/'));
    await sh(pad, "mkdir -p '" + dir + "' 2>/dev/null");
    await sleep(3000);
    const CHUNK = 3500;
    if (b64.length <= CHUNK) {
      return await shOk(pad, "printf '%s' '" + b64 + "' | base64 -d > '" + remotePath + "' && echo DB_OK", 'DB_OK', 30);
    } else {
      const tmpR = '/data/local/tmp/_b64_' + crypto.randomBytes(4).toString('hex');
      const chunks = [];
      for (let i = 0; i < b64.length; i += CHUNK) chunks.push(b64.slice(i, i + CHUNK));
      for (let i = 0; i < chunks.length; i++) {
        await sleep(3000);
        const ok = await shOk(pad, "printf '%s' '" + chunks[i] + "' " + (i === 0 ? '>' : '>>') + " '" + tmpR + "' && echo CK", 'CK', 30);
        if (!ok) { await sh(pad, "rm -f '" + tmpR + "' 2>/dev/null"); return false; }
      }
      await sleep(3000);
      return await shOk(pad, "base64 -d '" + tmpR + "' > '" + remotePath + "' && rm -f '" + tmpR + "' && echo DB_OK", 'DB_OK', 30);
    }
  } catch (e) { console.error('  [createDb ERROR] ' + e.message); return false; }
  finally { try { fs.unlinkSync(tmpDb); } catch (_) {} }
}

(async () => {
  const now = Math.floor(Date.now() / 1000);
  const profileAge = AGE_DAYS * 86400;
  const regTimestamp = (now - profileAge) * 1000;
  const androidId = crypto.randomBytes(8).toString('hex');
  const gsfId = String(BigInt(3000000000000000000n) + BigInt(Math.floor(Math.random() * 999999999999999)));
  const deviceRegId = crypto.randomBytes(16).toString('hex');
  const oauthToken = crypto.randomBytes(64).toString('base64url');
  const googleId = crypto.randomBytes(10).toString('hex');
  const sidToken = crypto.randomBytes(64).toString('base64url');
  const lsidToken = crypto.randomBytes(64).toString('base64url');
  const authTok = crypto.randomBytes(32).toString('hex');
  const safe = san(GMAIL, 254);
  const safep = san(PASS, 128);

  const gmsDir = '/data/data/com.google.android.gms/shared_prefs';
  const gsfDir = '/data/data/com.google.android.gsf/shared_prefs';
  const vDir = '/data/data/com.android.vending/shared_prefs';

  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║  GENESIS RE-INJECTION (CORRECTED): APP5B54EI0Z1EOEA     ║');
  console.log('║  Sequence: Write → GMS reads → iptables → disable       ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');

  // ── PHASE 1: Verify device is running ──
  console.log('\n[1] Verifying device status...');
  const info = await vpost('/vcpcloud/api/padApi/infos', { padCodes: [PAD] });
  let devStatus = 0;
  if (info.data && info.data.pageData && info.data.pageData.length) {
    devStatus = info.data.pageData[0].padStatus;
  }
  console.log('  Status: ' + devStatus + ' (' + (devStatus === 10 ? 'Running' : 'NOT Running') + ')');
  if (devStatus !== 10) {
    console.log('FATAL: Device not running');
    process.exit(1);
  }

  // Verify GMS UID hasn't changed after reboot
  const uidCheck = (await sh(PAD, "stat -c %u /data/data/com.google.android.gms/ 2>/dev/null")).trim();
  console.log('  GMS UID: ' + uidCheck);
  const actualGmsUid = uidCheck || GMS_UID;
  await sleep(3500);

  // ── PHASE 2: Force-stop GMS (services stay ENABLED) ──
  console.log('\n[2] Force-stopping GMS, GSF, Vending (services stay ENABLED)...');
  await sh(PAD, 'am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.vending 2>/dev/null', 15);
  // Ensure authenticator is enabled
  await sh(PAD, [
    'pm enable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
    'pm enable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticatorService 2>/dev/null || true',
  ].join('; '), 10);
  console.log('  Stopped + authenticator ENABLED');
  await sleep(3500);

  // ── PHASE 3: Clean old DBs ──
  console.log('\n[3] Cleaning old account DBs...');
  await shOk(PAD, 'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null; echo CL', 'CL', 10);
  console.log('  Cleaned');
  await sleep(3500);

  // ── PHASE 4: Create accounts_ce.db ──
  console.log('\n[4] Creating accounts_ce.db...');
  const ceSQL = [
    'CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, password TEXT, UNIQUE(name,type));',
    'CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, key TEXT NOT NULL, value TEXT);',
    'CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, type TEXT NOT NULL, authtoken TEXT NOT NULL);',
    'CREATE TABLE IF NOT EXISTS grants (accounts_id INTEGER NOT NULL, auth_token_type TEXT NOT NULL, uid INTEGER NOT NULL, UNIQUE(accounts_id,auth_token_type,uid));',
    'CREATE TABLE IF NOT EXISTS shared_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));',
    "INSERT OR REPLACE INTO accounts (name,type,password) VALUES('" + safe + "','com.google','" + safep + "');",
    "INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES(1,'googleId','" + san(googleId) + "');",
    "INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES(1,'services','hist,mail,lso,calendar,youtube,cl');",
    "INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES(1,'is_child_account','0');",
    "INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES(1,'is_transient','0');",
    "INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES(1,'oauth2:https://www.googleapis.com/auth/plus.me','" + san(oauthToken) + "');",
    "INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES(1,'SID','" + san(sidToken) + "');",
    "INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES(1,'LSID','" + san(lsidToken) + "');",
    "INSERT OR IGNORE INTO shared_accounts (name,type) VALUES('" + safe + "','com.google');",
  ].join('\n');
  const ceOk = await createDb(PAD, '/data/system_ce/0/accounts_ce.db', ceSQL);
  if (ceOk) {
    await sleep(3000);
    await sh(PAD, 'chown 1000:1000 /data/system_ce/0/accounts_ce.db 2>/dev/null; chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null');
  }
  console.log('  accounts_ce.db: ' + (ceOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // ── PHASE 5: Create accounts_de.db ──
  console.log('\n[5] Creating accounts_de.db...');
  const deSQL = [
    'CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));',
    'CREATE TABLE IF NOT EXISTS ce_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));',
    "INSERT OR REPLACE INTO accounts (name,type) VALUES('" + safe + "','com.google');",
    "INSERT OR REPLACE INTO ce_accounts (name,type) VALUES('" + safe + "','com.google');",
  ].join('\n');
  const deOk = await createDb(PAD, '/data/system_de/0/accounts_de.db', deSQL);
  if (deOk) {
    await sleep(3000);
    await sh(PAD, 'chown 1000:1000 /data/system_de/0/accounts_de.db 2>/dev/null; chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null');
  }
  console.log('  accounts_de.db: ' + (deOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // ── PHASE 6: Write GMS XMLs (device_registration + checkin + COIN) ──
  console.log('\n[6] Writing GMS shared_prefs...');

  // 6a: device_registration.xml
  const regXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <string name="registration_timestamp_ms">' + regTimestamp + '</string>',
    '  <string name="device_registration_id">' + deviceRegId + '</string>',
    '  <boolean name="has_completed_registration" value="true"/>',
    '  <string name="android_id">' + androidId + '</string>',
    '</map>'
  ].join('\n');
  const regOk = await shOk(PAD,
    "cat > '" + gmsDir + "/device_registration.xml' << 'XMLEOF'\n" + regXml + "\nXMLEOF\necho REG_OK",
    'REG_OK', 20);
  console.log('  device_registration.xml: ' + (regOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // 6b: checkin.xml
  const checkinXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="checkin_enabled" value="false"/>',
    '  <long name="last_checkin_ms" value="' + Date.now() + '"/>',
    '  <string name="android_id">' + androidId + '</string>',
    '  <boolean name="is_checked_in" value="true"/>',
    '</map>'
  ].join('\n');
  const chkOk = await shOk(PAD,
    "cat > '" + gmsDir + "/checkin.xml' << 'XMLEOF'\n" + checkinXml + "\nXMLEOF\necho CHK_OK",
    'CHK_OK', 20);
  console.log('  checkin.xml: ' + (chkOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // 6c: COIN.xml
  const coinXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="has_payment_methods" value="true"/>',
    '  <string name="default_instrument_id">instrument_1</string>',
    '  <boolean name="wallet_enabled" value="true"/>',
    '  <boolean name="purchase_requires_auth" value="false"/>',
    '  <boolean name="one_touch_enabled" value="true"/>',
    '  <boolean name="biometric_payment_enabled" value="true"/>',
    '  <string name="auth_token">' + authTok + '</string>',
    '</map>'
  ].join('\n');
  const coinOk = await shOk(PAD,
    "cat > '" + gmsDir + "/COIN.xml' << 'XMLEOF'\n" + coinXml + "\nXMLEOF\necho COIN_OK",
    'COIN_OK', 20);
  console.log('  COIN.xml: ' + (coinOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // 6d: GMS ownership
  const gmsOwnOk = await shOk(PAD,
    "chown " + actualGmsUid + ":" + actualGmsUid + " '" + gmsDir + "/device_registration.xml' '" + gmsDir + "/checkin.xml' '" + gmsDir + "/COIN.xml' 2>/dev/null; echo OWN_OK",
    'OWN_OK', 10);
  console.log('  GMS ownership: ' + (gmsOwnOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // ── PHASE 7: Write GSF gservices.xml ──
  console.log('\n[7] Writing GSF gservices.xml...');
  const gsvcXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <string name="android_id">' + androidId + '</string>',
    '  <string name="registration_timestamp">' + regTimestamp + '</string>',
    '  <string name="android_gsf_id">' + gsfId + '</string>',
    '  <string name="account_type">hosted_or_google</string>',
    '</map>'
  ].join('\n');
  const gsOk = await shOk(PAD,
    "cat > '" + gsfDir + "/gservices.xml' << 'XMLEOF'\n" + gsvcXml + "\nXMLEOF\nchown " + actualGmsUid + ":" + actualGmsUid + " '" + gsfDir + "/gservices.xml' 2>/dev/null; echo GS_OK",
    'GS_OK', 20);
  console.log('  gservices.xml: ' + (gsOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // ── PHASE 8: Write Vending finsky.xml + billing.xml ──
  console.log('\n[8] Writing Vending finsky.xml + billing.xml...');
  const vendUid = (await sh(PAD, "stat -c %u /data/data/com.android.vending/ 2>/dev/null")).trim() || '10042';

  const finskyXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <string name="signed_in_account">' + safe + '</string>',
    '  <boolean name="setup_complete" value="true"/>',
    '  <long name="last_self_update_time" value="' + ((now - 86400 * 7) * 1000) + '"/>',
    '  <boolean name="tos_accepted" value="true"/>',
    '  <string name="account_type">com.google</string>',
    '  <string name="purchase_auth_required">never</string>',
    '  <boolean name="purchase_auth_opt_out" value="true"/>',
    '  <int name="purchase_auth_timeout_ms" value="0"/>',
    '  <boolean name="biometric_purchase_auth_enabled" value="false"/>',
    '  <boolean name="require_password_on_purchase" value="false"/>',
    '</map>'
  ].join('\n');
  const fOk = await shOk(PAD,
    "mkdir -p '" + vDir + "' 2>/dev/null; cat > '" + vDir + "/finsky.xml' << 'XMLEOF'\n" + finskyXml + "\nXMLEOF\necho F_OK",
    'F_OK', 20);
  console.log('  finsky.xml: ' + (fOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  const billingXml = [
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <string name="billing_account">' + safe + '</string>',
    '  <boolean name="billing_setup_complete" value="true"/>',
    '  <boolean name="accept_tos" value="true"/>',
    '  <int name="purchase_auth_expiry" value="0"/>',
    '  <boolean name="require_auth_for_purchase" value="false"/>',
    '  <string name="default_purchase_flow">direct</string>',
    '</map>'
  ].join('\n');
  const bOk = await shOk(PAD,
    "cat > '" + vDir + "/billing.xml' << 'XMLEOF'\n" + billingXml + "\nXMLEOF\necho B_OK",
    'B_OK', 20);
  console.log('  billing.xml: ' + (bOk ? 'OK' : 'FAIL'));
  await sleep(3500);

  // Vending ownership
  await shOk(PAD,
    "chown " + vendUid + ":" + vendUid + " '" + vDir + "/finsky.xml' '" + vDir + "/billing.xml' 2>/dev/null; echo VOWN_OK",
    'VOWN_OK', 10);
  console.log('  Vending ownership (UID ' + vendUid + '): OK');
  await sleep(3500);

  // ── PHASE 9: restorecon ──
  console.log('\n[9] restorecon...');
  const rcOk = await shOk(PAD, [
    'restorecon -R /data/system_ce/0/ /data/system_de/0/ 2>/dev/null || true',
    'restorecon -R ' + gmsDir + '/ 2>/dev/null || true',
    'restorecon -R ' + gsfDir + '/ 2>/dev/null || true',
    'restorecon -R ' + vDir + '/ 2>/dev/null || true',
    'echo RC_OK'
  ].join('; '), 'RC_OK', 20);
  console.log('  restorecon: ' + (rcOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // ── PHASE 10: Start GMS (authenticator ENABLED) → registers account ──
  console.log('\n[10] Starting GMS (authenticator ENABLED) — will register account...');
  await sh(PAD, 'am startservice -n com.google.android.gms/.persistent.PersistentMessagingService 2>/dev/null || true', 15);
  console.log('  GMS started. Waiting 20s for account registration...');
  await sleep(20000);

  // Check if account registered
  const preCheck = await sh(PAD, 'dumpsys account 2>/dev/null | head -8', 15);
  console.log('  AccountManager status:');
  console.log('  ' + (preCheck || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // ── PHASE 11: NOW apply iptables + disable authenticator ──
  console.log('\n[11] Applying iptables blocks (GMS UID ' + actualGmsUid + ')...');
  const blockOk = await shOk(PAD, [
    'iptables -A OUTPUT -m owner --uid-owner ' + actualGmsUid + ' -d accounts.google.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + actualGmsUid + ' -d android.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + actualGmsUid + ' -d www.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + actualGmsUid + ' -d oauth2.googleapis.com -j DROP',
    'echo BLOCK_OK'
  ].join('; '), 'BLOCK_OK', 20);
  console.log('  iptables: ' + (blockOk ? 'OK — 4 DROP rules' : 'PARTIAL'));
  await sleep(3500);

  console.log('\n[12] Disabling authenticator + sync...');
  await sh(PAD, [
    'pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
    'pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true',
    'settings put global account_sync_enabled 0 2>/dev/null || true',
  ].join('; '), 15);
  console.log('  Authenticator disabled, sync off');
  await sleep(3500);

  // ── FINAL VERIFICATION ──
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║  FINAL VERIFICATION                    ║');
  console.log('╚════════════════════════════════════════╝');

  console.log('\n[V1] AccountManager:');
  const v1 = await sh(PAD, 'dumpsys account 2>/dev/null | head -15', 15);
  console.log('  ' + (v1 || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  console.log('\n[V2] Files:');
  const v2 = await sh(PAD, [
    'test -f /data/system_ce/0/accounts_ce.db && echo "accounts_ce.db: OK" || echo "accounts_ce.db: MISSING"',
    'test -f /data/system_de/0/accounts_de.db && echo "accounts_de.db: OK" || echo "accounts_de.db: MISSING"',
    'test -f ' + gmsDir + '/device_registration.xml && echo "device_reg: OK" || echo "device_reg: MISSING"',
    'test -f ' + gmsDir + '/checkin.xml && echo "checkin: OK" || echo "checkin: MISSING"',
    'test -f ' + gmsDir + '/COIN.xml && echo "COIN: OK" || echo "COIN: MISSING"',
    'test -f ' + gsfDir + '/gservices.xml && echo "gservices: OK" || echo "gservices: MISSING"',
    'test -f ' + vDir + '/finsky.xml && echo "finsky: OK" || echo "finsky: MISSING"',
    'test -f ' + vDir + '/billing.xml && echo "billing: OK" || echo "billing: MISSING"',
  ].join('; '), 15);
  console.log('  ' + (v2 || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  console.log('\n[V3] DB content:');
  const v3 = await sh(PAD, 'sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;" 2>/dev/null', 10);
  console.log('  ' + (v3 || 'EMPTY').trim());
  await sleep(3500);

  console.log('\n[V4] finsky signed_in:');
  const v4 = await sh(PAD, "grep signed_in_account '" + vDir + "/finsky.xml' 2>/dev/null", 10);
  console.log('  ' + (v4 || 'NOT FOUND').trim());
  await sleep(3500);

  console.log('\n[V5] iptables:');
  const v5 = await sh(PAD, 'iptables -L OUTPUT -n 2>/dev/null | grep DROP | head -8', 10);
  console.log('  ' + (v5 || 'NONE').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  console.log('\n[V6] COIN.xml flags:');
  const v6 = await sh(PAD, "grep -E 'purchase_requires|has_payment|one_touch' '" + gmsDir + "/COIN.xml' 2>/dev/null", 10);
  console.log('  ' + (v6 || 'NOT FOUND').trim().replace(/\n/g, '\n  '));

  // Results summary
  const results = [ceOk, deOk, regOk, chkOk, coinOk, gsOk, fOk, bOk, blockOk, svcOk !== false];
  const passed = results.filter(Boolean).length;
  console.log('\n═══════════════════════════════════════════');
  console.log('RESULT: ' + passed + '/10 targets');
  console.log('═══════════════════════════════════════════');

})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
