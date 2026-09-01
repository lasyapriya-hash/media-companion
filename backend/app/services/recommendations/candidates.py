"""Candidate generation for recommendations (spec §8.2, §9).

Driven entirely by the preference object and the taste profile — never by the
LLM. Every external call is best-effort; a provider that fails is logged and
skipped (spec §3.4). The orchestrator decides what an empty pool means.
"""
from __future__ import annotations

import datetime as _dt
import logging

from app.clients import openlibrary_client, tmdb_client
from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject, ReleaseWindow
from app.services.vocab import language_to_code, language_to_ol_code

logger = logging.getLogger("uvicorn.error")

SCREEN_TYPES = ("movie", "series")
_RECENT_SPAN_YEARS = 6
_CLASSIC_UNTIL_YEAR = 2000


def period_years(period: object) -> tuple[int | None, int | None]:
    """Resolve `release_period` to a (from_year, to_year) window."""
    if period is None:
        return None, None
    if isinstance(period, ReleaseWindow):
        return period.from_year, period.to_year
    if isinstance(period, dict):
        return period.get("from_year"), period.get("to_year")
    if period == "recent":
        now = _dt.date.today().year
        return now - _RECENT_SPAN_YEARS, None
    if period == "classic":
        return None, _CLASSIC_UNTIL_YEAR
    return None, None


def _dedupe(items: list[NormalizedMedia]) -> list[NormalizedMedia]:
    seen: set[tuple[str, str]] = set()
    out: list[NormalizedMedia] = []
    for it in items:
        key = (it.source, it.source_id)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _target_types(prefs: PreferenceObject) -> list[str]:
    return list(prefs.media_type) if prefs.media_type else ["movie", "series", "book"]


def build_candidates(
    prefs: PreferenceObject, taste: TasteProfile
) -> tuple[list[NormalizedMedia], bool]:
    """Return (candidates, all_calls_failed).

    When the preference object lacks genres/language/period the queries lean on
    the taste profile instead — this is the spec §8.3 "still sparse at ranking
    time" fallback (taste-profile-driven for screen media, favourite-genre
    popularity for books).
    """
    types = _target_types(prefs)
    year_from, year_to = period_years(prefs.release_period)

    screen_genres = prefs.genres or list(taste.favourite_genres[:3])
    book_subjects = prefs.genres or list(taste.favourite_genres[:3])
    pref_lang_codes = [c for c in (language_to_code(l) for l in prefs.language) if c]
    screen_langs: list[str | None] = pref_lang_codes[:2] or [None]
    ol_lang = next(
        (c for c in (language_to_ol_code(l) for l in prefs.language) if c), None
    )

    items: list[NormalizedMedia] = []
    attempts = failures = 0

    for media_type in types:
        if media_type in SCREEN_TYPES:
            for lang in screen_langs:
                attempts += 1
                try:
                    items += tmdb_client().discover(
                        media_type,
                        genres=screen_genres,
                        language=lang,
                        year_from=year_from,
                        year_to=year_to,
                        limit=20,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    logger.warning("TMDb discover (%s) failed: %s", media_type, exc)
        else:
            attempts += 1
            try:
                items += openlibrary_client().discover(
                    subjects=book_subjects, language=ol_lang, limit=25
                )
            except Exception as exc:  # noqa: BLE001
                failures += 1
                logger.warning("Open Library discover failed: %s", exc)

    all_failed = attempts > 0 and failures == attempts
    return _dedupe(items), all_failed


def broad_candidates(prefs: PreferenceObject) -> list[NormalizedMedia]:
    """Last-resort unfiltered pull so `ranking` still yields a list (spec §8.2)."""
    items: list[NormalizedMedia] = []
    for media_type in _target_types(prefs):
        try:
            if media_type in SCREEN_TYPES:
                items += tmdb_client().discover(media_type, limit=20)
            else:
                items += openlibrary_client().discover(subjects=None, limit=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("broad discover (%s) failed: %s", media_type, exc)
    return _dedupe(items)
