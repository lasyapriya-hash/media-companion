"""Google Books client — the **fallback** book source (spec §15 D1).

Used only when Open Library returns nothing or errors. No key required for basic
search; `GOOGLE_BOOKS_API_KEY` (if set) just raises the rate limit.
"""
from __future__ import annotations

import httpx

from app.clients.base import DEFAULT_TIMEOUT, request_json
from app.schemas.media import NormalizedMedia
from app.services.normalization import length_bucket

GB_BASE = "https://www.googleapis.com/books/v1"


def _year(published: object) -> int | None:
    if isinstance(published, str) and published[:4].isdigit():
        return int(published[:4])
    return None


def _rating_to_ten(value: object) -> float | None:
    """Google Books averageRating is 0–5; normalize to 0–10."""
    if isinstance(value, (int, float)):
        return round(float(value) * 2, 2)
    return None


def _https(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    return url.replace("http://", "https://")


# --------------------------------------------------------------------------- #
# Pure normalization (no I/O)
# --------------------------------------------------------------------------- #
def normalize_gb_volume(volume: dict) -> NormalizedMedia:
    info = volume.get("volumeInfo") or {}
    images = info.get("imageLinks") or {}
    authors = info.get("authors") or []
    pages = info.get("pageCount")

    media = NormalizedMedia(
        source="google_books",
        source_id=str(volume.get("id") or ""),
        type="book",
        title=info.get("title") or "",
        description=info.get("description") or None,
        genres=(info.get("categories") or [])[:8],
        language=info.get("language"),
        year=_year(info.get("publishedDate")),
        external_rating=_rating_to_ten(info.get("averageRating")),
        artwork_url=_https(images.get("thumbnail") or images.get("smallThumbnail")),
        author=", ".join(authors[:3]) or None,
        page_count=pages if isinstance(pages, int) and pages > 0 else None,
        raw_metadata=volume,
    )
    media.length_bucket = length_bucket("book", page_count=media.page_count)
    return media


def book_access_link(volume: dict) -> str | None:
    """A purchase/access link if Google Books provides one, else None (spec §5.4)."""
    sale = volume.get("saleInfo") or {}
    if sale.get("saleability") == "FOR_SALE":
        link = sale.get("buyLink")
        if isinstance(link, str) and link:
            return link
    access = volume.get("accessInfo") or {}
    if access.get("viewability") in ("PARTIAL", "ALL_PAGES"):
        link = access.get("webReaderLink")
        if isinstance(link, str) and link:
            return link
    return None


# --------------------------------------------------------------------------- #
# Client (I/O)
# --------------------------------------------------------------------------- #
class GoogleBooksClient:
    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._http = httpx.Client(base_url=GB_BASE, timeout=DEFAULT_TIMEOUT)

    def _get(self, params: dict) -> dict:
        if self._api_key:
            params = {**params, "key": self._api_key}
        return request_json(self._http, "/volumes", {"country": "IN", **params})

    def _volumes(self, q: str, limit: int) -> list[NormalizedMedia]:
        data = self._get({"q": q, "maxResults": min(max(limit, 1), 40), "printType": "books"})
        return [normalize_gb_volume(v) for v in (data.get("items") or [])[:limit]]

    def search(self, query: str, limit: int = 10) -> list[NormalizedMedia]:
        query = (query or "").strip()
        return self._volumes(query, limit) if query else []

    def discover(
        self,
        *,
        subjects: list[str] | None = None,
        language: str | None = None,  # accepted for parity; GB `q` has no lang filter
        limit: int = 20,
    ) -> list[NormalizedMedia]:
        subs = [s.strip() for s in (subjects or []) if s.strip()]
        q = " ".join(f'subject:"{s}"' for s in subs) if subs else "subject:fiction"
        return self._volumes(q, limit)
