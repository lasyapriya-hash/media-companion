"""Unified library: add items, list them, and edit status/rating/review/
progress (spec §5.1, FR1, FR2).

Taste-profile recompute on rating/status change (FR9) is wired in Phase 3;
the seam is marked below.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import openlibrary_client, tmdb_client
from app.models.enums import LibraryStatus, MediaSource, MediaType
from app.models.library import LibraryEntry, SeriesProgress
from app.models.media import MediaItem
from app.schemas.library import UpdateEntryRequest, UpdateProgressRequest
from app.schemas.media import NormalizedMedia
from app.services import mood_tags

logger = logging.getLogger("uvicorn.error")

_MERGE_FIELDS = (
    "description",
    "language",
    "year",
    "external_rating",
    "artwork_url",
    "runtime_minutes",
    "seasons",
    "episodes",
    "episode_runtime_minutes",
    "author",
    "page_count",
)


# --------------------------------------------------------------------------- #
# Errors (mapped to HTTP in the router)
# --------------------------------------------------------------------------- #
class LibraryError(Exception):
    pass


class AlreadyInLibrary(LibraryError):
    pass


class EntryNotFound(LibraryError):
    pass


class NotASeries(LibraryError):
    pass


# --------------------------------------------------------------------------- #
# Metadata assembly
# --------------------------------------------------------------------------- #
def _merge(base: NormalizedMedia, extra: NormalizedMedia) -> NormalizedMedia:
    """Fill empty fields of `base` from `extra` (a details fetch)."""
    data = base.model_dump()
    for field in _MERGE_FIELDS:
        if not data.get(field) and getattr(extra, field) is not None:
            data[field] = getattr(extra, field)
    if not data.get("genres") and extra.genres:
        data["genres"] = extra.genres
    if extra.raw_metadata:
        data["raw_metadata"] = extra.raw_metadata
    return NormalizedMedia(**data)


def _enrich(item: NormalizedMedia) -> NormalizedMedia:
    """Best-effort details fetch; failures are non-fatal (spec NFR2)."""
    try:
        if item.source == "tmdb" and item.type in ("movie", "series"):
            return _merge(item, tmdb_client().get_details(item.source_id, item.type))
        if item.source == "open_library":
            return _merge(item, openlibrary_client().get_details(item.source_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "metadata enrichment failed for %s:%s: %s",
            item.source,
            item.source_id,
            exc,
        )
    return item


def _get_or_create_media_item(db: Session, item: NormalizedMedia) -> MediaItem:
    source = MediaSource(item.source)
    existing = db.scalar(
        select(MediaItem).where(
            MediaItem.source == source, MediaItem.source_id == item.source_id
        )
    )
    if existing is not None:
        return existing

    enriched = _enrich(item)
    tags: list[str] = []
    if mood_tags.is_enabled():
        tags = mood_tags.classify_mood_tags(
            title=enriched.title,
            description=enriched.description,
            genres=enriched.genres,
            media_type=enriched.type,
        )

    media = MediaItem(
        source=source,
        source_id=enriched.source_id,
        type=MediaType(enriched.type),
        title=enriched.title,
        description=enriched.description,
        genres=list(enriched.genres),
        language=enriched.language,
        year=enriched.year,
        external_rating=enriched.external_rating,
        artwork_url=enriched.artwork_url,
        runtime_minutes=enriched.runtime_minutes,
        seasons=enriched.seasons,
        episodes=enriched.episodes,
        episode_runtime_minutes=enriched.episode_runtime_minutes,
        author=enriched.author,
        page_count=enriched.page_count,
        mood_tags=tags,
        raw_metadata=enriched.raw_metadata or {},
    )
    db.add(media)
    db.flush()
    return media


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def add_to_library(
    db: Session,
    item: NormalizedMedia,
    status: LibraryStatus = LibraryStatus.want,
) -> LibraryEntry:
    media = _get_or_create_media_item(db, item)

    if db.scalar(
        select(LibraryEntry).where(LibraryEntry.media_item_id == media.id)
    ):
        raise AlreadyInLibrary(str(media.id))

    entry = LibraryEntry(media_item_id=media.id, status=status)
    db.add(entry)
    db.flush()
    if media.type == MediaType.series:
        db.add(SeriesProgress(library_entry_id=entry.id))
    db.commit()
    db.refresh(entry)
    return entry


def list_entries(
    db: Session, status: str | None = None, media_type: str | None = None
) -> list[LibraryEntry]:
    stmt = (
        select(LibraryEntry)
        .join(MediaItem, LibraryEntry.media_item_id == MediaItem.id)
        .order_by(LibraryEntry.added_at.desc())
    )
    if status:
        stmt = stmt.where(LibraryEntry.status == LibraryStatus(status))
    if media_type:
        stmt = stmt.where(MediaItem.type == MediaType(media_type))
    return list(db.scalars(stmt).unique())


def get_entry(db: Session, entry_id: uuid.UUID) -> LibraryEntry:
    entry = db.get(LibraryEntry, entry_id)
    if entry is None:
        raise EntryNotFound(str(entry_id))
    return entry


def update_entry(
    db: Session, entry_id: uuid.UUID, patch: UpdateEntryRequest
) -> LibraryEntry:
    entry = get_entry(db, entry_id)
    fields = patch.model_fields_set

    if "status" in fields and patch.status is not None:
        entry.status = patch.status
    if "rating" in fields:  # explicit null clears the rating
        entry.rating = patch.rating
    if "review" in fields:
        entry.review = patch.review
    if "favourite" in fields and patch.favourite is not None:
        entry.favourite = patch.favourite

    db.commit()
    db.refresh(entry)
    # Phase 3: recompute taste profile here when status or rating changed (FR9).
    return entry


def update_progress(
    db: Session, entry_id: uuid.UUID, patch: UpdateProgressRequest
) -> LibraryEntry:
    entry = get_entry(db, entry_id)
    if entry.media.type != MediaType.series:
        raise NotASeries(str(entry_id))

    progress = entry.progress or SeriesProgress(library_entry_id=entry.id)
    fields = patch.model_fields_set
    if "seasons_completed" in fields and patch.seasons_completed is not None:
        progress.seasons_completed = patch.seasons_completed
    if "current_season" in fields:
        progress.current_season = patch.current_season
    if "current_episode" in fields:
        progress.current_episode = patch.current_episode

    if progress not in db:
        db.add(progress)
    db.commit()
    db.refresh(entry)
    return entry
