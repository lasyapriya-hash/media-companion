"""Recommendation session orchestrator (spec §8).

Flow (spec §8.1):
  request -> extracting -> [sparse?] needs_clarification -> awaiting_answer
          -> (answer | decline | empty) -> ranking -> results
          -> [sufficient?] ranking -> results
  any state -> error

The LLM is used **only** for extraction (the request, and re-extraction of the
answer) and is always behind a deterministic fallback. Candidate generation,
scoring, ranking and reason text are deterministic backend code. The single
clarifying question is templated (`clarify.py`) — no LLM call.

Sessions are persisted (`recommendation_session`) so the two HTTP turns share
state; rows are debug data and may be pruned (spec §8.4).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import tmdb_client
from app.models.enums import LibraryStatus, SessionState
from app.models.library import LibraryEntry
from app.models.media import MediaItem
from app.models.recommendation import RecommendationSession
from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject
from app.schemas.recommendation import RecommendationItem, RecommendationResponse
from app.services import taste_profile as taste_service
from app.services.llm import get_extractor, parse_preferences
from app.services.recommendations.candidates import broad_candidates, build_candidates
from app.services.recommendations.clarify import clarifying_question, is_decline
from app.services.recommendations.merge import merge_preferences
from app.services.recommendations.reasons import build_reason
from app.services.recommendations.scoring import hits_avoid, passes_quality_floor, rank

logger = logging.getLogger("uvicorn.error")

DEFAULT_N = 8  # spec §15 D3
_EXCLUDED_STATUSES = (LibraryStatus.completed, LibraryStatus.dropped)  # spec §9
_ANSWERABLE_STATES = (SessionState.needs_clarification, SessionState.awaiting_answer)


class RecommendationError(RuntimeError):
    """All candidate data sources were unavailable (spec §8.2 -> `error`)."""


class SessionNotFound(Exception):
    pass


class ClarificationClosed(Exception):
    """The one clarifying question for this session is already spent (spec §8.2)."""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Ranking (spec §8.2, §9) — shared by both turns
# --------------------------------------------------------------------------- #
def _rank_and_finalize(
    db: Session,
    session: RecommendationSession,
    prefs: PreferenceObject,
    extraction: str,
    limit: int,
) -> RecommendationResponse:
    session.state = SessionState.ranking
    session.preference_object = prefs.model_dump(mode="json")
    db.flush()

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
        session.state = SessionState.error
        db.commit()
        raise RecommendationError("no recommendation data sources are reachable")

    ranked = rank(pool, prefs, taste, limit)
    items = [
        RecommendationItem(
            media=sc.item,
            score=sc.score,
            reason=build_reason(sc.item, prefs, sc.explanation, taste),
            availability=_availability(sc.item),
            book_link=_book_link(sc.item),
        )
        for sc in ranked
    ]

    session.results = [it.model_dump(mode="json") for it in items]
    session.state = SessionState.results
    db.commit()

    return RecommendationResponse(
        session_id=session.id,
        state="results",
        extraction=extraction,  # type: ignore[arg-type]
        preferences=prefs,
        clarification_question=None,
        results=items,
    )


# --------------------------------------------------------------------------- #
# Turn 1 — POST /recommendations
# --------------------------------------------------------------------------- #
def start_session(
    db: Session,
    *,
    request_text: str | None = None,
    preferences: PreferenceObject | None = None,
    limit: int = DEFAULT_N,
) -> RecommendationResponse:
    text = (request_text or "").strip()
    session = RecommendationSession(
        original_request=text or "(structured preferences)",
        state=SessionState.extracting,
    )
    db.add(session)
    db.flush()  # assign session.id

    # A pre-structured preference object is the caller's own answer — skip both
    # the LLM and the clarifying turn (spec §8.3 / Phase 4).
    if preferences is not None:
        session.clarification_used = True
        return _rank_and_finalize(db, session, preferences, "fallback", limit)

    prefs, extraction = _extract(text, None)
    session.preference_object = prefs.model_dump(mode="json")

    if prefs.is_sufficient():
        return _rank_and_finalize(db, session, prefs, extraction, limit)

    # Sparse -> ask exactly one templated question (spec §8.3).
    question = clarifying_question(prefs)
    session.clarification_question = question
    session.state = SessionState.awaiting_answer
    db.commit()

    return RecommendationResponse(
        session_id=session.id,
        state="needs_clarification",
        extraction=extraction,  # type: ignore[arg-type]
        preferences=prefs,
        clarification_question=question,
        results=[],
    )


# --------------------------------------------------------------------------- #
# Turn 2 — POST /recommendations/{id}/answer
# --------------------------------------------------------------------------- #
def answer_session(
    db: Session,
    session_id: uuid.UUID,
    answer_text: str | None,
    *,
    limit: int = DEFAULT_N,
) -> RecommendationResponse:
    session = db.get(RecommendationSession, session_id)
    if session is None:
        raise SessionNotFound(str(session_id))

    # One-question invariant (spec §8.2): once used, the flow can only go to
    # `ranking` — never back to another question.
    if session.clarification_used or session.state not in _ANSWERABLE_STATES:
        raise ClarificationClosed(str(session_id))

    existing = PreferenceObject(**(session.preference_object or {}))
    answer = (answer_text or "").strip()
    session.clarification_answer = answer or None

    if answer and not is_decline(answer):
        new_prefs, extraction = _extract(answer, None)
        merged = merge_preferences(existing, new_prefs)
    else:
        # Declined / empty -> straight to ranking with the existing prefs.
        merged, extraction = existing, "fallback"

    session.clarification_used = True  # set before ranking; invariant holds even on error
    return _rank_and_finalize(db, session, merged, extraction, limit)


# --------------------------------------------------------------------------- #
# Back-compat alias (single call -> full session start)
# --------------------------------------------------------------------------- #
def recommend(
    db: Session,
    *,
    request_text: str | None = None,
    preferences: PreferenceObject | None = None,
    limit: int = DEFAULT_N,
) -> RecommendationResponse:
    return start_session(
        db, request_text=request_text, preferences=preferences, limit=limit
    )
