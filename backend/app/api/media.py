"""`GET /media/details` — read-only metadata enrichment for a not-yet-collected
result (spec §5.2, §6.1).

TMDb's list endpoints (`/search`, `/discover`) omit runtime and season/episode
counts; they only come from the per-title details call. The Collection detail
page gets them because `library._enrich` runs on add. This endpoint gives the
read-only Discover / Recommend preview the same call — no database, no scoring,
no side effects — so the preview shows the same facts. Best-effort: the caller
falls back to the list-level fields on any failure.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.clients import openlibrary_client, tmdb_client
from app.schemas.media import NormalizedMedia

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/details", response_model=NormalizedMedia)
def media_details(
    source: str = Query(..., description="tmdb | open_library"),
    source_id: str = Query(..., min_length=1),
    type: str = Query(..., description="movie | series | book"),
) -> NormalizedMedia:
    try:
        if source == "tmdb" and type in ("movie", "series"):
            return tmdb_client().get_details(source_id, type)
        if source == "open_library" and type == "book":
            return openlibrary_client().get_details(source_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - upstream hiccup, not a server bug
        logger.warning("media details lookup failed for %s:%s: %s", source, source_id, exc)
        raise HTTPException(status_code=502, detail="Details are unavailable right now.") from exc

    raise HTTPException(status_code=400, detail="Unsupported source/type for details.")
