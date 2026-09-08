"""Authentication foundation (Phase 8): password hashing, JWT issuing/
verification, and the register/authenticate business logic.

Deliberately self-contained — nothing here is wired into any existing
route yet. No Anthropic dependency; no third-party auth service.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User

# bcrypt's own hard limit — silently truncates beyond this, so a longer
# password would collide with a truncated one if left unchecked. The schema's
# own `max_length=200` (schemas/auth.py) already keeps requests well under
# this; checked again here since this function has no schema in front of it
# once called directly (e.g. from a script or a future admin path).
_BCRYPT_MAX_PASSWORD_BYTES = 72


# --------------------------------------------------------------------------- #
# Errors (mapped to HTTP in the router, same pattern as services/library.py)
# --------------------------------------------------------------------------- #
class AuthError(Exception):
    pass


class EmailAlreadyRegistered(AuthError):
    pass


class InvalidCredentials(AuthError):
    """Deliberately the same error for "no such email" and "wrong password"
    — never reveal which one it was (that itself leaks whether an email is
    registered)."""


class InvalidToken(AuthError):
    """Missing/malformed/wrong-signature/expired token, or the token names a
    user that no longer exists — all collapse to one 401 at the API layer."""


# --------------------------------------------------------------------------- #
# Password hashing (bcrypt directly — no passlib: passlib is unmaintained and
# has known incompatibilities with recent bcrypt releases; bcrypt's own API
# is small enough not to need a wrapper).
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    raw = password.encode("utf-8")[:_BCRYPT_MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except ValueError:
        # Malformed stored hash — never a match, never a 500.
        return False


# --------------------------------------------------------------------------- #
# JWT issuing / verification
# --------------------------------------------------------------------------- #
def _require_secret() -> str:
    secret = get_settings().jwt_secret_key
    if not secret:
        # A blank/predictable key would let anyone forge a token — refuse
        # outright rather than signing with an insecure fallback.
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured; cannot sign or verify tokens"
        )
    return secret


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, _require_secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Verify signature + expiry, return the user id. Raises `InvalidToken`
    for every failure mode — malformed, wrong signature, expired, or a `sub`
    that isn't a UUID — never a raw jwt/library exception past this point."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, _require_secret(), algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("token invalid") from exc

    sub = payload.get("sub")
    try:
        return uuid.UUID(str(sub))
    except (TypeError, ValueError) as exc:
        raise InvalidToken("token subject is not a valid user id") from exc


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def register_user(db: Session, email: str, password: str) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailAlreadyRegistered(email)

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.hashed_password):
        raise InvalidCredentials(email)
    return user


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)
