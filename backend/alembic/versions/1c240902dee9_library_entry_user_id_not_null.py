"""library_entry.user_id NOT NULL (Phase 8.2c: library ownership, lock-down)

Tightens `library_entry.user_id` (added nullable in `47cf8fa2576e`) to NOT
NULL. Deploy this **only** after confirming every pre-existing row has been
claimed by a real account:

    python -m app.scripts.claim_legacy_library --email you@example.com

and verifying zero rows remain unclaimed, e.g.:

    SELECT count(*) FROM library_entry WHERE user_id IS NULL;  -- must be 0

If any row is still unclaimed when this migration runs, `ALTER COLUMN ...
SET NOT NULL` fails and the deploy stops — that's the intended behavior:
it forces the claim step to be completed first, instead of this migration
silently inventing an owner for whatever is left (which is exactly what the
first version of this migration used to do, and why it was split in two).

Safe on a fresh/empty database: an empty `library_entry` table has no rows
to violate the constraint, so this is a no-op there too.

Revision ID: 1c240902dee9
Revises: 47cf8fa2576e
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = '1c240902dee9'
down_revision: Union[str, None] = '47cf8fa2576e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('library_entry', 'user_id', nullable=False)


def downgrade() -> None:
    op.alter_column('library_entry', 'user_id', nullable=True)
