"""Phase 2 verification: search + library CRUD (spec FR1, FR2; acceptance §16).

Phase 8.2 (spec §6.1): the `client` fixture auto-authenticates as a default
user (see conftest.py), so every test above this point already exercises the
authenticated path. The block at the bottom of this file covers what that
default-user coverage can't: unauthenticated rejection and cross-user
isolation/duplicate behavior, using a raw unauthenticated client and a second
distinct user.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.media import NormalizedMedia
from tests.conftest import register_and_login


def _movie(**over):
    base = dict(
        source="tmdb",
        source_id="27205",
        type="movie",
        title="Inception",
        description="A thief who steals corporate secrets.",
        genres=["Action", "Science Fiction"],
        language="en",
        year=2010,
        external_rating=8.4,
        runtime_minutes=148,
    )
    base.update(over)
    return NormalizedMedia(**base).model_dump()


def _series(**over):
    base = dict(
        source="tmdb",
        source_id="1396",
        type="series",
        title="Breaking Bad",
        description="A chemistry teacher turns to crime.",
        genres=["Drama"],
        language="en",
        year=2008,
        external_rating=8.9,
        seasons=5,
        episodes=62,
        episode_runtime_minutes=47,
    )
    base.update(over)
    return NormalizedMedia(**base).model_dump()


def _book(**over):
    base = dict(
        source="open_library",
        source_id="OL27482W",
        type="book",
        title="The Hobbit",
        description="Bilbo Baggins goes on an adventure.",
        genres=["Fantasy"],
        language="eng",
        year=1937,
        external_rating=8.6,
        author="J.R.R. Tolkien",
        page_count=310,
    )
    base.update(over)
    return NormalizedMedia(**base).model_dump()


# --------------------------------------------------------------------------- #
# Search endpoint
# --------------------------------------------------------------------------- #
def test_search_endpoint_returns_normalized_results(client, monkeypatch):
    fake_movie = NormalizedMedia(**{**_movie(), "raw_metadata": {}})
    fake_book = NormalizedMedia(**{**_book(), "raw_metadata": {}})

    class FakeTMDb:
        def search(self, q, media_type=None, limit=20):
            return [fake_movie]

    class FakeOL:
        def search(self, q, limit=20):
            return [fake_book]

    monkeypatch.setattr("app.services.search.tmdb_client", lambda: FakeTMDb())
    monkeypatch.setattr("app.services.search.openlibrary_client", lambda: FakeOL())

    resp = client.get("/search", params={"q": "hobbit"})
    assert resp.status_code == 200
    kinds = {r["type"] for r in resp.json()}
    assert kinds == {"movie", "book"}

    resp = client.get("/search", params={"q": "inception", "type": "movie"})
    assert resp.status_code == 200
    assert all(r["type"] == "movie" for r in resp.json())


def test_search_requires_query(client):
    assert client.get("/search").status_code == 422


# --------------------------------------------------------------------------- #
# Add a movie, a series, and a book (acceptance §16)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload,expected_type",
    [(_movie(), "movie"), (_series(), "series"), (_book(), "book")],
)
def test_add_each_media_type(client, payload, expected_type):
    resp = client.post("/library", json={"item": payload})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "want"
    assert body["media"]["type"] == expected_type
    assert body["media"]["title"] == payload["title"]
    # length_bucket is derived, not stored
    assert body["media"]["length_bucket"] in {"short", "medium", "long"}

    listed = client.get("/library").json()
    assert any(e["media"]["source_id"] == payload["source_id"] for e in listed)


def test_add_series_creates_zero_progress_row(client):
    entry = client.post("/library", json={"item": _series()}).json()
    assert entry["progress"] is not None
    assert entry["progress"]["seasons_completed"] == 0


def test_add_duplicate_returns_409(client):
    assert client.post("/library", json={"item": _book()}).status_code == 201
    assert client.post("/library", json={"item": _book()}).status_code == 409


# --------------------------------------------------------------------------- #
# mood_tags feature check (feature-gated on ANTHROPIC_API_KEY)
# --------------------------------------------------------------------------- #
def test_add_without_anthropic_key_leaves_mood_tags_empty(client):
    entry = client.post("/library", json={"item": _movie()}).json()
    assert entry["media"]["mood_tags"] == []


def test_add_with_classifier_enabled_populates_mood_tags(client, monkeypatch):
    monkeypatch.setattr("app.services.library.mood_tags.is_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.library.mood_tags.classify_mood_tags",
        lambda **kw: ["cerebral", "tense"],
    )
    entry = client.post("/library", json={"item": _movie(source_id="999")}).json()
    assert entry["media"]["mood_tags"] == ["cerebral", "tense"]


# --------------------------------------------------------------------------- #
# Update status / rating / review / favourite (FR2, acceptance §16)
# --------------------------------------------------------------------------- #
def test_update_status_rating_review_favourite(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    resp = client.patch(
        f"/library/{entry_id}",
        json={
            "status": "completed",
            "rating": 8.5,
            "review": "Loved the ending.",
            "favourite": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["rating"] == 8.5
    assert body["review"] == "Loved the ending."
    assert body["favourite"] is True


def test_rating_must_be_half_step_in_range(client):
    entry_id = client.post("/library", json={"item": _book()}).json()["id"]
    assert client.patch(f"/library/{entry_id}", json={"rating": 8.3}).status_code == 422
    assert client.patch(f"/library/{entry_id}", json={"rating": 11}).status_code == 422
    assert client.patch(f"/library/{entry_id}", json={"rating": 7.5}).status_code == 200


def test_rating_can_be_cleared_with_null(client):
    entry_id = client.post("/library", json={"item": _book()}).json()["id"]
    client.patch(f"/library/{entry_id}", json={"rating": 6.0})
    resp = client.patch(f"/library/{entry_id}", json={"rating": None})
    assert resp.status_code == 200
    assert resp.json()["rating"] is None


def test_update_missing_entry_404(client):
    import uuid

    resp = client.patch(f"/library/{uuid.uuid4()}", json={"favourite": True})
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Series progress (acceptance §16)
# --------------------------------------------------------------------------- #
def test_track_series_progress(client):
    entry_id = client.post("/library", json={"item": _series()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress",
        json={"seasons_completed": 2, "current_season": 3, "current_episode": 4},
    )
    assert resp.status_code == 200, resp.text
    prog = resp.json()["progress"]
    assert prog["seasons_completed"] == 2
    assert prog["current_season"] == 3
    assert prog["current_episode"] == 4

    reread = client.get(f"/library/{entry_id}").json()["progress"]
    assert reread["seasons_completed"] == 2


def test_progress_rejected_for_non_series(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress", json={"seasons_completed": 1}
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Progress boundaries + seasons_completed derivation (series progress UX fix)
# --------------------------------------------------------------------------- #
_BB_SEASONS = [
    {"season_number": 0, "name": "Specials", "episode_count": 9},
    {"season_number": 1, "name": "Season 1", "episode_count": 7},
    {"season_number": 2, "name": "Season 2", "episode_count": 13},
    {"season_number": 3, "name": "Season 3", "episode_count": 13},
    {"season_number": 4, "name": "Season 4", "episode_count": 13},
    {"season_number": 5, "name": "Season 5", "episode_count": 16},
]


def _series_with_seasons(**over):
    return _series(season_episode_counts=_BB_SEASONS, **over)


def test_seasons_completed_is_derived_from_current_season(client):
    """Sending current_season always recomputes seasons_completed = season - 1,
    regardless of any (even wrong) seasons_completed the caller also sends."""
    entry_id = client.post("/library", json={"item": _series_with_seasons()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress",
        json={"seasons_completed": 99, "current_season": 3, "current_episode": 4},
    )
    assert resp.status_code == 200, resp.text
    prog = resp.json()["progress"]
    assert prog["seasons_completed"] == 2  # derived (3 - 1), NOT the sent 99
    assert prog["current_season"] == 3
    assert prog["current_episode"] == 4


def test_seasons_completed_direct_update_without_current_season_still_works(client):
    """Back-compat: a caller that never touches current_season keeps the old
    direct-passthrough behavior for seasons_completed."""
    entry_id = client.post("/library", json={"item": _series()}).json()["id"]
    resp = client.put(f"/library/{entry_id}/progress", json={"seasons_completed": 4})
    assert resp.status_code == 200, resp.text
    assert resp.json()["progress"]["seasons_completed"] == 4


def test_episode_beyond_season_count_is_rejected(client):
    entry_id = client.post("/library", json={"item": _series_with_seasons()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 5, "current_episode": 13},  # season 5 has only 16... ok
    )
    assert resp.status_code == 200
    bad = client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 1, "current_episode": 8},  # season 1 has only 7
    )
    assert bad.status_code == 400
    # the earlier valid save must be untouched
    reread = client.get(f"/library/{entry_id}").json()["progress"]
    assert reread["current_season"] == 5 and reread["current_episode"] == 13


def test_season_beyond_series_total_is_rejected(client):
    entry_id = client.post("/library", json={"item": _series_with_seasons()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress", json={"current_season": 6, "current_episode": 1}
    )
    assert resp.status_code == 400


def test_season_zero_is_rejected_for_progress(client):
    """Season 0 ("Specials") is real TMDb data but excluded from progress
    tracking — same aggregate TMDb's own number_of_seasons already excludes."""
    entry_id = client.post("/library", json={"item": _series_with_seasons()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress", json={"current_season": 0, "current_episode": 1}
    )
    assert resp.status_code == 400


def test_episode_only_update_validated_against_existing_season(client):
    entry_id = client.post("/library", json={"item": _series_with_seasons()}).json()["id"]
    client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 2, "current_episode": 1},
    )
    # season 2 has 13 episodes — sending only current_episode must still be
    # checked against the season already on record.
    bad = client.put(f"/library/{entry_id}/progress", json={"current_episode": 20})
    assert bad.status_code == 400
    ok = client.put(f"/library/{entry_id}/progress", json={"current_episode": 13})
    assert ok.status_code == 200


def test_progress_without_season_data_is_not_blocked(client):
    """Legacy/unenriched entries (no season_episode_counts cached) must not be
    hard-blocked — an unverifiable bound is skipped, never fabricated."""
    entry_id = client.post("/library", json={"item": _series()}).json()["id"]
    resp = client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 40, "current_episode": 999},
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Listing + filters
# --------------------------------------------------------------------------- #
def test_list_filters_by_status_and_type(client):
    m_id = client.post("/library", json={"item": _movie()}).json()["id"]
    client.post("/library", json={"item": _book()})
    client.patch(f"/library/{m_id}", json={"status": "completed"})

    by_type = client.get("/library", params={"type": "book"}).json()
    assert by_type and all(e["media"]["type"] == "book" for e in by_type)

    by_status = client.get("/library", params={"status": "completed"}).json()
    assert by_status and all(e["status"] == "completed" for e in by_status)


# --------------------------------------------------------------------------- #
# Remove from collection — DELETE /library/{id}
# --------------------------------------------------------------------------- #
def test_delete_entry_removes_it(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    assert client.get("/library").json()  # present

    resp = client.delete(f"/library/{entry_id}")
    assert resp.status_code == 204
    assert resp.content == b""

    assert client.get("/library").json() == []
    assert client.get(f"/library/{entry_id}").status_code == 404


def test_delete_unknown_entry_is_404(client):
    import uuid

    assert client.delete(f"/library/{uuid.uuid4()}").status_code == 404
    assert client.delete("/library/not-a-uuid").status_code == 422


def test_delete_keeps_media_item_so_it_can_be_readded(client):
    """Deleting the entry must not delete the cached media_item: re-adding the
    same item succeeds (a 409 would mean the media_item + entry still linked)."""
    first = client.post("/library", json={"item": _movie()})
    assert first.status_code == 201
    assert client.delete(f"/library/{first.json()['id']}").status_code == 204

    second = client.post("/library", json={"item": _movie()})
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


def test_delete_series_removes_progress(client):
    entry_id = client.post("/library", json={"item": _series()}).json()["id"]
    client.put(
        f"/library/{entry_id}/progress",
        json={"seasons_completed": 3, "current_season": 4},
    )
    assert client.delete(f"/library/{entry_id}").status_code == 204

    # re-adding starts fresh (a new zero-progress row, not the old one)
    re_id = client.post("/library", json={"item": _series()}).json()["id"]
    prog = client.get(f"/library/{re_id}").json()["progress"]
    assert prog["seasons_completed"] == 0 and prog["current_season"] is None


def test_delete_recomputes_taste_profile(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    client.patch(
        f"/library/{entry_id}", json={"status": "completed", "rating": 9.0}
    )
    assert "Action" in client.get("/taste-profile").json()["favourite_genres"]

    client.delete(f"/library/{entry_id}")
    assert client.get("/taste-profile").json()["favourite_genres"] == []


# --------------------------------------------------------------------------- #
# Phase 8.2: authentication + cross-user ownership (spec §6.1)
# --------------------------------------------------------------------------- #
def test_library_endpoints_reject_unauthenticated_requests(client):
    """Every library route 401s with no bearer token — using a bare TestClient
    that shares the fixture's db override but never got the default user's
    Authorization header attached."""
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]

    with TestClient(app) as anon:
        assert anon.get("/library").status_code == 401
        assert (
            anon.post("/library", json={"item": _movie(source_id="anon-add")}).status_code
            == 401
        )
        assert anon.get(f"/library/{entry_id}").status_code == 401
        assert (
            anon.patch(f"/library/{entry_id}", json={"favourite": True}).status_code
            == 401
        )
        assert (
            anon.put(
                f"/library/{entry_id}/progress", json={"seasons_completed": 1}
            ).status_code
            == 401
        )
        assert anon.delete(f"/library/{entry_id}").status_code == 401


def test_authenticated_request_succeeds(client):
    """Sanity check that the fixture's default user is genuinely authenticated
    (not e.g. accidentally bypassing the dependency)."""
    resp = client.post("/library", json={"item": _movie()})
    assert resp.status_code == 201, resp.text


def test_user_cannot_get_another_users_entry(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    other = register_and_login(client, "isolation-get@example.com")
    assert client.get(f"/library/{entry_id}", headers=other).status_code == 404
    # owner is unaffected
    assert client.get(f"/library/{entry_id}").status_code == 200


def test_user_cannot_patch_another_users_entry(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    other = register_and_login(client, "isolation-patch@example.com")
    resp = client.patch(
        f"/library/{entry_id}", json={"favourite": True}, headers=other
    )
    assert resp.status_code == 404
    # owner's entry was not modified by the other user's attempt
    assert client.get(f"/library/{entry_id}").json()["favourite"] is False


def test_user_cannot_update_progress_on_another_users_entry(client):
    entry_id = client.post("/library", json={"item": _series()}).json()["id"]
    client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 2, "current_episode": 3},
    )
    other = register_and_login(client, "isolation-progress@example.com")
    resp = client.put(
        f"/library/{entry_id}/progress",
        json={"current_season": 5},
        headers=other,
    )
    assert resp.status_code == 404
    # owner's progress is untouched by the other user's attempt
    reread = client.get(f"/library/{entry_id}").json()["progress"]
    assert reread["current_season"] == 2 and reread["current_episode"] == 3


def test_user_cannot_delete_another_users_entry(client):
    entry_id = client.post("/library", json={"item": _movie()}).json()["id"]
    other = register_and_login(client, "isolation-delete@example.com")
    assert client.delete(f"/library/{entry_id}", headers=other).status_code == 404
    # entry still exists for the owner
    assert client.get(f"/library/{entry_id}").status_code == 200


def test_list_only_shows_the_authenticated_users_own_entries(client):
    client.post("/library", json={"item": _movie()})
    other = register_and_login(client, "isolation-list@example.com")
    assert client.get("/library", headers=other).json() == []
    assert len(client.get("/library").json()) >= 1


def test_duplicate_same_user_same_media_still_409(client):
    """Regression: existing same-user duplicate behavior is unchanged by
    per-user scoping."""
    payload = _book(source_id="dup-same-user")
    assert client.post("/library", json={"item": payload}).status_code == 201
    assert client.post("/library", json={"item": payload}).status_code == 409


def test_different_users_can_each_add_the_same_media_sharing_one_media_item(client):
    payload = _movie(source_id="shared-across-users")
    first = client.post("/library", json={"item": payload})
    assert first.status_code == 201

    other = register_and_login(client, "isolation-duplicate@example.com")
    second = client.post("/library", json={"item": payload}, headers=other)
    assert second.status_code == 201, second.text

    # two distinct library entries...
    assert second.json()["id"] != first.json()["id"]
    # ...referencing the exact same underlying media_item, not a duplicate.
    assert second.json()["media"]["id"] == first.json()["media"]["id"]

    # and each user's list only shows their own entry.
    assert len(client.get("/library").json()) == 1
    assert len(client.get("/library", headers=other).json()) == 1


def test_removing_own_entry_still_works_after_another_user_shares_the_media(client):
    """Regression: owner's own DELETE still succeeds normally even once a
    second user also holds an entry for the same media_item."""
    payload = _movie(source_id="shared-then-delete")
    entry_id = client.post("/library", json={"item": payload}).json()["id"]
    other = register_and_login(client, "isolation-remove@example.com")
    client.post("/library", json={"item": payload}, headers=other)

    assert client.delete(f"/library/{entry_id}").status_code == 204
    assert client.get("/library").json() == []
    # the other user's own entry survives untouched
    assert len(client.get("/library", headers=other).json()) == 1
