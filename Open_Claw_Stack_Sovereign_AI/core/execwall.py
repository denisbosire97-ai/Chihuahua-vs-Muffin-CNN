"""
Open Claw Stack — Execwall Execution Firewall
=============================================
Intercepts every shell command and validates it against policy.yaml.
Implements PHASR (Proactive Hardening and Attack Surface Reduction).

Security model:
  1. DENY list checked first — if match, raise PolicyViolationError
  2. ALLOW list checked second — if no match, block in strict mode
  3. Every decision is audit-logged to SharedState
"""
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

BASE_DIR   = Path(__file__).parent.parent
POLICY_YML = BASE_DIR / "policy.yaml"


class PolicyViolationError(Exception):
    """Raised when a command is blocked by Execwall policy."""
    pass


class Execwall:
    """
    The execution firewall for the Open Claw Stack.
    All agent tool calls MUST pass through this gateway.
    """

    def __init__(
        self,
        policy_path: Optional[Path] = None,
        state=None,
        strict_mode: bool = False,
    ):
        self.state       = state
        self.strict_mode = strict_mode
        self.audit_log: list = []

        policy_path = policy_path or POLICY_YML
        self._load_policy(policy_path)

    # ──────────────────────────────────────────────
    # Policy Loading
    # ──────────────────────────────────────────────

    def _load_policy(self, path: Path):
        try:
            with open(path, "r") as f:
                policy = yaml.safe_load(f)
            rules         = policy.get("rules", {})
            self._deny    = [re.compile(r["pattern"], re.IGNORECASE) for r in rules.get("deny",  [])]
            self._allow   = [re.compile(r["pattern"], re.IGNORECASE) for r in rules.get("allow", [])]
            logger.info(f"Execwall: {len(self._deny)} deny rules, {len(self._allow)} allow rules loaded")
        except Exception as exc:
            logger.error(f"Execwall: failed to load policy ({exc}). Running in OPEN mode.")
            self._deny  = []
            self._allow = []

    # ──────────────────────────────────────────────
    # Policy Enforcement
    # ──────────────────────────────────────────────

    def _check(self, cmd: str) -> Tuple[bool, str]:
        """Returns (is_allowed, reason)."""
        # Step 1: deny list (higher priority)
        for pattern in self._deny:
            if pattern.search(cmd):
                return False, f"PHASR BLOCK — matched deny rule: `{pattern.pattern}`"

        # Step 2: allow list
        for pattern in self._allow:
            if pattern.search(cmd):
                return True, f"allowed — rule: `{pattern.pattern}`"

        # Step 3: strict mode?
        if self.strict_mode:
            return False, "BLOCK — command not in allowlist (strict mode)"

        return True, "allowed (passthrough — not in deny list)"

    # ──────────────────────────────────────────────
    # Execution Gateway
    # ──────────────────────────────────────────────

    def execute(
        self,
        cmd:        str,
        agent_name: str = "unknown",
        timeout:    int = 30,
    ) -> Tuple[str, str, int]:
        """
        Execute a shell command through the policy firewall.

        Returns:
            (stdout, stderr, exit_code)

        Raises:
            PolicyViolationError: if the command is blocked.
        """
        ts             = time.time()
        allowed, reason = self._check(cmd)

        entry = {
            "ts":      ts,
            "agent":   agent_name,
            "command": cmd[:200],
            "verdict": "ALLOW" if allowed else "DENY",
            "reason":  reason,
        }
        self.audit_log.append(entry)

        if self.state:
            self.state.add_execwall_entry(entry)

        if not allowed:
            logger.warning(f"Execwall BLOCKED [{agent_name}]: {cmd[:80]} — {reason}")
            if self.state:
                self.state.add_incident({
                    "type":    "PHASR_BLOCK",
                    "agent":   agent_name,
                    "command": cmd[:200],
                    "reason":  reason,
                })
            raise PolicyViolationError(f"Execwall blocked command: {reason}")

        logger.info(f"Execwall ALLOW [{agent_name}]: {cmd[:80]}")

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode

        except subprocess.TimeoutExpired:
            return "", f"Command timed out after {timeout}s", -1

        except Exception as exc:
            return "", str(exc), -1

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def get_audit_summary(self) -> dict:
        allow_count = sum(1 for e in self.audit_log if e["verdict"] == "ALLOW")
        deny_count  = sum(1 for e in self.audit_log if e["verdict"] == "DENY")
        return {
            "total":   len(self.audit_log),
            "allowed": allow_count,
            "denied":  deny_count,
            "log":     self.audit_log[-20:],
        }
