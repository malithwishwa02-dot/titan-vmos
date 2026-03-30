#!/usr/bin/env node
/**
 * Generate and inject synthetic data directly ON the VMOS device
 * via batched shell commands through ops-web syncCmd API.
 * No base64 transfer needed — content is generated on-device.
 */

const http = require('http');
const crypto = require('crypto');

const PAD_CODE = process.argv[2] || 'ACP250329ACQRPDV';
const OPS_URL = 'http://localhost:3000';
const DELAY_MS = 3200;
const CMD_LIMIT = 3800; // stay under 4000 char syncCmd limit

// ── Name pools ──────────────────────────────────────────────
const FN = ['James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
  'William','Barbara','Richard','Susan','Joseph','Jessica','Thomas','Sarah','Christopher','Karen',
  'Charles','Lisa','Daniel','Nancy','Matthew','Betty','Anthony','Margaret','Mark','Sandra',
  'Donald','Ashley','Steven','Kimberly','Paul','Emily','Andrew','Donna','Joshua','Michelle',
  'Kenneth','Carol','Kevin','Amanda','Brian','Dorothy','George','Melissa','Timothy','Deborah',
  'Ronald','Stephanie','Edward','Rebecca','Jason','Sharon','Jeffrey','Laura','Ryan','Cynthia',
  'Jacob','Kathleen','Gary','Amy','Nicholas','Angela','Eric','Jonathan','Stephen','Larry',
  'Justin','Scott','Brandon','Benjamin','Samuel','Raymond','Gregory','Frank','Alexander','Patrick',
  'Jack','Dennis','Jerry','Tyler','Aaron','Jose','Nathan','Henry','Peter','Douglas',
  'Adam','Zachary','Walter','Harold','Kyle','Carl','Arthur','Gerald','Roger','Keith',
  'Jeremy','Terry','Lawrence','Sean','Christian','Austin','Jesse','Dylan','Billy','Bruce',
  'Albert','Willie','Gabriel','Alan','Juan','Logan','Wayne','Elijah','Randy','Roy',
  'Vincent','Ralph','Eugene','Russell','Bobby','Mason','Philip','Louis','Emma','Nicole',
  'Helen','Samantha','Katherine','Christine','Debra','Rachel','Carolyn','Janet','Catherine','Maria',
  'Heather','Diane','Ruth','Julie','Olivia','Joyce','Virginia','Victoria','Kelly','Lauren',
  'Christina','Joan','Evelyn','Judith','Megan','Andrea','Cheryl','Hannah','Jacqueline','Martha',
  'Gloria','Teresa','Ann','Sara','Madison','Frances','Kathryn','Janice','Jean','Abigail',
  'Alice','Judy','Sophia','Grace','Denise','Amber','Doris','Marilyn','Danielle','Beverly',
  'Isabella','Theresa','Diana','Natalie','Brittany','Charlotte','Marie','Kayla','Alexis','Lori'];
const LN = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin',
  'Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
  'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen','Hill','Flores',
  'Green','Adams','Nelson','Baker','Hall','Rivera','Campbell','Mitchell','Carter','Roberts',
  'Gomez','Phillips','Evans','Turner','Diaz','Parker','Cruz','Edwards','Collins','Reyes',
  'Stewart','Morris','Morales','Murphy','Cook','Rogers','Gutierrez','Ortiz','Morgan','Cooper',
  'Peterson','Bailey','Reed','Kelly','Howard','Ramos','Kim','Cox','Ward','Richardson',
  'Watson','Brooks','Chavez','Wood','James','Bennett','Gray','Mendoza','Ruiz','Hughes',
  'Price','Alvarez','Castillo','Sanders','Patel','Myers','Long','Ross','Foster','Jimenez'];

const SMS_MSGS = [
  "Hey are you free tonight?","Can you call me back?","Thanks for dinner!",
  "Meeting at 3pm confirmed","Got your message","Running 10 mins late",
  "Happy birthday!","Did you see the game?","Pick up milk on the way home",
  "Just landed will call soon","Love you have a great day","What time works for you?",
  "Be there in 20 minutes","Sorry I missed your call","Sounds good see you then",
  "Can you send me that address?","Thanks for your help today","Still on for tomorrow?",
  "Just finished work heading home","Let me know when youre ready",
  "The package arrived today","Hows your day going?","Want to grab lunch?",
  "Im at the store need anything?","Great news got the job!","Traffic is terrible",
  "Movie starts at 7 dont be late","Can you watch the kids Saturday?","Doctor appt at 10am",
  "Flight delayed 2 hours","Pizza or Chinese tonight?","Your mom called",
  "Reminder dentist tomorrow 9am","Just sent you the photos","WiFi password sunshine2024",
  "Dont forget electric bill","Ill pick you up at 6","How was the interview?",
  "Congrats on the promotion!","Need to reschedule lunch","Weather looks great this weekend",
  "Forward me that email please","Stuck in traffic be there soon","Thank you for everything",
  "Miss you when can we hang?","Quick question about the project","Car broke down can you help?",
  "Dont forget Moms birthday Friday","Good morning!","Goodnight sleep well",
  "Ugh Monday already","TGIF any plans?","Kids miss you come visit",
  "New restaurant downtown wanna try?","Got home safe","Can you Venmo me for dinner?",
  "Game night my place Saturday?","Heading to gym call you after",
  "Did you submit the report?","Prescription ready for pickup",
  "Snow day no school tomorrow!","Happy anniversary!","Dog needs to go to the vet",
  "Yard sale this weekend","Thanks for the birthday gift",
  "Need a ride to airport Tuesday","Book club moved to Thursday",
  "Your turn to bring snacks","Power went out using candles lol",
  "Found your keys under the couch","Grocery list eggs bread cheese apples",
  "PTA meeting tonight at 7","Oil change reminder for car",
];

function ri(a,b){return Math.floor(Math.random()*(b-a+1))+a;}
function rc(a){return a[Math.floor(Math.random()*a.length)];}
function phone(){return `+1${ri(200,999)}${ri(200,999)}${ri(1000,9999)}`;}
function phoneFmt(){const a=ri(200,999),p=ri(200,999),l=ri(1000,9999);return `+1-${a}-${p}-${l}`;}

// ── Shell executor ──────────────────────────────────────────
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
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}

// ── Module 1: VCF Contacts ─────────────────────────────────
async function pushContacts(count = 500) {
  const VCF = '/sdcard/Download/500_US_Contacts.vcf';
  console.log(`\n[VCF] Generating ${count} contacts on device...`);
  
  await shell(`rm -f '${VCF}'`);
  await sleep(DELAY_MS);
  
  const usedNames = new Set();
  let batch = '';
  let batchNum = 0;
  let pushed = 0;
  
  for (let i = 0; i < count; i++) {
    let first, last, full;
    do { first = rc(FN); last = rc(LN); full = `${first} ${last}`; } while (usedNames.has(full));
    usedNames.add(full);
    
    let entry = `BEGIN:VCARD\\nVERSION:3.0\\nFN:${full}\\nN:${last};${first};;;\\nTEL;TYPE=CELL:${phoneFmt()}\\n`;
    if (Math.random() < 0.3) {
      entry += `EMAIL;TYPE=HOME:${first.toLowerCase()}.${last.toLowerCase()}${ri(1,99)}@gmail.com\\n`;
    }
    entry += `END:VCARD\\n\\n`;
    
    // Check if adding this entry would exceed command limit
    const testCmd = `printf '${batch}${entry}' >> '${VCF}'`;
    if (testCmd.length > CMD_LIMIT && batch) {
      // Flush current batch
      const cmd = `printf '${batch}' >> '${VCF}' && echo B${batchNum}`;
      const r = await shell(cmd);
      process.stdout.write(r.output?.includes(`B${batchNum}`) ? '.' : 'x');
      batchNum++;
      pushed += batch.split('END:VCARD').length - 1;
      batch = '';
      await sleep(DELAY_MS);
    }
    batch += entry;
  }
  
  // Flush remaining
  if (batch) {
    const cmd = `printf '${batch}' >> '${VCF}' && echo B${batchNum}`;
    const r = await shell(cmd);
    process.stdout.write(r.output?.includes(`B${batchNum}`) ? '.' : 'x');
    pushed += batch.split('END:VCARD').length - 1;
  }
  
  await sleep(DELAY_MS);
  const verify = await shell(`grep -c 'END:VCARD' '${VCF}'`);
  console.log(`\n[VCF] Done: ${verify.output?.trim()} contacts in ${VCF}`);
  return VCF;
}

// ── Module 2: SMS XML ───────────────────────────────────────
async function pushSmsXml(contactCount = 500, daysBack = 389) {
  const SMSFILE = '/sdcard/Download/sms_backup.xml';
  const now = Date.now();
  const start = now - (daysBack * 86400000);
  
  console.log(`\n[SMS] Generating ~${contactCount * 3} SMS messages on device...`);
  
  // Write XML header
  const uuid = crypto.randomUUID();
  await shell(`printf '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\\n' > '${SMSFILE}'`);
  await sleep(DELAY_MS);
  await shell(`printf '<smses count="0" backup_set="${uuid}" backup_date="${now}" type="full">\\n' >> '${SMSFILE}'`);
  await sleep(DELAY_MS);
  
  let totalMsgs = 0;
  let batchNum = 0;
  let batch = '';
  
  for (let i = 0; i < contactCount; i++) {
    const ph = phone();
    const name = `${rc(FN)} ${rc(LN)}`;
    const msgCount = ri(2, 5);
    
    for (let j = 0; j < msgCount; j++) {
      const ts = ri(start, now);
      const type = Math.random() > 0.5 ? 1 : 2;
      const body = rc(SMS_MSGS);
      const dateSent = type === 2 ? ts : 0;
      
      const entry = `  <sms protocol="0" address="${ph}" date="${ts}" type="${type}" subject="null" body="${body}" toa="null" sc_toa="null" service_center="null" read="1" status="-1" locked="0" date_sent="${dateSent}" sub_id="-1" readable_date="" contact_name="${name}" />\\n`;
      
      const testCmd = `printf '${batch}${entry}' >> '${SMSFILE}'`;
      if (testCmd.length > CMD_LIMIT && batch) {
        const cmd = `printf '${batch}' >> '${SMSFILE}' && echo S${batchNum}`;
        const r = await shell(cmd);
        process.stdout.write(r.output?.includes(`S${batchNum}`) ? '.' : 'x');
        batchNum++;
        batch = '';
        await sleep(DELAY_MS);
      }
      batch += entry;
      totalMsgs++;
    }
  }
  
  // Flush remaining batch
  if (batch) {
    const cmd = `printf '${batch}' >> '${SMSFILE}' && echo S${batchNum}`;
    const r = await shell(cmd);
    process.stdout.write(r.output?.includes(`S${batchNum}`) ? '.' : 'x');
  }
  
  // Write closing tag
  await sleep(DELAY_MS);
  await shell(`printf '</smses>\\n' >> '${SMSFILE}'`);
  
  // Fix the count in header
  await sleep(DELAY_MS);
  await shell(`sed -i 's/count="0"/count="${totalMsgs}"/' '${SMSFILE}'`);
  
  await sleep(DELAY_MS);
  const verify = await shell(`wc -l < '${SMSFILE}' && grep -c '<sms ' '${SMSFILE}'`);
  console.log(`\n[SMS] Done: ${totalMsgs} messages → ${SMSFILE}`);
  console.log(`  Verify: ${verify.output?.trim()}`);
  return SMSFILE;
}

// ── Module 3: Call Log XML ──────────────────────────────────
async function pushCallLogXml(contactCount = 500, daysBack = 356) {
  const CALLFILE = '/sdcard/Download/calls_backup.xml';
  const now = Date.now();
  const start = now - (daysBack * 86400000);
  
  console.log(`\n[CALLS] Generating ~${contactCount * 3} call records on device...`);
  
  const uuid = crypto.randomUUID();
  await shell(`printf '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\\n' > '${CALLFILE}'`);
  await sleep(DELAY_MS);
  await shell(`printf '<calls count="0" backup_set="${uuid}" backup_date="${now}" type="full">\\n' >> '${CALLFILE}'`);
  await sleep(DELAY_MS);
  
  let totalCalls = 0;
  let batchNum = 0;
  let batch = '';
  
  for (let i = 0; i < contactCount; i++) {
    const ph = phone();
    const name = `${rc(FN)} ${rc(LN)}`;
    const callCount = ri(1, 5);
    
    for (let j = 0; j < callCount; j++) {
      const ts = ri(start, now);
      const type = rc([1,1,1,2,2,2,3]); // weighted: more incoming/outgoing
      let dur;
      if (type === 3) { dur = 0; }
      else {
        const roll = Math.random();
        if (roll < 0.6) dur = ri(5, 120);
        else if (roll < 0.9) dur = ri(120, 900);
        else dur = ri(900, 3600);
      }
      
      const entry = `  <call number="${ph}" duration="${dur}" date="${ts}" type="${type}" presentation="1" subscription_id="1" post_dial_digits="" subscription_component_name="com.android.phone/com.android.services.telephony.TelephonyConnectionService" readable_date="" contact_name="${name}" />\\n`;
      
      const testCmd = `printf '${batch}${entry}' >> '${CALLFILE}'`;
      if (testCmd.length > CMD_LIMIT && batch) {
        const cmd = `printf '${batch}' >> '${CALLFILE}' && echo C${batchNum}`;
        const r = await shell(cmd);
        process.stdout.write(r.output?.includes(`C${batchNum}`) ? '.' : 'x');
        batchNum++;
        batch = '';
        await sleep(DELAY_MS);
      }
      batch += entry;
      totalCalls++;
    }
  }
  
  if (batch) {
    const cmd = `printf '${batch}' >> '${CALLFILE}' && echo C${batchNum}`;
    const r = await shell(cmd);
    process.stdout.write(r.output?.includes(`C${batchNum}`) ? '.' : 'x');
  }
  
  await sleep(DELAY_MS);
  await shell(`printf '</calls>\\n' >> '${CALLFILE}'`);
  
  await sleep(DELAY_MS);
  await shell(`sed -i 's/count="0"/count="${totalCalls}"/' '${CALLFILE}'`);
  
  await sleep(DELAY_MS);
  const verify = await shell(`wc -l < '${CALLFILE}' && grep -c '<call ' '${CALLFILE}'`);
  console.log(`\n[CALLS] Done: ${totalCalls} records → ${CALLFILE}`);
  console.log(`  Verify: ${verify.output?.trim()}`);
  return CALLFILE;
}

// ── Main ────────────────────────────────────────────────────
async function main() {
  console.log('=== VMOS Synthetic Data Injection ===');
  console.log(`Device: ${PAD_CODE}\n`);
  
  // Verify device is alive
  const check = await shell('id && echo ALIVE');
  if (!check.output?.includes('ALIVE')) {
    console.error('Device not responding!');
    process.exit(1);
  }
  console.log(`Device OK: ${check.output.split('\n')[0]}`);
  
  // Push all three files
  const vcfPath = await pushContacts(500);
  const smsPath = await pushSmsXml(500, 389);
  const callPath = await pushCallLogXml(500, 356);
  
  console.log('\n=== All files generated on device ===');
  console.log(`VCF:   ${vcfPath}`);
  console.log(`SMS:   ${smsPath}`);
  console.log(`Calls: ${callPath}`);
  
  // List files
  await sleep(DELAY_MS);
  const ls = await shell(`ls -la /sdcard/Download/*.vcf /sdcard/Download/*backup*.xml 2>/dev/null`);
  console.log(`\nFiles on device:\n${ls.output}`);
  
  console.log('\n=== Import Instructions ===');
  console.log('1. CONTACTS: Open Contacts app → Settings → Import → Select .vcf file');
  console.log('2. SMS + CALLS: Install "SMS Backup & Restore" from Play Store');
  console.log('   → Open app → Restore → Select XML files → Set as default SMS app → Restore');
  console.log('3. After restore, reset default SMS/Phone apps');
}

main().catch(e => { console.error(e); process.exit(1); });
