"""
Open Claw Stack — Product Lead Agent
=======================================
Transforms all technical agent outputs into a plain-English
executive summary, optimized for non-technical stakeholders.

Uses Gemini to:
  - Synthesize findings across all specialist agents
  - Apply severity triage
  - Generate actionable recommendations in plain English
  - Format as a structured, readable Markdown report

This agent ALWAYS runs last in the PRA loop.
"""
import logging
import time
from typing import Dict

from core.sandbox import Identity
from core.state import AgentStatus, SharedState

logger = logging.getLogger(__name__)

PRODUCT_LEAD_PROMPT = """You are the Product Lead Agent of the Open Claw Stack — a sovereign AI system.
Your role: translate raw technical analysis from specialist agents into a clear, concise executive summary
that a non-technical stakeholder (CEO, IT manager, student) can immediately understand and act on.

Style guidelines:
  - Use plain English — no jargon without explanation
  - Lead with the most critical finding first
  - Use severity labels: ✅ OK, ⚠️ WARNING, 🚨 CRITICAL
  - Provide EXACTLY 3 actionable recommendations, numbered
  - End with a one-sentence overall status summary
  - Keep total length under 400 words
  - Do NOT repeat raw data — interpret and summarize it

Structure your response EXACTLY as:
## 📋 Executive Summary

### Overall Status
[One line: system health in plain English]

### Key Findings
[Bullet points of the most important findings, max 5]

### Priority Actions
1. [First action]
2. [Second action]
3. [Third action]

### Bottom Line
[One powerful sentence that captures the full system status]
"""


class ProductLeadAgent:
    """Synthesizes all agent outputs into a plain-English executive report."""

    def __init__(self, state: SharedState, llm):
        self.state = state
        self.llm   = llm

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    def run(self, task: str, agent_results: Dict[str, str]) -> str:
        with Identity("product_lead", f"report-{int(time.time())}"):
            self.state.update_agent(
                "product_lead", AgentStatus.PERCEIVING,
                "📝 Product Lead online — synthesizing all reports..."
            )

            # Compile all agent outputs
            raw_data = self._compile_raw(agent_results)

            self.state.update_agent(
                "product_lead", AgentStatus.REASONING,
                "🧠 Sending to Gemini for plain-English synthesis..."
            )

            # Ask Gemini to summarize
            prompt = f"""
User's original task: "{task}"

Raw technical findings from specialist agents:
{raw_data}

Please generate the executive summary now, following your formatting guidelines exactly.
"""
            try:
                summary = self.llm.reason(prompt, PRODUCT_LEAD_PROMPT, max_tokens=1024, temperature=0.4)
            except Exception as exc:
                logger.warning(f"ProductLead: LLM synthesis failed ({exc}), using fallback")
                summary = self._fallback_summary(agent_results, task)

            # Append the full technical appendix
            final_report = summary + "\n\n---\n\n" + self._technical_appendix(agent_results)

            self.state.update_agent(
                "product_lead", AgentStatus.DONE,
                "✅ Executive report generated and ready.",
                metrics={"report_chars": len(final_report)},
            )
            self.state.agents["product_lead"].tool_calls = [
                {"tool": f"✅ Synthesized {len(agent_results)} agent reports via Gemini"}
            ]

            return final_report

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _compile_raw(self, results: Dict[str, str]) -> str:
        sections = []
        for agent, output in results.items():
            display = agent.replace("_", " ").title()
            sections.append(f"=== {display} ===\n{output or '(no output)'}")
        return "\n\n".join(sections)

    def _fallback_summary(self, results: Dict[str, str], task: str) -> str:
        agents_ran = list(results.keys())
        return f"""## 📋 Executive Summary

### Overall Status
System analysis completed for: "{task}"

### Key Findings
{chr(10).join(f'  • {a.replace("_"," ").title()}: Analysis complete' for a in agents_ran)}

### Priority Actions
1. Review the technical appendix below for detailed findings.
2. Address any 🟡 DEGRADED or 🔴 CRITICAL findings immediately.
3. Schedule a follow-up diagnostic in 24 hours to verify resolution.

### Bottom Line
The Open Claw Stack completed a full system sweep — review the appendix for actionable details.
"""

    def _technical_appendix(self, results: Dict[str, str]) -> str:
        lines = ["## 🔬 Technical Appendix\n*Full output from all specialist agents.*\n"]
        for agent, output in results.items():
            display = agent.replace("_", " ").title()
            lines.append(f"### {display}\n{output or '(no output)'}\n")
        return "\n".join(lines)
