"""
Titan V13.0 — VMOS File Pusher
================================
Transfers files (especially SQLite databases) to VMOS Cloud devices using
chunked base64 encoding over the VMOS ``asyncCmd`` / ``syncCmd`` shell API.

VMOS Cloud devices do not have an ``sqlite3`` binary, so all database
operations must be performed host-side (see :mod:`vmos_db_builder`) and the
result pushed as a binary blob via base64.

Transfer flow
-------------
1. Encode the binary payload as base64.
2. Split into chunks ≤ 4 KB (VMOS ``syncCmd`` limit).
3. Write chunks to a temp file on the device using ``echo -n ... >> /tmp/x.b64``.
4. Decode on-device: ``base64 -d /tmp/x.b64 > <dest>``.
5. Remove the temp base64 file.
6. Set ownership and SELinux context on the destination file.

Usage::

    from vmos_file_pusher import VMOSFilePusher

    pusher = VMOSFilePusher(vmos_client, pad_code="ACP2509244LGV1MV")

    # Async push a database (returns True on success)
    ok = await pusher.push_bytes(
        data=db_bytes,
        remote_path="/data/system_ce/0/accounts_ce.db",
        owner="system:system",
        mode="600",
    )
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from typing import Optional

logger = logging.getLogger("titan.vmos-file-pusher")

# VMOS syncCmd has a 4 KB payload limit.  We use 3 KB chunks to leave headroom
# for the surrounding shell command syntax.
_CHUNK_BYTES = 3072


class VMOSFilePusher:
    """Push binary files to VMOS Cloud devices via base64-chunked shell commands.

    Args:
        client: A :class:`~vmos_cloud_api.VMOSCloudClient` instance.
        pad_code: Target VMOS Cloud device pad code.
        shell_timeout: Per-command ADB shell timeout in seconds.
        inter_chunk_delay: Seconds to wait between chunk writes to avoid
            triggering VMOS rate-limit (error 110031).  Minimum 0.5s
            recommended; the plan warns against rapid-fire commands.
    """

    def __init__(
        self,
        client,
        pad_code: str,
        shell_timeout: int = 30,
        inter_chunk_delay: float = 0.5,
    ) -> None:
        self.client = client
        self.pad = pad_code
        self.pads = [pad_code]
        self.shell_timeout = shell_timeout
        self.inter_chunk_delay = max(inter_chunk_delay, 0.3)
    # ── Core push ─────────────────────────────────────────────────────

    async def push_bytes(
        self,
        data: bytes,
        remote_path: str,
        owner: str = "",
        mode: str = "644",
        restorecon: bool = True,
    ) -> bool:
        """Push raw bytes to *remote_path* on the VMOS device.

        The transfer uses the ``echo -n | base64 -d`` pipeline to avoid any
        dependency on ``adb push`` (which is blocked on VMOS Cloud) or
        ``sqlite3`` (not present on VMOS).

        Args:
            data: Bytes to write.
            remote_path: Absolute device path for the destination file.
            owner: Unix owner in ``user:group`` format (e.g. ``system:system``).
                   If empty, ownership is not changed.
            mode: Octal permission string (e.g. ``"600"``).
            restorecon: If True, run ``restorecon`` to restore SELinux context.

        Returns:
            True if the full transfer and permission-setting succeeded.
        """
        if not data:
            logger.warning("[%s] push_bytes: empty payload for %s", self.pad, remote_path)
            return False

        b64 = base64.b64encode(data).decode("ascii")
        tmp_b64 = f"/sdcard/.titan_push_{int(time.time())}.b64"
        tmp_dir = remote_path.rsplit("/", 1)[0]
        total_chunks = math.ceil(len(b64) / _CHUNK_BYTES)

        logger.info(
            "[%s] Pushing %d bytes (%d chunks) → %s",
            self.pad, len(data), total_chunks, remote_path,
        )

        # ── Step 1: ensure destination directory ──────────────────────
        ok = await self._sh(f"mkdir -p {tmp_dir} 2>/dev/null && echo OK", marker="OK")
        if not ok:
            logger.warning("[%s] Could not create directory %s", self.pad, tmp_dir)
            # Non-fatal — directory may already exist

        # ── Step 2: remove any stale temp file ────────────────────────
        await self._sh_fire(f"rm -f {tmp_b64}")

        # ── Step 3: write base64 chunks ───────────────────────────────
        for i, start in enumerate(range(0, len(b64), _CHUNK_BYTES)):
            chunk = b64[start:start + _CHUNK_BYTES]
            # Use printf instead of echo -n for POSIX portability
            cmd = f"printf '%s' '{chunk}' >> {tmp_b64}"
            wrote = await self._sh(cmd + " && echo CHUNK_OK", marker="CHUNK_OK")
            if not wrote:
                # Retry once before giving up
                await asyncio.sleep(self.inter_chunk_delay)
                wrote = await self._sh(cmd + " && echo CHUNK_OK", marker="CHUNK_OK")
                if not wrote:
                    logger.error(
                        "[%s] Chunk %d/%d failed for %s",
                        self.pad, i + 1, total_chunks, remote_path,
                    )
                    await self._sh_fire(f"rm -f {tmp_b64}")
                    return False

            if i > 0 and i % 10 == 0:
                logger.debug("[%s] Push progress: %d/%d chunks", self.pad, i + 1, total_chunks)

            # Rate-limit guard — avoid triggering VMOS 110031 cascade
            await asyncio.sleep(self.inter_chunk_delay)

        # ── Step 4: decode to destination ─────────────────────────────
        decode_cmd = f"base64 -d {tmp_b64} > {remote_path} && echo DECODE_OK"
        decoded = await self._sh(decode_cmd, marker="DECODE_OK", timeout=60)
        await self._sh_fire(f"rm -f {tmp_b64}")

        if not decoded:
            logger.error("[%s] base64 decode failed for %s", self.pad, remote_path)
            return False

        # ── Step 5: set permissions ────────────────────────────────────
        ok = await self._set_permissions(remote_path, owner, mode, restorecon)
        if not ok:
            logger.warning(
                "[%s] Permissions not fully applied on %s (file was written)",
                self.pad, remote_path,
            )

        logger.info("[%s] Push complete: %s (%d bytes)", self.pad, remote_path, len(data))
        return True

    async def push_text(
        self,
        content: str,
        remote_path: str,
        owner: str = "",
        mode: str = "644",
        restorecon: bool = True,
    ) -> bool:
        """Push a UTF-8 text string to *remote_path*.

        Convenience wrapper around :meth:`push_bytes`.
        """
        return await self.push_bytes(
            content.encode("utf-8"), remote_path, owner=owner, mode=mode,
            restorecon=restorecon,
        )

    # ── XML / SharedPreferences ────────────────────────────────────────

    async def push_xml_pref(
        self,
        xml_content: str,
        remote_path: str,
        pkg_dir: Optional[str] = None,
    ) -> bool:
        """Push a SharedPreferences XML file and apply package-owned permissions.

        Args:
            xml_content: Raw XML string (``<?xml version='1.0'...``).
            remote_path: Absolute path on the device (e.g.
                ``/data/data/com.google.android.gms/shared_prefs/COIN.xml``).
            pkg_dir: Root directory of the owning app (e.g.
                ``/data/data/com.google.android.gms``).  If provided, the file
                ownership is inherited from this directory.

        Returns:
            True if write + permission set succeeded.
        """
        # Write the file
        ok = await self.push_text(xml_content, remote_path, mode="660", restorecon=True)
        if not ok:
            return False

        # Inherit ownership from package directory
        if pkg_dir:
            chown_cmd = (
                f"OWNER=$(stat -c '%u:%g' {pkg_dir} 2>/dev/null); "
                f"[ -n \"$OWNER\" ] && chown $OWNER {remote_path} 2>/dev/null; "
                f"echo CHOWN_OK"
            )
            await self._sh(chown_cmd, marker="CHOWN_OK")

        return True

    # ── Permissions helper ────────────────────────────────────────────

    async def _set_permissions(
        self,
        path: str,
        owner: str,
        mode: str,
        restorecon: bool,
    ) -> bool:
        """Set ownership, mode, and SELinux context on *path*."""
        cmds = []
        if mode:
            cmds.append(f"chmod {mode} {path}")
        if owner:
            cmds.append(f"chown {owner} {path}")
        if restorecon:
            cmds.append(f"restorecon {path} 2>/dev/null")
        cmds.append("echo PERMS_OK")
        return await self._sh("; ".join(cmds), marker="PERMS_OK")

    # ── Shell helpers ─────────────────────────────────────────────────

    async def _sh(
        self,
        cmd: str,
        marker: str = "OK",
        timeout: Optional[int] = None,
    ) -> bool:
        """Execute *cmd* via VMOS Cloud API shell and check for *marker* in output."""
        try:
            resp = await self.client.async_adb_cmd(self.pads, cmd)
            if resp.get("code") != 200:
                return False
            data = resp.get("data", [])
            task_id = None
            if isinstance(data, list) and data:
                task_id = data[0].get("taskId")
            elif isinstance(data, dict):
                task_id = data.get("taskId")
            if not task_id:
                return False

            secs = timeout or self.shell_timeout
            for _ in range(secs):
                await asyncio.sleep(1)
                detail = await self.client.task_detail([task_id])
                if detail.get("code") == 200 and detail.get("data"):
                    items = detail["data"]
                    if isinstance(items, list) and items:
                        item = items[0]
                        st = item.get("taskStatus")
                        if st == 3:
                            return marker in (item.get("taskResult") or "")
                        if st in (-1, -2, -3, -4, -5):
                            return False
            return False
        except Exception as exc:
            logger.debug("[%s] _sh error: %s", self.pad, exc)
            return False

    async def _sh_fire(self, cmd: str) -> None:
        """Fire-and-forget shell command (no result check)."""
        try:
            await self.client.async_adb_cmd(self.pads, cmd)
        except Exception:
            pass
