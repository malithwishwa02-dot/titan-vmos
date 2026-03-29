#!/usr/bin/env node
/**
 * Synthetic Android Data Generation Suite
 * Generates VCF contacts, SMS XML, and Call Log XML
 * for native Android import (no root/sqlite3 needed)
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ── Name pools ──────────────────────────────────────────────
const FIRST_NAMES = [
  'James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
  'William','Barbara','Richard','Susan','Joseph','Jessica','Thomas','Sarah','Christopher','Karen',
  'Charles','Lisa','Daniel','Nancy','Matthew','Betty','Anthony','Margaret','Mark','Sandra',
  'Donald','Ashley','Steven','Kimberly','Paul','Emily','Andrew','Donna','Joshua','Michelle',
  'Kenneth','Carol','Kevin','Amanda','Brian','Dorothy','George','Melissa','Timothy','Deborah',
  'Ronald','Stephanie','Edward','Rebecca','Jason','Sharon','Jeffrey','Laura','Ryan','Cynthia',
  'Jacob','Kathleen','Gary','Amy','Nicholas','Angela','Eric','Shirley','Jonathan','Anna',
  'Stephen','Brenda','Larry','Pamela','Justin','Emma','Scott','Nicole','Brandon','Helen',
  'Benjamin','Samantha','Samuel','Katherine','Raymond','Christine','Gregory','Debra','Frank','Rachel',
  'Alexander','Carolyn','Patrick','Janet','Jack','Catherine','Dennis','Maria','Jerry','Heather',
  'Tyler','Diane','Aaron','Ruth','Jose','Julie','Nathan','Olivia','Henry','Joyce',
  'Peter','Virginia','Douglas','Victoria','Adam','Kelly','Zachary','Lauren','Walter','Christina',
  'Harold','Joan','Kyle','Evelyn','Carl','Judith','Arthur','Megan','Gerald','Andrea',
  'Roger','Cheryl','Keith','Hannah','Jeremy','Jacqueline','Terry','Martha','Lawrence','Gloria',
  'Sean','Teresa','Christian','Ann','Austin','Sara','Jesse','Madison','Dylan','Frances',
  'Billy','Kathryn','Bruce','Janice','Albert','Jean','Willie','Abigail','Gabriel','Alice',
  'Alan','Judy','Juan','Sophia','Logan','Grace','Wayne','Denise','Elijah','Amber',
  'Randy','Doris','Roy','Marilyn','Vincent','Danielle','Ralph','Beverly','Eugene','Isabella',
  'Russell','Theresa','Bobby','Diana','Mason','Natalie','Philip','Brittany','Louis','Charlotte',
];

const LAST_NAMES = [
  'Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin',
  'Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
  'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen','Hill','Flores',
  'Green','Adams','Nelson','Baker','Hall','Rivera','Campbell','Mitchell','Carter','Roberts',
  'Gomez','Phillips','Evans','Turner','Diaz','Parker','Cruz','Edwards','Collins','Reyes',
  'Stewart','Morris','Morales','Murphy','Cook','Rogers','Gutierrez','Ortiz','Morgan','Cooper',
  'Peterson','Bailey','Reed','Kelly','Howard','Ramos','Kim','Cox','Ward','Richardson',
  'Watson','Brooks','Chavez','Wood','James','Bennett','Gray','Mendoza','Ruiz','Hughes',
  'Price','Alvarez','Castillo','Sanders','Patel','Myers','Long','Ross','Foster','Jimenez',
];

// SMS message templates
const SMS_MESSAGES = [
  "Hey, are you free tonight?", "Can you call me back?", "Thanks for dinner last night!",
  "Meeting at 3pm confirmed", "Got your message, will reply soon", "Running 10 mins late sorry",
  "Happy birthday! 🎂", "Did you see the game last night?", "Can you pick up milk on the way home?",
  "Just landed, will call you soon", "Love you, have a great day!", "What time works for you?",
  "I'll be there in 20 minutes", "Sorry I missed your call", "Sounds good, see you then!",
  "Can you send me that address?", "Thanks for your help today", "Are we still on for tomorrow?",
  "Just finished work, heading home", "Let me know when you're ready",
  "The package arrived today", "How's your day going?", "Do you want to grab lunch?",
  "I'm at the store, need anything?", "Great news! Got the job!", "Traffic is terrible right now",
  "Movie starts at 7, don't be late", "Can you watch the kids Saturday?", "Doctor appointment at 10am",
  "Flight delayed 2 hours ugh", "Pizza or Chinese tonight?", "Your mom called, call her back",
  "Reminder: dentist tomorrow 9am", "Just sent you the photos", "WiFi password is sunshine2024",
  "Don't forget to pay the electric bill", "I'll pick you up at 6", "How was the interview?",
  "Congratulations on the promotion!", "Need to reschedule our lunch", "Weather looks great this weekend",
  "Can you forward me that email?", "Stuck in traffic, be there soon", "Thank you so much for everything",
  "Miss you! When can we hang out?", "Quick question about the project", "My car broke down, can you help?",
  "Don't forget Mom's birthday Friday", "Good morning! ☀️", "Night night, sleep well 💤",
  "Ugh Monday already", "TGIF! Any plans this weekend?", "The kids miss you, come visit soon",
  "New restaurant opened downtown, wanna try it?", "Just got home safe", "Can you Venmo me for dinner?",
  "Game night at my place Saturday?", "Heading to the gym, call you after",
  "Did you submit the report?", "Your prescription is ready for pickup",
  "Snow day tomorrow, no school!", "Happy anniversary! ❤️", "The dog needs to go to the vet",
  "Yard sale this weekend, come check it out", "Thanks for the birthday gift!",
  "Need a ride to the airport Tuesday", "Book club meeting moved to Thursday",
  "Your turn to bring snacks to practice", "Power went out, using candles lol",
  "Found your keys, they were under the couch", "Grocery list: eggs, bread, cheese, apples",
  "PTA meeting tonight at 7", "Oil change reminder for your car", "Can you water my plants while I'm gone?",
];

// ── Helper functions ─────────────────────────────────────────
function randInt(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
function randChoice(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function escapeXml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&apos;').replace(/"/g,'&quot;'); }

function genPhone() {
  const area = randInt(200, 999);
  const prefix = randInt(200, 999);
  const line = randInt(1000, 9999);
  return `+1${area}${prefix}${line}`;
}

function genPhoneFormatted() {
  const area = randInt(200, 999);
  const prefix = randInt(200, 999);
  const line = randInt(1000, 9999);
  return { e164: `+1${area}${prefix}${line}`, formatted: `+1-${area}-${prefix}-${line}` };
}

// ── Module 1: VCF Contact Generator ──────────────────────────
function generateVCF(count = 500) {
  const lines = [];
  const usedNames = new Set();

  for (let i = 0; i < count; i++) {
    let first, last, fullName;
    do {
      first = randChoice(FIRST_NAMES);
      last = randChoice(LAST_NAMES);
      fullName = `${first} ${last}`;
    } while (usedNames.has(fullName));
    usedNames.add(fullName);

    const { formatted } = genPhoneFormatted();

    lines.push('BEGIN:VCARD');
    lines.push('VERSION:3.0');
    lines.push(`FN:${fullName}`);
    lines.push(`N:${last};${first};;;`);
    lines.push(`TEL;TYPE=CELL:${formatted}`);
    // ~30% have email
    if (Math.random() < 0.3) {
      const email = `${first.toLowerCase()}.${last.toLowerCase()}${randInt(1,99)}@gmail.com`;
      lines.push(`EMAIL;TYPE=HOME:${email}`);
    }
    lines.push('END:VCARD');
    lines.push('');
  }

  return lines.join('\r\n');
}

// ── Module 2: SMS History XML Generator ──────────────────────
function generateSmsXml(contactCount = 500, daysBack = 389) {
  const now = Date.now();
  const startTime = now - (daysBack * 24 * 60 * 60 * 1000);
  const messages = [];

  for (let i = 0; i < contactCount; i++) {
    const phone = genPhone();
    const msgCount = randInt(2, 5);
    const name = `${randChoice(FIRST_NAMES)} ${randChoice(LAST_NAMES)}`;

    for (let j = 0; j < msgCount; j++) {
      const timestamp = randInt(startTime, now);
      const type = Math.random() > 0.5 ? 1 : 2; // 1=received, 2=sent
      const body = escapeXml(randChoice(SMS_MESSAGES));
      const read = 1;
      const dateStr = new Date(timestamp).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
      });

      messages.push({
        protocol: 0,
        address: phone,
        date: timestamp,
        type,
        subject: 'null',
        body,
        toa: 'null',
        sc_toa: 'null',
        service_center: 'null',
        read,
        status: -1,
        locked: 0,
        date_sent: type === 2 ? timestamp : 0,
        sub_id: -1,
        readable_date: dateStr,
        contact_name: escapeXml(name),
      });
    }
  }

  // Sort by date for natural order
  messages.sort((a, b) => a.date - b.date);

  let xml = '<?xml version=\'1.0\' encoding=\'UTF-8\' standalone=\'yes\' ?>\n';
  xml += `<!--File Created By Synthetic Data Generator-->\n`;
  xml += `<smses count="${messages.length}" backup_set="${crypto.randomUUID()}" backup_date="${now}" type="full">\n`;

  for (const m of messages) {
    xml += `  <sms protocol="${m.protocol}" address="${m.address}" date="${m.date}" type="${m.type}" `;
    xml += `subject="${m.subject}" body="${m.body}" toa="${m.toa}" sc_toa="${m.sc_toa}" `;
    xml += `service_center="${m.service_center}" read="${m.read}" status="${m.status}" `;
    xml += `locked="${m.locked}" date_sent="${m.date_sent}" sub_id="${m.sub_id}" `;
    xml += `readable_date="${m.readable_date}" contact_name="${m.contact_name}" />\n`;
  }

  xml += '</smses>\n';
  return { xml, count: messages.length };
}

// ── Module 3: Call Log XML Generator ─────────────────────────
function generateCallLogXml(contactCount = 500, daysBack = 356) {
  const now = Date.now();
  const startTime = now - (daysBack * 24 * 60 * 60 * 1000);
  const calls = [];

  for (let i = 0; i < contactCount; i++) {
    const phone = genPhone();
    const callCount = randInt(1, 5);
    const name = `${randChoice(FIRST_NAMES)} ${randChoice(LAST_NAMES)}`;

    for (let j = 0; j < callCount; j++) {
      const timestamp = randInt(startTime, now);
      // 1=incoming, 2=outgoing, 3=missed
      const type = randChoice([1, 1, 1, 2, 2, 2, 3]);

      let duration;
      if (type === 3) {
        duration = 0;
      } else {
        const roll = Math.random();
        if (roll < 0.6) {
          duration = randInt(5, 120);       // Short: 5s-2min
        } else if (roll < 0.9) {
          duration = randInt(120, 900);     // Medium: 2min-15min
        } else {
          duration = randInt(900, 3600);    // Long: 15min-60min
        }
      }

      const dateStr = new Date(timestamp).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', hour12: true
      });

      calls.push({
        number: phone,
        duration,
        date: timestamp,
        type,
        presentation: 1,
        subscription_id: 1,
        post_dial_digits: '',
        subscription_component_name: 'com.android.phone/com.android.services.telephony.TelephonyConnectionService',
        readable_date: dateStr,
        contact_name: escapeXml(name),
      });
    }
  }

  // Sort by date
  calls.sort((a, b) => a.date - b.date);

  let xml = '<?xml version=\'1.0\' encoding=\'UTF-8\' standalone=\'yes\' ?>\n';
  xml += `<!--File Created By Synthetic Data Generator-->\n`;
  xml += `<calls count="${calls.length}" backup_set="${crypto.randomUUID()}" backup_date="${now}" type="full">\n`;

  for (const c of calls) {
    xml += `  <call number="${c.number}" duration="${c.duration}" date="${c.date}" type="${c.type}" `;
    xml += `presentation="${c.presentation}" subscription_id="${c.subscription_id}" `;
    xml += `post_dial_digits="${c.post_dial_digits}" `;
    xml += `subscription_component_name="${c.subscription_component_name}" `;
    xml += `readable_date="${c.readable_date}" contact_name="${c.contact_name}" />\n`;
  }

  xml += '</calls>\n';
  return { xml, count: calls.length };
}

// ── Main execution ───────────────────────────────────────────
const outDir = path.join(__dirname, '..', 'generated-data');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

console.log('=== Synthetic Android Data Generator ===\n');

// Generate VCF
console.log('[1/3] Generating 500 contacts (VCF 3.0)...');
const vcf = generateVCF(500);
const vcfPath = path.join(outDir, '500_US_Contacts.vcf');
fs.writeFileSync(vcfPath, vcf, 'utf-8');
console.log(`  → ${vcfPath} (${(Buffer.byteLength(vcf)/1024).toFixed(1)} KB)`);

// Generate SMS XML
console.log('[2/3] Generating SMS history (XML)...');
const sms = generateSmsXml(500, 389);
const smsPath = path.join(outDir, 'sms_backup.xml');
fs.writeFileSync(smsPath, sms.xml, 'utf-8');
console.log(`  → ${smsPath} (${sms.count} messages, ${(Buffer.byteLength(sms.xml)/1024).toFixed(1)} KB)`);

// Generate Call Log XML
console.log('[3/3] Generating call log history (XML)...');
const callLog = generateCallLogXml(500, 356);
const callPath = path.join(outDir, 'calls_backup.xml');
fs.writeFileSync(callPath, callLog.xml, 'utf-8');
console.log(`  → ${callPath} (${callLog.count} records, ${(Buffer.byteLength(callLog.xml)/1024).toFixed(1)} KB)`);

console.log('\n=== Generation Complete ===');
console.log(`Total: 500 contacts, ${sms.count} SMS, ${callLog.count} calls`);
console.log(`Output directory: ${outDir}`);
