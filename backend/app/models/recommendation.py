"""`recommendation_session` — optional, non-durable conversation state (spec §6.1).

`user_id` is required: every session belongs to exactly one authenticated
account (spec §6.1). This table is still debug/prunable data (spec §8.4) —
rows may be pruned freely regardless of age — but ownership itself is not
optional; there is no legacy-NULL accommodation in the current schema (see
migration `bbc9876a2fe4`, which tightened a prior nullable-by-design column
now that spec v2.0 no longer treats this table as a legacy-accommodating
add-on).
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import SessionState, enum_values


class RecommendationSession(Base):
    __tablename__ = "recommendation_session"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_request: Mapped[str] = mapped_column(sa.Text, nullable=False)
    preference_object: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    clarification_question: Mapped[str | None] = mapped_column(sa.Text)
    clarification_answer: Mapped[str | None] = mapped_column(sa.Text)
    # Invariant (spec §8.2): once true, no further clarifying question may be asked.
    clarification_used: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    results: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[SessionState] = mapped_column(
        sa.Enum(SessionState, name="session_state", values_callable=enum_values),
        nullable=False,
        server_default=SessionState.extracting.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
