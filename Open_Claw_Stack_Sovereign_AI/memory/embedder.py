"""
Open Claw Stack — RAG Embedder
================================
Generates text embeddings using Gemini text-embedding-004.
Used by the Indexer to store documents and the Retriever to query them.

Falls back to a simple hash-based pseudo-embedding if Gemini unavailable.
"""
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM   = 768


class Embedder:
    """Generates text embeddings for RAG memory storage and retrieval."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key  = api_key or os.getenv("GOOGLE_API_KEY", "")
        self._model   = None
        self._backend = "fallback"
        self._init()

    def _init(self):
        if not self.api_key:
            logger.warning("Embedder: no API key — using hash-based fallback")
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._backend = "gemini"
            logger.info(f"Embedder: Gemini {EMBEDDING_MODEL} ready")
        except Exception as exc:
            logger.warning(f"Embedder: Gemini init failed ({exc}) — using fallback")

    # ──────────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────────

    def embed(self, text: str) -> List[float]:
        """Embed a single text string. Returns a float vector."""
        if self._backend == "gemini":
            return self._gemini_embed(text)
        return self._fallback_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts. Returns list of vectors."""
        return [self.embed(t) for t in texts]

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM

    # ──────────────────────────────────────────────
    # Backends
    # ──────────────────────────────────────────────

    def _gemini_embed(self, text: str) -> List[float]:
        try:
            import google.generativeai as genai
            result = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=text[:8000],                # model context limit
                task_type="RETRIEVAL_DOCUMENT",
            )
            return result["embedding"]
        except Exception as exc:
            logger.warning(f"Embedder: Gemini embed failed ({exc}) — falling back")
            return self._fallback_embed(text)

    def _fallback_embed(self, text: str) -> List[float]:
        """
        Deterministic pseudo-embedding based on SHA-256 hash.
        Not semantically meaningful but allows ChromaDB to store/retrieve documents.
        Querying with query_texts (not embeddings) still works via ChromaDB's built-in embedder.
        """
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(0, min(len(h) * 4, EMBEDDING_DIM * 4), 4):
            hi = i // 4 % len(h)
            lo = (i // 4 + 1) % len(h)
            val = ((h[hi] << 8) | h[lo]) / 65535.0 - 0.5
            vec.append(val)
        # Pad to full dimension
        while len(vec) < EMBEDDING_DIM:
            vec.extend(vec[:EMBEDDING_DIM - len(vec)])
        return vec[:EMBEDDING_DIM]
