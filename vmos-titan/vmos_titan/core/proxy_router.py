"""
Titan V11.3 — SOCKS5 Proxy Router
Routes all Android device traffic through SOCKS5 proxy using redsocks + iptables.

Usage:
    router = ProxyRouter(adb_target="127.0.0.1:6520")
    result = router.configure_socks5("socks5h://user:pass@host:port")
"""

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from adb_utils import adb as _adb, adb_shell as _adb_shell, adb_push as _adb_push, ensure_adb_root as _ensure_adb_root

logger = logging.getLogger("titan.proxy-router")


@dataclass
class ProxyResult:
    success: bool = False
    proxy_ip: str = ""
    proxy_port: int = 0
    external_ip: str = ""
    method: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "proxy_ip": self.proxy_ip,
            "proxy_port": self.proxy_port,
            "external_ip": self.external_ip,
            "method": self.method,
            "errors": self.errors,
        }


class ProxyRouter:
    """Routes Android device traffic through SOCKS5 proxy."""

    REDSOCKS_BIN = "/data/local/tmp/redsocks"
    REDSOCKS_CONF = "/data/local/tmp/redsocks.conf"
    STARTUP_SCRIPT = "/data/local/tmp/proxy_startup.sh"

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target

    def _sh(self, cmd: str, timeout: int = 30) -> Tuple[bool, str]:
        """Run shell command on device. Returns (success, stdout)."""
        return _adb(self.target, f'shell "{cmd}"', timeout=timeout)

    def configure_socks5(self, proxy_url: str) -> ProxyResult:
        """
        Configure device to route all traffic through SOCKS5 proxy.

        Args:
            proxy_url: SOCKS5 proxy URL (socks5h://user:pass@host:port)

        Returns:
            ProxyResult with configuration status
        """
        result = ProxyResult()
        _ensure_adb_root(self.target)

        # Parse proxy URL
        try:
            parsed = urlparse(proxy_url)
            proxy_host = parsed.hostname
            proxy_port = parsed.port or 1080
            proxy_user = parsed.username or ""
            proxy_pass = parsed.password or ""
            result.proxy_ip = proxy_host
            result.proxy_port = proxy_port
        except Exception as e:
            result.errors.append(f"Invalid proxy URL: {e}")
            return result

        logger.info(f"Configuring SOCKS5 proxy: {proxy_host}:{proxy_port}")

        # Try multiple methods in order of preference
        methods = [
            ("tun2socks", self._configure_tun2socks),
            ("iptables_tproxy", self._configure_tproxy),
            ("global_proxy", self._configure_global_proxy),
            ("vpn_service", self._configure_vpn_service),
        ]

        for method_name, method_func in methods:
            try:
                ok = method_func(proxy_host, proxy_port, proxy_user, proxy_pass)
                if ok:
                    result.method = method_name
                    result.success = True
                    # Verify external IP
                    result.external_ip = self._verify_proxy()
                    if result.external_ip:
                        logger.info(f"Proxy configured via {method_name}, external IP: {result.external_ip}")
                        return result
            except Exception as e:
                result.errors.append(f"{method_name}: {e}")
                logger.warning(f"Method {method_name} failed: {e}")

        return result

    def _configure_tproxy(self, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure transparent proxy using iptables REDIRECT."""
        logger.info("Attempting iptables TPROXY method...")

        # Create redsocks config
        redsocks_conf = f'''base {{
    log_debug = off;
    log_info = on;
    log = "syslog:daemon";
    daemon = on;
    redirector = iptables;
}}

redsocks {{
    local_ip = 127.0.0.1;
    local_port = 12345;
    ip = {host};
    port = {port};
    type = socks5;
    login = "{user}";
    password = "{passwd}";
}}
'''
        # Write config to temp file and push
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            f.write(redsocks_conf)
            conf_path = f.name

        _adb_push(self.target, conf_path, self.REDSOCKS_CONF)
        os.unlink(conf_path)

        # Check if redsocks binary exists, if not use socksify or proxychains
        ok, _ = self._sh(f"test -f {self.REDSOCKS_BIN} && echo exists")
        
        if not ok or "exists" not in _:
            # Try to use Android's built-in proxy support via settings
            return self._configure_settings_proxy(host, port, user, passwd)

        # Start redsocks
        self._sh(f"killall redsocks 2>/dev/null")
        self._sh(f"chmod 755 {self.REDSOCKS_BIN}")
        ok, out = self._sh(f"{self.REDSOCKS_BIN} -c {self.REDSOCKS_CONF}")

        if not ok:
            return False

        # Configure iptables to redirect TCP traffic
        iptables_cmds = [
            "iptables -t nat -F OUTPUT",
            "iptables -t nat -F PREROUTING",
            f"iptables -t nat -A OUTPUT -p tcp -d {host} -j RETURN",
            "iptables -t nat -A OUTPUT -p tcp -d 127.0.0.0/8 -j RETURN",
            "iptables -t nat -A OUTPUT -p tcp -d 10.0.0.0/8 -j RETURN",
            "iptables -t nat -A OUTPUT -p tcp -d 192.168.0.0/16 -j RETURN",
            "iptables -t nat -A OUTPUT -p tcp -j REDIRECT --to-port 12345",
        ]

        for cmd in iptables_cmds:
            self._sh(cmd)

        return True

    def _configure_settings_proxy(self, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure Android global proxy via settings (HTTP/HTTPS only)."""
        logger.info("Configuring Android global proxy via settings...")

        # Note: Android global proxy only supports HTTP/HTTPS, not full SOCKS5
        # For SOCKS5, we need to use a local proxy app or VPN
        
        # Set global HTTP proxy (limited but works for many apps)
        proxy_str = f"{host}:{port}"
        self._sh(f"settings put global http_proxy {proxy_str}")
        self._sh(f"settings put global global_http_proxy_host {host}")
        self._sh(f"settings put global global_http_proxy_port {port}")
        
        if user and passwd:
            self._sh(f"settings put global global_http_proxy_username {user}")
            self._sh(f"settings put global global_http_proxy_password {passwd}")

        # For SOCKS5 support, configure per-app proxy via ProxyHandler
        # This requires pushing a proxy helper app or using Proxifier
        
        return True

    def _configure_global_proxy(self, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure global proxy using Android's ConnectivityManager."""
        logger.info("Configuring global proxy via ConnectivityManager...")

        # Use adb to set proxy
        proxy_spec = f"{host}:{port}"
        
        # WiFi proxy (requires WiFi to be primary connection)
        cmds = [
            f"settings put global http_proxy {proxy_spec}",
            f"settings put global global_http_proxy_host {host}",
            f"settings put global global_http_proxy_port {port}",
        ]
        
        for cmd in cmds:
            self._sh(cmd)

        # Also set via setprop for apps that check properties
        self._sh(f"setprop net.gprs.http-proxy {proxy_spec}")
        self._sh(f"setprop net.http.proxy {proxy_spec}")

        return True

    def _configure_tun2socks(self, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure SOCKS5 via tun2socks — creates TUN interface and routes all traffic."""
        logger.info("Attempting tun2socks method...")
        TUN2SOCKS = "/data/local/tmp/tun2socks"

        # Check arch and download tun2socks if missing
        ok, arch_out = self._sh("uname -m")
        arch = arch_out.strip() if ok else "x86_64"
        ok, _ = self._sh(f"test -x {TUN2SOCKS} && echo exists")
        if not ok or "exists" not in _:
            # Download tun2socks static binary
            if "x86_64" in arch:
                dl_url = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-linux-amd64.zip"
            elif "aarch64" in arch or "arm64" in arch:
                dl_url = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-linux-arm64.zip"
            else:
                dl_url = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-linux-386.zip"

            self._sh(
                f"cd /data/local/tmp && "
                f"curl -sL --connect-timeout 15 --max-time 60 '{dl_url}' -o tun2socks.zip 2>/dev/null && "
                f"unzip -o tun2socks.zip -d tun2socks_tmp 2>/dev/null && "
                f"mv tun2socks_tmp/tun2socks-* {TUN2SOCKS} 2>/dev/null; "
                f"chmod 755 {TUN2SOCKS}; rm -rf tun2socks.zip tun2socks_tmp",
                timeout=90,
            )
            ok, _ = self._sh(f"test -x {TUN2SOCKS} && echo exists")
            if not ok or "exists" not in _:
                logger.warning("tun2socks binary not available")
                return False

        # Kill any previous instance
        self._sh("killall tun2socks 2>/dev/null")
        self._sh("ip link delete tun0 2>/dev/null")
        time.sleep(0.5)

        # Build proxy URL
        auth = f"{user}:{passwd}@" if user else ""
        socks_url = f"socks5://{auth}{host}:{port}"

        # Start tun2socks in background
        self._sh(
            f"nohup {TUN2SOCKS} -device tun0 -proxy '{socks_url}' "
            f"> /data/local/tmp/tun2socks.log 2>&1 &",
            timeout=5,
        )
        time.sleep(2)

        # Configure TUN interface
        tun_cmds = [
            "ip addr add 198.18.0.1/15 dev tun0",
            "ip link set tun0 up",
            "ip route add default dev tun0 table 100",
            "ip rule add fwmark 0x1 table 100",
            f"iptables -t mangle -A OUTPUT -p tcp ! -d {host} -j MARK --set-mark 0x1",
            f"iptables -t mangle -A OUTPUT -p udp ! -d {host} -j MARK --set-mark 0x1",
            "iptables -t mangle -A OUTPUT -d 127.0.0.0/8 -j RETURN",
            "iptables -t mangle -A OUTPUT -d 10.0.0.0/8 -j RETURN",
            "iptables -t mangle -A OUTPUT -d 192.168.0.0/16 -j RETURN",
        ]
        for cmd in tun_cmds:
            self._sh(cmd)

        # Verify TUN is up
        ok, tun_check = self._sh("ip link show tun0 2>/dev/null")
        if ok and "tun0" in tun_check:
            logger.info("tun2socks: TUN interface up, traffic routed through SOCKS5")
            return True

        logger.warning("tun2socks: TUN interface failed to come up")
        return False

    def _configure_vpn_service(self, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure SOCKS5 via VPN service app (SocksDroid, Postern)."""
        logger.info("Attempting VPN service method...")
        
        # Check if SocksDroid or similar is installed
        vpn_apps = [
            "net.typeblog.socks",      # SocksDroid
            "com.pairip.postern",       # Postern
            "com.proxydroid",           # ProxyDroid
        ]
        
        for pkg in vpn_apps:
            ok, _ = self._sh(f"pm list packages | grep {pkg}")
            if ok and pkg in _:
                logger.info(f"Found VPN app: {pkg}")
                # Configure via shared_prefs
                return self._configure_vpn_app(pkg, host, port, user, passwd)
        
        return False

    def _configure_vpn_app(self, pkg: str, host: str, port: int, user: str, passwd: str) -> bool:
        """Configure a VPN/SOCKS app via its preferences."""
        # This is app-specific, implement for SocksDroid
        if "socks" in pkg.lower():
            prefs = f'''<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="server">{host}</string>
    <int name="port" value="{port}" />
    <string name="username">{user}</string>
    <string name="password">{passwd}</string>
    <boolean name="isRunning" value="true" />
    <boolean name="isAutoConnect" value="true" />
</map>'''
            prefs_path = f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
                f.write(prefs)
                tmp_path = f.name
            
            _adb_push(self.target, tmp_path, prefs_path)
            os.unlink(tmp_path)
            
            # Start the VPN service
            self._sh(f"am startservice -n {pkg}/.SocksVpnService")
            return True
        
        return False

    def _verify_proxy(self) -> str:
        """Verify proxy is working by checking external IP."""
        # Use curl on device to check IP
        ok, out = self._sh("curl -s --connect-timeout 10 https://api.ipify.org 2>/dev/null")
        if ok and out.strip():
            return out.strip()
        
        # Fallback: try wget
        ok, out = self._sh("wget -qO- --timeout=10 https://api.ipify.org 2>/dev/null")
        if ok and out.strip():
            return out.strip()
        
        return ""

    def clear_proxy(self) -> bool:
        """Remove all proxy configuration (tun2socks, redsocks, settings, iptables)."""
        logger.info("Clearing proxy configuration...")
        _ensure_adb_root(self.target)

        cmds = [
            # Kill proxy daemons
            "killall tun2socks 2>/dev/null",
            "killall redsocks 2>/dev/null",
            # Remove TUN interface and routing rules
            "ip link delete tun0 2>/dev/null",
            "ip rule del fwmark 0x1 table 100 2>/dev/null",
            "ip route flush table 100 2>/dev/null",
            # Flush iptables proxy rules
            "iptables -t mangle -F OUTPUT 2>/dev/null",
            "iptables -t nat -F OUTPUT 2>/dev/null",
            "iptables -t nat -F PREROUTING 2>/dev/null",
            # Clear Android global proxy settings
            "settings delete global http_proxy",
            "settings delete global global_http_proxy_host",
            "settings delete global global_http_proxy_port",
            "settings delete global global_http_proxy_username",
            "settings delete global global_http_proxy_password",
            # Clear setprop-based proxy
            "setprop net.gprs.http-proxy ''",
            "setprop net.http.proxy ''",
        ]

        for cmd in cmds:
            self._sh(cmd)

        logger.info("Proxy cleared: tun2socks, redsocks, iptables, global settings")
        return True

    def disable_proxy(self) -> bool:
        """Disable proxy temporarily (keep config for re-enable).

        Stops traffic routing but preserves tun2socks binary and redsocks config
        so enable_proxy() can bring it back without re-downloading.
        """
        logger.info("Disabling proxy (temporary)...")
        _ensure_adb_root(self.target)

        cmds = [
            "killall tun2socks 2>/dev/null",
            "killall redsocks 2>/dev/null",
            "ip link set tun0 down 2>/dev/null",
            "ip rule del fwmark 0x1 table 100 2>/dev/null",
            "ip route flush table 100 2>/dev/null",
            "iptables -t mangle -F OUTPUT 2>/dev/null",
            "iptables -t nat -F OUTPUT 2>/dev/null",
            "iptables -t nat -F PREROUTING 2>/dev/null",
            "settings delete global http_proxy",
            "settings delete global global_http_proxy_host",
            "settings delete global global_http_proxy_port",
        ]
        for cmd in cmds:
            self._sh(cmd)

        logger.info("Proxy disabled — direct connectivity restored")
        return True

    def enable_proxy(self, proxy_url: str) -> ProxyResult:
        """Re-enable proxy with given URL. Alias for configure_socks5()."""
        return self.configure_socks5(proxy_url)

    def get_status(self) -> dict:
        """Get current proxy status."""
        _, http_proxy = self._sh("settings get global http_proxy")
        _, external_ip = self._sh("curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null")
        _, redsocks_running = self._sh("pgrep redsocks")
        _, tun2socks_running = self._sh("pgrep tun2socks")
        _, tun_up = self._sh("ip link show tun0 2>/dev/null | grep -c UP")

        return {
            "http_proxy": http_proxy.strip() if http_proxy else "",
            "external_ip": external_ip.strip() if external_ip else "",
            "redsocks_running": bool(redsocks_running.strip()),
            "tun2socks_running": bool(tun2socks_running.strip()),
            "tun_interface_up": tun_up.strip() == "1" if tun_up else False,
            "proxy_active": bool(tun2socks_running.strip()) or bool(redsocks_running.strip()),
        }
