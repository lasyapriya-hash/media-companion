"""External data-source clients (spec §7, §10).

Candidate generation and metadata come from these APIs; Claude is never on
this path.
"""
from functools import lru_cache

from app.clients.openlibrary import OpenLibraryClient
from app.clients.tmdb import TMDbClient
from app.config import get_settings


@lru_cache
def tmdb_client() -> TMDbClient:
    return TMDbClient(get_settings().tmdb_api_key)


@lru_cache
def openlibrary_client() -> OpenLibraryClient:
    return OpenLibraryClient()


__all__ = ["TMDbClient", "OpenLibraryClient", "tmdb_client", "openlibrary_client"]
