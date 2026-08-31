"""`GET /search` — unified movie/series/book discovery (spec §5.2)."""
from fastapi import APIRouter, Query

from app.schemas.media import NormalizedMedia
from app.services.search import VALID_TYPES, search_media

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[NormalizedMedia])
def search(
    q: str = Query(..., min_length=1, description="free-text query"),
    type: str | None = Query(None, description="movie | series | book; omit for all"),
    limit: int = Query(20, ge=1, le=50),
) -> list[NormalizedMedia]:
    media_type = type if type in VALID_TYPES else None
    return search_media(q, media_type, limit)
