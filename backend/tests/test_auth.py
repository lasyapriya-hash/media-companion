"""Phase 8: authentication foundation (register, login, get_current_user).

Nothing here touches library/recommendation routes — those aren't
auth-protected yet (deliberately, per this phase's scope).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.api.deps import get_current_user
from app.config import get_settings
from app.models.user import User
from app.services import auth as svc

EMAIL = "reader@example.com"
PASSWORD = "correct-horse-battery-staple"


# --------------------------------------------------------------------------- #
# POST /auth/register
# --------------------------------------------------------------------------- #
def test_register_succeeds(client):
    resp = client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == EMAIL
    assert "id" in body and uuid.UUID(body["id"])
    assert "created_at" in body
    # never returned, in any shape
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_normalizes_email(client):
    resp = client.post(
        "/auth/register", json={"email": "  Reader@Example.COM  ", "password": PASSWORD}
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == EMAIL


def test_register_duplicate_email_is_409(client):
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    resp = client.post("/auth/register", json={"email": EMAIL, "password": "another-pass1"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


def test_register_duplicate_email_case_insensitive(client):
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    resp = client.post(
        "/auth/register", json={"email": "READER@EXAMPLE.COM", "password": PASSWORD}
    )
    assert resp.status_code == 409


def test_register_rejects_short_password(client):
    resp = client.post("/auth/register", json={"email": EMAIL, "password": "short"})
    assert resp.status_code == 422


def test_register_rejects_malformed_email(client):
    resp = client.post(
        "/auth/register", json={"email": "not-an-email", "password": PASSWORD}
    )
    assert resp.status_code == 422


def test_password_is_stored_hashed_never_plaintext(client, db_session):
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    user = db_session.query(User).filter(User.email == EMAIL).one()
    assert user.hashed_password != PASSWORD
    assert PASSWORD not in user.hashed_password
    # a real bcrypt hash: one of the standard prefixes + non-trivial length
    assert user.hashed_password.startswith(("$2a$", "$2b$", "$2y$"))
    assert len(user.hashed_password) >= 50
    assert svc.verify_password(PASSWORD, user.hashed_password)


# --------------------------------------------------------------------------- #
# POST /auth/login
# --------------------------------------------------------------------------- #
def test_login_succeeds_and_returns_bearer_token(client):
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    resp = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]
    # a real, decodable JWT for this user
    settings = get_settings()
    payload = jwt.decode(
        body["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    assert "sub" in payload and "exp" in payload


def test_login_wrong_password_is_401(client):
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    resp = client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    assert resp.status_code == 401
    assert "access_token" not in resp.json()


def test_login_nonexistent_user_is_401(client):
    resp = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 401


def test_login_error_message_does_not_reveal_which_field_was_wrong(client):
    """Same detail for 'no such email' and 'wrong password' — otherwise the
    error itself becomes an email-enumeration oracle."""
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    wrong_password = client.post(
        "/auth/login", json={"email": EMAIL, "password": "nope-nope-nope"}
    )
    no_such_user = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_password.json()["detail"] == no_such_user.json()["detail"]


# --------------------------------------------------------------------------- #
# get_current_user (Phase 8 dependency — not wired into any route yet)
# --------------------------------------------------------------------------- #
def test_get_current_user_accepts_a_valid_token(client, db_session):
    reg = client.post(
        "/auth/register", json={"email": EMAIL, "password": PASSWORD}
    ).json()
    token = client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]

    user = get_current_user(token=token, db=db_session)
    assert str(user.id) == reg["id"]
    assert user.email == EMAIL


def test_get_current_user_rejects_missing_token(db_session):
    with pytest.raises(Exception) as exc_info:
        get_current_user(token=None, db=db_session)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_get_current_user_rejects_malformed_token(db_session):
    with pytest.raises(Exception) as exc_info:
        get_current_user(token="not-a-real-jwt", db=db_session)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_get_current_user_rejects_wrong_signature(db_session):
    settings = get_settings()
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "a-completely-different-secret-of-plausible-length-1234567890",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(Exception) as exc_info:
        get_current_user(token=forged, db=db_session)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_get_current_user_rejects_expired_token(client, db_session):
    reg = client.post(
        "/auth/register", json={"email": EMAIL, "password": PASSWORD}
    ).json()
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": reg["id"], "iat": now - timedelta(minutes=20), "exp": now - timedelta(minutes=10)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(Exception) as exc_info:
        get_current_user(token=expired, db=db_session)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_get_current_user_rejects_valid_token_for_deleted_user(client, db_session):
    """Signature and expiry are both fine, but the user id it names doesn't
    exist — must still be rejected, not silently loaded as None-ish."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(Exception) as exc_info:
        get_current_user(token=token, db=db_session)
    assert getattr(exc_info.value, "status_code", None) == 401


# --------------------------------------------------------------------------- #
# services/auth.py — unit-level coverage of the token helpers directly
# --------------------------------------------------------------------------- #
def test_decode_access_token_round_trips_create_access_token():
    user_id = uuid.uuid4()
    token = svc.create_access_token(user_id)
    assert svc.decode_access_token(token) == user_id


def test_decode_access_token_rejects_expired(monkeypatch):
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now - timedelta(days=1), "exp": now - timedelta(hours=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(svc.InvalidToken):
        svc.decode_access_token(token)


def test_hash_password_is_nondeterministic_but_both_verify():
    """bcrypt salts each hash — two hashes of the same password must differ,
    and both must still verify."""
    a = svc.hash_password(PASSWORD)
    b = svc.hash_password(PASSWORD)
    assert a != b
    assert svc.verify_password(PASSWORD, a)
    assert svc.verify_password(PASSWORD, b)


def test_verify_password_rejects_wrong_password():
    hashed = svc.hash_password(PASSWORD)
    assert not svc.verify_password("definitely-wrong", hashed)
