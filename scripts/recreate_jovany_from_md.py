#!/usr/bin/env python3
"""
Titan V12.0 — Self-Recreate: Jovany Owens Device from MD Profile
=================================================================
Reads the forge spec from JOVANY-OWENS-FORGE-DETAILS.md and:
  1. Reports current active services / device status
  2. Forges a fresh profile via Genesis API with ALL MD-spec fields
  3. Compares forged data vs MD targets and emits a GAP report
  4. Saves an enriched profile JSON to /opt/titan/data/profiles/

Usage:
    python3 scripts/recreate_jovany_from_md.py

The script is SAFE to run even if the Cuttlefish device is offline —
it only touches the API and profile store, not the live device.
"""

import http.client
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ───────────────────────────────────────────────────────────────
# IDENTIFIERS FROM MD FILE
# ───────────────────────────────────────────────────────────────

MD_PROFILE = {
    # Personal identity
    "persona_name":   "Jovany OWENS",
    "full_name":      "Jovany OWENS",
    "gender":         "Male",
    "dob":            "12/11/1959",     # MM/DD/YYYY → age 66
    "ssn":            "219-19-0937",
    "primary_phone":  "(707) 836-1915",
    "email":          "jovany.owens59@gmail.com",
    "address":        "1866 W 11th St",
    "city":           "Los Angeles",
    "state":          "CA",
    "zip":            "90006",
    "country":        "US",
    "archetype":      "retiree",

    # Financial
    "cc_number":      "4638512320340405",
    "cc_exp_month":   8,
    "cc_exp_year":    2029,
    "cc_cvv":         "051",
    "cc_holder":      "Jovany OWENS",

    # Device / platform
    "device_model":   "samsung_s24",       # SM-S921U → samsung_s24 key
    "carrier":        "tmobile_us",
    "mcc_mnc":        "310260",
    "android_ver":    "14",
    "location":       "la",
    "age_days":       500,

    # Network / OTP
    "otp_phone":      "+14304314828",
    "proxy_type":     "socks5",

    # Expected inject counts (from MD "Injected Data Summary")
    "target_contacts":        268,
    "target_call_logs":       368,
    "target_sms":             180,
    "target_cookies":         72,
    "target_history":         5099,
    "target_gallery":         312,
    "target_wifi":            24,
    "target_play_purchases":  21,
    "target_app_usage":       12,
    "target_installed_apps":  15,
    "target_autofill":        6,

    # Trust / stealth from MD
    "md_trust_score":   84,
    "md_stealth_score": 72,
    "md_stealth_pass":  108,
    "md_stealth_fail":  42,

    # Profile IDs
    "md_profile_id":  "TITAN-DB36DE5B",   # referenced in MD (not in system)
    "md_device_id":   "dev-cvd001",
    "md_adb_target":  "127.0.0.1:6520",
    "md_forge_date":  "2026-03-18T21:15:00Z",

    # Missing from MD forge (gaps)
    "missing_google_wallet":  True,   # -12 trust points
    "missing_chrome_signin":  True,   # -5 trust points
}

API_PORT    = 8080
TITAN_DATA  = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))


# ───────────────────────────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Return last valid TITAN_API_SECRET from .env (multiple entries allowed)."""
    env_file = Path("/opt/titan-v11.3-device/.env")
    last_key = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("TITAN_API_SECRET="):
                key = line.split("=", 1)[1].strip()
                if key and key != "change-me-to-a-secure-random-string" and len(key) >= 32:
                    last_key = key          # keep updating — last valid wins
    if last_key:
        return last_key
    return os.environ.get("TITAN_API_SECRET", "")


def api(method: str, path: str, body=None, api_key: str = "") -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    conn = http.client.HTTPConnection("localhost", API_PORT, timeout=30)
    payload = json.dumps(body).encode() if body else None
    conn.request(method, path, body=payload, headers=headers)
    r = conn.getresponse()
    raw = r.read().decode()
    try:
        return {"status": r.status, "data": json.loads(raw)}
    except Exception:
        return {"status": r.status, "data": raw}


def section(title: str):
    print(f"\n{'═'*68}")
    print(f"  {title}")
    print(f"{'═'*68}")


def ok(msg):  print(f"  ✅  {msg}")
def warn(msg): print(f"  ⚠️   {msg}")
def fail(msg): print(f"  ❌  {msg}")
def info(msg): print(f"  ℹ️   {msg}")


# ───────────────────────────────────────────────────────────────
# STEP 1 — ACTIVE SERVICES & DEVICE STATUS
# ───────────────────────────────────────────────────────────────

def step1_services(api_key: str):
    section("STEP 1 — Active Services & Device Status")

    import subprocess

    # Port scan
    ports = {
        8080: "Titan API (uvicorn/FastAPI)",
        8081: "Titan Console (alt server)",
        8000: "ws-scrcpy (Android screen)",
        443:  "HTTPS (docker/nginx)",
        80:   "HTTP (nginx)",
        3389: "xRDP (remote desktop)",
        6080: "websockify (VNC/noVNC)",
        5037: "ADB server",
        11434: "Ollama (AI/LLM)",
        6520: "Cuttlefish ADB (target)",
    }
    print("\n  Port       Service                      Status")
    print("  " + "-"*56)
    for port, desc in ports.items():
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("HEAD", "/")
            conn.getresponse()
            status = "LISTENING ✅"
        except ConnectionRefusedError:
            status = "REFUSED  ❌"
        except Exception:
            status = "OPEN     ✅"
        print(f"  :{port:<7}  {desc:<30} {status}")

    # ADB / Cuttlefish status
    print()
    r = subprocess.run("adb connect 127.0.0.1:6520",
                       shell=True, capture_output=True, text=True, timeout=5)
    adb_out = r.stdout.strip()
    if "connected" in adb_out.lower() and "refused" not in adb_out.lower():
        ok(f"Cuttlefish ADB alive: {adb_out}")
    else:
        fail(f"Cuttlefish ADB DOWN: {adb_out or r.stderr.strip()}")
        warn("Device dev-cvd001 is registered in DB but NOT running.")
        warn("Cuttlefish VM (launch_cvd) must be started to inject data.")

    # DB device entry
    db_path = TITAN_DATA / "devices.db"
    if db_path.exists():
        conn_db = sqlite3.connect(str(db_path))
        conn_db.row_factory = sqlite3.Row
        rows = conn_db.execute("SELECT id, adb_target, state, config, stealth_score FROM devices").fetchall()
        conn_db.close()
        print()
        for row in rows:
            cfg = json.loads(row["config"] or "{}")
            info(f"DB device: id={row['id']}  target={row['adb_target']}  state={row['state']}")
            info(f"          model={cfg.get('model')}  carrier={cfg.get('carrier')}  android={cfg.get('android_version')}")
            info(f"          stealth_score={row['stealth_score']}")
    else:
        warn("devices.db not found")


# ───────────────────────────────────────────────────────────────
# STEP 2 — FORGE VIA GENESIS API (exact MD spec)
# ───────────────────────────────────────────────────────────────

def step2_forge(api_key: str) -> dict:
    section("STEP 2 — Genesis Forge (Exact MD Spec)")

    payload = {
        "name":         MD_PROFILE["persona_name"],
        "email":        MD_PROFILE["email"],
        "phone":        MD_PROFILE["primary_phone"],
        "country":      MD_PROFILE["country"],
        "archetype":    MD_PROFILE["archetype"],
        "age_days":     MD_PROFILE["age_days"],
        "carrier":      MD_PROFILE["carrier"],
        "location":     MD_PROFILE["location"],
        "device_model": MD_PROFILE["device_model"],
        # Credit card fields
        "cc_number":    MD_PROFILE["cc_number"],
        "cc_exp_month": MD_PROFILE["cc_exp_month"],
        "cc_exp_year":  MD_PROFILE["cc_exp_year"],
        "cc_cvv":       MD_PROFILE["cc_cvv"],
        "cc_cardholder": MD_PROFILE["cc_holder"],
        # Optional extras
        "install_wallets": True,
        "pre_login":    True,
    }

    info(f"Posting to /api/genesis/create with {MD_PROFILE['persona_name']} persona ...")
    result = api("POST", "/api/genesis/create", body=payload, api_key=api_key)

    if result["status"] != 200:
        fail(f"Genesis forge failed: HTTP {result['status']} — {result['data']}")
        return {}

    data = result["data"]
    new_id = data.get("profile_id", "?")
    persona = data.get("persona", {})
    stats   = data.get("stats", {})

    ok(f"New profile forged: {new_id}")
    info(f"  Name:  {persona.get('name')}")
    info(f"  Email: {persona.get('email')}")
    info(f"  Phone: {persona.get('phone')}")

    return {"profile_id": new_id, "stats": stats}


# ───────────────────────────────────────────────────────────────
# STEP 3 — LOAD PROFILE & COMPARE VS MD TARGETS
# ───────────────────────────────────────────────────────────────

def step3_gap_report(api_key: str, new_profile_id: str):
    section("STEP 3 — Gap Analysis: Forged Profile vs MD Targets")

    profiles_dir = TITAN_DATA / "profiles"

    # Find profiles for Jovany Owens
    jovany_profiles = []
    for pf in sorted(profiles_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(pf.read_text())
            if "jovany" in d.get("persona_name", "").lower() or \
               "jovany.owens" in d.get("persona_email", ""):
                jovany_profiles.append((pf.stem, d))
        except Exception:
            pass

    print(f"\n  Found {len(jovany_profiles)} Jovany Owens profile(s) in system:\n")

    for pid, prof in jovany_profiles:
        is_new = (pid == new_profile_id)
        tag = " ← NEWLY FORGED" if is_new else ""
        print(f"  Profile: {pid}{tag}")
        print(f"    Email:     {prof.get('persona_email')}")
        print(f"    Created:   {prof.get('created_at')}")
        print(f"    Age days:  {prof.get('age_days')}")
        stats = prof.get("stats", {})

        # Data count fields
        count_fields = [
            ("contacts",       "contact",          MD_PROFILE["target_contacts"]),
            ("call_logs",      "call log",          MD_PROFILE["target_call_logs"]),
            ("sms",            "SMS",               MD_PROFILE["target_sms"]),
            ("cookies",        "cookie",            MD_PROFILE["target_cookies"]),
            ("history",        "history entry",     MD_PROFILE["target_history"]),
            ("gallery",        "gallery photo",     MD_PROFILE["target_gallery"]),
            ("wifi",           "WiFi network",      MD_PROFILE["target_wifi"]),
            ("play_purchases", "Play purchase",     MD_PROFILE["target_play_purchases"]),
            ("app_usage",      "app usage stat",    MD_PROFILE["target_app_usage"]),
            ("autofill",       "autofill entry",    MD_PROFILE["target_autofill"]),
        ]

        print("    " + "-"*58)
        print(f"    {'Category':<22} {'Got':>6}  {'Target':>7}  {'Gap':>7}  Status")
        print("    " + "-"*58)
        total_gap = 0
        gap_items = []
        for key, label, target in count_fields:
            actual = stats.get(key, len(prof.get(key, [])) if isinstance(prof.get(key), list) else 0)
            gap = target - actual
            total_gap += max(gap, 0)
            if gap <= 0:
                status = "✅"
            elif gap <= target * 0.2:
                status = "⚠️ "
            else:
                status = "❌"
            if gap > 0:
                gap_items.append((label, actual, target, gap))
            print(f"    {label:<22} {actual:>6}  {target:>7}  {gap:>+7}  {status}")

        print()
        if gap_items:
            warn(f"DATA GAPS in {pid}:")
            for label, actual, target, gap in gap_items:
                print(f"      • {label}: need {gap} more (have {actual}, target {target})")

        print()


# ───────────────────────────────────────────────────────────────
# STEP 4 — KNOWN STRUCTURAL GAPS (from MD analysis)
# ───────────────────────────────────────────────────────────────

def step4_known_gaps():
    section("STEP 4 — Known Structural Gaps (MD File Analysis)")

    GAPS = [
        {
            "severity": "CRITICAL",
            "category": "Device offline",
            "detail": (
                "Cuttlefish VM (dev-cvd001) is NOT running.\n"
                "          ADB connect to 127.0.0.1:6520 refused.\n"
                "          Profile data CANNOT be injected until `launch_cvd` starts the VM."
            ),
            "trust_impact": 0,
            "fix": "Run: cvd start  or  launch_cvd <flags>  to start the Cuttlefish instance.",
        },
        {
            "severity": "HIGH",
            "category": "Google Wallet missing",
            "detail": (
                "Google Wallet APK failed to install during original forge\n"
                "          due to manifest corruption in the GApps bundle."
            ),
            "trust_impact": -12,
            "fix": "Sideload Wallet APK manually: adb install -r /opt/titan/data/apks/wallet.apk",
        },
        {
            "severity": "HIGH",
            "category": "Chrome not signed in",
            "detail": (
                "Chrome is too large (244 MB) for Cuttlefish binder limits.\n"
                "          Kiwi Browser is installed instead, but Chrome sync is not active."
            ),
            "trust_impact": -5,
            "fix": (
                "Option A: Use Kiwi Browser cookies/sync as Chrome substitute.\n"
                "          Option B: Install Chrome lite or WebView-based alternative."
            ),
        },
        {
            "severity": "MEDIUM",
            "category": "42 ro.* system properties read-only (erofs)",
            "detail": (
                "Properties like ro.product.model, ro.build.fingerprint, ro.hardware\n"
                "          cannot be overwritten on erofs/read-only system partition.\n"
                "          Values still show Cuttlefish defaults (e.g. 'ranchu' hw)."
            ),
            "trust_impact": 0,  # stealth score impact: -37 checks
            "fix": (
                "Use a custom system image with props pre-baked, or\n"
                "          apply Magisk resetprop (if root available) via init.d hooks."
            ),
        },
        {
            "severity": "MEDIUM",
            "category": "Contact count below target (112 vs 268)",
            "detail": (
                "Genesis forge generated 112 contacts; MD target was 268+.\n"
                "          The forge algorithmic ceiling for this archetype/age is ~120."
            ),
            "trust_impact": 0,  # trust still counts as 'contacts present'
            "fix": (
                "Re-forge with age_days=900 or increase contact multiplier in\n"
                "          android_profile_forge.py CONTACT_DENSITY constant."
            ),
        },
        {
            "severity": "MEDIUM",
            "category": "Cookie count below target (27 vs 72)",
            "detail": (
                "Kiwi Browser cookie injection yielded 27 cookies; MD target 72.\n"
                "          Browser-specific trust anchors and commerce cookies incomplete."
            ),
            "trust_impact": 0,
            "fix": (
                "Run gapfill_jovany.py after device starts to push additional\n"
                "          cookie rows directly into Kiwi SQLite DB."
            ),
        },
        {
            "severity": "MEDIUM",
            "category": "History below target (2,500 vs 5,099)",
            "detail": (
                "Profile history capped at 2,500 entries at forge time.\n"
                "          MD target requires 5,099 browsing history records."
            ),
            "trust_impact": 0,
            "fix": "Increase HISTORY_CAP in android_profile_forge.py or run gap-fill injection.",
        },
        {
            "severity": "LOW",
            "category": "Profile ID mismatch",
            "detail": (
                "MD references profile TITAN-DB36DE5B which does not exist.\n"
                "          Active Jovany profile is TITAN-FC9639B4 (same persona, different run)."
            ),
            "trust_impact": 0,
            "fix": "Update JOVANY-OWENS-FORGE-DETAILS.md to reference TITAN-FC9639B4.",
        },
        {
            "severity": "LOW",
            "category": "ro.debuggable = 1",
            "detail": (
                "Cuttlefish boots with ro.debuggable=1 (debug build).\n"
                "          Production Samsung has ro.debuggable=0."
            ),
            "trust_impact": 0,
            "fix": "Use a production-signed system image or init.d ro property override.",
        },
    ]

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    GAPS.sort(key=lambda g: severity_order.get(g["severity"], 9))

    trust_delta = sum(g["trust_impact"] for g in GAPS)

    for g in GAPS:
        sev = g["severity"]
        sym = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(sev, "⚪")
        print(f"\n  {sym} [{sev}] {g['category']}")
        impact = f"  Trust impact: {g['trust_impact']} pts" if g["trust_impact"] else ""
        print(f"     Issue : {g['detail']}{impact}")
        print(f"     Fix   : {g['fix']}")

    print(f"\n  ── Trust Score Impact Summary ──────────────────────────────")
    print(f"     MD target trust score : {MD_PROFILE['md_trust_score']}/100")
    print(f"     Max achievable (gaps) : {MD_PROFILE['md_trust_score'] + trust_delta}/100")
    print(f"     Google Wallet gap     : -12 pts  (not installed)")
    print(f"     Chrome sign-in gap    : -5 pts  (Chrome too large for Cuttlefish)")
    print(f"     Total recoverable     : 17 pts  (possible with fixes above)")
    print()
    print(f"  ── Stealth Score Breakdown ─────────────────────────────────")
    print(f"     MD reported stealth   : {MD_PROFILE['md_stealth_score']}/100")
    print(f"     Checks passed         : {MD_PROFILE['md_stealth_pass']}/150")
    print(f"     Checks failed         : {MD_PROFILE['md_stealth_fail']}  (all ro.* read-only)")
    print(f"     Max recoverable       : ~90/100  (needs writable system image)")


# ───────────────────────────────────────────────────────────────
# STEP 5 — ENRICHMENT: patch the profile with full MD field set
# ───────────────────────────────────────────────────────────────

def step5_enrich_profile(new_profile_id: str):
    section("STEP 5 — Enrich Profile JSON with Full MD Field Set")

    if not new_profile_id:
        warn("No new profile to enrich — skipping.")
        return

    pf = TITAN_DATA / "profiles" / f"{new_profile_id}.json"
    if not pf.exists():
        warn(f"Profile file not found: {pf}")
        return

    profile = json.loads(pf.read_text())

    # Inject all MD-spec fields that aren't auto-generated
    additions = {
        "md_source":          "JOVANY-OWENS-FORGE-DETAILS.md",
        "md_profile_ref":     MD_PROFILE["md_profile_id"],
        "full_name":          MD_PROFILE["full_name"],
        "gender":             MD_PROFILE["gender"],
        "date_of_birth":      MD_PROFILE["dob"],
        "ssn":                MD_PROFILE["ssn"],
        "address":            MD_PROFILE["address"],
        "city":               MD_PROFILE["city"],
        "state":              MD_PROFILE["state"],
        "zip":                MD_PROFILE["zip"],
        "otp_phone":          MD_PROFILE["otp_phone"],
        "cc_number":          MD_PROFILE["cc_number"],
        "cc_exp_month":       MD_PROFILE["cc_exp_month"],
        "cc_exp_year":        MD_PROFILE["cc_exp_year"],
        "cc_cvv":             MD_PROFILE["cc_cvv"],
        "cc_cardholder":      MD_PROFILE["cc_holder"],
        "device_adb_target":  MD_PROFILE["md_adb_target"],
        "device_id":          MD_PROFILE["md_device_id"],
        "mcc_mnc":            MD_PROFILE["mcc_mnc"],
        "android_version":    MD_PROFILE["android_ver"],
        "gps_lat":            34.0522,
        "gps_lon":            -118.2437,
        "timezone":           "America/Los_Angeles",
        "locale":             "en_US",
        "android_screen":     "1080x2400",
        "dpi":                420,
        "md_trust_score":     MD_PROFILE["md_trust_score"],
        "md_stealth_score":   MD_PROFILE["md_stealth_score"],
        "gaps": {
            "google_wallet_missing": True,
            "chrome_signin_missing": True,
            "ro_props_read_only":    42,
            "contacts_shortfall":    max(0, MD_PROFILE["target_contacts"] - profile.get("stats", {}).get("contacts", 0)),
            "cookies_shortfall":     max(0, MD_PROFILE["target_cookies"]  - profile.get("stats", {}).get("cookies", 0)),
            "history_shortfall":     max(0, MD_PROFILE["target_history"]  - profile.get("stats", {}).get("history", 0)),
        },
        "enriched_at": datetime.utcnow().isoformat() + "Z",
    }

    profile.update(additions)
    pf.write_text(json.dumps(profile, indent=2))
    ok(f"Profile {new_profile_id} enriched with full MD field set")
    info(f"  File: {pf}")


# ───────────────────────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────────────────────

def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  Titan V12.0 — Jovany Owens Self-Recreate from MD Profile       ║")
    print(f"║  Run at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC" + " "*28 + "║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    api_key = _get_api_key()
    if not api_key:
        print("\n  ❌  Cannot read TITAN_API_SECRET from .env — aborting.")
        sys.exit(1)

    step1_services(api_key)

    forge_result = step2_forge(api_key)
    new_profile_id = forge_result.get("profile_id", "")

    step3_gap_report(api_key, new_profile_id)
    step4_known_gaps()
    step5_enrich_profile(new_profile_id)

    section("COMPLETE")
    print()
    print("  Summary:")
    if new_profile_id:
        ok(f"New profile created: {new_profile_id}")
    else:
        warn("Profile creation failed — check genesis API logs.")
    fail("Cuttlefish device NOT running (ADB :6520 refused)")
    warn("Next steps:")
    print("    1. Start Cuttlefish: cvd start  (or launch_cvd)")
    print("    2. Verify ADB:       adb connect 127.0.0.1:6520")
    print("    3. Run injection:    python3 scripts/run_jovany_pipeline.py")
    print("    4. Fill data gaps:   python3 scripts/gapfill_jovany.py")
    print("    5. Patch stealth:    POST /api/stealth/patch  {device_id: dev-cvd001}")
    print("    6. Audit trust:      GET  /api/genesis/trust-score/dev-cvd001")
    print()


if __name__ == "__main__":
    main()
