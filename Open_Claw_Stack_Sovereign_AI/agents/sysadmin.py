"""
Open Claw Stack — SysAdmin Agent
==================================
Specialist agent for system health monitoring.

Tools (cross-platform via psutil):
  - CPU utilization & top processes
  - Memory (RAM) usage
  - Disk space across all partitions
  - Service / process status
  - System uptime and OS info

Identifies resource bottlenecks and OS-level issues.
"""
import logging
import platform
import time
from typing import Dict, List, Tuple

import psutil

from core.execwall import Execwall, PolicyViolationError
from core.sandbox import Identity, Cgroup
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)
IS_WIN = platform.system() == "Windows"


class SysAdminAgent:
    """Monitors system health: CPU, RAM, disk, and processes."""

    def __init__(self, state: SharedState, execwall: Execwall):
        self.state    = state
        self.execwall = execwall
        self.cgroup   = Cgroup("sysadmin", mem_max_mb=512, cpu_max_percent=50)

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str = "") -> str:
        with Identity("sysadmin", f"sys-{int(time.time())}"):
            self.state.update_agent(
                "sysadmin", AgentStatus.PERCEIVING,
                "🖥️ SysAdmin online — gathering system telemetry..."
            )

            tool_log = []

            # 1. CPU
            self.state.update_agent("sysadmin", AgentStatus.ACTING, "⚙️ Measuring CPU utilization...")
            cpu_data = self._cpu_info()
            tool_log.append(f"✅ CPU: {cpu_data['percent']}% utilization")

            # 2. Memory
            self.state.update_agent("sysadmin", AgentStatus.ACTING, "💾 Analyzing RAM usage...")
            mem_data = self._memory_info()
            tool_log.append(f"✅ RAM: {mem_data['used_gb']:.1f}GB / {mem_data['total_gb']:.1f}GB")

            # 3. Disk
            self.state.update_agent("sysadmin", AgentStatus.ACTING, "💿 Scanning disk partitions...")
            disk_data = self._disk_info()
            tool_log.append(f"✅ Disk: {len(disk_data)} partitions scanned")

            # 4. Top processes
            self.state.update_agent("sysadmin", AgentStatus.ACTING, "📊 Identifying top resource consumers...")
            top_procs = self._top_processes()
            tool_log.append(f"✅ Processes: top {len(top_procs)} identified")

            # 5. System info
            sys_info = self._system_info()
            tool_log.append(f"✅ OS: {sys_info['os']} | Uptime: {sys_info['uptime']}")

            # 6. Cgroup check
            within, cgroup_msg, cgroup_metrics = self.cgroup.check_limits()
            tool_log.append(f"{'✅' if within else '⚠️'} Cgroup: {cgroup_msg}")
            if not within:
                self.state.add_incident({
                    "type":   "CGROUP_LIMIT",
                    "agent":  "sysadmin",
                    "detail": cgroup_msg,
                })

            # 7. Health score
            score, label = self._health_score(cpu_data, mem_data, disk_data)

            self.state.update_agent(
                "sysadmin", AgentStatus.DONE,
                f"✅ System health: {label} ({score}/100)",
                metrics={
                    "health_score":  score,
                    "health_label":  label,
                    "cpu_pct":       cpu_data["percent"],
                    "ram_pct":       mem_data["percent"],
                    "disk_min_free": min((d["free_pct"] for d in disk_data), default=100),
                    "uptime":        sys_info["uptime"],
                    "process_count": cpu_data["count"],
                },
            )
            self.state.agents["sysadmin"].tool_calls = [{"tool": t} for t in tool_log]

            return self._format_report(
                cpu_data, mem_data, disk_data, top_procs,
                sys_info, score, label, task, cgroup_msg,
            )

    # ──────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────

    def _cpu_info(self) -> Dict:
        cpu_pct   = psutil.cpu_percent(interval=1.0)
        cpu_count = psutil.cpu_count(logical=True)
        freq      = psutil.cpu_freq()
        load_avg  = [0, 0, 0]
        try:
            load_avg = list(psutil.getloadavg())
        except AttributeError:
            pass   # Windows doesn't have getloadavg()
        return {
            "percent":   cpu_pct,
            "count":     cpu_count,
            "freq_mhz":  round(freq.current, 0) if freq else 0,
            "load_avg":  load_avg,
        }

    def _memory_info(self) -> Dict:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return {
            "total_gb":  round(vm.total  / 1e9, 2),
            "used_gb":   round(vm.used   / 1e9, 2),
            "free_gb":   round(vm.free   / 1e9, 2),
            "percent":   vm.percent,
            "swap_total_gb": round(sw.total / 1e9, 2),
            "swap_used_gb":  round(sw.used  / 1e9, 2),
        }

    def _disk_info(self) -> List[Dict]:
        partitions = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions.append({
                    "device":     part.device,
                    "mountpoint": part.mountpoint,
                    "fstype":     part.fstype,
                    "total_gb":   round(usage.total / 1e9, 2),
                    "used_gb":    round(usage.used  / 1e9, 2),
                    "free_gb":    round(usage.free  / 1e9, 2),
                    "used_pct":   usage.percent,
                    "free_pct":   round(100 - usage.percent, 1),
                })
            except (PermissionError, OSError):
                pass
        return partitions

    def _top_processes(self, n: int = 8) -> List[Dict]:
        procs = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # Sort by CPU then memory
        procs.sort(key=lambda p: (p.get("cpu_percent") or 0), reverse=True)
        return procs[:n]

    def _system_info(self) -> Dict:
        boot_time = psutil.boot_time()
        uptime_s  = time.time() - boot_time
        hours     = int(uptime_s // 3600)
        minutes   = int((uptime_s % 3600) // 60)
        uname     = platform.uname()
        return {
            "os":       f"{uname.system} {uname.release}",
            "machine":  uname.machine,
            "node":     uname.node,
            "uptime":   f"{hours}h {minutes}m",
            "python":   platform.python_version(),
        }

    # ──────────────────────────────────────────────
    # Scoring & Report
    # ──────────────────────────────────────────────

    @staticmethod
    def _health_score(cpu: Dict, mem: Dict, disks: List[Dict]) -> Tuple[int, str]:
        score = 100
        if cpu["percent"] > 90:  score -= 30
        elif cpu["percent"] > 70: score -= 15
        elif cpu["percent"] > 50: score -= 5

        if mem["percent"] > 90:  score -= 30
        elif mem["percent"] > 75: score -= 15
        elif mem["percent"] > 60: score -= 5

        for d in disks:
            if d["used_pct"] > 95: score -= 20
            elif d["used_pct"] > 80: score -= 10

        score = max(0, min(100, score))
        if score >= 80: label = "🟢 HEALTHY"
        elif score >= 50: label = "🟡 DEGRADED"
        else:             label = "🔴 CRITICAL"
        return score, label

    def _format_report(
        self, cpu, mem, disks, top_procs, sys_info,
        score, label, task, cgroup_msg
    ) -> str:
        proc_rows = "\n".join(
            f"  {i+1:2}. {p.get('name','?')[:30]:30s}  CPU: {p.get('cpu_percent',0):5.1f}%  "
            f"MEM: {p.get('memory_percent',0):4.1f}%"
            for i, p in enumerate(top_procs)
        )
        disk_rows = "\n".join(
            f"  • {d['mountpoint']:15s}  {d['used_gb']:6.1f}GB / {d['total_gb']:6.1f}GB  "
            f"({d['used_pct']:.1f}% used)  {'⚠️ LOW' if d['used_pct'] > 85 else '✅'}"
            for d in disks
        )
        return f"""## 🖥️ SysAdmin Report

**Task**: {task or "General system health check"}
**Health Score**: {score}/100  {label}

### CPU
  • Utilization : {cpu['percent']}%
  • Cores       : {cpu['count']} (logical)
  • Frequency   : {cpu['freq_mhz']:.0f} MHz

### Memory (RAM)
  • Used/Total  : {mem['used_gb']:.1f}GB / {mem['total_gb']:.1f}GB ({mem['percent']}%)
  • Free        : {mem['free_gb']:.1f}GB
  • Swap        : {mem['swap_used_gb']:.1f}GB / {mem['swap_total_gb']:.1f}GB

### Disk Partitions
{disk_rows or "  (no readable partitions)"}

### Top Processes (by CPU)
{proc_rows or "  (unable to enumerate)"}

### System Info
  • OS          : {sys_info['os']}
  • Hostname    : {sys_info['node']}
  • Uptime      : {sys_info['uptime']}
  • Python      : {sys_info['python']}

### Cgroup Governance
  • Status      : {cgroup_msg}

### Recommendation
{"✅ System resources within normal operating parameters." if score >= 80 else "⚠️ Resource pressure detected. Consider terminating high-CPU processes or increasing RAM." if score >= 50 else "🚨 Critical resource exhaustion. Immediate intervention required."}
"""
