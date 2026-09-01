"""Read-only view of the derived taste profile (spec §6.3).

Not user-facing chrome — it exists so the recommendation engine (Phase 4) and
manual verification can inspect what the profile currently holds. The profile is
maintained by ``app.services.taste_profile`` on every rating/status change.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.taste import TasteProfileOut
from app.services import taste_profile as svc

router = APIRouter(prefix="/taste-profile", tags=["taste-profile"])


@router.get("", response_model=TasteProfileOut)
def read_taste_profile(db: Session = Depends(get_db)) -> TasteProfileOut:
    return svc.get_or_compute(db)
