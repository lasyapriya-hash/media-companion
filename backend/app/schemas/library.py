"""Request/response shapes for search and the unified library (spec §5.1, §5.2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import LibraryStatus
from app.schemas.media import LengthBucket, NormalizedMedia


# --------------------------------------------------------------------------- #
# Library: requests
# --------------------------------------------------------------------------- #
class AddToLibraryRequest(BaseModel):
    """The client sends back the normalized item it received from `/search`
    (spec §5.2 — no manual metadata entry), plus an optional initial status.
    """

    item: NormalizedMedia
    status: LibraryStatus = LibraryStatus.want


class UpdateEntryRequest(BaseModel):
    """Partial update: any subset of these fields (spec FR2)."""

    status: LibraryStatus | None = None
    rating: float | None = None
    review: str | None = None
    favourite: bool | None = None

    @field_validator("rating")
    @classmethod
    def _rating_range_and_step(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not (1.0 <= v <= 10.0) or round(v * 2) != v * 2:
            raise ValueError("rating must be between 1.0 and 10.0 in 0.5 steps")
        return v


class UpdateProgressRequest(BaseModel):
    """Series progress (spec §5.1). All optional; omitted fields are unchanged."""

    seasons_completed: int | None = Field(default=None, ge=0)
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)


# --------------------------------------------------------------------------- #
# Library: responses
# --------------------------------------------------------------------------- #
def _enum_value(v: object) -> object:
    """ORM columns hand back Enum members; responses want their string value."""
    return getattr(v, "value", v)


class MediaItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    source_id: str
    type: str

    _norm_source = field_validator("source", mode="before")(_enum_value)
    _norm_type = field_validator("type", mode="before")(_enum_value)
    title: str
    description: str | None = None
    genres: list[str] = Field(default_factory=list)
    language: str | None = None
    year: int | None = None
    external_rating: float | None = None
    artwork_url: str | None = None
    runtime_minutes: int | None = None
    seasons: int | None = None
    episodes: int | None = None
    episode_runtime_minutes: int | None = None
    author: str | None = None
    page_count: int | None = None
    mood_tags: list[str] = Field(default_factory=list)
    length_bucket: LengthBucket | None = None


class SeriesProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seasons_completed: int
    current_season: int | None = None
    current_episode: int | None = None
    updated_at: datetime


class LibraryEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    favourite: bool
    rating: float | None = None
    review: str | None = None
    added_at: datetime
    updated_at: datetime
    media: MediaItemOut
    progress: SeriesProgressOut | None = None

    _norm_status = field_validator("status", mode="before")(_enum_value)
