"""Read-only view of the derived taste profile (spec §6.3).

Not user-facing chrome — it exists so the recommendation engine (Phase 4) and
manual verification can inspect what the profile currently holds. The profile is
maintained by ``app.services.taste_profile`` on every rating/status change.

Requires authentication (Phase 8.3, spec §6.1/§6.3) — returns the calling
account's own profile only; see spec.md §13 for why this enforcement's
production deployment is held until Phase 8.4.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.taste import TasteProfileOut
from app.services import taste_profile as svc

router = APIRouter(prefix="/taste-profile", tags=["taste-profile"])


@router.get("", response_model=TasteProfileOut)
def read_taste_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TasteProfileOut:
    return svc.get_or_compute(db, user_id=current_user.id)
