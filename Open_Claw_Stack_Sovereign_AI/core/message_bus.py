"""
Open Claw Stack — A2A Message Bus
====================================
Agent-to-Agent (A2A) communication protocol.
Agents can send events directly to each other without going through the Supervisor.

Example: NetworkEngineer detects anomalous latency spike
         → sends A2A message to SecurityAuditor
         → SecurityAuditor immediately runs targeted port scan

Uses a thread-safe in-process queue. Future: replace with Redis or NATS for distributed setups.
"""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from queue import Empty, Queue
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Valid A2A event types
class EventType:
    ANOMALY_DETECTED    = "ANOMALY_DETECTED"
    THREAT_FOUND        = "THREAT_FOUND"
    RESOURCE_PRESSURE   = "RESOURCE_PRESSURE"
    NETWORK_DEGRADED    = "NETWORK_DEGRADED"
    SERVICE_CRASHED     = "SERVICE_CRASHED"
    TASK_COMPLETE       = "TASK_COMPLETE"
    REQUEST_ANALYSIS    = "REQUEST_ANALYSIS"
    PACKAGE_VULNERABLE  = "PACKAGE_VULNERABLE"
    GPU_OVERHEATING     = "GPU_OVERHEATING"
    FIREWALL_GAP        = "FIREWALL_GAP"
    LOG_ANOMALY         = "LOG_ANOMALY"


@dataclass
class A2AMessage:
    """Standardized inter-agent message contract."""
    from_agent:  str
    to_agent:    str
    event_type:  str
    payload:     Dict
    priority:    str  = "medium"   # low | medium | high | critical
    msg_id:      str  = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp:   float= field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def threat(cls, from_agent: str, to_agent: str, detail: str, **payload) -> "A2AMessage":
        return cls(
            from_agent=from_agent, to_agent=to_agent,
            event_type=EventType.THREAT_FOUND,
            payload={"detail": detail, **payload},
            priority="high",
        )

    @classmethod
    def anomaly(cls, from_agent: str, to_agent: str, metric: str, value, **payload) -> "A2AMessage":
        return cls(
            from_agent=from_agent, to_agent=to_agent,
            event_type=EventType.ANOMALY_DETECTED,
            payload={"metric": metric, "value": value, **payload},
            priority="medium",
        )


class MessageBus:
    """
    Central inter-agent message bus.
    Agents register their inbox and poll for messages.
    Thread-safe — safe to use from any agent thread.
    """

    def __init__(self, state=None):
        self._lock:     threading.Lock         = threading.Lock()
        self._inboxes:  Dict[str, Queue]       = {}
        self._log:      List[Dict]             = []
        self.state      = state

    # ──────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────

    def register(self, agent_name: str):
        """Register an agent's inbox."""
        with self._lock:
            if agent_name not in self._inboxes:
                self._inboxes[agent_name] = Queue()
                logger.info(f"MessageBus: registered '{agent_name}'")

    def registered_agents(self) -> List[str]:
        with self._lock:
            return list(self._inboxes.keys())

    # ──────────────────────────────────────────────
    # Send / Receive
    # ──────────────────────────────────────────────

    def send(self, message: A2AMessage) -> bool:
        """Send a message to another agent's inbox."""
        with self._lock:
            inbox = self._inboxes.get(message.to_agent)
            if inbox is None:
                logger.warning(f"MessageBus: no inbox for '{message.to_agent}' — dropped")
                return False
            inbox.put(message)
            self._log.append(message.to_dict())

        logger.info(
            f"MessageBus: [{message.from_agent}] -> [{message.to_agent}] "
            f"({message.event_type}) [{message.priority}]"
        )

        # Notify SharedState for dashboard display
        if self.state:
            self.state.add_message(
                "system",
                f"📨 A2A: **{message.from_agent}** → **{message.to_agent}**: "
                f"{message.event_type} [{message.priority}]",
                "system",
            )
        return True

    def receive(self, agent_name: str, timeout: float = 0.05) -> Optional[A2AMessage]:
        """Poll for the next message for this agent."""
        with self._lock:
            inbox = self._inboxes.get(agent_name)
        if inbox:
            try:
                return inbox.get(timeout=timeout)
            except Empty:
                pass
        return None

    def receive_all(self, agent_name: str) -> List[A2AMessage]:
        """Drain all pending messages for this agent."""
        msgs = []
        while True:
            m = self.receive(agent_name, timeout=0.001)
            if m is None:
                break
            msgs.append(m)
        return msgs

    def pending_count(self, agent_name: str) -> int:
        with self._lock:
            inbox = self._inboxes.get(agent_name)
        return inbox.qsize() if inbox else 0

    # ──────────────────────────────────────────────
    # Diagnostics
    # ──────────────────────────────────────────────

    def get_log(self, n: int = 20) -> List[Dict]:
        return self._log[-n:]

    def status(self) -> Dict:
        with self._lock:
            return {
                "registered_agents": list(self._inboxes.keys()),
                "message_log_count": len(self._log),
                "pending": {
                    name: inbox.qsize()
                    for name, inbox in self._inboxes.items()
                },
            }
