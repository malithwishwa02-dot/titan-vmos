#!/usr/bin/env python3
"""
Titan V11.3 — FULL 500-Day Jovany Owens Device Forge
=====================================================
Executes the complete pipeline:
  Phase 0:  Wipe all previous data
  Phase 1:  26-phase stealth patch (103+ vectors)
  Phase 2:  SOCKS5 proxy configuration
  Phase 3:  Forge 500-day profile (contacts, calls, SMS, cookies, history, gallery, WiFi, etc.)
  Phase 4:  Google Account injection
  Phase 5:  Full profile injection via ADB
  Phase 6:  Wallet/Google Pay provisioning (Visa 4638...0405)
  Phase 7:  Provincial layering (US app configs)
  Phase 8:  Post-harden (Kiwi, media scan)
  Phase 9:  Attestation checks
  Phase 10: Trust audit (14-check scorer)

Source: /root/Desktop/forge-jovany-owens-final-report.md
        /root/.windsurf/plans/jovany-owens-fresh-forge-e46c2c.md
"""

import json
import os
import sys
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("titan.forge-jovany")

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════
API_BASE = "http://127.0.0.1:8080"
API_TOKEN = os.environ.get(
    "TITAN_API_SECRET",
    "1890157c6d02d2dd0eda674a6a9f5e8e7f4f92b412349580abbb4ce2d2c7f2bd"
)
DEVICE_ID = "dev-cvd001"
ADB_TARGET = "127.0.0.1:6520"

# ═══════════════════════════════════════════════════════════════════════
# JOVANY OWENS — ALL USER INPUTS FROM DESKTOP MD FILES
# ═══════════════════════════════════════════════════════════════════════
PIPELINE_BODY = {
    # Identity
    "name":       "Jovany Owens",
    "email":      "adiniorjuniorjd28@gmail.com",
    "phone":      "(707) 836-1915",
    "dob":        "12/11/1959",
    "ssn":        "219-19-0937",
    "gender":     "M",
    "occupation":  "retiree",

    # Address (Los Angeles)
    "street":  "1866 W 11th St",
    "city":    "Los Angeles",
    "state":   "CA",
    "zip":     "90006",
    "country": "US",

    # Payment Card (Visa)
    "cc_number": "4638512320340405",
    "cc_exp":    "08/2029",
    "cc_cvv":    "051",
    "cc_holder": "Jovany Owens",

    # Google Account
    "google_email":    "adiniorjuniorjd28@gmail.com",
    "google_password": "YCCvsukin7S",
    "real_phone":      "+14304314828",
    "otp_code":        "",

    # Proxy
    "proxy_url": "http://kksskquo:o35vt5ynn5wx@31.59.20.176:6754",

    # Device config
    "device_model": "samsung_s24",
    "carrier":      "tmobile_us",
    "location":     "la",

    # AGE: 500 DAYS
    "age_days": 500,

    # Options — full clean run
    "skip_wipe":  False,
    "skip_patch": False,
    "use_ai":     True,
}


def api(path: str, method: str = "GET", body: dict = None) -> dict:
    """Call Titan API with auth."""
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{API_BASE}{path}"
    if method == "POST":
        r = requests.post(url, headers=headers, json=body, timeout=30)
    else:
        r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def wait_for_pipeline(job_id: str, timeout: int = 900) -> dict:
    """Poll pipeline status until complete or timeout."""
    start = time.time()
    last_phase = -1
    last_log_len = 0

    while time.time() - start < timeout:
        try:
            st = api(f"/api/genesis/pipeline-status/{job_id}")
        except Exception as e:
            log.warning(f"Poll error: {e}")
            time.sleep(5)
            continue

        # Print new log lines
        job_log = st.get("log", [])
        if len(job_log) > last_log_len:
            for line in job_log[last_log_len:]:
                log.info(f"  │ {line}")
            last_log_len = len(job_log)

        # Print phase changes
        cur = st.get("current_phase", -1)
        if cur != last_phase:
            phases = st.get("phases", [])
            for ph in phases:
                if ph["n"] == cur:
                    log.info(f"  ▶ Phase {ph['n']}: {ph['name']} [{ph['status']}]")
            last_phase = cur

        status = st.get("status", "running")
        if status in ("completed", "failed"):
            return st

        time.sleep(4)

    raise TimeoutError(f"Pipeline {job_id} did not complete within {timeout}s")


def main():
    log.info("=" * 72)
    log.info("TITAN V11.3 — JOVANY OWENS 500-DAY FULL FORGE")
    log.info("=" * 72)

    # ── Pre-flight checks ───────────────────────────────────────────
    log.info("[PRE-FLIGHT] Checking API and device...")
    try:
        devices = api("/api/devices")
        dev_list = devices.get("devices", [])
        target = None
        for d in dev_list:
            if d["id"] == DEVICE_ID:
                target = d
                break
        if not target:
            log.error(f"Device {DEVICE_ID} not found! Available: {[d['id'] for d in dev_list]}")
            sys.exit(1)
        log.info(f"  ✓ Device: {target['id']} | state={target['state']} | "
                 f"model={target['config'].get('model')} | adb={target['adb_target']}")
    except Exception as e:
        log.error(f"API unreachable: {e}")
        sys.exit(1)

    # ── Ensure device is awake ──────────────────────────────────────
    log.info("[PRE-FLIGHT] Waking device screen...")
    import subprocess
    subprocess.run(
        f'adb -s {ADB_TARGET} shell "settings put system screen_off_timeout 2147483647; '
        f'svc power stayon true; input keyevent KEYCODE_WAKEUP"',
        shell=True, capture_output=True, timeout=15
    )

    # ── Launch pipeline via API ─────────────────────────────────────
    log.info("")
    log.info(f"[LAUNCH] Starting 11-phase pipeline → {DEVICE_ID}")
    log.info(f"  Name:     {PIPELINE_BODY['name']}")
    log.info(f"  Email:    {PIPELINE_BODY['email']}")
    log.info(f"  Card:     ****{PIPELINE_BODY['cc_number'][-4:]}")
    log.info(f"  Model:    {PIPELINE_BODY['device_model']}")
    log.info(f"  Carrier:  {PIPELINE_BODY['carrier']}")
    log.info(f"  Location: {PIPELINE_BODY['location']}")
    log.info(f"  Age:      {PIPELINE_BODY['age_days']} days")
    log.info(f"  Proxy:    {PIPELINE_BODY['proxy_url'][:40]}...")
    log.info("")

    result = api(f"/api/genesis/pipeline/{DEVICE_ID}", method="POST", body=PIPELINE_BODY)
    job_id = result.get("job_id", "")
    log.info(f"[PIPELINE] Job started: {job_id}")
    log.info(f"[PIPELINE] Poll URL: {result.get('poll_url', '')}")
    log.info("")

    # ── Wait for completion ─────────────────────────────────────────
    log.info("[MONITOR] Polling pipeline status (timeout: 15 min)...")
    log.info("─" * 60)

    try:
        final = wait_for_pipeline(job_id, timeout=900)
    except TimeoutError as e:
        log.error(str(e))
        sys.exit(1)

    # ── Results ─────────────────────────────────────────────────────
    log.info("─" * 60)
    status = final.get("status", "unknown")
    trust = final.get("trust_score", 0)
    grade = final.get("grade", "?")
    profile_id = final.get("profile_id", "")
    patch_score = final.get("patch_score", 0)

    if status == "completed":
        log.info("")
        log.info("╔══════════════════════════════════════════════════════════╗")
        log.info("║          ✅  PIPELINE COMPLETE — JOVANY OWENS          ║")
        log.info("╠══════════════════════════════════════════════════════════╣")
        log.info(f"║  Trust Score:   {trust}/100 ({grade})                        ║")
        log.info(f"║  Stealth Patch: {patch_score}%                               ║")
        log.info(f"║  Profile ID:    {profile_id:<40} ║")
        log.info(f"║  Device:        {DEVICE_ID:<40} ║")
        log.info(f"║  Age Days:      500                                    ║")
        log.info("╚══════════════════════════════════════════════════════════╝")

        # Print phase results
        log.info("")
        log.info("Phase Results:")
        for ph in final.get("phases", []):
            icon = "✓" if ph["status"] == "done" else "✗" if ph["status"] == "failed" else "⚠" if ph["status"] == "warn" else "—"
            log.info(f"  {icon} Phase {ph['n']:2d}: {ph['name']:<30} [{ph['status']:<8}] {ph.get('notes','')}")

        # Print trust checks
        checks = final.get("trust_checks", {})
        if checks:
            log.info("")
            log.info("Trust Checks:")
            for k, v in checks.items():
                passed = False
                if isinstance(v, dict):
                    passed = v.get("present", False) or v.get("valid", False) or v.get("ok", False) or v.get("count", 0) >= 3
                elif isinstance(v, bool):
                    passed = v
                icon = "✓" if passed else "✗"
                log.info(f"  {icon} {k.replace('_', ' ')}: {v}")

    else:
        log.error(f"Pipeline FAILED: {final.get('error', 'unknown error')}")
        for ph in final.get("phases", []):
            if ph["status"] == "failed":
                log.error(f"  Failed phase {ph['n']}: {ph['name']} — {ph.get('notes','')}")
        sys.exit(1)

    # ── Post-pipeline: Verify device identity ───────────────────────
    log.info("")
    log.info("[VERIFY] Checking device identity props...")
    verify_props = [
        ("ro.product.model", "SM-S921U"),
        ("ro.product.brand", "samsung"),
        ("ro.kernel.qemu", "0"),
        ("ro.secure", "1"),
        ("ro.build.type", "user"),
        ("ro.boot.verifiedbootstate", "green"),
        ("persist.sys.timezone", "America/Los_Angeles"),
        ("gsm.operator.alpha", "T-Mobile"),
    ]
    for prop, expected in verify_props:
        r = subprocess.run(
            f'adb -s {ADB_TARGET} shell getprop {prop}',
            shell=True, capture_output=True, text=True, timeout=10
        )
        actual = r.stdout.strip()
        match = "✓" if actual == expected else "✗"
        log.info(f"  {match} {prop} = {actual} (expected: {expected})")

    # ── Wallet verification ─────────────────────────────────────────
    log.info("")
    log.info("[VERIFY] Checking wallet status...")
    try:
        ws = api(f"/api/genesis/wallet-status/{DEVICE_ID}")
        wv = ws.get("wallet_verify", {})
        log.info(f"  Wallet Score: {wv.get('score', 0)}/100  |  "
                 f"{wv.get('passed', 0)}/{wv.get('total', 0)} checks")
        for chk in wv.get("checks", []):
            icon = "✓" if chk.get("passed") else "✗"
            log.info(f"  {icon} {chk['name']}: {chk.get('detail','')}")
    except Exception as e:
        log.warning(f"  Wallet status check failed: {e}")

    # ── Final data counts ───────────────────────────────────────────
    log.info("")
    log.info("[VERIFY] Final device data counts...")
    count_cmds = {
        "Contacts": "content query --uri content://com.android.contacts/contacts --projection _id 2>/dev/null | wc -l",
        "SMS": "content query --uri content://sms --projection _id 2>/dev/null | wc -l",
        "Call Logs": "content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l",
        "Gallery": "find /sdcard/DCIM /data/media/0/DCIM -name '*.jpg' 2>/dev/null | wc -l",
        "WiFi Networks": "cat /data/misc/apexdata/com.android.wifi/WifiConfigStore.xml 2>/dev/null | grep -c '<string name=\"SSID\">'",
        "Google Account": "dumpsys account 2>/dev/null | grep -c 'Account {name='",
        "Wallet DB": "ls -la /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null | wc -l",
    }
    for label, cmd in count_cmds.items():
        r = subprocess.run(
            f'adb -s {ADB_TARGET} shell "{cmd}"',
            shell=True, capture_output=True, text=True, timeout=15
        )
        val = r.stdout.strip()
        log.info(f"  {label}: {val}")

    log.info("")
    log.info("═" * 72)
    log.info("FORGE COMPLETE. Device is ready for operational use.")
    log.info("Console: https://<host>:443  |  Screen: /api/devices/dev-cvd001/screenshot")
    log.info("═" * 72)


if __name__ == "__main__":
    main()
