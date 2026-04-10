"""
Open Claw Stack — RAG Retriever
==================================
Queries the vector store for relevant past context.
Used by agents to recall similar past incidents before reasoning.

Example: Agent asks "have we seen high CPU before?"
         Retriever finds past sysadmin reports with similar patterns
         → Agent now knows this is recurring, not new
"""
import logging
from typing import Dict, List, Optional

from memory.vector_store import VectorStore
from memory.embedder     import Embedder

logger = logging.getLogger(__name__)


class Retriever:
    """RAG query interface for agents — gives them long-term memory."""

    def __init__(self, store: VectorStore, embedder: Embedder):
        self.store    = store
        self.embedder = embedder

    # ──────────────────────────────────────────────
    # Query Interface
    # ──────────────────────────────────────────────

    def recall_similar_incidents(self, query: str, n: int = 4) -> List[Dict]:
        """Find past reports most similar to the current task."""
        emb = self.embedder.embed(query)
        return self.store.query("incident_reports", query, emb, n_results=n)

    def recall_phasr_patterns(self, query: str, n: int = 4) -> List[Dict]:
        """Find similar PHASR block events in history."""
        emb = self.embedder.embed(query)
        return self.store.query("phasr_events", query, emb, n_results=n)

    def recall_baseline(self, agent_name: str, n: int = 3) -> List[Dict]:
        """Find historical baseline metrics for an agent."""
        query = f"{agent_name} metrics baseline"
        emb   = self.embedder.embed(query)
        return self.store.query("system_baselines", query, emb, n_results=n)

    def search_docs(self, query: str, n: int = 3) -> List[Dict]:
        """Search indexed documentation."""
        emb = self.embedder.embed(query)
        return self.store.query("documentation", query, emb, n_results=n)

    # ──────────────────────────────────────────────
    # Context Builder (for LLM augmentation)
    # ──────────────────────────────────────────────

    def build_context(self, task: str, max_chars: int = 2000) -> str:
        """
        Build a rich context string from multiple collections.
        Injected into agent reasoning prompts to provide historical awareness.
        """
        if not self.store.available:
            return ""

        sections = []

        # Past similar incidents
        incidents = self.recall_similar_incidents(task, n=3)
        if incidents:
            parts = [f"  • [{r['metadata'].get('ts_human','?')}] {r['text'][:200]}" for r in incidents]
            sections.append("**Relevant Past Reports:**\n" + "\n".join(parts))

        # PHASR patterns
        phasr = self.recall_phasr_patterns(task, n=2)
        if phasr:
            parts = [f"  • {r['text'][:150]}" for r in phasr]
            sections.append("**Historical PHASR Events:**\n" + "\n".join(parts))

        context = "\n\n".join(sections)
        return context[:max_chars] if context else ""

    # ──────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────

    def status(self) -> Dict:
        return {
            "store_available": self.store.available,
            "embedding_backend": self.embedder.backend,
            "collections": self.store.status().get("collections", {}),
        }
