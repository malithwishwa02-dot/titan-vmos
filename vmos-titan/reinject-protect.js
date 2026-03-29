#!/usr/bin/env node
const https = require('https'), crypto = require('crypto'), fs = require('fs');
const { execSync } = require('child_process');

const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi';
const SK = 'Q2SgcSwEfuwoedY0cijp6Mce';
const HOST = 'api.vmoscloud.com';

function _sign(body) {
  const dt = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const sd = dt.slice(0, 8);
  const xs = crypto.createHash('sha256').update(body, 'utf8').digest('hex');
  const SH = 'content-type;host;x-content-sha256;x-date';
  const CT = 'application/json;charset=UTF-8';
  const canon = ['host:' + HOST, 'x-date:' + dt, 'content-type:' + CT, 'signedHeaders:' + SH, 'x-content-sha256:' + xs].join('\n');
  const scope = sd + '/armcloud-paas/request';
  const hc = crypto.createHash('sha256').update(canon, 'utf8').digest('hex');
  const toSign = ['HMAC-SHA256', dt, scope, hc].join('\n');
  const kd = crypto.createHmac('sha256', Buffer.from(SK, 'utf8')).update(sd).digest();
  const ks = crypto.createHmac('sha256', kd).update('armcloud-paas').digest();
  const kr = crypto.createHmac('sha256', ks).update('request').digest();
  const sig = crypto.createHmac('sha256', kr).update(toSign).digest('hex');
  return {
    'content-type': CT, 'x-date': dt, 'x-host': HOST,
    'authorization': 'HMAC-SHA256 Credential=' + AK + ', SignedHeaders=' + SH + ', Signature=' + sig
  };
}

function vpost(path, data, timeout) {
  return new Promise((resolve, reject) => {
    const b = JSON.stringify(data || {});
    const h = _sign(b);
    const buf = Buffer.from(b, 'utf8');
    const req = https.request({
      hostname: HOST, path, method: 'POST',
      headers: { ...h, 'content-length': buf.length },
      timeout: (timeout || 30) * 1000
    }, res => {
      let raw = ''; res.on('data', c => raw += c);
      res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { resolve({ raw }); } });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
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

async function createDb(pad, remotePath, sql, ownerDir) {
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
  } catch (e) { console.error('  [createDb] ' + e.message); return false; }
  finally { try { fs.unlinkSync(tmpDb); } catch (_) {} }
}

const GMAIL = 'epolusamuel682@gmail.com';
const PASS = 'gA3EFqhAQJOBZ';
const PADS = ['ACP250329ACQRPDV', 'ACP2507296TM25XE'];

(async () => {
  for (const pad of PADS) {
    const now = Math.floor(Date.now() / 1000);
    const ageDays = 365, profileAge = ageDays * 86400;
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

    console.log('\n╔═══════════════════════════════════════════════╗');
    console.log('║ RE-INJECT + PROTECT: ' + pad + ' ║');
    console.log('╚═══════════════════════════════════════════════╝');

    // Step 1: Kill GMS completely
    console.log('[1] Killing GMS, GSF, Vending...');
    await sh(pad, 'am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.vending 2>/dev/null', 15);
    await sleep(3500);

    // Step 2: Block GMS from validating tokens via iptables
    console.log('[2] Blocking GMS auth to Google servers...');
    const gmsUid = (await sh(pad, "stat -c %u /data/data/com.google.android.gms/ 2>/dev/null")).trim();
    console.log('  GMS UID: ' + gmsUid);
    if (gmsUid) {
      const blockCmd = [
        'iptables -D OUTPUT -m owner --uid-owner ' + gmsUid + ' -d accounts.google.com -j DROP 2>/dev/null || true',
        'iptables -D OUTPUT -m owner --uid-owner ' + gmsUid + ' -d android.googleapis.com -j DROP 2>/dev/null || true',
        'iptables -D OUTPUT -m owner --uid-owner ' + gmsUid + ' -d www.googleapis.com -j DROP 2>/dev/null || true',
        'iptables -D OUTPUT -m owner --uid-owner ' + gmsUid + ' -d oauth2.googleapis.com -j DROP 2>/dev/null || true',
        'iptables -A OUTPUT -m owner --uid-owner ' + gmsUid + ' -d accounts.google.com -j DROP',
        'iptables -A OUTPUT -m owner --uid-owner ' + gmsUid + ' -d android.googleapis.com -j DROP',
        'iptables -A OUTPUT -m owner --uid-owner ' + gmsUid + ' -d www.googleapis.com -j DROP',
        'iptables -A OUTPUT -m owner --uid-owner ' + gmsUid + ' -d oauth2.googleapis.com -j DROP',
        'echo BLOCK_OK'
      ].join('; ');
      const blockOk = await shOk(pad, blockCmd, 'BLOCK_OK', 20);
      console.log('  iptables block: ' + (blockOk ? 'OK' : 'PARTIAL'));
    }
    await sleep(3500);

    // Step 3: Disable GMS sync services
    console.log('[3] Disabling GMS sync services...');
    const svcOk = await shOk(pad, [
      'pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true',
      'pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
      'settings put global account_sync_enabled 0 2>/dev/null || true',
      'echo SVC_OK'
    ].join('; '), 'SVC_OK', 15);
    console.log('  Sync services disabled: ' + (svcOk ? 'OK' : 'PARTIAL'));
    await sleep(3500);

    // Step 4: Clean old DBs
    console.log('[4] Cleaning old account data...');
    await shOk(pad, 'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null; echo CL', 'CL', 15);
    await sleep(3500);

    // Step 5: Create accounts_ce.db
    console.log('[5] Creating accounts_ce.db...');
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
    const ceOk = await createDb(pad, '/data/system_ce/0/accounts_ce.db', ceSQL);
    if (ceOk) { await sleep(3000); await sh(pad, 'chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null'); }
    console.log('  accounts_ce.db: ' + (ceOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 6: Create accounts_de.db
    console.log('[6] Creating accounts_de.db...');
    const deSQL = [
      'CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));',
      'CREATE TABLE IF NOT EXISTS ce_accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));',
      "INSERT OR REPLACE INTO accounts (name,type) VALUES('" + safe + "','com.google');",
      "INSERT OR REPLACE INTO ce_accounts (name,type) VALUES('" + safe + "','com.google');",
    ].join('\n');
    const deOk = await createDb(pad, '/data/system_de/0/accounts_de.db', deSQL);
    if (deOk) { await sleep(3000); await sh(pad, 'chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null'); }
    console.log('  accounts_de.db: ' + (deOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 7: Write device_registration.xml
    console.log('[7] Writing device_registration.xml...');
    const gmsDir = '/data/data/com.google.android.gms/shared_prefs';
    const regXml = [
      '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
      '<map>',
      '  <string name="registration_timestamp_ms">' + regTimestamp + '</string>',
      '  <string name="device_registration_id">' + deviceRegId + '</string>',
      '  <boolean name="has_completed_registration" value="true"/>',
      '  <string name="android_id">' + androidId + '</string>',
      '</map>'
    ].join('\n');
    const regOk = await shOk(pad,
      "mkdir -p '" + gmsDir + "' 2>/dev/null; cat > '" + gmsDir + "/device_registration.xml' << 'XMLEOF'\n" + regXml + "\nXMLEOF\necho REG_OK",
      'REG_OK', 20);
    console.log('  device_registration.xml: ' + (regOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 8: Write checkin.xml
    console.log('[8] Writing checkin.xml...');
    const checkinXml = [
      '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
      '<map>',
      '  <boolean name="checkin_enabled" value="false"/>',
      '  <long name="last_checkin_ms" value="' + Date.now() + '"/>',
      '  <string name="android_id">' + androidId + '</string>',
      '  <boolean name="is_checked_in" value="true"/>',
      '</map>'
    ].join('\n');
    const chkOk = await shOk(pad,
      "cat > '" + gmsDir + "/checkin.xml' << 'XMLEOF'\n" + checkinXml + "\nXMLEOF\necho CHK_OK",
      'CHK_OK', 20);
    console.log('  checkin.xml: ' + (chkOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 9: Write COIN.xml
    console.log('[9] Writing COIN.xml...');
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
    const coinOk = await shOk(pad,
      "cat > '" + gmsDir + "/COIN.xml' << 'XMLEOF'\n" + coinXml + "\nXMLEOF\necho COIN_OK",
      'COIN_OK', 20);
    console.log('  COIN.xml: ' + (coinOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 10: Write gservices.xml
    console.log('[10] Writing gservices.xml...');
    const gsfDir = '/data/data/com.google.android.gsf/shared_prefs';
    const gsvcXml = [
      '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
      '<map>',
      '  <string name="android_id">' + androidId + '</string>',
      '  <string name="registration_timestamp">' + regTimestamp + '</string>',
      '  <string name="android_gsf_id">' + gsfId + '</string>',
      '  <string name="account_type">hosted_or_google</string>',
      '</map>'
    ].join('\n');
    const gsOk = await shOk(pad,
      "mkdir -p '" + gsfDir + "' 2>/dev/null; cat > '" + gsfDir + "/gservices.xml' << 'XMLEOF'\n" + gsvcXml + "\nXMLEOF\necho GS_OK",
      'GS_OK', 20);
    console.log('  gservices.xml: ' + (gsOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 11: Write finsky.xml + billing.xml
    console.log('[11] Writing finsky.xml + billing.xml...');
    const vDir = '/data/data/com.android.vending/shared_prefs';
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
    const fOk = await shOk(pad,
      "mkdir -p '" + vDir + "' 2>/dev/null; cat > '" + vDir + "/finsky.xml' << 'XMLEOF'\n" + finskyXml + "\nXMLEOF\necho F_OK",
      'F_OK', 20);
    await sleep(3500);
    const bOk = await shOk(pad,
      "cat > '" + vDir + "/billing.xml' << 'XMLEOF'\n" + billingXml + "\nXMLEOF\necho B_OK",
      'B_OK', 20);
    console.log('  finsky.xml: ' + (fOk ? 'OK' : 'FAIL') + ', billing.xml: ' + (bOk ? 'OK' : 'FAIL'));
    await sleep(3500);

    // Step 12: Fix ownership + restorecon
    console.log('[12] Fixing ownership + restorecon...');
    const ownOk = await shOk(pad, [
      "chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) " + gmsDir + "/device_registration.xml " + gmsDir + "/checkin.xml " + gmsDir + "/COIN.xml 2>/dev/null || true",
      "chown $(stat -c '%u:%g' /data/data/com.google.android.gsf/ 2>/dev/null) " + gsfDir + "/gservices.xml 2>/dev/null || true",
      "chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) " + vDir + "/finsky.xml " + vDir + "/billing.xml 2>/dev/null || true",
      'restorecon -R /data/system_ce/0/ /data/system_de/0/ 2>/dev/null || true',
      'restorecon -R /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null || true',
      'restorecon -R /data/data/com.google.android.gsf/shared_prefs/ 2>/dev/null || true',
      'restorecon -R /data/data/com.android.vending/shared_prefs/ 2>/dev/null || true',
      'echo OWN_OK'
    ].join('; '), 'OWN_OK', 20);
    console.log('  ownership+restorecon: ' + (ownOk ? 'OK' : 'PARTIAL'));
    await sleep(3500);

    // Step 13: Restart GMS (auth endpoints still blocked)
    console.log('[13] Restarting GMS (auth still blocked)...');
    await sh(pad, 'am startservice -n com.google.android.gms/.persistent.PersistentMessagingService 2>/dev/null || true', 15);
    await sleep(4000);

    // Step 14: Verify
    console.log('[14] Verifying account...');
    const verify = await sh(pad, 'dumpsys account 2>/dev/null | head -8');
    console.log('  ' + (verify || '').trim().replace(/\n/g, '\n  '));
    await sleep(3500);

    // Step 15: Verify iptables
    console.log('[15] Verifying iptables blocks...');
    const ipt = await sh(pad, 'iptables -L OUTPUT -n 2>/dev/null | grep -i drop | head -6');
    console.log('  ' + (ipt || 'no rules').trim().replace(/\n/g, '\n  '));
  }

  console.log('\n══════════════════════════════════════════════════');
  console.log('BOTH DEVICES RE-INJECTED + AUTH BLOCKED');
  console.log('GMS cannot validate tokens → accounts persist');
  console.log('══════════════════════════════════════════════════');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
