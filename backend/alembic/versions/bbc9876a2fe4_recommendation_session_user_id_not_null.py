"""recommendation_session.user_id NOT NULL (spec.md v2.0: every session
belongs to exactly one authenticated account)

`bee1a3183184` added `user_id` as nullable **by design, permanently** —
correct under v1.x's incremental rollout, where pre-Phase-8.3 sessions had no
owner and were deliberately left `NULL` forever rather than backfilled. spec
v2.0 redesigned `recommendation_session` as core multi-user architecture
rather than a legacy-accommodating add-on: `user_id` is now specified as
`not null` (spec §6.1) — every session belongs to exactly one account,
structurally, not just by application-level convention. This migration
brings the schema into line with that.

Every session created since Phase 8.3 already has a real `user_id`
(`start_session` has always required it, and no code path can start a
session without an authenticated caller) — this migration only tightens the
constraint the database enforces, it does not change what the application
already writes.

Refuses to run if any row still has `user_id IS NULL`, with an explicit
pre-check that raises a clear, actionable error identifying the row count
before ever touching the column — rather than a bare Postgres
constraint-violation error, and rather than silently discarding or
reassigning those rows. `recommendation_session` has no natural "real owner"
to backfill onto the way `library_entry` did in Phase 8.2 (there is no
registered account a stale, ownerless debug session obviously belongs to) —
if any such rows are found, the correct fix is a deliberate human decision
(this table is documented, prunable debug data per spec §6.1/§8.4, so
deleting the specific stale rows is one reasonable option) made outside this
migration, not something this migration assumes or automates.

Safe on a fresh/empty database: zero rows trivially satisfy the pre-check.

Revision ID: bbc9876a2fe4
Revises: bee1a3183184
Create Date: 2026-09-13 18:48:13.050398
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bbc9876a2fe4'
down_revision: Union[str, None] = 'bee1a3183184'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    null_count = conn.execute(
        sa.text("SELECT count(*) FROM recommendation_session WHERE user_id IS NULL")
    ).scalar()
    if null_count:
        raise RuntimeError(
            f"Cannot set recommendation_session.user_id NOT NULL: {null_count} "
            "row(s) still have user_id IS NULL. This table has no real owner "
            "to backfill these onto (spec §6.1) — decide deliberately how to "
            "handle them (e.g. delete these specific stale, prunable-by-design "
            "rows per spec §8.4) before re-running this migration. It will not "
            "do so automatically."
        )
    op.alter_column('recommendation_session', 'user_id', nullable=False)


def downgrade() -> None:
    op.alter_column('recommendation_session', 'user_id', nullable=True)
