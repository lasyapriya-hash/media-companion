"""Unified discovery across TMDb (movies/series) and books.

Spec §5.2 / §15 D1: books via Open Library (primary); Google Books is the
fallback when Open Library returns nothing or errors. A single failing provider
must never sink the whole search (spec NFR2).
"""
from __future__ import annotations

import logging

from app.clients import google_books_client, openlibrary_client, tmdb_client
from app.schemas.media import NormalizedMedia

logger = logging.getLogger("uvicorn.error")

VALID_TYPES = {"movie", "series", "book"}


def _books(query: str, limit: int) -> list[NormalizedMedia]:
    """Open Library first; fall back to Google Books on empty/error (spec §15 D1)."""
    try:
        results = openlibrary_client().search(query, limit=limit)
        if results:
            return results
        logger.info("Open Library search empty for %r; trying Google Books", query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Open Library search failed for %r: %s", query, exc)

    try:
        return google_books_client().search(query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Books search failed for %r: %s", query, exc)
        return []


def search_media(
    query: str, media_type: str | None = None, limit: int = 20
) -> list[NormalizedMedia]:
    query = (query or "").strip()
    if not query:
        return []

    want_screen = media_type in (None, "movie", "series")
    want_books = media_type in (None, "book")
    results: list[NormalizedMedia] = []

    if want_screen:
        try:
            results.extend(
                tmdb_client().search(query, media_type=media_type, limit=limit)
            )
        except Exception as exc:  # noqa: BLE001 - keep books if TMDb fails
            logger.warning("TMDb search failed for %r: %s", query, exc)

    if want_books:
        results.extend(_books(query, limit))

    return results[:limit] if media_type is None else results
