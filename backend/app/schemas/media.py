"""Common (provider-agnostic) media shapes produced by the normalization layer
(spec §5.2, §6.1). These are transport/DTO models, not database rows.
"""
import enum
from typing import Literal

from pydantic import BaseModel, Field


class LengthBucket(str, enum.Enum):
    short = "short"
    medium = "medium"
    long = "long"


class SeasonInfo(BaseModel):
    """One entry from TMDb's per-series `seasons` array (spec §6.1).

    `season_number == 0` is TMDb's "Specials" bucket — included here for
    completeness, but excluded from progress tracking (season selection,
    seasons_completed, advance/rollover) wherever that's relevant; TMDb's own
    aggregate `number_of_seasons`/`number_of_episodes` already exclude it too.
    """

    season_number: int
    name: str | None = None
    episode_count: int


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
    season_episode_counts: list[SeasonInfo] | None = None
    # Book
    author: str | None = None
    page_count: int | None = None

    # Derived
    length_bucket: LengthBucket | None = None
    mood_tags: list[str] = Field(default_factory=list)  # assigned later (Phase 2)

    raw_metadata: dict = Field(default_factory=dict)


class WatchAvailability(BaseModel):
    """TMDb watch-provider summary for one region (spec §5.4).

    `status` is always exactly `"available"` or `"unknown"` — never an error or
    a blank; the frontend renders "availability unknown" for the latter.
    """

    region: str = "IN"
    status: Literal["available", "unknown"]
    flatrate: list[str] = Field(default_factory=list)
    rent: list[str] = Field(default_factory=list)
    buy: list[str] = Field(default_factory=list)
    link: str | None = None
