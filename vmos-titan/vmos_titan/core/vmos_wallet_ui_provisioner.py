"""
Titan V13 — VMOS Wallet UI Provisioner
========================================
Accessibility Service-based Google Pay card provisioning via VMOS Cloud API.

Replaces local SQLite/XML injection with AI-driven UI automation that:
  1. Launches the Google Wallet app on the cloud instance
  2. Navigates to "Add card" using humanized touch simulation
  3. Inputs card details via the VMOS Cloud `inputText` API
  4. Submits the card and polls for activation confirmation
  5. Hides the accessibility automation package from detection

This approach eliminates the direct database write vulnerability that static
injection methods expose (SQLite schema changes, ownership mismatches, etc.)
and produces a wallet card that passes tokenization service liveness checks.

Architecture:
    VMOSWalletUIProvisioner
      └─ VMOSCloudClient         (cloud API control plane)
      └─ simulate_click_humanized  (Fitts's-law touch via /openApi/simulateClick)
      └─ input_text                (keyboard injection via /padApi/inputText)
      └─ sync_cmd                  (shell verification via /padApi/syncCmd)
      └─ hide_accessibility_service  (anti-detection via /padApi/setHideAccessibilityAppList)

Usage:
    provisioner = VMOSWalletUIProvisioner(vmos_client, pad_code="xxx")
    result = await provisioner.provision_card_via_ui(
        card_number="4111111111111111",
        exp_month=12, exp_year=2027,
        cardholder="Jane Smith",
        cvv="123",
    )
    if result.success:
        print(f"Card provisioned via UI in {result.elapsed_seconds:.1f}s")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.vmos-wallet-ui")

# Google Wallet package name
_WALLET_PKG = "com.google.android.apps.walletnfcrel"
# Google Pay Play Store package (alternative entry)
_GPAY_PKG = "com.google.android.apps.nbu.paisa.user"

# Fallback display dimensions (VMOS cloud phones are typically 1080×2340)
_DEFAULT_WIDTH = 1080
_DEFAULT_HEIGHT = 2340

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class WalletUIProvisionResult:
    """Result of UI-driven wallet provisioning."""
    success: bool = False
    method: str = "ui_automation"
    steps_completed: int = 0
    elapsed_seconds: float = 0.0
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------

class VMOSWalletUIProvisioner:
    """
    Provision a payment card into Google Wallet via VMOS Cloud UI automation.

    The provisioner drives the Google Wallet UI using the VMOS Cloud
    `simulateClick` and `inputText` APIs, mimicking real user interaction
    rather than writing directly to on-device databases.

    Args:
        vmos_client:     Authenticated VMOSCloudClient instance.
        pad_code:        VMOS cloud phone instance ID.
        screen_width:    Device screen width (pixels).
        screen_height:   Device screen height (pixels).
        hide_automation: Whether to hide the automation package from detection.
    """

    def __init__(self, vmos_client: Any, pad_code: str,
                 screen_width: int = _DEFAULT_WIDTH,
                 screen_height: int = _DEFAULT_HEIGHT,
                 hide_automation: bool = True):
        self._client = vmos_client
        self.pad_code = pad_code
        self.width = screen_width
        self.height = screen_height
        self.hide_automation = hide_automation

    # ── Public API ────────────────────────────────────────────────────

    async def provision_card_via_ui(
        self,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cardholder: str,
        cvv: str = "",
        billing_zip: str = "",
    ) -> WalletUIProvisionResult:
        """
        Provision a payment card using Accessibility Service UI automation.

        Navigates the Google Wallet "Add card" flow and inputs card details
        via touch simulation and text injection through the VMOS Cloud API.

        Returns a WalletUIProvisionResult with success status and diagnostics.
        """
        start = time.time()
        result = WalletUIProvisionResult()

        try:
            if self.hide_automation:
                await self._hide_automation_package()

            # Step 1 — Launch Google Wallet
            await self._launch_wallet()
            result.steps_completed += 1

            # Step 2 — Navigate to Add Card
            await self._navigate_to_add_card()
            result.steps_completed += 1

            # Step 3 — Enter card number
            await self._enter_card_number(card_number)
            result.steps_completed += 1

            # Step 4 — Enter expiry
            exp_str = f"{exp_month:02d}{str(exp_year)[-2:]}"
            await self._enter_text_field(exp_str)
            result.steps_completed += 1

            # Step 5 — Enter CVV (if required)
            if cvv:
                await self._enter_text_field(cvv)
                result.steps_completed += 1

            # Step 6 — Enter cardholder name
            await self._enter_text_field(cardholder)
            result.steps_completed += 1

            # Step 7 — Enter billing ZIP (if provided)
            if billing_zip:
                await self._enter_text_field(billing_zip)
                result.steps_completed += 1

            # Step 8 — Submit (tap Save / Next)
            await self._tap_submit()
            result.steps_completed += 1

            # Step 9 — Poll for confirmation
            confirmed = await self._poll_card_added(card_number[-4:])
            result.success = confirmed
            result.steps_completed += 1
            result.details["last4"] = card_number[-4:]

        except Exception as exc:
            result.error = str(exc)
            logger.warning("VMOSWalletUIProvisioner error: %s", exc)

        result.elapsed_seconds = round(time.time() - start, 2)
        logger.info("Wallet UI provision: success=%s steps=%d elapsed=%.1fs",
                    result.success, result.steps_completed, result.elapsed_seconds)
        return result

    # ── Internal steps ────────────────────────────────────────────────

    async def _hide_automation_package(self):
        """Hide accessibility automation package from detection lists."""
        try:
            # Hide the Android system accessibility package so RASP SDKs
            # cannot enumerate the active accessibility services
            await self._client.hide_accessibility_service(
                [self.pad_code],
                ["com.android.accessibilityservice", "com.google.android.marvin.talkback"],
            )
        except Exception as e:
            logger.debug("hide_accessibility_service skipped: %s", e)

    async def _launch_wallet(self):
        """Launch Google Wallet app and wait for it to be ready."""
        pads = [self.pad_code]

        # Force-stop first to get a clean launch state
        try:
            await self._client.stop_app(pads, _WALLET_PKG)
            await asyncio.sleep(1.0)
        except Exception:
            pass

        # Launch wallet
        await self._client.start_app(pads, _WALLET_PKG)
        # Allow splash screen to complete
        await asyncio.sleep(3.0)
        logger.debug("Wallet launched on %s", self.pad_code)

    async def _navigate_to_add_card(self):
        """Tap the '+ Add card' or 'Add to Wallet' button."""
        # Bottom-right FAB: ~90% width, ~88% height (typical Wallet layout)
        x = int(self.width * 0.90)
        y = int(self.height * 0.88)
        await self._tap(x, y)
        await asyncio.sleep(2.0)

        # Tap "Payment card" option (~50% width, ~55% height on card selector)
        await self._tap(int(self.width * 0.50), int(self.height * 0.55))
        await asyncio.sleep(2.0)
        logger.debug("Navigated to Add Card screen")

    async def _enter_card_number(self, card_number: str):
        """Focus card number field and type the card number."""
        # Card number input field: ~50% width, ~35% height
        await self._tap(int(self.width * 0.50), int(self.height * 0.35))
        await asyncio.sleep(0.5)
        await self._type(card_number)
        await asyncio.sleep(0.5)
        # Tap Next on keyboard
        await self._tap_soft_keyboard_next()

    async def _enter_text_field(self, text: str):
        """Type text into the currently focused field."""
        await asyncio.sleep(0.5)
        await self._type(text)
        await asyncio.sleep(0.3)
        await self._tap_soft_keyboard_next()

    async def _tap_submit(self):
        """Tap the Save / Continue button to submit the card."""
        # Primary action button: ~50% width, ~85% height
        await self._tap(int(self.width * 0.50), int(self.height * 0.85))
        await asyncio.sleep(3.0)
        logger.debug("Submit tapped")

    async def _poll_card_added(self, last4: str, max_wait: int = 30) -> bool:
        """
        Poll the device to verify the card was successfully added.

        Checks the Google Wallet database for a row matching last4.
        Returns True if card found within max_wait seconds.
        """
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                resp = await self._client.sync_cmd(
                    self.pad_code,
                    f"sqlite3 /data/data/{_WALLET_PKG}/databases/tapandpay.db "
                    f"\"SELECT COUNT(*) FROM card WHERE last4='{last4}'\" 2>/dev/null",
                    timeout_sec=15,
                )
                output = (resp.get("data") or {}).get("errorMsg", "").strip()
                if output and output != "0":
                    logger.info("Card %s confirmed in Wallet DB", last4)
                    return True
            except Exception as e:
                logger.debug("DB poll error: %s", e)
            await asyncio.sleep(3.0)
        logger.warning("Card %s not confirmed in Wallet DB after %ds", last4, max_wait)
        return False

    # ── Touch helpers ─────────────────────────────────────────────────

    async def _tap(self, x: int, y: int):
        """Perform a humanized tap at (x, y) via VMOS Cloud API."""
        try:
            await self._client.simulate_click_humanized(self.pad_code, x, y)
        except Exception as e:
            logger.debug("tap(%d,%d) failed: %s; falling back to syncCmd", x, y, e)
            # ADB input fallback
            await self._client.sync_cmd(
                self.pad_code,
                f"input tap {x} {y}",
                timeout_sec=10,
            )

    async def _type(self, text: str):
        """Inject text into the currently focused view via VMOS Cloud inputText."""
        try:
            await self._client.input_text(self.pad_code, text)
        except Exception as e:
            logger.debug("input_text failed: %s; falling back to syncCmd", e)
            safe_text = text.replace("'", "")
            await self._client.sync_cmd(
                self.pad_code,
                f"input text '{safe_text}'",
                timeout_sec=10,
            )

    async def _tap_soft_keyboard_next(self):
        """Tap the keyboard action key (Next/Done) — typically bottom-right of keyboard."""
        # Soft keyboard Next key: ~93% width, ~97% height
        await self._tap(int(self.width * 0.93), int(self.height * 0.97))
        await asyncio.sleep(0.4)
