#!/usr/bin/env node
/**
 * Genesis Engine Phase Tester for VMOS Pro
 * Tests each phase step-by-step with validation checks
 * 
 * Usage: node genesis-phase-tester.js [PAD_CODE] [PHASE]
 * Example: node genesis-phase-tester.js ACP250329ACQRPDV 1
 */

const http = require('http');

const PAD_CODE = process.argv[2] || 'ACP250329ACQRPDV';
const PHASE = parseInt(process.argv[3]) || 0;
const OPS_URL = 'http://localhost:3000';
const DELAY_MS = 3500; // 3.5s between commands (VMOS rate limit)

// ── Shell executor ──────────────────────────────────────────
function shell(cmd, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => reject(new Error('Timeout')), timeout);
    const body = JSON.stringify({ command: cmd.slice(0, 4000) });
    const req = http.request(`${OPS_URL}/api/instances/${PAD_CODE}/shell`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        clearTimeout(timeoutId);
        try { resolve(JSON.parse(data)); } catch { resolve({ output: data, ok: false }); }
      });
    });
    req.on('error', (e) => { clearTimeout(timeoutId); reject(e); });
    req.write(body);
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function log(phase, step, msg, status = 'INFO') {
  const icon = status === 'PASS' ? '✅' : status === 'FAIL' ? '❌' : status === 'WARN' ? '⚠️' : '→';
  console.log(`[Phase ${phase}][${step}] ${icon} ${msg}`);
}

// ══════════════════════════════════════════════════════════════
// PHASE 0: PRE-FLIGHT CHECKS
// ══════════════════════════════════════════════════════════════
async function phase0() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 0: PRE-FLIGHT CHECKS');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0 };
  
  // Test 1: Device alive
  log(0, 'alive', 'Checking device responsiveness...');
  const alive = await shell('echo ALIVE && id');
  if (alive.output?.includes('ALIVE')) {
    log(0, 'alive', `Device responding: ${alive.output.split('\n')[1]?.trim()}`, 'PASS');
    results.passed++;
  } else {
    log(0, 'alive', 'Device not responding!', 'FAIL');
    results.failed++;
    return results;
  }
  await sleep(DELAY_MS);
  
  // Test 2: Root access
  log(0, 'root', 'Checking root access...');
  const root = await shell('id | grep -q "uid=0" && echo ROOT_OK');
  if (root.output?.includes('ROOT_OK')) {
    log(0, 'root', 'Root access confirmed (uid=0)', 'PASS');
    results.passed++;
  } else {
    log(0, 'root', 'No root access! Enable root via Expansion Tools', 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Test 3: Storage space
  log(0, 'storage', 'Checking /data storage...');
  const storage = await shell("df /data | tail -1 | awk '{print $4}'");
  const freeKb = parseInt(storage.output?.trim() || '0');
  const freeGb = (freeKb / 1024 / 1024).toFixed(1);
  if (freeKb > 5 * 1024 * 1024) { // >5GB
    log(0, 'storage', `${freeGb}GB free on /data`, 'PASS');
    results.passed++;
  } else if (freeKb > 1 * 1024 * 1024) { // >1GB
    log(0, 'storage', `Only ${freeGb}GB free - may have issues`, 'WARN');
    results.warnings++;
  } else {
    log(0, 'storage', `Insufficient storage: ${freeGb}GB`, 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Test 4: Magisk presence
  log(0, 'magisk', 'Checking Magisk installation...');
  const magisk = await shell('which magisk 2>/dev/null && magisk --version 2>/dev/null || echo NO_MAGISK');
  if (magisk.output?.includes('NO_MAGISK') || !magisk.output?.trim()) {
    log(0, 'magisk', 'Magisk NOT installed - Phase 1 must enable it', 'WARN');
    results.warnings++;
  } else {
    log(0, 'magisk', `Magisk found: ${magisk.output.trim()}`, 'PASS');
    results.passed++;
  }
  await sleep(DELAY_MS);
  
  // Test 5: resetprop presence
  log(0, 'resetprop', 'Checking resetprop availability...');
  const resetprop = await shell('which resetprop 2>/dev/null || echo NO_RESETPROP');
  if (resetprop.output?.includes('NO_RESETPROP')) {
    log(0, 'resetprop', 'resetprop NOT available - requires Magisk', 'WARN');
    results.warnings++;
  } else {
    log(0, 'resetprop', 'resetprop available', 'PASS');
    results.passed++;
  }
  await sleep(DELAY_MS);
  
  // Test 6: sqlite3 presence
  log(0, 'sqlite3', 'Checking sqlite3 binary...');
  const sqlite3 = await shell('which sqlite3 2>/dev/null || echo NO_SQLITE3');
  if (sqlite3.output?.includes('NO_SQLITE3')) {
    log(0, 'sqlite3', 'sqlite3 NOT on device - must push pre-built DBs', 'WARN');
    results.warnings++;
  } else {
    log(0, 'sqlite3', 'sqlite3 available', 'PASS');
    results.passed++;
  }
  await sleep(DELAY_MS);
  
  // Test 7: Toybox tools
  log(0, 'tools', 'Checking available tools...');
  const tools = await shell('toybox --help 2>/dev/null | head -1');
  const toolCount = tools.output?.match(/\d+/)?.[0] || '?';
  log(0, 'tools', `Toybox with ${toolCount} commands`, 'PASS');
  results.passed++;
  
  console.log(`\n─── Phase 0 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 1: SANITIZATION - DETECTION VECTOR CHECK
// ══════════════════════════════════════════════════════════════
async function phase1() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 1: DETECTION VECTOR ANALYSIS');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0, vectors: [] };
  
  // Test 1: Count ro.* property leaks
  log(1, 'props', 'Scanning for property detection vectors...');
  await sleep(DELAY_MS);
  
  const propCheck = await shell(`getprop | grep -iE "qemu|goldfish|vmos|cloud|rockchip|rk3588|ossi|vcloud|armcloud|xu_daemon|cloudservice" | wc -l`);
  const propLeaks = parseInt(propCheck.output?.trim() || '0');
  
  if (propLeaks === 0) {
    log(1, 'props', 'No property leaks detected!', 'PASS');
    results.passed++;
  } else {
    log(1, 'props', `${propLeaks} property leaks detected`, 'FAIL');
    results.failed++;
    results.vectors.push({ type: 'props', count: propLeaks });
    
    // List specific leaks
    const leaks = await shell(`getprop | grep -iE "qemu|goldfish|vmos|cloud|rockchip|rk3588|ossi|vcloud|armcloud" | head -10`);
    console.log('    Sample leaks:');
    leaks.output?.split('\n').slice(0, 5).forEach(l => console.log(`      ${l.trim()}`));
  }
  await sleep(DELAY_MS);
  
  // Test 2: Process leaks
  log(1, 'procs', 'Scanning for process detection vectors...');
  const procCheck = await shell(`ps -A | grep -iE "cloudservice|xu_daemon|rockchip" | grep -v grep | wc -l`);
  const procLeaks = parseInt(procCheck.output?.trim() || '0');
  
  if (procLeaks === 0) {
    log(1, 'procs', 'No process leaks detected!', 'PASS');
    results.passed++;
  } else {
    log(1, 'procs', `${procLeaks} process leaks detected (need Zygisk)`, 'WARN');
    results.warnings++;
    results.vectors.push({ type: 'procs', count: procLeaks });
  }
  await sleep(DELAY_MS);
  
  // Test 3: /proc/cmdline leaks
  log(1, 'cmdline', 'Scanning /proc/cmdline...');
  const cmdlineCheck = await shell(`cat /proc/cmdline | grep -oE "overlayroot|PARTLABEL=rootfs|storagemedia=emmc|verifiedbootstate=orange" | wc -w`);
  const cmdlineLeaks = parseInt(cmdlineCheck.output?.trim() || '0');
  
  if (cmdlineLeaks === 0) {
    log(1, 'cmdline', '/proc/cmdline is clean', 'PASS');
    results.passed++;
  } else {
    log(1, 'cmdline', `${cmdlineLeaks} cmdline leaks (need bind-mount)`, 'FAIL');
    results.failed++;
    results.vectors.push({ type: 'cmdline', count: cmdlineLeaks });
  }
  await sleep(DELAY_MS);
  
  // Test 4: Loop device count
  log(1, 'loops', 'Checking loop device count...');
  const loopCheck = await shell(`ls -1 /dev/block/loop* 2>/dev/null | wc -l`);
  const loopCount = parseInt(loopCheck.output?.trim() || '0');
  
  if (loopCount < 10) {
    log(1, 'loops', `${loopCount} loop devices (normal)`, 'PASS');
    results.passed++;
  } else {
    log(1, 'loops', `${loopCount} loop devices (container signature - need LSPosed hook)`, 'WARN');
    results.warnings++;
    results.vectors.push({ type: 'loops', count: loopCount });
  }
  await sleep(DELAY_MS);
  
  // Test 5: GPU leak
  log(1, 'gpu', 'Checking GPU identity...');
  const gpuCheck = await shell(`getprop ro.hardware.egl`);
  const gpu = gpuCheck.output?.trim() || '';
  
  if (gpu === 'adreno' || gpu === '') {
    log(1, 'gpu', `GPU: ${gpu || '(default)'}`, 'PASS');
    results.passed++;
  } else if (gpu === 'mali') {
    log(1, 'gpu', `GPU: mali (should be adreno for OnePlus)`, 'FAIL');
    results.failed++;
    results.vectors.push({ type: 'gpu', value: gpu });
  }
  await sleep(DELAY_MS);
  
  // Test 6: Verified boot state
  log(1, 'vbmeta', 'Checking verified boot state...');
  const vbCheck = await shell(`getprop ro.boot.verifiedbootstate`);
  const vbState = vbCheck.output?.trim() || '';
  
  if (vbState === 'green') {
    log(1, 'vbmeta', 'Verified boot: green', 'PASS');
    results.passed++;
  } else {
    log(1, 'vbmeta', `Verified boot: ${vbState} (should be green)`, 'FAIL');
    results.failed++;
    results.vectors.push({ type: 'vbmeta', value: vbState });
  }
  await sleep(DELAY_MS);
  
  // Test 7: Build type
  log(1, 'build', 'Checking build type...');
  const buildCheck = await shell(`getprop ro.build.type`);
  const buildType = buildCheck.output?.trim() || '';
  
  if (buildType === 'user') {
    log(1, 'build', 'Build type: user', 'PASS');
    results.passed++;
  } else {
    log(1, 'build', `Build type: ${buildType} (should be user)`, 'FAIL');
    results.failed++;
    results.vectors.push({ type: 'build', value: buildType });
  }
  
  console.log(`\n─── Phase 1 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───`);
  console.log(`─── Total detection vectors: ${results.vectors.reduce((a, v) => a + (v.count || 1), 0)} ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 2: DEVICE IDENTITY CHECK
// ══════════════════════════════════════════════════════════════
async function phase2() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 2: DEVICE IDENTITY VERIFICATION');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0 };
  
  // Check device model
  log(2, 'model', 'Checking device model...');
  const model = await shell(`getprop ro.product.model`);
  const modelVal = model.output?.trim() || '';
  console.log(`    ro.product.model: ${modelVal}`);
  
  if (modelVal && !modelVal.toLowerCase().includes('vcloud') && !modelVal.toLowerCase().includes('ossi')) {
    log(2, 'model', `Model appears clean: ${modelVal}`, 'PASS');
    results.passed++;
  } else {
    log(2, 'model', `Model may leak: ${modelVal}`, 'WARN');
    results.warnings++;
  }
  await sleep(DELAY_MS);
  
  // Check brand
  log(2, 'brand', 'Checking device brand...');
  const brand = await shell(`getprop ro.product.brand`);
  console.log(`    ro.product.brand: ${brand.output?.trim()}`);
  await sleep(DELAY_MS);
  
  // Check fingerprint
  log(2, 'fingerprint', 'Checking build fingerprint...');
  const fp = await shell(`getprop ro.build.fingerprint`);
  const fpVal = fp.output?.trim() || '';
  console.log(`    ro.build.fingerprint: ${fpVal.slice(0, 60)}...`);
  
  if (fpVal.includes('vcloud') || fpVal.includes('minical')) {
    log(2, 'fingerprint', 'Fingerprint contains vcloud/minical leak!', 'FAIL');
    results.failed++;
  } else {
    log(2, 'fingerprint', 'Fingerprint appears clean', 'PASS');
    results.passed++;
  }
  await sleep(DELAY_MS);
  
  // Check serial
  log(2, 'serial', 'Checking serial number...');
  const serial = await shell(`getprop ro.serialno`);
  console.log(`    ro.serialno: ${serial.output?.trim()}`);
  await sleep(DELAY_MS);
  
  // Check SIM
  log(2, 'sim', 'Checking SIM state...');
  const sim = await shell(`getprop gsm.sim.state`);
  const simState = sim.output?.trim() || '';
  
  if (simState === 'READY') {
    log(2, 'sim', `SIM state: ${simState}`, 'PASS');
    results.passed++;
  } else {
    log(2, 'sim', `SIM state: ${simState} (should be READY)`, 'WARN');
    results.warnings++;
  }
  
  console.log(`\n─── Phase 2 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 3: AGING VERIFICATION
// ══════════════════════════════════════════════════════════════
async function phase3() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 3: DEVICE AGING VERIFICATION');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0 };
  
  // Check /data timestamp
  log(3, 'data_ts', 'Checking /data timestamp...');
  const dataTs = await shell(`stat -c %y /data | cut -d' ' -f1`);
  const dataDate = dataTs.output?.trim() || '';
  console.log(`    /data modified: ${dataDate}`);
  
  const now = new Date();
  const dataParsed = new Date(dataDate);
  const daysDiff = Math.floor((now - dataParsed) / (1000 * 60 * 60 * 24));
  
  if (daysDiff >= 90) {
    log(3, 'data_ts', `Device appears ${daysDiff} days old`, 'PASS');
    results.passed++;
  } else if (daysDiff >= 30) {
    log(3, 'data_ts', `Device only ${daysDiff} days old (target: 90+)`, 'WARN');
    results.warnings++;
  } else {
    log(3, 'data_ts', `Device too new: ${daysDiff} days`, 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check UsageStats
  log(3, 'usage', 'Checking UsageStats files...');
  const usageCount = await shell(`ls -1 /data/system/usagestats/0/daily/ 2>/dev/null | wc -l`);
  const usageFiles = parseInt(usageCount.output?.trim() || '0');
  
  if (usageFiles >= 90) {
    log(3, 'usage', `${usageFiles} UsageStats daily files`, 'PASS');
    results.passed++;
  } else if (usageFiles >= 30) {
    log(3, 'usage', `Only ${usageFiles} UsageStats files (target: 90+)`, 'WARN');
    results.warnings++;
  } else {
    log(3, 'usage', `Too few UsageStats files: ${usageFiles}`, 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check GMS timestamp
  log(3, 'gms', 'Checking GMS installation date...');
  const gmsTs = await shell(`stat -c %y /data/data/com.google.android.gms 2>/dev/null | cut -d' ' -f1`);
  console.log(`    GMS installed: ${gmsTs.output?.trim() || 'N/A'}`);
  await sleep(DELAY_MS);
  
  // Check photos
  log(3, 'photos', 'Checking gallery photos...');
  const photoCount = await shell(`ls -1 /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l`);
  const photos = parseInt(photoCount.output?.trim() || '0');
  
  if (photos >= 100) {
    log(3, 'photos', `${photos} photos in gallery`, 'PASS');
    results.passed++;
  } else if (photos >= 20) {
    log(3, 'photos', `Only ${photos} photos (target: 100+)`, 'WARN');
    results.warnings++;
  } else {
    log(3, 'photos', `Too few photos: ${photos}`, 'FAIL');
    results.failed++;
  }
  
  console.log(`\n─── Phase 3 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 5: ACCOUNT VERIFICATION
// ══════════════════════════════════════════════════════════════
async function phase5() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 5: GOOGLE ACCOUNT VERIFICATION');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0 };
  
  // Check account in dumpsys
  log(5, 'account', 'Checking Google account...');
  const acct = await shell(`dumpsys account | grep -A1 "Account {" | grep "com.google" | head -1`);
  const acctLine = acct.output?.trim() || '';
  
  if (acctLine.includes('com.google')) {
    const email = acctLine.match(/name=([^,]+)/)?.[1] || 'unknown';
    log(5, 'account', `Account found: ${email}`, 'PASS');
    results.passed++;
  } else {
    log(5, 'account', 'No Google account found!', 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check Play Store prefs
  log(5, 'playstore', 'Checking Play Store configuration...');
  const finsky = await shell(`cat /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null | grep -c "signed_in"`);
  const hasSignIn = parseInt(finsky.output?.trim() || '0') > 0;
  
  if (hasSignIn) {
    log(5, 'playstore', 'Play Store has signed_in config', 'PASS');
    results.passed++;
  } else {
    log(5, 'playstore', 'Play Store missing signed_in config', 'WARN');
    results.warnings++;
  }
  await sleep(DELAY_MS);
  
  // Check GMS prefs
  log(5, 'gms', 'Checking GMS device registration...');
  const gmsReg = await shell(`ls /data/data/com.google.android.gms/shared_prefs/device_registration.xml 2>/dev/null`);
  
  if (gmsReg.output?.includes('device_registration.xml')) {
    log(5, 'gms', 'GMS device_registration.xml exists', 'PASS');
    results.passed++;
  } else {
    log(5, 'gms', 'GMS device_registration.xml missing', 'FAIL');
    results.failed++;
  }
  
  console.log(`\n─── Phase 5 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 7: DATA INJECTION VERIFICATION
// ══════════════════════════════════════════════════════════════
async function phase7() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 7: DATA INJECTION VERIFICATION');
  console.log('═══════════════════════════════════════════════════════\n');
  
  const results = { passed: 0, failed: 0, warnings: 0 };
  
  // Check contacts
  log(7, 'contacts', 'Checking contacts database...');
  const contactsDb = await shell(`ls -la /data/data/com.android.providers.contacts/databases/contacts2.db 2>/dev/null`);
  
  if (contactsDb.output?.includes('contacts2.db')) {
    log(7, 'contacts', 'contacts2.db exists', 'PASS');
    results.passed++;
  } else {
    log(7, 'contacts', 'contacts2.db missing', 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check call log
  log(7, 'calls', 'Checking call log database...');
  const callDb = await shell(`ls -la /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null`);
  
  if (callDb.output?.includes('calllog.db')) {
    log(7, 'calls', 'calllog.db exists', 'PASS');
    results.passed++;
  } else {
    log(7, 'calls', 'calllog.db missing', 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check SMS
  log(7, 'sms', 'Checking SMS database...');
  const smsDb = await shell(`ls -la /data/data/com.android.providers.telephony/databases/mmssms.db 2>/dev/null`);
  
  if (smsDb.output?.includes('mmssms.db')) {
    log(7, 'sms', 'mmssms.db exists', 'PASS');
    results.passed++;
  } else {
    log(7, 'sms', 'mmssms.db missing', 'FAIL');
    results.failed++;
  }
  await sleep(DELAY_MS);
  
  // Check Chrome history
  log(7, 'chrome', 'Checking Chrome data...');
  const chromeHist = await shell(`ls -la /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null`);
  
  if (chromeHist.output?.includes('History')) {
    log(7, 'chrome', 'Chrome History exists', 'PASS');
    results.passed++;
  } else {
    log(7, 'chrome', 'Chrome History missing', 'WARN');
    results.warnings++;
  }
  await sleep(DELAY_MS);
  
  // Check WiFi
  log(7, 'wifi', 'Checking WiFi configuration...');
  const wifi = await shell(`cat /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null | grep -c "SSID" || echo 0`);
  const wifiCount = parseInt(wifi.output?.trim() || '0');
  
  if (wifiCount >= 5) {
    log(7, 'wifi', `${wifiCount} WiFi networks configured`, 'PASS');
    results.passed++;
  } else if (wifiCount > 0) {
    log(7, 'wifi', `Only ${wifiCount} WiFi networks (target: 5+)`, 'WARN');
    results.warnings++;
  } else {
    log(7, 'wifi', 'No WiFi networks configured', 'FAIL');
    results.failed++;
  }
  
  console.log(`\n─── Phase 7 Summary: ${results.passed} passed, ${results.failed} failed, ${results.warnings} warnings ───\n`);
  return results;
}

// ══════════════════════════════════════════════════════════════
// PHASE 12: TRUST SCORE CALCULATION
// ══════════════════════════════════════════════════════════════
async function phase12() {
  console.log('\n═══════════════════════════════════════════════════════');
  console.log('  PHASE 12: TRUST SCORE CALCULATION');
  console.log('═══════════════════════════════════════════════════════\n');
  
  let score = 0;
  const checks = [];
  
  // 1. Google Account (12 pts)
  const acct = await shell(`dumpsys account | grep -c "com.google" 2>/dev/null`);
  const hasAccount = parseInt(acct.output?.trim() || '0') > 0;
  if (hasAccount) { score += 12; checks.push({ name: 'Google Account', points: 12, status: 'PASS' }); }
  else { checks.push({ name: 'Google Account', points: 0, status: 'FAIL', max: 12 }); }
  await sleep(DELAY_MS);
  
  // 2. Chrome Cookies (8 pts)
  const cookies = await shell(`ls -la /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null`);
  const hasCookies = cookies.output?.includes('Cookies');
  if (hasCookies) { score += 8; checks.push({ name: 'Chrome Cookies', points: 8, status: 'PASS' }); }
  else { checks.push({ name: 'Chrome Cookies', points: 0, status: 'FAIL', max: 8 }); }
  await sleep(DELAY_MS);
  
  // 3. Chrome History (8 pts)
  const history = await shell(`ls -la /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null`);
  const hasHistory = history.output?.includes('History');
  if (hasHistory) { score += 8; checks.push({ name: 'Chrome History', points: 8, status: 'PASS' }); }
  else { checks.push({ name: 'Chrome History', points: 0, status: 'FAIL', max: 8 }); }
  await sleep(DELAY_MS);
  
  // 4. Contacts (7 pts)
  const contacts = await shell(`ls -la /data/data/com.android.providers.contacts/databases/contacts2.db 2>/dev/null`);
  const hasContacts = contacts.output?.includes('contacts2.db');
  if (hasContacts) { score += 7; checks.push({ name: 'Contacts DB', points: 7, status: 'PASS' }); }
  else { checks.push({ name: 'Contacts DB', points: 0, status: 'FAIL', max: 7 }); }
  await sleep(DELAY_MS);
  
  // 5. Call Logs (7 pts)
  const calls = await shell(`ls -la /data/data/com.android.providers.contacts/databases/calllog.db 2>/dev/null`);
  const hasCalls = calls.output?.includes('calllog.db');
  if (hasCalls) { score += 7; checks.push({ name: 'Call Logs', points: 7, status: 'PASS' }); }
  else { checks.push({ name: 'Call Logs', points: 0, status: 'FAIL', max: 7 }); }
  await sleep(DELAY_MS);
  
  // 6. SMS (6 pts)
  const sms = await shell(`ls -la /data/data/com.android.providers.telephony/databases/mmssms.db 2>/dev/null`);
  const hasSms = sms.output?.includes('mmssms.db');
  if (hasSms) { score += 6; checks.push({ name: 'SMS DB', points: 6, status: 'PASS' }); }
  else { checks.push({ name: 'SMS DB', points: 0, status: 'FAIL', max: 6 }); }
  await sleep(DELAY_MS);
  
  // 7. UsageStats (5 pts)
  const usage = await shell(`ls -1 /data/system/usagestats/0/daily/ 2>/dev/null | wc -l`);
  const usageCount = parseInt(usage.output?.trim() || '0');
  if (usageCount >= 30) { score += 5; checks.push({ name: 'UsageStats', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'UsageStats', points: 0, status: 'FAIL', max: 5 }); }
  await sleep(DELAY_MS);
  
  // 8. WiFi Networks (5 pts)
  const wifi = await shell(`cat /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null | grep -c "SSID" || echo 0`);
  const wifiCount = parseInt(wifi.output?.trim() || '0');
  if (wifiCount >= 3) { score += 5; checks.push({ name: 'WiFi Networks', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'WiFi Networks', points: 0, status: 'FAIL', max: 5 }); }
  await sleep(DELAY_MS);
  
  // 9. Photos (5 pts)
  const photos = await shell(`ls -1 /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l`);
  const photoCount = parseInt(photos.output?.trim() || '0');
  if (photoCount >= 50) { score += 5; checks.push({ name: 'Gallery Photos', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'Gallery Photos', points: 0, status: 'FAIL', max: 5 }); }
  await sleep(DELAY_MS);
  
  // 10. Build Type (5 pts)
  const build = await shell(`getprop ro.build.type`);
  const buildType = build.output?.trim();
  if (buildType === 'user') { score += 5; checks.push({ name: 'Build Type', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'Build Type', points: 0, status: 'FAIL', max: 5 }); }
  await sleep(DELAY_MS);
  
  // 11. Verified Boot (5 pts)
  const vb = await shell(`getprop ro.boot.verifiedbootstate`);
  const vbState = vb.output?.trim();
  if (vbState === 'green') { score += 5; checks.push({ name: 'Verified Boot', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'Verified Boot', points: 0, status: 'FAIL', max: 5 }); }
  await sleep(DELAY_MS);
  
  // 12. No VMOS Leaks (5 pts)
  const vmos = await shell(`getprop | grep -ciE "vmos|vcloud|armcloud|cloudservice" 2>/dev/null`);
  const vmosLeaks = parseInt(vmos.output?.trim() || '0');
  if (vmosLeaks === 0) { score += 5; checks.push({ name: 'No VMOS Leaks', points: 5, status: 'PASS' }); }
  else { checks.push({ name: 'No VMOS Leaks', points: 0, status: 'FAIL', max: 5 }); }
  
  // Print results
  console.log('┌────────────────────────────┬────────┬────────┐');
  console.log('│ Check                      │ Points │ Status │');
  console.log('├────────────────────────────┼────────┼────────┤');
  checks.forEach(c => {
    const name = c.name.padEnd(26);
    const pts = c.status === 'PASS' ? `+${c.points}`.padStart(6) : `0/${c.max}`.padStart(6);
    const status = c.status === 'PASS' ? ' ✅  ' : ' ❌  ';
    console.log(`│ ${name} │ ${pts} │${status} │`);
  });
  console.log('├────────────────────────────┼────────┼────────┤');
  console.log(`│ TOTAL SCORE                │ ${String(score).padStart(3)}/88 │        │`);
  console.log('└────────────────────────────┴────────┴────────┘');
  
  // Grade
  let grade;
  if (score >= 80) grade = 'A';
  else if (score >= 70) grade = 'B';
  else if (score >= 60) grade = 'C';
  else if (score >= 50) grade = 'D';
  else grade = 'F';
  
  console.log(`\n═══════════════════════════════════════════════════════`);
  console.log(`  TRUST SCORE: ${score}/88 (${Math.round(score/88*100)}%) — Grade: ${grade}`);
  console.log(`═══════════════════════════════════════════════════════\n`);
  
  return { score, grade, checks };
}

// ══════════════════════════════════════════════════════════════
// MAIN
// ══════════════════════════════════════════════════════════════
async function main() {
  console.log('╔═══════════════════════════════════════════════════════╗');
  console.log('║     GENESIS ENGINE PHASE TESTER — VMOS PRO            ║');
  console.log('╠═══════════════════════════════════════════════════════╣');
  console.log(`║  Device: ${PAD_CODE.padEnd(43)} ║`);
  console.log(`║  Phase:  ${PHASE === 0 ? 'ALL' : PHASE.toString().padEnd(43)} ║`);
  console.log('╚═══════════════════════════════════════════════════════╝');
  
  const phases = {
    0: phase0,
    1: phase1,
    2: phase2,
    3: phase3,
    5: phase5,
    7: phase7,
    12: phase12,
  };
  
  if (PHASE === 0) {
    // Run all phases
    for (const [num, fn] of Object.entries(phases)) {
      await fn();
      await sleep(2000);
    }
  } else if (phases[PHASE]) {
    await phases[PHASE]();
  } else {
    console.log(`\nUnknown phase: ${PHASE}`);
    console.log('Available phases: 0 (pre-flight), 1 (detection), 2 (identity), 3 (aging), 5 (account), 7 (data), 12 (trust score)');
    process.exit(1);
  }
}

main().catch(e => {
  console.error('Error:', e.message);
  process.exit(1);
});
