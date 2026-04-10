"""
Open Claw Stack — RAG Vector Store
=====================================
Local ChromaDB vector database.
Stores embeddings of past reports, incidents, and documentation.
No cloud dependency — fully sovereign.

Collections:
  - incident_reports : Final Product Lead reports
  - phasr_events     : Execwall block events
  - system_baselines : Agent metric snapshots over time
  - documentation    : Indexed reference docs
"""
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent.parent / "data" / "chroma_db"


class VectorStore:
    """Local ChromaDB wrapper for persistent agent memory."""

    COLLECTIONS = ["incident_reports", "phasr_events", "system_baselines", "documentation"]

    def __init__(self, persist_dir: Optional[Path] = None):
        self._persist_dir = str(persist_dir or DB_PATH)
        self._client      = None
        self._collections: Dict = {}
        self._available   = False
        self._init()

    def _init(self):
        try:
            import chromadb
            from chromadb.config import Settings
            self._client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            for name in self.COLLECTIONS:
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"},
                )
            self._available = True
            logger.info(f"VectorStore: ChromaDB initialized at {self._persist_dir}")
        except ImportError:
            logger.warning("VectorStore: chromadb not installed — run: pip install chromadb")
        except Exception as exc:
            logger.error(f"VectorStore: init failed: {exc}")

    # ──────────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────────

    def add_document(
        self,
        collection:  str,
        doc_id:      str,
        text:        str,
        embedding:   Optional[List[float]] = None,
        metadata:    Optional[Dict]        = None,
    ) -> bool:
        if not self._available:
            return False
        col = self._collections.get(collection)
        if not col:
            return False
        try:
            kwargs: Dict = {
                "documents": [text],
                "ids":       [doc_id],
                "metadatas": [metadata or {"ts": time.time()}],
            }
            if embedding:
                kwargs["embeddings"] = [embedding]

            # Upsert (update if exists)
            col.upsert(**kwargs)
            return True
        except Exception as exc:
            logger.error(f"VectorStore: add failed for {collection}/{doc_id}: {exc}")
            return False

    # ──────────────────────────────────────────────
    # Read
    # ──────────────────────────────────────────────

    def query(
        self,
        collection:  str,
        query_text:  str,
        embedding:   Optional[List[float]] = None,
        n_results:   int                   = 5,
    ) -> List[Dict]:
        if not self._available:
            return []
        col = self._collections.get(collection)
        if not col:
            return []
        try:
            kwargs: Dict = {"n_results": min(n_results, col.count() or 1)}
            if embedding:
                kwargs["query_embeddings"] = [embedding]
            else:
                kwargs["query_texts"] = [query_text]

            res = col.query(**kwargs)
            results = []
            for i, doc in enumerate(res.get("documents", [[]])[0]):
                results.append({
                    "text":     doc,
                    "id":       res["ids"][0][i],
                    "metadata": res["metadatas"][0][i] if res.get("metadatas") else {},
                    "distance": res["distances"][0][i] if res.get("distances") else 1.0,
                })
            return results
        except Exception as exc:
            logger.error(f"VectorStore: query failed: {exc}")
            return []

    def count(self, collection: str) -> int:
        if not self._available:
            return 0
        col = self._collections.get(collection)
        return col.count() if col else 0

    @property
    def available(self) -> bool:
        return self._available

    def status(self) -> Dict:
        return {
            "available":   self._available,
            "persist_dir": self._persist_dir,
            "collections": {
                name: self.count(name) for name in self.COLLECTIONS
            },
        }
