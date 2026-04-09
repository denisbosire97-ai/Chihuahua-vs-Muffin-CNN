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
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from core.state import AgentStatus, SharedState
from core.sandbox import Identity, Cgroup

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """You are the Supervisor Agent of the Open Claw Stack — a sovereign AI multi-agent system.
Your role: analyze incoming tasks, delegate to specialist agents, synthesize results.

Available specialist agents:
  - security_auditor  : Scans open ports, detects Shadow AI, enforces PHASR rules, audits processes
  - network_engineer  : Ping, DNS, traceroute, connectivity analysis, latency measurement
  - sysadmin          : CPU, RAM, disk health, service status, process monitoring
  - product_lead      : Always runs LAST — converts all technical output to plain-English executive summary

Selection rules:
  - Always include "product_lead" as the final agent
  - General health check or "check everything" → all three specialists
  - Slow network / connectivity / DNS → network_engineer + security_auditor
  - Security breach / unauthorized access / shadow AI → security_auditor + sysadmin
  - High CPU / memory / disk full → sysadmin
  - Unknown or ambiguous → all three specialists (safe default)

Respond ONLY with valid JSON — no markdown fences, no explanation outside the JSON:
{
  "agents": ["agent1", "agent2", "product_lead"],
  "reasoning": "One-sentence explanation",
  "priority": "high|medium|low",
  "investigation_focus": "Specific aspect to investigate"
}"""


class SupervisorAgent:
    """Orchestrates the Open Claw Stack PRA loop."""

    AGENT_DISPLAY_NAMES = {
        "security_auditor": "Security Auditor",
        "network_engineer": "Network Engineer",
        "sysadmin":         "SysAdmin",
        "product_lead":     "Product Lead",
    }

    def __init__(
        self,
        state:    SharedState,
        llm,
        execwall,
        agents:   Dict[str, Any],
    ):
        self.state    = state
        self.llm      = llm
        self.execwall = execwall
        self.agents   = agents          # name → agent instance

    # ──────────────────────────────────────────────
    # Main Entry Point
    # ──────────────────────────────────────────────

    def run(self, task: str) -> str:
        """Execute the full PRA loop for a given task."""
        with Identity("supervisor", task[:40]) as identity:

            # ── PERCEPTION ────────────────────────
            self.state.current_task = task
            self.state.set_pra_phase("perception")
            self.state.update_agent(
                "supervisor", AgentStatus.PERCEIVING,
                f"🔍 Perceiving task: {task}"
            )
            self.state.add_message("user", task, "user")
            logger.info(f"Supervisor: task received — {task}")

            # ── REASONING ─────────────────────────
            self.state.set_pra_phase("reasoning")
            self.state.update_agent(
                "supervisor", AgentStatus.REASONING, "🧠 Routing task via Gemini..."
            )
            routing         = self._route_task(task)
            selected_agents = routing.get("agents", self._default_agents())
            reasoning       = routing.get("reasoning", "Full system investigation")
            focus           = routing.get("investigation_focus", task)
            priority        = routing.get("priority", "medium")

            self.state.update_agent(
                "supervisor", AgentStatus.REASONING,
                f"📋 Routing [{priority.upper()}]: {reasoning}",
                metrics={"priority": priority, "agents_selected": len(selected_agents)},
            )
            self.state.add_message(
                "supervisor",
                f"**Routing Decision** [{priority.upper()}]: {reasoning}\n"
                f"**Activating agents**: {', '.join(selected_agents)}\n"
                f"**Focus**: {focus}",
                "supervisor",
            )

            # ── ACTION ────────────────────────────
            self.state.set_pra_phase("action")
            self.state.update_agent(
                "supervisor", AgentStatus.ACTING,
                f"⚡ Coordinating {len(selected_agents)} agents..."
            )

            specialists  = [a for a in selected_agents if a != "product_lead"]
            results: Dict[str, str] = {}

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
                t.join(timeout=50)

            # Product Lead always runs last (sequential)
            if "product_lead" in selected_agents and "product_lead" in self.agents:
                self.state.update_agent("supervisor", AgentStatus.ACTING, "📝 Product Lead synthesizing report...")
                product_output  = self.agents["product_lead"].run(task, results)
                results["product_lead"] = product_output

            # ── COMPLETE ──────────────────────────
            final_report = results.get("product_lead") or self._raw_report(results)
            self.state.set_final_report(final_report)
            self.state.set_pra_phase("done")
            self.state.update_agent(
                "supervisor", AgentStatus.DONE, "✅ Mission complete. Report generated.",
                metrics={"agents_ran": len(results)},
            )
            self.state.add_message("supervisor", "**Task complete.** Final report ready.", "supervisor")
            logger.info("Supervisor: task complete")
            return final_report

    # ──────────────────────────────────────────────
    # Helpers
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
            "reasoning":            "Default full-system investigation",
            "priority":             "medium",
            "investigation_focus":  task,
        }

    def _threaded_run(self, name: str, task: str, focus: str, results: dict):
        try:
            results[name] = self.agents[name].run(task)
        except Exception as exc:
            results[name] = f"⚠️ Agent error: {exc}"
            self.state.update_agent(name, AgentStatus.ERROR, f"Error: {exc}")

    def _default_agents(self) -> List[str]:
        return ["network_engineer", "security_auditor", "sysadmin", "product_lead"]

    def _raw_report(self, results: dict) -> str:
        lines = ["# 🛡️ Open Claw Stack — System Report\n"]
        for agent, output in results.items():
            display = self.AGENT_DISPLAY_NAMES.get(agent, agent.replace("_", " ").title())
            lines.append(f"## {display}\n{output}\n")
        return "\n".join(lines)
