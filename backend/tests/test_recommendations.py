"""Phase 4 verification: single-turn natural-language recommendations
(spec §5.3, §7, §8.2-8.3, §9; plan Phase 4).

External data sources and the LLM are stubbed; the deterministic engine
(candidate filtering, scoring, ranking, reason text) runs for real.
"""
from __future__ import annotations

import pytest

from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _media(source_id, *, type="movie", title="Untitled", genres=None, language="en",
           year=2018, rating=7.0, source="tmdb", popularity=40.0, description="",
           page_count=None):
    raw = {"popularity": popularity}
    return NormalizedMedia(
        source=source,
        source_id=str(source_id),
        type=type,
        title=title,
        description=description or f"{title} description.",
        genres=genres or [],
        language=language,
        year=year,
        external_rating=rating,
        page_count=page_count,
        raw_metadata=raw,
    )


class FakeClients:
    """Stands in for both `tmdb_client()` and `openlibrary_client()`."""

    def __init__(self, screen=None, books=None, providers=None, fail=False):
        self._screen = screen or []
        self._books = books or []
        self._providers = providers or {}
        self._fail = fail
        self.discover_calls: list[tuple] = []

    # -- TMDb surface -- #
    def discover(self, media_type, *, genres=None, language=None, year_from=None,
                 year_to=None, limit=20):
        if self._fail:
            raise RuntimeError("tmdb down")
        self.discover_calls.append(("tmdb", media_type, tuple(genres or []), language))
        return [m for m in self._screen if m.type == media_type][:limit]

    def get_watch_providers(self, source_id, media_type, region="IN"):
        return self._providers.get(
            str(source_id), WatchAvailability(region="IN", status="unknown")
        )

    # -- Open Library surface -- #
    # (same object; `discover` is dispatched by kwargs shape)
    def ol_discover(self, *, subjects=None, language=None, limit=20):
        if self._fail:
            raise RuntimeError("ol down")
        self.discover_calls.append(("ol", tuple(subjects or []), language))
        return list(self._books[:limit])


@pytest.fixture()
def wire(monkeypatch):
    """Install fake clients + a controllable extractor. Returns a configy setter."""
    state: dict = {"clients": FakeClients(), "extractor": None}

    def tmdb():
        return state["clients"]

    class _OL:
        def discover(self, **kw):
            return state["clients"].ol_discover(**kw)

    def ol():
        return _OL()

    monkeypatch.setattr("app.services.recommendations.candidates.tmdb_client", tmdb)
    monkeypatch.setattr("app.services.recommendations.candidates.openlibrary_client", ol)
    monkeypatch.setattr("app.services.recommendations.tmdb_client", tmdb)
    monkeypatch.setattr(
        "app.services.recommendations.get_extractor", lambda: state["extractor"]
    )
    return state


class SpyExtractor:
    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def extract(self, request_text):
        self.calls.append(request_text)
        return self.result


# --------------------------------------------------------------------------- #
# Core: a free-text request returns a ranked list with request-specific reasons
# --------------------------------------------------------------------------- #
def test_free_text_request_returns_ranked_list_with_reasons(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("A", genres=["Crime", "Thriller"], rating=6.4, title="Cold Ledger"),
            _media("B", genres=["Comedy", "Family"], rating=8.9, title="Sunny Days"),
            _media("C", genres=["Thriller"], rating=7.1, title="Nightcall"),
        ]
    )
    # re-point the fixture's closures at the new clients object
    resp = client.post(
        "/recommendations",
        json={"request": "a dark, tense crime thriller movie"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extraction"] == "fallback"  # LLM disabled in conftest
    assert body["preferences"]["genres"] == ["crime", "thriller"]
    assert len(body["results"]) >= 1
    for item in body["results"]:
        assert isinstance(item["reason"], str) and len(item["reason"]) > 15
        assert item["score"] == pytest.approx(item["score"])  # is a number
    top = body["results"][0]
    assert top["media"]["title"] in {"Cold Ledger", "Nightcall"}
    assert any(
        w in top["reason"].lower() for w in ("crime", "thriller", "dark", "tense")
    )


# --------------------------------------------------------------------------- #
# LLM off -> deterministic fallback still returns a list
# --------------------------------------------------------------------------- #
def test_llm_disabled_still_returns_list_via_fallback(client, wire):
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Drama"]), _media("B", genres=["Drama"])]
    )
    wire["extractor"] = None  # explicit: no LLM
    resp = client.post("/recommendations", json={"request": "a thoughtful drama"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction"] == "fallback"
    assert len(body["results"]) >= 1


# --------------------------------------------------------------------------- #
# Pre-structured `preferences` bypasses the LLM entirely
# --------------------------------------------------------------------------- #
def test_prestructured_preferences_bypass_llm(client, wire):
    spy = SpyExtractor(PreferenceObject(genres=["should-not-be-used"]))
    wire["extractor"] = spy
    wire["clients"] = FakeClients(screen=[_media("A", genres=["Fantasy"])])
    resp = client.post(
        "/recommendations",
        json={"preferences": {"genres": ["Fantasy"], "media_type": ["movie"]}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert spy.calls == []  # LLM never called
    assert body["extraction"] == "fallback"
    assert body["preferences"]["genres"] == ["Fantasy"]
    assert body["results"][0]["media"]["title"]


# --------------------------------------------------------------------------- #
# The LLM call is bounded: exactly one extract(), and only for extraction
# --------------------------------------------------------------------------- #
def test_llm_called_once_and_only_for_extraction(client, wire):
    spy = SpyExtractor(
        PreferenceObject(genres=["Crime"], mood=["tense"], explicit_fields=["genres"])
    )
    wire["extractor"] = spy
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime"]), _media("B", genres=["Crime"])]
    )
    resp = client.post("/recommendations", json={"request": "gritty crime stuff"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction"] == "llm"
    assert len(spy.calls) == 1  # exactly one bounded call
    assert spy.calls[0] == "gritty crime stuff"
    # candidates really were built (deterministic path ran)
    assert any(c[0] == "tmdb" for c in wire["clients"].discover_calls)


def test_gemini_call_config_is_bounded_and_union_free():
    from app.services.llm import gemini

    assert gemini._MAX_OUTPUT_TOKENS <= 1024
    assert gemini._TIMEOUT_MS <= 10_000
    # response schema must be union-free (no anyOf/oneOf) for portability
    dumped = repr(gemini._RESPONSE_SCHEMA)
    assert "anyOf" not in dumped and "oneOf" not in dumped
    assert gemini._RESPONSE_SCHEMA["type"] == "object"


# --------------------------------------------------------------------------- #
# "Not highest-rated" guarantee (spec §9.3)
# --------------------------------------------------------------------------- #
def test_not_highest_rated_when_mood_conflicts(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("TOP", genres=["Animation", "Family"], rating=9.6, popularity=190.0,
                   title="Happy Meadow", description="A wholesome feel-good romp."),
            _media("M1", genres=["Crime", "Thriller"], rating=6.6, popularity=25.0,
                   title="Ash & Iron", description="A bleak, violent descent."),
            _media("M2", genres=["Thriller"], rating=7.0, popularity=30.0,
                   title="The Undertow", description="Tense and grim."),
        ]
    )
    resp = client.post(
        "/recommendations",
        json={"request": "something really dark and tense, crime and violence"},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results, "expected a non-empty list"
    assert results[0]["media"]["source_id"] != "TOP"  # the 9.6-rated feel-good pick
    assert results[0]["media"]["source_id"] in {"M1", "M2"}


# --------------------------------------------------------------------------- #
# Movie/series ranking uses the taste profile
# --------------------------------------------------------------------------- #
def test_movie_ranking_uses_taste_profile(client, wire):
    # Build a taste profile that strongly favours Drama.
    for i, (genres, rating) in enumerate(
        [(["Drama"], 9.0), (["Drama"], 9.5), (["Western"], 3.0)]
    ):
        m = _media(f"seed{i}", genres=genres)
        client.post("/library", json={"item": m.model_dump()})
    lib = client.get("/library").json()
    for entry in lib:
        client.patch(
            f"/library/{entry['id']}",
            json={"status": "completed", "rating": 9.0 if "Drama" in entry["media"]["genres"] else 3.0},
        )

    wire["clients"] = FakeClients(
        screen=[
            _media("DR", genres=["Drama"], rating=7.0, title="Quiet Harbor"),
            _media("WE", genres=["Western"], rating=7.0, title="Dust Road"),
        ]
    )
    # Sparse request -> one clarifying question; a declined answer proceeds to
    # ranking, which then leans on the taste profile (spec §8.3).
    q = client.post("/recommendations", json={"request": "something to watch"}).json()
    assert q["state"] == "needs_clarification"
    body = client.post(
        f"/recommendations/{q['session_id']}/answer", json={"answer": ""}
    ).json()
    assert body["state"] == "results"
    assert body["results"][0]["media"]["source_id"] == "DR"
    # taste-driven candidate query carried the favourite genre
    assert any(
        "Drama" in call[2] for call in wire["clients"].discover_calls if call[0] == "tmdb"
    )


# --------------------------------------------------------------------------- #
# Books ranked by genre / mood-tag overlap (spec §9.2)
# --------------------------------------------------------------------------- #
def test_books_ranked_by_overlap(client, wire):
    wire["clients"] = FakeClients(
        books=[
            _media("bk1", source="open_library", type="book", genres=["Fantasy"],
                   title="Elderwood", rating=6.0, page_count=300),
            _media("bk2", source="open_library", type="book", genres=["Romance"],
                   title="Paper Hearts", rating=9.2, page_count=300),
        ]
    )
    resp = client.post(
        "/recommendations", json={"request": "an escapist fantasy book"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preferences"]["media_type"] == ["book"]
    assert body["results"][0]["media"]["source_id"] == "bk1"  # genre overlap beats rating
    assert body["results"][0]["availability"] is None
    assert body["results"][0]["book_link"] is None  # no ebook_access -> omitted


# --------------------------------------------------------------------------- #
# Availability: provider data vs clean "unknown" (spec §5.4, FR7)
# --------------------------------------------------------------------------- #
def test_availability_shown_or_unknown(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("has", genres=["Drama"], title="Streamable"),
            _media("none", genres=["Drama"], title="Obscure"),
        ],
        providers={
            "has": WatchAvailability(
                region="IN", status="available", flatrate=["Netflix"]
            ),
        },
    )
    resp = client.post("/recommendations", json={"request": "a drama film"})
    assert resp.status_code == 200
    by_id = {r["media"]["source_id"]: r for r in resp.json()["results"]}
    assert by_id["has"]["availability"]["status"] == "available"
    assert by_id["has"]["availability"]["flatrate"] == ["Netflix"]
    assert by_id["none"]["availability"]["status"] == "unknown"


# --------------------------------------------------------------------------- #
# `avoid` is a hard filter (spec §7)
# --------------------------------------------------------------------------- #
def test_avoid_is_a_hard_filter(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("keep", genres=["Comedy"], title="Light Fare"),
            _media("drop", genres=["Horror"], title="The Cellar"),
        ]
    )
    resp = client.post(
        "/recommendations", json={"request": "a fun comedy movie, no horror"}
    )
    assert resp.status_code == 200
    ids = {r["media"]["source_id"] for r in resp.json()["results"]}
    assert "drop" not in ids and "keep" in ids


# --------------------------------------------------------------------------- #
# Completed / dropped library items are excluded (spec §9)
# --------------------------------------------------------------------------- #
def test_completed_library_items_excluded(client, wire):
    seen = _media("SEEN", genres=["Drama"], title="Already Watched")
    entry = client.post("/library", json={"item": seen.model_dump()}).json()
    client.patch(f"/library/{entry['id']}", json={"status": "completed"})

    wire["clients"] = FakeClients(
        screen=[seen, _media("NEW", genres=["Drama"], title="Fresh")]
    )
    resp = client.post("/recommendations", json={"request": "a drama movie"})
    assert resp.status_code == 200
    ids = {r["media"]["source_id"] for r in resp.json()["results"]}
    assert "SEEN" not in ids
    assert "NEW" in ids


# --------------------------------------------------------------------------- #
# Reasons: no placeholder text, and request-specific
# --------------------------------------------------------------------------- #
def test_reasons_are_clean_and_specific(client, wire):
    wire["clients"] = FakeClients(
        screen=[_media("A", genres=["Crime", "Thriller"], title="Cold Ledger")]
    )
    resp = client.post(
        "/recommendations", json={"request": "a tense crime thriller"}
    )
    reasons = [r["reason"] for r in resp.json()["results"]]
    assert reasons
    for reason in reasons:
        low = reason.lower()
        assert not any(bad in low for bad in ("lorem", "ipsum", "todo", "placeholder"))
    assert any(
        any(w in r.lower() for w in ("crime", "thriller", "tense")) for r in reasons
    )


# --------------------------------------------------------------------------- #
# All data sources down -> graceful 503 (spec §8.2 / NFR2)
# --------------------------------------------------------------------------- #
def test_all_sources_down_returns_503(client, wire):
    wire["clients"] = FakeClients(fail=True)
    resp = client.post("/recommendations", json={"request": "an action movie"})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# Request validation
# --------------------------------------------------------------------------- #
def test_empty_request_is_422(client, wire):
    assert client.post("/recommendations", json={}).status_code == 422
    assert client.post("/recommendations", json={"request": "   "}).status_code == 422
