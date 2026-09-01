"""Google Gemini implementation of `PreferenceExtractor` (spec §10, §15 D7).

One bounded call: JSON-only response, low token cap, `temperature=0`, a single
short timeout, at most one retry. No tools, no multi-turn, no agent loop. Any
failure returns ``None`` so the caller falls back to the deterministic parser.
"""
from __future__ import annotations

import json
import logging

from app.schemas.preference import PreferenceObject, ReleaseWindow
from app.services.normalization import MOOD_TAG_VOCABULARY

logger = logging.getLogger("uvicorn.error")

DEFAULT_MODEL = "gemini-2.5-flash"
_TIMEOUT_MS = 8000
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

    media_type = [
        m for m in _clean_strlist(data.get("media_type")) if m in ("movie", "series", "book")
    ]
    length = data.get("length") if data.get("length") in ("short", "medium", "long") else None
    intensity = (
        data.get("intensity") if data.get("intensity") in ("low", "medium", "high") else None
    )

    return PreferenceObject(
        media_type=media_type or None,
        mood=_clean_strlist(data.get("mood")),
        tone=_clean_strlist(data.get("tone")),
        genres=_clean_strlist(data.get("genres")),
        length=length,
        intensity=intensity,
        language=_clean_strlist(data.get("language")),
        release_period=release_period,
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
