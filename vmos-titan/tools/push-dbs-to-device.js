#!/usr/bin/env node
/**
 * Push pre-built SQLite databases to VMOS device via chunked base64.
 * Then set correct ownership, permissions, and restorecon.
 */

const fs = require('fs');
const http = require('http');

const PAD_CODE = process.argv[2] || 'ACP250329ACQRPDV';
const OPS_URL = 'http://localhost:3000';
const CHUNK_SIZE = 2500; // base64 chars per chunk (fits in 4000 char cmd limit)
const DELAY_MS = 3200;

function shell(cmd) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ command: cmd.slice(0, 4000) });
    const req = http.request(`${OPS_URL}/api/instances/${PAD_CODE}/shell`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve({ output: data, ok: false }); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function pushFile(localPath, remotePath, owner) {
  const fileData = fs.readFileSync(localPath);
  const b64 = fileData.toString('base64');
  const totalChunks = Math.ceil(b64.length / CHUNK_SIZE);
  const totalKB = (fileData.length / 1024).toFixed(1);

  console.log(`\nPushing ${localPath.split('/').pop()} (${totalKB} KB) → ${remotePath}`);
  console.log(`  ${totalChunks} chunks, ~${(totalChunks * DELAY_MS / 1000).toFixed(0)}s`);

  // Stop the app that uses this database
  const appMap = {
    'contacts2.db': 'com.android.providers.contacts',
    'calllog.db': 'com.android.providers.contacts',
    'mmssms.db': 'com.android.providers.telephony',
  };
  const dbName = localPath.split('/').pop();
  const app = appMap[dbName];
  if (app) {
    await shell(`am force-stop ${app} 2>/dev/null; echo STOPPED`);
    await sleep(DELAY_MS);
  }

  // Clear target
  await shell(`rm -f '${remotePath}' && echo CLEARED`);
  await sleep(DELAY_MS);

  let failures = 0;
  for (let i = 0; i < totalChunks; i++) {
    const chunk = b64.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    // Use printf to avoid echo interpretation issues
    const cmd = `printf '%s' '${chunk}' | base64 -d >> '${remotePath}' && echo K${i}`;
    const r = await shell(cmd);
    const ok = r.output?.includes(`K${i}`);
    process.stdout.write(ok ? '.' : 'x');
    if (!ok) {
      failures++;
      // Retry once
      await sleep(DELAY_MS);
      const retry = await shell(cmd);
      if (retry.output?.includes(`K${i}`)) {
        process.stdout.write('✓');
      } else {
        console.log(` FAIL chunk ${i}`);
        process.exit(1);
      }
    }
    if ((i + 1) % 20 === 0) process.stdout.write(`[${i+1}/${totalChunks}]`);
    await sleep(DELAY_MS);
  }

  // Set ownership and permissions
  await sleep(DELAY_MS);
  await shell(`chown '${owner}':'${owner}' '${remotePath}' && chmod 660 '${remotePath}' && restorecon '${remotePath}' 2>/dev/null && echo PERMS_OK`);
  await sleep(DELAY_MS);

  // Also handle journal/wal files
  await shell(`rm -f '${remotePath}'-journal '${remotePath}'-wal '${remotePath}'-shm 2>/dev/null && echo JOURNAL_CLEAN`);

  // Verify
  await sleep(DELAY_MS);
  const verify = await shell(`ls -la '${remotePath}' && wc -c < '${remotePath}'`);
  const remoteSize = parseInt(verify.output?.split('\n').pop()?.trim() || '0');
  const match = remoteSize === fileData.length;

  console.log(`\n  Size: local=${fileData.length} remote=${remoteSize} ${match ? '✅' : '❌ MISMATCH'}`);
  if (failures) console.log(`  Retries: ${failures}`);
  return match;
}

async function main() {
  console.log('=== Push SQLite DBs to VMOS Device ===');
  console.log(`Device: ${PAD_CODE}\n`);

  // Verify device
  const check = await shell('id && echo ALIVE');
  if (!check.output?.includes('ALIVE')) { console.error('Device offline!'); process.exit(1); }
  console.log(`Device: ${check.output.split('\n')[0]}`);

  const BASE = '/root/Titan-android-v13/vmos-titan/generated-data';

  const files = [
    {
      local: `${BASE}/contacts2.db`,
      remote: '/data/data/com.android.providers.contacts/databases/contacts2.db',
      owner: 'u0_a24',
    },
    {
      local: `${BASE}/calllog.db`,
      remote: '/data/data/com.android.providers.contacts/databases/calllog.db',
      owner: 'u0_a24',
    },
    {
      local: `${BASE}/mmssms.db`,
      remote: '/data/data/com.android.providers.telephony/databases/mmssms.db',
      owner: 'radio',
    },
  ];

  let allOk = true;
  for (const f of files) {
    const ok = await pushFile(f.local, f.remote, f.owner);
    if (!ok) allOk = false;
    await sleep(DELAY_MS);
  }

  // Restart content providers to pick up new data
  console.log('\nRestarting content providers...');
  await shell('am force-stop com.android.providers.contacts 2>/dev/null');
  await sleep(DELAY_MS);
  await shell('am force-stop com.android.providers.telephony 2>/dev/null');
  await sleep(DELAY_MS);
  await shell('am force-stop com.google.android.contacts 2>/dev/null');
  await sleep(DELAY_MS);
  await shell('am force-stop com.google.android.apps.messaging 2>/dev/null');
  await sleep(DELAY_MS);
  await shell('am force-stop com.google.android.dialer 2>/dev/null');

  console.log(`\n=== Push Complete: ${allOk ? 'ALL OK ✅' : 'SOME FAILURES ❌'} ===`);
  console.log('Contacts: 500 | Call logs: 1500 | SMS: 1739');
  console.log('Content providers restarted — data should be visible in apps now.');
}

main().catch(e => { console.error(e); process.exit(1); });
