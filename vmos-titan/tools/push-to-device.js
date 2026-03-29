#!/usr/bin/env node
/**
 * Push files to VMOS device via chunked base64 through syncCmd API
 * Usage: node push-to-device.js <local-file> <remote-path> [pad-code]
 */

const fs = require('fs');
const http = require('http');

const PAD_CODE = process.argv[4] || 'ACP250329ACQRPDV';
const OPS_URL = 'http://localhost:3000';
const CHUNK_SIZE = 2048; // bytes of raw data per chunk (becomes ~2.7KB base64)
const DELAY_MS = 3500;   // 3.5s between commands to avoid 110031 cascade

const localFile = process.argv[2];
const remotePath = process.argv[3];

if (!localFile || !remotePath) {
  console.error('Usage: node push-to-device.js <local-file> <remote-path> [pad-code]');
  process.exit(1);
}

function shell(cmd) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ command: cmd });
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

async function main() {
  const fileData = fs.readFileSync(localFile);
  const b64 = fileData.toString('base64');
  const totalChunks = Math.ceil(b64.length / CHUNK_SIZE);
  const totalKB = (fileData.length / 1024).toFixed(1);

  console.log(`Pushing ${localFile} (${totalKB} KB) → ${remotePath}`);
  console.log(`  ${totalChunks} chunks × ${CHUNK_SIZE} chars, ~${(totalChunks * DELAY_MS / 1000).toFixed(0)}s estimated`);

  // Clear target file first
  const clearResult = await shell(`rm -f '${remotePath}' && echo CLEARED`);
  console.log(`  [0/${totalChunks}] Cleared target: ${clearResult.output?.trim()}`);
  await sleep(DELAY_MS);

  for (let i = 0; i < totalChunks; i++) {
    const chunk = b64.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    const cmd = `echo '${chunk}' | base64 -d >> '${remotePath}' && echo CHUNK_${i}_OK`;
    const result = await shell(cmd);
    const ok = result.output?.includes(`CHUNK_${i}_OK`);
    process.stdout.write(`  [${i + 1}/${totalChunks}] ${ok ? '✓' : '✗'}`);
    if (!ok) {
      console.log(` FAILED: ${JSON.stringify(result).slice(0, 100)}`);
      // Retry once
      await sleep(DELAY_MS);
      const retry = await shell(cmd);
      const retryOk = retry.output?.includes(`CHUNK_${i}_OK`);
      console.log(`  [RETRY] ${retryOk ? '✓' : '✗ GIVING UP'}`);
      if (!retryOk) process.exit(1);
    }
    if ((i + 1) % 10 === 0 || i === totalChunks - 1) console.log('');
    await sleep(DELAY_MS);
  }

  // Verify file size
  await sleep(DELAY_MS);
  const verify = await shell(`ls -la '${remotePath}' && wc -c < '${remotePath}'`);
  console.log(`  Verify: ${verify.output?.trim()}`);

  console.log(`\n✅ Push complete: ${remotePath}`);
}

main().catch(e => { console.error(e); process.exit(1); });
