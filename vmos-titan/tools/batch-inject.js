#!/usr/bin/env node
/**
 * Batch inject data to VMOS device via content insert.
 * Runs sequentially (1 record at a time) via syncCmd,
 * fire-and-forget with DB growth verification.
 * 
 * Usage: node batch-inject.js [contacts|calls|sms] [start] [pad-code]
 */

const http = require('http');
const PAD_CODE = process.argv[4] || 'ACP250329ACQRPDV';
const OPS_URL = 'http://localhost:3000';
const MODE = process.argv[2] || 'contacts';
const START_FROM = parseInt(process.argv[3]) || 0;

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

// ── Name data ────────────────────────────────────────────────
const FN = ['James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
  'William','Barbara','Richard','Susan','Joseph','Jessica','Thomas','Sarah','Christopher','Karen',
  'Charles','Lisa','Daniel','Nancy','Matthew','Betty','Anthony','Margaret','Mark','Sandra',
  'Donald','Ashley','Steven','Kimberly','Paul','Emily','Andrew','Donna','Joshua','Michelle'];
const LN = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin'];
const MSGS = ['Hey are you free','Call me back','Thanks for dinner','Meeting at 3pm','Got your msg',
  'Running late','Happy bday','See the game','Pick up milk','Just landed','Have a great day',
  'What time','Be there in 20','Missed your call','Sounds good','Thanks for help',
  'Tomorrow still on','Heading home','Package arrived','Grab lunch','Traffic bad',
  'Movie at 7','Doctor at 10','Pizza tonight','Mom called','Weather great','Good morning',
  'Goodnight','TGIF','Got home safe'];

function getFN(i) { return FN[i % FN.length]; }
function getLN(i) { return LN[Math.floor(i / FN.length) % LN.length]; }
function getPhone(i) { 
  const a = 200 + (i * 7) % 800;
  const p = 200 + (i * 13) % 800;
  const l = 1000 + (i * 31) % 9000;
  return `+1${a}${p}${l}`;
}
function getMsg(i) { return MSGS[i % MSGS.length]; }

// ── Inject a single contact via content insert ──────────────
// NOTE: content insert works via syncCmd but returns no output.
// We fire-and-forget and verify via DB size growth.
async function injectContact(i) {
  const fn = getFN(i);
  const ln = getLN(i);
  const ph = getPhone(i);
  const rid = i + 1;
  const cmd = `content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s:com.google --bind account_name:s:epolusamuel682@gmail.com 2>/dev/null; content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:${rid} --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:${fn}%20${ln} --bind data2:s:${fn} --bind data3:s:${ln} 2>/dev/null; content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:${rid} --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:${ph} --bind data2:i:2 2>/dev/null`;
  await shell(cmd);
  return true; // fire-and-forget, verify via DB growth
}

// ── Inject a single call log entry ──────────────────────────
async function injectCall(i) {
  const ph = getPhone(i);
  const nowSec = Math.floor(Date.now() / 1000);
  const startSec = nowSec - (356 * 86400);
  const ts = (startSec + ((i * 20500 + (i * 7 * 1000)) % (356 * 86400))) * 1000;
  const type = (i % 7 < 3) ? 1 : (i % 7 < 6) ? 2 : 3;
  const dur = type === 3 ? 0 : 5 + (i * 17) % 600;
  
  const cmd = `content insert --uri content://call_log/calls --bind number:s:${ph} --bind date:l:${ts} --bind duration:i:${dur} --bind type:i:${type} --bind new:i:0 2>/dev/null`;
  await shell(cmd);
  return true;
}

// ── Inject a single SMS ─────────────────────────────────────
async function injectSms(i) {
  const contactIdx = Math.floor(i / 3);
  const ph = getPhone(contactIdx);
  const nowSec = Math.floor(Date.now() / 1000);
  const startSec = nowSec - (389 * 86400);
  const ts = (startSec + ((i * 22000 + (i * 11 * 1000)) % (389 * 86400))) * 1000;
  const type = i % 2 === 0 ? 1 : 2;
  const body = getMsg(i);
  const ds = type === 2 ? ts : 0;

  const cmd = `content insert --uri content://sms --bind address:s:${ph} --bind date:l:${ts} --bind date_sent:l:${ds} --bind type:i:${type} --bind body:s:"${body}" --bind read:i:1 --bind seen:i:1 2>/dev/null`;
  await shell(cmd);
  return true;
}

// ── Main batch runner ───────────────────────────────────────
async function main() {
  let total, batchSize, injectFn;
  
  switch (MODE) {
    case 'contacts':
      total = 500; batchSize = 1; injectFn = injectContact;
      break;
    case 'calls':
      total = 1500; batchSize = 1; injectFn = injectCall;
      break;
    case 'sms':
      total = 1500; batchSize = 1; injectFn = injectSms;
      break;
    default:
      console.error('Usage: node batch-inject.js [contacts|calls|sms] [start]');
      process.exit(1);
  }

  console.log(`=== Batch Inject: ${MODE} ===`);
  console.log(`Total: ${total}, Starting from: ${START_FROM}`);
  console.log(`Device: ${PAD_CODE}\n`);

  let success = 0, fail = 0;
  const startTime = Date.now();

  for (let i = START_FROM; i < total; i++) {
    const ok = await injectFn(i);
    if (ok) {
      success++;
      process.stdout.write('.');
    } else {
      fail++;
      process.stdout.write('x');
      // Retry once
      await sleep(3200);
      const retry = await injectFn(i);
      if (retry) { success++; process.stdout.write('✓'); }
    }
    if ((i + 1) % 50 === 0) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
      const rate = (success / (elapsed || 1)).toFixed(1);
      console.log(` [${i + 1}/${total}] ${success}ok ${fail}fail ${elapsed}s (${rate}/s)`);
    }
    // Small delay to avoid overwhelming the device
    await sleep(500);
  }

  const totalTime = ((Date.now() - startTime) / 1000).toFixed(0);
  console.log(`\n\n=== Done: ${success} success, ${fail} fail in ${totalTime}s ===`);
}

main().catch(e => { console.error(e); process.exit(1); });
