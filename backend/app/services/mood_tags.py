"""Mood/tone tagging for media items (spec §6.4).

A bounded, one-shot **Gemini** classification run on add (spec §15 D6), through
the shared provider-agnostic LLM layer (`app.services.llm`). This is **not** a
hard dependency: with no LLM provider configured the feature is simply off,
library creation still succeeds, and `mood_tags` stays empty until the backfill
runs (`python -m app.scripts.backfill_mood_tags`). No Anthropic dependency.
"""
from __future__ import annotations

import json
import logging

from app.services.llm import gemini_target
from app.services.normalization import MOOD_TAG_VOCABULARY

logger = logging.getLogger("uvicorn.error")

MAX_TAGS = 5


def is_enabled() -> bool:
    """True when mood-tag classification can run (an LLM provider is configured)."""
    return gemini_target() is not None


def _coerce_tags(raw: object) -> list[str]:
    """Keep only known-vocabulary tags, de-duplicated, capped."""
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for tag in raw:
        if isinstance(tag, str):
            t = tag.strip().lower()
            if t in MOOD_TAG_VOCABULARY and t not in seen:
                seen.append(t)
    return seen[:MAX_TAGS]


def _call_llm(prompt: str) -> str:
    """Single bounded LLM call. Isolated so it is easy to stub/replace."""
    from app.services.llm.gemini import GeminiMoodClassifier

    target = gemini_target()
    if target is None:  # pragma: no cover - guarded by is_enabled()
        raise RuntimeError("no LLM provider configured")
    api_key, model = target
    return GeminiMoodClassifier(api_key=api_key, model=model).classify(prompt)


def classify_mood_tags(
    *, title: str, description: str | None, genres: list[str], media_type: str
) -> list[str]:
    """Return a subset of MOOD_TAG_VOCABULARY describing the item's tone.

    Never raises: any failure logs and returns an empty list so the caller
    (library add) is unaffected.
    """
    if not is_enabled():
        return []

    vocab = ", ".join(MOOD_TAG_VOCABULARY)
    prompt = (
        f"Classify the mood/tone of this {media_type}. Choose only from this "
        f"fixed vocabulary: {vocab}.\n"
        f"Title: {title}\n"
        f"Genres: {', '.join(genres) or 'unknown'}\n"
        f"Synopsis: {description or 'unknown'}\n\n"
        f"Return ONLY a JSON array of 1-{MAX_TAGS} tags from the vocabulary, "
        "most salient first. No prose."
    )
    try:
        text = _call_llm(prompt)
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        return _coerce_tags(json.loads(text))
    except Exception as exc:  # noqa: BLE001 - feature must never break add
        logger.warning("mood_tags classification failed for %r: %s", title, exc)
        return []
