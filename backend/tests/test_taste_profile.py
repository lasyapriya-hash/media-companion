"""Phase 3 verification: derived taste profile (spec §6.3, FR9).

* profile fields are correct over a seeded library
* every rating change and every status change triggers a recompute
"""
import pytest

from app.schemas.media import NormalizedMedia


def _item(**over):
    base = dict(
        source="tmdb",
        type="movie",
        title="Untitled",
        description="x",
        genres=["Drama"],
        language="en",
        year=2010,
        external_rating=7.0,
        runtime_minutes=120,
    )
    base.update(over)
    return NormalizedMedia(**base).model_dump()


def _add(client, **over):
    resp = client.post("/library", json={"item": _item(**over)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_library(client):
    """A small library with a known shape (see assertions in the test)."""
    a = _add(client, source_id="A", genres=["Action", "Science Fiction"], language="en")
    b = _add(client, source_id="B", genres=["Drama"], language="en")
    c = _add(client, source_id="C", type="series", genres=["Drama"], language="ko",
             seasons=2, episodes=16, episode_runtime_minutes=45)
    _add(client, source_id="D", type="book", genres=["Fantasy"], language="eng",
         page_count=300)
    e = _add(client, source_id="E", genres=["Horror"], language="en")
    f = _add(client, source_id="F", genres=["Horror"], language="en")

    client.patch(f"/library/{a}", json={"status": "completed", "rating": 9.0})
    client.patch(f"/library/{b}", json={"status": "dropped", "rating": 4.0})
    client.patch(f"/library/{c}", json={"status": "completed", "rating": 8.0,
                                        "favourite": True})
    client.patch(f"/library/{e}", json={"status": "dropped", "rating": 3.0})
    client.patch(f"/library/{f}", json={"status": "dropped"})


def test_profile_fields_correct_over_seeded_library(client):
    _seed_library(client)
    p = client.get("/taste-profile").json()

    # completed = {A, C}; dropped = {B, E, F} -> 2 / 5
    assert p["completion_rate"] == pytest.approx(0.4)

    # score = count(completed) + count(favourite); zero-score labels dropped.
    # Drama: completed(C)=1 + favourite(C)=1 -> 2 ; Action/SciFi: 1 each (avg 9.0)
    assert p["favourite_genres"] == ["Drama", "Action", "Science Fiction"]
    # ko: completed(C)=1 + favourite(C)=1 -> 2 ; en: completed(A)=1 -> 1
    assert p["favourite_languages"] == ["ko", "en"]

    assert p["avg_rating_by_genre"]["Drama"] == pytest.approx(6.0)  # (4.0 + 8.0)/2
    assert p["avg_rating_by_genre"]["Action"] == pytest.approx(9.0)
    assert "Fantasy" not in p["avg_rating_by_genre"]  # never rated
    assert p["avg_rating_by_language"]["ko"] == pytest.approx(8.0)
    assert p["avg_rating_by_language"]["en"] == pytest.approx(5.33)  # (9+4+3)/3

    assert p["completion_rate_by_genre"]["Horror"] == pytest.approx(0.0)
    assert p["completion_rate_by_genre"]["Drama"] == pytest.approx(0.5)
    assert "Fantasy" not in p["completion_rate_by_genre"]  # nothing decided

    # Horror: 0 completed / 2 decided -> below threshold, enough sample.
    assert "Horror" in p["drop_patterns"]
    # Fantasy has only a `want` item -> never a drop pattern.
    assert "Fantasy" not in p["drop_patterns"]

    assert p["computed_at"] is not None


def test_empty_library_has_neutral_profile(client):
    p = client.get("/taste-profile").json()
    assert p["favourite_genres"] == []
    assert p["favourite_languages"] == []
    assert p["avg_rating_by_genre"] == {}
    assert p["completion_rate"] is None
    assert p["drop_patterns"] == []


def test_only_want_items_stay_neutral(client):
    _add(client, source_id="W1", genres=["Drama"])
    _add(client, source_id="W2", genres=["Comedy"])
    p = client.get("/taste-profile").json()
    assert p["favourite_genres"] == []
    assert p["completion_rate"] is None


def test_status_change_triggers_recompute(client, monkeypatch):
    calls: list[str] = []
    import app.services.taste_profile as tp

    real_recompute = tp.recompute
    monkeypatch.setattr(
        "app.services.library.taste_profile.recompute",
        lambda db: calls.append("x") or real_recompute(db),
    )

    entry_id = _add(client, source_id="S1", genres=["Thriller"])
    calls.clear()  # ignore the add-time recompute

    client.patch(f"/library/{entry_id}", json={"status": "completed"})
    assert calls, "status change did not recompute the taste profile"

    p = client.get("/taste-profile").json()
    assert "Thriller" in p["favourite_genres"]


def test_rating_change_triggers_recompute(client, monkeypatch):
    calls: list[str] = []
    import app.services.taste_profile as tp

    real_recompute = tp.recompute
    monkeypatch.setattr(
        "app.services.library.taste_profile.recompute",
        lambda db: calls.append("x") or real_recompute(db),
    )

    entry_id = _add(client, source_id="R1", genres=["Mystery"], language="fr")
    client.patch(f"/library/{entry_id}", json={"status": "completed"})
    calls.clear()

    client.patch(f"/library/{entry_id}", json={"rating": 7.5})
    assert calls, "rating change did not recompute the taste profile"

    p = client.get("/taste-profile").json()
    assert p["avg_rating_by_genre"]["Mystery"] == pytest.approx(7.5)


def test_review_only_change_does_not_recompute(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "app.services.library.taste_profile.recompute",
        lambda db: calls.append("x"),
    )
    entry_id = _add(client, source_id="RV1")
    calls.clear()

    client.patch(f"/library/{entry_id}", json={"review": "some notes"})
    assert not calls, "a review-only edit should not recompute the profile"
