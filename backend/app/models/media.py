"""`media_item` — cached external metadata (spec §6.1)."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import MediaSource, MediaType, enum_values


class MediaItem(Base):
    __tablename__ = "media_item"
    __table_args__ = (
        sa.UniqueConstraint("source", "source_id", name="uq_media_item_source_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[MediaSource] = mapped_column(
        sa.Enum(MediaSource, name="media_source", values_callable=enum_values),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    type: Mapped[MediaType] = mapped_column(
        sa.Enum(MediaType, name="media_type", values_callable=enum_values),
        nullable=False,
    )

    # Common fields
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    genres: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    language: Mapped[str | None] = mapped_column(sa.String(32))
    year: Mapped[int | None] = mapped_column(sa.Integer)
    external_rating: Mapped[float | None] = mapped_column(sa.Numeric(4, 2))
    artwork_url: Mapped[str | None] = mapped_column(sa.Text)

    # Movie
    runtime_minutes: Mapped[int | None] = mapped_column(sa.Integer)
    # Series
    seasons: Mapped[int | None] = mapped_column(sa.Integer)
    episodes: Mapped[int | None] = mapped_column(sa.Integer)
    episode_runtime_minutes: Mapped[int | None] = mapped_column(sa.Integer)
    # Book
    author: Mapped[str | None] = mapped_column(sa.Text)
    page_count: Mapped[int | None] = mapped_column(sa.Integer)

    # Derived / enrichment
    mood_tags: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    raw_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
