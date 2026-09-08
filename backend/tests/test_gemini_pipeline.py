"""Component-level tests for `gemini_pipeline.py` (Phase 9 hybrid architecture).

Covers resolution (title/year confidence matching — the anti-hallucination
guard) and objective-constraint validation in isolation from the HTTP layer.
End-to-end API coverage is in test_gemini_recommend.py.
"""
from __future__ import annotations

import uuid

from app.models.taste import TasteProfile
from app.schemas.preference import PreferenceObject, ReleaseWindow
from app.services.llm.base import GeminiSuggestion
from app.services.recommendations import gemini_pipeline as gp

from tests.test_recommendations import FakeClients, _media, wire  # noqa: F401


# --------------------------------------------------------------------------- #
# Title/year confidence matching — pure functions, no I/O
# --------------------------------------------------------------------------- #
def test_best_match_exact_title():
    sita = _media("894803", title="Sita Ramam", year=2022)
    assert gp.best_match([sita], "Sita Ramam", 2022) is sita


def test_best_match_case_and_punctuation_insensitive():
    item = _media("1", title="A Aa")
    assert gp.best_match([item], "a aa", None) is item


def test_best_match_rejects_unrelated_title():
    """The anti-hallucination guard: a search hit that isn't really the same
    title must not be accepted just because *something* came back."""
    unrelated = _media("1", title="Completely Different Movie")
    assert gp.best_match([unrelated], "Sita Ramam", 2022) is None


def test_best_match_returns_none_for_empty_candidates():
    assert gp.best_match([], "Anything", None) is None


def test_best_match_prefers_year_when_titles_tie():
    old = _media("1", title="Anna", year=1967)
    new = _media("2", title="Anna", year=2021)
    assert gp.best_match([old, new], "Anna", 2021) is new


# --------------------------------------------------------------------------- #
# Resolution (I/O via the fake TMDb/OL/GB clients)
# --------------------------------------------------------------------------- #
def test_resolve_suggestion_movie_via_search(wire):
    sita = _media("894803", title="Sita Ramam", year=2022, genres=["Romance"], language="te")
    wire["clients"] = FakeClients(search_results={"Sita Ramam": [sita]})
    s = GeminiSuggestion(title="Sita Ramam", media_type="movie", year=2022, reason="x")
    resolved = gp.resolve_suggestion(s)
    assert resolved is sita
    assert wire["clients"].search_calls == [("tmdb_search", "Sita Ramam", "movie")]


def test_resolve_suggestion_discards_when_nothing_returned():
    s = GeminiSuggestion(title="Totally Made Up Movie Nobody Made", media_type="movie",
                          year=2022, reason="x")
    assert gp.resolve_suggestion(s) is None


def test_resolve_suggestion_book_falls_back_ol_to_google_books(wire):
    book = _media("gb1", type="book", title="Some Novel", source="google_books")
    # OL search returns nothing (no search_results configured for it); Google
    # Books' fake `.search()` returns whatever `books=` holds.
    wire["clients"] = FakeClients(books=[book])
    s = GeminiSuggestion(title="Some Novel", media_type="book", year=None, reason="x")
    resolved = gp.resolve_suggestion(s)
    assert resolved is book


# --------------------------------------------------------------------------- #
# Objective constraints — deliberately excludes genre (Phase 9: Gemini is
# semantically authoritative; TMDb genre tags never gate this path).
# --------------------------------------------------------------------------- #
def test_passes_objective_constraints_ignores_genre_mismatch():
    """A resolved item whose TMDb genres don't contain anything matching the
    request's semantic category must still pass — genre is not checked here."""
    item = _media("1", genres=["Drama"])  # no "Romance" tag at all
    prefs = PreferenceObject()  # no objective constraints stated
    assert gp.passes_objective_constraints(item, prefs, excluded=set()) is True


def test_passes_objective_constraints_rejects_wrong_language():
    item = _media("1", language="en")
    prefs = PreferenceObject(language=["Telugu"], explicit_fields=["language"])
    assert gp.passes_objective_constraints(item, prefs, excluded=set()) is False


def test_passes_objective_constraints_rejects_below_rating_threshold():
    item = _media("1", rating=6.0)
    prefs = PreferenceObject(rating={"gt": 7.5})
    assert gp.passes_objective_constraints(item, prefs, excluded=set()) is False


def test_passes_objective_constraints_rejects_wrong_media_type():
    item = _media("1", type="series")
    prefs = PreferenceObject(media_type=["movie"])
    assert gp.passes_objective_constraints(item, prefs, excluded=set()) is False


def test_passes_objective_constraints_rejects_wrong_release_period():
    item = _media("1", year=2022)
    prefs = PreferenceObject(release_period=ReleaseWindow(from_year=1990, to_year=1999))
    assert gp.passes_objective_constraints(item, prefs, excluded=set()) is False


def test_passes_objective_constraints_rejects_excluded_collection_item():
    item = _media("1")
    prefs = PreferenceObject()
    assert gp.passes_objective_constraints(item, prefs, excluded={("tmdb", "1")}) is False


# --------------------------------------------------------------------------- #
# resolve_and_validate: orchestration — order, dedup, discard, limit
# --------------------------------------------------------------------------- #
def test_resolve_and_validate_preserves_gemini_order_and_reason(wire):
    a = _media("A", title="Alpha", genres=["Drama"])
    b = _media("B", title="Beta", genres=["Drama"])
    wire["clients"] = FakeClients(search_results={"Beta": [b], "Alpha": [a]})
    suggestions = [
        GeminiSuggestion(title="Beta", media_type="movie", year=None, reason="Beta reason"),
        GeminiSuggestion(title="Alpha", media_type="movie", year=None, reason="Alpha reason"),
    ]
    out = gp.resolve_and_validate(suggestions, PreferenceObject(), set(), limit=8)
    assert [m.source_id for m, _, _ in out] == ["B", "A"]
    assert out[0][2] == "Beta reason"
    assert out[1][2] == "Alpha reason"


def test_resolve_and_validate_discards_unresolved_and_keeps_the_rest(wire):
    good = _media("A", title="Real Movie")
    wire["clients"] = FakeClients(search_results={"Real Movie": [good]})
    suggestions = [
        GeminiSuggestion(title="Hallucinated Nonexistent Film", media_type="movie",
                          year=None, reason="x"),
        GeminiSuggestion(title="Real Movie", media_type="movie", year=None, reason="y"),
    ]
    out = gp.resolve_and_validate(suggestions, PreferenceObject(), set(), limit=8)
    assert [m.source_id for m, _, _ in out] == ["A"]


def test_resolve_and_validate_dedupes_same_resolved_item(wire):
    only = _media("A", title="Same Movie")
    wire["clients"] = FakeClients(
        search_results={"Same Movie": [only], "Same Movie (alt spelling)": [only]}
    )
    suggestions = [
        GeminiSuggestion(title="Same Movie", media_type="movie", year=None, reason="x"),
        GeminiSuggestion(title="Same Movie (alt spelling)", media_type="movie",
                          year=None, reason="y"),
    ]
    out = gp.resolve_and_validate(suggestions, PreferenceObject(), set(), limit=8)
    assert len(out) == 1


def test_resolve_and_validate_respects_limit(wire):
    items = {f"Movie {i}": [_media(str(i), title=f"Movie {i}")] for i in range(5)}
    wire["clients"] = FakeClients(search_results=items)
    suggestions = [
        GeminiSuggestion(title=f"Movie {i}", media_type="movie", year=None, reason="x")
        for i in range(5)
    ]
    out = gp.resolve_and_validate(suggestions, PreferenceObject(), set(), limit=3)
    assert len(out) == 3


# --------------------------------------------------------------------------- #
# taste_context: background framing, never a hard requirement
# --------------------------------------------------------------------------- #
def test_taste_context_empty_when_no_taste_data():
    taste = TasteProfile(user_id=uuid.uuid4(), favourite_genres=[], favourite_languages=[], drop_patterns=[])
    assert gp.taste_context(taste) == ""


def test_taste_context_mentions_never_override():
    taste = TasteProfile(user_id=uuid.uuid4(), favourite_genres=["Action"], favourite_languages=["Kannada"])
    ctx = gp.taste_context(taste)
    assert "Action" in ctx and "Kannada" in ctx
    assert "never override" in ctx.lower() or "never" in ctx.lower()
