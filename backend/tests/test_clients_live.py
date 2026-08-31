"""Phase 1 integration smoke tests — live calls to TMDb and Open Library.

Run with:  pytest -m integration
TMDb tests skip automatically when TMDB_API_KEY is not set in the environment
(.env). The Open Library tests need no credentials.
"""
import pytest

from app.clients import openlibrary_client
from app.clients.tmdb import TMDbClient
from app.config import get_settings

pytestmark = pytest.mark.integration

_TMDB_KEY = get_settings().tmdb_api_key
_needs_tmdb = pytest.mark.skipif(not _TMDB_KEY, reason="TMDB_API_KEY not set")


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
