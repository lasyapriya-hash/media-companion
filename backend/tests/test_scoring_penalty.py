"""Phase 6: scoring penalty uses drop_patterns *and* per-genre completion
(spec §9.1)."""
from __future__ import annotations

from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject
from app.services.recommendations.scoring import score_candidate


def _movie(sid, genres, *, rating=7.0):
    return NormalizedMedia(
        source="tmdb", source_id=sid, type="movie", title=f"M {sid}",
        genres=genres, language="en", year=2018, external_rating=rating,
        raw_metadata={"popularity": 40.0},
    )


def _taste(**kw):
    return TasteProfile(id=1, **kw)


PREFS = PreferenceObject()  # sparse -> preference_match is 0, penalty is visible


def test_drop_pattern_genre_is_penalised_below_a_neutral_genre():
    taste = _taste(
        drop_patterns=["horror"],
        completion_rate_by_genre={"horror": 0.0, "drama": 1.0},
    )
    horror = score_candidate(_movie("H", ["Horror"]), PREFS, taste).score
    drama = score_candidate(_movie("D", ["Drama"]), PREFS, taste).score
    assert horror < drama


def test_lower_completion_yields_a_larger_penalty():
    near_zero = _taste(drop_patterns=["horror"], completion_rate_by_genre={"horror": 0.0})
    near_half = _taste(drop_patterns=["horror"], completion_rate_by_genre={"horror": 0.45})
    worse = score_candidate(_movie("H", ["Horror"]), PREFS, near_zero).score
    milder = score_candidate(_movie("H", ["Horror"]), PREFS, near_half).score
    assert worse < milder


def test_low_completion_without_a_drop_pattern_still_nudges_down():
    taste = _taste(completion_rate_by_genre={"western": 0.2})  # low but not a pattern
    penalised = score_candidate(_movie("W", ["Western"]), PREFS, taste).score
    neutral = score_candidate(_movie("W2", ["Western"]), PREFS, _taste()).score
    assert penalised < neutral


def test_no_penalty_without_taste_signals():
    a = score_candidate(_movie("A", ["Comedy"]), PREFS, _taste()).score
    b = score_candidate(_movie("B", ["Comedy"]), PREFS, _taste()).score
    assert a == b  # deterministic, no penalty applied
