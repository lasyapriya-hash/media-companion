"""`user` — an account (Phase 8: multi-user authentication foundation).

This migration/model deliberately does not touch any other table. Nothing yet
references `user.id` as a foreign key — that wiring (LibraryEntry.user_id,
TasteProfile, RecommendationSession) is later Phase 8 work.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "user"
    __table_args__ = (sa.UniqueConstraint("email", name="uq_user_email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Normalized (stripped + lowercased) before storage — see app/services/auth.py.
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    hashed_password: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
