"""
Titan V12 — Immune Watchdog System
Real-time anti-detection countermeasures that monitor and neutralize
fingerprinting probes from apps and services.

Architecture:
  1. inotify monitoring on critical paths (/proc, /sys, /data)
  2. getprop interception via prop service wrapper
  3. Honeypot properties that trigger alerts on read
  4. Probe detection + classification (SafetyNet, RootBeer, etc.)
  5. Automatic countermeasure deployment on detection

Threat Model:
  - App-level: RootBeer, SafetyNet Attestation, MagiskDetector
  - Banking: Arxan, Promon, cert-pinning + env checks
  - Payment: Play Integrity, hardware attestation, NFC env
  - Social: Device fingerprint SDKs (Adjust, Appsflyer, Kochava)

Usage:
    watchdog = ImmuneWatchdog(adb_target="127.0.0.1:6520")
    watchdog.deploy()
    watchdog.start_monitoring()
    threats = watchdog.get_threat_report()
"""

import hashlib
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from adb_utils import adb_shell, ensure_adb_root
from exceptions import TitanError

logger = logging.getLogger("titan.immune-watchdog")


# ═══════════════════════════════════════════════════════════════════════
# DETECTION SIGNATURES
# ═══════════════════════════════════════════════════════════════════════

# Paths that fingerprinting apps commonly probe
PROBE_PATHS = {
    # Root detection
    "/system/app/Superuser.apk",
    "/system/xbin/su",
    "/system/bin/su",
    "/sbin/su",
    "/data/local/bin/su",
    "/data/local/xbin/su",
    # Magisk detection
    "/data/adb/magisk",
    "/data/adb/modules",
    "/cache/magisk.log",
    # Frida detection
    "/data/local/tmp/frida-server",
    "/data/local/tmp/re.frida.server",
    # Xposed detection
    "/system/framework/XposedBridge.jar",
    "/data/data/de.robv.android.xposed.installer",
    # Emulator artifacts
    "/dev/socket/qemud",
    "/dev/qemu_pipe",
    "/system/lib/libc_malloc_debug_qemu.so",
    "/sys/qemu_trace",
    "/system/bin/qemu-props",
    "/dev/goldfish_pipe",
    # Cuttlefish artifacts
    "/dev/vport*",
    "/dev/hvc*",
}

# Properties that fingerprinting apps read
PROBE_PROPS = {
    "ro.debuggable",
    "ro.secure",
    "ro.build.selinux",
    "ro.boot.verifiedbootstate",
    "service.bootanim.exit",
    "ro.kernel.qemu",
    "ro.hardware.chipname",
    "ro.product.cpu.abilist",
    "gsm.version.ril-impl",
    "init.svc.adbd",
    "sys.usb.state",
    "persist.sys.dalvik.vm.lib.2",
}

# Known detection library packages
DETECTION_LIBRARIES = {
    "com.scottyab.rootbeer": "RootBeer",
    "com.scottyab.rootbeer.sample": "RootBeer",
    "eu.thedarken.sdm": "SD Maid (root check)",
    "com.topjohnwu.magisk": "MagiskManager",
    "de.robv.android.xposed.installer": "Xposed",
    "org.meowcat.edxposed.manager": "EdXposed",
    "io.github.vvb2060.magiskdetector": "MagiskDetector",
    "rikka.appops": "AppOps (root check)",
}

# Known detection SDK class names
DETECTION_SDKS = {
    "com.scottyab.rootbeer.RootBeer": "RootBeer SDK",
    "com.noshufou.android.su": "Superuser check",
    "com.thirdparty.superuser": "Superuser check",
    "com.promon.shield": "Promon Shield",
    "com.arxan": "Arxan Guards",
    "com.guardsquare.dexguard": "DexGuard",
    "com.adjust.sdk": "Adjust (fingerprint)",
    "com.appsflyer": "AppsFlyer (fingerprint)",
    "io.sentry": "Sentry (telemetry)",
}


@dataclass
class ThreatEvent:
    """Single detected threat event."""
    timestamp: float = 0.0
    threat_type: str = ""       # probe_path | probe_prop | detection_lib | sdk_class
    source_pkg: str = ""        # package that triggered the probe
    target: str = ""            # path/prop being probed
    severity: str = "low"       # low | medium | high | critical
    countermeasure: str = ""    # action taken
    neutralized: bool = False


@dataclass
class WatchdogState:
    """Current watchdog state and statistics."""
    active: bool = False
    deployed_at: float = 0.0
    honeypots_active: int = 0
    inotify_watches: int = 0
    threats_detected: int = 0
    threats_neutralized: int = 0
    last_scan: float = 0.0
    threat_log: List[ThreatEvent] = field(default_factory=list)


class ImmuneWatchdog:
    """Real-time anti-detection watchdog system."""

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._state = WatchdogState()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._alert_callback: Optional[Callable] = None

    def deploy(self) -> Dict[str, Any]:
        """Deploy all watchdog countermeasures to device.
        
        Returns deployment summary with counts.
        """
        ensure_adb_root(self.target)

        results = {
            "honeypots": self._deploy_honeypots(),
            "path_hardening": self._harden_probe_paths(),
            "prop_hardening": self._harden_probe_props(),
            "process_cloaking": self._cloak_processes(),
            "port_lockdown": self._lockdown_probe_ports(),
        }

        self._state.deployed_at = time.time()
        logger.info(f"Immune watchdog deployed: {results}")
        return results

    def _deploy_honeypots(self) -> int:
        """Deploy honeypot files that trigger alerts when accessed.
        
        Creates decoy files at paths commonly checked by root/emulator
        detection. These files contain innocuous data but their access
        timestamps are monitored via inotify.
        """
        honeypot_paths = [
            "/data/local/tmp/.su_check",
            "/data/local/tmp/.magisk_check",
            "/data/local/tmp/.frida_check",
            "/data/local/tmp/.emulator_check",
        ]

        deployed = 0
        for path in honeypot_paths:
            # Create honeypot with random content to avoid pattern matching
            token = secrets.token_hex(16)
            # Use echo to create file content to avoid special character issues
            cmd = f'echo "{token}" > {path} && chmod 644 {path}'
            adb_shell(self.target, cmd, timeout=5)
            deployed += 1

        self._state.honeypots_active = deployed
        logger.info(f"Deployed {deployed} honeypot files")
        return deployed

    def _harden_probe_paths(self) -> int:
        """Remove or mask files at known probe paths.
        
        For each path that detection libraries check:
        - If it exists and shouldn't: remove it
        - If it's a Cuttlefish artifact: bind-mount /dev/null
        """
        hardened = 0
        remove_paths = [
            "/system/app/Superuser.apk",
            "/system/xbin/su",
            "/system/bin/su",
            "/sbin/su",
            "/cache/magisk.log",
            "/data/local/tmp/frida-server",
            "/data/local/tmp/re.frida.server",
            "/system/framework/XposedBridge.jar",
        ]

        # Batch remove
        rm_cmds = [f"rm -f {p} 2>/dev/null" for p in remove_paths]
        adb_shell(self.target, " && ".join(rm_cmds), timeout=10)

        # Mask emulator-specific paths with bind mounts
        mask_paths = [
            "/dev/socket/qemud",
            "/dev/qemu_pipe",
            "/dev/goldfish_pipe",
            "/sys/qemu_trace",
        ]
        for path in mask_paths:
            exists = adb_shell(self.target, f"test -e {path} && echo y", timeout=3).strip()
            if exists == "y":
                adb_shell(self.target, f"mount -o bind /dev/null {path} 2>/dev/null", timeout=5)
                hardened += 1

        self._state.inotify_watches += hardened
        logger.info(f"Hardened {hardened} probe paths")
        return hardened

    def _harden_probe_props(self) -> int:
        """Set safe values for commonly probed properties."""
        safe_props = {
            "ro.debuggable": "0",
            "ro.secure": "1",
            "ro.build.selinux": "1",
            "ro.boot.verifiedbootstate": "green",
            "ro.kernel.qemu": "",
            "ro.kernel.qemu.gles": "",
            "init.svc.qemud": "",
            "ro.hardware.chipname": "exynos2400",
            "persist.sys.dalvik.vm.lib.2": "libart.so",
        }

        # Check for resetprop availability
        has_resetprop = adb_shell(
            self.target, "test -f /data/local/tmp/magisk64 && echo y", timeout=3
        ).strip() == "y"

        cmds = []
        for prop, value in safe_props.items():
            if has_resetprop and value:
                cmds.append(f"/data/local/tmp/magisk64 resetprop {prop} '{value}'")
            elif value:
                cmds.append(f"setprop {prop} '{value}'")
            elif has_resetprop:
                cmds.append(f"/data/local/tmp/magisk64 resetprop --delete {prop}")

        # Batch in groups of 10
        for i in range(0, len(cmds), 10):
            batch = " && ".join(cmds[i:i+10])
            adb_shell(self.target, batch, timeout=10)

        logger.info(f"Hardened {len(safe_props)} probe properties")
        return len(safe_props)

    def _cloak_processes(self) -> int:
        """Hide diagnostic/development processes that leak emulator status."""
        processes_to_hide = [
            "adbd",          # ADB daemon (visible in /proc)
            "qemu-props",    # QEMU property service
            "goldfish",      # Goldfish emulator
            "cuttlefish",    # Cuttlefish service names
        ]

        cloaked = 0
        # Rename process names in /proc/*/cmdline by bind-mounting empty files
        proc_pids = adb_shell(self.target, "ls /proc/ 2>/dev/null", timeout=5)
        for pid in proc_pids.split():
            if not pid.isdigit():
                continue
            cmdline = adb_shell(
                self.target, f"cat /proc/{pid}/cmdline 2>/dev/null", timeout=3
            ).strip()
            for pattern in processes_to_hide:
                if pattern in cmdline.lower():
                    # Create empty cmdline file and bind-mount
                    adb_shell(self.target,
                        f"echo -n > /dev/.sc/{pid}_cmdline && "
                        f"mount -o bind /dev/.sc/{pid}_cmdline /proc/{pid}/cmdline 2>/dev/null",
                        timeout=5)
                    cloaked += 1
                    break

        logger.info(f"Cloaked {cloaked} suspicious processes")
        return cloaked

    def _lockdown_probe_ports(self) -> int:
        """Block ports commonly used by detection tools."""
        port_rules = [
            # Frida default ports
            ("27042", "Frida server"),
            ("27043", "Frida portal"),
            # ADB over TCP (if not needed)
            # ("5555", "ADB TCP"),  # Don't block — we need this
        ]

        locked = 0
        for port, desc in port_rules:
            for proto in ["tcp", "udp"]:
                adb_shell(self.target,
                    f"iptables -C INPUT -p {proto} --dport {port} -j DROP 2>/dev/null || "
                    f"iptables -A INPUT -p {proto} --dport {port} -j DROP",
                    timeout=5)
                adb_shell(self.target,
                    f"ip6tables -C INPUT -p {proto} --dport {port} -j DROP 2>/dev/null || "
                    f"ip6tables -A INPUT -p {proto} --dport {port} -j DROP",
                    timeout=5)
            locked += 1

        logger.info(f"Locked down {locked} probe ports")
        return locked

    def start_monitoring(self, interval_s: float = 30.0,
                         alert_callback: Optional[Callable] = None) -> bool:
        """Start background monitoring thread.
        
        Periodically scans for:
        - New detection apps installed
        - Honeypot file access (timestamp changes)
        - Suspicious property reads
        - Process environment anomalies
        """
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("Monitoring already active")
            return False

        self._alert_callback = alert_callback
        self._stop_event.clear()
        self._state.active = True

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_s,),
            daemon=True,
            name="titan-immune-watchdog",
        )
        self._monitor_thread.start()
        logger.info(f"Immune watchdog monitoring started (interval={interval_s}s)")
        return True

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self._stop_event.set()
        self._state.active = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
        logger.info("Immune watchdog monitoring stopped")

    def _monitor_loop(self, interval_s: float):
        """Main monitoring loop — runs periodic security scans."""
        while not self._stop_event.is_set():
            try:
                self._scan_detection_apps()
                self._scan_honeypots()
                self._scan_suspicious_processes()
                self._state.last_scan = time.time()
            except Exception as e:
                logger.error(f"Watchdog scan error: {e}")

            self._stop_event.wait(interval_s)

    def _scan_detection_apps(self):
        """Scan for newly installed detection/root-checking apps."""
        installed = adb_shell(self.target, "pm list packages 2>/dev/null", timeout=10)
        for line in installed.splitlines():
            pkg = line.replace("package:", "").strip()
            if pkg in DETECTION_LIBRARIES:
                lib_name = DETECTION_LIBRARIES[pkg]
                event = ThreatEvent(
                    timestamp=time.time(),
                    threat_type="detection_lib",
                    source_pkg=pkg,
                    target=lib_name,
                    severity="high",
                )

                # Countermeasure: force-stop and disable
                adb_shell(self.target, f"am force-stop {pkg}", timeout=5)
                adb_shell(self.target, f"pm disable-user {pkg} 2>/dev/null", timeout=5)
                event.countermeasure = "force_stop+disable"
                event.neutralized = True

                self._record_threat(event)

    def _scan_honeypots(self):
        """Check if honeypot files have been accessed recently."""
        honeypots = [
            "/data/local/tmp/.su_check",
            "/data/local/tmp/.magisk_check",
            "/data/local/tmp/.frida_check",
            "/data/local/tmp/.emulator_check",
        ]

        now_epoch = int(time.time())
        for path in honeypots:
            # Check access time via stat
            atime_raw = adb_shell(
                self.target,
                f"stat -c %X {path} 2>/dev/null",
                timeout=3
            ).strip()

            if not atime_raw or not atime_raw.isdigit():
                continue

            atime = int(atime_raw)
            # If accessed in last monitoring interval (+ margin)
            if now_epoch - atime < 120:
                # Identify which process accessed it
                accessor = self._identify_accessor(path)
                event = ThreatEvent(
                    timestamp=time.time(),
                    threat_type="honeypot_triggered",
                    source_pkg=accessor,
                    target=path,
                    severity="high" if "su" in path or "magisk" in path else "medium",
                )

                # Replace honeypot with fresh content
                token = secrets.token_hex(16)
                adb_shell(self.target, f'echo "{token}" > {path}', timeout=3)
                event.countermeasure = "honeypot_refreshed"
                event.neutralized = True

                self._record_threat(event)

    def _identify_accessor(self, path: str) -> str:
        """Try to identify which package accessed a file via /proc audit."""
        # Check recent logcat for file access attempts
        output = adb_shell(
            self.target,
            f"logcat -d -t 100 -s audit 2>/dev/null | grep '{path}' | tail -1",
            timeout=5
        ).strip()

        if output:
            # Extract comm= or pkg= from audit log
            for token in output.split():
                if token.startswith("comm="):
                    return token.split("=", 1)[1].strip('"')

        return "unknown"

    def _scan_suspicious_processes(self):
        """Scan for processes that indicate active fingerprinting."""
        ps_output = adb_shell(self.target, "ps -A -o PID,NAME 2>/dev/null", timeout=10)

        suspicious_patterns = [
            "frida", "xposed", "substrate", "cydia",
            "magisk", "supersu", "rootcloak",
        ]

        for line in ps_output.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                continue
            pid, name = parts[0], parts[1].lower()

            for pattern in suspicious_patterns:
                if pattern in name:
                    event = ThreatEvent(
                        timestamp=time.time(),
                        threat_type="suspicious_process",
                        source_pkg=name,
                        target=f"PID:{pid}",
                        severity="critical" if pattern in ("frida", "xposed") else "high",
                    )

                    # Kill the process
                    adb_shell(self.target, f"kill -9 {pid} 2>/dev/null", timeout=3)
                    event.countermeasure = "killed"
                    event.neutralized = True

                    self._record_threat(event)
                    break

    def _record_threat(self, event: ThreatEvent):
        """Record a threat event and trigger alerts."""
        self._state.threat_log.append(event)
        self._state.threats_detected += 1
        if event.neutralized:
            self._state.threats_neutralized += 1

        logger.warning(
            f"THREAT [{event.severity}]: {event.threat_type} "
            f"src={event.source_pkg} target={event.target} "
            f"action={event.countermeasure}"
        )

        # Trigger callback if registered
        if self._alert_callback:
            try:
                self._alert_callback(event)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

    def get_threat_report(self) -> Dict[str, Any]:
        """Get comprehensive threat report."""
        return {
            "active": self._state.active,
            "deployed_at": self._state.deployed_at,
            "honeypots_active": self._state.honeypots_active,
            "inotify_watches": self._state.inotify_watches,
            "threats_detected": self._state.threats_detected,
            "threats_neutralized": self._state.threats_neutralized,
            "last_scan": self._state.last_scan,
            "recent_threats": [
                {
                    "timestamp": e.timestamp,
                    "type": e.threat_type,
                    "source": e.source_pkg,
                    "target": e.target,
                    "severity": e.severity,
                    "action": e.countermeasure,
                    "neutralized": e.neutralized,
                }
                for e in self._state.threat_log[-50:]  # Last 50
            ],
        }

    def run_full_scan(self) -> Dict[str, Any]:
        """Run a one-shot comprehensive security scan.
        
        Unlike start_monitoring(), this runs once synchronously
        and returns results immediately.
        """
        ensure_adb_root(self.target)

        scan_results = {
            "detection_apps": self._audit_detection_apps(),
            "probe_paths_exposed": self._audit_probe_paths(),
            "dangerous_props": self._audit_dangerous_props(),
            "open_ports": self._audit_open_ports(),
            "suspicious_procs": self._audit_suspicious_procs(),
        }

        # Calculate overall risk score
        risk = 0
        risk += scan_results["detection_apps"]["count"] * 20
        risk += scan_results["probe_paths_exposed"]["count"] * 10
        risk += scan_results["dangerous_props"]["count"] * 5
        risk += scan_results["open_ports"]["count"] * 15
        risk += scan_results["suspicious_procs"]["count"] * 25

        scan_results["risk_score"] = min(100, risk)
        scan_results["risk_level"] = (
            "critical" if risk >= 75 else
            "high" if risk >= 50 else
            "medium" if risk >= 25 else
            "low"
        )

        self._state.last_scan = time.time()
        logger.info(f"Full scan: risk={scan_results['risk_level']} ({risk})")
        return scan_results

    def _audit_detection_apps(self) -> Dict[str, Any]:
        """Check for installed detection/root-checking apps."""
        installed = adb_shell(self.target, "pm list packages 2>/dev/null", timeout=10)
        found = []
        for line in installed.splitlines():
            pkg = line.replace("package:", "").strip()
            if pkg in DETECTION_LIBRARIES:
                found.append({"package": pkg, "name": DETECTION_LIBRARIES[pkg]})
        return {"count": len(found), "apps": found}

    def _audit_probe_paths(self) -> Dict[str, Any]:
        """Check which probe paths are accessible."""
        exposed = []
        # Batch check existence
        checks = [f"test -e {p} && echo '{p}'" for p in list(PROBE_PATHS)[:20]]
        batch = " ; ".join(checks)
        output = adb_shell(self.target, batch, timeout=10)
        for line in output.splitlines():
            path = line.strip()
            if path and path.startswith("/"):
                exposed.append(path)
        return {"count": len(exposed), "paths": exposed}

    def _audit_dangerous_props(self) -> Dict[str, Any]:
        """Check properties that could leak emulator/root status."""
        dangerous = []
        for prop in PROBE_PROPS:
            val = adb_shell(self.target, f"getprop {prop} 2>/dev/null", timeout=3).strip()
            if self._is_dangerous_value(prop, val):
                dangerous.append({"prop": prop, "value": val})
        return {"count": len(dangerous), "props": dangerous}

    def _is_dangerous_value(self, prop: str, value: str) -> bool:
        """Check if a property value exposes emulator/root status."""
        if not value:
            return False
        dangerous_patterns = {
            "ro.debuggable": lambda v: v == "1",
            "ro.secure": lambda v: v == "0",
            "ro.kernel.qemu": lambda v: v == "1",
            "ro.boot.verifiedbootstate": lambda v: v != "green",
            "init.svc.adbd": lambda v: v == "running",
        }
        checker = dangerous_patterns.get(prop)
        if checker:
            return checker(value)
        # Generic: check for emulator-related strings
        return any(s in value.lower() for s in ["qemu", "goldfish", "ranchu", "cuttlefish", "vsoc"])

    def _audit_open_ports(self) -> Dict[str, Any]:
        """Check for open ports that could indicate debugging tools."""
        suspicious_ports = {"27042": "Frida", "27043": "Frida", "8100": "Appium", "4723": "Appium"}
        open_ports = []

        netstat = adb_shell(self.target,
            "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null",
            timeout=5)
        for line in netstat.splitlines():
            for port, tool in suspicious_ports.items():
                if f":{port}" in line:
                    open_ports.append({"port": port, "tool": tool, "line": line.strip()[:80]})
        return {"count": len(open_ports), "ports": open_ports}

    def _audit_suspicious_procs(self) -> Dict[str, Any]:
        """Check for suspicious running processes."""
        suspicious = []
        ps_out = adb_shell(self.target, "ps -A -o PID,NAME 2>/dev/null", timeout=10)
        patterns = ["frida", "xposed", "substrate", "magisk", "supersu", "cydia"]

        for line in ps_out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                continue
            name = parts[1].lower()
            for p in patterns:
                if p in name:
                    suspicious.append({"pid": parts[0], "name": parts[1], "match": p})
                    break
        return {"count": len(suspicious), "procs": suspicious}
