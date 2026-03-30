#!/usr/bin/env node
/**
 * Gmail + Play Store Account Injection Script
 * Injects Google account into VMOS device accounts system + Play Store
 * Mirrors Phase 5 of the Genesis pipeline (main.js)
 */
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const { execSync } = require('child_process');

// ═══ Config ═══
const AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi';
const SK = 'Q2SgcSwEfuwoedY0cijp6Mce';
const PAD = 'ACP250329ACQRPDV';
const GOOGLE_EMAIL = 'epolusamuel682@gmail.com';
const GOOGLE_PASS = 'gA3EFqhAQJOBZ';

// ═══ VMOS Cloud API ═══
const VMOS_HOST = 'api.vmoscloud.com';
const VMOS_SERVICE = 'armcloud-paas';
const VMOS_CT = 'application/json;charset=UTF-8';
const VMOS_SH = 'content-type;host;x-content-sha256;x-date';

function _vmosSign(bodyJson) {
  const xDate = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const shortDate = xDate.slice(0, 8);
  const xSha = crypto.createHash('sha256').update(bodyJson, 'utf8').digest('hex');
  const canonical = [
    `host:${VMOS_HOST}`, `x-date:${xDate}`, `content-type:${VMOS_CT}`,
    `signedHeaders:${VMOS_SH}`, `x-content-sha256:${xSha}`,
  ].join('\n');
  const scope = `${shortDate}/${VMOS_SERVICE}/request`;
  const hashCan = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
  const sts = ['HMAC-SHA256', xDate, scope, hashCan].join('\n');
  const kDate = crypto.createHmac('sha256', Buffer.from(SK, 'utf8')).update(shortDate).digest();
  const kSvc = crypto.createHmac('sha256', kDate).update(VMOS_SERVICE).digest();
  const sigKey = crypto.createHmac('sha256', kSvc).update('request').digest();
  const sig = crypto.createHmac('sha256', sigKey).update(sts).digest('hex');
  return {
    'content-type': VMOS_CT, 'x-date': xDate, 'x-host': VMOS_HOST,
    'authorization': `HMAC-SHA256 Credential=${AK}, SignedHeaders=${VMOS_SH}, Signature=${sig}`,
  };
}

function vpost(apiPath, data, timeoutSec) {
  return new Promise((resolve, reject) => {
    const bodyJson = JSON.stringify(data || {});
    const headers = _vmosSign(bodyJson);
    const buf = Buffer.from(bodyJson, 'utf8');
    const timeoutMs = Math.min(Math.max((timeoutSec || 30) * 1000, 5000), 120000);
    const req = https.request({
      hostname: VMOS_HOST, path: apiPath, method: 'POST',
      headers: { ...headers, 'content-length': buf.length }, timeout: timeoutMs,
    }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => { try { resolve(JSON.parse(raw)); } catch { reject(new Error(`Bad JSON: ${raw.slice(0, 120)}`)); } });
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
    req.write(buf); req.end();
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function sh(cmd, sec) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const resp = await vpost('/vcpcloud/api/padApi/syncCmd', { padCode: PAD, scriptContent: cmd }, sec || 30);
      if (resp.code !== 200) { console.error(`  [sh] code=${resp.code} msg=${resp.msg}`); return ''; }
      const items = Array.isArray(resp.data) ? resp.data : [resp.data];
      const item = items[0] || {};
      if (item.taskStatus === 3) return item.errorMsg || item.taskResult || '';
      return '';
    } catch (e) {
      if (attempt === 1) { console.error(`  [sh] error: ${e.message}`); return ''; }
      await sleep(2000);
    }
  }
  return '';
}

async function shOk(cmd, marker, sec) {
  const result = await sh(cmd, sec);
  return (result || '').includes(marker);
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
      const ok = await shOk(
        `printf '%s' '${b64}' | base64 -d > '${remotePath}' && echo DB_XFER_OK`,
        'DB_XFER_OK', 30);
      if (!ok) return false;
    } else {
      const tmpRemote = `/data/local/tmp/_b64_${crypto.randomBytes(4).toString('hex')}`;
      const chunks = [];
      for (let i = 0; i < b64.length; i += CHUNK) chunks.push(b64.slice(i, i + CHUNK));
      for (let i = 0; i < chunks.length; i++) {
        await sleep(3000);
        const op = i === 0 ? '>' : '>>';
        const ok = await shOk(
          `printf '%s' '${chunks[i]}' ${op} '${tmpRemote}' && echo CK_OK`,
          'CK_OK', 30);
        if (!ok) {
          await sh(`rm -f '${tmpRemote}' 2>/dev/null`);
          return false;
        }
      }
      await sleep(3000);
      const ok = await shOk(
        `base64 -d '${tmpRemote}' > '${remotePath}' && rm -f '${tmpRemote}' && echo DB_XFER_OK`,
        'DB_XFER_OK', 30);
      if (!ok) return false;
    }

    if (ownerDir) {
      await sleep(3000);
      await sh(`chmod 660 '${remotePath}' && chown $(stat -c '%u:%g' '${ownerDir}' 2>/dev/null) '${remotePath}' 2>/dev/null`);
    }
    return true;
  } catch (e) {
    console.error(`  [createDb] ${remotePath}: ${e.message}`);
    return false;
  } finally {
    try { fs.unlinkSync(tmpDb); } catch (_) {}
  }
}

function sanitizeSQL(v, maxLen) {
  if (!v || typeof v !== 'string') return '';
  return v.replace(/'/g, '').replace(/"/g, '').replace(/;/g, '')
    .replace(/`/g, '').replace(/\\/g, '').replace(/\$/g, '')
    .replace(/\|/g, '').replace(/&/g, '').replace(/\n/g, '')
    .replace(/\r/g, '').replace(/--/g, '').replace(/\/\*/g, '')
    .replace(/\*\//g, '').slice(0, maxLen || 1000);
}

// ═══ Main Injection ═══
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
  const safeEmail = sanitizeSQL(GOOGLE_EMAIL, 254);
  const safePass = sanitizeSQL(GOOGLE_PASS, 128);

  console.log('═══════════════════════════════════════════════════════════');
  console.log(`GMAIL + PLAY STORE INJECTION — ${GOOGLE_EMAIL}`);
  console.log(`Target: ${PAD}  |  Age: ${ageDays}d  |  Android ID: ${androidId}`);
  console.log('═══════════════════════════════════════════════════════════');

  // Step 0: Force-stop GMS before writing
  console.log('\n[0] Force-stopping GMS/GSF/Vending...');
  const stopOk = await shOk(
    'am force-stop com.google.android.gms; am force-stop com.google.android.gsf; am force-stop com.android.vending; echo STOP_OK',
    'STOP_OK', 15);
  console.log(`  Result: ${stopOk ? 'OK' : 'WARN'}`);
  await sleep(3500);

  // Step 1: Clean existing account/GMS data
  console.log('\n[1] Cleaning existing account data...');
  const cleanOk = await shOk([
    'rm -rf /data/system_ce/0/accounts_ce.db* /data/system_de/0/accounts_de.db* 2>/dev/null',
    'rm -rf /data/data/com.google.android.gms/shared_prefs/device_registration.xml 2>/dev/null',
    'rm -rf /data/data/com.google.android.gms/shared_prefs/checkin.xml 2>/dev/null',
    'rm -rf /data/data/com.google.android.gsf/shared_prefs/gservices.xml 2>/dev/null',
    'rm -rf /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null',
    'rm -rf /data/data/com.android.vending/shared_prefs/billing.xml 2>/dev/null',
    'rm -rf /data/data/com.android.vending/shared_prefs/PlayAutoInstallConfig.xml 2>/dev/null',
    'echo CLEAN_OK',
  ].join('; '), 'CLEAN_OK', 20);
  console.log(`  Result: ${cleanOk ? 'OK' : 'WARN'}`);
  await sleep(3500);

  // Step 2: accounts_ce.db (main account DB with extras + authtokens)
  console.log('\n[2] Creating accounts_ce.db...');
  const acctCeSql = [
    "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, password TEXT, UNIQUE(name,type));",
    "CREATE TABLE IF NOT EXISTS extras (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER, key TEXT NOT NULL, value TEXT);",
    "CREATE TABLE IF NOT EXISTS authtokens (_id INTEGER PRIMARY KEY AUTOINCREMENT, accounts_id INTEGER NOT NULL, type TEXT NOT NULL, authtoken TEXT NOT NULL);",
    `INSERT OR REPLACE INTO accounts (name,type,password) VALUES('${safeEmail}','com.google','${safePass}');`,
    `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'googleId','${sanitizeSQL(googleId)}');`,
    `INSERT OR IGNORE INTO extras (accounts_id,key,value) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'services','hist,mail,lso,calendar,youtube,cl');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'oauth2:https://www.googleapis.com/auth/plus.me','${sanitizeSQL(oauthToken)}');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'SID','${sanitizeSQL(sidToken)}');`,
    `INSERT OR IGNORE INTO authtokens (accounts_id,type,authtoken) VALUES((SELECT _id FROM accounts WHERE name='${safeEmail}'),'LSID','${sanitizeSQL(lsidToken)}');`,
  ].join('\n');
  const acctCeOk = await createDb('/data/system_ce/0/accounts_ce.db', acctCeSql, '/data/system_ce/0');
  if (acctCeOk) {
    await sleep(3000);
    await sh('chmod 600 /data/system_ce/0/accounts_ce.db 2>/dev/null');
  }
  console.log(`  accounts_ce.db: ${acctCeOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 3: accounts_de.db
  console.log('\n[3] Creating accounts_de.db...');
  const acctDeSql = [
    "CREATE TABLE IF NOT EXISTS accounts (_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, UNIQUE(name,type));",
    `INSERT OR REPLACE INTO accounts (name,type) VALUES('${safeEmail}','com.google');`,
  ].join('\n');
  const acctDeOk = await createDb('/data/system_de/0/accounts_de.db', acctDeSql, '/data/system_de/0');
  if (acctDeOk) {
    await sleep(3000);
    await sh('chmod 600 /data/system_de/0/accounts_de.db 2>/dev/null');
  }
  console.log(`  accounts_de.db: ${acctDeOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 4: GMS device_registration.xml (backdated)
  console.log('\n[4] Writing GMS device_registration.xml...');
  const gmsDir = '/data/data/com.google.android.gms/shared_prefs';
  const devRegXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <string name="registration_timestamp_ms">${regTimestamp}</string>
  <string name="device_registration_id">${deviceRegId}</string>
  <boolean name="has_completed_registration" value="true"/>
  <string name="android_id">${androidId}</string>
</map>`;
  const gmsCmd = [
    `mkdir -p ${gmsDir} 2>/dev/null`,
    `cat > ${gmsDir}/device_registration.xml << 'GMSEOF'`,
    devRegXml,
    'GMSEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/device_registration.xml 2>/dev/null`,
    'echo GMS_DONE',
  ].join('\n');
  const gmsOk = await shOk(gmsCmd, 'GMS_DONE', 20);
  console.log(`  device_registration.xml: ${gmsOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 5: GMS checkin.xml (re-checkin prevention)
  console.log('\n[5] Writing GMS checkin.xml (re-checkin block)...');
  const recheckinCmd = [
    `pm disable com.google.android.gms/com.google.android.gms.checkin.GmsIntentOperationService 2>/dev/null || true`,
    `cat > ${gmsDir}/checkin.xml << 'CHKEOF'`,
    '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>',
    '<map>',
    '  <boolean name="checkin_enabled" value="false"/>',
    `  <long name="last_checkin_ms" value="${Date.now()}"/>`,
    `  <string name="android_id">${androidId}</string>`,
    '  <boolean name="is_checked_in" value="true"/>',
    '</map>',
    'CHKEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/checkin.xml 2>/dev/null`,
    'echo RECHECKIN_DONE',
  ].join('\n');
  const recheckinOk = await shOk(recheckinCmd, 'RECHECKIN_DONE', 15);
  console.log(`  checkin.xml: ${recheckinOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 6: GSF gservices.xml
  console.log('\n[6] Writing GSF gservices.xml...');
  const gsfDir = '/data/data/com.google.android.gsf/shared_prefs';
  const gsfXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <string name="android_id">${androidId}</string>
  <string name="registration_timestamp">${regTimestamp}</string>
  <string name="android_gsf_id">${gsfId}</string>
  <string name="account_type">hosted_or_google</string>
</map>`;
  const gsfCmd = [
    `mkdir -p ${gsfDir} 2>/dev/null`,
    `cat > ${gsfDir}/gservices.xml << 'GSFEOF'`,
    gsfXml,
    'GSFEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gsf/ 2>/dev/null) ${gsfDir}/gservices.xml 2>/dev/null`,
    'echo GSF_DONE',
  ].join('\n');
  const gsfOk = await shOk(gsfCmd, 'GSF_DONE', 20);
  console.log(`  gservices.xml: ${gsfOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 7: Play Store finsky.xml (signed-in + purchase auth bypass)
  console.log('\n[7] Writing Play Store finsky.xml...');
  const vendingDir = '/data/data/com.android.vending/shared_prefs';
  const finskyXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <string name="signed_in_account">${safeEmail}</string>
  <boolean name="setup_complete" value="true"/>
  <long name="last_self_update_time" value="${(now - 86400 * 7) * 1000}"/>
  <boolean name="tos_accepted" value="true"/>
  <string name="account_type">com.google</string>
  <string name="purchase_auth_required">never</string>
  <boolean name="purchase_auth_opt_out" value="true"/>
  <int name="purchase_auth_timeout_ms" value="0"/>
  <boolean name="biometric_purchase_auth_enabled" value="false"/>
  <boolean name="require_password_on_purchase" value="false"/>
</map>`;
  const finskyCmd = [
    `mkdir -p ${vendingDir} 2>/dev/null`,
    `cat > ${vendingDir}/finsky.xml << 'FEOF'`,
    finskyXml,
    'FEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/finsky.xml 2>/dev/null`,
    'echo FINSKY_DONE',
  ].join('\n');
  const finskyOk = await shOk(finskyCmd, 'FINSKY_DONE', 20);
  console.log(`  finsky.xml: ${finskyOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 8: Play Store billing.xml (auth-free in-app purchases)
  console.log('\n[8] Writing Play Store billing.xml...');
  const billingPrefsXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <string name="billing_account">${safeEmail}</string>
  <boolean name="billing_setup_complete" value="true"/>
  <boolean name="accept_tos" value="true"/>
  <int name="purchase_auth_expiry" value="0"/>
  <boolean name="require_auth_for_purchase" value="false"/>
  <boolean name="password_purchase_auth" value="false"/>
  <string name="default_purchase_flow">direct</string>
  <boolean name="iab_v3_enabled" value="true"/>
  <boolean name="iab_auto_confirm" value="true"/>
</map>`;
  const billingCmd = [
    `cat > ${vendingDir}/billing.xml << 'BILLEOF'`,
    billingPrefsXml,
    'BILLEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/billing.xml 2>/dev/null`,
    'echo BILLING_DONE',
  ].join('\n');
  const billingOk = await shOk(billingCmd, 'BILLING_DONE', 15);
  console.log(`  billing.xml: ${billingOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 9: PlayAutoInstallConfig.xml (disable purchase verification)
  console.log('\n[9] Writing PlayAutoInstallConfig.xml...');
  const autoInstallXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <boolean name="auto_update_enabled" value="true"/>
  <boolean name="skip_purchase_verification" value="true"/>
  <boolean name="parental_controls_enabled" value="false"/>
  <int name="content_rating_level" value="0"/>
  <boolean name="in_app_purchase_ask_every_time" value="false"/>
</map>`;
  const autoCmd = [
    `cat > ${vendingDir}/PlayAutoInstallConfig.xml << 'AUTOEOF'`,
    autoInstallXml,
    'AUTOEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.vending/ 2>/dev/null) ${vendingDir}/PlayAutoInstallConfig.xml 2>/dev/null`,
    'echo AUTO_DONE',
  ].join('\n');
  const autoOk = await shOk(autoCmd, 'AUTO_DONE', 15);
  console.log(`  PlayAutoInstallConfig.xml: ${autoOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 10: COIN.xml (zero-auth flags for Google Pay)
  console.log('\n[10] Writing COIN.xml (zero-auth payment flags)...');
  const authToken = crypto.randomBytes(32).toString('hex');
  const coinXml = `<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
  <boolean name="has_payment_methods" value="true"/>
  <string name="default_instrument_id">instrument_1</string>
  <boolean name="wallet_enabled" value="true"/>
  <boolean name="purchase_requires_auth" value="false"/>
  <boolean name="one_touch_enabled" value="true"/>
  <boolean name="biometric_payment_enabled" value="true"/>
  <string name="auth_token">${authToken}</string>
</map>`;
  const coinCmd = [
    `cat > ${gmsDir}/COIN.xml << 'COINEOF'`,
    coinXml,
    'COINEOF',
    `chown $(stat -c '%u:%g' /data/data/com.google.android.gms/ 2>/dev/null) ${gmsDir}/COIN.xml 2>/dev/null`,
    'echo COIN_DONE',
  ].join('\n');
  const coinOk = await shOk(coinCmd, 'COIN_DONE', 15);
  console.log(`  COIN.xml: ${coinOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 11: Chrome Preferences (signed-in state)
  console.log('\n[11] Writing Chrome Preferences (signed-in)...');
  const chromePrefsDir = '/data/data/com.android.chrome/app_chrome/Default';
  const chromePrefs = JSON.stringify({
    account_info: [{
      account_id: googleId,
      email: GOOGLE_EMAIL,
      full_name: "Samuel Epolu",
      given_name: "Samuel",
      is_child_account: false,
      is_under_advanced_protection: false,
      locale: "en-US",
    }],
    signin: { allowed: true, allowed_on_next_startup: true },
    sync: { has_setup_completed: true, keep_everything_synced: false, requested: true },
  }, null, 2);
  const chromeCmd = [
    `mkdir -p '${chromePrefsDir}' 2>/dev/null`,
    `cat > '${chromePrefsDir}/Preferences' << 'CPEOF'`,
    chromePrefs,
    'CPEOF',
    `chown $(stat -c '%u:%g' /data/data/com.android.chrome/ 2>/dev/null) '${chromePrefsDir}/Preferences' 2>/dev/null`,
    'echo CHROME_DONE',
  ].join('\n');
  const chromeOk = await shOk(chromeCmd, 'CHROME_DONE', 20);
  console.log(`  Chrome Preferences: ${chromeOk ? 'OK' : 'FAIL'}`);
  await sleep(3500);

  // Step 12: restorecon on all modified paths
  console.log('\n[12] Running restorecon...');
  const restoreconOk = await shOk([
    'restorecon -R /data/system_ce/0/ 2>/dev/null || true',
    'restorecon -R /data/system_de/0/ 2>/dev/null || true',
    'restorecon -R /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null || true',
    'restorecon -R /data/data/com.google.android.gsf/shared_prefs/ 2>/dev/null || true',
    'restorecon -R /data/data/com.android.vending/shared_prefs/ 2>/dev/null || true',
    'restorecon -R /data/data/com.android.chrome/app_chrome/ 2>/dev/null || true',
    'echo RESTORE_DONE',
  ].join('; '), 'RESTORE_DONE', 20);
  console.log(`  restorecon: ${restoreconOk ? 'OK' : 'FAIL'}`);

  // ═══ Summary ═══
  const results = {
    'accounts_ce.db': acctCeOk, 'accounts_de.db': acctDeOk,
    'device_registration.xml': gmsOk, 'checkin.xml': recheckinOk,
    'gservices.xml': gsfOk, 'finsky.xml': finskyOk,
    'billing.xml': billingOk, 'PlayAutoInstall.xml': autoOk,
    'COIN.xml': coinOk, 'Chrome Preferences': chromeOk,
    'restorecon': restoreconOk,
  };
  const passed = Object.values(results).filter(Boolean).length;
  const total = Object.keys(results).length;

  console.log('\n═══════════════════════════════════════════════════════════');
  console.log(`INJECTION COMPLETE: ${passed}/${total} targets succeeded`);
  console.log('═══════════════════════════════════════════════════════════');
  Object.entries(results).forEach(([k, v]) => {
    console.log(`  ${v ? '✓' : '✗'} ${k}`);
  });
  console.log(`\nAccount: ${GOOGLE_EMAIL}`);
  console.log(`Android ID: ${androidId}`);
  console.log(`GSF ID: ${gsfId}`);
  console.log(`Age backdated: ${ageDays} days (${new Date((now - profileAge) * 1000).toISOString().slice(0, 10)})`);
  console.log('');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
