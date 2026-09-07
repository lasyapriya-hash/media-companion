"""Provider-agnostic LLM layer (spec §7, §10; Phase 9 hybrid architecture).

Gemini (`GeminiRecommender`) is the *primary* semantic recommendation
intelligence: given a request, it both extracts the objective `PreferenceObject`
and judges which titles genuinely fit semantically (genre/mood/tone/vibe),
using its own knowledge — never a fixed tag vocabulary. Deterministic code
never re-judges that semantic fit; it only resolves suggested titles against
real metadata providers and verifies genuinely objective facts (existence,
language, media type, rating, release period). The weighted deterministic
scorer (`app.services.recommendations.scoring.rank`) is untouched and used
**only** as the fallback path, exactly as before.

A full deterministic fallback (`app.services.llm.fallback` + the existing
candidate/scoring pipeline) covers every case where the provider is disabled,
key-less, times out, returns malformed output, or yields nothing usable after
resolution — so the app runs with **no Anthropic access and no paid/
subscription dependency**, and never fails a request merely because Gemini is
unavailable.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings
from app.services.llm.base import GeminiRecommendation, GeminiSuggestion, PreferenceExtractor
from app.services.llm.fallback import parse_preferences

if TYPE_CHECKING:
    from app.services.llm.gemini import GeminiRecommender

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


def get_recommender() -> "GeminiRecommender | None":
    """The primary recommendation-and-extraction call, or ``None`` when the LLM
    is disabled/unavailable — the orchestrator's signal to use the fully
    deterministic pipeline instead (spec: Phase 9 hybrid architecture)."""
    target = gemini_target()
    if target is None:
        return None
    from app.services.llm.gemini import GeminiRecommender

    api_key, model = target
    return GeminiRecommender(api_key=api_key, model=model)


__all__ = [
    "PreferenceExtractor",
    "GeminiSuggestion",
    "GeminiRecommendation",
    "gemini_target",
    "get_extractor",
    "get_recommender",
    "parse_preferences",
]
