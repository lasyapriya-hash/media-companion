"""Recommendation session orchestrator (spec §8; Phase 9 hybrid architecture).

Flow (spec §8.1):
  request -> extracting -> [sparse AND no Gemini suggestions?] needs_clarification
          -> awaiting_answer -> (answer | decline | empty) -> ranking -> results
          -> [sufficient OR has Gemini suggestions?] ranking -> results
  any state -> error

Gemini (`GeminiRecommender`, via `_extract`) is the PRIMARY recommendation
intelligence: one bounded call both extracts the objective `PreferenceObject`
and judges which titles semantically fit the request (genre/mood/tone/vibe),
using its own knowledge — never a TMDb tag lookup. `gemini_pipeline` resolves
those suggestions against TMDb/Open Library and verifies only objective facts
(existence, language, media type, rating, release period); it never re-judges
semantic fit. The existing deterministic pipeline (`candidates.py`/
`scoring.py.rank`) is unchanged and used **only** as the fallback — when
Gemini is unavailable, times out, returns malformed output, or nothing it
suggested survives resolution + objective validation. The single clarifying
question is templated (`clarify.py`) — no LLM call.

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
from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject
from app.schemas.recommendation import RecommendationItem, RecommendationResponse
from app.services import taste_profile as taste_service
from app.services.llm import get_recommender, parse_preferences
from app.services.llm.base import GeminiSuggestion
from app.services.recommendations import gemini_pipeline
from app.services.recommendations.candidates import broad_candidates, build_candidates
from app.services.recommendations.clarify import clarifying_question, is_decline
from app.services.recommendations.merge import merge_preferences
from app.services.recommendations.reasons import build_reason
from app.services.recommendations.scoring import (
    hits_avoid,
    matches_explicit_genre,
    matches_explicit_language,
    passes_quality_floor,
    rank,
    satisfies_rating,
)

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
    """Apply every HARD constraint before anything is scored (spec §7).

    `avoid`, an explicit numeric rating bound, an explicitly-stated genre, and
    an explicitly-stated language are filters — a candidate that violates one
    is removed, never merely down-ranked by mood / taste / novelty. Soft
    preferences are left for `rank`.
    """
    return [
        it
        for it in items
        if (it.source, it.source_id) not in excluded
        and passes_quality_floor(it)
        and not hits_avoid(it, prefs.avoid)
        and satisfies_rating(it, prefs.rating)
        and matches_explicit_genre(it, prefs)
        and matches_explicit_language(it, prefs)
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
    """A purchase/access link only when the book API actually provides one; the
    field is otherwise omitted cleanly — no broken links (spec §5.4)."""
    media_type = getattr(item.type, "value", item.type)
    if media_type != "book":
        return None
    raw = item.raw_metadata if isinstance(item.raw_metadata, dict) else {}

    if item.source == "google_books":
        from app.clients.google_books import book_access_link

        return book_access_link(raw)

    # Open Library: link to the readable work only when it is actually readable.
    access = raw.get("ebook_access")
    if access in ("public", "borrowable", "printdisabled") or raw.get("ia"):
        return f"https://openlibrary.org/works/{item.source_id}"
    return None


def _extract(
    request_text: str | None,
    preferences: PreferenceObject | None,
    taste: TasteProfile,
) -> tuple[PreferenceObject, str, list[GeminiSuggestion] | None]:
    """Returns `(prefs, extraction_source, gemini_suggestions)`.

    `gemini_suggestions` is `None` when Gemini wasn't used or raised — the
    caller's signal to run the fully deterministic pipeline. When Gemini
    succeeds it may still return an empty list ("nothing genuinely fits");
    that is also a fallback signal, but it's for `_rank_and_finalize` to act
    on (after a resolution attempt), not this function.
    """
    if preferences is not None:
        return preferences, "fallback", None  # client-supplied; no LLM involved
    text = (request_text or "").strip()
    recommender = get_recommender()
    if recommender is not None:
        try:
            result = recommender.recommend(
                text, taste_context=gemini_pipeline.taste_context(taste)
            )
        except Exception as exc:  # noqa: BLE001 - defensive; recommender should not raise
            logger.warning("Gemini recommend raised, falling back: %s", exc)
            result = None
        if result is not None:
            return result.preferences, "llm", result.suggestions
    return parse_preferences(text), "fallback", None


# --------------------------------------------------------------------------- #
# Ranking (spec §8.2, §9) — shared by both turns
# --------------------------------------------------------------------------- #
def _rank_and_finalize(
    db: Session,
    session: RecommendationSession,
    prefs: PreferenceObject,
    extraction: str,
    limit: int,
    taste: TasteProfile,
    gemini_suggestions: list[GeminiSuggestion] | None = None,
) -> RecommendationResponse:
    session.state = SessionState.ranking
    session.preference_object = prefs.model_dump(mode="json")
    db.flush()

    excluded = _excluded_keys(db)
    items: list[RecommendationItem] = []

    if gemini_suggestions:
        # Primary path: Gemini already judged semantic fit. Resolve each
        # suggestion against real metadata and verify only objective facts —
        # never re-judge relevance by TMDb tag (spec: Phase 9). Gemini's own
        # order and reason are used as-is; the deterministic scorer never
        # touches this list.
        resolved = gemini_pipeline.resolve_and_validate(
            gemini_suggestions, prefs, excluded, limit
        )
        items = [
            RecommendationItem(
                media=media,
                score=score,
                reason=reason,
                availability=_availability(media),
                book_link=_book_link(media),
            )
            for media, score, reason in resolved
        ]

    if not items:
        # Fallback: Gemini unavailable, malformed, empty, or every suggestion
        # failed resolution/objective validation. The existing deterministic
        # pipeline, byte-for-byte unchanged.
        candidates, all_failed = build_candidates(prefs, taste)
        pool = _filter_pool(candidates, prefs, excluded)

        if not pool:
            # spec §8.2: `ranking` still yields a list unless every source is down.
            # The hard filters stay applied to the broad pull too — better an honest
            # empty list than a candidate that violates a stated bound.
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

    taste = taste_service.get_or_compute(db)

    # A pre-structured preference object is the caller's own answer — skip both
    # the LLM and the clarifying turn (spec §8.3 / Phase 4).
    if preferences is not None:
        session.clarification_used = True
        return _rank_and_finalize(db, session, preferences, "fallback", limit, taste)

    prefs, extraction, suggestions = _extract(text, None, taste)
    session.preference_object = prefs.model_dump(mode="json")

    # Gemini already having usable suggestions is itself sufficient — it means
    # the primary path can already answer, regardless of how sparse the
    # extracted structured object looks (spec: Phase 9 hybrid architecture).
    if suggestions or prefs.is_sufficient():
        return _rank_and_finalize(db, session, prefs, extraction, limit, taste, suggestions)

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

    taste = taste_service.get_or_compute(db)
    existing = PreferenceObject(**(session.preference_object or {}))
    answer = (answer_text or "").strip()
    session.clarification_answer = answer or None

    suggestions: list[GeminiSuggestion] | None = None
    if answer and not is_decline(answer):
        new_prefs, extraction, suggestions = _extract(answer, None, taste)
        merged = merge_preferences(existing, new_prefs)
    else:
        # Declined / empty -> straight to ranking with the existing prefs.
        merged, extraction = existing, "fallback"

    session.clarification_used = True  # set before ranking; invariant holds even on error
    return _rank_and_finalize(db, session, merged, extraction, limit, taste, suggestions)


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
