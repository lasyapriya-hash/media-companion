"""Request/response shapes for the recommendation session (spec §5.3, §8, §9.4)."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject

# Client-facing session outcomes (spec §8.1). The DB keeps the full lifecycle
# (`extracting`/`awaiting_answer`/`ranking`/…); the API collapses it to these.
ClientState = Literal["needs_clarification", "results", "error"]


class RecommendationRequest(BaseModel):
    """Free text, a pre-structured preference object, or both.

    Supplying `preferences` bypasses both the LLM and the clarifying turn
    (spec §8.3 / Phase 4) — the caller has already stated its intent.
    """

    request: str | None = Field(default=None, max_length=2000)
    preferences: PreferenceObject | None = None

    @model_validator(mode="after")
    def _need_one(self) -> "RecommendationRequest":
        if not (self.request and self.request.strip()) and self.preferences is None:
            raise ValueError("provide `request` text or a `preferences` object")
        return self


class ClarificationAnswer(BaseModel):
    """The reply to the single clarifying question (spec §8.3).

    An empty / absent answer is valid — it means "just recommend"; the flow
    still proceeds straight to ranking.
    """

    answer: str | None = Field(default=None, max_length=2000)


class RecommendationItem(BaseModel):
    media: NormalizedMedia
    score: float
    reason: str
    availability: WatchAvailability | None = None  # movies/series (spec §5.4)
    book_link: str | None = None  # only when the book API returns one (spec §5.4)


class RecommendationResponse(BaseModel):
    session_id: uuid.UUID
    state: ClientState
    # Which path produced the current preference object. "fallback" also covers a
    # client-supplied `preferences` object and an empty/declined answer.
    extraction: Literal["llm", "fallback"]
    preferences: PreferenceObject
    # Present iff state == "needs_clarification".
    clarification_question: str | None = None
    # Present iff state == "results".
    results: list[RecommendationItem] = Field(default_factory=list)
