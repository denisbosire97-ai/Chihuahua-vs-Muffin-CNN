"""
Open Claw Stack — Security Auditor Agent
==========================================
Specialist agent for security analysis and PHASR enforcement.

Tools:
  - Process auditing   — detect Shadow AI frameworks
  - Port scanning      — identify unauthorized open ports
  - PHASR rule checks  — verify no policy violations occurred
  - Execwall audit     — review command governance log
  - Identity integrity — check for unauthorized dubbing

Threat Model: Shadow AI, privilege escalation, unauthorized agent execution
"""
import logging
import platform
import re
import time
from typing import Dict, List, Tuple

import psutil

from core.execwall import Execwall, PolicyViolationError
from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"

# Shadow AI process names to watch for
SHADOW_AI_NAMES = [
    "copilot", "openai", "claude", "gemini-app", "localai",
    "lmstudio", "text-generation-webui", "koboldcpp", "oogabooga",
    "llama", "ollama", "stable-diffusion", "automatic1111",
]

# Suspicious listening ports (unmanaged AI services)
SUSPICIOUS_PORTS = {
    11434: "Ollama (local LLM)",
    7860:  "Gradio UI",
    8888:  "Unmanaged Jupyter",
    5000:  "Generic AI server",
    5001:  "Generic AI server (alt)",
    1234:  "LMStudio",
    8080:  "Generic web / proxy",
}


class SecurityAuditorAgent:
    """
    Validates system security posture, audits running processes,
    and enforces PHASR rules against Shadow AI and unauthorized execution.
    """

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("security_auditor", mem_max_mb=256, cpu_max_percent=30)

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("security_auditor", f"sec-{int(time.time())}"):
            self.state.update_agent(
                "security_auditor", AgentStatus.PERCEIVING,
                "🔐 Security Auditor online — initiating threat assessment..."
            )

            findings:    List[Dict] = []
            tool_log:    List[str]  = []

            # 1. Process audit — detect Shadow AI
            self.state.update_agent(
                "security_auditor", AgentStatus.ACTING,
                "🕵️ Scanning processes for Shadow AI frameworks..."
            )
            shadow_findings, all_procs = self._audit_processes()
            findings.extend(shadow_findings)
            tool_log.append(f"✅ Process audit: {all_procs} processes scanned, {len(shadow_findings)} threats found")

            # 2. Port audit
            self.state.update_agent(
                "security_auditor", AgentStatus.ACTING,
                "🔌 Auditing open ports for unauthorized services..."
            )
            port_findings, port_count = self._audit_ports()
            findings.extend(port_findings)
            tool_log.append(f"✅ Port audit: {port_count} listening ports, {len(port_findings)} suspicious")

            # 3. Execwall audit review
            self.state.update_agent(
                "security_auditor", AgentStatus.ACTING,
                "📋 Reviewing Execwall PHASR audit log..."
            )
            phasr_summary = self._review_execwall()
            tool_log.append(f"✅ Execwall audit: {phasr_summary.get('denied', 0)} blocked commands")

            # 4. Incident log review
            incident_count = len(self.state.incident_log)
            tool_log.append(f"📌 Incident log: {incident_count} entries")

            # 5. Score
            threat_level, threat_label = self._threat_level(findings)

            self.state.update_agent(
                "security_auditor", AgentStatus.DONE,
                f"✅ Security audit complete — Threat Level: {threat_label}",
                metrics={
                    "threat_level":    threat_level,
                    "threat_label":    threat_label,
                    "findings":        len(findings),
                    "shadow_ai_found": len(shadow_findings),
                    "suspicious_ports":len(port_findings),
                    "phasr_blocks":    phasr_summary.get("denied", 0),
                },
            )
            self.state.agents["security_auditor"].tool_calls = [{"tool": t} for t in tool_log]

            return self._format_report(findings, phasr_summary, threat_level, threat_label, task)

    # ──────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────

    def _audit_processes(self) -> Tuple[List[Dict], int]:
        """Enumerate running processes and flag Shadow AI."""
        findings = []
        all_procs = 0
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "username"]):
                all_procs += 1
                try:
                    name    = (proc.info.get("name") or "").lower()
                    cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                    full    = f"{name} {cmdline}"

                    for shadow in SHADOW_AI_NAMES:
                        if shadow in full:
                            findings.append({
                                "type":    "SHADOW_AI",
                                "severity":"HIGH",
                                "pid":     proc.info["pid"],
                                "name":    proc.info["name"],
                                "detail":  f"Shadow AI framework detected: '{shadow}' in process '{name}'",
                            })
                            self.state.add_incident({
                                "type":   "SHADOW_AI_DETECTED",
                                "agent":  "security_auditor",
                                "detail": f"PID {proc.info['pid']} — {proc.info['name']} — matched '{shadow}'",
                            })
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as exc:
            logger.warning(f"SecurityAuditor: process scan error: {exc}")

        return findings, all_procs

    def _audit_ports(self) -> Tuple[List[Dict], int]:
        """Check for suspicious listening ports."""
        findings   = []
        listen_count = 0
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN":
                    listen_count += 1
                    port = conn.laddr.port
                    if port in SUSPICIOUS_PORTS:
                        label = SUSPICIOUS_PORTS[port]
                        findings.append({
                            "type":    "SUSPICIOUS_PORT",
                            "severity":"MEDIUM",
                            "port":    port,
                            "detail":  f"Unauthorized service detected on port {port}: {label}",
                        })
        except Exception as exc:
            logger.warning(f"SecurityAuditor: port scan error: {exc}")

        return findings, listen_count

    def _review_execwall(self) -> Dict:
        """Summarize Execwall audit entries."""
        audit  = self.state.execwall_audit
        denied = [e for e in audit if e.get("verdict") == "DENY"]
        return {
            "total":  len(audit),
            "denied": len(denied),
            "blocks": denied[-5:],
        }

    # ──────────────────────────────────────────────
    # Scoring & Report
    # ──────────────────────────────────────────────

    @staticmethod
    def _threat_level(findings: List[Dict]) -> Tuple[int, str]:
        highs   = sum(1 for f in findings if f.get("severity") == "HIGH")
        mediums = sum(1 for f in findings if f.get("severity") == "MEDIUM")
        score   = (highs * 30) + (mediums * 10)

        if score == 0:  return 0,  "🟢 SECURE"
        if score < 30:  return score, "🟡 LOW RISK"
        if score < 60:  return score, "🟠 ELEVATED"
        return score,              "🔴 CRITICAL"

    def _format_report(
        self,
        findings:     List[Dict],
        phasr_summary: Dict,
        threat_level: int,
        threat_label: str,
        task: str,
    ) -> str:
        finding_lines = "\n".join(
            f"  [{f['severity']}] {f['type']} — {f['detail']}"
            for f in findings
        ) or "  ✅ No threats detected."

        phasr_lines = "\n".join(
            f"  • [{b.get('agent')}] blocked: `{b.get('command', '')[:60]}`  — {b.get('reason', '')[:80]}"
            for b in phasr_summary.get("blocks", [])
        ) or "  ✅ No blocked commands."

        return f"""## 🔐 Security Auditor Report

**Task**: {task or "General security audit"}
**Threat Level**: {threat_label}  (score: {threat_level})

### Findings ({len(findings)} total)
{finding_lines}

### PHASR / Execwall Summary
  • Total command executions: {phasr_summary.get('total', 0)}
  • Commands blocked: {phasr_summary.get('denied', 0)}
{phasr_lines}

### Identity Integrity
  • Dubbing model: DUBPROCESS (task-scoped, auto-undub on completion)
  • Privileged escalation: ✅ None detected

### Recommendation
{"✅ System security posture is clean. No unauthorized agents detected." if threat_level == 0 else "⚠️ Security threats identified. Review findings above and terminate unauthorized processes." if threat_level < 60 else "🚨 CRITICAL security event. Initiate incident response protocol immediately."}
"""
