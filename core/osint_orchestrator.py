"""
Titan V11.3 — OSINT Orchestrator
Runs Sherlock, Maigret, Holehe against target identifiers.
Aggregates results into a unified profile enrichment dict.
"""

import json
import logging
import os
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.osint")

# Tool binary/script locations — auto-detected
OSINT_TOOLS = {
    "sherlock": {
        "cmd": ["sherlock"],
        "pip": "sherlock-project",
        "check": "sherlock --version",
        "description": "Username enumeration across 400+ social networks",
    },
    "maigret": {
        "cmd": ["maigret"],
        "pip": "maigret",
        "check": "maigret --version",
        "description": "Advanced username OSINT with profile parsing",
    },
    "holehe": {
        "cmd": ["holehe"],
        "pip": "holehe",
        "check": "holehe --version",
        "description": "Email registration check across 100+ sites",
    },
}


@dataclass
class OSINTResult:
    """Aggregated OSINT result across all tools."""
    name: str = ""
    email: str = ""
    username: str = ""
    phone: str = ""
    domain: str = ""
    tools_run: List[str] = field(default_factory=list)
    tools_available: List[str] = field(default_factory=list)
    tools_missing: List[str] = field(default_factory=list)
    sherlock_hits: List[Dict[str, Any]] = field(default_factory=list)
    maigret_hits: List[Dict[str, Any]] = field(default_factory=list)
    holehe_hits: List[Dict[str, Any]] = field(default_factory=list)
    social_profiles: List[Dict[str, str]] = field(default_factory=list)
    emails_found: List[str] = field(default_factory=list)
    enrichment: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "username": self.username,
            "phone": self.phone,
            "domain": self.domain,
            "tools_run": self.tools_run,
            "tools_available": self.tools_available,
            "tools_missing": self.tools_missing,
            "sherlock_hits": self.sherlock_hits,
            "maigret_hits": self.maigret_hits,
            "holehe_hits": self.holehe_hits,
            "social_profiles": self.social_profiles,
            "emails_found": self.emails_found,
            "enrichment": self.enrichment,
            "errors": self.errors,
            "total_hits": len(self.sherlock_hits) + len(self.maigret_hits) + len(self.holehe_hits),
        }


class OSINTOrchestrator:
    """Orchestrates OSINT tool execution and result aggregation."""

    def __init__(self, timeout: int = 60, proxy: str = ""):
        self.timeout = timeout
        self.proxy = proxy
        self._available = self._detect_tools()

    def _detect_tools(self) -> Dict[str, bool]:
        """Detect which OSINT tools are installed."""
        available = {}
        for name, cfg in OSINT_TOOLS.items():
            available[name] = shutil.which(cfg["cmd"][0]) is not None
        return available

    def get_status(self) -> Dict[str, Any]:
        """Return tool availability status."""
        return {
            name: {
                "installed": self._available.get(name, False),
                "description": cfg["description"],
                "pip_package": cfg["pip"],
            }
            for name, cfg in OSINT_TOOLS.items()
        }

    def run(
        self,
        name: str = "",
        email: str = "",
        username: str = "",
        phone: str = "",
        domain: str = "",
    ) -> OSINTResult:
        """Run all available OSINT tools against provided identifiers."""
        result = OSINTResult(
            name=name, email=email, username=username,
            phone=phone, domain=domain,
        )
        result.tools_available = [k for k, v in self._available.items() if v]
        result.tools_missing = [k for k, v in self._available.items() if not v]

        if username:
            if self._available.get("sherlock"):
                self._run_sherlock(username, result)
            if self._available.get("maigret"):
                self._run_maigret(username, result)

        if email and self._available.get("holehe"):
            self._run_holehe(email, result)

        # Aggregate social profiles from all tools
        self._aggregate(result)
        return result

    def _run_cmd(self, cmd: List[str], timeout: Optional[int] = None) -> str:
        """Run a shell command with timeout and optional proxy."""
        env = os.environ.copy()
        if self.proxy:
            env["ALL_PROXY"] = self.proxy
            env["HTTPS_PROXY"] = self.proxy
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout or self.timeout, env=env,
            )
            return proc.stdout
        except subprocess.TimeoutExpired:
            logger.warning(f"OSINT tool timeout: {cmd[0]}")
            return ""
        except Exception as e:
            logger.warning(f"OSINT tool error ({cmd[0]}): {e}")
            return ""

    def _run_sherlock(self, username: str, result: OSINTResult):
        """Run Sherlock username enumeration."""
        try:
            output_file = f"/tmp/sherlock_{username}.json"
            cmd = ["sherlock", username, "--json", output_file, "--timeout", "15"]
            if self.proxy:
                cmd.extend(["--proxy", self.proxy])
            self._run_cmd(cmd, timeout=self.timeout)
            result.tools_run.append("sherlock")

            if os.path.exists(output_file):
                with open(output_file) as f:
                    data = json.load(f)
                for site, info in data.items():
                    if isinstance(info, dict) and info.get("status", "") == "Claimed":
                        result.sherlock_hits.append({
                            "site": site,
                            "url": info.get("url_user", ""),
                            "status": "found",
                        })
                os.unlink(output_file)
        except Exception as e:
            result.errors.append(f"sherlock: {e}")
            logger.warning(f"Sherlock failed: {e}")

    def _run_maigret(self, username: str, result: OSINTResult):
        """Run Maigret advanced username OSINT."""
        try:
            output_file = f"/tmp/maigret_{username}.json"
            cmd = ["maigret", username, "--json", "simple", "-o", output_file, "--timeout", "15"]
            if self.proxy:
                cmd.extend(["--proxy", self.proxy])
            self._run_cmd(cmd, timeout=self.timeout)
            result.tools_run.append("maigret")

            if os.path.exists(output_file):
                with open(output_file) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for entry in data:
                        result.maigret_hits.append({
                            "site": entry.get("sitename", ""),
                            "url": entry.get("url", ""),
                            "status": "found",
                        })
                elif isinstance(data, dict):
                    for site, info in data.items():
                        if isinstance(info, dict):
                            result.maigret_hits.append({
                                "site": site,
                                "url": info.get("url", ""),
                                "status": "found",
                            })
                os.unlink(output_file)
        except Exception as e:
            result.errors.append(f"maigret: {e}")
            logger.warning(f"Maigret failed: {e}")

    def _run_holehe(self, email: str, result: OSINTResult):
        """Run Holehe email registration check."""
        try:
            output = self._run_cmd(["holehe", email, "--no-color"], timeout=self.timeout)
            result.tools_run.append("holehe")

            for line in output.splitlines():
                line = line.strip()
                if not line or line.startswith("[") and "+" not in line:
                    continue
                if "[+]" in line:
                    parts = line.replace("[+]", "").strip().split()
                    if parts:
                        result.holehe_hits.append({
                            "site": parts[0],
                            "status": "registered",
                        })
        except Exception as e:
            result.errors.append(f"holehe: {e}")
            logger.warning(f"Holehe failed: {e}")

    def _aggregate(self, result: OSINTResult):
        """Aggregate all hits into unified social_profiles and enrichment."""
        seen = set()
        for hit in result.sherlock_hits + result.maigret_hits:
            key = hit.get("site", "").lower()
            if key not in seen:
                seen.add(key)
                result.social_profiles.append({
                    "platform": hit.get("site", ""),
                    "url": hit.get("url", ""),
                    "source": "sherlock" if hit in result.sherlock_hits else "maigret",
                })

        for hit in result.holehe_hits:
            if hit.get("status") == "registered":
                result.emails_found.append(hit.get("site", ""))

        # Build enrichment dict for forge integration
        result.enrichment = {
            "social_platforms": [p["platform"] for p in result.social_profiles[:10]],
            "social_urls": {p["platform"]: p["url"] for p in result.social_profiles[:10]},
            "email_registrations": result.emails_found[:20],
            "osint_enriched": len(result.social_profiles) > 0 or len(result.holehe_hits) > 0,
            "total_social_hits": len(result.social_profiles),
            "total_email_hits": len(result.holehe_hits),
        }
