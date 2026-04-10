"""
Open Claw Stack — Firewall Agent
===================================
Audits firewall rules for security posture.

Windows: netsh advfirewall
Linux:   iptables / ufw

Detects:
  - Firewall disabled profiles
  - Overly permissive inbound rules (any source)
  - Unexpected open ports in firewall config
  - Rules allowing inbound on dangerous ports
"""
import logging
import platform
import re
import time
from typing import Dict, List, Tuple

from core.execwall import Execwall, PolicyViolationError
from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"

# Ports that should almost never have permissive inbound rules
DANGEROUS_PORTS = {
    22:    "SSH",
    23:    "Telnet (plaintext)",
    445:   "SMB (ransomware vector)",
    3389:  "RDP (brute-force target)",
    5900:  "VNC (remote desktop)",
    6379:  "Redis (often unauthenticated)",
    27017: "MongoDB (often unauthenticated)",
    11434: "Ollama (AI framework)",
    8888:  "Jupyter (unauthenticated notebooks)",
}


class FirewallAgent:
    """Audits firewall configuration for gaps in the security perimeter."""

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("firewall", mem_max_mb=128, cpu_max_percent=20)

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("firewall", f"fw-{int(time.time())}"):
            self.state.update_agent(
                "firewall", AgentStatus.PERCEIVING,
                "🔥 Firewall Agent online — auditing firewall rules..."
            )
            tool_log = []
            results  = {}

            if IS_WIN:
                self.state.update_agent("firewall", AgentStatus.ACTING, "🪟 Querying Windows Firewall profiles...")
                profiles  = self._win_profiles()
                rules     = self._win_rules()
                results["profiles"] = profiles
                results["rules"]    = rules
                tool_log.append(f"✅ Windows Firewall: {len(profiles)} profiles, {len(rules)} inbound rules")
            else:
                self.state.update_agent("firewall", AgentStatus.ACTING, "🐧 Querying iptables/ufw...")
                profiles = self._linux_ufw()
                rules    = self._linux_iptables()
                results["profiles"] = profiles
                results["rules"]    = rules
                tool_log.append(f"✅ Linux Firewall: profiles={profiles}, {len(rules)} rules")

            # Analyze
            self.state.update_agent("firewall", AgentStatus.ACTING, "🔍 Analyzing for dangerous rules...")
            findings = self._analyze(results)
            for f in findings:
                if f["severity"] == "HIGH":
                    self.state.add_incident({"type": "FIREWALL_RISK", "agent": "firewall", "detail": f["detail"]})

            score, label = self._score(findings, results)

            self.state.update_agent(
                "firewall", AgentStatus.DONE,
                f"✅ Firewall audit complete — {label}",
                metrics={
                    "health_score": score,
                    "health_label": label,
                    "findings":     len(findings),
                    "high_risk":    sum(1 for f in findings if f["severity"] == "HIGH"),
                },
            )
            self.state.agents["firewall"].tool_calls = [{"tool": t} for t in tool_log]
            return self._format_report(results, findings, score, label, task)

    # ──────────────────────────────────────────────
    # Windows Tools
    # ──────────────────────────────────────────────

    def _win_profiles(self) -> Dict[str, str]:
        """Get state of Domain/Private/Public firewall profiles."""
        try:
            out, _, rc = self.execwall.execute(
                "netsh advfirewall show allprofiles state", "firewall", timeout=10
            )
            profiles = {}
            for line in out.splitlines():
                m = re.search(r"(\w+ Profile) Settings:|State\s+(ON|OFF)", line)
                if m:
                    if "Profile" in m.group(0):
                        current_profile = m.group(1)
                    elif "State" in m.group(0) and current_profile:
                        profiles[current_profile] = m.group(2)
            return profiles
        except PolicyViolationError:
            return {}
        except Exception:
            return {}

    def _win_rules(self) -> List[Dict]:
        """Get inbound firewall rules allowing traffic."""
        try:
            out, _, rc = self.execwall.execute(
                'netsh advfirewall firewall show rule name=all dir=in action=allow',
                "firewall", timeout=20
            )
            rules = []
            current: Dict = {}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Rule Name:"):
                    if current:
                        rules.append(current)
                    current = {"name": line.split(":", 1)[-1].strip()}
                elif ":" in line and current:
                    k, _, v = line.partition(":")
                    current[k.strip().lower().replace(" ", "_")] = v.strip()
            if current:
                rules.append(current)
            return rules[:50]
        except PolicyViolationError:
            return []
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # Linux Tools
    # ──────────────────────────────────────────────

    def _linux_ufw(self) -> Dict:
        try:
            out, _, _ = self.execwall.execute("ufw status verbose", "firewall", timeout=10)
            return {"ufw_status": out[:500]}
        except Exception:
            return {}

    def _linux_iptables(self) -> List[str]:
        try:
            out, _, _ = self.execwall.execute("iptables -L INPUT -n --line-numbers", "firewall", timeout=10)
            return out.splitlines()[:40]
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # Analysis
    # ──────────────────────────────────────────────

    def _analyze(self, results: Dict) -> List[Dict]:
        findings = []

        # Check disabled profiles (Windows)
        for profile, state in results.get("profiles", {}).items():
            if state == "OFF":
                findings.append({
                    "severity": "HIGH",
                    "type":     "FIREWALL_DISABLED",
                    "detail":   f"Firewall {profile} is DISABLED — no inbound protection!",
                })

        # Check rules for dangerous ports
        for rule in results.get("rules", []):
            # Look for any-source rules
            remote_addr = rule.get("remoteip", "any")
            local_port  = rule.get("localport", "")
            name        = rule.get("name", "?")

            if remote_addr.lower() in ("any", "0.0.0.0/0"):
                for port, label in DANGEROUS_PORTS.items():
                    if str(port) in local_port:
                        findings.append({
                            "severity": "HIGH",
                            "type":     "DANGEROUS_INBOUND",
                            "detail":   f"Rule '{name}' allows inbound from ANY source on port {port} ({label})",
                        })

        return findings

    @staticmethod
    def _score(findings: List[Dict], results: Dict) -> Tuple[int, str]:
        score   = 100
        highs   = sum(1 for f in findings if f["severity"] == "HIGH")
        score  -= highs * 25
        # Penalize disabled firewall heavily
        for state in results.get("profiles", {}).values():
            if state == "OFF":
                score -= 30

        score = max(0, min(100, score))
        if score >= 80: label = "🟢 HARDENED"
        elif score >= 50: label = "🟡 GAPS FOUND"
        else:             label = "🔴 EXPOSED"
        return score, label

    # ──────────────────────────────────────────────
    # Report
    # ──────────────────────────────────────────────

    def _format_report(self, results, findings, score, label, task) -> str:
        profiles_txt = "\n".join(
            f"  • {k}: {'✅ ON' if v == 'ON' else '🔴 OFF'}"
            for k, v in results.get("profiles", {}).items()
        ) or "  (query failed — run as administrator)"

        findings_txt = "\n".join(
            f"  [{f['severity']}] {f['type']}: {f['detail']}"
            for f in findings
        ) or "  ✅ No firewall vulnerabilities found"

        rule_count = len(results.get("rules", []))

        return f"""## 🔥 Firewall Agent Report

**Task**: {task or "Firewall audit"}
**Score**: {score}/100  {label}

### Firewall Profiles
{profiles_txt}

### Inbound Rules Scanned
  • Total inbound ALLOW rules: {rule_count}

### Security Findings ({len(findings)} issues)
{findings_txt}

### Recommendation
{"✅ Firewall posture is strong." if score >= 80 else "⚠️ Review dangerous inbound rules and ensure all profiles are ON." if score >= 50 else "🚨 Critical exposure. Enable firewall on all profiles and remove permissive rules immediately."}
"""
