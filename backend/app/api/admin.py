"""Temporary, one-purpose legacy-library-claim endpoint (Phase 8.2
bootstrap).

Exists only because this Render plan has neither interactive Shell nor
one-off Job access, so `app/scripts/claim_legacy_library.py` can't be run
directly against production — this route drives the exact same shared
claiming logic (`app/services/legacy_claim.py`) over HTTPS instead, with
the same safety guarantees (only `library_entry` rows at `user_id IS
NULL`; only `user_id` is ever set; nothing is ever deleted; idempotent;
a dry run never writes).

This is deliberately NOT a general admin system: one hardcoded route,
gated to exactly one pre-configured email (`LEGACY_CLAIM_ALLOWED_EMAIL`),
with no role model, no other admin operations, and no plan to add any.
Meant to be deleted (this file + its one line in app/main.py + the
`legacy_claim_allowed_email` setting) once the legacy rows are claimed
and verified — see spec.md / plan.md Phase 8.2 for the full rollout.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models.user import User
from app.services.legacy_claim import claim_orphaned_entries

router = APIRouter(prefix="/admin", tags=["admin"])


class ClaimLegacyLibraryRequest(BaseModel):
    """`extra="forbid"`: a request can only ever say *whether* to write, not
    *who* to claim for — the target is always the caller's own JWT identity,
    never something the request body could specify or override."""

    model_config = ConfigDict(extra="forbid")

    # Defaults to a dry run — a real write requires the caller to pass
    # `dry_run: false` explicitly. Inverted default vs. the CLI script
    # on purpose: this is reachable over the network, the CLI isn't.
    dry_run: bool = True


class ClaimedEntryOut(BaseModel):
    title: str
    type: str


class ClaimLegacyLibraryResponse(BaseModel):
    dry_run: bool
    count: int
    entries: list[ClaimedEntryOut]


def _require_allowed_caller(current_user: User) -> None:
    allowed = get_settings().legacy_claim_allowed_email.strip().lower()
    # current_user.email is already normalized (stripped + lowercased) at
    # registration time (schemas/auth.py) — same semantics on both sides.
    if not allowed or current_user.email != allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/claim-legacy-library", response_model=ClaimLegacyLibraryResponse)
def claim_legacy_library(
    req: ClaimLegacyLibraryRequest = ClaimLegacyLibraryRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClaimLegacyLibraryResponse:
    _require_allowed_caller(current_user)

    result = claim_orphaned_entries(
        db, user_id=current_user.id, dry_run=req.dry_run
    )

    return ClaimLegacyLibraryResponse(
        dry_run=result.dry_run,
        count=result.count,
        entries=[
            ClaimedEntryOut(title=e.title, type=e.media_type) for e in result.entries
        ],
    )
