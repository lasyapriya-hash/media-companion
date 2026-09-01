"""Request/response shapes for `POST /recommendations` (spec §5.3, §9.4)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject


class RecommendationRequest(BaseModel):
    """Free text, a pre-structured preference object, or both.

    Supplying `preferences` bypasses the LLM entirely (spec §8.3 / Phase 4).
    """

    request: str | None = Field(default=None, max_length=2000)
    preferences: PreferenceObject | None = None

    @model_validator(mode="after")
    def _need_one(self) -> "RecommendationRequest":
        if not (self.request and self.request.strip()) and self.preferences is None:
            raise ValueError("provide `request` text or a `preferences` object")
        return self


class RecommendationItem(BaseModel):
    media: NormalizedMedia
    score: float
    reason: str
    availability: WatchAvailability | None = None  # movies/series (spec §5.4)
    book_link: str | None = None  # only when the book API returns one (spec §5.4)


class RecommendationResponse(BaseModel):
    # Which path produced the preference object. "fallback" also covers a
    # client-supplied `preferences` object (no LLM was involved).
    extraction: Literal["llm", "fallback"]
    preferences: PreferenceObject
    results: list[RecommendationItem]
