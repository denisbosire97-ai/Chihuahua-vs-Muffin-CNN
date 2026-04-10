"""
Open Claw Stack — Network Engineer Agent
=========================================
Specialist agent for connectivity analysis and port security posture.

Tools:
  - ping          — latency and packet loss
  - tracert/traceroute — path analysis
  - nslookup      — DNS resolution
  - ipconfig/ip   — interface configuration
  - netstat       — active connections
  - nmap          — port scan for unauthorized services and Shadow AI detection
"""
import logging
import platform
import re
import time
from typing import Dict, Tuple

from core.execwall import Execwall, PolicyViolationError
from core.sandbox import Identity, Cgroup, Namespace
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"

# DNS targets for resolution testing
DNS_TARGETS = ["google.com", "cloudflare.com", "github.com"]

# Ping targets for latency measurement
PING_TARGETS = [
    ("8.8.8.8",       "Google DNS"),
    ("1.1.1.1",       "Cloudflare DNS"),
    ("192.168.1.1",   "Default Gateway (common)"),
]


class NetworkEngineerAgent:
    """Monitors network health, latency, DNS, and connectivity."""

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("network_engineer", mem_max_mb=256, cpu_max_percent=40)
        self.ns       = Namespace("network_engineer", net_isolated=False)  # needs host network

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("network_engineer", f"net-{int(time.time())}"):
            self.state.update_agent(
                "network_engineer", AgentStatus.PERCEIVING,
                "🌐 Network Engineer online — beginning connectivity analysis..."
            )

            results    = {}
            tool_log   = []

            # 1. Interface info
            iface_info = self._get_interfaces()
            results["interfaces"] = iface_info
            tool_log.append("✅ Interface scan")
            self.state.update_agent(
                "network_engineer", AgentStatus.ACTING,
                "📡 Scanning network interfaces...",
                metrics={"tool": "ipconfig/ip"},
            )

            # 2. Ping targets
            ping_results = {}
            for ip, label in PING_TARGETS:
                latency, loss = self._ping(ip)
                ping_results[label] = {"ip": ip, "latency_ms": latency, "loss_pct": loss}
                tool_log.append(f"📶 Ping {ip}: {latency}ms / {loss}% loss")
                self.state.update_agent(
                    "network_engineer", AgentStatus.ACTING,
                    f"🏓 Ping {label} ({ip}): {latency}ms",
                    metrics={"last_ping_ms": latency, "last_ping_target": label},
                )
            results["ping"] = ping_results

            # 3. DNS resolution
            dns_results = {}
            for host in DNS_TARGETS:
                resolved, ms = self._dns_resolve(host)
                dns_results[host] = {"resolved": resolved, "response_ms": ms}
                tool_log.append(f"🔍 DNS {host}: {resolved or 'FAILED'} ({ms}ms)")
            results["dns"] = dns_results
            self.state.update_agent(
                "network_engineer", AgentStatus.ACTING,
                f"🔍 DNS checks complete — {sum(1 for v in dns_results.values() if v['resolved'])} / {len(dns_results)} resolved",
            )

            # 4. Active connections (netstat)
            conn_summary = self._get_connections()
            results["connections"] = conn_summary
            tool_log.append("Active connection scan (netstat)")

            # 5. nmap port scan (Shadow AI + unauthorized service detection)
            self.state.update_agent(
                "network_engineer", AgentStatus.ACTING,
                "nmap: scanning localhost for unauthorized services...",
            )
            nmap_result = self._nmap_scan()
            results["nmap"] = nmap_result
            tool_log.append(f"nmap: {nmap_result.get('status','?')} — {nmap_result.get('open_ports',0)} open ports")

            # Shadow AI ports flagged by nmap
            for alert in nmap_result.get("shadow_ai_ports", []):
                self.state.add_incident({
                    "type":   "SHADOW_AI_PORT_NMAP",
                    "agent":  "network_engineer",
                    "detail": alert,
                })

            # 6. Score & report
            score, label = self._health_score(ping_results, dns_results)
            results["health_score"] = score
            results["health_label"] = label

            self.state.update_agent(
                "network_engineer", AgentStatus.DONE,
                f"Analysis complete — Network Health: {label} ({score}/100)",
                metrics={
                    "health_score": score,
                    "health_label": label,
                    "dns_success":  sum(1 for v in dns_results.values() if v["resolved"]),
                    "interfaces":   iface_info[:80],
                    "nmap_open_ports": results.get("nmap", {}).get("open_ports", "?"),
                    "tool_calls":   len(tool_log),
                },
            )

            self.state.agents["network_engineer"].tool_calls = [
                {"tool": t} for t in tool_log
            ]

            return self._format_report(results, task)

    # ──────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────

    def _get_interfaces(self) -> str:
        cmd = "ipconfig /all" if IS_WIN else "ip addr"
        try:
            stdout, stderr, rc = self.execwall.execute(cmd, "network_engineer", timeout=10)
            return stdout[:2000] if stdout else f"(error: {stderr[:200]})"
        except PolicyViolationError as e:
            return f"Blocked: {e}"

    def _ping(self, target: str) -> Tuple[float, float]:
        """Returns (avg_latency_ms, loss_pct)."""
        cmd = (
            f"ping -n 4 {target}" if IS_WIN
            else f"ping -c 4 -W 2 {target}"
        )
        try:
            stdout, _, rc = self.execwall.execute(cmd, "network_engineer", timeout=20)
            return self._parse_ping(stdout, IS_WIN)
        except PolicyViolationError:
            return -1.0, 100.0
        except Exception:
            return -1.0, 100.0

    @staticmethod
    def _parse_ping(output: str, is_win: bool) -> Tuple[float, float]:
        try:
            if is_win:
                # "Average = 12ms"
                m = re.search(r"Average\s*=\s*(\d+)ms", output)
                avg = float(m.group(1)) if m else -1.0
                # "Lost = 0 (0% loss)"
                m2 = re.search(r"Lost\s*=\s*\d+\s*\((\d+)%", output)
                loss = float(m2.group(1)) if m2 else 100.0
            else:
                m    = re.search(r"rtt min/avg/max.*?=\s*[\d.]+/([\d.]+)/", output)
                avg  = float(m.group(1)) if m else -1.0
                m2   = re.search(r"(\d+)%\s*packet loss", output)
                loss = float(m2.group(1)) if m2 else 100.0
            return avg, loss
        except Exception:
            return -1.0, 100.0

    def _dns_resolve(self, host: str) -> Tuple[str, float]:
        cmd = f"nslookup {host}"
        try:
            t0 = time.time()
            stdout, _, rc = self.execwall.execute(cmd, "network_engineer", timeout=10)
            ms = round((time.time() - t0) * 1000, 1)
            m  = re.search(r"Address(?:es)?:\s*([\d.]+)", stdout)
            ip = m.group(1) if m else ""
            return ip, ms
        except PolicyViolationError:
            return "", -1.0

    def _get_connections(self) -> str:
        cmd = "netstat -an" if IS_WIN else "ss -tuln"
        try:
            stdout, _, _ = self.execwall.execute(cmd, "network_engineer", timeout=15)
            return stdout[:1500]
        except PolicyViolationError as e:
            return f"Blocked: {e}"

    # Shadow AI port signatures (same ports Execwall PHASR monitors)
    _SHADOW_AI_PORTS = {
        11434: "Ollama (local LLM runtime)",
        8080:  "LM Studio / generic AI server",
        8888:  "Jupyter Notebook (unauthenticated notebook server)",
        7860:  "Gradio (ML demo app)",
        5000:  "Flask / ML inference server",
        3000:  "Generic dev server (potential LLM UI)",
        4891:  "GPT4All",
        1234:  "LM Studio API",
    }

    def _nmap_scan(self, target: str = "localhost") -> dict:
        """
        Run nmap against localhost to identify open ports.
        Flags any ports matching known Shadow AI or unauthorized services.
        Falls back to netstat-based port parsing if nmap is not installed.
        """
        # Try nmap first
        nmap_cmd = f"nmap -sT -p 1-65535 --open -T4 {target}" if not IS_WIN else f"nmap -sT -p 1-10000 --open {target}"
        try:
            stdout, stderr, rc = self.execwall.execute(nmap_cmd, "network_engineer", timeout=60)
            if rc == 0 and stdout:
                return self._parse_nmap_output(stdout)
        except PolicyViolationError:
            logger.info("NetworkAgent: nmap blocked by Execwall — using netstat fallback")
        except Exception as exc:
            logger.info(f"NetworkAgent: nmap unavailable ({exc}) — using netstat fallback")

        # Fallback: parse open ports from netstat
        return self._nmap_via_netstat()

    def _parse_nmap_output(self, output: str) -> dict:
        """Parse nmap text output into structured results."""
        open_ports = []
        for line in output.splitlines():
            m = re.match(r"(\d+)/tcp\s+(open)\s+(\S+)", line)
            if m:
                port, state, service = int(m.group(1)), m.group(2), m.group(3)
                shadow_label = self._SHADOW_AI_PORTS.get(port)
                open_ports.append({
                    "port": port, "state": state, "service": service,
                    "shadow_ai": shadow_label,
                })
        shadow = [f"Port {p['port']} ({p['shadow_ai']})" for p in open_ports if p.get("shadow_ai")]
        return {
            "status":          "nmap",
            "open_ports":      len(open_ports),
            "ports":           open_ports[:30],
            "shadow_ai_ports": shadow,
        }

    def _nmap_via_netstat(self) -> dict:
        """Extract open listening ports from netstat as nmap fallback."""
        try:
            cmd = "netstat -ano" if IS_WIN else "ss -tlnp"
            stdout, _, _ = self.execwall.execute(cmd, "network_engineer", timeout=15)
            open_ports = []
            for line in stdout.splitlines():
                m = re.search(r"[:\s](\d{2,5})\s.*LISTEN", line)
                if m:
                    port = int(m.group(1))
                    shadow_label = self._SHADOW_AI_PORTS.get(port)
                    open_ports.append({"port": port, "state": "open", "service": "?", "shadow_ai": shadow_label})
            shadow = [f"Port {p['port']} ({p['shadow_ai']})" for p in open_ports if p.get("shadow_ai")]
            return {
                "status":          "netstat-fallback",
                "open_ports":      len(open_ports),
                "ports":           open_ports[:30],
                "shadow_ai_ports": shadow,
            }
        except Exception:
            return {"status": "unavailable", "open_ports": 0, "ports": [], "shadow_ai_ports": []}

    # ──────────────────────────────────────────────
    # Scoring & Report
    # ──────────────────────────────────────────────

    @staticmethod
    def _health_score(ping: dict, dns: dict) -> Tuple[int, str]:
        score = 100
        for data in ping.values():
            if data["latency_ms"] < 0:       score -= 20
            elif data["latency_ms"] > 200:    score -= 10
            elif data["latency_ms"] > 100:    score -= 5
            if data["loss_pct"] > 0:          score -= int(data["loss_pct"] / 5)
        for data in dns.values():
            if not data["resolved"]:          score -= 10
        score = max(0, min(100, score))
        if score >= 80: label = "🟢 HEALTHY"
        elif score >= 50: label = "🟡 DEGRADED"
        else:             label = "🔴 CRITICAL"
        return score, label

    def _format_report(self, results: dict, task: str) -> str:
        ping   = results.get("ping", {})
        dns    = results.get("dns", {})
        score  = results.get("health_score", 0)
        label  = results.get("health_label", "UNKNOWN")
        conns  = results.get("connections", "")
        nmap   = results.get("nmap", {})

        ping_rows = "\n".join(
            f"  {name:30s} {d['ip']:15s}  {d['latency_ms']:>7.1f}ms  {d['loss_pct']:>5.1f}% loss"
            for name, d in ping.items()
        )
        dns_rows = "\n".join(
            f"  {host:20s}  {'OK ' + ip if ip else 'FAILED':20s}  {ms:.0f}ms"
            for host, (ip, ms) in (
                (h, (v["resolved"], v["response_ms"])) for h, v in dns.items()
            )
        )
        listen_count = conns.count("LISTEN") if conns else 0

        nmap_ports = nmap.get("open_ports", "?")
        nmap_status = nmap.get("status", "?")
        shadow_lines = "\n".join(
            f"  SHADOW AI PORT DETECTED: {s}" for s in nmap.get("shadow_ai_ports", [])
        ) or "  No suspicious ports detected"

        return f"""## Network Engineer Report

**Task**: {task or "General connectivity analysis"}
**Overall Score**: {score}/100  {label}

### Latency & Packet Loss
{ping_rows or "  (no results)"}

### DNS Resolution
{dns_rows or "  (no results)"}

### Port Scan (nmap / {nmap_status})
  Open ports: {nmap_ports}
{shadow_lines}

### Active Connections
  LISTEN ports detected: {listen_count}

### Recommendation
{"Network operating normally." if score >= 80 else "Network degradation detected. Check router/gateway and ISP status." if score >= 50 else "Critical network failure. Check physical connection and DNS settings."}
"""
