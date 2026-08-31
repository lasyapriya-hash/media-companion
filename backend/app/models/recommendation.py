"""`recommendation_session` — optional, non-durable conversation state (spec §6.1)."""
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
