"""
Open Claw Stack — Package Manager Agent
=========================================
Audits installed Python packages and system packages for:
  - Outdated versions
  - Known CVE vulnerabilities (via pip-audit)
  - Missing critical security patches

Cross-platform: pip (all), winget (Windows), apt (Linux)
"""
import json
import logging
import platform
import subprocess
import time
from typing import Dict, List, Tuple

from core.execwall import Execwall, PolicyViolationError
from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"


class PackageManagerAgent:
    """Audits packages for outdated versions and known CVE vulnerabilities."""

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("package_manager", mem_max_mb=256, cpu_max_percent=30)

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("package_manager", f"pkg-{int(time.time())}"):
            self.state.update_agent(
                "package_manager", AgentStatus.PERCEIVING,
                "📦 Package Manager online — scanning dependencies..."
            )

            tool_log = []
            results  = {}

            # 1. Outdated pip packages
            self.state.update_agent("package_manager", AgentStatus.ACTING, "🔍 Checking for outdated pip packages...")
            outdated, total = self._check_pip_outdated()
            results["pip_outdated"] = outdated
            results["pip_total"]    = total
            tool_log.append(f"✅ pip: {total} packages, {len(outdated)} outdated")

            # 2. pip-audit for CVEs
            self.state.update_agent("package_manager", AgentStatus.ACTING, "🔒 Running pip-audit CVE scan...")
            vulns = self._run_pip_audit()
            results["vulnerabilities"] = vulns
            tool_log.append(f"✅ pip-audit: {len(vulns)} vulnerabilities found")

            if vulns:
                for v in vulns[:3]:
                    self.state.add_incident({
                        "type":    "PACKAGE_CVE",
                        "agent":   "package_manager",
                        "detail":  f"{v.get('name','?')} {v.get('version','?')}: {v.get('id','?')}",
                    })

            # 3. System package manager
            self.state.update_agent("package_manager", AgentStatus.ACTING, "🖥️ Checking system package manager...")
            sys_updates = self._check_system_packages()
            results["system_updates"] = sys_updates
            tool_log.append(f"✅ System packages: {len(sys_updates)} updates available")

            # Score
            score, label = self._health_score(outdated, vulns)

            self.state.update_agent(
                "package_manager", AgentStatus.DONE,
                f"✅ Package audit complete — {label}",
                metrics={
                    "health_score":   score,
                    "health_label":   label,
                    "pip_outdated":   len(outdated),
                    "cve_count":      len(vulns),
                    "system_updates": len(sys_updates),
                    "total_packages": total,
                },
            )
            self.state.agents["package_manager"].tool_calls = [{"tool": t} for t in tool_log]
            return self._format_report(results, score, label, task)

    # ──────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────

    def _check_pip_outdated(self) -> Tuple[List[Dict], int]:
        try:
            # Total count
            all_res = subprocess.run(
                "pip list --format=json", shell=True, capture_output=True, text=True, timeout=20
            )
            all_pkgs = json.loads(all_res.stdout) if all_res.returncode == 0 else []
            total = len(all_pkgs)

            # Outdated
            out_res = subprocess.run(
                "pip list --outdated --format=json", shell=True, capture_output=True, text=True, timeout=30
            )
            outdated = json.loads(out_res.stdout) if out_res.returncode == 0 else []
            return outdated[:20], total
        except Exception as exc:
            logger.warning(f"PackageAgent: pip check failed: {exc}")
            return [], 0

    def _run_pip_audit(self) -> List[Dict]:
        """Run pip-audit to find CVEs. Falls back to empty list if not installed."""
        try:
            res = subprocess.run(
                "pip-audit --format=json --progress-spinner=off",
                shell=True, capture_output=True, text=True, timeout=60
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                vulns = []
                for dep in data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        vulns.append({
                            "name":    dep.get("name"),
                            "version": dep.get("version"),
                            "id":      vuln.get("id"),
                            "aliases": vuln.get("aliases", []),
                            "fix":     vuln.get("fix_versions", []),
                        })
                return vulns
            # Non-zero means vulnerabilities found (also valid JSON output)
            try:
                data  = json.loads(res.stdout)
                vulns = []
                for dep in data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        vulns.append({
                            "name":    dep.get("name"),
                            "version": dep.get("version"),
                            "id":      vuln.get("id"),
                            "fix":     vuln.get("fix_versions", []),
                        })
                return vulns
            except Exception:
                return []
        except FileNotFoundError:
            logger.info("PackageAgent: pip-audit not installed — run: pip install pip-audit")
            return []
        except Exception as exc:
            logger.warning(f"PackageAgent: pip-audit error: {exc}")
            return []

    def _check_system_packages(self) -> List[str]:
        try:
            if IS_WIN:
                res = subprocess.run(
                    "winget upgrade --include-unknown",
                    shell=True, capture_output=True, text=True, timeout=30
                )
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and "---" not in l]
                return lines[2:22] if len(lines) > 2 else []
            else:
                res = subprocess.run(
                    "apt list --upgradable 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=20
                )
                return [l for l in res.stdout.splitlines() if "upgradable" in l][:20]
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────

    @staticmethod
    def _health_score(outdated: List, vulns: List) -> Tuple[int, str]:
        score = 100
        score -= min(len(outdated) * 2, 30)   # max -30 for outdated
        score -= min(len(vulns) * 15, 60)     # max -60 for CVEs
        score = max(0, score)
        if score >= 80: label = "🟢 CLEAN"
        elif score >= 50: label = "🟡 PATCHING NEEDED"
        else:             label = "🔴 VULNERABLE"
        return score, label

    # ──────────────────────────────────────────────
    # Report
    # ──────────────────────────────────────────────

    def _format_report(self, results, score, label, task) -> str:
        outdated  = results.get("pip_outdated", [])
        vulns     = results.get("vulnerabilities", [])
        sys_upd   = results.get("system_updates", [])
        total     = results.get("pip_total", 0)

        outdated_rows = "\n".join(
            f"  • {p.get('name','?'):30s} {p.get('version','?'):12s} -> {p.get('latest_version','?')}"
            for p in outdated[:10]
        ) or "  ✅ All packages up to date"

        vuln_rows = "\n".join(
            f"  🚨 [{v.get('id','?')}] {v.get('name','?')} {v.get('version','?')}"
            f"  Fix: {', '.join(v.get('fix', [])) or 'manual review required'}"
            for v in vulns[:8]
        ) or "  ✅ No known CVEs found"

        sys_rows = "\n".join(f"  • {u}" for u in sys_upd[:5]) or "  ✅ System packages current"

        return f"""## 📦 Package Manager Report

**Task**: {task or "Dependency audit"}
**Score**: {score}/100  {label}

### Python Packages ({total} installed, {len(outdated)} outdated)
{outdated_rows}

### CVE Vulnerabilities ({len(vulns)} found)
{vuln_rows}

### System Package Updates ({len(sys_upd)} available)
{sys_rows}

### Recommendation
{"✅ Dependency posture is clean." if score >= 80 else "⚠️ Run: pip install --upgrade <packages> and pip-audit --fix to patch vulnerabilities." if score >= 50 else "🚨 Critical CVEs present. Patch immediately: pip-audit --fix"}
"""
