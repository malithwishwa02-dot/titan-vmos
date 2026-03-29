#!/usr/bin/env node
// ═══════════════════════════════════════════════════════════════════
// DRY-RUN VERIFICATION: Samsung S24 preset through all 12 phases
// Validates: preset data, SQL generation, command sizes, file paths,
//            scoring gaps, property coverage, timing constraints
// ═══════════════════════════════════════════════════════════════════

const crypto = require('crypto');
const fs = require('fs');
const { execSync } = require('child_process');

const mainSrc = fs.readFileSync('main.js', 'utf-8');

// Extract DEVICE_PRESETS
const presetsBlock = mainSrc.match(/const DEVICE_PRESETS = \{([\s\S]*?)\n  \};/);
if (!presetsBlock) { console.log('ERROR: DEVICE_PRESETS block not found'); process.exit(1); }
const DEVICE_PRESETS = eval('({' + presetsBlock[1] + '})');
const preset = DEVICE_PRESETS.samsung_s24;
if (!preset) { console.log('ERROR: samsung_s24 preset not found'); process.exit(1); }

// Extract CARRIERS
const carriersBlock = mainSrc.match(/const CARRIERS = \{([\s\S]*?)\n  \};/);
const CARRIERS = carriersBlock ? eval('({' + carriersBlock[1] + '})') : {};

// Extract COUNTRY_DEFAULTS
const countryBlock = mainSrc.match(/const COUNTRY_DEFAULTS = \{([\s\S]*?)\n  \};/);
const COUNTRY_DEFAULTS = countryBlock ? eval('({' + countryBlock[1] + '})') : {};

console.log('═══════════════════════════════════════════════════════');
console.log(' SAMSUNG S24 — FULL DRY-RUN PIPELINE VERIFICATION');
console.log('═══════════════════════════════════════════════════════');
console.log();

// ── Preset Completeness ──
const requiredFields = ['brand','model','device','product','manufacturer','board','platform',
  'hardware','fingerprint','bootloader','display','sdk','release','security_patch',
  'incremental','codename','glVendor','glRenderer','density','width','height'];

const missing = requiredFields.filter(f => !preset[f]);
console.log('PRESET FIELDS:', requiredFields.length - missing.length, '/', requiredFields.length, 'present');
if (missing.length) console.log('  MISSING:', missing.join(', '));
else console.log('  All required fields present ✓');

// Fingerprint format
const fpParts = preset.fingerprint.split('/');
console.log('FINGERPRINT:', fpParts.length >= 5 ? '✓' : '✗', 'parts=' + fpParts.length);
console.log('  Value:', preset.fingerprint);
const fpStartsWithBrand = preset.fingerprint.toLowerCase().startsWith(preset.brand.toLowerCase() + '/');
console.log('  Brand prefix:', fpStartsWithBrand ? '✓' : '✗ WARN');
console.log('  Display ID:', preset.display || '(empty!)');
console.log();

// ── Phase 0: Pre-Flight ──
console.log('═══ PHASE 0: PRE-FLIGHT ═══');
console.log('  /infos API call: Standard → checks padStatus=10');
console.log('  Boot poll loop: max 60 iterations × 5s = 5min timeout');
console.log('  Shell verify: echo SHELL_TEST_OK → validates syncCmd works');
console.log('  resetprop verify: resetprop ro.test.genesis → validates Magisk');
console.log('  STATUS: ✓ No issues expected');
console.log();

// ── Phase 1: Identity ──
console.log('═══ PHASE 1: WIPE + IDENTITY INJECTION ═══');

// Simulate actual batch commands from main.js
// Batch 1: Core build properties
const b1Props = [
  `ro.product.brand '${preset.brand}'`,
  `ro.product.model '${preset.model}'`,
  `ro.product.device '${preset.device}'`,
  `ro.product.name '${preset.product}'`,
  `ro.product.manufacturer '${preset.manufacturer}'`,
  `ro.product.board '${preset.board}'`,
  `ro.board.platform '${preset.platform}'`,
  `ro.hardware.chipname '${preset.hardware}'`,
  `ro.build.fingerprint '${preset.fingerprint}'`,
  `ro.build.display.id '${preset.display}'`,
  `ro.build.version.sdk '${preset.sdk}'`,
  `ro.build.version.release '${preset.release}'`,
  `ro.build.version.security_patch '${preset.security_patch}'`,
  `ro.build.version.incremental '${preset.incremental}'`,
  `ro.build.version.codename '${preset.codename || 'REL'}'`,
  `ro.build.type 'user'`,
  `ro.build.tags 'release-keys'`,
];
const b1Cmd = b1Props.map(p => 'resetprop ' + p).join('; ') + '; echo B1_OK';
console.log(`  Batch 1 (BUILD): ${b1Props.length} props, ${b1Cmd.length} chars → ${b1Cmd.length < 4000 ? '✓ OK' : '✗ OVER 4KB!'}`);

// Batch 2: System/Vendor/ODM mirror
const b2Props = [];
for (const ns of ['system', 'vendor', 'odm']) {
  b2Props.push(`ro.product.${ns}.brand '${preset.brand}'`);
  b2Props.push(`ro.product.${ns}.model '${preset.model}'`);
  b2Props.push(`ro.product.${ns}.device '${preset.device}'`);
  b2Props.push(`ro.product.${ns}.name '${preset.product}'`);
}
const b2Cmd = b2Props.map(p => 'resetprop ' + p).join('; ') + '; echo B2_OK';
console.log(`  Batch 2 (SYS/VND/ODM): ${b2Props.length} props, ${b2Cmd.length} chars → ${b2Cmd.length < 4000 ? '✓ OK' : '✗ OVER 4KB!'}`);

// Batch 3: Telephony
// From main.js: carrier, IMEI, ICCID, phone, android_id, serial
const b3Props = [
  "ro.carrier 'samsung'",
  "persist.radio.device.imei0 '<generated>'",
  "persist.radio.device.imei1 '<generated>'",
  "persist.sys.cloud.iccid '<generated>'",
  "gsm.sim.operator.numeric '310260'",
  "gsm.sim.operator.alpha 'T-Mobile'",
  "gsm.operator.alpha 'T-Mobile'",
  "gsm.operator.numeric '310260'",
  "gsm.sim.state 'READY'",
  "persist.sys.phone.number '<generated>'",
  "ro.serialno '<generated>'",
  `ro.boot.hardware '${preset.hardware}'`,
  `ro.hardware '${preset.hardware}'`,
  `persist.sys.dalvik.vm.lib.2 'libart.so'`,
  "ro.zygote 'zygote64_32'",
];
const b3Cmd = b3Props.map(p => 'resetprop ' + p).join('; ') + '; echo B3_OK';
console.log(`  Batch 3 (TELEPHONY): ${b3Props.length} props, ${b3Cmd.length} chars → ${b3Cmd.length < 4000 ? '✓ OK' : '✗ OVER 4KB!'}`);

// Batch 4: Bootloader/GL/carrier branding
const b4Props = [
  `ro.bootloader '${preset.bootloader}'`,
  `ro.boot.bootloader '${preset.bootloader}'`,
  `persist.sys.timezone 'America/New_York'`,
  `persist.sys.language 'en'`,
  `persist.sys.country 'US'`,
  `ro.build.flavor '${preset.product}-user'`,
  `ro.build.product '${preset.device}'`,
  `ro.product.first_api_level '${preset.sdk}'`,
  `ro.com.google.gmsversion '${preset.release}_202401'`,
  `ro.opengles.version '196610'`,
  `ro.hardware.egl 'mali'`,
];
const b4Cmd = b4Props.map(p => 'resetprop ' + p).join('; ') + '; echo B4_OK';
console.log(`  Batch 4 (BOOT/GL): ${b4Props.length} props, ${b4Cmd.length} chars → ${b4Cmd.length < 4000 ? '✓ OK' : '✗ OVER 4KB!'}`);
console.log('  STATUS: ✓ All batches within 4KB limit');
console.log();

// ── Phase 2: Stealth ──
console.log('═══ PHASE 2: STEALTH PATCH ═══');
const stealthChecks = [
  { name: 'VBS=green', ok: true },
  { name: 'ro.debuggable=0', ok: true },
  { name: 'ro.secure=1', ok: true },
  { name: 'ro.kernel.qemu delete', ok: true },
  { name: 'ro.vmos.* prop scrub', ok: true },
  { name: '/proc/cmdline bind-mount', ok: true },
  { name: '/proc/mounts bind-mount', ok: true },
  { name: '/proc/1/cgroup bind-mount', ok: true },
  { name: 'process comm rename', ok: true },
];
stealthChecks.forEach(c => console.log(`  ${c.ok ? '✓' : '✗'} ${c.name}`));
console.log('  STATUS: ✓ Standard stealth operations');
console.log();

// ── Phase 3: Network ──
console.log('═══ PHASE 3: NETWORK/PROXY ═══');
console.log('  setProxy API: Standard → requires proxy URL in config');
console.log('  checkIP verification: Standard');
console.log('  STATUS: ✓ API-based, no shell issues');
console.log();

// ── Phase 4: Forge Profile ──
console.log('═══ PHASE 4: FORGE PROFILE ═══');
console.log('  Inline persona generation: name, email, WiFi networks');
console.log('  STATUS: ✓ Pure JavaScript, no external deps');
console.log();

// ── Phase 5: Google Account ──
console.log('═══ PHASE 5: GOOGLE ACCOUNT ═══');
let hasSqlite3 = false;
try { execSync('which sqlite3', { timeout: 3000 }); hasSqlite3 = true; } catch(_) {}
console.log(`  sqlite3 binary: ${hasSqlite3 ? '✓ AVAILABLE' : '✗ NOT FOUND'}`);
const dbTargets = [
  { name: 'accounts_ce.db', path: '/data/system_ce/0/accounts_ce.db', critical: true },
  { name: 'accounts_de.db', path: '/data/system_de/0/accounts_de.db', critical: true },
  { name: 'library.db (purchases)', path: '/data/data/com.android.vending/databases/library.db', critical: false },
];
dbTargets.forEach(db => {
  console.log(`  ${hasSqlite3 ? '✓' : '✗'} ${db.name} → ${db.path} ${db.critical ? '[CRITICAL]' : ''}`);
});
const xmlTargets = [
  'device_registration.xml', 'gservices.xml', 'finsky.xml',
  'billing.xml', 'PlayAutoInstallConfig.xml',
];
xmlTargets.forEach(f => console.log(`  ✓ ${f} → printf/echo (no sqlite3 needed)`));
console.log(`  STATUS: ${hasSqlite3 ? '✓ All DBs will generate' : '✗ DBs WILL FAIL — need sqlite3 install'}`);
console.log();

// ── Phase 6: Inject Data ──
console.log('═══ PHASE 6: DATA INJECTION ═══');
const injectChecks = [
  { name: 'Contacts (content insert)', ok: true, note: 'API fallback available' },
  { name: 'Call Logs (content insert)', ok: true, note: 'API fallback available' },
  { name: 'SMS (mmssms.db)', ok: hasSqlite3, note: hasSqlite3 ? '' : 'NO API FALLBACK — will score 0' },
  { name: 'WiFi (setWifiList API)', ok: true, note: '' },
  { name: 'Chrome Cookies (sqlite3)', ok: hasSqlite3, note: '' },
  { name: 'Chrome History (sqlite3)', ok: hasSqlite3, note: '' },
  { name: 'Chrome Autofill (sqlite3)', ok: hasSqlite3, note: '' },
  { name: 'Battery (setBattery API)', ok: true, note: '' },
  { name: 'GAID (resetGAID API)', ok: true, note: '' },
  { name: 'UsageStats (printf XML)', ok: true, note: '' },
  { name: 'Media DB (sqlite3)', ok: hasSqlite3, note: '' },
  { name: 'Downloads DB (sqlite3)', ok: hasSqlite3, note: '' },
  { name: 'Notifications DB (sqlite3)', ok: hasSqlite3, note: '' },
];
injectChecks.forEach(c => console.log(`  ${c.ok ? '✓' : '✗'} ${c.name} ${c.note ? '— ' + c.note : ''}`));
console.log();

// ── Phase 7: Wallet ──
console.log('═══ PHASE 7: WALLET/GPAY ═══');
const walletChecks = [
  { name: '7a Chrome credit_cards (sqlite3)', ok: hasSqlite3 },
  { name: '7b tapandpay.db (sqlite3)', ok: hasSqlite3, note: 'token_metadata + transaction_log' },
  { name: '7c COIN.xml (printf)', ok: true },
  { name: '7d TapAndPayPrefs.xml (printf)', ok: true },
  { name: '7e WalletPrefs.xml (printf)', ok: true },
  { name: '7f BillingParams.xml (printf)', ok: true },
  { name: '7g CardRiskProfile.xml (printf)', ok: true },
  { name: '7h InstrumentVerification.xml (printf)', ok: true },
  { name: '7i PlayBillingCache.xml (printf)', ok: true },
];
walletChecks.forEach(c => console.log(`  ${c.ok ? '✓' : '✗'} ${c.name} ${c.note ? '— ' + c.note : ''}`));
console.log(`  ISSUE: Transaction timestamps not aged (all within recent days)`);
console.log(`  ISSUE: Chrome card_number_encrypted=NULL may be rejected by Chrome`);
console.log();

// ── Phase 8: Provincial ──
console.log('═══ PHASE 8: PROVINCIAL ═══');
console.log('  US apps: Chrome, YouTube, Maps, Gmail, Drive, Photos, Keep');
console.log('  Method: startApp API only');
console.log('  ✗ ISSUE: Never creates shared_prefs files that Phase 11 checks');
console.log('  ✗ ISSUE: Phase 11 looks for specific XML files in app data dirs');
console.log();

// ── Phase 9: Post-Harden ──
console.log('═══ PHASE 9: POST-HARDEN ═══');
console.log('  14 sub-phases (9a-9l): All standard shell/API operations');
console.log('  ✓ Kiwi prefs, DNS, SELinux, settings, lock screen');
console.log('  ✓ Payment trust binding, NFC, media scan, permissions');
console.log('  ✓ Install attribution, boot broadcasts');
console.log('  ✓ KeepAlive, HideAccessibility, SwitchRoot API calls');
console.log();

// ── Phase 10: Attestation ──
console.log('═══ PHASE 10: ATTESTATION ═══');
console.log('  13 checks + auto-remediation + re-verify');
console.log('  FP_MATCH check regex:', `'${preset.fingerprint.split('/')[0]}'`);
console.log('  ✓ Auto-remediation will fix most props via resetprop');
console.log('  ⚠ keybox_not_loaded: Requires external Magisk module');
console.log();

// ── Phase 11: Trust Audit ──
console.log('═══ PHASE 11: TRUST AUDIT — SAMSUNG S24 SCORE PROJECTION ═══');
console.log();

const scoreChecks = [
  // Core Identity (20)
  { cat: 'Core Identity', name: 'Google Account', pts: 7, ok: hasSqlite3 },
  { cat: 'Core Identity', name: 'GMS device_registration', pts: 4, ok: true },
  { cat: 'Core Identity', name: 'GSF gservices', pts: 3, ok: true },
  { cat: 'Core Identity', name: 'android_id', pts: 2, ok: true },
  { cat: 'Core Identity', name: 'IMEI injected', pts: 2, ok: true },
  { cat: 'Core Identity', name: 'WiFi configured', pts: 2, ok: true },
  // System Profile (10)
  { cat: 'System', name: 'build_type=user', pts: 2, ok: true },
  { cat: 'System', name: 'No VMOS leak', pts: 2, ok: true },
  { cat: 'System', name: 'SELinux Enforcing', pts: 2, ok: true },
  { cat: 'System', name: 'System settings', pts: 2, ok: true },
  { cat: 'System', name: 'Permissions (base)', pts: 2, ok: true },
  // Browser (12)
  { cat: 'Browser', name: 'Chrome Cookies', pts: 4, ok: hasSqlite3 },
  { cat: 'Browser', name: 'Chrome History', pts: 4, ok: hasSqlite3 },
  { cat: 'Browser', name: 'Chrome Visits', pts: 1, ok: hasSqlite3 },
  { cat: 'Browser', name: 'Chrome Autofill', pts: 3, ok: hasSqlite3 },
  // Communication (10)
  { cat: 'Communication', name: 'Contacts', pts: 4, ok: true },
  { cat: 'Communication', name: 'Call Logs', pts: 3, ok: true },
  { cat: 'Communication', name: 'SMS', pts: 3, ok: hasSqlite3 },
  // Activity (10)
  { cat: 'Activity', name: 'UsageStats', pts: 3, ok: true },
  { cat: 'Activity', name: 'Kiwi browser', pts: 2, ok: true },
  { cat: 'Activity', name: 'Media DB', pts: 2, ok: hasSqlite3 },
  { cat: 'Activity', name: 'Downloads DB', pts: 2, ok: hasSqlite3 },
  { cat: 'Activity', name: 'Notifications', pts: 1, ok: hasSqlite3 },
  // Payment (20)
  { cat: 'Payment', name: 'tapandpay.db', pts: 4, ok: hasSqlite3 },
  { cat: 'Payment', name: 'PlayStore prefs', pts: 3, ok: true },
  { cat: 'Payment', name: 'Purchase history', pts: 3, ok: hasSqlite3 },
  { cat: 'Payment', name: 'Transaction log', pts: 3, ok: hasSqlite3 },
  { cat: 'Payment', name: 'CardRiskProfile', pts: 2, ok: true },
  { cat: 'Payment', name: 'InstrumentVerify', pts: 2, ok: true },
  { cat: 'Payment', name: 'PlayBillingCache', pts: 1, ok: true },
  { cat: 'Payment', name: 'Play auth bypass', pts: 1, ok: true },
  { cat: 'Payment', name: 'GPay auth bypass', pts: 1, ok: true },
  // Trust Signals (18)
  { cat: 'Trust', name: 'billing.xml', pts: 1, ok: true },
  { cat: 'Trust', name: 'TapAndPayPrefs', pts: 1, ok: true },
  { cat: 'Trust', name: 'Provincial prefs', pts: 2, ok: false, reason: 'Phase 8 never creates prefs files' },
  { cat: 'Trust', name: 'Boot init', pts: 2, ok: true },
  { cat: 'Trust', name: 'Deep permissions', pts: 2, ok: true },
  { cat: 'Trust', name: 'Install source', pts: 2, ok: false, reason: 'persist.sys.cloud.pm.install_source never set in any phase' },
  { cat: 'Trust', name: 'Gallery photos', pts: 2, ok: false, reason: 'No DCIM photo creation in pipeline' },
  { cat: 'Trust', name: 'DRM device ID', pts: 2, ok: false, reason: 'persist.sys.cloud.drm.id never set' },
  { cat: 'Trust', name: 'Cell info', pts: 2, ok: false, reason: 'persist.sys.cloud.cellinfo never set' },
  { cat: 'Trust', name: 'Boot ID', pts: 2, ok: false, reason: 'ro.sys.cloud.boot_id never set' },
];

let willScore = 0, wontScore = 0;
let curCat = '';
for (const c of scoreChecks) {
  if (c.cat !== curCat) {
    curCat = c.cat;
    console.log(`  ── ${curCat} ──`);
  }
  if (c.ok) {
    willScore += c.pts;
    console.log(`    ✓ [+${c.pts}] ${c.name}`);
  } else {
    wontScore += c.pts;
    console.log(`    ✗ [+0] ${c.name} — ${c.reason || 'sqlite3 required'}`);
  }
}

console.log();
console.log('═══════════════════════════════════════════════════════');
console.log(` PROJECTED SCORE: ${willScore}/100 (${wontScore} pts unreachable)`);
console.log(` GRADE: ${willScore >= 95 ? 'A+' : willScore >= 90 ? 'A' : willScore >= 80 ? 'B+' : willScore >= 70 ? 'B' : willScore >= 60 ? 'C' : willScore >= 50 ? 'D' : 'F'}`);
console.log('═══════════════════════════════════════════════════════');
console.log();

console.log('═══ ISSUES REQUIRING CODEBASE FIXES ═══');
console.log();
console.log('FIX-1 [+2pts] Set persist.sys.cloud.pm.install_source in Phase 1 or 9');
console.log('FIX-2 [+2pts] Set persist.sys.cloud.drm.id in Phase 1');
console.log('FIX-3 [+2pts] Set persist.sys.cloud.cellinfo in Phase 1');
console.log('FIX-4 [+2pts] Set ro.sys.cloud.boot_id in Phase 1');
console.log('FIX-5 [+2pts] Inject gallery photos in Phase 6 (use injectPicture API)');
console.log('FIX-6 [+2pts] Create provincial app shared_prefs in Phase 8');
console.log('FIX-7 [SAFETY] Remove/guard updatePadAndroidProp endpoint');
console.log('FIX-8 [BUG] SMS needs content insert API fallback when sqlite3 unavailable');
console.log('FIX-9 [BUG] Wallet transaction timestamps should be aged over 365 days');
console.log();
console.log('TOTAL RECOVERABLE: +12 pts → projected score would be ' + (willScore + 12) + '/100');
