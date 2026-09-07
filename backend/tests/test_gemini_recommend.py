"""End-to-end tests for the Gemini-primary recommendation path (Phase 9
hybrid architecture).

The core guarantee under test: Gemini decides semantic fit (genre/mood/tone/
vibe) using its own knowledge; TMDb/Open Library only resolve a suggested
title to real metadata and verify OBJECTIVE facts (existence, language, media
type, rating, release period, collection membership). A resolved candidate
must never be rejected merely because its TMDb genre tags don't contain the
exact semantic label the request used — that is exactly the bug this
architecture replaces. Component-level coverage of the pipeline itself is in
test_gemini_pipeline.py.
"""
from __future__ import annotations

from app.schemas.preference import PreferenceObject, RatingRange, ReleaseWindow
from app.services.llm.base import GeminiRecommendation, GeminiSuggestion

from tests.test_recommendations import FakeClients, SpyRecommender, _media, wire  # noqa: F401


def _gemini(prefs, *suggestions):
    return SpyRecommender(GeminiRecommendation(preferences=prefs, suggestions=list(suggestions)))


# --------------------------------------------------------------------------- #
# Core claim: Gemini's semantic judgment survives even when TMDb's own tags
# don't line up with the request's wording.
# --------------------------------------------------------------------------- #
def test_sita_ramam_survives_for_telugu_love_story(client, wire):
    """The exact diagnosed case: Gemini recommends Sita Ramam for "Telugu love
    story"; TMDb resolves it with History/Romance/Drama tags. It must survive
    — and with Gemini's own reason, not a templated genre-overlap sentence."""
    sita = _media("894803", title="Sita Ramam", year=2022,
                   genres=["History", "Romance", "Drama"], language="te", rating=7.8)
    wire["recommender"] = _gemini(
        PreferenceObject(media_type=["movie"], language=["Telugu"],
                          explicit_fields=["media_type", "language"]),
        GeminiSuggestion(title="Sita Ramam", media_type="movie", year=2022,
                          reason="A tender, romantic period drama widely regarded as "
                                 "one of Telugu cinema's great love stories."),
    )
    wire["clients"] = FakeClients(search_results={"Sita Ramam": [sita]})
    body = client.post("/recommendations", json={"request": "Telugu love story"}).json()
    assert body["extraction"] == "llm"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"894803"}
    assert "great love stories" in body["results"][0]["reason"]


def test_survives_without_matching_tmdb_genre_tag(client, wire):
    """A title Gemini judges a fitting "cozy romantic drama" but whose TMDb
    genre tags are just ["Drama"] (no Romance, nothing resembling "cozy") must
    still survive — genre is never checked on this path."""
    plain = _media("1", title="A Quiet Evening", genres=["Drama"], rating=7.9)
    wire["recommender"] = _gemini(
        PreferenceObject(rating=RatingRange(gt=7.5), explicit_fields=["rating"]),
        GeminiSuggestion(title="A Quiet Evening", media_type="movie", year=2015,
                          reason="A gentle, cozy romance with real warmth."),
    )
    wire["clients"] = FakeClients(search_results={"A Quiet Evening": [plain]})
    body = client.post(
        "/recommendations",
        json={"request": "a cozy romantic drama movie which has rating above 7.5"},
    ).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"1"}  # survived despite genres == ["Drama"] only


# --------------------------------------------------------------------------- #
# Objective constraints still apply, post-resolution
# --------------------------------------------------------------------------- #
def test_rating_below_threshold_gemini_suggestion_discarded(client, wire):
    low = _media("LOW", title="Below The Bar", rating=6.9)
    high = _media("HIGH", title="Clear Winner", rating=9.1)
    wire["recommender"] = _gemini(
        PreferenceObject(rating=RatingRange(gt=7.5), explicit_fields=["rating"]),
        GeminiSuggestion(title="Below The Bar", media_type="movie", year=None, reason="x"),
        GeminiSuggestion(title="Clear Winner", media_type="movie", year=None, reason="y"),
    )
    wire["clients"] = FakeClients(
        search_results={"Below The Bar": [low], "Clear Winner": [high]}
    )
    body = client.post(
        "/recommendations", json={"request": "a movie rated above 7.5"}
    ).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"HIGH"}


def test_wrong_media_type_gemini_suggestion_discarded(client, wire):
    """User explicitly asked for a movie; Gemini's own suggestion resolves
    (correctly) as a series — the objective media-type check discards it."""
    series = _media("S1", title="Some Show", type="series")
    movie = _media("M1", title="Some Film", type="movie")
    wire["recommender"] = _gemini(
        PreferenceObject(media_type=["movie"], explicit_fields=["media_type"]),
        GeminiSuggestion(title="Some Show", media_type="series", year=None, reason="x"),
        GeminiSuggestion(title="Some Film", media_type="movie", year=None, reason="y"),
    )
    wire["clients"] = FakeClients(
        search_results={"Some Show": [series], "Some Film": [movie]}
    )
    body = client.post("/recommendations", json={"request": "a movie"}).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"M1"}


def test_wrong_release_period_gemini_suggestion_discarded(client, wire):
    old = _media("OLD", title="Retro Pick", year=1995)
    new = _media("NEW", title="Modern Pick", year=2022)
    wire["recommender"] = _gemini(
        PreferenceObject(
            release_period=ReleaseWindow(from_year=1990, to_year=1999),
            explicit_fields=["release_period"],
        ),
        GeminiSuggestion(title="Retro Pick", media_type="movie", year=1995, reason="x"),
        GeminiSuggestion(title="Modern Pick", media_type="movie", year=2022, reason="y"),
    )
    wire["clients"] = FakeClients(
        search_results={"Retro Pick": [old], "Modern Pick": [new]}
    )
    body = client.post("/recommendations", json={"request": "a movie from the 90s"}).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"OLD"}


def test_collection_item_excluded_on_gemini_path(client, wire):
    seen = _media("SEEN", title="Already Watched")
    entry = client.post("/library", json={"item": seen.model_dump()}).json()
    client.patch(f"/library/{entry['id']}", json={"status": "completed"})

    fresh = _media("FRESH", title="Something New")
    wire["recommender"] = _gemini(
        PreferenceObject(),
        GeminiSuggestion(title="Already Watched", media_type="movie", year=None, reason="x"),
        GeminiSuggestion(title="Something New", media_type="movie", year=None, reason="y"),
    )
    wire["clients"] = FakeClients(
        search_results={"Already Watched": [seen], "Something New": [fresh]}
    )
    body = client.post("/recommendations", json={"request": "anything good"}).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "SEEN" not in ids
    assert "FRESH" in ids


def test_hallucinated_title_rejected(client, wire):
    """A suggestion that doesn't resolve to anything real is silently dropped
    — never shown, never treated as an error."""
    real = _media("REAL", title="Genuine Film")
    wire["recommender"] = _gemini(
        PreferenceObject(),
        GeminiSuggestion(title="Totally Fabricated Nonexistent Movie",
                          media_type="movie", year=None, reason="x"),
        GeminiSuggestion(title="Genuine Film", media_type="movie", year=None, reason="y"),
    )
    wire["clients"] = FakeClients(search_results={"Genuine Film": [real]})
    body = client.post("/recommendations", json={"request": "anything good"}).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"REAL"}


# --------------------------------------------------------------------------- #
# Fallback: Gemini unavailable/failing must never fail the user-facing request
# --------------------------------------------------------------------------- #
def test_gemini_unavailable_falls_back_to_deterministic(client, wire):
    wire["recommender"] = None  # disabled/unavailable — the fixture default too
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime", "Thriller"], title="Cold Ledger")]
    )
    body = client.post(
        "/recommendations", json={"request": "a dark crime thriller movie"}
    ).json()
    assert body["extraction"] == "fallback"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "A" in ids


def test_gemini_raising_falls_back_to_deterministic(client, wire):
    class Boom:
        def recommend(self, request_text, *, taste_context=""):
            raise RuntimeError("network blip")

    wire["recommender"] = Boom()
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime", "Thriller"], title="Cold Ledger")]
    )
    body = client.post(
        "/recommendations", json={"request": "a dark crime thriller movie"}
    ).json()
    assert body["extraction"] == "fallback"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "A" in ids


def test_gemini_malformed_output_falls_back_to_deterministic(client, wire):
    """`GeminiRecommender.recommend()` itself already swallows malformed JSON
    and returns `None` (unit-tested in test_llm_extraction.py-style coverage
    of the real class) — this exercises the orchestrator's handling of that
    `None` signal end-to-end."""
    wire["recommender"] = SpyRecommender(None)
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime", "Thriller"], title="Cold Ledger")]
    )
    body = client.post(
        "/recommendations", json={"request": "a dark crime thriller movie"}
    ).json()
    assert body["extraction"] == "fallback"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "A" in ids


def test_gemini_all_suggestions_fail_resolution_falls_back_to_deterministic(client, wire):
    """Gemini succeeds and produces a `PreferenceObject`, but every suggestion
    is a dead end — the deterministic pipeline still runs, using that same
    (Gemini-derived) `PreferenceObject`. `extraction` stays "llm" because the
    preferences genuinely came from Gemini, even though the shown results
    came from the deterministic candidate pool."""
    wire["recommender"] = _gemini(
        PreferenceObject(genres=["Crime"], explicit_fields=["genres"]),
        GeminiSuggestion(title="Nonexistent Movie One", media_type="movie",
                          year=None, reason="x"),
        GeminiSuggestion(title="Nonexistent Movie Two", media_type="movie",
                          year=None, reason="y"),
    )
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime"], title="Cold Ledger")]
        # no search_results configured -> both suggestions fail resolution
    )
    body = client.post("/recommendations", json={"request": "gritty crime stuff"}).json()
    assert body["extraction"] == "llm"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"A"}
    assert any(c[0] == "tmdb" for c in wire["clients"].discover_calls)  # deterministic path ran


def test_gemini_empty_recommendations_falls_back_to_deterministic(client, wire):
    """Gemini explicitly returning no suggestions ("nothing genuinely fits")
    is a valid, honest answer — not an error — and still falls back."""
    wire["recommender"] = _gemini(
        PreferenceObject(genres=["Crime"], explicit_fields=["genres"])
    )
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime"], title="Cold Ledger")]
    )
    body = client.post("/recommendations", json={"request": "gritty crime stuff"}).json()
    assert body["extraction"] == "llm"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"A"}
