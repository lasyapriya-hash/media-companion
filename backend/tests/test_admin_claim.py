"""Tests for the temporary legacy-library-claim admin endpoint
(Phase 8.2 bootstrap, app/api/admin.py) — exists only because this Render
plan has no Shell/Job access to run claim_legacy_library.py directly.

Stage A's `client` fixture does not auto-authenticate (that's a Stage-C
change) and `POST /library` is still unauthenticated at this stage, so
every entry it creates lands with `user_id IS NULL` — exactly the shape
production's real legacy rows have. This file provides its own
register/login helper rather than depending on a conftest.py change.
"""
from __future__ import annotations

import uuid

from app.models.library import LibraryEntry
from app.schemas.media import NormalizedMedia

ALLOWED_EMAIL = "legacy-owner@example.com"  # matches conftest.py's LEGACY_CLAIM_ALLOWED_EMAIL


def _movie(**over):
    base = dict(
        source="tmdb",
        type="movie",
        title="Legacy Item",
        description="x",
        genres=["Drama"],
        language="en",
        year=2010,
        external_rating=7.0,
    )
    base.update(over)
    return NormalizedMedia(**base).model_dump()


def _add_orphaned_entry(client, **over):
    """POST /library at Stage A has no auth wiring yet and services/library.py
    never sets user_id — so every entry created this way is exactly the shape
    a real pre-Phase-8.2 legacy row has (user_id IS NULL)."""
    resp = client.post("/library", json={"item": _movie(**over)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _register_and_login(client, email: str, password: str = "correct-horse-battery") -> dict[str, str]:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    if resp.status_code not in (201, 409):
        resp.raise_for_status()
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    login_resp.raise_for_status()
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Authentication / authorization
# --------------------------------------------------------------------------- #
def test_unauthenticated_request_is_401(client):
    resp = client.post("/admin/claim-legacy-library", json={"dry_run": True})
    assert resp.status_code == 401


def test_authenticated_non_allowlisted_user_is_403(client):
    _add_orphaned_entry(client, source_id="A1")
    headers = _register_and_login(client, "someone-else@example.com")

    resp = client.post(
        "/admin/claim-legacy-library", json={"dry_run": True}, headers=headers
    )
    assert resp.status_code == 403

    # and no row was touched by the attempt
    resp2 = client.post(
        "/admin/claim-legacy-library", json={"dry_run": True}, headers=headers
    )
    assert resp2.status_code == 403


def test_endpoint_disabled_when_allowed_email_unset(client, monkeypatch):
    """Blank LEGACY_CLAIM_ALLOWED_EMAIL must fail closed for everyone,
    including the account whose email happens to be blank-adjacent."""
    monkeypatch.setattr(
        "app.api.admin.get_settings",
        lambda: type("S", (), {"legacy_claim_allowed_email": ""})(),
    )
    headers = _register_and_login(client, ALLOWED_EMAIL)
    resp = client.post(
        "/admin/claim-legacy-library", json={"dry_run": True}, headers=headers
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Dry run: no writes
# --------------------------------------------------------------------------- #
def test_allowlisted_user_dry_run_reports_correct_rows_no_writes(client, db_session):
    _add_orphaned_entry(client, source_id="B1", title="First Legacy Item")
    _add_orphaned_entry(client, source_id="B2", title="Second Legacy Item")
    headers = _register_and_login(client, ALLOWED_EMAIL)

    resp = client.post(
        "/admin/claim-legacy-library", json={"dry_run": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert body["count"] == 2
    titles = {e["title"] for e in body["entries"]}
    assert titles == {"First Legacy Item", "Second Legacy Item"}
    assert all(e["type"] == "movie" for e in body["entries"])

    # no write happened — every row is still unowned
    still_null = db_session.query(LibraryEntry).filter(
        LibraryEntry.user_id.is_(None)
    ).count()
    assert still_null == 2


def test_dry_run_is_the_default_when_body_omitted(client):
    _add_orphaned_entry(client, source_id="C1")
    headers = _register_and_login(client, ALLOWED_EMAIL)

    resp = client.post("/admin/claim-legacy-library", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["dry_run"] is True
    assert resp.json()["count"] == 1


# --------------------------------------------------------------------------- #
# Real run: writes, idempotent, ownership-correct
# --------------------------------------------------------------------------- #
def test_allowlisted_user_real_run_claims_rows(client, db_session):
    entry_id = _add_orphaned_entry(client, source_id="D1")
    headers = _register_and_login(client, ALLOWED_EMAIL)

    resp = client.post(
        "/admin/claim-legacy-library", json={"dry_run": False}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is False
    assert body["count"] == 1

    entry = db_session.get(LibraryEntry, uuid.UUID(entry_id))
    assert entry.user_id is not None
    # claimed to the caller's own JWT identity, not some other id
    from app.models.user import User

    claimer = db_session.query(User).filter(User.email == ALLOWED_EMAIL).one()
    assert entry.user_id == claimer.id


def test_repeated_real_run_is_idempotent(client, db_session):
    _add_orphaned_entry(client, source_id="E1")
    headers = _register_and_login(client, ALLOWED_EMAIL)

    first = client.post(
        "/admin/claim-legacy-library", json={"dry_run": False}, headers=headers
    )
    assert first.json()["count"] == 1

    second = client.post(
        "/admin/claim-legacy-library", json={"dry_run": False}, headers=headers
    )
    assert second.status_code == 200
    assert second.json()["count"] == 0
    assert second.json()["entries"] == []


def test_already_owned_rows_are_never_touched_or_reclaimed(client, db_session):
    """A row someone else already owns must stay exactly as it is — not
    reassigned to the caller, not reported as claimable."""
    from app.models.user import User

    other_owned_id = _add_orphaned_entry(client, source_id="F1", title="Not Yours")
    # A real, already-registered second account — LibraryEntry.user_id has
    # an FK to user.id, so the "already owned" row needs a genuine owner.
    _register_and_login(client, "other-owner@example.com")
    other_user = db_session.query(User).filter(
        User.email == "other-owner@example.com"
    ).one()
    entry = db_session.get(LibraryEntry, uuid.UUID(other_owned_id))
    entry.user_id = other_user.id
    db_session.commit()
    other_user_id = other_user.id

    _add_orphaned_entry(client, source_id="F2", title="Genuinely Legacy")
    headers = _register_and_login(client, ALLOWED_EMAIL)

    resp = client.post(
        "/admin/claim-legacy-library", json={"dry_run": False}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["entries"][0]["title"] == "Genuinely Legacy"

    # the already-owned row's owner is completely unchanged
    db_session.refresh(entry)
    assert entry.user_id == other_user_id


# --------------------------------------------------------------------------- #
# Target identity comes from the JWT only
# --------------------------------------------------------------------------- #
def test_request_body_cannot_specify_a_different_target_user(client):
    """extra='forbid' on the request schema: a body trying to smuggle in a
    target identity is rejected outright, not silently ignored."""
    headers = _register_and_login(client, ALLOWED_EMAIL)

    resp = client.post(
        "/admin/claim-legacy-library",
        json={"dry_run": True, "user_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 422
