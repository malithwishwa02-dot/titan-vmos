#!/usr/bin/env node
/**
 * Generate shell scripts for injecting contacts, call logs, and SMS
 * via `content insert` on the VMOS device.
 * These scripts run locally on the device (background) where content insert works.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const OUTDIR = path.join(__dirname, '..', 'generated-data');
fs.mkdirSync(OUTDIR, { recursive: true });

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
  'Helen','Samantha','Katherine','Christine','Debra','Rachel','Carolyn','Janet','Catherine','Maria'];
const LN = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin',
  'Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
  'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen','Hill','Flores',
  'Green','Adams','Nelson','Baker','Hall','Rivera','Campbell','Mitchell','Carter','Roberts',
  'Gomez','Phillips','Evans','Turner','Diaz','Parker','Cruz','Edwards','Collins','Reyes',
  'Stewart','Morris','Morales','Murphy','Cook','Rogers','Gutierrez','Ortiz','Morgan','Cooper',
  'Peterson','Bailey','Reed','Kelly','Howard','Ramos','Kim','Cox','Ward','Richardson'];
const SMS_MSGS = [
  'Hey are you free tonight','Can you call me back','Thanks for dinner',
  'Meeting at 3pm confirmed','Got your message','Running 10 mins late',
  'Happy birthday','Did you see the game','Pick up milk on the way home',
  'Just landed will call soon','Love you have a great day','What time works for you',
  'Be there in 20 minutes','Sorry I missed your call','Sounds good see you then',
  'Can you send me that address','Thanks for your help today','Still on for tomorrow',
  'Just finished work heading home','Let me know when you are ready',
  'The package arrived today','How is your day going','Want to grab lunch',
  'I am at the store need anything','Great news got the job','Traffic is terrible',
  'Movie starts at 7','Can you watch the kids Saturday','Doctor appointment at 10am',
  'Flight delayed 2 hours','Pizza or Chinese tonight','Your mom called call her back',
  'Reminder dentist tomorrow 9am','Just sent you the photos','WiFi password sunshine2024',
  'Do not forget electric bill','I will pick you up at 6','How was the interview',
  'Congrats on the promotion','Need to reschedule lunch','Weather looks great this weekend',
];
function ri(a,b){return Math.floor(Math.random()*(b-a+1))+a;}
function rc(a){return a[Math.floor(Math.random()*a.length)];}
function phone(){return `+1${ri(200,999)}${ri(200,999)}${ri(1000,9999)}`;}

const now = Date.now();

// ── 1. Contacts injection script ────────────────────────────
console.log('[1/3] Generating contacts injection script...');
let contactScript = `#!/system/bin/sh
# Inject 500 contacts via content insert
# Run as: nohup sh /data/local/tmp/inject_contacts.sh > /data/local/tmp/inject_contacts.log 2>&1 &
LOG=/data/local/tmp/inject_contacts.log
echo "Starting contact injection at $(date)" > $LOG
COUNT=0
`;

const usedNames = new Set();
for (let i = 0; i < 500; i++) {
  let first, last, full;
  do { first = rc(FN); last = rc(LN); full = `${first} ${last}`; } while (usedNames.has(full));
  usedNames.add(full);
  const ph = phone();
  
  contactScript += `
content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s:com.google --bind account_name:s:epolusamuel682@gmail.com 2>/dev/null
RID=$((COUNT + 1))
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$RID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"${full}" --bind data2:s:"${first}" --bind data3:s:"${last}" 2>/dev/null
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$RID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:"${ph}" --bind data2:i:2 2>/dev/null
COUNT=$((COUNT + 1))
`;
  // Add email for ~30%
  if (Math.random() < 0.3) {
    const email = `${first.toLowerCase()}.${last.toLowerCase()}${ri(1,99)}@gmail.com`;
    contactScript += `content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$RID --bind mimetype:s:vnd.android.cursor.item/email_v2 --bind data1:s:"${email}" --bind data2:i:1 2>/dev/null\n`;
  }
}

contactScript += `
echo "Done: $COUNT contacts inserted at $(date)" >> $LOG
echo "CONTACTS_DONE_$COUNT"
`;

const contactPath = path.join(OUTDIR, 'inject_contacts.sh');
fs.writeFileSync(contactPath, contactScript);
console.log(`  → ${contactPath} (${(Buffer.byteLength(contactScript)/1024).toFixed(1)} KB)`);

// ── 2. Call log injection script ────────────────────────────
console.log('[2/3] Generating call log injection script...');
const startCall = now - (356 * 86400000);
let callScript = `#!/system/bin/sh
# Inject 1500 call records via content insert
LOG=/data/local/tmp/inject_calls.log
echo "Starting call log injection at $(date)" > $LOG
COUNT=0
`;

for (let i = 0; i < 1500; i++) {
  const ph = phone();
  const ts = ri(startCall, now);
  const type = rc([1,1,1,2,2,2,3]);
  let dur;
  if (type === 3) dur = 0;
  else {
    const roll = Math.random();
    if (roll < 0.6) dur = ri(5, 120);
    else if (roll < 0.9) dur = ri(120, 900);
    else dur = ri(900, 3600);
  }
  const isNew = type === 3 ? ri(0,1) : 0;
  
  callScript += `content insert --uri content://call_log/calls --bind number:s:${ph} --bind date:l:${ts} --bind duration:i:${dur} --bind type:i:${type} --bind new:i:${isNew} 2>/dev/null\nCOUNT=$((COUNT + 1))\n`;
}

callScript += `
echo "Done: $COUNT call records at $(date)" >> $LOG
echo "CALLS_DONE_$COUNT"
`;

const callPath = path.join(OUTDIR, 'inject_calls.sh');
fs.writeFileSync(callPath, callScript);
console.log(`  → ${callPath} (${(Buffer.byteLength(callScript)/1024).toFixed(1)} KB)`);

// ── 3. SMS injection script ─────────────────────────────────
console.log('[3/3] Generating SMS injection script...');
const startSms = now - (389 * 86400000);
let smsScript = `#!/system/bin/sh
# Inject ~1700 SMS messages via content insert
LOG=/data/local/tmp/inject_sms.log
echo "Starting SMS injection at $(date)" > $LOG
COUNT=0
`;

for (let i = 0; i < 500; i++) {
  const ph = phone();
  const msgCount = ri(2, 5);
  for (let j = 0; j < msgCount; j++) {
    const ts = ri(startSms, now);
    const type = Math.random() > 0.5 ? 1 : 2;
    const body = rc(SMS_MSGS);
    const dateSent = type === 2 ? ts : 0;
    
    smsScript += `content insert --uri content://sms --bind address:s:${ph} --bind date:l:${ts} --bind date_sent:l:${dateSent} --bind type:i:${type} --bind body:s:"${body}" --bind read:i:1 --bind seen:i:1 2>/dev/null\nCOUNT=$((COUNT + 1))\n`;
  }
}

smsScript += `
echo "Done: $COUNT SMS messages at $(date)" >> $LOG
echo "SMS_DONE_$COUNT"
`;

const smsPath = path.join(OUTDIR, 'inject_sms.sh');
fs.writeFileSync(smsPath, smsScript);
console.log(`  → ${smsPath} (${(Buffer.byteLength(smsScript)/1024).toFixed(1)} KB)`);

console.log('\n=== All injection scripts generated ===');
console.log('Push to device and run in background:');
console.log('  nohup sh /data/local/tmp/inject_contacts.sh > /data/local/tmp/inject_contacts.log 2>&1 &');
console.log('  nohup sh /data/local/tmp/inject_calls.sh > /data/local/tmp/inject_calls.log 2>&1 &');
console.log('  nohup sh /data/local/tmp/inject_sms.sh > /data/local/tmp/inject_sms.log 2>&1 &');
