"""Regression: an explicitly-stated language is a HARD filter (spec §7), not
only a soft scoring signal.

Diagnosed bug: "telugu lovestory movie" returned "The Last Sunrise" (English)
because `_filter_pool` enforced genre/rating/avoid as hard constraints but had
no equivalent for language — `_language_signal` in scoring.py only nudges the
score, it never excludes a candidate. Live-reproduced with the real
`broad_candidates()` + `_filter_pool()` functions: a wrong-language title with
a matching genre sailed straight through. This file pins the fix — a new
`matches_explicit_language()` wired into `_filter_pool` — at the unit level.
API-level end-to-end coverage (including the exact reported request) is in
test_recommendations.py.
"""
from __future__ import annotations

import pytest

from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject
from app.services.recommendations import _filter_pool
from app.services.recommendations.candidates import build_candidates
from app.services.recommendations.scoring import explicit_languages, matches_explicit_language


class _SpyTMDb:
    """Minimal double recording every `discover()` call's params."""

    def __init__(self):
        self.discover_calls: list[tuple] = []

    def discover(self, media_type, *, genres=None, language=None, year_from=None,
                 year_to=None, rating_gte=None, limit=20):
        self.discover_calls.append(("tmdb", media_type, tuple(genres or []), language, rating_gte))
        return []


@pytest.fixture()
def spy_tmdb(monkeypatch):
    spy = _SpyTMDb()
    monkeypatch.setattr(
        "app.services.recommendations.candidates.tmdb_client", lambda: spy
    )
    return spy


def _movie(sid, *, language, genres=("Romance",), rating=7.0, popularity=40.0, type="movie"):
    return NormalizedMedia(
        source="tmdb", source_id=sid, type=type, title=f"M {sid}",
        genres=list(genres), language=language, year=2020, external_rating=rating,
        raw_metadata={"popularity": popularity},
    )


# --------------------------------------------------------------------------- #
# `explicit_languages` / `matches_explicit_language` — unit behavior
# --------------------------------------------------------------------------- #
def test_explicit_languages_none_when_not_stated():
    prefs = PreferenceObject(genres=["romance"], explicit_fields=["genres"])
    assert explicit_languages(prefs) is None


def test_explicit_languages_resolves_known_name_case_insensitively():
    prefs = PreferenceObject(language=["Telugu"], explicit_fields=["language"])
    assert explicit_languages(prefs) == {"te"}


def test_explicit_languages_unresolved_is_empty_set_not_none():
    """An explicit but unrecognised language must still act as a filter —
    distinguishable from "no constraint" (None)."""
    prefs = PreferenceObject(language=["Klingon"], explicit_fields=["language"])
    want = explicit_languages(prefs)
    assert want is not None
    assert want == set()


def test_matches_explicit_language_true_when_no_constraint():
    prefs = PreferenceObject()
    assert matches_explicit_language(_movie("A", language="en"), prefs) is True
    assert matches_explicit_language(_movie("B", language="te"), prefs) is True


def test_matches_explicit_language_rejects_wrong_language():
    prefs = PreferenceObject(language=["Telugu"], explicit_fields=["language"])
    assert matches_explicit_language(_movie("EN", language="en"), prefs) is False
    assert matches_explicit_language(_movie("TE", language="te"), prefs) is True


def test_matches_explicit_language_unresolved_rejects_every_candidate():
    prefs = PreferenceObject(language=["Klingon"], explicit_fields=["language"])
    for lang in ("en", "te", "hi", "ja", ""):
        assert matches_explicit_language(_movie("X", language=lang), prefs) is False


def test_matches_explicit_language_exempts_books():
    """Open Library/Google Books use inconsistent language-code formats (the
    project's own OL 3-letter map is missing several Indian languages) —
    mirrors the existing `matches_explicit_genre` book exemption."""
    prefs = PreferenceObject(language=["Telugu"], explicit_fields=["language"])
    book = _movie("BK", language="eng", type="book")  # OL 3-letter code, deliberately "wrong" shape
    assert matches_explicit_language(book, prefs) is True


# --------------------------------------------------------------------------- #
# `_filter_pool` — source-agnostic: rejects wrong-language candidates
# regardless of which pool (primary discover vs. broad fallback) they came
# from, since both route through the identical function.
# --------------------------------------------------------------------------- #
def test_filter_pool_removes_wrong_language_candidates_from_any_pool():
    """Simulates exactly what `broad_candidates()` produces: a
    genre-unrestricted, language-unrestricted, globally-popular pull that
    happens to include Romance titles in several languages."""
    prefs = PreferenceObject(
        genres=["romance"], language=["telugu"], explicit_fields=["genres", "language"]
    )
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    pool = [
        _movie("LAST_SUNRISE", language="en", genres=["Romance", "Drama"], rating=6.625, popularity=198.0),
        _movie("SHAPE_OF_HEART", language="ja", genres=["Romance"], rating=5.2, popularity=241.0),
        _movie("SITA_RAMAM", language="te", genres=["History", "Romance", "Drama"], rating=7.829, popularity=4.1),
    ]
    survivors = _filter_pool(pool, prefs, excluded=set())
    ids = {c.source_id for c in survivors}
    assert ids == {"SITA_RAMAM"}
    assert "LAST_SUNRISE" not in ids and "SHAPE_OF_HEART" not in ids


# --------------------------------------------------------------------------- #
# candidates.py edge case: an explicit-but-unresolved language must never
# silently widen into an unrestricted TMDb query.
# --------------------------------------------------------------------------- #
def test_build_candidates_makes_no_screen_calls_for_unresolved_explicit_language(spy_tmdb):
    prefs = PreferenceObject(
        media_type=["movie"], genres=["romance"], language=["Klingon"],
        explicit_fields=["media_type", "genres", "language"],
    )
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    candidates, _ = build_candidates(prefs, taste)
    assert candidates == []
    assert spy_tmdb.discover_calls == []  # zero TMDb calls made, not an unrestricted one


def test_build_candidates_still_queries_normally_when_language_resolves(spy_tmdb):
    prefs = PreferenceObject(
        media_type=["movie"], genres=["romance"], language=["Telugu"],
        explicit_fields=["media_type", "genres", "language"],
    )
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    build_candidates(prefs, taste)
    assert spy_tmdb.discover_calls == [("tmdb", "movie", ("romance",), "te", None)]
