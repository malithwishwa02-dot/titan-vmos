"""
Titan V11.3 — AI Device Agent
Autonomous Android device control powered by GPU LLM models.
See→Think→Act loop: screenshot device → LLM decides action → execute via ADB.

Supports:
  - Free-form user prompts ("create an Amazon account")
  - Pre-built task templates (browse, login, install app)
  - Multi-step workflows with memory
  - Human-like touch/type via TouchSimulator

AI Models (via Vast.ai GPU Ollama tunnel):
  - titan-agent:7b   — trained action planning model (primary)
  - titan-specialist:7b — anomaly patching + wallet specialist
  - minicpm-v:8b     — vision model for screenshot analysis

Usage:
    agent = DeviceAgent(adb_target="127.0.0.1:5555")
    task = agent.start_task("Open Chrome and go to amazon.com")
    # Returns task_id, runs async in background
    status = agent.get_task_status(task_id)
"""

import glob
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from screen_analyzer import ScreenAnalyzer, ScreenState
from touch_simulator import TouchSimulator
from trajectory_logger import TrajectoryLogger

logger = logging.getLogger("titan.device-agent")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

GPU_OLLAMA_URL = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
CPU_OLLAMA_URL = os.environ.get("TITAN_CPU_OLLAMA", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("TITAN_AGENT_MODEL", "titan-agent:7b")
MAX_STEPS = int(os.environ.get("TITAN_AGENT_MAX_STEPS", "50"))
STEP_TIMEOUT = int(os.environ.get("TITAN_AGENT_STEP_TIMEOUT", "30"))

# ── Failure analysis & retry configuration ─────────────────────────
MAX_RETRIES_PER_STEP = 3           # Retry a failing action N times before entering analysis
MAX_ANALYSIS_ROUNDS = 3            # Max LLM analysis rounds per stuck point
ANALYSIS_COOLDOWN = 2.0            # Seconds between analysis rounds
DISPLAY_MODE = "rdp"               # Developer on RDP — screen is always visible, never headless

# Trained model preferences — auto-detected at startup
TRAINED_ACTION_MODEL = os.environ.get("TITAN_TRAINED_ACTION", "titan-agent:7b")
TRAINED_SPECIALIST_MODEL = os.environ.get("TITAN_SPECIALIST_MODEL", "titan-specialist:7b-v2")
TRAINED_VISION_MODEL = os.environ.get("TITAN_TRAINED_VISION", "minicpm-v:8b")
UNCENSORED_MODEL = os.environ.get("TITAN_UNCENSORED_MODEL", "fast-uncensored:latest")
ROLEPLAY_MODEL = os.environ.get("TITAN_ROLEPLAY_MODEL", "lightning-roleplay:latest")
GENERAL_MODEL = os.environ.get("TITAN_GENERAL_MODEL", "llama3.1:8b")
FALLBACK_ACTION_MODELS = ["titan-specialist:7b-v2", "fast-uncensored:latest", "llama3.1:8b"]
FALLBACK_VISION_MODELS = ["minicpm-v:8b"]

# ── Task category → model routing ──────────────────────────────────
# Maps TASK_TEMPLATES categories to the optimal Titan-trained model
TASK_MODEL_ROUTING: Dict[str, str] = {
    # Device automation: titan-agent (fine-tuned on Android UI trajectories)
    "install": TRAINED_ACTION_MODEL,         # Play Store navigation
    "browse": TRAINED_ACTION_MODEL,           # Chrome/browser navigation
    "aging": TRAINED_ACTION_MODEL,            # Warmup tasks, settings, photos
    # Sign-in flows: uncensored model (handles credential entry without refusal)
    "sign_in": UNCENSORED_MODEL,              # Login flows, credential filling
    # Wallet/payment: specialist (fine-tuned on wallet/payment flows)
    "wallet": TRAINED_SPECIALIST_MODEL,        # Google Pay, card verification
    # Persona generation: roleplay model (natural persona behavior)
    "persona": ROLEPLAY_MODEL,                # Persona-driven browsing
    # KYC flows: uncensored + vision (document/face interaction)
    "kyc": UNCENSORED_MODEL,                  # KYC form filling, doc upload
}

_available_models_cache: Optional[List[str]] = None
_models_cache_time: float = 0.0


def _detect_best_model(ollama_url: str = GPU_OLLAMA_URL,
                       model_type: str = "action") -> str:
    """Auto-detect the best available model, preferring trained LoRA models."""
    global _available_models_cache, _models_cache_time
    import urllib.request

    # Cache model list for 60 seconds
    if _available_models_cache is not None and time.time() - _models_cache_time < 60:
        available = _available_models_cache
    else:
        available = []
        for url in [ollama_url, CPU_OLLAMA_URL]:
            try:
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    available = [m["name"] for m in data.get("models", [])]
                    if available:
                        break
            except Exception:
                continue
        _available_models_cache = available
        _models_cache_time = time.time()

    if model_type == "vision":
        preferred = [TRAINED_VISION_MODEL] + FALLBACK_VISION_MODELS
    else:
        preferred = [TRAINED_ACTION_MODEL] + FALLBACK_ACTION_MODELS

    for model in preferred:
        if model in available:
            return model
        # Check without tag (e.g. "titan-agent" matches "titan-agent:7b")
        base = model.split(":")[0]
        for avail in available:
            if avail.startswith(base):
                return avail

    return DEFAULT_MODEL


def load_agent_capabilities_from_docs(docs_path: str = "docs") -> Dict[str, Any]:
    """Read markdown docs and build an agent skills/capabilities listing."""
    caps: Dict[str, Any] = {
        "source_files": [],
        "templates": {},
        "features": [],
    }

    if not os.path.isdir(docs_path):
        logger.warning("agent docs path not found: %s", docs_path)
        return caps

    for path in sorted(glob.glob(os.path.join(docs_path, "*.md"))):
        caps["source_files"].append(os.path.basename(path))
        try:
            text = open(path, "r", encoding="utf-8").read()
        except Exception as exc:
            logger.warning("unable to read doc %s: %s", path, exc)
            continue

        # Capture Task Templates block from 06-ai-agent.md
        if "## 7. Task Templates" in text:
            in_table = False
            for line in text.splitlines():
                if line.strip().startswith("| Template"):
                    in_table = True
                    continue
                if in_table:
                    if not line.strip() or line.strip().startswith("---"):
                        continue
                    if line.strip().startswith("## "):
                        break
                    cols = [c.strip().strip("` ") for c in line.split("|")]
                    if len(cols) >= 3:
                        template_name = cols[1]
                        desc = cols[3] if len(cols) > 3 else ""
                        caps["templates"][template_name] = {
                            "description": desc,
                            "source": os.path.basename(path),
                        }

        # Extract heading-based features for summary
        for heading in re.findall(r"^##+\s+(.*)$", text, flags=re.MULTILINE):
            caps["features"].append(f"{os.path.basename(path)}: {heading.strip()}")

    # Normalize unique feature set
    caps["features"] = sorted(set(caps["features"]))
    return caps


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentAction:
    """Single action taken by the agent."""
    step: int = 0
    action_type: str = ""    # tap, type, swipe, scroll_down, scroll_up, back, home, enter, open_app, open_url, wait, done, error
    params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    screen_summary: str = ""
    timestamp: float = 0.0
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "step": self.step, "action": self.action_type,
            "params": self.params, "reasoning": self.reasoning[:200],
            "screen": self.screen_summary[:200],
            "success": self.success,
            "time": self.timestamp,
        }


@dataclass
class FailureVector:
    """Records a single failure event for session memory.
    The agent NEVER skips failures — it records, analyzes, and learns from each one."""
    step: int = 0
    action_type: str = ""
    action_params: Dict[str, Any] = field(default_factory=dict)
    screen_summary: str = ""
    error_reason: str = ""
    analysis: str = ""
    recovery_action: str = ""
    resolved: bool = False
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "step": self.step, "action": self.action_type,
            "params": self.action_params, "screen": self.screen_summary[:150],
            "error": self.error_reason[:200], "analysis": self.analysis[:200],
            "recovery": self.recovery_action[:100], "resolved": self.resolved,
        }


@dataclass
class AgentTask:
    """A running or completed agent task."""
    id: str = ""
    device_id: str = ""
    prompt: str = ""
    status: str = "queued"     # queued, running, completed, failed, stopped
    model: str = ""
    steps_taken: int = 0
    max_steps: int = MAX_STEPS
    actions: List[AgentAction] = field(default_factory=list)
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    persona: Dict[str, str] = field(default_factory=dict)  # name, email, phone for form filling
    failure_vectors: List["FailureVector"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "device_id": self.device_id,
            "prompt": self.prompt, "status": self.status,
            "model": self.model,
            "steps_taken": self.steps_taken, "max_steps": self.max_steps,
            "actions": [a.to_dict() for a in self.actions[-20:]],
            "result": self.result, "error": self.error,
            "failure_vectors": [fv.to_dict() for fv in self.failure_vectors[-10:]],
            "started_at": self.started_at, "completed_at": self.completed_at,
            "duration": round(self.completed_at - self.started_at, 1) if self.completed_at else 0,
        }


# ═══════════════════════════════════════════════════════════════════════
# LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════

def _query_ollama(prompt: str, model: str = DEFAULT_MODEL,
                  ollama_url: str = GPU_OLLAMA_URL,
                  temperature: float = 0.3,
                  max_tokens: int = 256) -> str:
    """Query Ollama API and return raw text response."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }).encode()

    urls_to_try = [ollama_url, CPU_OLLAMA_URL] if ollama_url != CPU_OLLAMA_URL else [ollama_url]

    for url in urls_to_try:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"{url}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=STEP_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
                    return data.get("response", "")
            except Exception as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Ollama ({url}) attempt {attempt+1}/3 failed: {e}, retry in {wait}s")
                if attempt < 2:
                    time.sleep(wait)
                continue
        logger.warning(f"Ollama ({url}) exhausted all retries, trying next endpoint")

    return ""


def _parse_action_json(text: str) -> Optional[Dict]:
    """Extract JSON action from LLM response."""
    # Try full response as JSON first (most common with format=json)
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict) and "action" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to find JSON block with "action" key
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try fixing unquoted keys: {action: "tap"} -> {"action": "tap"}
    fixed = re.sub(r'([{,])\s*(\w+)\s*:', r'\1 "\2":', text)
    fix_match = re.search(r'\{[^{}]*"action"[^{}]*\}', fixed, re.DOTALL)
    if fix_match:
        try:
            return json.loads(fix_match.group())
        except json.JSONDecodeError:
            pass

    # Try to extract from markdown code block
    code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════════
# ACTION PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════

_AGENT_SYSTEM_PROMPT = """You are an AI agent controlling a REAL Android phone with a VISIBLE DISPLAY (developer monitors via RDP — this is NOT headless).
The screen is always live and visible. Output ONE JSON action per response.

FORMAT (pick ONE):
{"action":"tap","x":540,"y":1200,"reason":"tap Sign In"}
{"action":"type","text":"hello@gmail.com","reason":"enter email"}
{"action":"scroll_down","reason":"scroll to find element"}
{"action":"scroll_up","reason":"scroll back up"}
{"action":"swipe","x1":540,"y1":1800,"x2":540,"y2":600,"reason":"swipe"}
{"action":"back","reason":"go back"}
{"action":"home","reason":"home screen"}
{"action":"enter","reason":"submit"}
{"action":"open_app","package":"com.android.settings","reason":"open Settings"}
{"action":"open_url","url":"https://amazon.com","reason":"navigate"}
{"action":"wait","seconds":3,"reason":"wait for load"}
{"action":"done","reason":"task complete"}

RULES (strictly follow):
1. Output ONLY the JSON object — no text before or after, no markdown, no steps.
2. WRONG: "Let me..." {"action":"tap"}  WRONG: Step 1: {...} Step 2: {...}
3. CORRECT: {"action":"tap","x":360,"y":880,"reason":"tap Display"}
4. Only tap elements VISIBLE in the CURRENT SCREEN list — use exact coordinates shown.
5. If the needed app is NOT open yet: use open_app with its package name. If already open: do NOT use open_app.
6. If a target element is NOT visible in the list: use scroll_down — do NOT tap off-screen coordinates.
7. To enter text: FIRST tap the text field, THEN type in the next step. Never type without tapping first.
8. After typing text, press enter or tap the submit/search button.
9. Wait 2-3s after app launches or page navigations.
10. Say done only when the task goal is clearly achieved.
11. NEVER say error or give up. If something isn't working, try a DIFFERENT approach — scroll, go back, try another element, wait longer, reopen the app. You must EXHAUST all alternatives before reporting stuck.
12. The display is LIVE (RDP session) — the screen is real, not simulated. Screenshots reflect the actual device state."""

_FAILURE_ANALYSIS_PROMPT = """You are debugging an Android automation task that keeps failing. Analyze the root cause and suggest a DIFFERENT approach.

TASK: {task}

CURRENT SCREEN:
{screen_context}

RECENT FAILED ACTIONS (these approaches did NOT work):
{failed_actions}

KNOWN FAILURE PATTERNS FROM THIS SESSION:
{session_failures}

Analyze:
1. WHY is the current approach failing? (root cause — be specific)
2. What is the ACTUAL state of the screen vs what was expected?
3. What COMPLETELY DIFFERENT approach should be tried?
4. Can this task still be completed, or is it genuinely impossible?

Respond with ONLY this JSON:
{{"analysis": "root cause explanation", "recovery_action": "specific different action to try", "can_recover": true, "new_approach": "detailed step description"}}"""

_STEP_PROMPT = """TASK: {task}

{persona_context}

STEP {step}/{max_steps} | DISPLAY: LIVE (RDP visible — not headless)

CURRENT SCREEN:
{screen_context}

{failure_context}

PREVIOUS ACTIONS:
{action_history}

What is the next action? Respond with a single JSON object."""


# ═══════════════════════════════════════════════════════════════════════
# TASK TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

TASK_TEMPLATES = {
    # ── INSTALL ───────────────────────────────────────────────────────
    "install_app": {
        "prompt": "Open the Google Play Store and search for '{app_name}'. Install the app and wait for installation to complete. Once installed, go back to Play Store home.",
        "params": ["app_name"],
        "category": "install",
        "realism": "achievable",
    },
    "install_batch": {
        "prompt": "Open Google Play Store and install the following apps one by one: {app_list}. For each app: search by name, tap Install, wait for installation to finish, then go back to Play Store for the next one. Skip any app that requires payment.",
        "params": ["app_list"],
        "category": "install",
        "realism": "achievable",
    },
    # ── SIGN-IN ───────────────────────────────────────────────────────
    "google_signin": {
        "prompt": "Open Settings, go to Accounts, and add a Google account. Use email {email} and password {password}. If Google shows verification (SMS, phone prompt, CAPTCHA), complete it if possible. Accept all terms. NOTE: If stuck on a verification screen you cannot bypass, report done with what was accomplished so far.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "chrome_signin": {
        "prompt": "Open Google Chrome. Tap the profile icon or go to Settings > Sign in. Sign in with Google account {email} and password {password}. Enable sync if prompted.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "login_app": {
        "prompt": "Open {app_name} app and log in with email {email} and password {password}. Complete any verification or setup steps that appear.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "paypal_signin": {
        "prompt": "Open PayPal app. Tap 'Log In'. Enter email {email} and password {password}. Complete any security verification. Skip any promotional screens.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "venmo_signin": {
        "prompt": "Open Venmo app. Tap 'Sign In'. Enter phone number or email {email} and password {password}. Complete verification if asked. Skip any setup prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "cashapp_signin": {
        "prompt": "Open Cash App. Enter phone number or email {email}. Complete the sign-in flow. Verify with code if needed. Skip optional setup steps.",
        "params": ["email"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "bank_app_signin": {
        "prompt": "Open {app_name} banking app. Tap 'Sign In' or 'Log In'. Enter username {email} and password {password}. Complete any security challenge or biometric prompt. Skip marketing screens.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "instagram_signin": {
        "prompt": "Open Instagram. Tap 'Log In'. Enter username {email} and password {password}. If asked to save login info, tap 'Save'. Skip any popups or notifications prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    # ── WALLET ────────────────────────────────────────────────────────
    "wallet_verify": {
        "prompt": "Open Google Wallet (or Google Pay) app. Check if a payment card is visible on the main screen. If a card ending in {card_last4} is shown, the wallet is set up correctly. Take a screenshot showing the card. Then go back to home screen.",
        "params": ["card_last4"],
        "category": "wallet",
        "realism": "achievable",
    },
    "wallet_add_card_ui": {
        "prompt": "Open Google Wallet (or Google Pay). Tap 'Add to Wallet' or '+' button. Select 'Payment card' or 'Credit or debit card'. When the camera/scanner appears, tap 'Enter details manually'. Fill in the card details when prompted and accept all terms. NOTE: Bank verification (SMS OTP) will require manual intervention — if a verification screen appears that the agent cannot proceed past, report done with what was accomplished.",
        "params": [],
        "category": "wallet",
        "realism": "requires_otp",
    },
    "play_store_add_payment": {
        "prompt": "Open Google Play Store. Tap your profile icon (top right). Tap 'Payments & subscriptions'. Tap 'Payment methods'. Tap 'Add payment method' or 'Add credit or debit card'. Follow the prompts to add a card. Accept any terms.",
        "params": [],
        "category": "wallet",
        "realism": "requires_payment",
    },
    # ── AGING / WARMUP ────────────────────────────────────────────────
    "warmup_device": {
        "prompt": "Open Chrome and browse naturally for 5 minutes. Visit Google, YouTube, and 3 other popular websites. Scroll through content on each site. This is to warm up the device with realistic usage.",
        "params": [],
        "category": "aging",
        "realism": "achievable",
    },
    "warmup_youtube": {
        "prompt": "Open YouTube app. Search for '{query}' or browse the home feed. Watch at least 2 videos for 30 seconds each, scrolling the feed between videos. Like one video.",
        "params": ["query"],
        "category": "aging",
        "realism": "achievable",
    },
    "warmup_maps": {
        "prompt": "Open Google Maps. Search for '{location}'. Explore the area, check a restaurant or business listing, look at reviews. Then get directions from current location to that place.",
        "params": ["location"],
        "category": "aging",
        "realism": "achievable",
    },
    "warmup_social": {
        "prompt": "Open {app_name}. Scroll through the main feed for 2-3 minutes. View 3-4 posts. Like one post. Go to the Explore/Discover tab and browse briefly.",
        "params": ["app_name"],
        "category": "aging",
        "realism": "achievable",
    },
    "gmail_compose": {
        "prompt": "Open Gmail. Compose a new email to {to_email} with subject '{subject}' and body '{body}'. Send the email.",
        "params": ["to_email", "subject", "body"],
        "category": "aging",
        "realism": "achievable",
    },
    "settings_tweak": {
        "prompt": "Open Settings. Change the display brightness to about 60%. Go to Sounds and set the ring volume to medium. Go to Display and check the current wallpaper. Go back to home screen.",
        "params": [],
        "category": "aging",
        "realism": "achievable",
    },
    # ── BROWSE ────────────────────────────────────────────────────────
    "browse_url": {
        "prompt": "Open the web browser and navigate to {url}. Wait for the page to load completely.",
        "params": ["url"],
        "category": "browse",
        "realism": "achievable",
    },
    "browse_site": {
        "prompt": "Open the web browser and visit {url}. Scroll through the page, click 2-3 links, and spend a moment on each page.",
        "params": ["url"],
        "category": "browse",
        "realism": "achievable",
    },
    "search_google": {
        "prompt": "Open the web browser, go to google.com, and search for '{query}'. Click on the first organic result and scroll through the page.",
        "params": ["query"],
        "category": "browse",
        "realism": "achievable",
    },
    "browse_amazon": {
        "prompt": "Open Amazon app or amazon.com. Search for '{product_query}', view product details, add one item to cart, and return to home.",
        "params": ["product_query"],
        "category": "browse",
        "realism": "achievable",
    },
    "open_app": {
        "prompt": "Launch app {package}, wait for it to open, and navigate around the main screen for a few actions.",
        "params": ["package"],
        "category": "install",
        "realism": "achievable",
    },
    "check_gmail": {
        "prompt": "Open Gmail app. Refresh inbox, open the top email, and confirm content is visible.",
        "params": [],
        "category": "aging",
        "realism": "achievable",
    },
    "take_photo": {
        "prompt": "Open Camera app, take a photo, and return to home screen.",
        "params": [],
        "category": "aging",
        "realism": "achievable",
    },
    "youtube_video": {
        "prompt": "Open YouTube app. Search for '{query}' and play the first result for 30 seconds.",
        "params": ["query"],
        "category": "aging",
        "realism": "achievable",
    },
    "login_facebook": {
        "prompt": "Open Facebook app. Tap 'Log In'. Enter email {email} and password {password}. Complete any verification and dismiss optional prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_captcha",
    },
    "create_account": {
        "prompt": "Go to {url} and create a new account. Use the persona details provided. Fill in all required fields and submit the registration form. NOTE: If a CAPTCHA appears, try to solve it. If email verification is required, report done with current progress.",
        "params": ["url"],
        "category": "sign_in",
        "realism": "requires_captcha",
    },
    # ── SOCIAL SIGN-INS ──────────────────────────────────────────────
    "facebook_signin": {
        "prompt": "Open Facebook app. Tap 'Log In'. Enter email {email} and password {password}. Tap 'Log In' button. If asked to save login, tap 'OK'. Skip any 'Find Friends' or notification prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_captcha",
    },
    "tiktok_signin": {
        "prompt": "Open TikTok app. Tap 'Profile' tab at bottom. Tap 'Log in'. Choose 'Use phone/email/username'. Enter email {email} and password {password}. Complete any CAPTCHA or verification. Skip onboarding prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_captcha",
    },
    "whatsapp_setup": {
        "prompt": "Open WhatsApp. Enter phone number {phone} when prompted. Verify with SMS code if possible, otherwise wait. Enter display name {name} when asked. Skip backup restoration. Allow contacts access if prompted. NOTE: SMS verification requires real phone number — if stuck on verification, report done with what was accomplished.",
        "params": ["phone", "name"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "telegram_signin": {
        "prompt": "Open Telegram app. Enter phone number {phone}. Wait for SMS verification code. Enter the code if received. Set display name to {name} if prompted. Skip optional profile photo.",
        "params": ["phone", "name"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "snapchat_signin": {
        "prompt": "Open Snapchat app. Tap 'Log In'. Enter username or email {email} and password {password}. Complete any verification. Skip 'Add Friends' and notification prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "twitter_signin": {
        "prompt": "Open X (Twitter) app. Tap 'Sign in'. Enter email or username {email}. Enter password {password} on next screen. Skip any 'Turn on notifications' or suggestions prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    # ── CRYPTO / COMMERCE ────────────────────────────────────────────
    "crypto_signin": {
        "prompt": "Open {app_name} app. Tap 'Sign In' or 'Log In'. Enter email {email} and password {password}. Complete 2FA or email verification if prompted. Skip any promotional screens or tutorials.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
        "realism": "requires_otp",
    },
    "amazon_signin": {
        "prompt": "Open Amazon Shopping app. Tap 'Sign In'. Enter email {email} and password {password}. Complete any CAPTCHA or OTP verification. Skip 'Turn on notifications'. Browse home page briefly.",
        "params": ["email", "password"],
        "category": "sign_in",
        "realism": "requires_captcha",
    },
    # ── PLAY STORE / APP MANAGEMENT ──────────────────────────────────
    "play_purchase": {
        "prompt": "Open Google Play Store. Search for '{app_name}'. If it has an in-app purchase or paid version, tap 'Buy' or 'Install' (paid). Complete the purchase using the saved payment method. Accept any confirmations. NOTE: Requires valid payment method already configured in Play Store.",
        "params": ["app_name"],
        "category": "install",
        "realism": "requires_payment",
    },
    "app_update": {
        "prompt": "Open Google Play Store. Tap your profile icon (top right). Tap 'Manage apps & device'. Tap 'Updates available'. Update {app_name} if listed, or tap 'Update all'. Wait for updates to finish.",
        "params": ["app_name"],
        "category": "install",
        "realism": "achievable",
    },
    # ── NOTIFICATION / PERMISSION HANDLING ───────────────────────────
    "handle_permissions": {
        "prompt": "A dialog or permission prompt is visible on screen. If it asks to allow notifications, tap 'Allow'. If it asks for location/camera/contacts permission, tap 'Allow' or 'While using the app'. If it shows a promotional popup, dismiss it by tapping 'No thanks', 'Skip', 'Not now', or the X button. Return to the app's main screen.",
        "params": [],
        "category": "aging",
        "realism": "achievable",
    },
}


# Agent capabilities populated from docs (06-ai-agent and others)
DOCS_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))
AGENT_CAPABILITIES = load_agent_capabilities_from_docs(DOCS_BASE_DIR)


# ═══════════════════════════════════════════════════════════════════════
# DEVICE AGENT
# ═══════════════════════════════════════════════════════════════════════

class DeviceAgent:
    """AI-powered autonomous Android device controller."""

    def __init__(self, adb_target: str = "127.0.0.1:5555",
                 model: str = "",
                 ollama_url: str = GPU_OLLAMA_URL):
        self.target = adb_target
        self.ollama_url = ollama_url
        # Auto-detect best action model if not explicitly set
        self.model = model or _detect_best_model(ollama_url, "action")
        self.vision_model = _detect_best_model(ollama_url, "vision")
        self.analyzer = ScreenAnalyzer(adb_target=adb_target)
        self.touch = TouchSimulator(adb_target=adb_target)
        self._tasks: Dict[str, AgentTask] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._current_traj: Optional[TrajectoryLogger] = None
        # ── Session memory: persists across tasks within this agent instance ──
        self._session_memory: Dict[str, Any] = {
            "failures": [],          # All FailureVector dicts from all tasks
            "screens_visited": [],   # Screen summaries for context
            "resolved_patterns": [], # Patterns that were fixed (learn from)
            "display_mode": DISPLAY_MODE,
        }
        logger.info(f"DeviceAgent init: action={self.model}, vision={self.vision_model}, display={DISPLAY_MODE}")

    # ─── PUBLIC API ───────────────────────────────────────────────────

    def start_task(self, prompt: str, persona: Dict[str, str] = None,
                   template: str = None, template_params: Dict = None,
                   max_steps: int = MAX_STEPS,
                   model_override: str = None) -> str:
        """Start an autonomous task on the device. Returns task_id.
        
        Model priority: model_override (client) > TASK_MODEL_ROUTING (category) > self.model (default)
        """
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        # Apply template if specified
        final_prompt = prompt
        task_category = ""
        if template and template in TASK_TEMPLATES:
            tmpl = TASK_TEMPLATES[template]
            params = template_params or {}
            final_prompt = tmpl["prompt"].format(**params)
            task_category = tmpl.get("category", "")

        # Model selection: client override > category routing > agent default
        if model_override:
            task_model = model_override
            logger.info(f"Task {task_id}: client override → model={task_model}")
        elif task_category and task_category in TASK_MODEL_ROUTING:
            task_model = TASK_MODEL_ROUTING[task_category]
            logger.info(f"Task {task_id}: category={task_category} → model={task_model}")
        else:
            task_model = self.model

        task = AgentTask(
            id=task_id,
            device_id=self.target,
            prompt=final_prompt,
            status="queued",
            model=task_model,
            max_steps=max_steps,
            persona=persona or {},
        )
        self._tasks[task_id] = task

        stop_flag = threading.Event()
        self._stop_flags[task_id] = stop_flag

        thread = threading.Thread(target=self._run_task, args=(task_id,), daemon=True)
        self._threads[task_id] = thread
        thread.start()
        logger.info(f"Task {task_id} started: model={task_model}, prompt={final_prompt[:80]}...")
        return task_id

    # ─── PUBLIC API ───────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self._tasks.get(task_id)

    def stop_task(self, task_id: str) -> bool:
        if task_id in self._stop_flags:
            self._stop_flags[task_id].set()
            return True
        return False

    def list_tasks(self) -> List[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    def analyze_screen(self) -> dict:
        screen = self.analyzer.capture_and_analyze(use_ui_dump=True, use_ocr=True)
        return {
            "description": screen.description,
            "elements": len(screen.elements),
            "app": getattr(screen, "current_app", "unknown"),
            "text": (screen.all_text[:500] if screen.all_text else ""),
        }

    def get_session_memory(self) -> Dict[str, Any]:
        """Return the agent's session memory (failure vectors, screens, patterns)."""
        return {
            "total_failures": len(self._session_memory["failures"]),
            "resolved_patterns": len(self._session_memory["resolved_patterns"]),
            "screens_visited": len(self._session_memory["screens_visited"]),
            "display_mode": self._session_memory["display_mode"],
            "recent_failures": self._session_memory["failures"][-10:],
            "resolved": self._session_memory["resolved_patterns"][-10:],
        }

    # ─── MAIN LOOP ────────────────────────────────────────────────────

    def _run_task(self, task_id: str):
        """Main see→think→act loop with NEVER-SKIP failure analysis.
        Runs in background thread. On failure: stop, analyze WHY, patch approach, retry.
        Only gives up after exhausting MAX_ANALYSIS_ROUNDS of LLM diagnosis."""
        task = self._tasks[task_id]
        stop = self._stop_flags[task_id]

        task.status = "running"
        task.started_at = time.time()

        # ── Trajectory logging ──
        traj = TrajectoryLogger(task_id=task_id, device_id=task.device_id)
        traj.set_metadata(
            prompt=task.prompt, model=task.model, persona=task.persona,
            device_type="cuttlefish",
        )
        self._current_traj = traj

        import random as _rnd

        # ── Failure tracking state ──
        consecutive_failures = 0
        analysis_rounds_used = 0
        failure_context = ""         # Injected into prompt after analysis
        task_failures: List[FailureVector] = []

        try:
            step = 1
            while True:
                if stop.is_set():
                    task.status = "stopped"
                    break

                # ── SEE → THINK → ACT (with failure context injected) ──
                action = self._execute_step(task, step, failure_context)
                task.actions.append(action)
                task.steps_taken = step

                # ── Record screen in session memory ──
                if action.screen_summary:
                    self._session_memory["screens_visited"].append({
                        "step": step, "task_id": task_id,
                        "screen": action.screen_summary[:200],
                        "time": time.time(),
                    })
                    # Cap screen memory at 100 entries
                    if len(self._session_memory["screens_visited"]) > 100:
                        self._session_memory["screens_visited"] = \
                            self._session_memory["screens_visited"][-50:]

                # ── TASK COMPLETE ──
                if action.action_type == "done":
                    task.status = "completed"
                    task.result = action.reasoning
                    # Mark any pending failure vectors as resolved
                    for fv in task_failures:
                        if not fv.resolved:
                            fv.resolved = True
                    break

                # ── FAILURE DETECTION ──
                is_failure = (action.action_type == "error" or not action.success)

                if is_failure:
                    consecutive_failures += 1
                    fv = FailureVector(
                        step=step,
                        action_type=action.action_type,
                        action_params=action.params,
                        screen_summary=action.screen_summary,
                        error_reason=action.reasoning,
                        timestamp=time.time(),
                    )
                    task_failures.append(fv)
                    task.failure_vectors.append(fv)
                    self._session_memory["failures"].append(fv.to_dict())

                    logger.warning(
                        f"Task {task_id} step {step}: FAILURE #{consecutive_failures} — "
                        f"{action.action_type}: {action.reasoning[:80]}"
                    )

                    # ── ANALYSIS MODE: triggered after MAX_RETRIES_PER_STEP consecutive failures ──
                    if consecutive_failures >= MAX_RETRIES_PER_STEP:
                        analysis_rounds_used += 1

                        if analysis_rounds_used > MAX_ANALYSIS_ROUNDS:
                            task.status = "failed"
                            task.error = (
                                f"Exhausted {MAX_ANALYSIS_ROUNDS} analysis rounds at step {step}. "
                                f"Last failure: {action.reasoning[:200]}"
                            )
                            logger.error(
                                f"Task {task_id}: GIVING UP after {MAX_ANALYSIS_ROUNDS} analysis rounds "
                                f"({len(task_failures)} total failures)"
                            )
                            break

                        logger.warning(
                            f"Task {task_id}: entering ANALYSIS round {analysis_rounds_used}/"
                            f"{MAX_ANALYSIS_ROUNDS} after {consecutive_failures} consecutive failures"
                        )

                        # ── STOP AND ANALYZE: ask LLM why it's failing ──
                        analysis = self._analyze_failure(task, task_failures)

                        # Record analysis in failure vectors
                        for recent_fv in task_failures[-consecutive_failures:]:
                            recent_fv.analysis = analysis.get("analysis", "")
                            recent_fv.recovery_action = analysis.get("recovery_action", "")

                        if not analysis.get("can_recover", True):
                            task.status = "failed"
                            task.error = (
                                f"Analysis determined unrecoverable: "
                                f"{analysis.get('analysis', 'unknown')[:200]}"
                            )
                            logger.error(f"Task {task_id}: analysis says UNRECOVERABLE")
                            break

                        # ── BUILD PATCHED CONTEXT for next step ──
                        failure_context = self._build_failure_context(
                            task_failures, analysis
                        )
                        consecutive_failures = 0  # Reset for new round

                        # Record resolved pattern if analysis succeeded
                        self._session_memory["resolved_patterns"].append({
                            "task_id": task_id, "step": step,
                            "pattern": analysis.get("analysis", "")[:200],
                            "fix": analysis.get("new_approach", "")[:200],
                            "time": time.time(),
                        })

                        time.sleep(ANALYSIS_COOLDOWN)
                        step += 1
                        continue  # Retry with patched context

                    # Simple retry — wait a bit and try again
                    time.sleep(_rnd.uniform(1.0, 2.0))
                    step += 1
                    continue

                # ── SUCCESS — reset failure counters ──
                consecutive_failures = 0
                analysis_rounds_used = 0
                # Keep accumulated failure context as passive memory
                if task_failures:
                    failure_context = self._build_failure_context(task_failures)
                else:
                    failure_context = ""

                # ── LOOP DETECTION → triggers analysis, not immediate failure ──
                if len(task.actions) >= 5:
                    recent = [a.action_type + str(a.params) for a in task.actions[-5:]]
                    if len(set(recent)) == 1:
                        logger.warning(f"Task {task_id}: loop detected (same action 5x), analyzing...")
                        analysis_rounds_used += 1
                        if analysis_rounds_used > MAX_ANALYSIS_ROUNDS:
                            task.status = "failed"
                            task.error = "Stuck in loop — analysis exhausted"
                            break
                        analysis = self._analyze_failure(task, task_failures)
                        failure_context = self._build_failure_context(task_failures, analysis)
                        consecutive_failures = 0
                        time.sleep(ANALYSIS_COOLDOWN)

                # Oscillation detection → analysis
                if len(task.actions) >= 6:
                    last6 = [a.action_type + str(a.params) for a in task.actions[-6:]]
                    if (last6[0] == last6[2] == last6[4] and
                            last6[1] == last6[3] == last6[5] and
                            last6[0] != last6[1]):
                        logger.warning(f"Task {task_id}: oscillation detected, analyzing...")
                        analysis_rounds_used += 1
                        if analysis_rounds_used > MAX_ANALYSIS_ROUNDS:
                            task.status = "failed"
                            task.error = "Stuck in oscillating loop — analysis exhausted"
                            break
                        analysis = self._analyze_failure(task, task_failures)
                        failure_context = self._build_failure_context(task_failures, analysis)
                        consecutive_failures = 0
                        time.sleep(ANALYSIS_COOLDOWN)

                # Step limit
                if step >= task.max_steps:
                    task.status = "completed"
                    task.result = f"Max steps ({task.max_steps}) reached"
                    break

                # Post-action delay for UI transitions
                time.sleep(_rnd.uniform(1.5, 2.5))
                step += 1

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.exception(f"Task {task_id} crashed")

        task.completed_at = time.time()
        task.failure_vectors = task_failures
        traj.finalize(status=task.status, total_steps=task.steps_taken)
        self._current_traj = None
        logger.info(
            f"Task {task_id} finished: {task.status} ({task.steps_taken} steps, "
            f"{task.completed_at - task.started_at:.1f}s, "
            f"{len(task_failures)} failures, {analysis_rounds_used} analysis rounds)"
        )

    def _analyze_failure(self, task: AgentTask,
                         failures: List[FailureVector],
                         analysis_override: Dict = None) -> Dict:
        """Use LLM to diagnose WHY the task keeps failing and suggest a different approach.
        This is the 'stop and think' mode — the agent pauses, reviews all evidence,
        and formulates a recovery plan before retrying."""
        # Build failed actions summary
        failed_lines = []
        for fv in failures[-6:]:
            failed_lines.append(
                f"  Step {fv.step}: {fv.action_type}({json.dumps(fv.action_params)[:80]}) "
                f"→ FAILED: {fv.error_reason[:100]}"
            )
        failed_actions_text = "\n".join(failed_lines) if failed_lines else "  (none)"

        # Build session failure memory
        session_fails = self._session_memory.get("failures", [])[-10:]
        session_lines = []
        for sf in session_fails:
            session_lines.append(
                f"  [{sf.get('action', '?')}] {sf.get('error', '?')[:80]} "
                f"→ resolved: {sf.get('resolved', False)}"
            )
        session_text = "\n".join(session_lines) if session_lines else "  (no prior session failures)"

        # Get current screen state for analysis
        try:
            screen = self.analyzer.capture_and_analyze(use_ui_dump=True, use_ocr=True)
            screen_context = screen.to_llm_context()
        except Exception:
            screen_context = "(screen capture failed during analysis)"

        prompt = _FAILURE_ANALYSIS_PROMPT.format(
            task=task.prompt,
            screen_context=screen_context,
            failed_actions=failed_actions_text,
            session_failures=session_text,
        )

        llm_response = _query_ollama(
            prompt, model=task.model, ollama_url=self.ollama_url,
            temperature=0.4, max_tokens=512,
        )

        # Parse analysis JSON
        if llm_response:
            parsed = _parse_action_json(llm_response)
            if parsed and "analysis" in parsed:
                logger.info(
                    f"Failure analysis: {parsed.get('analysis', '')[:120]} | "
                    f"Recovery: {parsed.get('recovery_action', '')[:80]} | "
                    f"Can recover: {parsed.get('can_recover', True)}"
                )
                return parsed

        # Fallback if LLM analysis fails
        return {
            "analysis": "LLM analysis unavailable — will retry with fresh context",
            "recovery_action": "try a completely different UI path",
            "can_recover": True,
            "new_approach": "take a fresh screenshot, identify what's actually on screen, and try an alternative action",
        }

    def _build_failure_context(self, failures: List[FailureVector],
                               analysis: Dict = None) -> str:
        """Build failure context string to inject into the step prompt.
        This teaches the agent what NOT to do and what to try instead."""
        if not failures:
            return ""

        lines = ["FAILURE MEMORY (do NOT repeat these failed approaches):"]
        for fv in failures[-5:]:
            lines.append(
                f"  ✗ {fv.action_type}({json.dumps(fv.action_params)[:60]}) FAILED: {fv.error_reason[:80]}"
            )

        if analysis:
            lines.append(f"\nANALYSIS: {analysis.get('analysis', '')[:200]}")
            lines.append(f"TRY INSTEAD: {analysis.get('new_approach', analysis.get('recovery_action', ''))[:200]}")

        # Include any resolved patterns from session memory
        resolved = self._session_memory.get("resolved_patterns", [])[-3:]
        if resolved:
            lines.append("\nPREVIOUSLY RESOLVED ISSUES (learned from earlier):")
            for rp in resolved:
                lines.append(f"  ✓ {rp.get('pattern', '')[:80]} → fixed by: {rp.get('fix', '')[:80]}")

        return "\n".join(lines)

    def _execute_step(self, task: AgentTask, step: int,
                      failure_context: str = "") -> AgentAction:
        """Single see→think→act iteration. Failure context from analysis is injected into prompt."""
        action = AgentAction(step=step, timestamp=time.time())
        vision_used = False
        vision_desc_text = ""

        # 1. SEE — capture and analyze screen (retry up to 3 times)
        screen = None
        for _capture_attempt in range(3):
            screen = self.analyzer.capture_and_analyze(
                use_ui_dump=True,
                use_ocr=(step % 3 == 1),  # OCR every 3rd step for speed
            )
            if not screen.error:
                break
            logger.warning(f"Screen capture attempt {_capture_attempt + 1}/3 failed: {screen.error}")
            time.sleep(1.0 * (_capture_attempt + 1))

        action.screen_summary = screen.description[:200]

        if screen.error:
            action.action_type = "error"
            action.reasoning = f"Screen capture failed after 3 attempts: {screen.error}"
            return action

        # 1b. AUTO-DISMISS — handle crash/ANR dialogs before LLM query
        _crash_patterns = ["isn't responding", "has stopped", "keeps stopping",
                           "close app", "app isn't responding"]
        # 1c. AUTO-DISMISS — handle permission prompts automatically
        _permission_patterns = ["allow .* to access", "allow .* to send",
                                "allow .* to make", "allow .* to take"]
        _permission_buttons = ["allow", "while using the app", "only this time",
                               "allow all the time"]

        if screen.all_text:
            _lower_text = screen.all_text.lower()

            # Handle permission dialogs first (very common in real-world usage)
            import re as _re
            for _ppat in _permission_patterns:
                if _re.search(_ppat, _lower_text):
                    for el in screen.elements:
                        if el.text and el.text.lower().strip() in _permission_buttons:
                            self.touch.tap(el.center[0], el.center[1])
                            action.action_type = "grant_permission"
                            action.reasoning = f"Auto-granted permission: tapped '{el.text}'"
                            action.success = True
                            logger.info(f"Step {step}: auto-granted permission dialog")
                            return action

            # Handle crash/ANR dialogs
            for _pat in _crash_patterns:
                if _pat in _lower_text:
                    # Try to dismiss: tap "Close app" or "Wait" or "OK"
                    for el in screen.elements:
                        if el.text and el.text.lower() in ("close app", "close", "wait", "ok"):
                            self.touch.tap(el.center[0], el.center[1])
                            action.action_type = "dismiss_dialog"
                            action.reasoning = f"Auto-dismissed crash dialog: '{_pat}' → tapped '{el.text}'"
                            action.success = True
                            logger.info(f"Step {step}: auto-dismissed crash/ANR dialog")
                            return action
                    # Fallback: press Back to dismiss
                    self.touch.back()
                    action.action_type = "dismiss_dialog"
                    action.reasoning = f"Auto-dismissed crash dialog via BACK key: '{_pat}'"
                    action.success = True
                    return action

        # 2. THINK — ask LLM for next action
        screen_context = screen.to_llm_context()

        # Vision fallback: when UI dump returns 0 elements (e.g. canvas-based UI),
        # use a vision model to describe the screen visually.
        if len(screen.elements) == 0 and screen.screenshot_b64:
            vision_desc_text = self._vision_describe_screen(screen.screenshot_b64, task.prompt)
            if vision_desc_text:
                vision_used = True
                screen_context = (
                    f"[Screen: {screen.width}x{screen.height} | App: {screen.current_app}]\n"
                    f"[Vision Analysis - UI dump empty, screenshot analyzed by vision model]:\n"
                    f"{vision_desc_text}"
                )

        # Scroll heuristic: if last action was NOT scroll and task mentions a keyword
        # not visible in current elements, append a hint to steer the model.
        if not vision_used and screen.elements:
            visible_texts = " ".join(e.text.lower() for e in screen.elements if e.text)
            # Extract meaningful words from task prompt (>4 chars, not common verbs)
            _skip = {"open", "find", "the", "and", "tap", "click", "into", "from",
                     "with", "that", "this", "then", "after", "when", "your", "scroll"}
            task_words = [w.lower().strip(".,") for w in task.prompt.split()
                          if len(w) > 4 and w.lower().strip(".,") not in _skip]
            last_action = task.actions[-1].action_type if task.actions else ""
            if task_words and last_action not in ("scroll_down", "scroll_up"):
                if not any(w in visible_texts for w in task_words[:6]):
                    screen_context += "\n[HINT: Target element not visible in current view — consider scroll_down]"

        # Build action history (last 12 actions)
        history_lines = []
        for prev in task.actions[-12:]:
            history_lines.append(
                f"  Step {prev.step}: {prev.action_type}({json.dumps(prev.params)}) → {'OK' if prev.success else 'FAIL'} | {prev.reasoning[:60]}"
            )
        action_history = "\n".join(history_lines) if history_lines else "  (no previous actions)"

        # Build persona context
        persona_ctx = ""
        if task.persona:
            persona_parts = []
            for k, v in task.persona.items():
                if v:
                    persona_parts.append(f"{k}: {v}")
            if persona_parts:
                persona_ctx = "PERSONA DATA (use for form filling):\n  " + "\n  ".join(persona_parts)

        prompt = _AGENT_SYSTEM_PROMPT + "\n\n" + _STEP_PROMPT.format(
            task=task.prompt,
            persona_context=persona_ctx,
            step=step,
            max_steps=task.max_steps,
            screen_context=screen_context,
            failure_context=failure_context if failure_context else "(no prior failures)",
            action_history=action_history,
        )

        # 2b. QUERY LLM — retry on empty/unparseable responses
        llm_response = ""
        parsed = None
        for _llm_attempt in range(3):
            llm_response = _query_ollama(prompt, model=task.model, ollama_url=self.ollama_url)
            if not llm_response:
                logger.warning(f"Step {step}: LLM attempt {_llm_attempt + 1}/3 returned empty")
                time.sleep(1.5)
                continue
            parsed = _parse_action_json(llm_response)
            if parsed:
                break
            # LLM responded but JSON parse failed — retry with stripped prompt
            logger.warning(
                f"Step {step}: LLM attempt {_llm_attempt + 1}/3 unparseable: "
                f"{llm_response[:100]}"
            )
            # On retry, append a stronger formatting hint
            if _llm_attempt < 2:
                prompt += '\n\nIMPORTANT: Output ONLY raw JSON like {"action":"tap","x":540,"y":1200,"reason":"tap button"}. No markdown, no text.'
                time.sleep(1.0)

        if not llm_response:
            action.action_type = "error"
            action.reasoning = "LLM returned empty response after 3 retries"
            return action

        # 3. Parse action
        if not parsed:
            action.action_type = "error"
            action.reasoning = f"Could not parse LLM response after 3 retries: {llm_response[:200]}"
            return action

        action.action_type = parsed.get("action", "error")
        action.reasoning = parsed.get("reason", "")[:60]
        action.params = {k: v for k, v in parsed.items() if k not in ("action", "reason")}

        # 4. ACT — execute the action
        action.success = self._execute_action(action)

        # 5. LOG — record step for training data
        traj = getattr(self, "_current_traj", None)
        if traj:
            traj.log_step(
                step=step,
                screen_b64=getattr(screen, "screenshot_b64", ""),
                screen_context=screen_context,
                screen_width=screen.width,
                screen_height=screen.height,
                current_app=getattr(screen, "current_app", ""),
                element_count=len(screen.elements),
                vision_used=vision_used,
                vision_description=vision_desc_text,
                llm_prompt=prompt,
                llm_response=llm_response,
                llm_model=task.model,
                action=parsed,
                action_type=action.action_type,
                action_success=action.success,
                action_reasoning=action.reasoning,
            )

        logger.info(f"  Step {step}: {action.action_type}({json.dumps(action.params)[:60]}) "
                     f"→ {'OK' if action.success else 'FAIL'}")
        return action

    def _vision_describe_screen(self, screenshot_b64: str, task_hint: str = "") -> str:
        """Use vision model to describe screen when UIAutomator returns no elements.
        Sends base64 screenshot to minicpm-v or llava via Ollama /api/generate."""
        import urllib.request
        import urllib.error

        vision_models = [self.vision_model] + [m for m in FALLBACK_VISION_MODELS if m != self.vision_model]
        prompt = (
            f"Describe this Android phone screen in detail for an AI agent. "
            f"Current task: {task_hint[:100]}. "
            "List: 1) What app/screen is shown, 2) All visible buttons and their positions, "
            "3) Any text fields or input areas, 4) The best next tap coordinates (x,y) to progress the task. "
            "Be concise and specific about UI element positions."
        )

        urls_to_try = [self.ollama_url, CPU_OLLAMA_URL]
        for url in urls_to_try:
            for model in vision_models:
                try:
                    payload = json.dumps({
                        "model": model,
                        "prompt": prompt,
                        "images": [screenshot_b64],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 400},
                    }).encode()
                    req = urllib.request.Request(
                        f"{url}/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read().decode())
                        desc = data.get("response", "")
                        if desc:
                            logger.debug(f"Vision fallback used ({model}): {desc[:80]}...")
                            return desc
                except Exception as e:
                    logger.debug(f"Vision model {model} at {url} failed: {e}")
                    continue
        return ""

    def _execute_action(self, action: AgentAction) -> bool:
        """Execute a parsed action via TouchSimulator."""
        t = action.action_type
        p = action.params

        try:
            if t == "tap":
                return self.touch.tap(int(p.get("x", 0)), int(p.get("y", 0)))

            elif t == "type":
                return self.touch.type_text(str(p.get("text", "")))

            elif t == "swipe":
                return self.touch.swipe(
                    int(p.get("x1", 0)), int(p.get("y1", 0)),
                    int(p.get("x2", 0)), int(p.get("y2", 0)),
                )

            elif t == "scroll_down":
                return self.touch.scroll_down(int(p.get("amount", 800)))

            elif t == "scroll_up":
                return self.touch.scroll_up(int(p.get("amount", 800)))

            elif t == "back":
                return self.touch.back()

            elif t == "home":
                return self.touch.home()

            elif t == "enter":
                return self.touch.enter()

            elif t == "open_app":
                return self.touch.open_app(str(p.get("package", "")))

            elif t == "open_url":
                return self.touch.open_url(str(p.get("url", "")))

            elif t == "wait":
                self.touch.wait(float(p.get("seconds", 2)))
                return True

            elif t == "done":
                return True

            elif t == "error":
                return False

            else:
                logger.warning(f"Unknown action type: {t}")
                return False

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return False
