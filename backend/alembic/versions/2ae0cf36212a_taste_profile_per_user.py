"""taste_profile becomes per-user (Phase 8.3: personalization isolation)

Replaces `taste_profile`'s hardcoded `id=1` singleton primary key with
`user_id` (FK -> user.id, CASCADE) as the primary key itself — one row per
account, enforced structurally rather than by convention.

`taste_profile` is **derived/cache data only**: every field is fully
rebuildable from `library_entry` via `taste_profile.recompute()`, and none of
it is ever user-input. The old singleton row (if one exists) was computed
from *every* account's library combined pre-Phase-8.2 and post-8.2-pre-8.3 —
it does not correspond to any single real account, so there is nothing
correct to backfill it to. Assigning it to a guessed owner would repeat
exactly the mistake the original (later reworked) Phase 8.2 migration draft
made with `library_entry`: inventing an owner for data that has none. Unlike
`library_entry`, there is no real data to lose here — the row is discarded
and every account's profile is transparently rebuilt (empty until then, then
correct) the next time `taste_profile.get_or_compute()` runs for them.

Does **not** touch `library_entry`, `series_progress`, or any other table —
the Phase 8.2 library-ownership data is untouched by this migration.

Revision ID: 2ae0cf36212a
Revises: 1c240902dee9
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '2ae0cf36212a'
down_revision: Union[str, None] = '1c240902dee9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Derived data only (see module docstring) — safe to discard outright
    # rather than guess an owner for it. A no-op on a database with no
    # existing taste_profile row (e.g. a fresh deploy).
    op.execute("TRUNCATE TABLE taste_profile")

    op.drop_constraint('taste_profile_pkey', 'taste_profile', type_='primary')
    op.drop_column('taste_profile', 'id')
    op.add_column(
        'taste_profile',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_primary_key('taste_profile_pkey', 'taste_profile', ['user_id'])
    op.create_foreign_key(
        'fk_taste_profile_user_id',
        'taste_profile',
        'user',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    # Same story in reverse: per-user profiles don't collapse losslessly back
    # into one singleton row, so this discards data rather than merging it —
    # consistent with upgrade() treating this table as pure cache.
    op.execute("TRUNCATE TABLE taste_profile")

    op.drop_constraint('fk_taste_profile_user_id', 'taste_profile', type_='foreignkey')
    op.drop_constraint('taste_profile_pkey', 'taste_profile', type_='primary')
    op.drop_column('taste_profile', 'user_id')
    op.add_column(
        'taste_profile',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    )
    op.create_primary_key('taste_profile_pkey', 'taste_profile', ['id'])
