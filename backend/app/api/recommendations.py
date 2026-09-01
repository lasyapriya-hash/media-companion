"""Conversational recommendation endpoints (spec §5.3, §8, §9).

`POST /recommendations`            -> ranked list, or one clarifying question
`POST /recommendations/{id}/answer` -> ranked list (the question is asked at most once)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.recommendation import (
    ClarificationAnswer,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services import recommendations as svc

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_SOURCES_DOWN = "Recommendation sources are unavailable right now. Please try again shortly."


@router.post("", response_model=RecommendationResponse)
def create_recommendations(
    req: RecommendationRequest, db: Session = Depends(get_db)
) -> RecommendationResponse:
    try:
        return svc.start_session(
            db, request_text=req.request, preferences=req.preferences
        )
    except svc.RecommendationError as exc:
        raise HTTPException(status_code=503, detail=_SOURCES_DOWN) from exc


@router.post("/{session_id}/answer", response_model=RecommendationResponse)
def answer_recommendations(
    session_id: uuid.UUID,
    body: ClarificationAnswer,
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    try:
        return svc.answer_session(db, session_id, body.answer)
    except svc.SessionNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Recommendation session not found"
        ) from exc
    except svc.ClarificationClosed as exc:
        # The one clarifying question has already been asked/answered (spec §8.2).
        raise HTTPException(
            status_code=409,
            detail="This recommendation session already has its answer.",
        ) from exc
    except svc.RecommendationError as exc:
        raise HTTPException(status_code=503, detail=_SOURCES_DOWN) from exc
