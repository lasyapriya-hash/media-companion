"""Provider-agnostic LLM layer for free-text -> preference extraction (spec §7,
§10).

The **only** LLM use in the recommendation flow. Candidate retrieval, scoring,
ranking and reason text are all deterministic and never call this. A deterministic
fallback (`app.services.llm.fallback`) covers every case where the provider is
disabled, key-less, or fails — so the app runs with **no Anthropic access and no
paid/subscription dependency**.
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.services.llm.base import PreferenceExtractor
from app.services.llm.fallback import parse_preferences

logger = logging.getLogger("uvicorn.error")

_DISABLED = {"", "none", "off", "disabled", "false"}


def get_extractor() -> PreferenceExtractor | None:
    """The configured extractor, or ``None`` when the LLM is disabled/unavailable.

    ``None`` is the signal to the orchestrator to use `parse_preferences`.
    """
    settings = get_settings()
    provider = (settings.llm_provider or "").strip().lower()
    if provider in _DISABLED:
        return None
    if provider == "gemini":
        if not settings.gemini_api_key:
            logger.info("LLM_PROVIDER=gemini but GEMINI_API_KEY is unset; using fallback")
            return None
        from app.services.llm.gemini import GeminiExtractor

        return GeminiExtractor(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model or None,
        )
    logger.warning("unknown LLM_PROVIDER %r; using deterministic fallback", provider)
    return None


__all__ = ["PreferenceExtractor", "get_extractor", "parse_preferences"]
