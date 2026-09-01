"""`GET /media/details` — read-only enrichment for the Discover / Recommend
preview (spec §5.2, §6.1). TMDb list rows omit runtime & season/episode counts;
this endpoint fetches them via the same details call `library._enrich` uses.
"""
from __future__ import annotations

from app.schemas.media import NormalizedMedia


def _movie_details(**over):
    base = dict(
        source="tmdb", source_id="27205", type="movie", title="Inception",
        genres=["Action"], language="en", year=2010, external_rating=8.4,
        runtime_minutes=148,
    )
    base.update(over)
    return NormalizedMedia(**base)


def _series_details(**over):
    base = dict(
        source="tmdb", source_id="1396", type="series", title="Breaking Bad",
        genres=["Drama"], language="en", year=2008, external_rating=8.9,
        seasons=5, episodes=62, episode_runtime_minutes=47,
    )
    base.update(over)
    return NormalizedMedia(**base)


def test_movie_details_returns_runtime(client, monkeypatch):
    class FakeTMDb:
        def get_details(self, source_id, media_type):
            assert (source_id, media_type) == ("27205", "movie")
            return _movie_details()

    monkeypatch.setattr("app.api.media.tmdb_client", lambda: FakeTMDb())
    resp = client.get(
        "/media/details", params={"source": "tmdb", "source_id": "27205", "type": "movie"}
    )
    assert resp.status_code == 200
    assert resp.json()["runtime_minutes"] == 148


def test_series_details_returns_season_and_episode_counts(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.media.tmdb_client",
        lambda: type("F", (), {"get_details": lambda self, s, m: _series_details()})(),
    )
    resp = client.get(
        "/media/details", params={"source": "tmdb", "source_id": "1396", "type": "series"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["seasons"] == 5 and body["episodes"] == 62


def test_details_never_invents_missing_values(client, monkeypatch):
    """A details payload with no runtime must come back as null, not a guess."""
    monkeypatch.setattr(
        "app.api.media.tmdb_client",
        lambda: type(
            "F", (), {"get_details": lambda self, s, m: _movie_details(runtime_minutes=None)}
        )(),
    )
    resp = client.get(
        "/media/details", params={"source": "tmdb", "source_id": "27205", "type": "movie"}
    )
    assert resp.status_code == 200
    assert resp.json()["runtime_minutes"] is None


def test_details_upstream_failure_is_502_not_500(client, monkeypatch):
    def boom():
        raise RuntimeError("tmdb down")

    monkeypatch.setattr(
        "app.api.media.tmdb_client",
        lambda: type("F", (), {"get_details": lambda self, s, m: boom()})(),
    )
    resp = client.get(
        "/media/details", params={"source": "tmdb", "source_id": "1", "type": "movie"}
    )
    assert resp.status_code == 502


def test_details_unsupported_source_is_400(client):
    resp = client.get(
        "/media/details",
        params={"source": "google_books", "source_id": "x", "type": "book"},
    )
    assert resp.status_code == 400
