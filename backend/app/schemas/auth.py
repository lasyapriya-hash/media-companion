"""Request/response shapes for authentication (Phase 8: auth foundation)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # A length floor only — this is a personal-project auth foundation, not a
    # password-strength policy; that's a separate, later concern.
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("not a valid email address")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    """Never includes `hashed_password` — this is the whole point of the
    model existing separately from `User` (spec: never return the hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    """Standard OAuth2 bearer-token response shape."""

    access_token: str
    token_type: str = "bearer"
