"""
Titan V13.0 — Google Master Auth
=================================
Acquires real, server-validated Google OAuth tokens using the Android Account
Services (AAS) master-token flow via the ``gpsoauth`` library.

Three authentication methods are supported, ranked by reliability:

  Method A — gpsoauth master-token (host-side, no device UI required)
  Method B — Coordinate-based UI automation sign-in (VMOS fallback)
  Method C — Hybrid injection + AccountManager refresh (background re-auth)

Usage::

    from google_master_auth import GoogleMasterAuth, AuthMethod

    auth = GoogleMasterAuth()

    # Method A: programmatic (real tokens, no UI)
    result = auth.authenticate(
        email="user@gmail.com",
        password="app_password",          # use Google App Password for 2FA accounts
        android_id="a1b2c3d4e5f6a7b8",   # 16-hex device ID
        method=AuthMethod.MASTER_TOKEN,
    )
    if result.success:
        print(result.master_token, result.tokens)

Notes:
- Google App Passwords bypass 2FA and work with this flow.
- Standard passwords may trigger re-auth or 2FA challenge.
- Tokens are short-lived (~1h for OAuth, indefinite for master_token).
- On VMOS Cloud devices (no local ADB), use method=AuthMethod.MASTER_TOKEN only.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("titan.google-master-auth")

# ── Google Play Services constants ────────────────────────────────────────────

_GPS_VERSION = "23.45.19 (190408-605850880)"
_GMS_VERSION_INT = 240913900

# Client signature of com.google.android.gms (production apk cert SHA1)
_CLIENT_SIG = "38918a453d07199354f8b19af05ec6562ced5788"

# OAuth2 scopes required for full Google account functionality
_CORE_SCOPES = [
    "oauth2:https://www.googleapis.com/auth/plus.me",
    "oauth2:https://www.googleapis.com/auth/userinfo.email",
    "oauth2:https://www.googleapis.com/auth/userinfo.profile",
    "oauth2:https://www.googleapis.com/auth/gmail.readonly",
    "oauth2:https://www.googleapis.com/auth/youtube",
    "oauth2:https://www.googleapis.com/auth/drive",
    "oauth2:https://www.googleapis.com/auth/contacts",
    "oauth2:https://www.googleapis.com/auth/calendar",
    "oauth2:https://www.googleapis.com/auth/android",
]


# ── Enums & result types ──────────────────────────────────────────────────────

class AuthMethod(str, Enum):
    MASTER_TOKEN = "master_token"   # gpsoauth programmatic (Method A) — recommended
    UI_AUTOMATION = "ui_automation" # coordinate-based UI on VMOS (Method B)
    HYBRID_INJECT = "hybrid_inject" # inject synthetic + trigger GMS refresh (Method C)


@dataclass
class AuthResult:
    """Result of a Google authentication attempt."""
    email: str = ""
    method: AuthMethod = AuthMethod.MASTER_TOKEN
    success: bool = False

    # Real tokens (present when Method A succeeds)
    master_token: str = ""   # aas_et/... — long-lived, use for token refresh
    tokens: Dict[str, str] = field(default_factory=dict)  # scope → Bearer token
    token_expiry: Dict[str, int] = field(default_factory=dict)  # scope → unix ts

    # Fallback synthetic tokens (present when Method A fails)
    synthetic_tokens: Dict[str, str] = field(default_factory=dict)

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_real_tokens(self) -> bool:
        return bool(self.master_token) and bool(self.tokens)

    @property
    def primary_token(self) -> str:
        """Return the primary oauth2 access token for GMS injection."""
        return (
            self.tokens.get("oauth2:https://www.googleapis.com/auth/plus.me")
            or next(iter(self.tokens.values()), "")
        )

    def all_tokens_for_injection(self) -> Dict[str, str]:
        """Return complete token dict suitable for accounts_ce.db authtoken rows.

        Falls back to synthetic tokens when real ones are unavailable.
        """
        base = dict(self.tokens) if self.tokens else dict(self.synthetic_tokens)
        # Always include a com.google master entry
        if "com.google" not in base:
            base["com.google"] = self.master_token or base.get(
                "oauth2:https://www.googleapis.com/auth/plus.me", ""
            )
        return base

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "method": str(self.method),
            "success": self.success,
            "has_real_tokens": self.has_real_tokens,
            "master_token": bool(self.master_token),
            "token_count": len(self.tokens),
            "synthetic_token_count": len(self.synthetic_tokens),
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ── Main authenticator ────────────────────────────────────────────────────────

class GoogleMasterAuth:
    """Acquire real Google OAuth tokens using the Android Account Services flow.

    The primary path (Method A) calls ``gpsoauth.perform_master_login`` followed
    by ``gpsoauth.perform_oauth`` for each required scope.  The library uses the
    same HTTPS endpoints as the Android GMS ``AccountManagerService``.

    When Method A fails (bad password, Google challenge, 2FA without app
    password) the caller can fall back to Method C (hybrid injection) which
    injects synthetic tokens and stores the plaintext password for GMS to refresh
    them on next sync.  Method B (UI automation) is for interactive environments
    only and is handled by ``google_account_creator.GoogleAccountCreator``.
    """

    def __init__(self, country: str = "us", lang: str = "en_US"):
        self.country = country.lower()
        self.lang = lang

    # ── Method A: gpsoauth master-token ───────────────────────────────

    def authenticate(
        self,
        email: str,
        password: str,
        android_id: str = "",
        method: AuthMethod = AuthMethod.MASTER_TOKEN,
        scopes: Optional[List[str]] = None,
        totp_secret: Optional[str] = None,
    ) -> AuthResult:
        """Obtain real OAuth tokens for *email* using *password*.

        Args:
            email: Gmail address (e.g. ``user@gmail.com``).
            password: Account password **or** Google App Password (recommended
                for 2FA accounts — create at myaccount.google.com/apppasswords).
            android_id: 16-char hex device fingerprint.  If empty, one is
                generated (this affects which tokens are bound to which device).
            method: Which authentication method to attempt.
            scopes: List of OAuth2 scopes.  Defaults to :data:`_CORE_SCOPES`.
            totp_secret: Base32 TOTP secret if user wants automatic 2FA code
                generation (not usually needed with an App Password).

        Returns:
            :class:`AuthResult` with real or synthetic tokens.
        """
        if not android_id:
            android_id = secrets.token_hex(8)

        result = AuthResult(email=email, method=method)

        if method == AuthMethod.MASTER_TOKEN:
            self._authenticate_master_token(
                result, email, password, android_id,
                scopes or _CORE_SCOPES, totp_secret,
            )
        elif method == AuthMethod.HYBRID_INJECT:
            self._authenticate_hybrid(result, email, password, android_id)
        else:
            result.errors.append(
                "AuthMethod.UI_AUTOMATION is handled by GoogleAccountCreator — "
                "pass the VMOS shell helper to that class instead."
            )

        # Guarantee synthetic tokens are always available as fallback
        if not result.tokens:
            result.synthetic_tokens = self._make_synthetic_tokens(email)
            if not result.success:
                result.warnings.append(
                    "Real token acquisition failed — synthetic tokens generated as "
                    "fallback.  Apps will show Sign-in Required after first sync."
                )
        return result

    def _authenticate_master_token(
        self,
        result: AuthResult,
        email: str,
        password: str,
        android_id: str,
        scopes: List[str],
        totp_secret: Optional[str],
    ) -> None:
        """Inner implementation of Method A."""
        try:
            import gpsoauth  # guarded import — optional dependency
        except ImportError:
            result.errors.append(
                "gpsoauth not installed — run: pip install gpsoauth>=1.0.0"
            )
            return

        logger.info("[%s] Method A: gpsoauth master-token login...", email)

        # ── Step 1: master login ──────────────────────────────────────
        try:
            master_resp = gpsoauth.perform_master_login(
                email=email,
                password=password,
                android_id=android_id,
                service="ac2dm",
                device_country=self.country,
                operator_country=self.country,
                lang=self.lang,
                sdk_version=34,
                client_sig=_CLIENT_SIG,
            )
        except Exception as exc:
            result.errors.append(f"Master login network error: {exc}")
            logger.warning("[%s] Master login network error: %s", email, exc)
            return

        if "Token" not in master_resp:
            error_code = master_resp.get("Error", "Unknown")
            error_detail = master_resp.get("ErrorDetail", "")
            msg = f"Master login failed: {error_code}"
            if error_detail:
                msg += f" — {error_detail}"
            if error_code == "NeedsBrowser":
                msg += (
                    " — Google requires browser-based sign-in. "
                    "Create an App Password at myaccount.google.com/apppasswords and use that instead."
                )
            elif error_code == "BadAuthentication":
                msg += " — Wrong password or App Password required for 2FA accounts."
            result.errors.append(msg)
            logger.warning("[%s] %s", email, msg)
            return

        master_token = master_resp["Token"]
        result.master_token = master_token
        logger.info("[%s] Master token acquired: aas_et/***%s", email, master_token[-6:])

        # ── Step 2: TOTP OTP if needed ───────────────────────────────
        if totp_secret:
            otp = self._generate_totp(totp_secret)
            logger.debug("[%s] Generated TOTP: %s", email, otp)

        # ── Step 3: exchange master token for per-scope OAuth tokens ──
        for scope in scopes:
            try:
                oauth_resp = gpsoauth.perform_oauth(
                    email=email,
                    master_token=master_token,
                    android_id=android_id,
                    service=scope,
                    app="com.google.android.gms",
                    client_sig=_CLIENT_SIG,
                    device_country=self.country,
                    operator_country=self.country,
                    lang=self.lang,
                    sdk_version=34,
                )
                if "Auth" in oauth_resp:
                    result.tokens[scope] = oauth_resp["Auth"]
                    expiry = oauth_resp.get("Expiry")
                    if expiry:
                        result.token_expiry[scope] = int(expiry)
                    logger.debug("[%s] OAuth token obtained for %s", email, scope)
                else:
                    warn = f"No Auth in OAuth response for {scope}: {oauth_resp.get('Error', '?')}"
                    result.warnings.append(warn)
                    logger.debug("[%s] %s", email, warn)
            except Exception as exc:
                result.warnings.append(f"OAuth exchange failed for {scope}: {exc}")
                logger.debug("[%s] OAuth error for %s: %s", email, scope, exc)

        if result.tokens:
            result.success = True
            logger.info(
                "[%s] Method A success: %d/%d scopes acquired",
                email, len(result.tokens), len(scopes),
            )
        else:
            result.errors.append(
                f"Master token acquired but no OAuth tokens exchanged for {len(scopes)} scopes"
            )

    # ── Method C: hybrid inject + GMS refresh ─────────────────────────

    def _authenticate_hybrid(
        self,
        result: AuthResult,
        email: str,
        password: str,
        android_id: str,
    ) -> None:
        """Method C: inject synthetic tokens + store password for GMS refresh.

        This does not produce real tokens directly.  Instead it injects the
        plaintext password into the accounts_ce.db ``password`` column so that
        Android AccountManagerService / GMS can refresh tokens on next sync.
        The ``vmos_db_builder`` module picks up ``result.hybrid_password`` when
        building the database.

        Note: GMS may surface a re-authentication UI on next boot if it detects
        unusual activity on the account.
        """
        result.synthetic_tokens = self._make_synthetic_tokens(email)
        # Expose the password for DB builder — stored in-memory only, not logged
        result._hybrid_password = password  # type: ignore[attr-defined]
        result.method = AuthMethod.HYBRID_INJECT
        # Mark success so downstream code proceeds with injection
        result.success = True
        result.warnings.append(
            "Hybrid mode: synthetic tokens injected with stored password. "
            "GMS will attempt real token refresh on next network sync. "
            "Apps may show Sign-in Required until sync completes."
        )
        logger.info("[%s] Method C: hybrid tokens prepared (password stored for GMS refresh)", email)

    # ── Token refresh ─────────────────────────────────────────────────

    def refresh_tokens(
        self,
        email: str,
        master_token: str,
        android_id: str,
        scopes: Optional[List[str]] = None,
    ) -> AuthResult:
        """Refresh all OAuth tokens using an existing master token.

        Master tokens don't expire, so this can be called at any time to get
        fresh OAuth tokens without re-entering the password.
        """
        result = AuthResult(email=email, method=AuthMethod.MASTER_TOKEN)
        result.master_token = master_token

        try:
            import gpsoauth
        except ImportError:
            result.errors.append("gpsoauth not installed")
            return result

        for scope in (scopes or _CORE_SCOPES):
            try:
                oauth_resp = gpsoauth.perform_oauth(
                    email=email,
                    master_token=master_token,
                    android_id=android_id,
                    service=scope,
                    app="com.google.android.gms",
                    client_sig=_CLIENT_SIG,
                    sdk_version=34,
                )
                if "Auth" in oauth_resp:
                    result.tokens[scope] = oauth_resp["Auth"]
                    expiry = oauth_resp.get("Expiry")
                    if expiry:
                        result.token_expiry[scope] = int(expiry)
            except Exception as exc:
                result.warnings.append(f"Refresh failed for {scope}: {exc}")

        result.success = bool(result.tokens)
        return result

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _make_synthetic_tokens(email: str) -> Dict[str, str]:
        """Generate synthetic (fake) tokens as a last-resort fallback.

        These tokens make the account *appear* in Android Settings → Accounts
        but will fail server-side validation when Google apps attempt to sync.
        They are identical to what the legacy GoogleAccountInjector generates.
        """
        sid = secrets.token_hex(60)
        lsid = secrets.token_hex(60)
        tokens: Dict[str, str] = {
            "com.google": f"ya29.{secrets.token_urlsafe(80)}",
            "SID": sid,
            "LSID": lsid,
        }
        for scope in _CORE_SCOPES:
            tokens[scope] = f"ya29.{secrets.token_urlsafe(80)}"
        return tokens

    @staticmethod
    def _generate_totp(secret: str) -> str:
        """Generate a 6-digit TOTP code from a base32 secret.

        Uses the standard RFC 6238 algorithm (SHA-1, 30-second window).
        """
        import base64
        import hashlib
        import hmac
        import struct

        try:
            key = base64.b32decode(secret.upper().replace(" ", ""))
        except Exception:
            logger.warning("Invalid TOTP secret — cannot generate OTP")
            return ""

        ts = int(time.time()) // 30
        msg = struct.pack(">Q", ts)
        mac = hmac.new(key, msg, hashlib.sha1).digest()
        offset = mac[-1] & 0x0F
        code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{code % 1000000:06d}"
