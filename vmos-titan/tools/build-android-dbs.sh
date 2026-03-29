#!/bin/bash
# Build Android SQLite databases on server for VMOS injection
# Requires: sqlite3 on the server

set -e
OUTDIR="/root/Titan-android-v13/vmos-titan/generated-data"
mkdir -p "$OUTDIR"

echo "=== Building Android SQLite Databases ==="

# ── 1. CALL LOG DATABASE ─────────────────────────────────────
echo "[1/3] Building calllog.db (1500 records)..."
CALLDB="$OUTDIR/calllog.db"
rm -f "$CALLDB"

sqlite3 "$CALLDB" << 'SCHEMA'
CREATE TABLE IF NOT EXISTS calls (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT,
  presentation INTEGER NOT NULL DEFAULT 1,
  date INTEGER,
  duration INTEGER,
  type INTEGER,
  features INTEGER NOT NULL DEFAULT 0,
  new INTEGER NOT NULL DEFAULT 1,
  name TEXT,
  numbertype INTEGER,
  numberlabel TEXT,
  countryiso TEXT DEFAULT 'US',
  geocoded_location TEXT,
  phone_account_component_name TEXT DEFAULT 'com.android.phone/com.android.services.telephony.TelephonyConnectionService',
  phone_account_id TEXT DEFAULT '0',
  subscription_id INTEGER DEFAULT 1,
  subscription_component_name TEXT DEFAULT 'com.android.phone/com.android.services.telephony.TelephonyConnectionService',
  post_dial_digits TEXT DEFAULT '',
  via_number TEXT DEFAULT '',
  is_read INTEGER DEFAULT 1,
  add_for_all_users INTEGER DEFAULT 1,
  last_modified INTEGER,
  call_screening_app_name TEXT,
  call_screening_component_name TEXT,
  block_reason INTEGER DEFAULT 0,
  missed_reason INTEGER DEFAULT 0,
  priority INTEGER DEFAULT 0,
  subject TEXT
);
SCHEMA

# Generate 1500 call records
python3 -c "
import random, time

now_ms = int(time.time() * 1000)
start_ms = now_ms - (356 * 86400 * 1000)

first_names = ['James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
  'William','Barbara','Richard','Susan','Joseph','Jessica','Thomas','Sarah','Christopher','Karen',
  'Charles','Lisa','Daniel','Nancy','Matthew','Betty','Anthony','Margaret','Mark','Sandra',
  'Donald','Ashley','Steven','Kimberly','Paul','Emily','Andrew','Donna','Joshua','Michelle',
  'Kenneth','Carol','Kevin','Amanda','Brian','Dorothy','George','Melissa','Timothy','Deborah',
  'Ronald','Stephanie','Edward','Rebecca','Jason','Sharon','Jeffrey','Laura','Ryan','Cynthia',
  'Jacob','Kathleen','Gary','Amy','Nicholas','Angela','Eric','Jonathan','Stephen','Larry',
  'Justin','Scott','Brandon','Benjamin','Samuel','Raymond','Gregory','Frank','Alexander','Patrick',
  'Jack','Dennis','Jerry','Tyler','Aaron','Jose','Nathan','Henry','Peter','Douglas','Adam','Zachary']
last_names = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin',
  'Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
  'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen','Hill','Flores',
  'Green','Adams','Nelson','Baker','Hall','Rivera','Campbell','Mitchell','Carter','Roberts']

stmts = []
for i in range(1500):
    area = random.randint(200, 999)
    prefix = random.randint(200, 999)
    line = random.randint(1000, 9999)
    number = f'+1{area}{prefix}{line}'
    date = random.randint(start_ms, now_ms)
    call_type = random.choice([1,1,1,2,2,2,3])
    if call_type == 3:
        duration = 0
    else:
        roll = random.random()
        if roll < 0.6: duration = random.randint(5, 120)
        elif roll < 0.9: duration = random.randint(120, 900)
        else: duration = random.randint(900, 3600)
    name = f'{random.choice(first_names)} {random.choice(last_names)}'
    new_flag = 0 if call_type != 3 else random.randint(0,1)
    name_esc = name.replace(\"'\", \"''\")
    stmts.append(f\"INSERT INTO calls (number,date,duration,type,name,new,is_read,last_modified) VALUES ('{number}',{date},{duration},{call_type},'{name_esc}',{new_flag},1,{date // 1000});\")

print('\n'.join(stmts))
" | sqlite3 "$CALLDB"

CALL_COUNT=$(sqlite3 "$CALLDB" "SELECT COUNT(*) FROM calls;")
echo "  → $CALLDB ($CALL_COUNT records, $(du -h "$CALLDB" | cut -f1))"

# ── 2. SMS DATABASE ──────────────────────────────────────────
echo "[2/3] Building mmssms.db (1500 messages)..."
SMSDB="$OUTDIR/mmssms.db"
rm -f "$SMSDB"

sqlite3 "$SMSDB" << 'SCHEMA'
CREATE TABLE IF NOT EXISTS sms (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL DEFAULT 0,
  address TEXT,
  person INTEGER,
  date INTEGER,
  date_sent INTEGER DEFAULT 0,
  protocol INTEGER DEFAULT 0,
  read INTEGER DEFAULT 1,
  status INTEGER DEFAULT -1,
  type INTEGER,
  reply_path_present INTEGER DEFAULT 0,
  subject TEXT,
  body TEXT,
  service_center TEXT,
  locked INTEGER DEFAULT 0,
  sub_id INTEGER DEFAULT -1,
  error_code INTEGER DEFAULT -1,
  creator TEXT DEFAULT 'com.google.android.apps.messaging',
  seen INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS threads (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  date INTEGER DEFAULT 0,
  message_count INTEGER DEFAULT 0,
  recipient_ids TEXT,
  snippet TEXT,
  snippet_cs INTEGER DEFAULT 0,
  read INTEGER DEFAULT 1,
  archived INTEGER DEFAULT 0,
  type INTEGER DEFAULT 0,
  error INTEGER DEFAULT 0,
  has_attachment INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS canonical_addresses (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT NOT NULL
);
SCHEMA

python3 -c "
import random, time

now_ms = int(time.time() * 1000)
start_ms = now_ms - (389 * 86400 * 1000)

first_names = ['James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
  'William','Barbara','Richard','Susan','Joseph','Jessica','Thomas','Sarah','Christopher','Karen',
  'Charles','Lisa','Daniel','Nancy','Matthew','Betty','Anthony','Margaret','Mark','Sandra']
last_names = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin']

msgs = [
  'Hey are you free tonight?','Can you call me back?','Thanks for dinner!',
  'Meeting at 3pm confirmed','Got your message','Running 10 mins late',
  'Happy birthday!','Did you see the game?','Pick up milk on the way home',
  'Just landed will call soon','Love you have a great day','What time works for you?',
  'Be there in 20 minutes','Sorry I missed your call','Sounds good see you then',
  'Can you send me that address?','Thanks for your help today','Still on for tomorrow?',
  'Just finished work heading home','Let me know when youre ready',
  'The package arrived today','Hows your day going?','Want to grab lunch?',
  'Im at the store need anything?','Great news got the job!','Traffic is terrible',
  'Movie starts at 7 dont be late','Can you watch the kids Saturday?','Doctor appt at 10am',
  'Flight delayed 2 hours','Pizza or Chinese tonight?','Your mom called',
  'Reminder dentist tomorrow 9am','Just sent you the photos','WiFi password sunshine2024',
  'Dont forget electric bill','Ill pick you up at 6','How was the interview?',
  'Congrats on the promotion!','Need to reschedule lunch','Weather looks great this weekend',
  'Forward me that email please','Stuck in traffic be there soon','Thank you for everything',
  'Miss you when can we hang?','Quick question about project','Car broke down can you help?',
  'Dont forget Moms birthday Friday','Good morning!','Goodnight sleep well',
  'TGIF any plans?','Kids miss you come visit','New restaurant wanna try?',
  'Got home safe','Can you Venmo me for dinner?','Game night my place Saturday?',
  'Heading to gym call you after','Did you submit the report?','Prescription ready for pickup',
  'Snow day no school tomorrow!','Happy anniversary!','Dog needs the vet',
  'Yard sale this weekend','Thanks for the birthday gift','Need a ride to airport Tuesday',
  'Book club moved to Thursday','Your turn to bring snacks','Power went out using candles',
  'Found your keys under the couch','Grocery list eggs bread cheese apples',
  'PTA meeting tonight at 7','Oil change reminder',
]

stmts = []
contacts = []
for i in range(500):
    area = random.randint(200, 999)
    prefix = random.randint(200, 999)
    line = random.randint(1000, 9999)
    number = f'+1{area}{prefix}{line}'
    contacts.append(number)
    # Add canonical address
    stmts.append(f\"INSERT INTO canonical_addresses (address) VALUES ('{number}');\")

thread_id = 0
for i, number in enumerate(contacts):
    thread_id += 1
    msg_count = random.randint(2, 5)
    thread_msgs = []
    for j in range(msg_count):
        date = random.randint(start_ms, now_ms)
        sms_type = random.choice([1, 2])  # 1=received, 2=sent
        body = random.choice(msgs).replace(\"'\", \"''\")
        date_sent = date if sms_type == 2 else 0
        stmts.append(f\"INSERT INTO sms (thread_id,address,date,date_sent,type,body,read,seen) VALUES ({thread_id},'{number}',{date},{date_sent},{sms_type},'{body}',1,1);\")
        thread_msgs.append((date, body))
    # Update thread
    latest = max(thread_msgs, key=lambda x: x[0])
    snippet = latest[1][:100].replace(\"'\", \"''\")
    stmts.append(f\"INSERT INTO threads (_id,date,message_count,recipient_ids,snippet,read) VALUES ({thread_id},{latest[0]},{msg_count},'{i+1}','{snippet}',1);\")

print('\n'.join(stmts))
" | sqlite3 "$SMSDB"

SMS_COUNT=$(sqlite3 "$SMSDB" "SELECT COUNT(*) FROM sms;")
THREAD_COUNT=$(sqlite3 "$SMSDB" "SELECT COUNT(*) FROM threads;")
echo "  → $SMSDB ($SMS_COUNT messages, $THREAD_COUNT threads, $(du -h "$SMSDB" | cut -f1))"

# ── 3. CONTACTS DATABASE (simplified — raw_contacts + data) ──
echo "[3/3] Building contacts2.db (500 contacts)..."
CONTACTDB="$OUTDIR/contacts2.db"
rm -f "$CONTACTDB"

sqlite3 "$CONTACTDB" << 'SCHEMA'
CREATE TABLE IF NOT EXISTS raw_contacts (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_name TEXT DEFAULT 'epolusamuel682@gmail.com',
  account_type TEXT DEFAULT 'com.google',
  sourceid TEXT,
  raw_contact_is_user_profile INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  dirty INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  contact_id INTEGER,
  aggregation_mode INTEGER NOT NULL DEFAULT 0,
  aggregation_needed INTEGER NOT NULL DEFAULT 0,
  custom_ringtone TEXT,
  send_to_voicemail INTEGER NOT NULL DEFAULT 0,
  times_contacted INTEGER NOT NULL DEFAULT 0,
  last_time_contacted INTEGER,
  starred INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  display_name TEXT,
  display_name_alt TEXT,
  display_name_source INTEGER NOT NULL DEFAULT 40,
  phonetic_name TEXT,
  phonetic_name_style INTEGER NOT NULL DEFAULT 0,
  sort_key TEXT,
  phonebook_label TEXT,
  phonebook_bucket INTEGER DEFAULT 0,
  sort_key_alt TEXT,
  phonebook_label_alt TEXT,
  phonebook_bucket_alt INTEGER DEFAULT 0,
  name_verified INTEGER NOT NULL DEFAULT 0,
  backup_id TEXT,
  metadata_dirty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contacts (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  name_raw_contact_id INTEGER,
  photo_id INTEGER,
  photo_file_id INTEGER,
  custom_ringtone TEXT,
  send_to_voicemail INTEGER NOT NULL DEFAULT 0,
  times_contacted INTEGER NOT NULL DEFAULT 0,
  last_time_contacted INTEGER,
  starred INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  has_phone_number INTEGER NOT NULL DEFAULT 0,
  lookup TEXT,
  status_update_id INTEGER,
  contact_last_updated_timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS data (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  package_id INTEGER,
  mimetype_id INTEGER NOT NULL,
  raw_contact_id INTEGER NOT NULL,
  is_super_primary INTEGER NOT NULL DEFAULT 0,
  data_version INTEGER NOT NULL DEFAULT 0,
  is_primary INTEGER NOT NULL DEFAULT 0,
  is_read_only INTEGER NOT NULL DEFAULT 0,
  data1 TEXT,
  data2 TEXT,
  data3 TEXT,
  data4 TEXT,
  data5 TEXT,
  data6 TEXT,
  data7 TEXT,
  data8 TEXT,
  data9 TEXT,
  data10 TEXT,
  data11 TEXT,
  data12 TEXT,
  data13 TEXT,
  data14 TEXT,
  data15 BLOB,
  data_sync1 TEXT,
  data_sync2 TEXT,
  data_sync3 TEXT,
  data_sync4 TEXT,
  carrier_presence INTEGER NOT NULL DEFAULT 0,
  preferred_phone_account_component_name TEXT,
  preferred_phone_account_id TEXT
);

CREATE TABLE IF NOT EXISTS mimetypes (
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
  mimetype TEXT NOT NULL UNIQUE
);
INSERT INTO mimetypes (mimetype) VALUES ('vnd.android.cursor.item/name');
INSERT INTO mimetypes (mimetype) VALUES ('vnd.android.cursor.item/phone_v2');
INSERT INTO mimetypes (mimetype) VALUES ('vnd.android.cursor.item/email_v2');

CREATE TABLE IF NOT EXISTS phone_lookup (
  data_id INTEGER NOT NULL,
  raw_contact_id INTEGER NOT NULL,
  normalized_number TEXT NOT NULL,
  min_match TEXT NOT NULL
);
SCHEMA

python3 -c "
import random, time, hashlib

first_names = ['James','Mary','Robert','Patricia','John','Jennifer','Michael','Linda','David','Elizabeth',
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
  'Christina','Joan','Evelyn','Judith','Megan','Andrea','Cheryl','Hannah','Jacqueline','Martha']
last_names = ['Smith','Johnson','Williams','Brown','Jones','Garcia','Miller','Davis','Rodriguez','Martinez',
  'Hernandez','Lopez','Gonzalez','Wilson','Anderson','Thomas','Taylor','Moore','Jackson','Martin',
  'Lee','Perez','Thompson','White','Harris','Sanchez','Clark','Ramirez','Lewis','Robinson',
  'Walker','Young','Allen','King','Wright','Scott','Torres','Nguyen','Hill','Flores',
  'Green','Adams','Nelson','Baker','Hall','Rivera','Campbell','Mitchell','Carter','Roberts',
  'Gomez','Phillips','Evans','Turner','Diaz','Parker','Cruz','Edwards','Collins','Reyes',
  'Stewart','Morris','Morales','Murphy','Cook','Rogers','Gutierrez','Ortiz','Morgan','Cooper',
  'Peterson','Bailey','Reed','Kelly','Howard','Ramos','Kim','Cox','Ward','Richardson']

now = int(time.time())
stmts = []
used = set()
data_id = 0

for i in range(500):
    while True:
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        full = f'{fn} {ln}'
        if full not in used:
            used.add(full)
            break
    
    raw_id = i + 1
    contact_id = i + 1
    area = random.randint(200, 999)
    prefix = random.randint(200, 999)
    line = random.randint(1000, 9999)
    phone = f'+1{area}{prefix}{line}'
    phone_norm = phone
    min_match = phone[-7:][::-1]  # reversed last 7 digits
    lookup = hashlib.md5(full.encode()).hexdigest()[:16]
    last_contact = now - random.randint(0, 356*86400)
    times = random.randint(0, 25)
    
    full_esc = full.replace(\"'\", \"''\")
    fn_esc = fn.replace(\"'\", \"''\")
    ln_esc = ln.replace(\"'\", \"''\")
    
    # raw_contacts
    stmts.append(f\"INSERT INTO raw_contacts (_id,contact_id,display_name,display_name_alt,sort_key,sort_key_alt,phonebook_label,phonebook_label_alt,times_contacted,last_time_contacted) VALUES ({raw_id},{contact_id},'{full_esc}','{ln_esc}, {fn_esc}','{full_esc}','{ln_esc}, {fn_esc}','{full_esc[0]}','{ln_esc[0]}',{times},{last_contact});\")
    
    # contacts
    stmts.append(f\"INSERT INTO contacts (_id,name_raw_contact_id,has_phone_number,lookup,times_contacted,last_time_contacted,contact_last_updated_timestamp) VALUES ({contact_id},{raw_id},1,'{lookup}',{times},{last_contact},{now});\")
    
    # data: name (mimetype_id=1)
    data_id += 1
    stmts.append(f\"INSERT INTO data (_id,mimetype_id,raw_contact_id,data1,data2,data3,data7,data8,data9,data11) VALUES ({data_id},1,{raw_id},'{full_esc}','{fn_esc}','{ln_esc}','{fn_esc}','{ln_esc}','{full_esc}','{full_esc}');\")
    
    # data: phone (mimetype_id=2)
    data_id += 1
    stmts.append(f\"INSERT INTO data (_id,mimetype_id,raw_contact_id,data1,data2,data4) VALUES ({data_id},2,{raw_id},'{phone}',2,'{phone_norm}');\")
    
    # phone_lookup
    stmts.append(f\"INSERT INTO phone_lookup (data_id,raw_contact_id,normalized_number,min_match) VALUES ({data_id},{raw_id},'{phone_norm}','{min_match}');\")
    
    # Optional email (~30%)
    if random.random() < 0.3:
        data_id += 1
        email = f'{fn.lower()}.{ln.lower()}{random.randint(1,99)}@gmail.com'
        stmts.append(f\"INSERT INTO data (_id,mimetype_id,raw_contact_id,data1,data2) VALUES ({data_id},3,{raw_id},'{email}',1);\")

print('\n'.join(stmts))
" | sqlite3 "$CONTACTDB"

CONTACT_COUNT=$(sqlite3 "$CONTACTDB" "SELECT COUNT(*) FROM raw_contacts;")
DATA_COUNT=$(sqlite3 "$CONTACTDB" "SELECT COUNT(*) FROM data;")
echo "  → $CONTACTDB ($CONTACT_COUNT contacts, $DATA_COUNT data rows, $(du -h "$CONTACTDB" | cut -f1))"

echo ""
echo "=== All databases built ==="
ls -lh "$OUTDIR"/*.db
echo ""
echo "Total sizes:"
du -ch "$OUTDIR"/*.db | tail -1
