"""delete legacy NULL-owned recommendation sessions

Removes `recommendation_session` rows with `user_id IS NULL` — pre-Phase-8.3
(indeed pre-Phase-8.1) rows created before the `user` table existed at all,
back when the app had no accounts. `bee1a3183184` added `user_id` nullable
specifically to accommodate these rows without inventing an owner for them;
they have been permanently unreachable through the API ever since (every
ownership check rejects a NULL-owned row against any authenticated caller,
identically to a nonexistent session — see `answer_session`).

This is a deliberate, narrowly-scoped prerequisite for `bbc9876a2fe4`
(`recommendation_session.user_id NOT NULL`), which spec.md v2.0 §6.1
requires: every session now belongs to exactly one authenticated account,
with no legacy-NULL accommodation. `recommendation_session` is explicitly
documented as non-durable debug data (spec §6.1, §8.4: "rows are not
surfaced as user-visible history and MAY be pruned freely... regardless of
age") — unlike `library_entry`, there is no real owner to backfill these
onto, no way for any current account to have created them, and no feature
anywhere that would ever surface or resume one even for the account that
originally triggered it. Deletion, not reassignment, is the behavior spec
v2.0 itself prescribes for stale rows in this specific table.

Scope, precisely:
- Deletes ONLY `recommendation_session` rows where `user_id IS NULL`.
- Every `recommendation_session` row with a non-NULL `user_id` is left
  completely untouched.
- No other table is read or written by this migration. No FK anywhere
  references `recommendation_session.id`, so this delete cannot cascade
  into or affect `user`, `library_entry`, `series_progress`,
  `taste_profile`, or `media_item`.
- No reassignment, no backfill, no placeholder owner — only a delete.

Safe on a fresh/empty database: zero matching rows, a no-op delete.

Revision ID: 3c1cd7a08822
Revises: bee1a3183184
Create Date: 2026-09-13 19:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3c1cd7a08822'
down_revision: Union[str, None] = 'bee1a3183184'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("DELETE FROM recommendation_session WHERE user_id IS NULL")
    )
    print(f"==> deleted {result.rowcount} legacy NULL-owned recommendation_session row(s)")


def downgrade() -> None:
    # Deliberately irreversible: the deleted rows' data cannot be
    # reconstructed. Matches this table's own documented semantics (spec
    # §6.1, §8.4) — pruned debug data is not expected to come back.
    pass
