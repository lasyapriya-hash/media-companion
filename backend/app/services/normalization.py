"""Provider-agnostic normalization rules (spec §6.4).

Pure functions only — no I/O. The API clients call these after fetching.
"""
from app.schemas.media import LengthBucket

# Fixed vocabulary for mood/tone tagging (spec §6.4). Assignment happens in
# Phase 2 (a bounded Claude call on add); kept here as the single source of truth.
MOOD_TAG_VOCABULARY: tuple[str, ...] = (
    "cozy",
    "tense",
    "feel-good",
    "dark",
    "bittersweet",
    "slow-burn",
    "high-energy",
    "cerebral",
    "escapist",
    "romantic",
    "bleak",
    "wholesome",
)


def length_bucket(
    media_type: str,
    *,
    runtime_minutes: int | None = None,
    episode_runtime_minutes: int | None = None,
    page_count: int | None = None,
) -> LengthBucket | None:
    """Map a duration/length to a bucket per spec §6.4.

    movie   : <90 short, 90–150 medium, >150 long   (by runtime_minutes)
    series  : <30 short, 30–50 medium, >50 long     (by episode_runtime_minutes)
    book    : <250 short, 250–500 medium, >500 long (by page_count)

    Returns None when the relevant measure is missing.
    """
    if media_type == "movie" and runtime_minutes:
        v = runtime_minutes
        return (
            LengthBucket.short
            if v < 90
            else LengthBucket.medium
            if v <= 150
            else LengthBucket.long
        )
    if media_type == "series" and episode_runtime_minutes:
        v = episode_runtime_minutes
        return (
            LengthBucket.short
            if v < 30
            else LengthBucket.medium
            if v <= 50
            else LengthBucket.long
        )
    if media_type == "book" and page_count:
        v = page_count
        return (
            LengthBucket.short
            if v < 250
            else LengthBucket.medium
            if v <= 500
            else LengthBucket.long
        )
    return None
