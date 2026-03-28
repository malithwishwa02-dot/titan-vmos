#!/usr/bin/env python3
"""Hard reset device data and re-forge with Jovany Owens persona."""
import subprocess, time, json, sys

ADB = "adb -s 127.0.0.1:6520"
API = "http://127.0.0.1:8080"
TOKEN = "f5e89e29b1cb9a8d79bf25f8fdb556e4c7fea4cec7f06af5d74c4f35543b9868"

def adb(cmd, timeout=15):
    """Run ADB shell command."""
    full = f"{ADB} shell \"{cmd}\""
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "[timeout]"

def api(method, path, body=None, timeout=60):
    """Call API endpoint."""
    import urllib.request
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, method=method, data=data,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

print("=" * 60)
print("PHASE 1: HARD RESET — Wiping all persona data")
print("=" * 60)

# Step 1: Remove Google account
print("\n[1/10] Removing Google accounts...")
out = adb("am broadcast -a com.google.android.gms.CLEAR_ACCOUNT")
print(f"  {out}")

# Step 2: Wipe contacts
print("[2/10] Wiping contacts...")
adb("content delete --uri content://com.android.contacts/raw_contacts")
adb("rm -f /data/data/com.android.providers.contacts/databases/contacts2.db*")
adb("rm -f /data/data/com.android.providers.contacts/databases/calllog.db*")
adb("rm -f /data/data/com.android.providers.contacts/databases/profile.db*")
print(f"  Contacts wiped")

# Step 3: Wipe call logs  
print("[3/10] Wiping call logs...")
out = adb("content delete --uri content://call_log/calls")
print(f"  Call logs wiped")

# Step 4: Wipe SMS
print("[4/10] Wiping SMS...")
out = adb("content delete --uri content://sms")
print(f"  SMS wiped")

# Step 5: Wipe browser data (Chrome cookies, history, Kiwi)
print("[5/10] Wiping browser data (Chrome + Kiwi)...")
adb("rm -rf /data/data/com.android.chrome/app_chrome/Default/Cookies")
adb("rm -rf /data/data/com.android.chrome/app_chrome/Default/History")
adb("rm -rf /data/data/com.android.chrome/app_chrome/Default/Login\\ Data")
adb("rm -rf /data/data/com.android.chrome/app_chrome/Default/Web\\ Data")
adb("rm -rf /data/data/com.android.chrome/cache/*")
adb("rm -rf /data/data/com.kiwibrowser.browser/app_chrome/Default/*")
print(f"  Browser data wiped")

# Step 6: Wipe gallery/photos
print("[6/10] Wiping gallery photos...")
adb("rm -rf /sdcard/DCIM/*")
adb("rm -rf /sdcard/Pictures/*")
adb("rm -rf /sdcard/Download/*")
# Also wipe the underlying storage (FUSE /sdcard may be disconnected)
adb("rm -rf /data/media/0/DCIM/*")
adb("rm -rf /data/media/0/Pictures/*")
adb("rm -rf /data/media/0/Download/*")
print(f"  Gallery wiped")

# Step 7: Wipe WiFi configs
print("[7/10] Wiping WiFi configs...")
adb("rm -f /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml")
adb("rm -f /data/misc/wifi/WifiConfigStore.xml")
print(f"  WiFi configs wiped")

# Step 8: Wipe usage stats
print("[8/10] Wiping usage stats...")
adb("rm -rf /data/system/usagestats/0/*")
print(f"  Usage stats wiped")

# Step 9: Wipe Gboard learned data
print("[9/10] Wiping keyboard learned data...")
adb("rm -rf /data/data/com.google.android.inputmethod.latin/databases/*")
adb("rm -rf /data/data/com.google.android.inputmethod.latin/shared_prefs/*")
print(f"  Keyboard data wiped")

# Step 10: Wipe app usage / notifications DB
print("[10/10] Wiping notification history & app data...")
adb("rm -rf /data/system/notification_log/*")
adb("rm -rf /data/data/com.google.android.apps.maps/databases/*")
adb("rm -rf /data/data/com.google.android.apps.maps/cache/*")
print(f"  Notification/maps data wiped")

# Verify wipe
print("\n--- Verifying wipe ---")
contacts = adb("content query --uri content://com.android.contacts/contacts 2>/dev/null | wc -l")
print(f"  Contacts remaining: {contacts}")
accounts = adb("dumpsys account 2>/dev/null | grep 'Account {' | wc -l")
print(f"  Accounts remaining: {accounts}")

print("\n" + "=" * 60)
print("PHASE 2: FORGE — Jovany Owens persona")
print("=" * 60)

# Build unified forge body using Jovany Owens data from README
forge_body = {
    "mode": "manual",
    "occupation": "auto",
    "country": "US",
    "age": 66,  # Born 12/11/1959
    "gender": "M",
    "target_site": "",
    "use_ai": True,
    "age_days": 120,
    
    # Identity
    "name": "Jovany Owens",
    "email": "adiniorjuniorjd28@gmail.com",
    "phone": "(707) 836-1915",
    "dob": "12/11/1959",
    "ssn": "219-19-0937",
    "street": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90006",
    
    # Card
    "card_number": "4638512320340405",
    "card_exp": "08/2029",
    "card_cvv": "051",
    "card_holder": "Jovany Owens",
    
    # OSINT off for now
    "run_osint": False,
    
    # Proxy
    "proxy_url": "socks5h://2eiw7c10o5p:192aqpgq10x@91.231.186.249:1080",
    
    # Google account
    "google_email": "jovany.owens59@gmail.com",
    "google_password": "YCCvsukin7S",
    "real_phone": "+14304314828",
    "otp_code": "",
    
    # Device
    "device_id": "dev-cvd001",
    "device_model": "samsung_s24",
    "carrier": "tmobile_us",
    "location": "la",
    
    # Pipeline
    "inject": True,
    "full_provision": False,
}

print("\n[1/3] Calling unified-forge API...")
print(f"  Persona: {forge_body['name']}")
print(f"  Email: {forge_body['email']}")
print(f"  Country: {forge_body['country']}, City: {forge_body['city']}")
print(f"  Device: {forge_body['device_id']} ({forge_body['device_model']})")

result = api("POST", "/api/genesis/unified-forge", forge_body, timeout=120)

if "error" in result:
    print(f"\n  ERROR: {result['error']}")
    sys.exit(1)

profile = result.get("profile", {})
print(f"\n[2/3] Profile forged!")
print(f"  Profile ID: {profile.get('profile_id', '?')}")
stats = profile.get("stats", {})
print(f"  Contacts: {stats.get('contacts', 0)}")
print(f"  Call Logs: {stats.get('call_logs', 0)}")
print(f"  SMS: {stats.get('sms', 0)}")
print(f"  Cookies: {stats.get('cookies', 0)}")
print(f"  History: {stats.get('history', 0)}")
print(f"  Gallery: {stats.get('gallery', 0)}")
print(f"  Apps: {stats.get('apps', 0)}")

persona = profile.get("persona", {})
print(f"  Persona Name: {persona.get('name', '?')}")
print(f"  Persona Email: {persona.get('email', '?')}")
print(f"  Persona Phone: {persona.get('phone', '?')}")

osint = result.get("osint")
if osint:
    print(f"  OSINT: {osint.get('total_hits', 0)} hits")

proxy = result.get("proxy")
if proxy:
    print(f"  Proxy: {'OK' if proxy.get('reachable') else 'FAILED'} - {proxy.get('ip', proxy.get('error', '?'))}")

print(f"\n[3/3] Steps log:")
for step in result.get("steps_log", []):
    print(f"  → {step}")

print("\n" + "=" * 60)
print("PHASE 3: FULL PROVISION (inject + patch + trust)")
print("=" * 60)

profile_id = profile.get("profile_id")
if not profile_id:
    print("ERROR: No profile ID returned, aborting provision")
    sys.exit(1)

# Now trigger full provision
provision_body = {
    "profile_id": profile_id,
    "cc_number": "4638512320340405",
    "cc_exp_month": 8,
    "cc_exp_year": 2029,
    "cc_cvv": "051",
    "cc_cardholder": "Jovany Owens",
    "lockdown": False,
    "proxy_url": "socks5h://2eiw7c10o5p:192aqpgq10x@91.231.186.249:1080",
    "google_email": "jovany.owens59@gmail.com",
    "google_password": "YCCvsukin7S",
    "real_phone": "+14304314828",
    "otp_code": "",
}

print(f"\nStarting full provision on dev-cvd001 with profile {profile_id}...")
prov = api("POST", "/api/genesis/full-provision/dev-cvd001", provision_body, timeout=30)

if "error" in prov:
    print(f"  Provision start error: {prov['error']}")
    # Try direct inject + patch instead
    print("\n  Falling back to inject + patch separately...")
    
    # Inject
    print("  [Inject] Injecting profile...")
    inject_r = api("POST", "/api/genesis/inject/dev-cvd001", {
        "profile_id": profile_id,
        "cc_number": "4638512320340405",
        "cc_exp": "08/2029",
        "cc_cvv": "051",
        "age_days": 120,
    }, timeout=120)
    if "error" in inject_r:
        print(f"  Inject error: {inject_r['error']}")
    else:
        print(f"  Inject result: {json.dumps(inject_r, indent=2)[:500]}")
    
    # Patch
    print("  [Patch] Running stealth patch...")
    patch_r = api("POST", "/api/stealth/dev-cvd001/patch", {
        "preset": "samsung_s24",
        "carrier": "tmobile_us",
        "location": "la",
        "lockdown": False,
    }, timeout=600)
    if "error" in patch_r:
        print(f"  Patch error: {patch_r['error']}")
    else:
        score = patch_r.get("score", patch_r.get("patch_score", "?"))
        print(f"  Stealth Score: {score}%")
    
    # Trust
    print("  [Trust] Checking trust score...")
    trust_r = api("GET", "/api/genesis/trust-score/dev-cvd001", timeout=60)
    if "error" in trust_r:
        print(f"  Trust error: {trust_r['error']}")
    else:
        print(f"  Trust Score: {trust_r.get('trust_score', '?')}/100")
        checks = trust_r.get("checks", {})
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        print(f"  Checks: {passed}/{total}")
        failed = [k for k, v in checks.items() if not v]
        if failed:
            print(f"  Failed: {', '.join(failed)}")

else:
    job_id = prov.get("job_id", "")
    print(f"  Job ID: {job_id}")
    print("  Polling provision status...")
    
    for i in range(120):  # Up to 10 minutes
        time.sleep(5)
        status = api("GET", f"/api/genesis/provision-status/{job_id}", timeout=15)
        step = status.get("step", "?")
        step_n = status.get("step_n", 0)
        st = status.get("status", "?")
        print(f"  [{i*5}s] Step {step_n}: {step} — {st}")
        
        if st == "completed":
            print(f"\n  ✓ PROVISION COMPLETE!")
            print(f"  Stealth Score: {status.get('patch_score', '?')}%")
            print(f"  Trust Score: {status.get('trust_score', '?')}/100")
            print(f"  GSM: {'OK' if status.get('gsm', {}).get('ok') else 'FAIL'}")
            print(f"  Google: {'OK' if status.get('google_signin', {}).get('success') else status.get('google_signin', {})}")
            print(f"  Proxy: {status.get('proxy', {})}")
            
            checks = status.get("trust_checks", {})
            if checks:
                passed = sum(1 for v in checks.values() if v)
                total = len(checks)
                print(f"  Trust Checks: {passed}/{total}")
                failed = [k for k, v in checks.items() if not v]
                if failed:
                    print(f"  Failed checks: {', '.join(failed)}")
            break
        elif st == "failed":
            print(f"\n  ✗ PROVISION FAILED: {status.get('error', '?')}")
            break
    else:
        print("\n  TIMEOUT waiting for provision to complete")

# Post-provision: Inject browser Preferences for chrome_signin check
print("\n[POST] Injecting browser Preferences...")
kiwi_prefs = '{"account_info":[{"email":"jovany.owens59@gmail.com","full_name":"Jovany Owens"}],"browser":{"has_seen_welcome_page":true},"signin":{"allowed":true},"sync":{"has_setup_completed":true}}'
adb(f"mkdir -p /data/data/com.kiwibrowser.browser/app_chrome/Default")
adb(f"echo '{kiwi_prefs}' > /data/data/com.kiwibrowser.browser/app_chrome/Default/Preferences")
adb("chown u0_a109:u0_a109 /data/data/com.kiwibrowser.browser/app_chrome/Default/Preferences 2>/dev/null")
print("  Browser Preferences injected")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
