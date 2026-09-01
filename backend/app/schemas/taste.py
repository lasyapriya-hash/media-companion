"""Response shape for the derived taste profile (spec §6.3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TasteProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    favourite_genres: list[str] = Field(default_factory=list)
    favourite_languages: list[str] = Field(default_factory=list)
    avg_rating_by_genre: dict[str, float] = Field(default_factory=dict)
    avg_rating_by_language: dict[str, float] = Field(default_factory=dict)
    completion_rate: float | None = None
    completion_rate_by_genre: dict[str, float] = Field(default_factory=dict)
    drop_patterns: list[str] = Field(default_factory=list)
    computed_at: datetime | None = None
