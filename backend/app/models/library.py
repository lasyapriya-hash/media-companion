"""`library_entry` and `series_progress` (spec §6.1)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import LibraryStatus, enum_values


class LibraryEntry(Base):
    __tablename__ = "library_entry"
    __table_args__ = (
        sa.UniqueConstraint("media_item_id", name="uq_library_entry_media_item"),
        sa.CheckConstraint(
            "rating IS NULL OR "
            "(rating >= 1.0 AND rating <= 10.0 AND (rating * 2) = floor(rating * 2))",
            name="ck_library_entry_rating_half_step",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("media_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[LibraryStatus] = mapped_column(
        sa.Enum(LibraryStatus, name="library_status", values_callable=enum_values),
        nullable=False,
    )
    favourite: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    # 1.0–10.0 in 0.5 steps (spec §5.1); enforced by the check constraint above.
    rating: Mapped[float | None] = mapped_column(sa.Numeric(3, 1))
    review: Mapped[str | None] = mapped_column(sa.Text)

    added_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    progress: Mapped["SeriesProgress | None"] = relationship(
        back_populates="entry", cascade="all, delete-orphan", uselist=False
    )


class SeriesProgress(Base):
    __tablename__ = "series_progress"

    library_entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("library_entry.id", ondelete="CASCADE"),
        primary_key=True,
    )
    seasons_completed: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0"
    )
    current_season: Mapped[int | None] = mapped_column(sa.Integer)
    current_episode: Mapped[int | None] = mapped_column(sa.Integer)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    entry: Mapped[LibraryEntry] = relationship(back_populates="progress")
