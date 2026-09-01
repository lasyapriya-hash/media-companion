"""Open Library client: book search and work details (spec §7, §10 — primary
book source per spec §15 D1). The Google Books fallback is Phase 6.
"""
from __future__ import annotations

import httpx

from app.clients.base import DEFAULT_TIMEOUT, request_json
from app.schemas.media import NormalizedMedia
from app.services.normalization import length_bucket

OL_BASE = "https://openlibrary.org"
COVERS_BASE = "https://covers.openlibrary.org/b/id"
USER_AGENT = "PersonalMediaCompanion/0.1 (educational project)"

SEARCH_FIELDS = ",".join(
    [
        "key",
        "title",
        "author_name",
        "first_publish_year",
        "cover_i",
        "number_of_pages_median",
        "language",
        "subject",
        "ratings_average",
    ]
)


def _work_id(key: str) -> str:
    return key.rsplit("/", 1)[-1] if key else ""


def _ol_rating_to_ten(value: object) -> float | None:
    """Open Library ratings are 0–5; normalize to 0–10 (spec: external_rating 0–10)."""
    if isinstance(value, (int, float)):
        return round(float(value) * 2, 2)
    return None


# --------------------------------------------------------------------------- #
# Pure normalization (no I/O) — unit-tested directly.
# --------------------------------------------------------------------------- #
def normalize_ol_doc(doc: dict) -> NormalizedMedia:
    """Normalize one `/search.json` doc."""
    cover = doc.get("cover_i")
    languages = doc.get("language") or []
    pages = doc.get("number_of_pages_median")
    authors = doc.get("author_name") or []

    media = NormalizedMedia(
        source="open_library",
        source_id=_work_id(doc.get("key", "")),
        type="book",
        title=doc.get("title") or "",
        description=None,  # search docs carry no description; details supplies it
        genres=(doc.get("subject") or [])[:8],
        language=languages[0] if languages else None,
        year=doc.get("first_publish_year"),
        external_rating=_ol_rating_to_ten(doc.get("ratings_average")),
        artwork_url=f"{COVERS_BASE}/{cover}-L.jpg" if cover else None,
        author=", ".join(authors[:3]) or None,
        page_count=pages,
        raw_metadata=doc,
    )
    media.length_bucket = length_bucket("book", page_count=pages)
    return media


def normalize_ol_work(payload: dict) -> NormalizedMedia:
    """Normalize a `/works/{id}.json` details payload (description + subjects)."""
    description = payload.get("description")
    if isinstance(description, dict):
        description = description.get("value")

    return NormalizedMedia(
        source="open_library",
        source_id=_work_id(payload.get("key", "")),
        type="book",
        title=payload.get("title") or "",
        description=description or None,
        genres=(payload.get("subjects") or [])[:8],
        raw_metadata=payload,
    )


# --------------------------------------------------------------------------- #
# Client (I/O)
# --------------------------------------------------------------------------- #
class OpenLibraryClient:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=OL_BASE,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )

    def search(self, query: str, limit: int = 10) -> list[NormalizedMedia]:
        data = request_json(
            self._http,
            "/search.json",
            {"q": query, "limit": limit, "fields": SEARCH_FIELDS},
        )
        return [normalize_ol_doc(d) for d in data.get("docs", [])[:limit]]

    def get_details(self, work_id: str) -> NormalizedMedia:
        key = work_id if work_id.startswith("/works/") else f"/works/{work_id}"
        payload = request_json(self._http, f"{key}.json")
        return normalize_ol_work(payload)

    def discover(
        self,
        *,
        subjects: list[str] | None = None,
        language: str | None = None,
        limit: int = 20,
    ) -> list[NormalizedMedia]:
        """Subject-driven candidate query for book recommendations (spec §8.2).

        Builds an OR of `subject:"…"` clauses; with no subjects it falls back to
        a broad popular query so the pool is never empty.
        """
        clauses = [f'subject:"{s.strip()}"' for s in (subjects or []) if s.strip()]
        params: dict[str, object] = {
            "q": " OR ".join(clauses) if clauses else "*",
            "limit": limit,
            "fields": SEARCH_FIELDS,
        }
        if not clauses:
            params["sort"] = "readinglog"  # broad-popularity fallback pool
        if language:
            params["language"] = language
        data = request_json(self._http, "/search.json", params)
        return [normalize_ol_doc(d) for d in data.get("docs", [])[:limit]]
