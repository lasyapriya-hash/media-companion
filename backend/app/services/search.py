"""Unified discovery across TMDb (movies/series) and Open Library (books).

Spec §5.2: search movies/series via TMDb, books via Open Library. A single
failing provider must not sink the whole search (spec NFR2); deeper failure
handling is Phase 6.
"""
from __future__ import annotations

import logging

from app.clients import openlibrary_client, tmdb_client
from app.schemas.media import NormalizedMedia

logger = logging.getLogger("uvicorn.error")

VALID_TYPES = {"movie", "series", "book"}


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
        try:
            results.extend(openlibrary_client().search(query, limit=limit))
        except Exception as exc:  # noqa: BLE001 - keep movies if OL fails
            logger.warning("Open Library search failed for %r: %s", query, exc)

    return results[:limit] if media_type is None else results
