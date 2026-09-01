"""Taste-profile service (spec §6.3, FR9).

A *derived* record — not a trained model. Recomputed from the whole library on
every rating change and every status change (wired in ``app.services.library``).
Single-user instance, so there is exactly one row (``SINGLETON_ID``).

Field definitions (spec §6.3):

* ``favourite_genres`` / ``favourite_languages`` — labels ranked by
  ``count(completed) + count(favourite)``, then by mean personal rating, then by
  name. Labels with a zero score are omitted.
* ``avg_rating_by_genre`` / ``avg_rating_by_language`` — mean personal rating
  over rated entries carrying that label.
* ``completion_rate`` — ``completed / (completed + dropped)`` overall, and the
  per-genre map ``completion_rate_by_genre``. ``None`` when the denominator is 0.
* ``drop_patterns`` — genres/languages whose completion rate sits below
  ``DROP_PATTERN_THRESHOLD`` with at least ``DROP_PATTERN_MIN_SAMPLE`` decided
  entries (completed + dropped).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import LibraryEntry
from app.models.taste import SINGLETON_ID, TasteProfile

# How many labels to keep in each ranked "favourite" list.
FAVOURITE_LIST_LIMIT = 10
# A label counts as a drop pattern when its completion rate is strictly below
# this and it has been "decided" (completed or dropped) at least this many times.
DROP_PATTERN_THRESHOLD = 0.5
DROP_PATTERN_MIN_SAMPLE = 2


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _rank_labels(
    completed: dict[str, int],
    favourite: dict[str, int],
    avg_rating: dict[str, float | None],
) -> list[str]:
    """Rank labels by (completed + favourite) count, then mean rating, then name."""
    scored: list[tuple[str, int, float]] = []
    for label in set(completed) | set(favourite):
        score = completed.get(label, 0) + favourite.get(label, 0)
        if score <= 0:
            continue
        scored.append((label, score, avg_rating.get(label) or 0.0))
    scored.sort(key=lambda t: (-t[1], -t[2], t[0]))
    return [label for label, _, _ in scored][:FAVOURITE_LIST_LIMIT]


def _completion_rate(completed: int, dropped: int) -> float | None:
    decided = completed + dropped
    return round(completed / decided, 3) if decided else None


def recompute(db: Session) -> TasteProfile:
    """Rebuild the singleton taste profile from the current library. Commits."""
    entries = list(db.scalars(select(LibraryEntry)).unique())

    completed_by_genre: dict[str, int] = defaultdict(int)
    dropped_by_genre: dict[str, int] = defaultdict(int)
    favourite_by_genre: dict[str, int] = defaultdict(int)
    ratings_by_genre: dict[str, list[float]] = defaultdict(list)

    completed_by_lang: dict[str, int] = defaultdict(int)
    dropped_by_lang: dict[str, int] = defaultdict(int)
    favourite_by_lang: dict[str, int] = defaultdict(int)
    ratings_by_lang: dict[str, list[float]] = defaultdict(list)

    total_completed = total_dropped = 0

    for entry in entries:
        media = entry.media
        status = getattr(entry.status, "value", entry.status)
        rating = float(entry.rating) if entry.rating is not None else None
        is_favourite = bool(entry.favourite)

        if status == "completed":
            total_completed += 1
        elif status == "dropped":
            total_dropped += 1

        labels: list[tuple[str, dict, dict, dict, dict]] = []
        for genre in media.genres or []:
            labels.append(
                (genre, completed_by_genre, dropped_by_genre,
                 favourite_by_genre, ratings_by_genre)
            )
        if media.language:
            labels.append(
                (media.language, completed_by_lang, dropped_by_lang,
                 favourite_by_lang, ratings_by_lang)
            )

        for label, completed_map, dropped_map, favourite_map, ratings_map in labels:
            if status == "completed":
                completed_map[label] += 1
            elif status == "dropped":
                dropped_map[label] += 1
            if is_favourite:
                favourite_map[label] += 1
            if rating is not None:
                ratings_map[label].append(rating)

    avg_rating_by_genre = {
        g: _mean(v) for g, v in ratings_by_genre.items() if v
    }
    avg_rating_by_language = {
        lang: _mean(v) for lang, v in ratings_by_lang.items() if v
    }

    completion_rate_by_genre: dict[str, float] = {}
    for genre in set(completed_by_genre) | set(dropped_by_genre):
        rate = _completion_rate(
            completed_by_genre.get(genre, 0), dropped_by_genre.get(genre, 0)
        )
        if rate is not None:
            completion_rate_by_genre[genre] = rate

    drop_patterns: list[str] = []
    for completed_map, dropped_map in (
        (completed_by_genre, dropped_by_genre),
        (completed_by_lang, dropped_by_lang),
    ):
        for label in set(completed_map) | set(dropped_map):
            decided = completed_map.get(label, 0) + dropped_map.get(label, 0)
            if decided >= DROP_PATTERN_MIN_SAMPLE and (
                completed_map.get(label, 0) / decided < DROP_PATTERN_THRESHOLD
            ):
                drop_patterns.append(label)
    drop_patterns.sort()

    profile = db.get(TasteProfile, SINGLETON_ID)
    if profile is None:
        profile = TasteProfile(id=SINGLETON_ID)
        db.add(profile)

    profile.favourite_genres = _rank_labels(
        completed_by_genre, favourite_by_genre, avg_rating_by_genre
    )
    profile.favourite_languages = _rank_labels(
        completed_by_lang, favourite_by_lang, avg_rating_by_language
    )
    profile.avg_rating_by_genre = avg_rating_by_genre
    profile.avg_rating_by_language = avg_rating_by_language
    profile.completion_rate = _completion_rate(total_completed, total_dropped)
    profile.completion_rate_by_genre = completion_rate_by_genre
    profile.drop_patterns = drop_patterns
    profile.computed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(profile)
    return profile


def get_or_compute(db: Session) -> TasteProfile:
    """Return the singleton profile, computing it once if it has never been built."""
    profile = db.get(TasteProfile, SINGLETON_ID)
    if profile is None:
        profile = recompute(db)
    return profile
