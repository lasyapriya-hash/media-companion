"""Phase 1 integration smoke tests — live calls to TMDb, Open Library, and
(Phase 8 fix) Gemini.

Run with:  pytest -m integration
TMDb/Gemini tests skip automatically when their API key is not set in the
environment (.env). The Open Library tests need no credentials.
"""
import time

import pytest
from dotenv import dotenv_values

from app.clients import openlibrary_client
from app.clients.tmdb import TMDbClient
from app.config import get_settings

pytestmark = pytest.mark.integration

_TMDB_KEY = get_settings().tmdb_api_key
_needs_tmdb = pytest.mark.skipif(not _TMDB_KEY, reason="TMDB_API_KEY not set")

# conftest.py force-blanks GEMINI_API_KEY (env var, not just the settings
# cache) so the rest of the suite stays LLM-free by default — read the real
# configured key straight from .env instead of through get_settings().
_GEMINI_KEY = dotenv_values(".env").get("GEMINI_API_KEY") or ""
_needs_gemini = pytest.mark.skipif(not _GEMINI_KEY, reason="GEMINI_API_KEY not set")


@_needs_tmdb
def test_tmdb_search_returns_normalized_movies_and_series():
    client = TMDbClient(_TMDB_KEY)

    movies = client.search("Inception", media_type="movie", limit=5)
    assert movies, "expected at least one movie result"
    top = movies[0]
    assert top.type == "movie"
    assert top.source == "tmdb" and top.source_id
    assert top.title

    series = client.search("Breaking Bad", media_type="series", limit=5)
    assert series, "expected at least one series result"
    assert series[0].type == "series"


@_needs_tmdb
def test_tmdb_details_enrich_movie_with_runtime_and_bucket():
    client = TMDbClient(_TMDB_KEY)
    details = client.get_details("27205", "movie")  # Inception
    assert details.type == "movie"
    assert details.runtime_minutes and details.runtime_minutes > 0
    assert details.length_bucket is not None


@_needs_tmdb
def test_tmdb_watch_providers_known_title_region_in():
    client = TMDbClient(_TMDB_KEY)
    av = client.get_watch_providers("1396", "series", region="IN")  # Breaking Bad
    assert av.region == "IN"
    assert av.status in {"available", "unknown"}
    if av.status == "available":
        assert av.flatrate or av.rent or av.buy


@_needs_tmdb
def test_tmdb_watch_providers_unknown_state_is_clean():
    """A title with no India provider data must yield 'unknown', not an error."""
    client = TMDbClient(_TMDB_KEY)
    # Search a deliberately obscure term and probe the first movie hit.
    hits = client.search("Manakamana", media_type="movie", limit=1)
    if not hits:
        pytest.skip("no candidate title available for the unknown-state probe")
    av = client.get_watch_providers(hits[0].source_id, "movie", region="IN")
    assert av.status in {"available", "unknown"}
    if av.status == "unknown":
        assert av.flatrate == [] and av.rent == [] and av.buy == []


def test_openlibrary_search_returns_normalized_books():
    client = openlibrary_client()
    books = client.search("The Hobbit", limit=5)
    assert books, "expected at least one book result"
    top = books[0]
    assert top.type == "book"
    assert top.source == "open_library" and top.source_id
    assert top.title


def test_openlibrary_details_returns_description_or_subjects():
    client = openlibrary_client()
    books = client.search("The Lord of the Rings Tolkien", limit=5)
    assert books
    details = client.get_details(books[0].source_id)
    assert details.type == "book"
    assert details.description is not None or details.genres


# --------------------------------------------------------------------------- #
# Phase 8 fix regression: `gemini-2.5-flash` was retired for this project's
# API key (404 "no longer available to new users") and the 8s timeout was
# below Gemini's own enforced 10s minimum deadline — both together meant
# extraction silently fell back to the deterministic parser on *every* call.
# This proves a real call against `DEFAULT_MODEL` actually succeeds now,
# rather than only checking that the (masking) fallback still works.
# --------------------------------------------------------------------------- #
@_needs_gemini
def test_gemini_extraction_actually_succeeds_not_silent_fallback():
    from app.services.llm.gemini import DEFAULT_MODEL, GeminiExtractor

    extractor = GeminiExtractor(api_key=_GEMINI_KEY, model=DEFAULT_MODEL)
    prefs = None
    last_exc = None
    for _ in range(3):  # free-tier model can transiently 503; not what we test
        try:
            prefs = extractor.extract("Telugu love story")
            if prefs is not None:
                break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(3)
    assert prefs is not None, (
        f"Gemini extraction returned None (silently fell back) using "
        f"DEFAULT_MODEL={DEFAULT_MODEL!r}; last error: {last_exc}"
    )
    assert "romance" in [g.lower() for g in prefs.genres]
    assert "telugu" in [l.lower() for l in prefs.language]


# --------------------------------------------------------------------------- #
# Phase 9 hybrid architecture: `GeminiRecommender` is the primary path — a
# live call proves it actually returns semantic title suggestions (not just
# the objective PreferenceObject GeminiExtractor already covers above).
# --------------------------------------------------------------------------- #
@_needs_gemini
def test_gemini_recommender_suggests_real_titles_for_telugu_love_story():
    from app.services.llm.gemini import DEFAULT_MODEL, GeminiRecommender

    recommender = GeminiRecommender(api_key=_GEMINI_KEY, model=DEFAULT_MODEL)
    result = None
    last_exc = None
    for _ in range(3):  # free-tier model can transiently 503; not what we test
        try:
            result = recommender.recommend("Telugu love story")
            if result is not None:
                break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(3)
    assert result is not None, (
        f"Gemini recommend returned None (silently fell back) using "
        f"DEFAULT_MODEL={DEFAULT_MODEL!r}; last error: {last_exc}"
    )
    assert result.suggestions, "expected at least one semantic suggestion"
    for s in result.suggestions:
        assert s.media_type in ("movie", "series", "book")
        assert s.title.strip()
        assert s.reason.strip()
        # Gemini must never claim a rating/runtime/availability fact itself —
        # those come only from resolving against TMDb/Open Library.
        assert not any(w in s.reason.lower() for w in ("/10", "imdb", "rotten tomatoes"))
