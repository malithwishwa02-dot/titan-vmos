# Provincial Injection Protocol

The Provincial Injection Protocol (`core/provincial_injection_protocol.py`) is a robust, multi-phase data injection system designed for high-reliability contact, call log, and SMS injection into Cuttlefish Android VMs. It addresses provider crashes, database corruption, and timing issues that occur with naive batch injection.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Protocol Overview](#2-protocol-overview)
3. [Phase 1: Pre-Flight Checks](#3-phase-1-pre-flight-checks)
4. [Phase 2: Provider Shutdown](#4-phase-2-provider-shutdown)
5. [Phase 3: Database Backup](#5-phase-3-database-backup)
6. [Phase 4: SQLite Batch Injection](#6-phase-4-sqlite-batch-injection)
7. [Phase 5: Permission Repair](#7-phase-5-permission-repair)
8. [Phase 6: Provider Restart](#8-phase-6-provider-restart)
9. [Phase 7: Health Verification](#9-phase-7-health-verification)
10. [Phase 8: Fallback ADB Insert](#10-phase-8-fallback-adb-insert)
11. [Error Handling](#11-error-handling)
12. [API Reference](#12-api-reference)

---

## 1. Problem Statement

### Issues with Naive SQLite Injection

1. **Provider Crash Loop:** Contacts provider detects DB modification while running → infinite crash-restart
2. **Permission Corruption:** Incorrect UID/GID causes `EACCES` errors
3. **SELinux Denials:** Missing `restorecon` breaks provider access
4. **Database Locking:** WAL mode causes "database is locked" errors
5. **Sync Conflicts:** Provider syncs with Google mid-injection → data loss

### V12 Solution: 8-Phase Protocol

```
┌─────────────────────────────────────────────────────────────┐
│  Provincial Injection Protocol                               │
├─────────────────────────────────────────────────────────────┤
│  Phase 1: Pre-Flight      → Check device state, screen wake  │
│  Phase 2: Shutdown        → Stop contacts provider           │
│  Phase 3: Backup          → Backup existing DB               │
│  Phase 4: Injection       → SQLite batch with BEGIN IMMEDIATE│
│  Phase 5: Permissions     → chown, chmod, restorecon         │
│  Phase 6: Restart         → Start provider, trigger sync     │
│  Phase 7: Health Check    → Verify via content query         │
│  Phase 8: Fallback        → ADB content insert if needed   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Protocol Overview

```python
from provincial_injection_protocol import ProvincialInjectionProtocol

protocol = ProvincialInjectionProtocol(adb_target="127.0.0.1:6520")
result = protocol.inject_contacts_provincial(
    contacts=profile["contacts"],      # List of contact dicts
    calls=profile["call_logs"],         # List of call dicts
    sms=profile["sms"]                 # List of SMS dicts
)

# result.ok = True/False
# result.contacts_injected = N
# result.calls_injected = N
# result.sms_injected = N
# result.errors = []  # Empty if success
```

---

## 3. Phase 1: Pre-Flight Checks

### Screen Wake
```python
adb shell "input keyevent KEYCODE_WAKEUP; svc power stayon true"
```

### Database State Check
```python
# Check if contacts2.db exists and is accessible
ok, _ = adb_shell("ls -la /data/data/com.android.providers.contacts/databases/contacts2.db")
if not ok:
    # Create directory structure
    adb_shell("mkdir -p /data/data/com.android.providers.contacts/databases")
    adb_shell("chmod 771 /data/data/com.android.providers.contacts/databases")
```

### Provider State
```python
# Check if provider is running
ok, output = adb_shell("ps -A | grep contacts")
provider_running = "com.android.providers.contacts" in output
```

---

## 4. Phase 2: Provider Shutdown

### Critical Step: Stop Provider Before DB Write

```python
def _shutdown_provider(self):
    """Stop contacts provider to prevent corruption."""
    # Force stop (kills process)
    adb_shell("am force-stop com.android.providers.contacts")
    
    # Disable user (prevents auto-restart)
    adb_shell("pm disable-user --user 0 com.android.providers.contacts")
    
    # Wait for process termination
    time.sleep(2)
    
    # Verify stopped
    ok, output = adb_shell("ps -A | grep contacts")
    if "com.android.providers.contacts" in output:
        raise ProviderShutdownError("Provider still running after force-stop")
```

---

## 5. Phase 3: Database Backup

### Backup Existing Data

```python
def _backup_database(self) -> str:
    """Create timestamped backup of contacts2.db."""
    backup_path = f"/data/data/com.android.providers.contacts/databases/contacts2.db.bak.{int(time.time())}"
    
    # Check if DB exists
    ok, _ = adb_shell("ls /data/data/com.android.providers.contacts/databases/contacts2.db")
    if ok:
        # Create backup
        adb_shell(f"cp /data/data/com.android.providers.contacts/databases/contacts2.db {backup_path}")
        adb_shell(f"chmod 600 {backup_path}")
        return backup_path
    return None
```

---

## 6. Phase 4: SQLite Batch Injection

### Pull-Modify-Push Pattern

```python
def _inject_contacts_sqlite(self, contacts: List[Dict]):
    """SQLite batch injection with proper transaction handling."""
    
    # 1. Pull existing DB (or create new)
    local_db = "/tmp/contacts2_inject.db"
    ok, _ = adb_shell("ls /data/data/com.android.providers.contacts/databases/contacts2.db")
    if ok:
        adb_pull("/data/data/com.android.providers.contacts/databases/contacts2.db", local_db)
    else:
        # Create new DB with schema
        conn = sqlite3.connect(local_db)
        conn.executescript(CONTACTS_SCHEMA_SQL)
        conn.commit()
        conn.close()
    
    # 2. Modify locally
    conn = sqlite3.connect(local_db)
    cursor = conn.cursor()
    
    # Use IMMEDIATE transaction mode (prevents locking issues)
    cursor.execute("BEGIN IMMEDIATE")
    
    try:
        for contact in contacts:
            # Insert raw_contact
            cursor.execute('''
                INSERT INTO raw_contacts (contact_id, account_type, account_name, display_name, deleted)
                VALUES (?, ?, ?, ?, 0)
            ''', (
                contact.get('id', 0),
                'com.google',
                self.persona_email,
                contact['name']
            ))
            raw_id = cursor.lastrowid
            
            # Insert phone numbers
            for phone in contact.get('phones', []):
                cursor.execute('''
                    INSERT INTO data (raw_contact_id, mimetype_id, data1, data2, is_primary)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    raw_id,
                    MIMETYPE_ID_PHONE,
                    phone['number'],
                    phone.get('type', 'mobile'),
                    1 if phone.get('primary') else 0
                ))
            
            # Insert emails
            for email in contact.get('emails', []):
                cursor.execute('''
                    INSERT INTO data (raw_contact_id, mimetype_id, data1, data2)
                    VALUES (?, ?, ?, ?)
                ''', (
                    raw_id,
                    MIMETYPE_ID_EMAIL,
                    email['address'],
                    email.get('type', 'home')
                ))
        
        conn.commit()
        
    except sqlite3.Error as e:
        conn.rollback()
        raise InjectionError(f"SQLite error: {e}")
    finally:
        conn.close()
    
    # 3. Push back to device
    adb_push(local_db, "/data/data/com.android.providers.contacts/databases/contacts2.db")
    
    # Clean up local temp
    os.unlink(local_db)
```

### Call Logs Injection

```python
def _inject_calls_sqlite(self, calls: List[Dict]):
    """Inject call logs into calllog.db."""
    local_db = "/tmp/calllog_inject.db"
    
    # Similar pull-modify-push pattern
    ok, _ = adb_shell("ls /data/data/com.android.providers.contacts/databases/calllog.db")
    if ok:
        adb_pull("/data/data/com.android.providers.contacts/databases/calllog.db", local_db)
    else:
        conn = sqlite3.connect(local_db)
        conn.executescript(CALLLOG_SCHEMA_SQL)
        conn.commit()
        conn.close()
    
    conn = sqlite3.connect(local_db)
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE")
    
    try:
        for call in calls:
            cursor.execute('''
                INSERT INTO calls (number, type, duration, date, name, new, geocoded_location)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                call['number'],
                call['type'],  # 1=incoming, 2=outgoing, 3=missed
                call.get('duration', 0),
                call['date'],  # Unix timestamp ms
                call.get('name', ''),
                1,  # new
                call.get('geocoded_location', '')
            ))
        
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise InjectionError(f"SQLite error: {e}")
    finally:
        conn.close()
    
    adb_push(local_db, "/data/data/com.android.providers.contacts/databases/calllog.db")
    os.unlink(local_db)
```

---

## 7. Phase 5: Permission Repair

### Fix Ownership and SELinux

```python
def _repair_permissions(self):
    """Set correct UID/GID and SELinux context."""
    
    # Get contacts provider UID
    ok, uid_output = adb_shell("stat -c %u /data/data/com.android.providers.contacts")
    if not ok or not uid_output.strip():
        uid = "10020"  # Default u0_a20
    else:
        uid = uid_output.strip()
    
    # chown to provider UID
    adb_shell(f"chown {uid}:{uid} /data/data/com.android.providers.contacts/databases/contacts2.db")
    adb_shell(f"chown {uid}:{uid} /data/data/com.android.providers.contacts/databases/calllog.db")
    
    # chmod
    adb_shell("chmod 660 /data/data/com.android.providers.contacts/databases/contacts2.db")
    adb_shell("chmod 660 /data/data/com.android.providers.contacts/databases/calllog.db")
    adb_shell("chmod 771 /data/data/com.android.providers.contacts/databases")
    
    # SELinux restorecon (critical!)
    adb_shell("restorecon -R /data/data/com.android.providers.contacts/databases/")
    
    # Also fix parent directory
    adb_shell(f"chown {uid}:{uid} /data/data/com.android.providers.contacts")
    adb_shell("chmod 751 /data/data/com.android.providers.contacts")
```

---

## 8. Phase 6: Provider Restart

### Enable and Trigger Sync

```python
def _restart_provider(self):
    """Restart contacts provider and trigger sync."""
    
    # Re-enable provider
    adb_shell("pm enable com.android.providers.contacts")
    
    # Send boot completed broadcast (triggers provider init)
    adb_shell("am broadcast -a android.intent.action.BOOT_COMPLETED -p com.android.providers.contacts")
    
    # Wait for provider to initialize
    time.sleep(3)
    
    # Trigger sync
    adb_shell("am broadcast -a android.intent.action.SYNC -p com.android.providers.contacts")
    
    # Wait for sync to complete
    time.sleep(2)
```

---

## 9. Phase 7: Health Verification

### Verify Injection Success

```python
def _health_check(self) -> Dict[str, bool]:
    """Verify data accessible via content provider."""
    results = {}
    
    # Check contacts
    ok, count = adb_shell(
        "content query --uri content://com.android.contacts/raw_contacts | wc -l"
    )
    results['contacts'] = ok and int(count) > 0
    
    # Check calls
    ok, count = adb_shell(
        "content query --uri content://call_log/calls | wc -l"
    )
    results['calls'] = ok and int(count) > 0
    
    # Check SMS
    ok, count = adb_shell(
        "content query --uri content://sms | wc -l"
    )
    results['sms'] = ok and int(count) > 0
    
    return results
```

---

## 10. Phase 8: Fallback ADB Insert

### Content Provider Fallback

If SQLite injection fails, fall back to slower but safer `content insert`:

```python
def _fallback_adb_insert(self, contacts: List[Dict]) -> bool:
    """Fallback to ADB content provider insert."""
    try:
        for contact in contacts[:10]:  # Limit to first 10 in fallback
            # Insert via content provider
            adb_shell(f'''
                content insert --uri content://com.android.contacts/raw_contacts \\
                    --bind account_type:s:com.google \\
                    --bind account_name:s:{self.persona_email}
            ''')
        return True
    except Exception as e:
        logger.error(f"Fallback insert failed: {e}")
        return False
```

---

## 11. Error Handling

### Exception Hierarchy

```python
class ProvincialInjectionError(Exception):
    """Base protocol error."""
    pass

class ProviderShutdownError(ProvincialInjectionError):
    """Failed to stop contacts provider."""
    pass

class DatabaseLockedError(ProvincialInjectionError):
    """SQLite database locked."""
    pass

class PermissionError(ProvincialInjectionError):
    """Failed to set correct permissions."""
    pass

class HealthCheckError(ProvincialInjectionError):
    """Post-injection health check failed."""
    pass
```

### Recovery Strategies

| Error | Recovery |
|-------|----------|
| ProviderShutdownError | Retry with `am kill` before `force-stop` |
| DatabaseLockedError | Wait 5s, retry with `BEGIN EXCLUSIVE` |
| PermissionError | Try `run-as` context or skip SELinux |
| HealthCheckError | Run `pm clear` and retry with ADB fallback |

---

## 12. API Reference

### ProvincialInjectionProtocol

```python
class ProvincialInjectionProtocol:
    """Robust multi-phase injection protocol for contacts/calls/SMS."""
    
    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self.persona_email = None
    
    def inject_contacts_provincial(
        self,
        contacts: List[Dict],
        persona_email: str
    ) -> InjectionResult:
        """
        Inject contacts using 8-phase protocol.
        
        Args:
            contacts: List of contact dicts with name, phones, emails
            persona_email: Google account email for account_name field
            
        Returns:
            InjectionResult with ok, count, errors
        """
        pass
    
    def inject_calls_provincial(
        self,
        calls: List[Dict]
    ) -> InjectionResult:
        """Inject call logs using 8-phase protocol."""
        pass
    
    def inject_sms_provincial(
        self,
        sms: List[Dict]
    ) -> InjectionResult:
        """Inject SMS using 8-phase protocol."""
        pass
    
    def inject_full_profile(
        self,
        profile: Dict
    ) -> ProvincialResult:
        """
        Inject full profile (contacts + calls + SMS).
        
        Returns:
            ProvincialResult with per-category results
        """
        pass
```

### InjectionResult

```python
@dataclass
class InjectionResult:
    ok: bool
    count: int
    errors: List[str]
    backup_path: Optional[str]  # Path to DB backup if created
    phase_timings: Dict[str, float]  # Per-phase timing
```

---

## See Also

- [04-profile-injector.md](./04-profile-injector.md) — Legacy injection methods
- [03-genesis-pipeline.md](./03-genesis-pipeline.md) — Full profile injection pipeline
- [02-anomaly-patcher.md](./02-anomaly-patcher.md) — Device stealth patching
