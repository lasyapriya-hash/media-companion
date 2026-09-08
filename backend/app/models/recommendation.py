"""`recommendation_session` — optional, non-durable conversation state (spec §6.1).

`user_id` (Phase 8.3) is nullable by design, not just during a migration
transition: sessions created before Phase 8.3 have no owner and are left
that way permanently (spec: this table is explicitly debug/prunable data,
spec §8.4 session lifetime) rather than backfilled via a claim step like
`library_entry` got in Phase 8.2. A `NULL` owner makes a row unreachable
through any user-scoped operation (an authenticated request can never match
`user_id IS NULL`), which is exactly the desired outcome for orphaned legacy
rows — not a gap to close.
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
    # Nullable: see module docstring. Every session created from Phase 8.3
    # onward always sets this (`start_session` requires `user_id`) — only
    # pre-8.3 legacy rows are ever NULL.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
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
