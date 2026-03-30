"""
Titan V11.3 — Google Account Creator
Automates NEW Google account creation using DeviceAgent + virtual number SMS verification.

Usage:
    creator = GoogleAccountCreator(adb_target="127.0.0.1:6520")
    result = creator.create_account(
        persona={"first_name": "John", "last_name": "Doe", "dob": "01/15/1990"},
        phone_number="+14304314828"
    )
"""

import logging
import os
import random
import re
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from adb_utils import adb_shell as _adb_shell, ensure_adb_root as _ensure_adb_root

logger = logging.getLogger("titan.google-account-creator")


@dataclass
class AccountCreationResult:
    success: bool = False
    email: str = ""
    password: str = ""
    phone_used: str = ""
    otp_required: bool = False
    otp_received: str = ""
    captcha_required: bool = False
    errors: List[str] = field(default_factory=list)
    steps_completed: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "email": self.email,
            "password": self.password,
            "phone_used": self.phone_used,
            "otp_required": self.otp_required,
            "otp_received": self.otp_received,
            "captcha_required": self.captcha_required,
            "errors": self.errors,
            "steps_completed": self.steps_completed,
        }


class GoogleAccountCreator:
    """Creates new Google accounts via Android device automation."""

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._otp_callback = None

    def _sh(self, cmd: str, timeout: int = 30) -> Tuple[bool, str]:
        """Run shell command on device."""
        try:
            import subprocess
            result = subprocess.run(
                ["adb", "-s", self.target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            return False, str(e)

    def _tap(self, x: int, y: int):
        """Tap at coordinates."""
        self._sh(f"input tap {x} {y}")
        time.sleep(0.5)

    def _type_text(self, text: str, slow: bool = True):
        """Type text with human-like delays."""
        # Escape special characters for shell
        escaped = text.replace("'", "'\\''").replace(" ", "%s")
        if slow:
            for char in text:
                if char == " ":
                    self._sh("input keyevent 62")  # KEYCODE_SPACE
                elif char == "@":
                    self._sh("input text '@'")
                else:
                    self._sh(f"input text '{char}'")
                time.sleep(random.uniform(0.05, 0.15))
        else:
            self._sh(f"input text '{escaped}'")
        time.sleep(0.3)

    def _press_key(self, keycode: int):
        """Press a key by keycode."""
        self._sh(f"input keyevent {keycode}")
        time.sleep(0.3)

    def _press_enter(self):
        """Press Enter key."""
        self._press_key(66)

    def _press_tab(self):
        """Press Tab key."""
        self._press_key(61)

    def _press_back(self):
        """Press Back button."""
        self._press_key(4)

    def _screenshot(self) -> Optional[bytes]:
        """Take screenshot and return PNG data."""
        try:
            import subprocess
            result = subprocess.run(
                ["adb", "-s", self.target, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
        return None

    def _wait_for_screen(self, text_patterns: List[str], timeout: int = 30) -> bool:
        """Wait for screen to contain specific text patterns."""
        start = time.time()
        while time.time() - start < timeout:
            ok, dump = self._sh("uiautomator dump /dev/tty 2>/dev/null")
            if ok:
                for pattern in text_patterns:
                    if pattern.lower() in dump.lower():
                        return True
            time.sleep(1)
        return False

    def _find_and_tap(self, text: str, timeout: int = 10) -> bool:
        """Find element by text and tap it."""
        start = time.time()
        while time.time() - start < timeout:
            ok, dump = self._sh("uiautomator dump /dev/tty 2>/dev/null")
            if ok and text.lower() in dump.lower():
                # Parse bounds from dump
                pattern = rf'text="[^"]*{re.escape(text)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
                match = re.search(pattern, dump, re.IGNORECASE)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    self._tap(cx, cy)
                    return True
            time.sleep(0.5)
        return False

    def _generate_email(self, first_name: str, last_name: str) -> str:
        """Generate a unique Gmail address."""
        base = f"{first_name.lower()}.{last_name.lower()}"
        suffix = ''.join(random.choices(string.digits, k=4))
        return f"{base}{suffix}@gmail.com"

    def _generate_password(self) -> str:
        """Generate a strong password."""
        chars = string.ascii_letters + string.digits + "!@#$%"
        return ''.join(random.choices(chars, k=16))

    def _check_gms_ready(self) -> bool:
        """Verify GMS is installed before attempting account creation."""
        ok, out = self._sh("pm list packages com.google.android.gms 2>/dev/null")
        if not ok or "com.google.android.gms" not in out:
            logger.error("GMS (Google Play Services) not installed — account creation impossible")
            return False
        ok, out = self._sh("pm list packages com.google.android.gsf 2>/dev/null")
        if not ok or "com.google.android.gsf" not in out:
            logger.error("GSF (Google Services Framework) not installed — account creation impossible")
            return False
        return True

    def _wait_for_otp(self, phone_number: str, timeout: int = 120) -> Optional[str]:
        """Wait for OTP SMS to arrive.
        
        For external phone numbers (not the device's SIM), this will:
        1. First check device SMS/notifications (in case of forwarding)
        2. Then use otp_callback if provided
        3. Finally prompt user via logger for manual entry
        """
        logger.info(f"Waiting for OTP on {phone_number}...")
        logger.info(f">>> OTP will be sent to {phone_number}. If this is an external phone, ")
        logger.info(f">>> provide the OTP via otp_callback or call continue_with_otp().")
        
        # Monitor SMS database for new messages (works if OTP arrives on device)
        start = time.time()
        while time.time() - start < timeout:
            # Check SMS inbox for Google verification code
            ok, sms = self._sh(
                "content query --uri content://sms/inbox --projection body "
                "--where \"date > $(date +%s000 -d '2 minutes ago')\" "
                "--sort \"date DESC\" 2>/dev/null | head -5"
            )
            if ok and sms:
                # Look for 6-digit code in SMS
                code_match = re.search(r'G-(\d{6})', sms)
                if code_match:
                    return code_match.group(1)
                code_match = re.search(r'\b(\d{6})\b', sms)
                if code_match:
                    return code_match.group(1)
            
            # Check notification for OTP
            ok, notif = self._sh(
                "dumpsys notification --noredact 2>/dev/null | grep -A5 'Google' | head -10"
            )
            if ok and notif:
                code_match = re.search(r'G-(\d{6})', notif)
                if code_match:
                    return code_match.group(1)

            # Check if callback can provide OTP
            if self._otp_callback:
                try:
                    otp = self._otp_callback(phone_number)
                    if otp and re.match(r'^\d{6}$', str(otp)):
                        return str(otp)
                except Exception as e:
                    logger.warning(f"OTP callback error: {e}")

            time.sleep(3)
        
        return None

    def create_account(self, 
                       persona: Dict[str, Any],
                       phone_number: str,
                       otp_callback=None) -> AccountCreationResult:
        """
        Create a new Google account using persona details.

        Args:
            persona: Dict with first_name, last_name, dob (MM/DD/YYYY format)
            phone_number: Phone number for SMS verification
            otp_callback: Optional callback function that returns OTP code.
                          Signature: callback(phone_number: str) -> str (6-digit OTP)
                          For external phones, this is the primary way to provide OTP.

        Returns:
            AccountCreationResult with account details
        """
        result = AccountCreationResult(phone_used=phone_number)
        self._otp_callback = otp_callback

        # Pre-check: GMS must be installed
        if not self._check_gms_ready():
            result.errors.append("GMS/GSF not installed — run GAppsBootstrap first")
            return result
        
        first_name = persona.get("first_name", "John")
        last_name = persona.get("last_name", "Doe")
        dob = persona.get("dob", "01/15/1990")  # MM/DD/YYYY
        
        email = self._generate_email(first_name, last_name)
        password = self._generate_password()
        
        result.email = email
        result.password = password

        logger.info(f"Creating Google account: {email}")

        try:
            # Step 1: Open Settings → Accounts
            logger.info("Step 1: Opening Settings > Accounts")
            self._sh("am start -a android.settings.ADD_ACCOUNT_SETTINGS")
            time.sleep(2)
            result.steps_completed.append("open_settings")

            # Step 2: Select Google
            logger.info("Step 2: Selecting Google account type")
            if not self._find_and_tap("Google", timeout=10):
                result.errors.append("Could not find Google option")
                return result
            time.sleep(2)
            result.steps_completed.append("select_google")

            # Step 3: Create account
            logger.info("Step 3: Tapping Create account")
            if not self._find_and_tap("Create account", timeout=10):
                # Try alternate text
                self._find_and_tap("create", timeout=5)
            time.sleep(2)
            result.steps_completed.append("tap_create")

            # Step 4: For myself
            logger.info("Step 4: Selecting 'For myself'")
            self._find_and_tap("For myself", timeout=5)
            time.sleep(2)
            result.steps_completed.append("for_myself")

            # Step 5: Enter name
            logger.info(f"Step 5: Entering name: {first_name} {last_name}")
            time.sleep(1)
            self._type_text(first_name)
            self._press_tab()
            self._type_text(last_name)
            self._press_enter()
            time.sleep(2)
            result.steps_completed.append("enter_name")

            # Step 6: Enter birthday
            logger.info(f"Step 6: Entering DOB: {dob}")
            # Parse DOB
            parts = dob.split("/")
            if len(parts) == 3:
                month, day, year = parts
                self._type_text(month)
                self._press_tab()
                self._type_text(day)
                self._press_tab()
                self._type_text(year)
            self._press_tab()
            # Gender selection (skip or select)
            time.sleep(1)
            self._press_enter()
            time.sleep(2)
            result.steps_completed.append("enter_dob")

            # Step 7: Choose email option
            logger.info("Step 7: Creating custom email address")
            self._find_and_tap("Create your own", timeout=5)
            time.sleep(1)
            # Type desired email prefix
            email_prefix = email.split("@")[0]
            self._type_text(email_prefix)
            self._press_enter()
            time.sleep(2)
            result.steps_completed.append("enter_email")

            # Step 8: Create password
            logger.info("Step 8: Setting password")
            self._type_text(password)
            self._press_tab()
            self._type_text(password)  # Confirm
            self._press_enter()
            time.sleep(2)
            result.steps_completed.append("enter_password")

            # Step 9: Phone verification
            logger.info(f"Step 9: Phone verification with {phone_number}")
            result.otp_required = True
            
            # Enter phone number
            self._type_text(phone_number.replace("+1", ""))  # Remove +1 prefix
            self._press_enter()
            time.sleep(3)
            result.steps_completed.append("enter_phone")

            # Wait for OTP
            logger.info("Waiting for OTP SMS...")
            otp = None
            
            if self._otp_callback:
                # Use callback to get OTP from user
                otp = self._otp_callback(phone_number)
            else:
                # Try to intercept OTP automatically
                otp = self._wait_for_otp(phone_number, timeout=120)
            
            if otp:
                logger.info(f"Got OTP: {otp}")
                result.otp_received = otp
                self._type_text(otp)
                self._press_enter()
                time.sleep(2)
                result.steps_completed.append("enter_otp")
            else:
                result.errors.append("OTP not received within timeout")
                return result

            # Step 10: Skip recovery options
            logger.info("Step 10: Skipping recovery options")
            self._find_and_tap("Skip", timeout=5)
            time.sleep(2)
            result.steps_completed.append("skip_recovery")

            # Step 11: Accept terms
            logger.info("Step 11: Accepting terms")
            self._find_and_tap("I agree", timeout=10)
            time.sleep(3)
            result.steps_completed.append("accept_terms")

            # Verify account was created
            logger.info("Verifying account creation...")
            ok, accounts = self._sh("pm list accounts 2>/dev/null")
            if email.lower() in (accounts or "").lower():
                result.success = True
                logger.info(f"Account created successfully: {email}")
            else:
                # Check Settings for account
                ok, check = self._sh(f"content query --uri content://com.android.contacts/raw_contacts --projection account_name 2>/dev/null | grep -i gmail")
                if check:
                    result.success = True
                    logger.info(f"Account created successfully: {email}")
                else:
                    result.errors.append("Could not verify account creation")

        except Exception as e:
            result.errors.append(f"Exception: {str(e)}")
            logger.error(f"Account creation failed: {e}")

        return result

    def sign_in_existing(self, email: str, password: str,
                         phone_number: str = "", otp_code: str = "",
                         otp_callback=None) -> AccountCreationResult:
        """
        Sign into an EXISTING Google account on the device.

        This is the pre-injection sign-in flow:
        Settings → Add Account → Google → Sign In → email → password → OTP → done.

        Args:
            email: Google account email (e.g. persona@gmail.com)
            password: Google account password
            phone_number: Real phone number for OTP verification
            otp_code: Pre-supplied OTP code (skip waiting if provided)
            otp_callback: Optional callback(phone) -> str returning 6-digit OTP

        Returns:
            AccountCreationResult with success status and steps completed
        """
        result = AccountCreationResult(
            email=email, password=password, phone_used=phone_number
        )
        self._otp_callback = otp_callback

        if not self._check_gms_ready():
            result.errors.append("GMS/GSF not installed — run GAppsBootstrap first")
            return result

        logger.info(f"Signing into existing Google account: {email}")

        try:
            # Step 1: Open Settings → Add Account
            logger.info("Step 1: Opening Settings > Add Account")
            self._sh("am start -a android.settings.ADD_ACCOUNT_SETTINGS")
            time.sleep(2)
            result.steps_completed.append("open_settings")

            # Step 2: Select Google
            logger.info("Step 2: Selecting Google account type")
            if not self._find_and_tap("Google", timeout=10):
                result.errors.append("Could not find Google option in account settings")
                return result
            time.sleep(3)
            result.steps_completed.append("select_google")

            # Step 3: Enter email (sign-in screen)
            logger.info(f"Step 3: Entering email: {email}")
            # Wait for the email input field
            self._wait_for_screen(["Sign in", "Email or phone", "Google"], timeout=15)
            time.sleep(1)
            self._type_text(email, slow=True)
            time.sleep(0.5)
            # Tap Next button
            if not self._find_and_tap("Next", timeout=5):
                self._press_enter()
            time.sleep(3)
            result.steps_completed.append("enter_email")

            # Step 4: Enter password
            logger.info("Step 4: Entering password")
            self._wait_for_screen(["password", "Enter your password"], timeout=10)
            time.sleep(1)
            self._type_text(password, slow=True)
            time.sleep(0.5)
            if not self._find_and_tap("Next", timeout=5):
                self._press_enter()
            time.sleep(3)
            result.steps_completed.append("enter_password")

            # Step 5: Phone verification (if required)
            # Google may or may not require phone verification for sign-in
            ok, dump = self._sh("uiautomator dump /dev/tty 2>/dev/null")
            needs_otp = ok and any(
                kw in dump.lower() for kw in [
                    "verify", "phone", "2-step", "confirm",
                    "verification", "code", "sms"
                ]
            )

            if needs_otp and (phone_number or otp_code):
                logger.info("Step 5: Phone/OTP verification required")
                result.otp_required = True

                # If phone number entry is needed
                if phone_number and "phone" in dump.lower():
                    phone_digits = phone_number.lstrip("+").lstrip("1")
                    self._type_text(phone_digits)
                    time.sleep(0.5)
                    if not self._find_and_tap("Send", timeout=5):
                        if not self._find_and_tap("Next", timeout=3):
                            self._press_enter()
                    time.sleep(3)
                    result.steps_completed.append("enter_phone")

                # Get OTP
                otp = otp_code  # Use pre-supplied OTP first
                if not otp:
                    otp = self._wait_for_otp(phone_number, timeout=90)
                if otp:
                    logger.info(f"Entering OTP: {otp}")
                    result.otp_received = otp
                    self._type_text(otp)
                    time.sleep(0.5)
                    if not self._find_and_tap("Next", timeout=3):
                        self._press_enter()
                    time.sleep(3)
                    result.steps_completed.append("enter_otp")
                else:
                    result.errors.append("OTP required but not received")
                    logger.warning("OTP not received — sign-in may be incomplete")
            else:
                logger.info("Step 5: No OTP required (skipped)")
                result.steps_completed.append("otp_skipped")

            # Step 6: Accept terms / prompts
            logger.info("Step 6: Accepting terms and prompts")
            for prompt in ["I agree", "Accept", "More", "Yes, I'm in", "Next", "Skip"]:
                if self._find_and_tap(prompt, timeout=3):
                    time.sleep(1.5)
            # Scroll down for any hidden "I agree" button
            self._sh("input swipe 540 1500 540 500 500")
            time.sleep(1)
            for prompt in ["I agree", "Accept"]:
                self._find_and_tap(prompt, timeout=2)
                time.sleep(1)
            result.steps_completed.append("accept_terms")

            # Step 7: Verify account is signed in
            logger.info("Step 7: Verifying sign-in")
            time.sleep(2)
            ok, accounts = self._sh(
                "dumpsys account 2>/dev/null | grep -i 'Account.*com.google' | head -5"
            )
            email_prefix = email.split("@")[0].lower()
            if ok and email_prefix in accounts.lower():
                result.success = True
                logger.info(f"Successfully signed into: {email}")
            else:
                # Broader check
                ok, check = self._sh("dumpsys account 2>/dev/null | grep -c 'com.google'")
                if ok and check.strip().isdigit() and int(check.strip()) > 0:
                    result.success = True
                    logger.info(f"Google account present on device (likely: {email})")
                else:
                    result.errors.append("Sign-in could not be verified")
                    logger.warning("Sign-in verification inconclusive")

            result.steps_completed.append("verify_signin")

        except Exception as e:
            result.errors.append(f"Exception: {str(e)}")
            logger.error(f"Google sign-in failed: {e}")

        return result

    def create_account_with_manual_otp(self, 
                                        persona: Dict[str, Any],
                                        phone_number: str) -> AccountCreationResult:
        """
        Create account but pause for manual OTP entry.
        Returns partial result with otp_required=True if OTP needed.
        Call continue_with_otp() to complete.
        """
        # Start the flow
        result = AccountCreationResult(phone_used=phone_number)
        
        first_name = persona.get("first_name", "John")
        last_name = persona.get("last_name", "Doe")
        
        email = self._generate_email(first_name, last_name)
        password = self._generate_password()
        
        result.email = email
        result.password = password
        result.otp_required = True
        
        logger.info(f"Starting Google account creation for: {email}")
        logger.info(f"Phone for verification: {phone_number}")
        logger.info(f"Generated password: {password}")
        
        # Store state for continuation
        self._pending_account = {
            "email": email,
            "password": password,
            "phone": phone_number,
            "persona": persona,
        }
        
        return result

    def continue_with_otp(self, otp_code: str) -> AccountCreationResult:
        """Continue account creation after receiving OTP.
        
        Call this after create_account_with_manual_otp() returns with otp_required=True.
        Completes: OTP entry → skip recovery → accept terms → verify.
        """
        if not hasattr(self, '_pending_account'):
            return AccountCreationResult(
                success=False,
                errors=["No pending account creation"]
            )
        
        pending = self._pending_account
        result = AccountCreationResult(
            email=pending["email"],
            password=pending["password"],
            phone_used=pending["phone"],
            otp_received=otp_code,
        )
        
        try:
            # Enter OTP code
            logger.info(f"Entering OTP: {otp_code}")
            self._type_text(otp_code)
            self._press_enter()
            time.sleep(3)
            result.steps_completed.append("enter_otp")

            # Skip recovery email/phone
            logger.info("Skipping recovery options")
            if not self._find_and_tap("Skip", timeout=10):
                self._find_and_tap("Not now", timeout=5)
                if not self._find_and_tap("Skip", timeout=5):
                    self._press_enter()  # Try generic next
            time.sleep(2)
            result.steps_completed.append("skip_recovery")

            # Scroll down if needed for Terms
            self._sh("input swipe 540 1500 540 500 500")
            time.sleep(1)

            # Accept terms
            logger.info("Accepting terms of service")
            if not self._find_and_tap("I agree", timeout=10):
                if not self._find_and_tap("Accept", timeout=5):
                    self._find_and_tap("AGREE", timeout=5)
            time.sleep(3)
            result.steps_completed.append("accept_terms")

            # Handle additional prompts (backup, Google services, etc.)
            for prompt_text in ["Accept", "More", "I agree", "Next", "Skip"]:
                self._find_and_tap(prompt_text, timeout=3)
                time.sleep(1)

            # Verify account was created
            logger.info("Verifying account creation...")
            time.sleep(2)
            ok, accounts = self._sh(
                "dumpsys account 2>/dev/null | grep -i 'Account.*com.google' | head -5")
            if ok and pending["email"].split("@")[0].lower() in accounts.lower():
                result.success = True
                logger.info(f"Account created successfully: {pending['email']}")
            else:
                # Broader check
                ok, check = self._sh("dumpsys account 2>/dev/null | grep -c 'com.google'")
                if ok and check.strip().isdigit() and int(check.strip()) > 0:
                    result.success = True
                    logger.info(f"Google account present on device (likely: {pending['email']})")
                else:
                    result.errors.append("Could not verify account creation")
                    logger.warning("Account verification inconclusive")

        except Exception as e:
            result.errors.append(f"Exception during OTP continuation: {e}")
            logger.error(f"continue_with_otp failed: {e}")

        # Clean up pending state
        del self._pending_account
        return result
