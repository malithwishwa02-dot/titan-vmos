#!/usr/bin/env node
// Genesis Injection for APP5B54EI0Z1EOEA (Samsung S24 Ultra SM-S9280)
// GMS UID=10035, Vending UID=10042, Chrome UID=10060
// Fresh device: 0 accounts, empty prefs, finsky.xml has live Play Store data (MERGE)

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

// ─── API helpers ───
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

// ─── Main injection ───
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

  console.log('╔═══════════════════════════════════════════════════════╗');
  console.log('║  GENESIS INJECTION: APP5B54EI0Z1EOEA (S24 Ultra)     ║');
  console.log('║  Gmail: ' + GMAIL + '                  ║');
  console.log('║  GMS UID: ' + GMS_UID + ' | Age: ' + AGE_DAYS + ' days                        ║');
  console.log('╚═══════════════════════════════════════════════════════╝');

  // ═══ PHASE 1: Kill GMS + GSF + Vending ═══
  console.log('\n[1/10] Killing GMS, GSF, Vending...');
  await sh(PAD, 'am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.vending 2>/dev/null', 15);
  console.log('  Force-stopped all Google services');
  await sleep(3500);

  // ═══ PHASE 2: Block GMS auth endpoints via iptables ═══
  console.log('\n[2/10] Blocking GMS (UID=' + GMS_UID + ') → Google auth servers...');
  const blockCmd = [
    // Delete any existing (idempotent)
    'iptables -D OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d accounts.google.com -j DROP 2>/dev/null || true',
    'iptables -D OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d android.googleapis.com -j DROP 2>/dev/null || true',
    'iptables -D OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d www.googleapis.com -j DROP 2>/dev/null || true',
    'iptables -D OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d oauth2.googleapis.com -j DROP 2>/dev/null || true',
    // Add blocks
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d accounts.google.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d android.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d www.googleapis.com -j DROP',
    'iptables -A OUTPUT -m owner --uid-owner ' + GMS_UID + ' -d oauth2.googleapis.com -j DROP',
    'echo BLOCK_OK'
  ].join('; ');
  const blockOk = await shOk(PAD, blockCmd, 'BLOCK_OK', 20);
  console.log('  iptables: ' + (blockOk ? 'OK — 4 DROP rules applied' : 'PARTIAL'));
  await sleep(3500);

  // ═══ PHASE 3: Disable GMS sync services ═══
  console.log('\n[3/10] Disabling GMS sync services...');
  const svcOk = await shOk(PAD, [
    'pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true',
    'pm disable com.google.android.gms/com.google.android.gms.auth.account.authenticator.GoogleAccountAuthenticator 2>/dev/null || true',
    'settings put global account_sync_enabled 0 2>/dev/null || true',
    'echo SVC_OK'
  ].join('; '), 'SVC_OK', 15);
  console.log('  Checkin + Authenticator disabled, sync off: ' + (svcOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // ═══ PHASE 4: Clean existing empty account DBs ═══
  console.log('\n[4/10] Cleaning existing (empty) account DBs...');
  await shOk(PAD, 'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null; echo CL', 'CL', 10);
  console.log('  Cleaned');
  await sleep(3500);

  // ═══ PHASE 5: Create accounts_ce.db ═══
  console.log('\n[5/10] Creating accounts_ce.db (with OAuth tokens + GAIA ID)...');
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
    // Set correct ownership: system:system (1000:1000) + chmod 600
    await sh(PAD, 'chown 1000:1000 /data/system_ce/0/accounts_ce.db 2>/dev/null; chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null');
  }
  console.log('  accounts_ce.db: ' + (ceOk ? 'OK (5 tables, account + 4 extras + 3 tokens + shared)' : 'FAIL'));
  await sleep(3500);

  // ═══ PHASE 6: Create accounts_de.db ═══
  console.log('\n[6/10] Creating accounts_de.db...');
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
  console.log('  accounts_de.db: ' + (deOk ? 'OK (accounts + ce_accounts)' : 'FAIL'));
  await sleep(3500);

  // ═══ PHASE 7: GMS shared_prefs (device_registration + checkin + COIN) ═══
  console.log('\n[7/10] Writing GMS shared_prefs...');

  // 7a. device_registration.xml
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

  // 7b. checkin.xml (disable checkin to prevent GMS phoning home)
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
  console.log('  checkin.xml: ' + (chkOk ? 'OK (checkin disabled)' : 'FAIL'));
  await sleep(3500);

  // 7c. COIN.xml (6 zero-auth flags as per skill)
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
  console.log('  COIN.xml: ' + (coinOk ? 'OK (6 zero-auth flags)' : 'FAIL'));
  await sleep(3500);

  // 7d. Fix GMS ownership
  const gmsOwnOk = await shOk(PAD,
    "chown " + GMS_UID + ":" + GMS_UID + " '" + gmsDir + "/device_registration.xml' '" + gmsDir + "/checkin.xml' '" + gmsDir + "/COIN.xml' 2>/dev/null; echo OWN_OK",
    'OWN_OK', 10);
  console.log('  GMS ownership (UID ' + GMS_UID + '): ' + (gmsOwnOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // ═══ PHASE 8: GSF gservices.xml ═══
  console.log('\n[8/10] Writing GSF gservices.xml...');
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
    "cat > '" + gsfDir + "/gservices.xml' << 'XMLEOF'\n" + gsvcXml + "\nXMLEOF\nchown " + GMS_UID + ":" + GMS_UID + " '" + gsfDir + "/gservices.xml' 2>/dev/null; echo GS_OK",
    'GS_OK', 20);
  console.log('  gservices.xml: ' + (gsOk ? 'OK (GSF ID + android_id aligned)' : 'FAIL'));
  await sleep(3500);

  // ═══ PHASE 9: Vending finsky.xml (MERGE) + billing.xml ═══
  console.log('\n[9/10] MERGING into finsky.xml (preserving existing Play Store data)...');
  // Strategy: Read existing finsky.xml, inject account entries before </map>
  const existingFinsky = await sh(PAD, "cat '" + vDir + "/finsky.xml' 2>/dev/null");
  let fOk = false;
  if (existingFinsky && existingFinsky.includes('</map>')) {
    // Merge: inject our entries before closing </map>
    const accountEntries = [
      '    <string name="signed_in_account">' + safe + '</string>',
      '    <boolean name="setup_complete" value="true"/>',
      '    <string name="account_type">com.google</string>',
      '    <string name="purchase_auth_required">never</string>',
      '    <boolean name="purchase_auth_opt_out" value="true"/>',
      '    <int name="purchase_auth_timeout_ms" value="0"/>',
      '    <boolean name="biometric_purchase_auth_enabled" value="false"/>',
      '    <boolean name="require_password_on_purchase" value="false"/>',
    ].join('\n');
    const merged = existingFinsky.replace('</map>', accountEntries + '\n</map>');
    // Write merged back (truncate existing entries if they were already there)
    const mergeOk = await shOk(PAD,
      "cat > '" + vDir + "/finsky.xml' << 'XMLEOF'\n" + merged + "\nXMLEOF\necho MERGE_OK",
      'MERGE_OK', 25);
    fOk = mergeOk;
    console.log('  finsky.xml: ' + (mergeOk ? 'MERGED OK (preserved ' + (existingFinsky.match(/<\w+\s/g) || []).length + ' existing entries + 8 account entries)' : 'FAIL'));
  } else {
    // Fallback: create fresh
    const finskyXml = [
      '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
      '<map>',
      '    <string name="signed_in_account">' + safe + '</string>',
      '    <boolean name="setup_complete" value="true"/>',
      '    <long name="last_self_update_time" value="' + ((now - 86400 * 7) * 1000) + '"/>',
      '    <boolean name="tos_accepted" value="true"/>',
      '    <string name="account_type">com.google</string>',
      '    <string name="purchase_auth_required">never</string>',
      '    <boolean name="purchase_auth_opt_out" value="true"/>',
      '    <int name="purchase_auth_timeout_ms" value="0"/>',
      '    <boolean name="biometric_purchase_auth_enabled" value="false"/>',
      '    <boolean name="require_password_on_purchase" value="false"/>',
      '</map>'
    ].join('\n');
    fOk = await shOk(PAD,
      "cat > '" + vDir + "/finsky.xml' << 'XMLEOF'\n" + finskyXml + "\nXMLEOF\necho F_OK",
      'F_OK', 20);
    console.log('  finsky.xml: ' + (fOk ? 'OK (fresh)' : 'FAIL'));
  }
  await sleep(3500);

  // 9b. billing.xml
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
  console.log('  billing.xml: ' + (bOk ? 'OK (purchase auth bypassed)' : 'FAIL'));
  await sleep(3500);

  // 9c. Fix Vending ownership (UID 10042)
  const vOwnOk = await shOk(PAD,
    "chown 10042:10042 '" + vDir + "/finsky.xml' '" + vDir + "/billing.xml' 2>/dev/null; echo VOWN_OK",
    'VOWN_OK', 10);
  console.log('  Vending ownership (UID 10042): ' + (vOwnOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // ═══ PHASE 10: restorecon + restart GMS ═══
  console.log('\n[10/10] restorecon + restart GMS...');
  const rcOk = await shOk(PAD, [
    'restorecon -R /data/system_ce/0/ /data/system_de/0/ 2>/dev/null || true',
    'restorecon -R ' + gmsDir + '/ 2>/dev/null || true',
    'restorecon -R ' + gsfDir + '/ 2>/dev/null || true',
    'restorecon -R ' + vDir + '/ 2>/dev/null || true',
    'echo RC_OK'
  ].join('; '), 'RC_OK', 20);
  console.log('  restorecon: ' + (rcOk ? 'OK' : 'PARTIAL'));
  await sleep(3500);

  // Restart GMS to pick up new account data (auth endpoints still blocked)
  await sh(PAD, 'am startservice -n com.google.android.gms/.persistent.PersistentMessagingService 2>/dev/null || true', 15);
  console.log('  GMS restarted (auth still blocked by iptables)');
  await sleep(5000);

  // ═══ VERIFICATION ═══
  console.log('\n╔═══════════════════════════════════════════════════════╗');
  console.log('║  VERIFICATION                                         ║');
  console.log('╚═══════════════════════════════════════════════════════╝');

  // V1: AccountManager
  console.log('\n[V1] AccountManager (dumpsys account):');
  const v1 = await sh(PAD, 'dumpsys account 2>/dev/null | head -10', 15);
  console.log('  ' + (v1 || '').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // V2: File presence
  console.log('\n[V2] File presence:');
  const v2 = await sh(PAD, [
    'test -f /data/system_ce/0/accounts_ce.db && echo "  accounts_ce.db: EXISTS" || echo "  accounts_ce.db: MISSING"',
    'test -f /data/system_de/0/accounts_de.db && echo "  accounts_de.db: EXISTS" || echo "  accounts_de.db: MISSING"',
    'test -f ' + gmsDir + '/device_registration.xml && echo "  device_registration.xml: EXISTS" || echo "  device_registration.xml: MISSING"',
    'test -f ' + gmsDir + '/checkin.xml && echo "  checkin.xml: EXISTS" || echo "  checkin.xml: MISSING"',
    'test -f ' + gmsDir + '/COIN.xml && echo "  COIN.xml: EXISTS" || echo "  COIN.xml: MISSING"',
    'test -f ' + gsfDir + '/gservices.xml && echo "  gservices.xml: EXISTS" || echo "  gservices.xml: MISSING"',
    'test -f ' + vDir + '/finsky.xml && echo "  finsky.xml: EXISTS" || echo "  finsky.xml: MISSING"',
    'test -f ' + vDir + '/billing.xml && echo "  billing.xml: EXISTS" || echo "  billing.xml: MISSING"',
  ].join('; '), 15);
  console.log(v2);
  await sleep(3500);

  // V3: Account in DB
  console.log('\n[V3] Account in SQLite:');
  const v3 = await sh(PAD, 'sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name,type FROM accounts;" 2>/dev/null', 10);
  console.log('  ' + (v3 || 'EMPTY').trim());
  await sleep(3500);

  // V4: finsky signed_in_account
  console.log('\n[V4] finsky.xml signed_in_account:');
  const v4 = await sh(PAD, "grep signed_in_account '" + vDir + "/finsky.xml' 2>/dev/null", 10);
  console.log('  ' + (v4 || 'NOT FOUND').trim());
  await sleep(3500);

  // V5: iptables rules
  console.log('\n[V5] iptables DROP rules:');
  const v5 = await sh(PAD, 'iptables -L OUTPUT -n 2>/dev/null | grep DROP | head -6', 10);
  console.log('  ' + (v5 || 'NONE').trim().replace(/\n/g, '\n  '));
  await sleep(3500);

  // V6: COIN.xml content
  console.log('\n[V6] COIN.xml purchase_requires_auth:');
  const v6 = await sh(PAD, "grep -E 'purchase_requires_auth|has_payment_methods|one_touch_enabled' '" + gmsDir + "/COIN.xml' 2>/dev/null", 10);
  console.log('  ' + (v6 || 'NOT FOUND').trim().replace(/\n/g, '\n  '));

  // Summary
  const results = [ceOk, deOk, regOk, chkOk, coinOk, gsOk, fOk, bOk, blockOk, svcOk];
  const passed = results.filter(Boolean).length;
  console.log('\n══════════════════════════════════════════════════');
  console.log('RESULT: ' + passed + '/' + results.length + ' targets succeeded');
  if (passed === results.length) {
    console.log('STATUS: FULL SUCCESS — Account injected + GMS auth blocked');
  } else {
    console.log('STATUS: PARTIAL — Some targets failed, review above');
  }
  console.log('══════════════════════════════════════════════════');

})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
