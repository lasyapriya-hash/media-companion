"""Mood/tone tagging for media items (spec §6.4).

A bounded, one-shot Claude classification run on add (spec §15 D6). This is
**not** a hard dependency: if ANTHROPIC_API_KEY is unset the feature is simply
off, library creation still succeeds, and `mood_tags` stays empty until the
backfill runs (`python -m app.scripts.backfill_mood_tags`).

Only the Anthropic/Claude provider is used here, per spec §10. The recommendation
system's LLM approach is decided separately, later.
"""
from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.services.normalization import MOOD_TAG_VOCABULARY

logger = logging.getLogger("uvicorn.error")

# Small, cheap model for a constrained classification task.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TAGS = 5


def is_enabled() -> bool:
    """True when mood-tag classification can run (API key present)."""
    return bool(get_settings().anthropic_api_key)


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


def _call_anthropic(prompt: str) -> str:
    """Single bounded Claude call. Isolated so it is easy to stub/replace."""
    import anthropic  # lazy import: dependency is optional at runtime

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    msg = client.messages.create(
        model=get_settings().mood_tags_model or DEFAULT_MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text
        for block in msg.content
        if getattr(block, "type", None) == "text"
    ).strip()


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
        text = _call_anthropic(prompt)
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        return _coerce_tags(json.loads(text))
    except Exception as exc:  # noqa: BLE001 - feature must never break add
        logger.warning("mood_tags classification failed for %r: %s", title, exc)
        return []
