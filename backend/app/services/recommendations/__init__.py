"""Single-turn recommendation orchestrator (spec §8, Phase 4).

Flow: extract preferences (LLM if available, deterministic fallback otherwise)
-> build candidates from the preference object + taste profile -> exclude
completed/dropped library items and hard-filter `avoid` -> deterministic score
& rank -> top N with a templated reason and availability.

No session/state machine here — the clarifying turn is Phase 5. The LLM is used
only for extraction; everything else is deterministic backend code.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import tmdb_client
from app.models.enums import LibraryStatus
from app.models.library import LibraryEntry
from app.models.media import MediaItem
from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject
from app.schemas.recommendation import (
    RecommendationItem,
    RecommendationResponse,
)
from app.services import taste_profile as taste_service
from app.services.llm import get_extractor, parse_preferences
from app.services.recommendations.candidates import (
    broad_candidates,
    build_candidates,
)
from app.services.recommendations.reasons import build_reason
from app.services.recommendations.scoring import hits_avoid, passes_quality_floor, rank

logger = logging.getLogger("uvicorn.error")

DEFAULT_N = 8  # spec §15 D3
_EXCLUDED_STATUSES = (LibraryStatus.completed, LibraryStatus.dropped)  # spec §9


class RecommendationError(RuntimeError):
    """All candidate data sources were unavailable (spec §8.2 -> `error`)."""


def _excluded_keys(db: Session) -> set[tuple[str, str]]:
    rows = db.execute(
        select(MediaItem.source, MediaItem.source_id)
        .join(LibraryEntry, LibraryEntry.media_item_id == MediaItem.id)
        .where(LibraryEntry.status.in_(_EXCLUDED_STATUSES))
    ).all()
    return {(getattr(s, "value", s), sid) for s, sid in rows}


def _filter_pool(
    items: list[NormalizedMedia],
    prefs: PreferenceObject,
    excluded: set[tuple[str, str]],
) -> list[NormalizedMedia]:
    return [
        it
        for it in items
        if (it.source, it.source_id) not in excluded
        and passes_quality_floor(it)
        and not hits_avoid(it, prefs.avoid)
    ]


def _availability(item: NormalizedMedia) -> WatchAvailability | None:
    media_type = getattr(item.type, "value", item.type)
    if media_type not in ("movie", "series"):
        return None
    try:
        return tmdb_client().get_watch_providers(item.source_id, media_type)
    except Exception as exc:  # noqa: BLE001 - never an error to the user (spec §5.4)
        logger.warning("watch providers lookup failed for %s: %s", item.source_id, exc)
        return WatchAvailability(region="IN", status="unknown")


def _book_link(item: NormalizedMedia) -> str | None:
    media_type = getattr(item.type, "value", item.type)
    if media_type != "book":
        return None
    raw = item.raw_metadata if isinstance(item.raw_metadata, dict) else {}
    access = raw.get("ebook_access")
    if access in ("public", "borrowable", "printdisabled") or raw.get("ia"):
        return f"https://openlibrary.org/works/{item.source_id}"
    return None  # omit cleanly (spec §5.4)


def _extract(
    request_text: str | None, preferences: PreferenceObject | None
) -> tuple[PreferenceObject, str]:
    if preferences is not None:
        return preferences, "fallback"  # client-supplied; no LLM involved
    text = (request_text or "").strip()
    extractor = get_extractor()
    if extractor is not None:
        try:
            prefs = extractor.extract(text)
        except Exception as exc:  # noqa: BLE001 - defensive; extractor should not raise
            logger.warning("LLM extractor raised, falling back: %s", exc)
            prefs = None
        if prefs is not None:
            return prefs, "llm"
    return parse_preferences(text), "fallback"


def recommend(
    db: Session,
    *,
    request_text: str | None = None,
    preferences: PreferenceObject | None = None,
    limit: int = DEFAULT_N,
) -> RecommendationResponse:
    prefs, extraction = _extract(request_text, preferences)

    taste = taste_service.get_or_compute(db)
    excluded = _excluded_keys(db)

    candidates, all_failed = build_candidates(prefs, taste)
    pool = _filter_pool(candidates, prefs, excluded)

    if not pool:
        # spec §8.2: `ranking` still yields a list unless every source is down.
        broad = broad_candidates(prefs)
        if broad:
            all_failed = False
        pool = _filter_pool(broad, prefs, excluded)

    if not pool and all_failed:
        raise RecommendationError("no recommendation data sources are reachable")

    ranked = rank(pool, prefs, taste, limit)

    results = [
        RecommendationItem(
            media=sc.item,
            score=sc.score,
            reason=build_reason(sc.item, prefs, sc.explanation, taste),
            availability=_availability(sc.item),
            book_link=_book_link(sc.item),
        )
        for sc in ranked
    ]
    return RecommendationResponse(
        extraction=extraction, preferences=prefs, results=results
    )
