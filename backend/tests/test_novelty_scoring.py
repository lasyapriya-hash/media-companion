"""Regression: `_novelty()` must never punish a candidate for a strong
external rating once there is a real preference/taste signal to diversify
around (spec §9.1/§9.3).

Diagnosed against live TMDb data for "Telugu love story": once a whole
candidate cohort saturates `preference_match == 1.0` (identical genre +
language match), the old `_novelty()` treated a *higher* rating as *less*
novel and actively demoted well-reviewed titles below poorly-rated or unrated
ones (a 7.8-rated title ranked 15th of 18, behind a 3.0-rated one; a
10.0-rated title ranked dead last). This file pins the fix at the unit level;
`test_recommendations.py` covers the same scenario end-to-end through the API.

Companion to `test_zero_signal_scoring_uses_quality_prior_not_novelty` in
test_recommendations.py, which covers the has_signal=False ("surprise me")
branch — untouched by this fix.
"""
from __future__ import annotations

from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject
from app.services.recommendations.scoring import _novelty, score_candidate


def _movie(sid, *, rating, popularity=40.0, genres=("Romance",), language="te"):
    return NormalizedMedia(
        source="tmdb", source_id=sid, type="movie", title=f"M {sid}",
        genres=list(genres), language=language, year=2020, external_rating=rating,
        raw_metadata={"popularity": popularity},
    )


def test_novelty_is_monotonic_in_rating_alone():
    """Same popularity, only rating differs -> `_novelty` must not decrease."""
    low = _novelty(_movie("L", rating=3.0))
    high = _novelty(_movie("H", rating=9.0))
    assert high > low


def test_novelty_missing_rating_uses_neutral_default():
    unrated = _novelty(_movie("U", rating=None, popularity=40.0))
    mid_rated = _novelty(_movie("M", rating=6.0, popularity=40.0))
    assert unrated == mid_rated  # both fall back to the same neutral quality


def test_higher_rating_outranks_lower_rating_at_equal_preference_match():
    """Two candidates saturate preference_match at 1.0 (same genre/language) with
    zero taste signal — the only spread left is the 0.15 novelty slot. The
    better-rated one must win, not lose."""
    prefs = PreferenceObject(
        genres=["romance"], language=["telugu"], explicit_fields=["genres", "language"]
    )
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    good = score_candidate(_movie("GOOD", rating=7.8, popularity=4.1), prefs, taste)
    obscure_low = score_candidate(_movie("LOW", rating=3.0, popularity=3.0), prefs, taste)
    assert good.explanation.any_preference_signal()
    assert good.score > obscure_low.score


def test_sita_ramam_like_candidate_ranks_at_top_of_saturated_cohort():
    """End-to-end reproduction of the diagnosed cohort (real TMDb rating/
    popularity values for a Telugu-romance genre+language discover query).
    Every candidate matches genre+language+mood identically, so only novelty
    differentiates them. The realistic high-quality pick must land at the top,
    not mid/bottom of the pack, and the lowest-rated title must not win."""
    prefs = PreferenceObject(
        genres=["romance"], mood=["romantic"], language=["telugu"],
        explicit_fields=["genres", "mood", "language"],
    )
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    cohort = [
        ("Sita Ramam", 7.829, 4.137),
        ("Madhura Wines", 3.0, 3.0066),
        ("Deewana", 4.0, 3.1467),
        ("Ravoyi Chandamama", 6.0, 2.9957),
        ("RDX Love", 5.8, 3.3175),
        ("Ugly Story", 4.0, 3.172),
    ]
    scored = [
        (title, score_candidate(_movie(title, rating=r, popularity=p), prefs, taste).score)
        for title, r, p in cohort
    ]
    scored.sort(key=lambda t: -t[1])
    ranked_titles = [t for t, _ in scored]
    assert ranked_titles[0] == "Sita Ramam"
    assert ranked_titles[-1] != "Sita Ramam"
    assert ranked_titles[-1] == "Madhura Wines"  # was previously the #1 result
