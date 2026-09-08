"""add user_id to recommendation_session (Phase 8.3: personalization isolation)

Adds `recommendation_session.user_id` (FK -> user.id, CASCADE) as **nullable
by design, permanently** — not a transitional state like `library_entry`'s
Phase 8.2 nullable-then-NOT-NULL migration pair.

`recommendation_session` is documented (spec §6.1, §8.4) as non-durable debug
data: rows may be pruned freely and aren't part of any user-visible history.
Every session created from this point on always gets a real `user_id` (Phase
8.3's `start_session` requires it) — only pre-8.3 rows stay `NULL` forever,
and that's intentional: `answer_session`'s ownership check
(`session.user_id != user_id`) means a `NULL`-owned row can never match any
authenticated caller, so legacy rows simply become permanently unreachable
through the API rather than needing a claim step like Phase 8.2's library
data did. No backfill, no placeholder account, nothing to reassign.

Revision ID: bee1a3183184
Revises: 2ae0cf36212a
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'bee1a3183184'
down_revision: Union[str, None] = '2ae0cf36212a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recommendation_session',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_recommendation_session_user_id',
        'recommendation_session',
        'user',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_recommendation_session_user_id', 'recommendation_session', type_='foreignkey'
    )
    op.drop_column('recommendation_session', 'user_id')
