"""Gemini-primary recommendation pipeline (Phase 9 hybrid architecture).

Gemini is the semantic authority: it decides which titles fit a request's
genre/mood/tone/vibe (love story, cozy, funny, not-scary, ...) using its own
knowledge — never a TMDb tag lookup. This module never re-judges that
semantic fit. Its only two jobs are:

1. Resolve a Gemini-suggested title to a real, existing work (TMDb/Open
   Library search + a title/year confidence check) — the anti-hallucination
   guard. A title that doesn't resolve confidently is discarded, never shown.
2. Verify genuinely OBJECTIVE facts about the resolved work — existence,
   media type, language, rating threshold, release period, collection
   membership. These are facts a metadata provider can confirm or deny, not
   interpretive judgments, so they stay deterministic. Nothing here inspects
   TMDb's genre/mood tags to decide relevance — see `matches_explicit_genre`
   in scoring.py, which is deliberately NOT used on this path.

No synonym/tag vocabulary is added here — resolution is plain title-string
matching (stdlib `difflib`), not a semantic classifier.
"""
from __future__ import annotations

import difflib
import logging

from app.clients import google_books_client, openlibrary_client, tmdb_client
from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject
from app.services.llm.base import GeminiSuggestion
from app.services.recommendations.scoring import (
    matches_explicit_language,
    matches_explicit_media_type,
    matches_explicit_period,
    passes_quality_floor,
    satisfies_rating,
)

logger = logging.getLogger("uvicorn.error")

# Below this normalized title-similarity score, a search result is not
# considered a confident match — the suggestion is discarded rather than
# risking a wrong or hallucinated title being shown as real.
_SIMILARITY_THRESHOLD = 0.6
_YEAR_MATCH_BONUS = 0.05
_SEARCH_LIMIT = 5


# --------------------------------------------------------------------------- #
# Personalization context — background only, never an override (spec:
# "explicit request intent takes priority over taste personalization").
# --------------------------------------------------------------------------- #
def taste_context(taste: TasteProfile) -> str:
    parts: list[str] = []
    if taste.favourite_genres:
        parts.append(f"favourite genres: {', '.join(taste.favourite_genres[:5])}")
    if taste.favourite_languages:
        parts.append(f"favourite languages: {', '.join(taste.favourite_languages[:3])}")
    if taste.drop_patterns:
        parts.append(f"tends to drop/not finish: {', '.join(taste.drop_patterns[:3])}")
    if not parts:
        return ""
    return (
        "User's taste-profile summary, background context only — it must "
        "never override or substitute for anything the request states "
        "outright: " + "; ".join(parts) + "."
    )


# --------------------------------------------------------------------------- #
# Resolution — title-string matching only, no semantic judgment.
# --------------------------------------------------------------------------- #
def _normalize_title(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch.isspace()).strip()


def _title_score(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def best_match(
    candidates: list[NormalizedMedia], title: str, year: int | None
) -> NormalizedMedia | None:
    """The most confident title match among search results, or `None`.

    Pure string/year comparison — deliberately not a semantic check.
    """
    best: NormalizedMedia | None = None
    best_score = 0.0
    for c in candidates:
        score = _title_score(title, c.title)
        if year is not None and c.year is not None and abs(c.year - year) <= 1:
            score += _YEAR_MATCH_BONUS
        if score > best_score:
            best_score, best = score, c
    if best is not None and best_score >= _SIMILARITY_THRESHOLD:
        return best
    return None


def resolve_suggestion(suggestion: GeminiSuggestion) -> NormalizedMedia | None:
    """Resolve one Gemini suggestion against the real metadata providers.

    Only searches the media type Gemini declared — a suggestion that doesn't
    resolve there is discarded rather than guessed at under a different type.
    """
    media_type = suggestion.media_type
    try:
        if media_type in ("movie", "series"):
            candidates = tmdb_client().search(
                suggestion.title, media_type=media_type, limit=_SEARCH_LIMIT
            )
        else:
            candidates = openlibrary_client().search(suggestion.title, limit=_SEARCH_LIMIT)
            if not candidates:
                candidates = google_books_client().search(
                    suggestion.title, limit=_SEARCH_LIMIT
                )
    except Exception as exc:  # noqa: BLE001 - a resolution failure just discards this one
        logger.warning("resolution search failed for %r: %s", suggestion.title, exc)
        return None
    return best_match(candidates, suggestion.title, suggestion.year)


# --------------------------------------------------------------------------- #
# Objective validation — facts only. Deliberately excludes genre (semantic,
# Gemini's call) and `hits_avoid` (keyword-based semantic proxy, see its
# docstring in scoring.py) — those would recreate the tag-authority problem.
# --------------------------------------------------------------------------- #
def passes_objective_constraints(
    item: NormalizedMedia,
    prefs: PreferenceObject,
    excluded: set[tuple[str, str]],
) -> bool:
    return (
        (item.source, item.source_id) not in excluded
        and passes_quality_floor(item)
        and matches_explicit_media_type(item, prefs)
        and matches_explicit_language(item, prefs)
        and satisfies_rating(item, prefs.rating)
        and matches_explicit_period(item, prefs)
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def resolve_and_validate(
    suggestions: list[GeminiSuggestion],
    prefs: PreferenceObject,
    excluded: set[tuple[str, str]],
    limit: int,
) -> list[tuple[NormalizedMedia, float, str]]:
    """Resolve + objectively validate Gemini's suggestions, preserving
    Gemini's own order (that order — and each suggestion's own `reason` — IS
    the recommendation; nothing here re-ranks by a deterministic score).

    Returns (media, display_score, reason) triples, discarding anything that
    doesn't resolve confidently or fails an objective check, deduplicated by
    (source, source_id).
    """
    out: list[tuple[NormalizedMedia, float, str]] = []
    seen: set[tuple[str, str]] = set()
    total = max(len(suggestions), 1)
    for i, suggestion in enumerate(suggestions):
        media = resolve_suggestion(suggestion)
        if media is None:
            logger.info(
                "Gemini suggestion %r did not resolve confidently; discarded",
                suggestion.title,
            )
            continue
        key = (media.source, media.source_id)
        if key in seen:
            continue
        if not passes_objective_constraints(media, prefs, excluded):
            logger.info(
                "Gemini suggestion %r resolved to %s but failed an objective "
                "constraint; discarded",
                suggestion.title,
                key,
            )
            continue
        seen.add(key)
        # Positional, not a re-ranking: reflects Gemini's own ordering, in a
        # range that reads as "Gemini-scored" rather than pretending to be
        # the deterministic weighted formula.
        display_score = round(1.0 - (i / total) * 0.5, 4)
        out.append((media, display_score, suggestion.reason))
        if len(out) >= limit:
            break
    return out
