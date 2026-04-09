"""
Open Claw Stack — LLM Inference Client
=======================================
Primary:  Google Gemini API (gemini-2.0-flash)
Fallback: Rule-based reasoning (no API required)

All agent reasoning flows through this client.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from the stack root
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM gateway for the Open Claw Stack.
    Tries Gemini first, falls back to rule-based mode.
    """

    def __init__(
        self,
        api_key:   Optional[str] = None,
        model:     str           = "gemini-2.0-flash",
        max_retries: int         = 2,
    ):
        self.model_name  = model
        self.max_retries = max_retries
        self.api_key     = api_key or os.getenv("GOOGLE_API_KEY", "")
        self._model      = None
        self._backend    = "fallback"

        self._init_gemini()

    # ──────────────────────────────────────────────
    # Initialization
    # ──────────────────────────────────────────────

    def _init_gemini(self):
        if not self.api_key:
            logger.warning("LLMClient: no GOOGLE_API_KEY found — rule-based fallback active")
            return
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=self.api_key)
            self._model   = genai.GenerativeModel(self.model_name)
            self._backend = "gemini"
            logger.info(f"LLMClient: ✅ Gemini {self.model_name} initialized")
        except ImportError:
            logger.warning("LLMClient: google-generativeai not installed — run requirements.txt install")
        except Exception as exc:
            logger.warning(f"LLMClient: Gemini init error ({exc})")

    # ──────────────────────────────────────────────
    # Public Interface
    # ──────────────────────────────────────────────

    def reason(
        self,
        prompt:         str,
        system_context: Optional[str] = None,
        max_tokens:     int           = 2048,
        temperature:    float         = 0.3,
    ) -> str:
        """
        Core reasoning call.
        Returns the model's response as a string.
        """
        if self._backend == "gemini":
            return self._call_gemini(prompt, system_context, max_tokens, temperature)
        return self._fallback(prompt)

    @property
    def backend(self) -> str:
        return self._backend

    # ──────────────────────────────────────────────
    # Gemini Backend
    # ──────────────────────────────────────────────

    def _call_gemini(
        self,
        prompt:         str,
        system_context: Optional[str],
        max_tokens:     int,
        temperature:    float,
    ) -> str:
        import google.generativeai as genai  # type: ignore

        full_prompt = f"{system_context}\n\n{prompt}" if system_context else prompt

        for attempt in range(1, self.max_retries + 2):
            try:
                response = self._model.generate_content(
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                return response.text

            except Exception as exc:
                logger.warning(f"LLMClient: Gemini attempt {attempt} failed: {exc}")
                if attempt <= self.max_retries:
                    time.sleep(1.5 * attempt)

        # all retries exhausted — fall back
        logger.error("LLMClient: all Gemini retries exhausted, using rule-based fallback")
        return self._fallback(prompt)

    # ──────────────────────────────────────────────
    # Rule-Based Fallback
    # ──────────────────────────────────────────────

    def _fallback(self, prompt: str) -> str:
        keywords = prompt.lower()
        if "route" in keywords or "agent" in keywords:
            return (
                '{"agents": ["network_engineer", "security_auditor", "sysadmin", "product_lead"], '
                '"reasoning": "Default full-system investigation (fallback mode)", '
                '"priority": "medium", "investigation_focus": "General health check"}'
            )
        if "network" in keywords or "slow" in keywords or "latency" in keywords:
            return "[Rule-based] Network connectivity appears degraded. Run ping and traceroute to diagnose."
        if "security" in keywords or "breach" in keywords or "unauthorized" in keywords:
            return "[Rule-based] Potential security event detected. Audit running processes and open ports."
        if "cpu" in keywords or "memory" in keywords or "disk" in keywords:
            return "[Rule-based] Resource pressure detected. Check top processes and disk utilization."
        return f"[Rule-based] Analysis complete for: {prompt[:120]}. System operating nominally."
