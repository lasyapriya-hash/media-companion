"""Google Gemini bindings — the only LLM provider (spec §10, §15 D6/D7).

Two bounded call types, each JSON-only, low token cap, `temperature=0`, one
short timeout, at most one retry, no tools / multi-turn / agent loop:

* `GeminiExtractor` — free text -> structured preference object (spec §7).
* `GeminiMoodClassifier` — synopsis + genres -> `mood_tags` subset (spec §6.4).

Both are optional: any failure is swallowed by the caller (deterministic
fallback for extraction; empty tags for mood). No Anthropic dependency.
"""
from __future__ import annotations

import json
import logging

from app.schemas.preference import PreferenceObject, RatingRange, ReleaseWindow
from app.services.llm.base import GeminiRecommendation, GeminiSuggestion
from app.services.normalization import MOOD_TAG_VOCABULARY
from app.services.vocab import normalise_mood_tone

logger = logging.getLogger("uvicorn.error")

# gemini-2.5-flash was retired for this project's API key/tier (404 "no longer
# available to new users"). Google's error pointed at gemini-3.6-flash, but
# that's a "thinking" model whose reasoning tokens are drawn from the same
# `max_output_tokens` budget as the visible JSON — live-verified it burns
# ~600 of 640 tokens on internal thoughts alone, truncating the actual answer
# (finish_reason=MAX_TOKENS) and running 5-17s. gemini-3.5-flash-lite is the
# lite-tier sibling: no reasoning-token overhead, consistently <2s, clean
# `finish_reason=STOP` — pinned, not "-latest", so behavior doesn't drift.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Must stay >= the API's own enforced minimum deadline (10s) or every call
# fails with 400 INVALID_ARGUMENT regardless of network conditions.
_TIMEOUT_MS = 12000
_MAX_OUTPUT_TOKENS = 640

# Union-free JSON schema for the structured-output call. `release_period` is
# flattened into three scalar fields and reassembled afterwards.
_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "media_type": {
            "type": "array",
            "items": {"type": "string", "enum": ["movie", "series", "book"]},
        },
        "mood": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "array", "items": {"type": "string"}},
        "genres": {"type": "array", "items": {"type": "string"}},
        "length": {"type": "string", "enum": ["short", "medium", "long"], "nullable": True},
        "intensity": {"type": "string", "enum": ["low", "medium", "high"], "nullable": True},
        "language": {"type": "array", "items": {"type": "string"}},
        "release_from_year": {"type": "integer", "nullable": True},
        "release_to_year": {"type": "integer", "nullable": True},
        "release_named": {
            "type": "string",
            "enum": ["recent", "classic"],
            "nullable": True,
        },
        # Explicit numeric rating bound (0–10). "above 7.5" -> min 7.5,
        # min_inclusive false; "at least 8" -> min 8, min_inclusive true.
        "rating_min": {"type": "number", "nullable": True},
        "rating_min_inclusive": {"type": "boolean", "nullable": True},
        "rating_max": {"type": "number", "nullable": True},
        "rating_max_inclusive": {"type": "boolean", "nullable": True},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "explicit_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["mood", "tone", "genres", "language", "avoid", "explicit_fields"],
}

_SYSTEM_INSTRUCTION = (
    "You convert a person's free-text description of what they feel like "
    "watching or reading into a compact JSON preference object. "
    "Extract only what the text supports; leave everything else empty or null. "
    "Do not invent genres or moods. "
    f"Prefer these mood words when they fit: {', '.join(MOOD_TAG_VOCABULARY)}. "
    "A 'love story' / 'romance' / 'romantic' request is the Romance genre "
    "(put 'Romance' in `genres`), not only a mood. "
    "If the user states a numeric review-score bound (e.g. 'rated above 7.5', "
    "'at least 8', 'below 6'), fill `rating_min`/`rating_max` on a 0–10 scale and "
    "set the matching `*_inclusive` flag ('above'/'over' -> exclusive; 'at least'/"
    "'or higher' -> inclusive); add 'rating' to `explicit_fields`. "
    "`explicit_fields` lists the field names the user stated outright (versus "
    "ones you inferred). `avoid` is for things to exclude. "
    "Respond with JSON only."
)

_STRLIST = ("media_type", "mood", "tone", "genres", "language", "avoid", "explicit_fields")


def _clean_strlist(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s and s.lower() not in {x.lower() for x in out}:
                out.append(s)
    return out


def _to_preference(data: dict) -> PreferenceObject:
    named = data.get("release_named")
    from_year = data.get("release_from_year")
    to_year = data.get("release_to_year")
    if named in ("recent", "classic"):
        release_period: object = named
    elif isinstance(from_year, int) or isinstance(to_year, int):
        release_period = ReleaseWindow(
            from_year=from_year if isinstance(from_year, int) else None,
            to_year=to_year if isinstance(to_year, int) else None,
        )
    else:
        release_period = None

    rmin = data.get("rating_min")
    rmax = data.get("rating_max")
    rating: RatingRange | None = None
    if isinstance(rmin, (int, float)) or isinstance(rmax, (int, float)):
        rating = RatingRange()
        if isinstance(rmin, (int, float)):
            v = max(0.0, min(10.0, float(rmin)))
            if data.get("rating_min_inclusive") is False:
                rating.gt = v
            else:
                rating.gte = v
        if isinstance(rmax, (int, float)):
            v = max(0.0, min(10.0, float(rmax)))
            if data.get("rating_max_inclusive") is False:
                rating.lt = v
            else:
                rating.lte = v
        if not rating.is_set():
            rating = None

    media_type = [
        m for m in _clean_strlist(data.get("media_type")) if m in ("movie", "series", "book")
    ]
    length = data.get("length") if data.get("length") in ("short", "medium", "long") else None
    intensity = (
        data.get("intensity") if data.get("intensity") in ("low", "medium", "high") else None
    )

    # Gemini's mood/tone strings are free-form ("pleasant", "cheery", ...); reduce
    # them to the canonical vocabularies so scoring can act on them — the same
    # mapping the deterministic fallback uses (spec §7).
    mood, tone = normalise_mood_tone(
        _clean_strlist(data.get("mood")), _clean_strlist(data.get("tone"))
    )

    return PreferenceObject(
        media_type=media_type or None,
        mood=mood,
        tone=tone,
        genres=_clean_strlist(data.get("genres")),
        length=length,
        intensity=intensity,
        language=_clean_strlist(data.get("language")),
        release_period=release_period,
        rating=rating,
        avoid=_clean_strlist(data.get("avoid")),
        explicit_fields=_clean_strlist(data.get("explicit_fields")),
    )


class GeminiExtractor:
    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL

    def _raw_call(self, request_text: str) -> str:
        # Lazy import: the SDK is an optional runtime dependency.
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
        resp = client.models.generate_content(
            model=self._model,
            contents=request_text.strip(),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.0,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        return (resp.text or "").strip()

    def extract(self, request_text: str) -> PreferenceObject | None:
        if not request_text or not request_text.strip():
            return None
        last_exc: Exception | None = None
        for attempt in (1, 2):  # one bounded retry
            try:
                text = self._raw_call(request_text)
                start, end = text.find("{"), text.rfind("}")
                if start != -1 and end != -1:
                    text = text[start : end + 1]
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("response was not a JSON object")
                return _to_preference(data)
            except Exception as exc:  # noqa: BLE001 - never propagate; fall back
                last_exc = exc
                logger.warning("Gemini extraction attempt %d failed: %s", attempt, exc)
        logger.warning("Gemini extraction giving up, using fallback: %s", last_exc)
        return None


# --------------------------------------------------------------------------- #
# Primary semantic recommendation (Phase 9 hybrid architecture) — one call
# that returns both the objective `PreferenceObject` (identical shape/parsing
# to `GeminiExtractor`) and a bounded list of title suggestions Gemini judged
# to fit the request *semantically*: genre, mood, tone, vibe, theme. Gemini
# reasons about this with its own knowledge — it is never told to imitate a
# fixed tag vocabulary, and the caller must never re-judge semantic fit by
# checking a resolved title's TMDb genre tags (that recreates exactly the bug
# this architecture exists to avoid). Only objective facts — existence,
# language, media type, rating, release period — are re-verified downstream.
# --------------------------------------------------------------------------- #
_RECOMMEND_MAX_OUTPUT_TOKENS = 1536
_MAX_SUGGESTIONS = 12

_RECOMMEND_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        **_RESPONSE_SCHEMA["properties"],
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "media_type": {
                        "type": "string",
                        "enum": ["movie", "series", "book"],
                    },
                    "year": {"type": "integer", "nullable": True},
                    "reason": {"type": "string"},
                },
                "required": ["title", "media_type", "reason"],
            },
        },
    },
    "required": [*_RESPONSE_SCHEMA["required"], "recommendations"],
}

_RECOMMEND_SYSTEM_INSTRUCTION = (
    _SYSTEM_INSTRUCTION + " "
    f"In addition, using your own knowledge of movies, series, and books — not "
    f"any fixed tag or genre vocabulary — recommend up to {_MAX_SUGGESTIONS} "
    "specific, real titles that genuinely fit the request's semantic meaning: "
    "its genre, mood, tone, themes, and vibe (for example: a love story, "
    "comedy, cozy, wholesome, feel-good, scary or explicitly NOT scary, "
    "slow-burn, bittersweet). You decide this yourself from what you actually "
    "know about each title — do not rely on how any database happens to tag "
    "it. Only recommend titles you are confident really exist; never invent "
    "one. For each, give the release year you associate it with (or null if "
    "unsure) and one concise sentence on why it fits — but never state a "
    "rating, runtime, or streaming availability in that reason; you are not "
    "the source of truth for those facts, they are verified separately. If "
    "the request says to avoid something, never recommend a title that "
    "clearly involves it. `recommendations` may be empty if nothing genuinely "
    "fits — never pad it with a weak or unrelated match. A taste-profile "
    "summary may follow the request as background context only: it must "
    "never override or substitute for anything the request states outright — "
    "an explicit language, genre, or title in the request always wins over a "
    "personalization preference."
)


def _to_suggestion(entry: object) -> GeminiSuggestion | None:
    if not isinstance(entry, dict):
        return None
    title = entry.get("title")
    media_type = entry.get("media_type")
    reason = entry.get("reason")
    if not isinstance(title, str) or not title.strip():
        return None
    if media_type not in ("movie", "series", "book"):
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    year = entry.get("year")
    return GeminiSuggestion(
        title=title.strip(),
        media_type=media_type,
        year=year if isinstance(year, int) else None,
        reason=reason.strip(),
    )


def _to_suggestions(value: object) -> list[GeminiSuggestion]:
    if not isinstance(value, list):
        return []
    out: list[GeminiSuggestion] = []
    for entry in value[:_MAX_SUGGESTIONS]:
        s = _to_suggestion(entry)
        if s is not None:
            out.append(s)
    return out


class GeminiRecommender:
    """The primary recommendation path (Phase 9). One bounded call; never
    raises. `PreferenceExtractor`-compatible (`extract`) plus `recommend`."""

    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL

    def _raw_call(self, request_text: str, taste_context: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
        contents = request_text.strip()
        if taste_context:
            contents = f"{contents}\n\n{taste_context}"
        resp = client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_RECOMMEND_SYSTEM_INSTRUCTION,
                temperature=0.0,
                max_output_tokens=_RECOMMEND_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema=_RECOMMEND_RESPONSE_SCHEMA,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        return (resp.text or "").strip()

    def recommend(
        self, request_text: str, *, taste_context: str = ""
    ) -> GeminiRecommendation | None:
        if not request_text or not request_text.strip():
            return None
        last_exc: Exception | None = None
        for attempt in (1, 2):  # one bounded retry
            try:
                text = self._raw_call(request_text, taste_context)
                start, end = text.find("{"), text.rfind("}")
                if start != -1 and end != -1:
                    text = text[start : end + 1]
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("response was not a JSON object")
                return GeminiRecommendation(
                    preferences=_to_preference(data),
                    suggestions=_to_suggestions(data.get("recommendations")),
                )
            except Exception as exc:  # noqa: BLE001 - never propagate; fall back
                last_exc = exc
                logger.warning("Gemini recommend attempt %d failed: %s", attempt, exc)
        logger.warning("Gemini recommend giving up, using fallback: %s", last_exc)
        return None


# --------------------------------------------------------------------------- #
# Mood-tag classification (spec §6.4) — the second bounded call type
# --------------------------------------------------------------------------- #
_MOOD_MAX_OUTPUT_TOKENS = 120
_MOOD_SCHEMA: dict = {
    "type": "array",
    "items": {"type": "string", "enum": list(MOOD_TAG_VOCABULARY)},
}


class GeminiMoodClassifier:
    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL

    def classify(self, prompt: str) -> str:
        """Return the raw JSON string; the caller coerces to known tags."""
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
        resp = client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=_MOOD_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema=_MOOD_SCHEMA,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        return (resp.text or "").strip()
