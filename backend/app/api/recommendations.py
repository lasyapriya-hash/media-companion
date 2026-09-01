"""`POST /recommendations` — single-turn natural-language recommendations
(spec §5.3, §9; Phase 4). The clarifying turn is Phase 5.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.services import recommendations as svc

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("", response_model=RecommendationResponse)
def create_recommendations(
    req: RecommendationRequest, db: Session = Depends(get_db)
) -> RecommendationResponse:
    try:
        return svc.recommend(
            db, request_text=req.request, preferences=req.preferences
        )
    except svc.RecommendationError as exc:
        # spec §8.2 / NFR2: graceful, user-visible fallback — not a crash.
        raise HTTPException(
            status_code=503,
            detail="Recommendation sources are unavailable right now. Please try again shortly.",
        ) from exc
