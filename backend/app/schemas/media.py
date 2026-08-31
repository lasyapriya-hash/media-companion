"""Common (provider-agnostic) media shapes produced by the normalization layer
(spec §5.2, §6.1). These are transport/DTO models, not database rows.
"""
import enum

from pydantic import BaseModel, Field


class LengthBucket(str, enum.Enum):
    short = "short"
    medium = "medium"
    long = "long"


class NormalizedMedia(BaseModel):
    """One search/discovery result in the unified shape."""

    source: str  # "tmdb" | "open_library" | "google_books"
    source_id: str
    type: str  # "movie" | "series" | "book"

    title: str
    description: str | None = None
    genres: list[str] = Field(default_factory=list)
    language: str | None = None
    year: int | None = None
    external_rating: float | None = None  # normalized 0–10
    artwork_url: str | None = None

    # Movie
    runtime_minutes: int | None = None
    # Series
    seasons: int | None = None
    episodes: int | None = None
    episode_runtime_minutes: int | None = None
    # Book
    author: str | None = None
    page_count: int | None = None

    # Derived
    length_bucket: LengthBucket | None = None
    mood_tags: list[str] = Field(default_factory=list)  # assigned later (Phase 2)

    raw_metadata: dict = Field(default_factory=dict)


class WatchAvailability(BaseModel):
    """TMDb watch-provider summary for one region (spec §5.4)."""

    region: str = "IN"
    status: str  # "available" | "unknown"
    flatrate: list[str] = Field(default_factory=list)
    rent: list[str] = Field(default_factory=list)
    buy: list[str] = Field(default_factory=list)
    link: str | None = None
