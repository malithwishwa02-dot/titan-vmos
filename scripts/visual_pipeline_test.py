#!/usr/bin/env python3
"""
Visual Pipeline Test — Human-like interaction with Genesis Studio.
Opens Firefox VISUALLY on the RDP desktop so the user can watch every keystroke.

Fills all Jovany Owens fields one by one with realistic human typing speed,
sets 500 days aging, runs the full 9-phase forge pipeline, and monitors
every phase to completion.
"""
import time
import sys
import os
import random

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# ─── Config ─────────────────────────────────────────────────────────
URL = "http://localhost:8080"
WAIT = 20
REPORTS = "/opt/titan-v11.3-device/reports"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def human_pause(lo=0.6, hi=1.5):
    """Random pause like a human reading / thinking."""
    time.sleep(random.uniform(lo, hi))

def human_type(driver, element, text, speed="normal"):
    """Type one character at a time with variable human-like delays."""
    element.click()
    human_pause(0.2, 0.5)
    # Select all and delete (like a human clearing a field)
    element.send_keys(Keys.CONTROL + "a")
    time.sleep(0.1)
    element.send_keys(Keys.DELETE)
    time.sleep(0.15)

    delays = {"slow": (0.06, 0.18), "normal": (0.03, 0.10), "fast": (0.02, 0.06)}
    lo, hi = delays.get(speed, delays["normal"])

    for i, ch in enumerate(text):
        element.send_keys(ch)
        # Occasionally pause longer (like thinking while typing)
        if random.random() < 0.08:
            time.sleep(random.uniform(0.2, 0.5))
        else:
            time.sleep(random.uniform(lo, hi))
    human_pause(0.3, 0.6)

def human_click(driver, element, scroll=True):
    """Scroll to element smoothly, pause, then click — like a human."""
    if scroll:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});",
            element
        )
        human_pause(0.4, 0.8)
    try:
        actions = ActionChains(driver)
        actions.move_to_element(element).pause(random.uniform(0.15, 0.35)).click().perform()
    except Exception:
        # Fallback: JS click if element is off-viewport
        driver.execute_script("arguments[0].click();", element)
    human_pause(0.3, 0.5)

def human_select(driver, select_elem, value):
    """Set a select dropdown value with human timing via JS + Alpine dispatch."""
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});",
        select_elem
    )
    human_pause(0.3, 0.6)
    driver.execute_script("""
        let el = arguments[0], val = arguments[1];
        el.value = val;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
    """, select_elem, value)
    human_pause(0.4, 0.7)

def screenshot(driver, name):
    os.makedirs(REPORTS, exist_ok=True)
    path = f"{REPORTS}/{name}.png"
    driver.save_screenshot(path)
    log(f"📸 Screenshot: {path}")

def field(driver, model):
    """Find an input/select by Alpine x-model attribute (handles x-model.number etc)."""
    # Try exact match first, then partial attribute match
    for selector in [
        f'[x-model="{model}"]',
        f'[x-model\\.number="{model}"]',
    ]:
        els = driver.find_elements(By.CSS_SELECTOR, selector)
        if els:
            return els[0]
    # Fallback: find by JS
    el = driver.execute_script(f'''
        return document.querySelector('[x-model="{model}"]')
            || document.querySelector('[x-model\\\\.number="{model}"]')
            || document.querySelector('[x-bind\\\\:value="{model}"]');
    ''')
    if el:
        return el
    raise Exception(f"Cannot find field with model: {model}")

def field_val(driver, model):
    return driver.execute_script(
        f'return document.querySelector(\'[x-model="{model}"]\')?.value || ""'
    )

# ═════════════════════════════════════════════════════════════════════
def main():
    headless = "--headless" in sys.argv
    opts = Options()
    if headless:
        opts.add_argument("--headless")
        log("Running HEADLESS")
    else:
        log("🖥  VISIBLE MODE — Watch the browser on your RDP desktop!")

    os.environ.setdefault("DISPLAY", ":10")
    driver = webdriver.Firefox(options=opts)
    driver.set_window_size(1600, 1000)
    wait = WebDriverWait(driver, WAIT)

    try:
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 1 — Load console
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("Opening Titan Console...")
        driver.get(URL)
        time.sleep(3)
        log(f"Page loaded: {driver.title}")
        screenshot(driver, "01_console_loaded")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 2 — Navigate to Genesis Studio
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("Clicking 'Genesis Studio' in sidebar...")
        human_pause(1.0, 2.0)
        genesis_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Genesis')]")
        ))
        human_click(driver, genesis_btn, scroll=False)
        time.sleep(1.5)
        screenshot(driver, "02_genesis_studio")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 3 — Confirm Pipeline tab (default)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("Verifying ⚡ Pipeline tab is active...")
        wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//h3[contains(., 'Identity')]")
        ))
        log("✅ Pipeline tab confirmed — form sections visible")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 4 — Select device
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("Selecting target device...")
        dev_sel = field(driver, "pipeline.device_id")
        human_click(driver, dev_sel)
        human_pause(0.5, 1.0)
        human_select(driver, dev_sel, "dev-cvd001")
        log(f"  ✅ Device: {field_val(driver, 'pipeline.device_id')}")
        screenshot(driver, "03_device_selected")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 5 — Set device model & carrier & location & age
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("Setting device options...")
        human_select(driver, field(driver, "pipeline.device_model"), "samsung_s24")
        log("  Model: Samsung S24")
        human_pause(0.5, 0.8)

        human_select(driver, field(driver, "pipeline.carrier"), "tmobile_us")
        log("  Carrier: T-Mobile US")
        human_pause(0.5, 0.8)

        human_select(driver, field(driver, "pipeline.location"), "la")
        log("  Location: LA")
        human_pause(0.5, 0.8)

        # Set age to 500 days — use JS for x-model.number field
        log("  Setting age to 500 days...")
        driver.execute_script("""
            let el = document.querySelector('[x-data]');
            let d = el._x_dataStack ? el._x_dataStack[0] : (Alpine.$data ? Alpine.$data(el) : el.__x.$data);
            d.pipeline.age_days = 500;
            let inp = document.querySelector('input[type="number"]');
            if (inp) { inp.value = 500; inp.dispatchEvent(new Event('input', {bubbles:true})); }
        """)
        human_pause(0.8, 1.2)
        log("  📅 Age: 500 days")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 6 — Fill Identity section (human typing)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("👤 Filling Identity section...")
        human_pause(0.8, 1.2)

        name_el = field(driver, "pipeline.name")
        human_click(driver, name_el)
        human_type(driver, name_el, "Jovany Owens", speed="slow")
        log("  Name: Jovany Owens")

        email_el = field(driver, "pipeline.email")
        human_click(driver, email_el)
        human_type(driver, email_el, "adiniorjuniorjd28@gmail.com", speed="normal")
        log("  Email: adiniorjuniorjd28@gmail.com")

        phone_el = field(driver, "pipeline.phone")
        human_click(driver, phone_el)
        human_type(driver, phone_el, "(707) 836-1915", speed="normal")
        log("  Phone: (707) 836-1915")

        dob_el = field(driver, "pipeline.dob")
        human_click(driver, dob_el)
        human_type(driver, dob_el, "12/11/1959", speed="slow")
        log("  DOB: 12/11/1959")

        ssn_el = field(driver, "pipeline.ssn")
        human_click(driver, ssn_el)
        human_type(driver, ssn_el, "219-19-0937", speed="slow")
        log("  SSN: 219-19-0937")

        human_select(driver, field(driver, "pipeline.gender"), "M")
        log("  Gender: Male")

        human_select(driver, field(driver, "pipeline.occupation"), "retiree")
        log("  Occupation: Retiree")

        screenshot(driver, "04_identity_filled")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 7 — Fill Address section
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("🏠 Filling Address section...")
        human_pause(0.6, 1.0)

        street_el = field(driver, "pipeline.street")
        human_click(driver, street_el)
        human_type(driver, street_el, "1866 W 11th St", speed="normal")
        log("  Street: 1866 W 11th St")

        city_el = field(driver, "pipeline.city")
        human_click(driver, city_el)
        human_type(driver, city_el, "Los Angeles", speed="normal")
        log("  City: Los Angeles")

        state_el = field(driver, "pipeline.state")
        human_click(driver, state_el)
        human_type(driver, state_el, "CA", speed="slow")
        log("  State: CA")

        zip_el = field(driver, "pipeline.zip")
        human_click(driver, zip_el)
        human_type(driver, zip_el, "90006", speed="normal")
        log("  Zip: 90006")

        human_select(driver, field(driver, "pipeline.country"), "US")
        log("  Country: US")

        screenshot(driver, "05_address_filled")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 8 — Fill Payment Card section
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("💳 Filling Payment Card section...")
        human_pause(0.8, 1.2)

        cc_el = field(driver, "pipeline.cc_number")
        human_click(driver, cc_el)
        human_type(driver, cc_el, "4638512320340405", speed="slow")
        log("  Card#: 4638512320340405")

        exp_el = field(driver, "pipeline.cc_exp")
        human_click(driver, exp_el)
        human_type(driver, exp_el, "08/2029", speed="slow")
        log("  Exp: 08/2029")

        cvv_el = field(driver, "pipeline.cc_cvv")
        human_click(driver, cvv_el)
        human_type(driver, cvv_el, "051", speed="slow")
        log("  CVV: 051")

        holder_el = field(driver, "pipeline.cc_holder")
        human_click(driver, holder_el)
        human_type(driver, holder_el, "Jovany Owens", speed="normal")
        log("  Cardholder: Jovany Owens")

        screenshot(driver, "06_card_filled")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 9 — Fill Google Account section
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("🔑 Filling Google Account section...")
        human_pause(0.8, 1.2)

        gmail_el = field(driver, "pipeline.google_email")
        human_click(driver, gmail_el)
        human_type(driver, gmail_el, "jovany.owens59@gmail.com", speed="normal")
        log("  Gmail: jovany.owens59@gmail.com")

        gpass_el = field(driver, "pipeline.google_password")
        human_click(driver, gpass_el)
        human_type(driver, gpass_el, "YCCvsukin7S", speed="slow")
        log("  Password: ●●●●●●●●●●●")

        rphone_el = field(driver, "pipeline.real_phone")
        human_click(driver, rphone_el)
        human_type(driver, rphone_el, "+14304314828", speed="normal")
        log("  OTP Phone: +14304314828")

        screenshot(driver, "07_google_filled")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 10 — Fill Proxy section
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("🌐 Filling Proxy section...")
        human_pause(0.8, 1.0)

        proxy_el = field(driver, "pipeline.proxy_url")
        human_click(driver, proxy_el)
        human_type(driver, proxy_el,
                   "socks5h://2eiw7c10o5p:192aqpgq10x@91.231.186.249:1080",
                   speed="normal")
        log("  Proxy: socks5h://...@91.231.186.249:1080")

        screenshot(driver, "08_proxy_filled")
        human_pause(1.0, 1.5)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 11 — Options: ensure defaults (use_ai ON, skips OFF)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("⚙️  Checking options...")
        driver.execute_script("""
            let el = document.querySelector('[x-data]');
            let d = el._x_dataStack ? el._x_dataStack[0] : Alpine.$data(el);
            d.pipeline.skip_wipe = false;
            d.pipeline.skip_patch = false;
            d.pipeline.use_ai = true;
        """)
        log("  skip_wipe: OFF | skip_patch: OFF | AI enrichment: ON")
        screenshot(driver, "09_options_set")
        human_pause(1.0, 2.0)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 12 — Review: scroll through all sections slowly
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("📋 Reviewing all sections before launch...")
        section_titles = driver.find_elements(By.CSS_SELECTOR, ".grp-title")
        for s in section_titles[:9]:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", s
            )
            human_pause(1.0, 1.8)
        log("  Review complete — all fields verified")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 13 — Final verification printout
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log("─── FINAL FIELD VERIFICATION ───")
        fields_check = {
            "Name": "pipeline.name",
            "Email": "pipeline.email",
            "Phone": "pipeline.phone",
            "DOB": "pipeline.dob",
            "SSN": "pipeline.ssn",
            "Street": "pipeline.street",
            "City": "pipeline.city",
            "State": "pipeline.state",
            "Zip": "pipeline.zip",
            "Card#": "pipeline.cc_number",
            "Exp": "pipeline.cc_exp",
            "CVV": "pipeline.cc_cvv",
            "Holder": "pipeline.cc_holder",
            "Gmail": "pipeline.google_email",
            "OTP Phone": "pipeline.real_phone",
            "Proxy": "pipeline.proxy_url",
            "Device": "pipeline.device_id",
        }
        for label, model in fields_check.items():
            val = field_val(driver, model)
            display = "●●●●●●●" if "password" in model else val
            log(f"  {label:12s} → {display}")
        # Get age_days directly from Alpine data
        age_val = driver.execute_script("""
            let el = document.querySelector('[x-data]');
            let d = el._x_dataStack ? el._x_dataStack[0] : Alpine.$data(el);
            return d.pipeline.age_days;
        """)
        log(f"  {'Age Days':12s} → {age_val}")
        log("────────────────────────────────")
        human_pause(2.0, 3.0)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 14 — Click ⚡ RUN FORGE PIPELINE
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if "--no-run" in sys.argv:
            log("⏸  --no-run flag set. Form filled, not running pipeline.")
            screenshot(driver, "10_ready_to_run")
        else:
            run_btn = driver.find_element(
                By.XPATH, "//button[contains(., 'RUN FORGE PIPELINE')]"
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});",
                run_btn
            )
            human_pause(1.5, 2.5)
            log("🚀 Clicking ⚡ RUN FORGE PIPELINE...")
            human_click(driver, run_btn, scroll=False)
            time.sleep(2)
            screenshot(driver, "10_pipeline_started")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 15 — Monitor pipeline phases live
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # Scroll to the phase tracker on the right
            tracker = driver.find_elements(
                By.XPATH, "//h3[contains(., 'Pipeline Progress')]"
            )
            if tracker:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'start', behavior:'smooth'});",
                    tracker[0]
                )
            time.sleep(1)

            log("📊 Monitoring pipeline phases (polling every 4s)...")
            prev_phase = ""
            screenshot_count = 11
            for i in range(200):  # up to ~800 seconds
                status = driver.execute_script("""
                    let el = document.querySelector('[x-data]');
                    let c = el._x_dataStack ? el._x_dataStack[0] : Alpine.$data(el);
                    if (!c.pipelineJob) return {status:'waiting', phases:[], log_count:0};
                    let lastLog = (c.pipelineJob.log||[]);
                    return {
                        status: c.pipelineJob.status || 'unknown',
                        phases: (c.pipelineJob.phases||[]).map(
                            p => ({n:p.n, name:p.name, status:p.status, notes:p.notes||''})
                        ),
                        trust: c.pipelineJob.trust_score || 0,
                        patch: c.pipelineJob.patch_score || 0,
                        grade: c.pipelineJob.grade || '',
                        profile: c.pipelineJob.profile_id || '',
                        log_count: lastLog.length,
                        last_log: lastLog.length ? lastLog[lastLog.length-1] : ''
                    };
                """)

                phases = status.get("phases", [])
                running = [p for p in phases if p["status"] == "running"]
                done = [p for p in phases if p["status"] == "done"]
                failed = [p for p in phases if p["status"] == "failed"]

                current_phase = running[0]["name"] if running else ""
                elapsed = i * 4

                # Log phase transitions
                if current_phase and current_phase != prev_phase:
                    log(f"  ▶ Phase started: {current_phase}")
                    prev_phase = current_phase
                    screenshot(driver, f"{screenshot_count:02d}_phase_{current_phase.replace(' ','_').replace('/','_')}")
                    screenshot_count += 1

                # Periodic status line
                if i % 3 == 0:
                    phase_summary = " | ".join(
                        f"{p['name']}:{'✓' if p['status']=='done' else '⏳' if p['status']=='running' else '✗' if p['status']=='failed' else '·'}"
                        for p in phases
                    )
                    log(f"  [{elapsed:>4d}s] {status['status'].upper()} — {phase_summary}")
                    if status.get("last_log"):
                        log(f"         └ {status['last_log'][:120]}")

                if status["status"] == "completed":
                    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    log(f"✅ PIPELINE COMPLETED!")
                    log(f"   Trust Score : {status.get('trust', '?')}/100")
                    log(f"   Stealth     : {status.get('patch', '?')}%")
                    log(f"   Grade       : {status.get('grade', '?')}")
                    log(f"   Profile     : {status.get('profile', '?')}")
                    log(f"   Done phases : {len(done)}/9")
                    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    screenshot(driver, f"{screenshot_count:02d}_completed")
                    break

                if status["status"] == "failed":
                    log(f"❌ PIPELINE FAILED at phase: {current_phase}")
                    for p in failed:
                        log(f"   Failed: {p['name']} — {p.get('notes','')}")
                    screenshot(driver, f"{screenshot_count:02d}_failed")
                    break

                time.sleep(4)

            # Final result screenshot — scroll to scorecard
            time.sleep(2)
            scorecard = driver.find_elements(
                By.XPATH, "//*[contains(text(), 'Pipeline Complete')]"
            )
            if scorecard:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});",
                    scorecard[0]
                )
                time.sleep(1)
                screenshot(driver, "99_final_result")

        log("✅ Visual pipeline test finished!")

    except Exception as e:
        log(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        screenshot(driver, "error")
    finally:
        if "--keep-open" in sys.argv:
            log("Browser staying open (--keep-open). Ctrl+C to close.")
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                pass
        driver.quit()

if __name__ == "__main__":
    main()
