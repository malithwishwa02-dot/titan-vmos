#!/usr/bin/env node
/**
 * Gmail + Play Store Account Injection — Device ACP2507296TM25XE (Samsung S24)
 */
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const { execSync } = require('child_process');

const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi';
const SK = 'Q2SgcSwEfuwoedY0cijp6Mce';
const PAD = 'ACP2507296TM25XE';
const GMAIL = 'epolusamuel682@gmail.com';
const PASS = 'gA3EFqhAQJOBZ';

const H = 'api.vmoscloud.com', S = 'armcloud-paas';
const CT = 'application/json;charset=UTF-8';
const SH = 'content-type;host;x-content-sha256;x-date';

function _sign(bodyJson) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const sd = xDate.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const c = [`host:${H}`, `x-date:${xDate}`, `content-type:${CT}`, `signedHeaders:${SH}`, `x-content-sha256:${xSha}`].join('\n');
  const scope = `${sd}/${S}/request`;
  const hc = crypto.createHash('sha256').update(c, 'utf8').digest('hex');
  const sts = ['HMAC-SHA256', xDate, scope, hc].join('\n');
  const kd = crypto.createHmac('sha256', Buffer.from(SK, 'utf8')).update(sd).digest();
  const ks = crypto.createHmac('sha256', kd).update(S).digest();
  const sk2 = crypto.createHmac('sha256', ks).update('request').digest();
  const sig = crypto.createHmac('sha256', sk2).update(sts).digest('hex');
  return { 'content-type': CT, 'x-date': xDate, 'x-host': H, 'authorization': `HMAC-SHA256 Credential=${AK}, SignedHeaders=${SH}, Signature=${sig}` };
}

function vpost(path, data, sec) {
  return new Promise((resolve, reject) => {
    const b = JSON.stringify(data || {});
    const headers = _sign(b);
    const buf = Buffer.from(b, 'utf8');
    const req = https.request({ hostname: H, path, method: 'POST', headers: { ...headers, 'content-length': buf.length }, timeout: (sec || 30) * 1000 }, res => {
      let raw = ''; res.on('data', c => raw += c);
      res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { reject(new Error('Bad JSON')); } });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
    req.write(buf); req.end();
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function sh(cmd, sec) {
  for (let a = 0; a < 2; a++) {
    try {
      const r = await vpost('/vcpcloud/api/padApi/syncCmd', { padCode: PAD, scriptContent: cmd }, sec || 30);
      if (r.code !== 200) { console.error(`  [sh] code=${r.code} ${r.msg}`); return ''; }
      const items = Array.isArray(r.data) ? r.data : [r.data];
      const it = items[0] || {};
      if (it.taskStatus === 3) return it.errorMsg || it.taskResult || '';
      return '';
    } catch (e) { if (a === 1) return ''; await sleep(2000); }
  }
  return '';
}

async function shOk(cmd, marker, sec) {
  const r = await sh(cmd, sec);
  return (r || '').includes(marker);
}

function san(v, maxLen) {
  if (!v || typeof v !== 'string') return '';
  return v.replace(/'/g, '').replace(/"/g, '').replace(/;/g, '')
    .replace(/`/g, '').replace(/\\/g, '').replace(/\$/g, '')
    .replace(/\|/g, '').replace(/&/g, '').replace(/\n/g, '')
    .replace(/\r/g, '').replace(/--/g, '').replace(/\/\*/g, '')
    .replace(/\*\//g, '').slice(0, maxLen || 1000);
}

async function createDb(remotePath, sql, ownerDir) {
  const tmpDb = `/tmp/genesis_${crypto.randomBytes(8).toString('hex')}.db`;
  try {
    execSync(`sqlite3 "${tmpDb}"`, { input: sql, timeout: 15000 });
    const b64 = fs.readFileSync(tmpDb).toString('base64');
    const dir = remotePath.substring(0, remotePath.lastIndexOf('/'));
    await sh(`mkdir -p '${dir}' 2>/dev/null`);
    await sleep(3000);
    const CHUNK = 3500;
    if (b64.length <= CHUNK) {
      return await shOk(`printf '%s' '${b64}' | base64 -d > '${remotePath}' && echo DB_XFER_OK`, 'DB_XFER_OK', 30);
    } else {
      const tmpR = `/data/local/tmp/_b64_${crypto.randomBytes(4).toString('hex')}`;
      const chunks = [];
      for (let i = 0; i < b64.length; i += CHUNK) chunks.push(b64.slice(i, i + CHUNK));
      for (let i = 0; i < chunks.length; i++) {
        await sleep(3000);
        const op = i === 0 ? '>' : '>>';
        const ok = await shOk(`printf '%s' '${chunks[i]}' ${op} '${tmpR}' && echo CK_OK`, 'CK_OK', 30);
        if (!ok) { await sh(`rm -f '${tmpR}' 2>/dev/null`); return false; }
      }
      await sleep(3000);
      const ok = await shOk(`base64 -d '${tmpR}' > '${remotePath}' && rm -f '${tmpR}' && echo DB_XFER_OK`, 'DB_XFER_OK', 30);
      if (!ok) return false;
    }
    if (ownerDir) { await sleep(3000); await sh(`chmod 660 '${remotePath}' && chown $(stat -c '%u:%g' '${ownerDir}' 2>/dev/null) '${remotePath}' 2>/dev/null`); }
    return true;
  } catch (e) { console.error(`  [createDb] ${remotePath}: ${e.message}`); return false; }
  finally { try { fs.unlinkSync(tmpDb); } catch (_) {} }
}

(async () => {
  const now = Math.floor(Date.now() / 1000);
  const ageDays = 365;
  const profileAge = ageDays * 86400;
  const regTimestamp = (now - profileAge) * 1000;
  const androidId = crypto.randomBytes(8).toString('hex');
  const gsfId = String(BigInt(3000000000000000000n) + BigInt(Math.floor(Math.random() * 999999999999999)));
  const deviceRegId = crypto.randomBytes(16).toString('hex');
  const oauthToken = crypto.randomBytes(64).toString('base64url');
  const googleId = crypto.randomBytes(10).toString('hex');
  const sidToken = crypto.randomBytes(64).toString('base64url');
  const lsidToken = crypto.randomBytes(64).toString('base64url');
  const safeEmail = san(GMAIL, 254);
  const safePass = san(PASS, 128);

  console.log('═══════════════════════════════════════════════════════════');
  console.log(`PLAY STORE GMAIL INJECTION — ${GMAIL}`);
  console.log(`Device: ${PAD} (Samsung S24) | Age: ${ageDays}d | Android ID: ${androidId}`);
  console.log('═══════════════════════════════════════════════════════════');

  // [0] Force-stop
  console.log('\n[0] Force-stopping GMS/GSF/Vending...');
  await sh('am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.vending 2>/dev/null', 15);
  console.log('  Done');
  await sleep(3500);

  // [1] Clean existing
  console.log('\n[1] Cleaning existing account data...');
  const cleanOk = await shOk([
    'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null',
    'rm -rf /data/data/com.google.android.gms/shared_prefs/device_registration.xml /data/data/com.google.android.gms/shared_prefs/checkin.xml /data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null',
    'rm -rf /data/data/com.google.android.gsf/shared_prefs/gservices.xml /data/data/com.android.vending/shared_prefs/finsky.xml /data/data/com.android.vending/shared_prefs/billing.xml /data/data/com.android.vending/shared_prefs/PlayAutoInstallConfig.xml 2>/dev/null',
    'echo CLEAN_OK',
  ].join('; '), 'CLEAN_OK', 20);
  console.log(`  Result: ${cleanOk ? 'OK' : 'WARN'}`);
  await sleep(3500);

  // [2] accounts_ce.db
  console.log('\n[2] Creating accounts_ce.db...');
  const acctCeSql = [
    "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, password TEXT, UNIQUE(name,type));",
    "CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, key TEXT NOT NULL, value TEXT);",
    "CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, type TEXT NOT NULL, authtoken TEXT NOT NULL);",
    `INSERT OR REPLACE INTO accounts (name,type,password) VALUES('${safeEmail}','com.google','${safePass}');`,
    `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'googleId','${san(googleId)}');`,
    `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'services','hist,mail,lso,calendar,youtube,cl');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'oauth2:https://www.googleapis.com/auth/plus.me','${san(oauthToken)}');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'SID','${san(sidToken)}');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'LSID','${san(lsidToken)}');`,
  ].join('\n');
  const acctCeOk = await createDb('/data/system_ce/0/accounts_ce.db', acctCeSql, '/data/system_ce/0');
  if (acctCeOk) { await sleep(3000); await sh('chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null'); }
  console.log(`  accounts_ce.db: ${acctCeOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [3] accounts_de.db
  console.log('\n[3] Creating accounts_de.db...');
  const acctDeSql = [
    "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));",
    `INSERT OR REPLACE INTO accounts (name,type) VALUES('${safeEmail}','com.google');`,
  ].join('\n');
  const acctDeOk = await createDb('/data/system_de/0/accounts_de.db', acctDeSql, '/data/system_de/0');
  if (acctDeOk) { await sleep(3000); await sh('chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null'); }
  console.log(`  accounts_de.db: ${acctDeOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [4] GMS device_registration.xml
  console.log('\n[4] Writing GMS device_registration.xml...');
  const gmsDir = '/data/data/com.google.android.gms/shared_prefs';
  const devRegXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <string name="registration_timestamp_ms">${regTimestamp}</string>
  <string name="device_registration_id">${deviceRegId}</string>
  <boolean name="has_completed_registration" value="true"/>
  <string name="android_id">${androidId}</string>
</map>`;
  const gmsOk = await shOk([
    `mkdir -p ${gmsDir} 2>/dev/null`,
    `cat > ${gmsDir}/device_registration.xml << 'GMSEOF'`,
    devRegXml, 'GMSEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/device_registration.xml 2>/dev/null`,
    'echo GMS_DONE',
  ].join('\n'), 'GMS_DONE', 20);
  console.log(`  device_registration.xml: ${gmsOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [5] checkin.xml
  console.log('\n[5] Writing GMS checkin.xml...');
  const chkOk = await shOk([
    `pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true`,
    `cat > ${gmsDir}/checkin.xml << 'CHKEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="checkin_enabled" value="false"/>',
    `  <long name="last_checkin_ms" value="${Date.now()}"/>`,
    `  <string name="android_id">${androidId}</string>`,
    '  <boolean name="is_checked_in" value="true"/>',
    '</map>', 'CHKEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/checkin.xml 2>/dev/null`,
    'echo CHK_DONE',
  ].join('\n'), 'CHK_DONE', 15);
  console.log(`  checkin.xml: ${chkOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [6] GSF gservices.xml
  console.log('\n[6] Writing GSF gservices.xml...');
  const gsfDir = '/data/data/com.google.android.gsf/shared_prefs';
  const gsfOk = await shOk([
    `mkdir -p ${gsfDir} 2>/dev/null`,
    `cat > ${gsfDir}/gservices.xml << 'GSFEOF'`,
    `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>`,
    '<map>',
    `  <string name="android_id">${androidId}</string>`,
    `  <string name="registration_timestamp">${regTimestamp}</string>`,
    `  <string name="android_gsf_id">${gsfId}</string>`,
    '  <string name="account_type">hosted_or_google</string>',
    '</map>', 'GSFEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gsf/ 2>/dev/null) ${gsfDir}/gservices.xml 2>/dev/null`,
    'echo GSF_DONE',
  ].join('\n'), 'GSF_DONE', 20);
  console.log(`  gservices.xml: ${gsfOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [7] finsky.xml
  console.log('\n[7] Writing Play Store finsky.xml...');
  const vDir = '/data/data/com.android.vending/shared_prefs';
  const fOk = await shOk([
    `mkdir -p ${vDir} 2>/dev/null`,
    `cat > ${vDir}/finsky.xml << 'FEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    `  <string name="signed_in_account">${safeEmail}</string>`,
    '  <boolean name="setup_complete" value="true"/>',
    `  <long name="last_self_update_time" value="${(now - 86400 * 7) * 1000}"/>`,
    '  <boolean name="tos_accepted" value="true"/>',
    '  <string name="account_type">com.google</string>',
    '  <string name="purchase_auth_required">never</string>',
    '  <boolean name="purchase_auth_opt_out" value="true"/>',
    '  <int name="purchase_auth_timeout_ms" value="0"/>',
    '  <boolean name="biometric_purchase_auth_enabled" value="false"/>',
    '  <boolean name="require_password_on_purchase" value="false"/>',
    '</map>', 'FEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vDir}/finsky.xml 2>/dev/null`,
    'echo FINSKY_DONE',
  ].join('\n'), 'FINSKY_DONE', 20);
  console.log(`  finsky.xml: ${fOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [8] billing.xml
  console.log('\n[8] Writing billing.xml...');
  const bOk = await shOk([
    `cat > ${vDir}/billing.xml << 'BEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    `  <string name="billing_account">${safeEmail}</string>`,
    '  <boolean name="billing_setup_complete" value="true"/>',
    '  <boolean name="accept_tos" value="true"/>',
    '  <int name="purchase_auth_expiry" value="0"/>',
    '  <boolean name="require_auth_for_purchase" value="false"/>',
    '  <boolean name="password_purchase_auth" value="false"/>',
    '  <string name="default_purchase_flow">direct</string>',
    '  <boolean name="iab_v3_enabled" value="true"/>',
    '  <boolean name="iab_auto_confirm" value="true"/>',
    '</map>', 'BEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vDir}/billing.xml 2>/dev/null`,
    'echo BILL_DONE',
  ].join('\n'), 'BILL_DONE', 15);
  console.log(`  billing.xml: ${bOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [9] PlayAutoInstallConfig.xml
  console.log('\n[9] Writing PlayAutoInstallConfig.xml...');
  const aOk = await shOk([
    `cat > ${vDir}/PlayAutoInstallConfig.xml << 'AEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="auto_update_enabled" value="true"/>',
    '  <boolean name="skip_purchase_verification" value="true"/>',
    '  <boolean name="parental_controls_enabled" value="false"/>',
    '  <int name="content_rating_level" value="0"/>',
    '  <boolean name="in_app_purchase_ask_every_time" value="false"/>',
    '</map>', 'AEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vDir}/PlayAutoInstallConfig.xml 2>/dev/null`,
    'echo AUTO_DONE',
  ].join('\n'), 'AUTO_DONE', 15);
  console.log(`  PlayAutoInstallConfig.xml: ${aOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [10] COIN.xml
  console.log('\n[10] Writing COIN.xml...');
  const authTok = crypto.randomBytes(32).toString('hex');
  const cOk = await shOk([
    `cat > ${gmsDir}/COIN.xml << 'CEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="has_payment_methods" value="true"/>',
    '  <string name="default_instrument_id">instrument_1</string>',
    '  <boolean name="wallet_enabled" value="true"/>',
    '  <boolean name="purchase_requires_auth" value="false"/>',
    '  <boolean name="one_touch_enabled" value="true"/>',
    '  <boolean name="biometric_payment_enabled" value="true"/>',
    `  <string name="auth_token">${authTok}</string>`,
    '</map>', 'CEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/COIN.xml 2>/dev/null`,
    'echo COIN_DONE',
  ].join('\n'), 'COIN_DONE', 15);
  console.log(`  COIN.xml: ${cOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // [11] restorecon
  console.log('\n[11] Running restorecon...');
  const rcOk = await shOk([
    'restorecon -R /data/system_ce/0/ 2>/dev/null || true',
    'restorecon -R /data/system_de/0/ 2>/dev/null || true',
    'restorecon -R /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null || true',
    'restorecon -R /data/data/com.google.android.gsf/shared_prefs/ 2>/dev/null || true',
    'restorecon -R /data/data/com.android.vending/shared_prefs/ 2>/dev/null || true',
    'echo RC_DONE',
  ].join('; '), 'RC_DONE', 20);
  console.log(`  restorecon: ${rcOk ? 'OK' : 'FAIL'}`);

  // Summary
  const results = {
    'accounts_ce.db': acctCeOk, 'accounts_de.db': acctDeOk,
    'device_registration.xml': gmsOk, 'checkin.xml': chkOk,
    'gservices.xml': gsfOk, 'finsky.xml': fOk,
    'billing.xml': bOk, 'PlayAutoInstall.xml': aOk,
    'COIN.xml': cOk, 'restorecon': rcOk,
  };
  const passed = Object.values(results).filter(Boolean).length;
  const total = Object.keys(results).length;
  console.log('\n═══════════════════════════════════════════════════════════');
  console.log(`INJECTION COMPLETE: ${passed}/${total} targets succeeded`);
  console.log('═══════════════════════════════════════════════════════════');
  Object.entries(results).forEach(([k, v]) => console.log(`  ${v ? '✓' : '✗'} ${k}`));
  console.log(`\nAccount: ${GMAIL}`);
  console.log(`Android ID: ${androidId}`);
  console.log(`GSF ID: ${gsfId}`);
  console.log(`Age backdated: ${ageDays} days (${new Date((now - profileAge) * 1000).toISOString().slice(0, 10)})`);
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
