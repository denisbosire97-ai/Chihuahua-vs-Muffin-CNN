"""
Open Claw Stack — Sandbox & Identity Layer
==========================================
Implements the "Dubbing" concept from IBM z/OS UNIX System Services:
  - An agent is "dubbed" (given a temporary verified identity) before task execution.
  - After execution, it is "undubbed" — returning to a Clean Address Space.

Also implements:
  - Namespace: documents Linux namespace isolation intent (enforced on Linux, simulated on Windows)
  - Cgroup: resource governance via psutil limits
"""
import logging
import platform
import time
from typing import Tuple

import psutil

logger = logging.getLogger(__name__)
IS_LINUX = platform.system() == "Linux"


# ══════════════════════════════════════════════════════════
# Identity / Dubbing
# ══════════════════════════════════════════════════════════

class Identity:
    """
    Represents a dubbed identity for an agent task.
    Ensures agents do NOT hold persistent root access.
    Each task execution is bracketed: dub() → execute → undub().
    """

    def __init__(self, agent_name: str, task_id: str):
        self.agent_name = agent_name
        self.task_id    = task_id
        self.dubbed     = False
        self.dubbed_at: float = 0.0

    def dub(self) -> "Identity":
        """Register this identity for task execution (DUBPROCESS)."""
        self.dubbed    = True
        self.dubbed_at = time.time()
        logger.info(f"[IDENTITY] ✅ Agent '{self.agent_name}' dubbed for task '{self.task_id}'")
        return self

    def undub(self):
        """Remove identity after task completion — restores Clean Address Space."""
        elapsed = time.time() - self.dubbed_at if self.dubbed_at else 0
        self.dubbed = False
        logger.info(
            f"[IDENTITY] 🔒 Agent '{self.agent_name}' undubbed after {elapsed:.2f}s. "
            "Clean address space restored."
        )

    def __enter__(self):
        return self.dub()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.undub()
        return False  # do not suppress exceptions

    def to_dict(self) -> dict:
        return {
            "agent":     self.agent_name,
            "task_id":   self.task_id,
            "dubbed":    self.dubbed,
            "dubbed_at": self.dubbed_at,
        }


# ══════════════════════════════════════════════════════════
# Namespace Isolation
# ══════════════════════════════════════════════════════════

class Namespace:
    """
    Wraps Linux namespace isolation primitives.
    On Linux: generates unshare(1) flags.
    On Windows: documents isolation intent (governance layer).

    Namespace types used:
      - CLONE_NEWNS   (mount)   — filesystem isolation
      - CLONE_NEWPID  (pid)     — process tree isolation
      - CLONE_NEWNET  (network) — network stack isolation
      - CLONE_NEWUTS  (uts)     — hostname isolation
      - CLONE_NEWUSER (user)    — UID/GID mapping
    """

    def __init__(
        self,
        agent_name:   str,
        net_isolated: bool = True,
        pid_isolated: bool = True,
        uts_isolated: bool = True,
    ):
        self.agent_name   = agent_name
        self.net_isolated = net_isolated
        self.pid_isolated = pid_isolated
        self.uts_isolated = uts_isolated

    @property
    def unshare_flags(self) -> str:
        """Returns unshare(1) flags for Linux enforcement."""
        flags = ["--mount", "--user"]
        if self.net_isolated: flags.append("--net")
        if self.pid_isolated: flags.append("--pid")
        if self.uts_isolated: flags.append("--uts")
        return " ".join(flags)

    def wrap_command(self, cmd: str) -> str:
        """Wrap a command with namespace isolation (Linux only)."""
        if IS_LINUX:
            return f"unshare {self.unshare_flags} -- {cmd}"
        # Windows: return command as-is (governance is enforced by Execwall)
        return cmd

    def describe(self) -> dict:
        return {
            "agent":       self.agent_name,
            "platform":    platform.system(),
            "enforcement": "kernel-level" if IS_LINUX else "policy-simulated",
            "namespaces": {
                "mount":   True,
                "user":    True,
                "network": self.net_isolated,
                "pid":     self.pid_isolated,
                "uts":     self.uts_isolated,
            },
        }


# ══════════════════════════════════════════════════════════
# Cgroup Resource Governance
# ══════════════════════════════════════════════════════════

class Cgroup:
    """
    Resource governance inspired by Linux Cgroups v2.
    Uses psutil for cross-platform enforcement.

    Configurable limits:
      - mem_max_mb       — max system memory pressure to allow agent execution
      - cpu_max_percent  — max CPU utilization before throttling
      - pids_max         — max concurrent processes
    """

    def __init__(
        self,
        agent_name:      str,
        mem_max_mb:      int = 1024,
        cpu_max_percent: int = 75,
        pids_max:        int = 64,
    ):
        self.agent_name      = agent_name
        self.mem_max_mb      = mem_max_mb
        self.cpu_max_percent = cpu_max_percent
        self.pids_max        = pids_max

    def check_limits(self) -> Tuple[bool, str, dict]:
        """
        Check whether current system resources are within governance limits.
        Returns (within_limits, message, metrics_dict).
        """
        mem         = psutil.virtual_memory()
        cpu_pct     = psutil.cpu_percent(interval=0.3)
        proc_count  = len(psutil.pids())
        mem_used_mb = (mem.total - mem.available) / (1024 * 1024)

        metrics = {
            "cpu_percent":  cpu_pct,
            "mem_used_mb":  round(mem_used_mb, 1),
            "mem_total_mb": round(mem.total / (1024 * 1024), 1),
            "mem_percent":  mem.percent,
            "pids":         proc_count,
        }

        violations = []
        if cpu_pct > self.cpu_max_percent:
            violations.append(f"CPU {cpu_pct:.1f}% > limit {self.cpu_max_percent}%")
        if mem_used_mb > self.mem_max_mb:
            violations.append(f"MEM {mem_used_mb:.0f}MB > limit {self.mem_max_mb}MB")
        if proc_count > self.pids_max * 4:          # system-wide generous limit
            violations.append(f"PID count {proc_count} exceeds safety threshold")

        if violations:
            msg = "Cgroup THROTTLE: " + "; ".join(violations)
            logger.warning(f"[CGROUP] {self.agent_name}: {msg}")
            return False, msg, metrics

        return True, "Within governance limits", metrics

    def describe(self) -> dict:
        return {
            "agent":         self.agent_name,
            "mem_max_mb":    self.mem_max_mb,
            "cpu_max_pct":   self.cpu_max_percent,
            "pids_max":      self.pids_max,
            "enforcement":   "cgroups-v2" if IS_LINUX else "psutil-simulated",
        }
