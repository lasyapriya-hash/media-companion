"""`taste_profile` — single derived record, recomputed on rating/status change
(spec §6.3). Populated by the Phase 3 taste-profile service; this migration only
creates the table.
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Single-user instance -> exactly one row, keyed on this id.
SINGLETON_ID = 1


class TasteProfile(Base):
    __tablename__ = "taste_profile"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=False, default=SINGLETON_ID
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
