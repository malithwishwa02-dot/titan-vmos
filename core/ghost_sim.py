"""
Titan V12 — Ghost SIM v2.0
Virtual modem emulation for Cuttlefish Android VMs.

Makes TelephonyManager report a real SIM card with:
  - Valid IMSI, ICCID, MSISDN (phone number)
  - Carrier operator info matching CarrierProfile
  - Signal strength fluctuations (2-5 bars, jitter)
  - Cell tower IDs matching GPS location
  - Network registration state (LTE/5G)

Architecture:
  1. RIL property injection via resetprop (operator/SIM state props)
  2. Modem configuration via radio.conf patching
  3. Virtual modem daemon via Cuttlefish modem_simulator config
  4. Signal strength fluctuation daemon
  5. Cell tower ID generation from GPS coordinates

Prerequisites:
  - ADB root access
  - resetprop binary available
  - Cuttlefish modem_simulator running (default in CVD)

Usage:
    sim = GhostSIM(adb_target="127.0.0.1:6520")
    sim.configure(carrier="tmobile_us", phone="+12125551234", location="nyc")
    sim.start_signal_daemon()
"""

import hashlib
import logging
import math
import os
import random
import secrets
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from adb_utils import adb_shell, ensure_adb_root, adb as _adb
from device_presets import CARRIERS, LOCATIONS, CarrierProfile

logger = logging.getLogger("titan.ghost-sim")


# ═══════════════════════════════════════════════════════════════════════
# CELL TOWER DATABASE (by city/region)
# ═══════════════════════════════════════════════════════════════════════

CELL_TOWERS: Dict[str, List[Dict[str, Any]]] = {
    "nyc": [
        {"lac": 1001, "cid": 25631, "lat": 40.7128, "lon": -74.0060, "type": "LTE", "pci": 121},
        {"lac": 1001, "cid": 25632, "lat": 40.7580, "lon": -73.9855, "type": "LTE", "pci": 122},
        {"lac": 1002, "cid": 25700, "lat": 40.7831, "lon": -73.9712, "type": "LTE", "pci": 203},
        {"lac": 1002, "cid": 25701, "lat": 40.7484, "lon": -73.9857, "type": "NR", "pci": 401},
        {"lac": 1003, "cid": 25800, "lat": 40.6892, "lon": -74.0445, "type": "LTE", "pci": 305},
    ],
    "la": [
        {"lac": 2001, "cid": 33100, "lat": 34.0522, "lon": -118.2437, "type": "LTE", "pci": 150},
        {"lac": 2001, "cid": 33101, "lat": 34.0195, "lon": -118.4912, "type": "LTE", "pci": 151},
        {"lac": 2002, "cid": 33200, "lat": 34.1478, "lon": -118.1445, "type": "NR", "pci": 420},
        {"lac": 2002, "cid": 33201, "lat": 33.9425, "lon": -118.4081, "type": "LTE", "pci": 250},
    ],
    "london": [
        {"lac": 3001, "cid": 41000, "lat": 51.5074, "lon": -0.1278, "type": "LTE", "pci": 180},
        {"lac": 3001, "cid": 41001, "lat": 51.5155, "lon": -0.1415, "type": "LTE", "pci": 181},
        {"lac": 3002, "cid": 41100, "lat": 51.5033, "lon": -0.0195, "type": "NR", "pci": 500},
    ],
    "berlin": [
        {"lac": 4001, "cid": 52000, "lat": 52.5200, "lon": 13.4050, "type": "LTE", "pci": 210},
        {"lac": 4001, "cid": 52001, "lat": 52.5163, "lon": 13.3777, "type": "LTE", "pci": 211},
    ],
    "paris": [
        {"lac": 5001, "cid": 63000, "lat": 48.8566, "lon": 2.3522, "type": "LTE", "pci": 300},
        {"lac": 5001, "cid": 63001, "lat": 48.8584, "lon": 2.2945, "type": "NR", "pci": 510},
    ],
}

# Default tower for unknown locations
DEFAULT_TOWERS = [
    {"lac": 9001, "cid": 99000, "lat": 40.7128, "lon": -74.0060, "type": "LTE", "pci": 100},
]


@dataclass
class SIMConfig:
    """Configuration state for a Ghost SIM instance."""
    imsi: str = ""
    iccid: str = ""
    msisdn: str = ""
    mcc: str = "310"
    mnc: str = "260"
    carrier_name: str = "T-Mobile"
    carrier_iso: str = "us"
    network_type: str = "LTE"
    phone_type: int = 1  # 1=GSM, 2=CDMA
    sim_state: str = "READY"
    data_state: str = "CONNECTED"
    signal_bars: int = 4
    signal_dbm: int = -85
    lac: int = 0
    cid: int = 0
    pci: int = 0


class GhostSIM:
    """Virtual SIM card emulation for Cuttlefish VMs."""

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._config = SIMConfig()
        self._signal_thread: Optional[threading.Thread] = None
        self._signal_running = False
        self._rng = random.Random()

    def configure(self, carrier: str = "tmobile_us",
                  phone: str = "+12125551234",
                  location: str = "nyc",
                  imsi: Optional[str] = None,
                  iccid: Optional[str] = None) -> SIMConfig:
        """Configure Ghost SIM with carrier, phone number, and location.
        
        Sets all telephony properties to make TelephonyManager report
        a genuinely activated SIM card.
        """
        ensure_adb_root(self.target)

        # Resolve carrier profile
        carrier_profile = CARRIERS.get(carrier)
        if not carrier_profile:
            logger.warning(f"Unknown carrier '{carrier}', using T-Mobile US")
            carrier_profile = CARRIERS.get("tmobile_us", CarrierProfile(
                name="T-Mobile", mcc="310", mnc="260", iso="us",
                spn="T-Mobile", gid1="", apn="fast.t-mobile.com"))

        # Generate IMSI if not provided
        if not imsi:
            imsi = self._generate_imsi(carrier_profile)
        if not iccid:
            iccid = self._generate_iccid(carrier_profile)

        # Select nearest cell tower
        towers = CELL_TOWERS.get(location, DEFAULT_TOWERS)
        tower = self._rng.choice(towers)

        self._config = SIMConfig(
            imsi=imsi,
            iccid=iccid,
            msisdn=phone,
            mcc=carrier_profile.mcc,
            mnc=carrier_profile.mnc,
            carrier_name=carrier_profile.name,
            carrier_iso=carrier_profile.iso,
            network_type=tower.get("type", "LTE"),
            sim_state="READY",
            data_state="CONNECTED",
            signal_bars=self._rng.randint(3, 5),
            signal_dbm=self._rng.randint(-95, -65),
            lac=tower["lac"],
            cid=tower["cid"],
            pci=tower.get("pci", 100),
        )

        # Apply all telephony properties
        self._inject_ril_props()
        self._configure_modem()
        self._inject_cell_identity()

        logger.info(f"Ghost SIM configured: {carrier_profile.name} "
                    f"IMSI={imsi[:6]}*** MSISDN={phone}")
        return self._config

    def _inject_ril_props(self):
        """Inject all RIL/telephony system properties via resetprop + setprop."""
        cfg = self._config

        props = {
            # SIM identity
            "gsm.sim.state": cfg.sim_state,
            "gsm.sim.operator.alpha": cfg.carrier_name,
            "gsm.sim.operator.numeric": f"{cfg.mcc}{cfg.mnc}",
            "gsm.sim.operator.iso-country": cfg.carrier_iso,
            "gsm.operator.alpha": cfg.carrier_name,
            "gsm.operator.numeric": f"{cfg.mcc}{cfg.mnc}",
            "gsm.operator.iso-country": cfg.carrier_iso,
            "gsm.network.type": cfg.network_type,
            "gsm.current.phone-type": str(cfg.phone_type),
            "gsm.nitz.time": str(int(time.time() * 1000)),

            # SIM presence — critical for TelephonyManager
            "persist.sys.cloud.modem.config": "1",
            "persist.sys.cloud.modem.imei": "",  # Set separately by anomaly_patcher
            "persist.sys.cloud.modem.iccid": cfg.iccid,
            "persist.sys.cloud.modem.imsi": cfg.imsi,
            "persist.sys.cloud.modem.msisdn": cfg.msisdn,
            "persist.sys.cloud.modem.operator": cfg.carrier_name,
            "persist.sys.cloud.modem.mcc": cfg.mcc,
            "persist.sys.cloud.modem.mnc": cfg.mnc,

            # Signal state
            "gsm.signal_strength": str(cfg.signal_dbm),
            "gsm.signal_strength.bars": str(cfg.signal_bars),

            # Data connection
            "gsm.data.state": cfg.data_state,
            "gsm.data.network.type": cfg.network_type,
            "gsm.defaultpdpcontext.active": "true",

            # Modem/radio
            "persist.radio.multisim.config": "ssss",
            "ro.telephony.default_network": "13",  # LTE/WCDMA/GSM
            "ril.subscription.types": "NV,RUIM",
            "persist.radio.custom_ecc": "1",
            "ro.com.android.dataroaming": "false",

            # Carrier features
            "persist.carrier.volte_avail": "1",
            "persist.carrier.vonr_avail": "1",
            "persist.carrier.wfc_avail": "1",
        }

        # Batch inject via single shell command (performance: 10-15 props per call)
        batch_cmds = []
        for prop, val in props.items():
            if val:
                batch_cmds.append(f"setprop {prop} '{val}'")

        # Split into batches of 15
        for i in range(0, len(batch_cmds), 15):
            batch = " && ".join(batch_cmds[i:i+15])
            adb_shell(self.target, batch, timeout=15)

        logger.info(f"  RIL props injected: {len(props)} properties")

    def _configure_modem(self):
        """Configure Cuttlefish modem_simulator for realistic responses.
        
        Patches the modem config to return proper AT command responses:
        +CIMI (IMSI), +CNUM (MSISDN), +COPS (operator), +CSQ (signal).
        """
        cfg = self._config

        # Cuttlefish modem_simulator reads from modem_simulator config directory
        modem_config_dir = "/data/vendor/modem_simulator/files/iccprofile_for_sim0"
        backup_dir = "/data/vendor/modem_simulator/files"

        # AT+CIMI response (IMSI query)
        adb_shell(self.target,
            f'mkdir -p {modem_config_dir} 2>/dev/null; '
            f'echo "AT+CIMI" > {backup_dir}/cimi_response.txt; '
            f'echo "{cfg.imsi}" >> {backup_dir}/cimi_response.txt; '
            f'echo "OK" >> {backup_dir}/cimi_response.txt',
            timeout=10)

        # AT+CNUM response (subscriber number)
        adb_shell(self.target,
            f'echo "AT+CNUM" > {backup_dir}/cnum_response.txt; '
            f'echo "+CNUM: \\"{cfg.carrier_name}\\",\\"{cfg.msisdn}\\",129" >> {backup_dir}/cnum_response.txt; '
            f'echo "OK" >> {backup_dir}/cnum_response.txt',
            timeout=10)

        # AT+COPS response (operator selection)
        adb_shell(self.target,
            f'echo "AT+COPS?" > {backup_dir}/cops_response.txt; '
            f'echo "+COPS: 0,0,\\"{cfg.carrier_name}\\",7" >> {backup_dir}/cops_response.txt; '
            f'echo "OK" >> {backup_dir}/cops_response.txt',
            timeout=10)

        logger.info("  Modem simulator configured")

    def _inject_cell_identity(self):
        """Inject cell tower identity matching GPS location."""
        cfg = self._config

        cell_props = {
            "persist.titan.cell.lac": str(cfg.lac),
            "persist.titan.cell.cid": str(cfg.cid),
            "persist.titan.cell.pci": str(cfg.pci),
            "persist.titan.cell.mcc": cfg.mcc,
            "persist.titan.cell.mnc": cfg.mnc,
            "persist.titan.cell.type": cfg.network_type,
        }

        batch = " && ".join([f"setprop {k} '{v}'" for k, v in cell_props.items()])
        adb_shell(self.target, batch, timeout=10)
        logger.info(f"  Cell identity: LAC={cfg.lac} CID={cfg.cid} PCI={cfg.pci}")

    def start_signal_daemon(self, interval_s: float = 30.0):
        """Start background daemon that fluctuates signal strength.
        
        Real phones show 2-5 bars with jitter. Static signal strength
        is an emulator fingerprint used by banking apps.
        """
        if self._signal_running:
            logger.info("Signal daemon already running")
            return

        self._signal_running = True
        self._signal_thread = threading.Thread(
            target=self._signal_loop,
            args=(interval_s,),
            daemon=True,
            name=f"ghost-sim-signal-{self.target}",
        )
        self._signal_thread.start()
        logger.info(f"Signal fluctuation daemon started (interval={interval_s}s)")

    def stop_signal_daemon(self):
        """Stop signal fluctuation daemon."""
        self._signal_running = False
        if self._signal_thread:
            self._signal_thread.join(timeout=5)
        logger.info("Signal daemon stopped")

    def _signal_loop(self, interval_s: float):
        """Background loop that varies signal strength realistically."""
        base_dbm = self._config.signal_dbm
        while self._signal_running:
            try:
                # Gaussian jitter around base signal: ±8 dBm
                jitter = self._rng.gauss(0, 4.0)
                new_dbm = max(-110, min(-50, int(base_dbm + jitter)))

                # Convert dBm to bars (carrier-standard mapping)
                if new_dbm >= -75:
                    bars = 5
                elif new_dbm >= -85:
                    bars = 4
                elif new_dbm >= -95:
                    bars = 3
                elif new_dbm >= -105:
                    bars = 2
                else:
                    bars = 1

                batch = (
                    f"setprop gsm.signal_strength '{new_dbm}' && "
                    f"setprop gsm.signal_strength.bars '{bars}'"
                )
                adb_shell(self.target, batch, timeout=5)
                time.sleep(interval_s)

            except Exception as e:
                logger.debug(f"Signal daemon error: {e}")
                time.sleep(interval_s * 2)

    # ─── GENERATORS ──────────────────────────────────────────────────

    def _generate_imsi(self, carrier: CarrierProfile) -> str:
        """Generate valid IMSI: MCC(3) + MNC(2-3) + MSIN(9-10) = 15 digits."""
        mcc = carrier.mcc
        mnc = carrier.mnc
        msin_len = 15 - len(mcc) - len(mnc)
        msin = "".join([str(self._rng.randint(0, 9)) for _ in range(msin_len)])
        return f"{mcc}{mnc}{msin}"

    def _generate_iccid(self, carrier: CarrierProfile) -> str:
        """Generate valid ICCID with Luhn check digit.
        
        Format: 89 (telecom) + CC(2-3) + MNC(2-3) + individual(variable) + check
        Total: 19-20 digits
        """
        # Major Industry Identifier (89 = telecom)
        prefix = f"89{carrier.mcc[:2]}{carrier.mnc}"
        body_len = 18 - len(prefix)
        body = "".join([str(self._rng.randint(0, 9)) for _ in range(body_len)])
        partial = prefix + body

        # Luhn check digit
        digits = [int(d) for d in partial]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 0:
                doubled = d * 2
                total += doubled - 9 if doubled > 9 else doubled
            else:
                total += d
        check = (10 - (total % 10)) % 10

        return partial + str(check)

    def get_status(self) -> Dict[str, Any]:
        """Get current Ghost SIM status."""
        return {
            "configured": bool(self._config.imsi),
            "carrier": self._config.carrier_name,
            "mcc_mnc": f"{self._config.mcc}{self._config.mnc}",
            "sim_state": self._config.sim_state,
            "network_type": self._config.network_type,
            "signal_bars": self._config.signal_bars,
            "signal_dbm": self._config.signal_dbm,
            "cell": {
                "lac": self._config.lac,
                "cid": self._config.cid,
                "pci": self._config.pci,
            },
            "daemon_running": self._signal_running,
        }
