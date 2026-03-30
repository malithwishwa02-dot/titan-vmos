"""
Titan V13 — VMOS File Pusher

Handles file transfer to VMOS Cloud devices via chunked base64 encoding.
VMOS devices have limited shell capabilities, so we must:
1. Encode files as base64
2. Push in chunks (avoid command length limits)
3. Decode on device
4. Set correct permissions and SELinux context

Usage:
    pusher = VMOSFilePusher(vmos_api)
    
    # Push database file
    success = await pusher.push_file(
        db_bytes,
        "/data/system_ce/0/accounts_ce.db",
        owner="system:system",
        mode="600",
        selinux_context="u:object_r:accounts_data_file:s0"
    )
"""

import asyncio
import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger("titan.vmos-file-pusher")

CHUNK_SIZE = 4096
MAX_RETRIES = 3
COMMAND_DELAY = 3.0  # VMOS requires 3+ seconds between commands


@dataclass
class PushResult:
    """Result of file push operation."""
    success: bool = False
    path: str = ""
    size: int = 0
    checksum: str = ""
    error: str = ""
    retries: int = 0


class VMOSFilePusher:
    """
    Push files to VMOS Cloud devices via chunked base64.
    
    VMOS Cloud devices have specific limitations:
    - No direct file upload API
    - Shell commands have length limits (~4KB)
    - Commands must be spaced 3+ seconds apart
    - /system is read-only (dm-protected)
    """

    def __init__(self, vmos_api, pad_code: str):
        """
        Initialize file pusher.
        
        Args:
            vmos_api: VMOSCloudAPI instance
            pad_code: Device PAD code
        """
        self.api = vmos_api
        self.pad_code = pad_code
        self._last_command_time = 0

    async def _wait_for_rate_limit(self):
        """Ensure minimum delay between commands."""
        elapsed = time.time() - self._last_command_time
        if elapsed < COMMAND_DELAY:
            await asyncio.sleep(COMMAND_DELAY - elapsed)
        self._last_command_time = time.time()

    async def _execute(self, cmd: str, timeout: int = 30) -> Tuple[bool, str]:
        """Execute shell command on device with rate limiting."""
        await self._wait_for_rate_limit()
        
        try:
            result = await self.api.async_adb_cmd(self.pad_code, cmd, timeout=timeout)
            
            if result.get("status") == -1:
                logger.warning(f"Command returned status=-1, device may need restart")
                return False, "Device command failed"
            
            output = result.get("data", {}).get("output", "")
            return True, output
            
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return False, str(e)

    async def push_file(self,
                        data: bytes,
                        target_path: str,
                        owner: str = "system:system",
                        mode: str = "660",
                        selinux_context: Optional[str] = None) -> PushResult:
        """
        Push file to VMOS device via chunked base64.
        
        Args:
            data: File content as bytes
            target_path: Absolute path on device
            owner: Owner in user:group format
            mode: File permissions (e.g., "660")
            selinux_context: SELinux context or None for restorecon
        
        Returns:
            PushResult with operation status
        """
        result = PushResult(path=target_path, size=len(data))
        result.checksum = hashlib.md5(data).hexdigest()
        
        logger.info(f"Pushing {len(data)} bytes to {target_path}")
        
        b64_data = base64.b64encode(data).decode('ascii')
        
        staging_path = f"/sdcard/.titan_staging_{hashlib.md5(target_path.encode()).hexdigest()[:8]}"
        b64_path = f"{staging_path}.b64"
        
        ok, _ = await self._execute(f"rm -f {b64_path} {staging_path}")
        
        chunks = [b64_data[i:i+CHUNK_SIZE] for i in range(0, len(b64_data), CHUNK_SIZE)]
        logger.info(f"Transferring {len(chunks)} chunks...")
        
        for i, chunk in enumerate(chunks):
            for retry in range(MAX_RETRIES):
                ok, output = await self._execute(f"echo -n '{chunk}' >> {b64_path}")
                if ok:
                    break
                logger.warning(f"Chunk {i+1}/{len(chunks)} failed, retry {retry+1}")
                result.retries += 1
                await asyncio.sleep(1)
            else:
                result.error = f"Failed to transfer chunk {i+1}"
                logger.error(result.error)
                return result
            
            if (i + 1) % 10 == 0:
                logger.debug(f"Transferred {i+1}/{len(chunks)} chunks")
        
        ok, _ = await self._execute(f"base64 -d {b64_path} > {staging_path}")
        if not ok:
            result.error = "Base64 decode failed"
            return result
        
        ok, size_output = await self._execute(f"stat -c %s {staging_path} 2>/dev/null || wc -c < {staging_path}")
        try:
            actual_size = int(size_output.strip().split()[0])
            if actual_size != len(data):
                logger.warning(f"Size mismatch: expected {len(data)}, got {actual_size}")
        except:
            pass
        
        target_dir = os.path.dirname(target_path)
        await self._execute(f"mkdir -p {target_dir}")
        
        ok, _ = await self._execute(f"cp {staging_path} {target_path}")
        if not ok:
            result.error = f"Failed to copy to {target_path}"
            return result
        
        await self._execute(f"chown {owner} {target_path}")
        await self._execute(f"chmod {mode} {target_path}")
        
        if selinux_context:
            await self._execute(f"chcon {selinux_context} {target_path}")
        else:
            await self._execute(f"restorecon {target_path}")
        
        await self._execute(f"rm -f {b64_path} {staging_path}")
        
        result.success = True
        logger.info(f"Successfully pushed {target_path}")
        
        return result

    async def push_xml_file(self,
                            xml_content: str,
                            target_path: str,
                            owner: str = "system:system",
                            mode: str = "660") -> PushResult:
        """
        Push XML shared preferences file.
        
        Args:
            xml_content: XML content as string
            target_path: Absolute path on device
            owner: Owner in user:group format
            mode: File permissions
        
        Returns:
            PushResult with operation status
        """
        return await self.push_file(
            xml_content.encode('utf-8'),
            target_path,
            owner=owner,
            mode=mode
        )

    async def push_database(self,
                            db_bytes: bytes,
                            target_path: str,
                            app_uid: str = "system") -> PushResult:
        """
        Push SQLite database file with correct permissions.
        
        Args:
            db_bytes: Database file bytes
            target_path: Absolute path on device
            app_uid: App UID (e.g., "u0_a36" for GMS)
        
        Returns:
            PushResult with operation status
        """
        selinux_map = {
            "accounts_ce.db": "u:object_r:accounts_data_file:s0",
            "accounts_de.db": "u:object_r:accounts_data_file:s0",
            "tapandpay.db": "u:object_r:app_data_file:s0",
            "library.db": "u:object_r:app_data_file:s0",
        }
        
        filename = os.path.basename(target_path)
        selinux_context = selinux_map.get(filename)
        
        if "system_ce" in target_path or "system_de" in target_path:
            owner = "system:system"
            mode = "600"
        else:
            owner = f"{app_uid}:{app_uid}"
            mode = "660"
        
        result = await self.push_file(
            db_bytes,
            target_path,
            owner=owner,
            mode=mode,
            selinux_context=selinux_context
        )
        
        if result.success:
            wal_path = f"{target_path}-wal"
            shm_path = f"{target_path}-shm"
            await self._execute(f"rm -f {wal_path} {shm_path}")
        
        return result

    async def verify_file(self, path: str, expected_checksum: str) -> bool:
        """
        Verify file exists and matches expected checksum.
        
        Args:
            path: File path on device
            expected_checksum: Expected MD5 checksum
        
        Returns:
            True if file exists and checksum matches
        """
        ok, output = await self._execute(f"md5sum {path} 2>/dev/null | cut -d' ' -f1")
        if ok and output.strip() == expected_checksum:
            return True
        return False

    async def backup_file(self, path: str) -> Optional[str]:
        """
        Create backup of existing file.
        
        Args:
            path: File path to backup
        
        Returns:
            Backup path or None if backup failed
        """
        backup_path = f"{path}.titan_backup_{int(time.time())}"
        ok, _ = await self._execute(f"cp {path} {backup_path} 2>/dev/null")
        if ok:
            return backup_path
        return None


class SyncVMOSFilePusher:
    """
    Synchronous wrapper for VMOSFilePusher.
    
    Use this when you can't use async/await.
    """

    def __init__(self, vmos_api, pad_code: str):
        self._async_pusher = VMOSFilePusher(vmos_api, pad_code)
        self._loop = None

    def _get_loop(self):
        if self._loop is None:
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def push_file(self, *args, **kwargs) -> PushResult:
        """Synchronous push_file."""
        return self._get_loop().run_until_complete(
            self._async_pusher.push_file(*args, **kwargs)
        )

    def push_database(self, *args, **kwargs) -> PushResult:
        """Synchronous push_database."""
        return self._get_loop().run_until_complete(
            self._async_pusher.push_database(*args, **kwargs)
        )

    def push_xml_file(self, *args, **kwargs) -> PushResult:
        """Synchronous push_xml_file."""
        return self._get_loop().run_until_complete(
            self._async_pusher.push_xml_file(*args, **kwargs)
        )


def build_shared_prefs_xml(prefs: dict, package: str = "") -> str:
    """
    Build Android SharedPreferences XML from dict.
    
    Args:
        prefs: Dictionary of preferences
        package: Package name (optional, for header)
    
    Returns:
        XML string
    """
    lines = ["<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"]
    lines.append("<map>")
    
    for key, value in prefs.items():
        if isinstance(value, bool):
            lines.append(f'    <boolean name="{key}" value="{str(value).lower()}" />')
        elif isinstance(value, int):
            lines.append(f'    <int name="{key}" value="{value}" />')
        elif isinstance(value, float):
            lines.append(f'    <float name="{key}" value="{value}" />')
        elif isinstance(value, (list, set)):
            lines.append(f'    <set name="{key}">')
            for item in value:
                lines.append(f'        <string>{item}</string>')
            lines.append('    </set>')
        else:
            escaped = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f'    <string name="{key}">{escaped}</string>')
    
    lines.append("</map>")
    return "\n".join(lines)


def build_coin_xml(email: str, card_last_four: str = "") -> str:
    """
    Build COIN.xml for Google Pay zero-auth configuration.
    
    Implements the 8-Flag Zero-Auth Bitmask from V3 Nexus blueprint:
    - purchase_requires_auth: false
    - require_purchase_auth: false
    - one_touch_enabled: true
    - biometric_payment_enabled: true
    - PAYMENTS_ZERO_AUTH_ENABLED: true
    + 3 additional coherence flags
    
    Args:
        email: Google account email
        card_last_four: Last 4 digits of card (optional)
    
    Returns:
        XML string
    """
    prefs = {
        # === 8-FLAG ZERO-AUTH BITMASK (V3 Nexus) ===
        "purchase_requires_auth": False,           # Flag 1: Skip purchase auth
        "require_purchase_auth": False,            # Flag 2: Redundant auth bypass
        "one_touch_enabled": True,                 # Flag 3: One-tap purchasing
        "biometric_payment_enabled": True,         # Flag 4: Biometric bypass
        "PAYMENTS_ZERO_AUTH_ENABLED": True,        # Flag 5: Master zero-auth flag
        "device_auth_not_required": True,          # Flag 6: Device auth bypass
        "skip_challenge_on_payment": True,         # Flag 7: Skip 3DS challenge
        "frictionless_checkout_enabled": True,     # Flag 8: Frictionless checkout
        
        # === PAYMENT STATE FLAGS ===
        "PAYMENTS_DEVICE_AUTHENTICATOR_ENABLED": False,
        "GPay_SecureElement_Check": False,
        "PAYMENTS_CARD_TOKEN_LAST_REFRESH": "0",
        "PAYMENTS_CARD_TOKEN_COUNT": 1 if card_last_four else 0,
        
        # === ACCOUNT BINDING ===
        "account_name": email,
        "billing_user_consent": True,
        "billing_setup_complete": True,
        "play_billing_v2_enabled": True,
        "zero_auth_opt_in": True,
        "wallet_provisioned": True,
        "payment_method_synced": True,
    }
    
    if card_last_four:
        prefs["default_instrument_last_four"] = card_last_four
        prefs["has_default_instrument"] = True
        prefs["default_payment_instrument_token"] = f"token_{card_last_four}"
    
    return build_shared_prefs_xml(prefs)


def build_finsky_xml(email: str) -> str:
    """
    Build finsky.xml for Play Store account binding.
    
    Args:
        email: Google account email
    
    Returns:
        XML string
    """
    prefs = {
        "setup_done": True,
        "setup_wizard_has_run": True,
        "account": email,
        "logged_in": True,
        "auto_update_enabled": True,
        "content_rating": "PEGI 18",
        "download_preferred_network_type": 0,  # Any network
        "first_account_name": email,
        "gls_logged_in": True,
    }
    return build_shared_prefs_xml(prefs)


def build_billing_xml(email: str) -> str:
    """
    Build billing.xml for Play Store billing state.
    
    Args:
        email: Google account email
    
    Returns:
        XML string
    """
    prefs = {
        "billing_account": email,
        "billing_enabled": True,
        "zero_auth_enabled": True,
        "device_auth_required": False,
        "fingerprint_auth_enabled": False,
        "last_billing_refresh": int(time.time() * 1000),
    }
    return build_shared_prefs_xml(prefs)


def build_gmail_xml(email: str, order_ids: list = None) -> str:
    """
    Build Gmail SharedPreferences for receipt coherence.
    
    Cross-Store Coherence (V3 Nexus Blueprint Section 4):
    Receipts: Email metadata referencing Order IDs (GPA.XXXX-XXXX-XXXX-XXXXX)
    
    Args:
        email: Google account email
        order_ids: List of Play Store order IDs for receipt coherence
    
    Returns:
        XML string
    """
    import secrets
    
    now_ms = int(time.time() * 1000)
    
    prefs = {
        # Account binding
        "account_name": email,
        "account_type": "com.google",
        "sync_enabled": True,
        "last_sync_time": now_ms,
        
        # Gmail state
        "gmail_version": "2024.03.10.624953426",
        "inbox_unread_count": 0,
        "last_notification_id": secrets.token_hex(8),
        
        # Receipt coherence - cached email subjects
        "cached_email_count": len(order_ids) if order_ids else 0,
        "has_purchase_receipts": bool(order_ids),
    }
    
    # Add order ID references for coherence
    if order_ids:
        for i, order_id in enumerate(order_ids[:10]):  # Max 10 receipts
            prefs[f"receipt_order_{i}"] = order_id
            prefs[f"receipt_subject_{i}"] = f"Your Google Play Order Receipt ({order_id})"
        prefs["receipt_count"] = len(order_ids[:10])
    
    return build_shared_prefs_xml(prefs)


def build_chrome_history_coherence_xml(merchants: list = None) -> str:
    """
    Build Chrome SharedPreferences for browsing coherence.
    
    Cross-Store Coherence (V3 Nexus Blueprint Section 4):
    Browsing: History and Cookies for merchant domains.
    
    Args:
        merchants: List of merchant domains visited
    
    Returns:
        XML string
    """
    default_merchants = [
        "amazon.com", "starbucks.com", "target.com", 
        "netflix.com", "uber.com", "doordash.com"
    ]
    
    merchant_list = merchants or default_merchants
    now_ms = int(time.time() * 1000)
    
    prefs = {
        "browsing_history_enabled": True,
        "cookies_enabled": True,
        "last_sync_time": now_ms,
        "visited_domains_count": len(merchant_list),
    }
    
    # Add merchant domain references
    for i, domain in enumerate(merchant_list):
        prefs[f"visited_domain_{i}"] = domain
        prefs[f"last_visit_{i}"] = now_ms - (i * 86400000)  # Staggered visits
    
    return build_shared_prefs_xml(prefs)


if __name__ == "__main__":
    coin_xml = build_coin_xml("test@gmail.com", "4242")
    print("COIN.xml:")
    print(coin_xml)
    print()
    
    finsky_xml = build_finsky_xml("test@gmail.com")
    print("finsky.xml:")
    print(finsky_xml)
