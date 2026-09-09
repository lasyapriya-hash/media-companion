"""Shared legacy-library-claim logic (Phase 8.2 bootstrap).

Used by both `app/scripts/claim_legacy_library.py` (the original CLI,
for environments with Render Shell/Job access) and
`app/api/admin.py`'s temporary `POST /admin/claim-legacy-library`
endpoint (for plans without either) — one function, one set of safety
guarantees, so the two entry points can never drift apart.

Safety properties, all enforced here and nowhere else:
- Only ever reads/writes `library_entry` rows where `user_id IS NULL`.
- Only ever sets `user_id` on those rows — no other column, ever.
- Never touches `media_item` or `series_progress` (the latter inherits
  ownership automatically through its 1:1 FK to `library_entry`).
- Never deletes anything.
- Idempotent: once every row has an owner, finds zero rows to claim.
- Commits only when `dry_run` is False; a dry run performs strictly two
  `SELECT`s and no write of any kind.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import LibraryEntry


@dataclass(frozen=True)
class ClaimedEntry:
    title: str
    media_type: str


@dataclass(frozen=True)
class ClaimResult:
    dry_run: bool
    user_id: uuid.UUID
    count: int
    entries: list[ClaimedEntry]


def claim_orphaned_entries(
    db: Session, *, user_id: uuid.UUID, dry_run: bool
) -> ClaimResult:
    """Assign every `library_entry` row currently at `user_id IS NULL` to
    `user_id`. With `dry_run=True`, reports what *would* be claimed without
    setting anything or committing.
    """
    orphaned = list(
        db.scalars(select(LibraryEntry).where(LibraryEntry.user_id.is_(None)))
    )

    entries = [
        ClaimedEntry(title=entry.media.title, media_type=entry.media.type.value)
        for entry in orphaned
    ]

    if not dry_run:
        for entry in orphaned:
            entry.user_id = user_id
        db.commit()

    return ClaimResult(
        dry_run=dry_run, user_id=user_id, count=len(orphaned), entries=entries
    )
