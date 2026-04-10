"""
Open Claw Stack — RAG Indexer
================================
Indexes documents, reports, and incidents into the vector store.
Called automatically after each task completes.

What gets indexed:
  - Every Product Lead report
  - Every PHASR block event
  - Every incident log entry
  - System metric snapshots (baselines)
"""
import logging
import time
import uuid
from typing import Dict, Optional

from memory.vector_store import VectorStore
from memory.embedder     import Embedder

logger = logging.getLogger(__name__)


class Indexer:
    """Indexes all agent outputs into the RAG vector store."""

    def __init__(self, store: VectorStore, embedder: Embedder):
        self.store    = store
        self.embedder = embedder
        self._indexed = 0

    # ──────────────────────────────────────────────
    # Index Methods
    # ──────────────────────────────────────────────

    def index_report(self, report: str, task: str, metadata: Optional[Dict] = None) -> bool:
        """Index a final Product Lead report."""
        if not report or not self.store.available:
            return False
        doc_id   = f"report_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        embedding = self.embedder.embed(report[:4000])
        meta      = {
            "type":      "incident_report",
            "task":      task[:200],
            "ts":        time.time(),
            "ts_human":  time.strftime("%Y-%m-%d %H:%M"),
            **(metadata or {}),
        }
        ok = self.store.add_document("incident_reports", doc_id, report[:4000], embedding, meta)
        if ok:
            self._indexed += 1
            logger.info(f"Indexer: indexed report '{doc_id}'")
        return ok

    def index_incident(self, incident: Dict) -> bool:
        """Index a PHASR or security incident."""
        if not self.store.available:
            return False
        text     = f"{incident.get('type','')} — {incident.get('detail', incident.get('reason',''))}"
        doc_id   = f"inc_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        embedding = self.embedder.embed(text)
        ok = self.store.add_document(
            "phasr_events", doc_id, text, embedding,
            {"type": incident.get("type",""), "agent": incident.get("agent",""), "ts": time.time()},
        )
        if ok:
            self._indexed += 1
        return ok

    def index_baseline(self, agent_name: str, metrics: Dict) -> bool:
        """Index a system metric snapshot for baseline comparison."""
        if not self.store.available:
            return False
        text     = f"[{agent_name}] metrics: " + " | ".join(f"{k}={v}" for k, v in metrics.items())
        doc_id   = f"base_{agent_name}_{int(time.time())}"
        embedding = self.embedder.embed(text)
        return self.store.add_document(
            "system_baselines", doc_id, text, embedding,
            {"agent": agent_name, "ts": time.time(), **{str(k): str(v) for k, v in metrics.items()}},
        )

    def index_document(self, title: str, content: str, source: str = "manual") -> bool:
        """Index arbitrary reference documentation."""
        if not self.store.available:
            return False
        doc_id    = f"doc_{uuid.uuid4().hex[:8]}"
        embedding = self.embedder.embed(content[:4000])
        return self.store.add_document(
            "documentation", doc_id, content[:4000], embedding,
            {"title": title[:200], "source": source, "ts": time.time()},
        )

    def index_state(self, state) -> None:
        """Batch-index all new incidents and final report from SharedState."""
        if not self.store.available:
            return
        # Index final report if present
        if state.final_report and state.current_task:
            self.index_report(state.final_report, state.current_task)

        # Index recent incidents
        for inc in state.incident_log[-10:]:
            self.index_incident(inc)

        # Index agent metric baselines
        for agent_name, entry in state.agents.items():
            if entry.metrics:
                self.index_baseline(agent_name, entry.metrics)

    @property
    def indexed_count(self) -> int:
        return self._indexed
