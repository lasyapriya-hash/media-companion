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


def gemini_target() -> tuple[str, str] | None:
    """`(api_key, model)` when Gemini is configured, else ``None``.

    The single source of truth for "is the LLM provider available?" — shared by
    the preference extractor (spec §7) and the `mood_tags` classifier (spec
    §6.4). Anthropic is not referenced anywhere.
    """
    settings = get_settings()
    provider = (settings.llm_provider or "").strip().lower()
    if provider in _DISABLED:
        return None
    if provider != "gemini":
        logger.warning("unknown LLM_PROVIDER %r; LLM features disabled", provider)
        return None
    if not settings.gemini_api_key:
        return None
    from app.services.llm.gemini import DEFAULT_MODEL

    return settings.gemini_api_key, (settings.gemini_model or DEFAULT_MODEL)


def get_extractor() -> PreferenceExtractor | None:
    """The configured extractor, or ``None`` when the LLM is disabled/unavailable.

    ``None`` is the signal to the orchestrator to use `parse_preferences`.
    """
    target = gemini_target()
    if target is None:
        return None
    from app.services.llm.gemini import GeminiExtractor

    api_key, model = target
    return GeminiExtractor(api_key=api_key, model=model)


__all__ = ["PreferenceExtractor", "gemini_target", "get_extractor", "parse_preferences"]
