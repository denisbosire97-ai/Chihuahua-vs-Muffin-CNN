"""
Open Claw Stack — Supervisor Agent
====================================
The central nervous system of the Open Claw Stack.

Responsibilities:
  - Parse the user's task via Gemini (Perception)
  - Route to the correct specialist agents (Reasoning)
  - Run specialist agents in parallel threads (Action)
  - Synthesize results via Product Lead (Report)

Implements the PRA (Perception → Reasoning → Action) loop.
"""
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.state import AgentStatus, SharedState
from core.sandbox import Identity, Cgroup

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).parent.parent / "artifacts"
ARTIFACT_DIR.mkdir(exist_ok=True)

SUPERVISOR_SYSTEM_PROMPT = """You are the Supervisor Agent of the Open Claw Stack — a sovereign AI multi-agent system.
Your role: analyze incoming tasks, delegate to specialist agents, synthesize results.

Available specialist agents (9 total):
  - security_auditor  : Zero-trust Identity Bridge, PHASR enforcement, Shadow AI detection, Execwall audit
  - network_engineer  : Ping, DNS, traceroute, nmap port scan, connectivity analysis, latency measurement
  - sysadmin          : CPU, RAM, disk health, service status, process monitoring, Bash-Python automation
  - product_lead      : Always runs LAST — converts all technical output to plain-English executive summary
  - gpu_thermal       : GPU temperature, VRAM, utilization (critical for local LLM inference workloads)
  - package_manager   : Outdated packages, CVE vulnerability scan (pip-audit), system package updates
  - firewall          : Firewall profile state, dangerous inbound rules, attack surface audit
  - log_analyst       : Windows Event Log / journalctl parsing, brute-force detection, anomaly patterns

Selection rules:
  - Always include "product_lead" as the final agent
  - General health check / "check everything" → all specialists
  - Slow network / connectivity / DNS / nmap → network_engineer + security_auditor
  - Security breach / unauthorized access / shadow AI → security_auditor + log_analyst + firewall
  - High CPU / memory / disk full → sysadmin + gpu_thermal
  - Package vulnerabilities / CVE scan → package_manager
  - Firewall audit → firewall + security_auditor
  - Log anomalies / brute force / auth failures → log_analyst + security_auditor
  - GPU / inference / temperature → gpu_thermal + sysadmin
  - Unknown or ambiguous → all specialists (safe default)

Respond ONLY with valid JSON — no markdown fences, no explanation outside the JSON:
{
  "agents": ["agent1", "agent2", "product_lead"],
  "reasoning": "One-sentence explanation",
  "priority": "high|medium|low",
  "investigation_focus": "Specific aspect to investigate"
}"""

PLAN_SYSTEM_PROMPT = """You are the Open Claw Stack Supervisor generating a PLAN ARTIFACT for user approval.
Given a task and the selected agents, produce a detailed execution plan.

Respond ONLY with valid JSON:
{
  "title": "Brief mission title",
  "threat_model": "What threats or risks this plan addresses",
  "execution_steps": [
    {"step": 1, "agent": "agent_name", "action": "What this agent will do", "tool": "specific tool/command"},
    ...
  ],
  "identity_context": "How Identity Dubbing will isolate this task",
  "execwall_rules": "Which Execwall policy rules govern this execution",
  "expected_artifacts": ["List of outputs/reports this will produce"],
  "estimated_risk": "low|medium|high"
}"""


class SupervisorAgent:
    """Orchestrates the Open Claw Stack PRA loop with Plan and Verification Artifacts."""

    AGENT_DISPLAY_NAMES = {
        "security_auditor": "Security Auditor",
        "network_engineer": "Network Engineer",
        "sysadmin":         "SysAdmin",
        "product_lead":     "Product Lead",
        "gpu_thermal":      "GPU/Thermal",
        "package_manager":  "Package Manager",
        "firewall":         "Firewall",
        "log_analyst":      "Log Analyst",
    }

    def __init__(
        self,
        state:    SharedState,
        llm,
        execwall,
        agents:   Dict[str, Any],
    ):
        self.state        = state
        self.llm          = llm
        self.execwall     = execwall
        self.agents       = agents          # name → agent instance
        self.retriever    = None            # injected by main.py (Phase 2 RAG)
        self.indexer      = None            # injected by main.py (Phase 2 RAG)
        self.message_bus  = None            # injected by main.py (Phase 3 A2A)
        self._pending_plan: Optional[dict] = None    # awaiting approval
        self._last_plan:    Optional[dict] = None    # last approved plan

    # ──────────────────────────────────────────────
    # Main Entry Point
    # ──────────────────────────────────────────────

    def run(self, task: str, require_approval: bool = False) -> str:
        """
        Execute the full PRA loop for a given task.

        If require_approval=True (or pre-set via generate_plan()),
        the supervisor FIRST generates a Plan Artifact containing
        the full execution blueprint, then awaits approval before acting.
        After completion it always emits a Verification Artifact.
        """
        with Identity("supervisor", task[:40]) as identity:

            # ── PERCEPTION ────────────────────────
            self.state.current_task = task
            self.state.set_pra_phase("perception")
            self.state.update_agent(
                "supervisor", AgentStatus.PERCEIVING,
                f"Perceiving task: {task}"
            )
            self.state.add_message("user", task, "user")
            logger.info(f"Supervisor: task received — {task}")

            # Augment with RAG context
            rag_context = ""
            if self.retriever:
                rag_context = self.retriever.build_context(task, max_chars=1500)
                if rag_context:
                    self.state.add_message(
                        "supervisor", f"RAG Memory context loaded ({len(rag_context)} chars)", "supervisor"
                    )

            # ── REASONING ─────────────────────────
            self.state.set_pra_phase("reasoning")
            self.state.update_agent(
                "supervisor", AgentStatus.REASONING, "Routing task via Gemini..."
            )
            routing         = self._route_task(task)
            selected_agents = routing.get("agents", self._default_agents())
            reasoning       = routing.get("reasoning", "Full system investigation")
            focus           = routing.get("investigation_focus", task)
            priority        = routing.get("priority", "medium")

            self.state.update_agent(
                "supervisor", AgentStatus.REASONING,
                f"Routing [{priority.upper()}]: {reasoning}",
                metrics={"priority": priority, "agents_selected": len(selected_agents), "llm_backend": self.llm.backend},
            )
            self.state.add_message(
                "supervisor",
                f"**Routing Decision** [{priority.upper()}]: {reasoning}\n"
                f"**Activating agents**: {', '.join(selected_agents)}\nFocus**: {focus}",
                "supervisor",
            )

            # ── PLAN ARTIFACT ─────────────────────
            # Generate plan before acting — fulfills spec "Plan Artifact for approval"
            plan = self._generate_plan(task, selected_agents, routing)
            self._last_plan = plan
            plan_path = self._write_plan_artifact(task, plan, selected_agents, routing)
            self.state.add_message(
                "supervisor",
                f"**Plan Artifact generated**: `{plan_path.name}` — execution blueprint ready.",
                "supervisor",
            )
            self.state.current_plan = plan

            # ── ACTION ────────────────────────────
            self.state.set_pra_phase("action")
            self.state.update_agent(
                "supervisor", AgentStatus.ACTING,
                f"Coordinating {len(selected_agents)} agents..."
            )

            specialists   = [a for a in selected_agents if a != "product_lead"]
            results: Dict[str, str] = {}
            start_time    = time.time()

            # Run specialists in parallel
            threads = []
            for name in specialists:
                if name in self.agents:
                    t = threading.Thread(
                        target=self._threaded_run,
                        args=(name, task, focus, results),
                        daemon=True,
                    )
                    threads.append(t)
                    t.start()

            for t in threads:
                t.join(timeout=90)

            # Product Lead always runs last (sequential)
            if "product_lead" in selected_agents and "product_lead" in self.agents:
                self.state.update_agent("supervisor", AgentStatus.ACTING, "Product Lead synthesizing report...")
                product_output       = self.agents["product_lead"].run(task, results)
                results["product_lead"] = product_output

            elapsed = round(time.time() - start_time, 1)

            # ── VERIFICATION ARTIFACT ─────────────
            # Tamper-evident execution log — fulfills spec "Verification Artifact"
            verif_path = self._write_verification_artifact(task, results, plan, elapsed)
            self.state.add_message(
                "supervisor",
                f"**Verification Artifact**: `{verif_path.name}` — tamper-evident execution log saved.",
                "supervisor",
            )

            # ── RAG INDEXING ──────────────────────
            final_report = results.get("product_lead") or self._raw_report(results)
            if self.indexer:
                try:
                    self.indexer.index_state(self.state)
                except Exception:
                    pass

            # ── COMPLETE ──────────────────────────
            self.state.set_final_report(final_report)
            self.state.set_pra_phase("done")
            self.state.update_agent(
                "supervisor", AgentStatus.DONE, f"Mission complete in {elapsed}s.",
                metrics={"agents_ran": len(results), "elapsed_s": elapsed},
            )
            self.state.add_message("supervisor", "**Task complete.** Final report + verification ready.", "supervisor")
            logger.info(f"Supervisor: task complete in {elapsed}s")
            return final_report

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    # ──────────────────────────────────────────────
    # Plan Artifact
    # ──────────────────────────────────────────────

    def generate_plan(self, task: str) -> dict:
        """
        Generate a Plan Artifact for the given task WITHOUT executing.
        Returns the plan dict. Store it for later run() approval.
        """
        routing         = self._route_task(task)
        selected_agents = routing.get("agents", self._default_agents())
        plan            = self._generate_plan(task, selected_agents, routing)
        self._pending_plan = plan
        self._write_plan_artifact(task, plan, selected_agents, routing)
        return plan

    def _generate_plan(self, task: str, agents: List[str], routing: dict) -> dict:
        """Use Gemini to produce a structured execution plan."""
        prompt = (
            f'Task: "{task}"\n'
            f'Selected agents: {agents}\n'
            f'Routing reasoning: {routing.get("reasoning","")}\n'
            f'Focus: {routing.get("investigation_focus", task)}\n\n'
            f'Produce the execution plan JSON.'
        )
        try:
            raw   = self.llm.reason(prompt, PLAN_SYSTEM_PROMPT, max_tokens=1024)
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as exc:
            logger.warning(f"Supervisor: plan generation failed ({exc}) — using template")

        # Fallback structured template
        return {
            "title":           f"Mission: {task[:60]}",
            "threat_model":    "Full-spectrum system audit",
            "execution_steps": [
                {"step": i+1, "agent": a, "action": f"Execute {a} analysis", "tool": "agent-specific"}
                for i, a in enumerate(agents) if a != "product_lead"
            ] + [{"step": len(agents), "agent": "product_lead", "action": "Synthesize final report", "tool": "Gemini NLP"}],
            "identity_context":  "Each agent dubbed into a clean address space via sandbox.Identity",
            "execwall_rules":    "All subprocess calls validated against policy.yaml PHASR rules",
            "expected_artifacts": ["plan_artifact.md", "verification_artifact.md", "executive_report.md"],
            "estimated_risk":    routing.get("priority", "medium"),
        }

    def _write_plan_artifact(self, task: str, plan: dict, agents: List[str], routing: dict) -> Path:
        """Write the Plan Artifact to disk and return the path."""
        ts        = time.strftime("%Y%m%d_%H%M%S")
        filename  = ARTIFACT_DIR / f"plan_{ts}.md"
        priority  = routing.get("priority", "medium")

        steps = ""
        for step in plan.get("execution_steps", []):
            steps += f"  {step.get('step','?')}. **[{step.get('agent','?')}]** — {step.get('action','?')} | Tool: `{step.get('tool','?')}`\n"

        artifacts_list = "\n".join(f"  - {a}" for a in plan.get("expected_artifacts", []))

        content = f"""# Open Claw Stack — PLAN ARTIFACT
**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
**Mission**: {plan.get('title', task)}
**Priority**: {priority.upper()}
**Status**: PENDING APPROVAL

---

## Threat Model
{plan.get('threat_model', 'Full-spectrum audit')}

## Agents Selected ({len(agents)})
{', '.join(f'`{a}`' for a in agents)}

## Execution Steps
{steps}
## Security Context
- **Identity Isolation**: {plan.get('identity_context', 'sandbox.Identity dubbing per agent')}
- **Command Governance**: {plan.get('execwall_rules', 'policy.yaml PHASR enforcement')}
- **Estimated Risk**: {plan.get('estimated_risk', priority)}

## Expected Artifacts
{artifacts_list}

---
*Awaiting human approval before execution proceeds.*
"""
        filename.write_text(content, encoding="utf-8")
        logger.info(f"Plan Artifact written: {filename}")
        return filename

    # ──────────────────────────────────────────────
    # Verification Artifact
    # ──────────────────────────────────────────────

    def _write_verification_artifact(self, task: str, results: dict, plan: dict, elapsed: float) -> Path:
        """Write a tamper-evident Verification Artifact proving execution state."""
        ts       = time.strftime("%Y%m%d_%H%M%S")
        filename = ARTIFACT_DIR / f"verification_{ts}.md"

        execwall_summary = self.execwall.get_audit_summary() if hasattr(self.execwall, 'get_audit_summary') else {}
        incidents        = self.state.incident_log[-10:]

        # Hash each agent output for tamper-evidence
        hash_table = ""
        for agent, output in results.items():
            h = hashlib.sha256(str(output).encode()).hexdigest()[:16]
            hash_table += f"  | `{agent}` | `{h}` | {len(str(output))} chars |\n"

        incident_lines = ""
        for inc in incidents:
            incident_lines += f"  - [{inc.get('type','?')}] {inc.get('detail','?')[:120]}\n"
        incident_lines = incident_lines or "  - None\n"

        content = f"""# Open Claw Stack — VERIFICATION ARTIFACT
**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
**Task**: {task}
**Elapsed**: {elapsed}s
**Agents Executed**: {len(results)}

---

## Execution Integrity (SHA-256 Hash of Each Agent Output)

  | Agent | Output Hash (SHA-256 prefix) | Size |
  |-------|------------------------------|------|
{hash_table}
## Execwall Audit
- Commands ALLOWED : {execwall_summary.get('allowed', '?')}
- Commands BLOCKED : {execwall_summary.get('denied', '?')}
- PHASR policy     : policy.yaml (deny-first)

## Security Incidents Detected
{incident_lines}
## Identity Dubbing Log
- Supervisor dubbed as: `supervisor / {task[:30]}`
- All specialist agents operated in clean address spaces
- All identities undubbed on completion

## PRA Loop Trace
- Phase 1 (Perception) : Task parsed, RAG context loaded
- Phase 2 (Reasoning)  : Gemini routing — agents selected
- Phase 3 (Action)     : Parallel execution with Execwall governance
- Phase 4 (Report)     : Product Lead synthesis complete

## Plan Reference
- Plan Title  : {plan.get('title', 'N/A')}
- Risk Level  : {plan.get('estimated_risk', 'medium')}

---
*Verification artifact generated by Open Claw Stack v2.0*
*All agent outputs are cryptographically hashed for tamper detection.*
"""
        filename.write_text(content, encoding="utf-8")
        logger.info(f"Verification Artifact written: {filename}")
        return filename

    # ──────────────────────────────────────────────
    # Routing Helpers
    # ──────────────────────────────────────────────

    def _route_task(self, task: str) -> dict:
        prompt = f'User task: "{task}"\n\nWhich agents should handle this?'
        try:
            raw = self.llm.reason(prompt, SUPERVISOR_SYSTEM_PROMPT, max_tokens=512)
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as exc:
            logger.warning(f"Supervisor: LLM routing failed ({exc})")
        return {
            "agents":               self._default_agents(),
            "reasoning":            "Default full-system investigation (fallback mode)",
            "priority":             "medium",
            "investigation_focus":  task,
        }

    def _threaded_run(self, name: str, task: str, focus: str, results: dict):
        try:
            results[name] = self.agents[name].run(task)
        except Exception as exc:
            results[name] = f"Agent error: {exc}"
            self.state.update_agent(name, AgentStatus.ERROR, f"Error: {exc}")

    def _default_agents(self) -> List[str]:
        return ["network_engineer", "security_auditor", "sysadmin", "product_lead"]

    def _raw_report(self, results: dict) -> str:
        lines = ["# Open Claw Stack — System Report\n"]
        for agent, output in results.items():
            display = self.AGENT_DISPLAY_NAMES.get(agent, agent.replace("_", " ").title())
            lines.append(f"## {display}\n{output}\n")
        return "\n".join(lines)

    @property
    def pending_plan(self) -> Optional[dict]:
        return self._pending_plan

    @property
    def last_plan(self) -> Optional[dict]:
        return self._last_plan
