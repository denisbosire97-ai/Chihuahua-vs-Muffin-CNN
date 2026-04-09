"""
Open Claw Stack — Shared State & PRA Loop
==========================================
Thread-safe shared state for all agents.
Implements the Perception → Reasoning → Action cycle.
"""
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(Enum):
    IDLE       = "idle"
    PERCEIVING = "perceiving"
    REASONING  = "reasoning"
    ACTING     = "acting"
    DONE       = "done"
    ERROR      = "error"


class PRAPhase(Enum):
    IDLE       = "idle"
    PERCEPTION = "perception"
    REASONING  = "reasoning"
    ACTION     = "action"
    DONE       = "done"


@dataclass
class Message:
    role: str        # "user" | "supervisor" | "agent" | "system"
    content: str
    agent: str       = "system"
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentEntry:
    name:          str
    status:        AgentStatus        = AgentStatus.IDLE
    last_output:   str                = ""
    metrics:       Dict[str, Any]     = field(default_factory=dict)
    execution_log: List[str]          = field(default_factory=list)
    tool_calls:    List[Dict]         = field(default_factory=list)


class SharedState:
    """
    Central state store for the Open Claw Stack.
    All agents read from and write to this object.
    Version counter enables efficient WebSocket polling.
    """

    def __init__(self):
        self._lock   = threading.Lock()
        self.version = 0

        # Task context
        self.current_task  = ""
        self.pra_phase     = PRAPhase.IDLE.value
        self.final_report  = ""

        # Agent registry
        self.agents: Dict[str, AgentEntry] = {
            "supervisor":       AgentEntry("supervisor"),
            "security_auditor": AgentEntry("security_auditor"),
            "network_engineer": AgentEntry("network_engineer"),
            "sysadmin":         AgentEntry("sysadmin"),
            "product_lead":     AgentEntry("product_lead"),
        }

        # Message history (conversation)
        self.messages: List[Message] = []

        # Incident log (PHASR violations, anomalies)
        self.incident_log: List[Dict] = []

        # Execwall audit log
        self.execwall_audit: List[Dict] = []

    # ──────────────────────────────────────────────
    # Write Methods
    # ──────────────────────────────────────────────

    def update_agent(
        self,
        name:    str,
        status:  Optional[AgentStatus] = None,
        output:  Optional[str]         = None,
        metrics: Optional[Dict]        = None,
    ):
        with self._lock:
            entry = self.agents.get(name)
            if not entry:
                return
            if status is not None:
                entry.status = status
            if output is not None:
                entry.last_output = output
                entry.execution_log.append(f"[{time.strftime('%H:%M:%S')}] {output}")
            if metrics is not None:
                entry.metrics.update(metrics)
            self.version += 1

    def add_message(self, role: str, content: str, agent: str = "system") -> Message:
        msg = Message(role=role, content=content, agent=agent)
        with self._lock:
            self.messages.append(msg)
            self.version += 1
        return msg

    def set_pra_phase(self, phase: str):
        with self._lock:
            self.pra_phase = phase
            self.version += 1

    def set_final_report(self, report: str):
        with self._lock:
            self.final_report = report
            self.version += 1

    def add_incident(self, incident: Dict):
        with self._lock:
            incident["timestamp"] = time.time()
            self.incident_log.append(incident)
            self.version += 1

    def add_execwall_entry(self, entry: Dict):
        with self._lock:
            self.execwall_audit.append(entry)
            self.version += 1

    def reset(self):
        """Reset state for a new task."""
        with self._lock:
            self.current_task = ""
            self.pra_phase    = PRAPhase.IDLE.value
            self.final_report = ""
            self.messages     = []
            for entry in self.agents.values():
                entry.status        = AgentStatus.IDLE
                entry.last_output   = ""
                entry.execution_log = []
                entry.tool_calls    = []
                entry.metrics       = {}
            self.version += 1

    # ──────────────────────────────────────────────
    # Serialization (for WebSocket broadcast)
    # ──────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version":      self.version,
                "current_task": self.current_task,
                "pra_phase":    self.pra_phase,
                "final_report": self.final_report,
                "agents": {
                    name: {
                        "name":       e.name,
                        "status":     e.status.value,
                        "last_output": e.last_output,
                        "metrics":    e.metrics,
                        "log":        e.execution_log[-15:],
                        "tool_calls": e.tool_calls[-5:],
                    }
                    for name, e in self.agents.items()
                },
                "messages": [
                    {
                        "role":      m.role,
                        "content":   m.content,
                        "agent":     m.agent,
                        "timestamp": m.timestamp,
                    }
                    for m in self.messages[-60:]
                ],
                "incident_log":   self.incident_log[-20:],
                "execwall_audit": self.execwall_audit[-30:],
            }
