"""Shared FastAPI dependencies (Phase 8: auth foundation).

`get_current_user` follows the same shape as `app.db.get_db` — a plain
`Depends`-able callable. Wired into `api/library.py` (Phase 8.2) and
`api/taste.py` / `api/recommendations.py` (Phase 8.3); search and
media-details stay unauthenticated (spec §13).
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services import auth as auth_service

# `tokenUrl` only feeds the OpenAPI docs' "Authorize" flow (spec: a standard
# bearer-token structure) — it doesn't constrain how /auth/login itself is
# called, which stays plain JSON like the rest of this API.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str | None = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extract + verify the bearer token, load the user it names.

    Raises 401 for every failure mode alike (missing header, malformed token,
    bad signature, expired token, or a user id that no longer exists) — never
    reveals which one it was.
    """
    if token is None:
        raise _UNAUTHORIZED
    try:
        user_id = auth_service.decode_access_token(token)
    except auth_service.InvalidToken as exc:
        raise _UNAUTHORIZED from exc

    user = auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user
