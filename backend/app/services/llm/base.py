"""The extraction contract. One method, one bounded call."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.schemas.preference import PreferenceObject


@runtime_checkable
class PreferenceExtractor(Protocol):
    """Turns a free-text request into a `PreferenceObject` (spec §7).

    Implementations must be bounded: a single request, structured JSON out, a
    short timeout, at most one retry. They return ``None`` (never raise) when
    they cannot produce a usable object, so the caller can fall back.
    """

    def extract(self, request_text: str) -> PreferenceObject | None: ...


@dataclass
class GeminiSuggestion:
    """One title Gemini judged to semantically fit the request — its own
    reasoning about genre/mood/tone/vibe, never a TMDb tag lookup.

    Deliberately thin: no rating, runtime, availability, or ID — Gemini is not
    the source of truth for facts, only for "does this title fit". Everything
    factual is filled in by resolving against TMDb/Open Library.
    """

    title: str
    media_type: str  # "movie" | "series" | "book"
    year: int | None
    reason: str


@dataclass
class GeminiRecommendation:
    """Result of one combined Gemini call: the same objective `PreferenceObject`
    `GeminiExtractor` would produce, plus a bounded list of semantic
    suggestions from the same call (spec: Phase 9 hybrid architecture)."""

    preferences: PreferenceObject
    suggestions: list[GeminiSuggestion]
