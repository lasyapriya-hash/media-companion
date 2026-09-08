"""add user_id to library_entry, nullable (Phase 8.2a: library ownership, schema)

Adds `library_entry.user_id` (FK -> user.id, CASCADE) as a **nullable**
column and replaces the global `unique(media_item_id)` constraint with a
per-user `unique(user_id, media_item_id)` — the same title can now exist in
two different users' libraries, but not twice in the same one.

Deliberately does **not** backfill or tighten to NOT NULL, and never invents
a placeholder account: this migration runs unattended at deploy time
(`start.sh` -> `alembic upgrade head`), so it has no way to know who should
own pre-existing rows, and guessing (or minting a disposable account) would
either assign real data to the wrong owner or create a permanent account
nobody can log into. Deciding who owns pre-existing rows is a deliberate,
authenticated, human action instead: register the real account normally via
`POST /auth/register`, then run `python -m app.scripts.claim_legacy_library`
once (see that script's docstring) to assign every still-`user_id IS NULL`
row to it. Only once that's confirmed does the follow-up migration
(`add_library_entry_user_id_not_null`, Revises this one) tighten the column
to NOT NULL — split out specifically so it fails loudly on any row still
unclaimed, rather than silently inventing an owner for it.

Safe on a fresh/empty database: this migration is pure additive DDL with no
data-touching statements, so an empty `library_entry` table is a no-op here.

`series_progress` is untouched: it's already scoped 1:1 to `library_entry`
via `library_entry_id` (cascade), so it inherits ownership through its
parent without needing its own `user_id`.

Revision ID: 47cf8fa2576e
Revises: 72ec4e899aca
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '47cf8fa2576e'
down_revision: Union[str, None] = '72ec4e899aca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'library_entry',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_library_entry_user_id',
        'library_entry',
        'user',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )

    # Safe to swap straight away, even while every row is still `user_id
    # IS NULL`: Postgres treats each NULL in a unique constraint as distinct
    # from every other NULL, and the *old* unique(media_item_id) constraint
    # already guaranteed no two existing rows share a media_item_id — so no
    # (NULL, media_item_id) collision can exist either.
    op.drop_constraint('uq_library_entry_media_item', 'library_entry', type_='unique')
    op.create_unique_constraint(
        'uq_library_entry_user_media_item', 'library_entry', ['user_id', 'media_item_id']
    )


def downgrade() -> None:
    # Not perfectly reversible once more than one user holds the same
    # media_item_id: restoring the single-column unique constraint fails
    # loudly (not silently) if that's the case at downgrade time — resolve
    # any such duplicates manually before downgrading past this point.
    op.drop_constraint('uq_library_entry_user_media_item', 'library_entry', type_='unique')
    op.create_unique_constraint(
        'uq_library_entry_media_item', 'library_entry', ['media_item_id']
    )
    op.drop_constraint('fk_library_entry_user_id', 'library_entry', type_='foreignkey')
    op.drop_column('library_entry', 'user_id')
