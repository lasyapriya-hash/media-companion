"""`taste_profile` — one derived record per account, recomputed on rating/status
change (spec §6.3, Phase 8.3). Populated by the taste-profile service; this
migration only creates the table.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TasteProfile(Base):
    __tablename__ = "taste_profile"

    # The owning account IS the primary key (Phase 8.3) — this is what makes
    # "one profile per user" structural rather than an application-level
    # convention: a second row for the same user is a primary-key violation,
    # not just a bug someone could introduce later.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Ranked lists of labels.
    favourite_genres: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    favourite_languages: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # label -> mean personal rating.
    avg_rating_by_genre: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    avg_rating_by_language: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # Overall completed / (completed + dropped).
    completion_rate: Mapped[float | None] = mapped_column(sa.Numeric(4, 3))
    # genre -> completion rate.
    completion_rate_by_genre: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # Genres/languages with a low completion rate.
    drop_patterns: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    computed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
