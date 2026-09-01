"""External data-source clients (spec §7, §10).

Candidate generation and metadata come from these APIs; the LLM is never on
this path.
"""
from functools import lru_cache

from app.clients.google_books import GoogleBooksClient
from app.clients.openlibrary import OpenLibraryClient
from app.clients.tmdb import TMDbClient
from app.config import get_settings


@lru_cache
def tmdb_client() -> TMDbClient:
    return TMDbClient(get_settings().tmdb_api_key)


@lru_cache
def openlibrary_client() -> OpenLibraryClient:
    return OpenLibraryClient()


@lru_cache
def google_books_client() -> GoogleBooksClient:
    return GoogleBooksClient(get_settings().google_books_api_key)


__all__ = [
    "TMDbClient",
    "OpenLibraryClient",
    "GoogleBooksClient",
    "tmdb_client",
    "openlibrary_client",
    "google_books_client",
]
