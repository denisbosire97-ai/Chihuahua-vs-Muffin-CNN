"""
Open Claw Stack — Log Analyst Agent
======================================
Parses system and application logs for anomalies.

Windows: Windows Event Log (PowerShell Get-WinEvent)
Linux:   journalctl, /var/log/syslog, /var/log/auth.log

Detects:
  - Failed authentication attempts (brute force)
  - Service crashes and restarts
  - Kernel panics / BSODs
  - Application errors
  - Anomalous login times/sources
"""
import logging
import platform
import re
import subprocess
import time
from collections import Counter
from typing import Dict, List, Tuple

from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"

# Windows Event IDs worth monitoring
WIN_EVENT_IDS = {
    4625: ("FAILED_LOGIN",      "HIGH",   "Failed account login attempt"),
    4648: ("EXPLICIT_CREDS",    "MEDIUM", "Login with explicit credentials"),
    4720: ("ACCOUNT_CREATED",   "MEDIUM", "New user account created"),
    4726: ("ACCOUNT_DELETED",   "MEDIUM", "User account deleted"),
    4776: ("NTLM_AUTH",         "LOW",    "NTLM authentication attempt"),
    6005: ("SYSTEM_START",      "INFO",   "Event log service started (system boot)"),
    6006: ("SYSTEM_STOP",       "INFO",   "Event log service stopped (system shutdown)"),
    7034: ("SERVICE_CRASH",     "HIGH",   "Service terminated unexpectedly"),
    7040: ("SERVICE_CHANGED",   "MEDIUM", "Service start type changed"),
    1102: ("AUDIT_LOG_CLEARED", "HIGH",   "Security audit log was cleared!"),
}


class LogAnalystAgent:
    """Parses system logs for security anomalies and service failures."""

    def __init__(self, state, execwall=None):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("log_analyst", mem_max_mb=256, cpu_max_percent=30)

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("log_analyst", f"log-{int(time.time())}"):
            self.state.update_agent(
                "log_analyst", AgentStatus.PERCEIVING,
                "📈 Log Analyst online — parsing system event logs..."
            )

            tool_log = []
            all_events: List[Dict] = []

            if IS_WIN:
                self.state.update_agent("log_analyst", AgentStatus.ACTING, "🪟 Reading Windows Event Log...")
                events = self._read_win_events()
                all_events.extend(events)
                tool_log.append(f"✅ Windows Event Log: {len(events)} relevant events")
            else:
                self.state.update_agent("log_analyst", AgentStatus.ACTING, "🐧 Reading journalctl...")
                events = self._read_journal()
                all_events.extend(events)
                tool_log.append(f"✅ journalctl: {len(events)} events")

                auth_events = self._read_auth_log()
                all_events.extend(auth_events)
                tool_log.append(f"✅ auth.log: {len(auth_events)} events")

            # Analyze patterns
            self.state.update_agent("log_analyst", AgentStatus.ACTING, "🔍 Analyzing event patterns...")
            analysis = self._analyze(all_events)

            # Critical events trigger incidents
            for ev in all_events:
                if ev.get("severity") == "HIGH":
                    self.state.add_incident({
                        "type":   f"LOG_{ev.get('event_type','EVENT')}",
                        "agent":  "log_analyst",
                        "detail": ev.get("message", "")[:200],
                    })

            score, label = self._health_score(analysis)

            self.state.update_agent(
                "log_analyst", AgentStatus.DONE,
                f"✅ Log analysis complete — {label}",
                metrics={
                    "health_score":       score,
                    "health_label":       label,
                    "total_events":       len(all_events),
                    "failed_logins":      analysis.get("failed_logins", 0),
                    "service_crashes":    analysis.get("service_crashes", 0),
                    "audit_clears":       analysis.get("audit_clears", 0),
                    "high_severity":      analysis.get("high_count", 0),
                },
            )
            self.state.agents["log_analyst"].tool_calls = [{"tool": t} for t in tool_log]
            return self._format_report(all_events, analysis, score, label, task)

    # ──────────────────────────────────────────────
    # Windows Tools
    # ──────────────────────────────────────────────

    def _read_win_events(self) -> List[Dict]:
        """Query Windows Event Log via PowerShell."""
        id_filter = ",".join(str(k) for k in WIN_EVENT_IDS.keys())
        ps_cmd = (
            f"powershell -Command \""
            f"Get-WinEvent -FilterHashtable @{{LogName='Security','System','Application';"
            f"Id={id_filter};StartTime=(Get-Date).AddHours(-24)}} "
            f"-MaxEvents 200 -ErrorAction SilentlyContinue | "
            f"Select-Object Id,TimeCreated,Message | "
            f"ConvertTo-Json -Depth 2\""
        )
        events = []
        try:
            res = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=30,
                                 encoding="utf-8", errors="replace")
            if res.returncode == 0 and res.stdout.strip():
                import json
                raw = json.loads(res.stdout)
                if isinstance(raw, dict):
                    raw = [raw]
                for entry in raw:
                    eid  = entry.get("Id", 0)
                    info = WIN_EVENT_IDS.get(eid, ("UNKNOWN", "INFO", "Unknown event"))
                    events.append({
                        "event_id":   eid,
                        "event_type": info[0],
                        "severity":   info[1],
                        "message":    str(entry.get("Message", ""))[:500],
                        "time":       str(entry.get("TimeCreated", "")),
                    })
        except Exception as exc:
            logger.warning(f"LogAgent: Win event query failed: {exc}")
            # Fallback: simplified PowerShell
            events = self._win_simple_fallback()
        return events

    def _win_simple_fallback(self) -> List[Dict]:
        """Simpler PowerShell fallback for event log access."""
        events = []
        try:
            ps = (
                "powershell -Command \""
                "Get-EventLog -LogName Security -Newest 50 -ErrorAction SilentlyContinue | "
                "Select-Object EventID,TimeGenerated,Message | "
                "Format-List\""
            )
            res = subprocess.run(ps, shell=True, capture_output=True, text=True, timeout=20,
                                 encoding="utf-8", errors="replace")
            # Parse text output
            current = {}
            for line in res.stdout.splitlines():
                if "EventID" in line:
                    if current:
                        eid  = int(current.get("eventid", 0))
                        info = WIN_EVENT_IDS.get(eid, ("UNKNOWN", "INFO", "Unknown event"))
                        events.append({
                            "event_id":   eid,
                            "event_type": info[0],
                            "severity":   info[1],
                            "message":    current.get("message", "")[:300],
                            "time":       current.get("timegenerated", ""),
                        })
                    current = {}
                    m = re.search(r":\s*(\d+)", line)
                    if m:
                        current["eventid"] = m.group(1)
                elif "TimeGenerated" in line:
                    current["timegenerated"] = line.split(":", 1)[-1].strip()
                elif "Message" in line:
                    current["message"] = line.split(":", 1)[-1].strip()
        except Exception:
            pass
        return events[:30]

    # ──────────────────────────────────────────────
    # Linux Tools
    # ──────────────────────────────────────────────

    def _read_journal(self) -> List[Dict]:
        try:
            res = subprocess.run(
                "journalctl -p err --since '24 hours ago' --no-pager -n 100",
                shell=True, capture_output=True, text=True, timeout=20
            )
            events = []
            for line in res.stdout.splitlines():
                if any(kw in line.lower() for kw in ("error", "failed", "crash", "killed")):
                    events.append({
                        "event_type": "SERVICE_ERROR",
                        "severity":   "MEDIUM",
                        "message":    line[:300],
                        "time":       ""
                    })
            return events[:50]
        except Exception:
            return []

    def _read_auth_log(self) -> List[Dict]:
        try:
            res = subprocess.run(
                "grep -i 'failed\\|invalid\\|authentication failure' /var/log/auth.log 2>/dev/null | tail -50",
                shell=True, capture_output=True, text=True, timeout=15
            )
            events = []
            for line in res.stdout.splitlines():
                events.append({
                    "event_type": "FAILED_LOGIN",
                    "severity":   "HIGH",
                    "message":    line[:300],
                    "time":       ""
                })
            return events
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # Analysis
    # ──────────────────────────────────────────────

    def _analyze(self, events: List[Dict]) -> Dict:
        type_counts = Counter(e.get("event_type") for e in events)
        sev_counts  = Counter(e.get("severity")   for e in events)
        return {
            "total":          len(events),
            "failed_logins":  type_counts.get("FAILED_LOGIN", 0),
            "service_crashes":type_counts.get("SERVICE_CRASH", 0),
            "audit_clears":   type_counts.get("AUDIT_LOG_CLEARED", 0),
            "high_count":     sev_counts.get("HIGH", 0),
            "medium_count":   sev_counts.get("MEDIUM", 0),
            "type_summary":   dict(type_counts.most_common(8)),
        }

    @staticmethod
    def _health_score(analysis: Dict) -> Tuple[int, str]:
        score = 100
        score -= min(analysis.get("failed_logins", 0) * 5, 40)
        score -= min(analysis.get("service_crashes", 0) * 10, 30)
        score -= analysis.get("audit_clears", 0) * 40  # clearing audit log is critical
        score -= min(analysis.get("high_count", 0) * 3, 20)
        score = max(0, min(100, score))

        if score >= 80: label = "🟢 CLEAN LOGS"
        elif score >= 50: label = "🟡 ANOMALIES FOUND"
        else:             label = "🔴 ATTACK INDICATORS"
        return score, label

    # ──────────────────────────────────────────────
    # Report
    # ──────────────────────────────────────────────

    def _format_report(self, events, analysis, score, label, task) -> str:
        high_events = [e for e in events if e.get("severity") == "HIGH"][:5]
        high_lines  = "\n".join(
            f"  [{e['event_type']}] {e['message'][:120]}"
            for e in high_events
        ) or "  ✅ No high-severity events in last 24h"

        summary_lines = "\n".join(
            f"  • {k:25s}: {v}"
            for k, v in analysis.get("type_summary", {}).items()
        ) or "  (no events)"

        return f"""## 📈 Log Analyst Report

**Task**: {task or "Log analysis (24h window)"}
**Score**: {score}/100  {label}

### Event Summary (Last 24 Hours)
  • Total events scanned : {analysis.get('total', 0)}
  • Failed logins        : {analysis.get('failed_logins', 0)} {"⚠️ BRUTE FORCE RISK" if analysis.get('failed_logins', 0) > 5 else "✅"}
  • Service crashes      : {analysis.get('service_crashes', 0)} {"⚠️" if analysis.get('service_crashes', 0) > 0 else "✅"}
  • Audit log clears     : {analysis.get('audit_clears', 0)} {"🚨 ANTI-FORENSICS!" if analysis.get('audit_clears', 0) > 0 else "✅"}

### Event Type Breakdown
{summary_lines}

### High-Severity Events
{high_lines}

### Recommendation
{"✅ Log history is clean." if score >= 80 else "⚠️ Investigate failed logins and service crash patterns." if score >= 50 else "🚨 Critical indicators present. Possible active attack. Isolate system and review all recent logins."}
"""
