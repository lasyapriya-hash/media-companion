"""Phase 4 verification: single-turn natural-language recommendations
(spec §5.3, §7, §8.2-8.3, §9; plan Phase 4).

External data sources and the LLM are stubbed; the deterministic engine
(candidate filtering, scoring, ranking, reason text) runs for real.
"""
from __future__ import annotations

import pytest

from app.schemas.media import NormalizedMedia, WatchAvailability
from app.schemas.preference import PreferenceObject
from app.services.llm.base import GeminiRecommendation, GeminiSuggestion


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

    def __init__(self, screen=None, books=None, providers=None, fail=False,
                 search_results=None):
        self._screen = screen or []
        self._books = books or []
        self._providers = providers or {}
        self._fail = fail
        # Gemini-pipeline resolution: exact suggestion title -> search results.
        self._search_results = search_results or {}
        self.discover_calls: list[tuple] = []
        self.search_calls: list[tuple] = []

    # -- TMDb surface -- #
    def discover(self, media_type, *, genres=None, language=None, year_from=None,
                 year_to=None, rating_gte=None, limit=20):
        if self._fail:
            raise RuntimeError("tmdb down")
        self.discover_calls.append(
            ("tmdb", media_type, tuple(genres or []), language, rating_gte)
        )
        return [m for m in self._screen if m.type == media_type][:limit]

    def search(self, query, media_type=None, limit=10):
        if self._fail:
            raise RuntimeError("tmdb down")
        self.search_calls.append(("tmdb_search", query, media_type))
        results = self._search_results.get(query, [])
        if media_type:
            results = [m for m in results if m.type == media_type]
        return list(results[:limit])

    def get_watch_providers(self, source_id, media_type, region="IN"):
        return self._providers.get(
            str(source_id), WatchAvailability(region="IN", status="unknown")
        )

    # -- Open Library / Google Books surface -- #
    # (same object; `discover`/`search` are dispatched by kwargs shape)
    def ol_discover(self, *, subjects=None, language=None, limit=20):
        if self._fail:
            raise RuntimeError("ol down")
        self.discover_calls.append(("ol", tuple(subjects or []), language))
        return list(self._books[:limit])

    def ol_search(self, query, limit=10):
        if self._fail:
            raise RuntimeError("ol down")
        self.search_calls.append(("ol_search", query, "book"))
        return list(self._search_results.get(query, [])[:limit])

    def gb_discover(self, *, subjects=None, language=None, limit=20):
        if self._fail:
            raise RuntimeError("google books down")
        self.discover_calls.append(("gb", tuple(subjects or []), language))
        return list(self._books[:limit])

    def gb_search(self, query, limit=20):
        if self._fail:
            raise RuntimeError("google books down")
        return list(self._books[:limit])


class SpyRecommender:
    """Fake `GeminiRecommender`: returns a fixed `GeminiRecommendation` (or
    `None`, to simulate Gemini failing) and records every call."""

    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def recommend(self, request_text, *, taste_context=""):
        self.calls.append(request_text)
        return self.result


@pytest.fixture()
def wire(monkeypatch):
    """Install fake clients + a controllable extractor/recommender."""
    state: dict = {"clients": FakeClients(), "extractor": None, "recommender": None}

    def tmdb():
        return state["clients"]

    class _OL:
        def discover(self, **kw):
            return state["clients"].ol_discover(**kw)

        def search(self, query, limit=10):
            return state["clients"].ol_search(query, limit)

    class _GB:
        def discover(self, **kw):
            return state["clients"].gb_discover(**kw)

        def search(self, query, limit=20):
            return state["clients"].gb_search(query, limit)

    monkeypatch.setattr("app.services.recommendations.candidates.tmdb_client", tmdb)
    monkeypatch.setattr(
        "app.services.recommendations.candidates.openlibrary_client", lambda: _OL()
    )
    monkeypatch.setattr(
        "app.services.recommendations.candidates.google_books_client", lambda: _GB()
    )
    monkeypatch.setattr("app.services.recommendations.tmdb_client", tmdb)
    monkeypatch.setattr("app.services.recommendations.gemini_pipeline.tmdb_client", tmdb)
    monkeypatch.setattr(
        "app.services.recommendations.gemini_pipeline.openlibrary_client", lambda: _OL()
    )
    monkeypatch.setattr(
        "app.services.recommendations.gemini_pipeline.google_books_client", lambda: _GB()
    )
    # `get_extractor`/`GeminiExtractor` are no longer called by the live
    # orchestrator (Phase 9: `get_recommender` is the primary path) — kept
    # importable for `test_llm_extraction.py`'s direct unit tests, but there is
    # nothing in this module's namespace to patch any more.
    monkeypatch.setattr(
        "app.services.recommendations.get_recommender", lambda: state["recommender"]
    )
    return state


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
    wire["recommender"] = None  # explicit: no LLM (also the fixture default)
    resp = client.post("/recommendations", json={"request": "a thoughtful drama"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction"] == "fallback"
    assert len(body["results"]) >= 1


# --------------------------------------------------------------------------- #
# Pre-structured `preferences` bypasses the LLM entirely
# --------------------------------------------------------------------------- #
def test_prestructured_preferences_bypass_llm(client, wire):
    spy = SpyRecommender(GeminiRecommendation(
        preferences=PreferenceObject(genres=["should-not-be-used"]), suggestions=[]
    ))
    wire["recommender"] = spy
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
# The Gemini call is bounded: exactly one recommend() (Phase 9), and
# suggestions are resolved via TMDb `search`, never `discover`.
# --------------------------------------------------------------------------- #
def test_gemini_recommend_called_once_and_resolves_via_search(client, wire):
    cold_ledger = _media("A", genres=["Crime"], title="Cold Ledger", rating=7.2)
    spy = SpyRecommender(GeminiRecommendation(
        preferences=PreferenceObject(genres=["Crime"], explicit_fields=["genres"]),
        suggestions=[
            GeminiSuggestion(
                title="Cold Ledger", media_type="movie", year=2018,
                reason="A gritty, tense crime drama.",
            ),
        ],
    ))
    wire["recommender"] = spy
    wire["clients"] = FakeClients(
        screen=[_media("B", genres=["Crime"])],  # would only appear via the OLD path
        search_results={"Cold Ledger": [cold_ledger]},
    )
    resp = client.post("/recommendations", json={"request": "gritty crime stuff"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction"] == "llm"
    assert len(spy.calls) == 1  # exactly one bounded call
    assert spy.calls[0] == "gritty crime stuff"
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"A"}  # resolved via search — "B" (discover-only) never entered
    assert body["results"][0]["reason"] == "A gritty, tense crime drama."
    # resolution used `.search()`, never the old `.discover()` query
    assert wire["clients"].search_calls == [("tmdb_search", "Cold Ledger", "movie")]
    assert wire["clients"].discover_calls == []


def test_gemini_call_config_is_bounded_and_union_free():
    from app.services.llm import gemini

    assert gemini._MAX_OUTPUT_TOKENS <= 1024
    # Gemini enforces its own minimum request deadline of 10s — a timeout below
    # that fails every call with 400 INVALID_ARGUMENT regardless of network
    # conditions (the Phase 8 fix bug). "Bounded" (spec §10: "one short
    # timeout") means clearing that floor while staying short, not racing it.
    assert 10_000 <= gemini._TIMEOUT_MS <= 15_000
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


# --------------------------------------------------------------------------- #
# Mood/tone must actually match the request (regression: "pleasant" -> horror)
# --------------------------------------------------------------------------- #
def test_pleasant_request_ranks_feelgood_above_horror(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("FG", genres=["Family", "Comedy"], rating=8.0, popularity=45.0,
                   title="Sunny Lane", description="A warm, gentle small-town story."),
            _media("HR", genres=["Horror"], rating=6.0, popularity=95.0,
                   title="The Cellar", description="A malevolent presence in the walls."),
        ]
    )
    resp = client.post("/recommendations", json={"request": "a pleasant movie"})
    assert resp.status_code == 200
    body = resp.json()
    # "pleasant" now canonicalises to feel-good/light -> sufficient, no question
    assert body["state"] == "results"
    p = body["preferences"]
    assert (set(p["mood"]) | set(p["tone"])) & {"feel-good", "uplifting", "light"}
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "FG"
    assert ids.index("FG") < ids.index("HR")


def test_dark_horror_request_still_favours_horror(client, wire):
    """Negative polarity must not regress. "horror" is stated outright, so it is
    now a HARD genre constraint: the cheerful Family/Comedy title is filtered
    out entirely, not merely out-ranked."""
    wire["clients"] = FakeClients(
        screen=[
            _media("HR", genres=["Horror", "Thriller"], rating=6.4, popularity=50.0,
                   title="Nightshade", description="A dark, dread-soaked descent."),
            _media("FG", genres=["Family", "Comedy"], rating=8.3, popularity=50.0,
                   title="Bright Meadow", description="A cheerful, sunny romp."),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a dark horror movie"}
    ).json()
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "HR"
    assert "FG" not in ids  # explicit-genre hard filter removed the family romp


def test_blank_request_ranks_reasonable_above_obscure(client, wire):
    """No preference + no taste signal: novelty must not invert quality."""
    wire["clients"] = FakeClients(
        screen=[
            _media("REASONABLE", genres=["Drama"], rating=8.1, popularity=60.0,
                   title="Well Regarded"),
            _media("OBSCURE", genres=["Horror"], rating=5.2, popularity=8.0,
                   title="Forgotten Reel"),
        ]
    )
    body = client.post("/recommendations", json={"preferences": {}}).json()
    assert body["state"] == "results"
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "REASONABLE"  # not the obscure/low-rated horror


# --------------------------------------------------------------------------- #
# Hard constraints: explicit rating bound + explicit genre FILTER, never rank
# (spec §7). Regression for "comedy rated above 7.5" -> 6.3 movie.
# --------------------------------------------------------------------------- #
def test_rating_bound_filters_out_violators(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            # violates "above 7.5" — must be removed, not merely down-ranked,
            # even though it is the more novel / lower-profile pick
            _media("LOW", genres=["Comedy"], rating=6.3, popularity=8.0,
                   title="Animals", description="A scrappy low-key comedy."),
            _media("OK", genres=["Comedy"], rating=8.1, popularity=70.0,
                   title="Bright Room", description="A warm, sharp comedy."),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a comedy movie rated above 7.5"}
    ).json()
    assert body["state"] == "results"
    rc = body["preferences"]["rating"]
    assert rc and rc["gt"] == 7.5  # exclusive bound survived extraction
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids == ["OK"]
    assert "LOW" not in ids
    # "Why this" may only claim the bound for a candidate that meets it
    assert "7.5" in body["results"][0]["reason"]


def test_rating_bound_at_least_is_inclusive(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("EXACT", genres=["Drama"], rating=8.0, title="On The Line"),
            _media("UNDER", genres=["Drama"], rating=7.9, title="Just Short"),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a drama movie rated at least 8"}
    ).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "EXACT" in ids and "UNDER" not in ids  # >= keeps the boundary value


def test_romantic_movie_is_content_not_just_mood(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("ROM", genres=["Romance", "Drama"], rating=7.4, popularity=40.0,
                   title="Two Trains", description="A tender long-distance romance."),
            _media("HOR", genres=["Horror", "Thriller"], rating=7.2, popularity=90.0,
                   title="The Vestibule", description="A dread-soaked haunting."),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a romantic movie"}
    ).json()
    p = body["preferences"]
    assert "romance" in p["genres"]  # content signal, not only mood
    assert "romantic" in p["mood"]
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "HOR" not in ids  # explicit-genre hard filter drops the horror pick
    assert "ROM" in ids


def test_romantic_rated_bound_filters_below_threshold(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("GOOD", genres=["Romance"], rating=7.9, title="Paper Boats"),
            _media("LOW", genres=["Romance"], rating=6.2, title="Shape Of My Heart"),
        ]
    )
    body = client.post(
        "/recommendations",
        json={"request": "a romantic movie rated above 7.5"},
    ).json()
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids == ["GOOD"]  # the 6.2 romance is filtered, not just ranked lower


def test_cozy_romantic_drama_rated_all_constraints_survive(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("HIT", genres=["Romance", "Drama"], rating=8.2, popularity=30.0,
                   title="Slow Light", description="A cosy, tender romance."),
            _media("RATE_FAIL", genres=["Romance", "Drama"], rating=6.2,
                   title="Hotel Desire", description="A steamy chamber romance."),
            _media("GENRE_FAIL", genres=["Action"], rating=8.6, title="Blast Radius"),
        ]
    )
    body = client.post(
        "/recommendations",
        json={"request": "a cozy romantic drama movie which has rating above 7.5"},
    ).json()
    p = body["preferences"]
    assert {"romance", "drama"} <= set(p["genres"])
    assert p["rating"]["gt"] == 7.5
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids == ["HIT"]
    assert "RATE_FAIL" not in ids and "GENRE_FAIL" not in ids


def test_wholesome_love_story_keeps_romance_content(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("LOVE", genres=["Romance"], rating=7.6, popularity=25.0,
                   title="The Long Way", description="A gentle small-town love story."),
            # wholesome + uplifting but NOT a love story -> must not satisfy it
            _media("FAMILY", genres=["Family", "Animation"], rating=8.4,
                   popularity=120.0, title="Moana",
                   description="A spirited voyager saves her island."),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a wholesome love story"}
    ).json()
    p = body["preferences"]
    assert "romance" in p["genres"]
    assert "wholesome" in p["mood"] and "uplifting" in p["tone"]
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "LOVE" in ids
    assert "FAMILY" not in ids  # Family/uplifting alone is not a "love story"


def test_not_scary_negative_constraint_unchanged(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("SAFE", genres=["Comedy", "Family"], rating=7.0, title="Warm Bread"),
            _media("SCARY", genres=["Horror"], rating=7.0, title="The Attic"),
        ]
    )
    # "a fun movie which is not scary" — non-sparse (mood: fun), avoid: scary.
    body = client.post(
        "/recommendations",
        json={"request": "a fun movie which is not scary"},
    ).json()
    assert body["state"] == "results"
    assert "tense" in body["preferences"]["avoid"]  # "scary" -> canonical avoid
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "SCARY" not in ids and "SAFE" in ids


def test_surprise_me_still_reasonable(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("A", genres=["Drama"], rating=8.0, popularity=60.0, title="Anchor"),
            _media("B", genres=["Drama"], rating=7.5, popularity=40.0, title="Barge"),
        ]
    )
    body = client.post("/recommendations", json={"preferences": {}}).json()
    assert body["state"] == "results"
    assert len(body["results"]) >= 1
    assert body["preferences"].get("rating") is None


def test_unsatisfiable_rating_bound_returns_empty_not_a_violation(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("A", genres=["Comedy"], rating=6.0, title="Middling"),
            _media("B", genres=["Comedy"], rating=5.5, title="Lesser"),
        ]
    )
    resp = client.post(
        "/recommendations", json={"request": "a comedy movie rated above 9"}
    )
    assert resp.status_code == 200  # graceful, not a 503
    body = resp.json()
    assert body["state"] == "results"
    assert body["results"] == []  # no violator is ever substituted in


def test_zero_signal_scoring_uses_quality_prior_not_novelty():
    """Component-level: with pref_match == 0 and taste_match == 0, a better-rated
    candidate must outscore an obscure low-rated one (spec §9.1/§9.3)."""
    from app.models.taste import TasteProfile
    from app.services.recommendations.scoring import score_candidate

    prefs = PreferenceObject()  # nothing at all
    taste = TasteProfile(id=1, favourite_genres=[], favourite_languages=[])
    good = _media("good", genres=["Drama"], rating=8.0, popularity=50.0)
    obscure = _media("obscure", genres=["Drama"], rating=5.0, popularity=6.0)

    sg = score_candidate(good, prefs, taste)
    so = score_candidate(obscure, prefs, taste)
    assert sg.explanation.any_preference_signal() is False
    assert sg.score > so.score


# --------------------------------------------------------------------------- #
# Novelty/ranking fix regression (spec §9.1/§9.3): once preference_match
# saturates for a whole genre+language cohort, a strong external rating must
# never be actively penalised by the novelty term. Component-level coverage is
# in test_novelty_scoring.py; these exercise the same fix end-to-end via the
# API, across the request shapes named in the diagnosis.
# --------------------------------------------------------------------------- #
def test_telugu_love_story_surfaces_quality_pick(client, wire):
    """Regression for the diagnosed case: real TMDb rating/popularity values
    for a Telugu-romance cohort where every candidate matches genre+language
    identically. The well-reviewed pick must be the top result, not buried
    behind lower-rated peers."""
    wire["clients"] = FakeClients(
        screen=[
            _media("SITA", genres=["Romance", "Drama", "History"], rating=7.829,
                   popularity=4.137, language="te", title="Sita Ramam"),
            _media("LOW1", genres=["Romance", "Drama"], rating=3.0, popularity=3.0,
                   language="te", title="Madhura Wines"),
            _media("LOW2", genres=["Romance", "Drama"], rating=4.0, popularity=3.1,
                   language="te", title="Deewana"),
            _media("MID", genres=["Romance", "Drama"], rating=5.8, popularity=3.3,
                   language="te", title="RDX Love"),
        ]
    )
    body = client.post("/recommendations", json={"request": "Telugu love story"}).json()
    assert body["extraction"] == "fallback"  # LLM disabled in conftest
    p = body["preferences"]
    assert "romance" in p["genres"] and p["language"] == ["telugu"]
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "SITA"


def test_romantic_movie_prefers_better_reviewed_match(client, wire):
    """Extends test_romantic_movie_is_content_not_just_mood: among candidates
    that already pass the hard genre filter, the higher-rated one must rank
    first, not last."""
    wire["clients"] = FakeClients(
        screen=[
            _media("GOOD", genres=["Romance", "Drama"], rating=8.4, popularity=30.0,
                   title="Two Trains", description="A tender long-distance romance."),
            _media("MEH", genres=["Romance", "Drama"], rating=4.1, popularity=28.0,
                   title="Faded Letters", description="A forgettable romance."),
        ]
    )
    body = client.post("/recommendations", json={"request": "a romantic movie"}).json()
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "GOOD"


def test_rating_threshold_request_orders_survivors_by_quality(client, wire):
    """Rating bound stays a hard filter (violator dropped), and among the
    survivors that clear it, the novelty fix must not still prefer the
    lower-rated one."""
    wire["clients"] = FakeClients(
        screen=[
            _media("VIOLATOR", genres=["Comedy"], rating=6.9, popularity=20.0,
                   title="Below The Bar"),
            _media("BARELY", genres=["Comedy"], rating=7.6, popularity=15.0,
                   title="Just Clears It"),
            _media("STRONG", genres=["Comedy"], rating=9.1, popularity=18.0,
                   title="Clear Winner"),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a comedy movie rated above 7.5"}
    ).json()
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert "VIOLATOR" not in ids  # hard filter unaffected by the scoring fix
    assert ids[0] == "STRONG"  # among survivors, quality now orders correctly


def test_fun_not_scary_prefers_higher_rated_safe_pick(client, wire):
    """Extends test_not_scary_negative_constraint_unchanged: the avoid-term
    hard filter still drops the scary pick, and among the safe candidates the
    better-rated one now ranks first."""
    wire["clients"] = FakeClients(
        screen=[
            _media("SAFE_GOOD", genres=["Comedy", "Family"], rating=8.2,
                   popularity=25.0, title="Warm Bread"),
            _media("SAFE_MEH", genres=["Comedy", "Family"], rating=4.5,
                   popularity=22.0, title="Stale Loaf"),
            _media("SCARY", genres=["Horror"], rating=8.9, popularity=90.0,
                   title="The Attic"),
        ]
    )
    body = client.post(
        "/recommendations", json={"request": "a fun movie which is not scary"}
    ).json()
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert "SCARY" not in ids
    assert ids[0] == "SAFE_GOOD"


def test_surprise_me_still_prefers_quality_over_obscurity(client, wire):
    """"Surprise me" (no preferences at all) must keep favouring a well-
    reviewed pick over a merely-obscure/low-rated one — the has_signal=False
    branch was already correct and must remain untouched by the novelty fix."""
    wire["clients"] = FakeClients(
        screen=[
            _media("QUALITY", genres=["Drama"], rating=8.7, popularity=45.0,
                   title="Well Regarded"),
            _media("OBSCURE", genres=["Horror"], rating=4.9, popularity=7.0,
                   title="Forgotten Reel"),
        ]
    )
    body = client.post("/recommendations", json={"preferences": {}}).json()
    assert body["state"] == "results"
    ids = [r["media"]["source_id"] for r in body["results"]]
    assert ids[0] == "QUALITY"


# --------------------------------------------------------------------------- #
# Language hard-filter fix (spec §7): reported bug — "telugu lovestory movie"
# returned an English candidate because language was only a soft scoring
# signal, never a hard filter. Component-level coverage (matches_explicit_
# language, unresolved-language behavior, build_candidates' screen_langs
# guard) is in test_language_filter.py; these are the end-to-end regressions.
# --------------------------------------------------------------------------- #
def test_explicit_language_rejects_wrong_language_candidate_deterministic_path(client, wire):
    """(A) The exact reported shape on the deterministic fallback: explicit
    Telugu + Romance genre. An English Romance candidate must never survive;
    a Telugu one must. Uses `preferences` directly (Gemini disabled by the
    fixture default) to exercise `_filter_pool`/`matches_explicit_language`
    without depending on how any particular text happens to extract."""
    wire["clients"] = FakeClients(
        screen=[
            _media("EN_ROM", genres=["Romance", "Drama"], language="en", rating=6.6,
                   popularity=198.0, title="The Last Sunrise"),
            _media("TE_ROM", genres=["Romance", "Drama"], language="te", rating=7.8,
                   popularity=4.1, title="Sita Ramam"),
        ]
    )
    body = client.post(
        "/recommendations",
        json={"preferences": {
            "media_type": ["movie"], "genres": ["Romance"], "language": ["Telugu"],
            "explicit_fields": ["media_type", "genres", "language"],
        }},
    ).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "EN_ROM" not in ids
    assert ids == {"TE_ROM"}


def test_explicit_language_rejects_wrong_language_gemini_suggestion(client, wire):
    """(A, Gemini-primary path) Even if Gemini itself suggests a wrong-language
    title (simulating it not perfectly honoring the prompt instruction — the
    exact 'Kannada action movie despite Telugu request' scenario), the
    post-resolution objective language check must still discard it. This is
    the structural guarantee: personalization/Gemini judgment can select
    among valid candidates, but can never override an explicit constraint."""
    sita_ramam = _media("SITA", genres=["History", "Romance", "Drama"], language="te",
                         rating=7.8, title="Sita Ramam", year=2022)
    wrong_lang = _media("WRONG", genres=["Action"], language="kn",
                         rating=8.0, title="Some Kannada Action Movie", year=2019)
    wire["recommender"] = SpyRecommender(GeminiRecommendation(
        preferences=PreferenceObject(
            media_type=["movie"], language=["Telugu"], explicit_fields=["language"],
        ),
        suggestions=[
            GeminiSuggestion(title="Some Kannada Action Movie", media_type="movie",
                              year=2019, reason="Fits your love of action."),
            GeminiSuggestion(title="Sita Ramam", media_type="movie", year=2022,
                              reason="A tender, romantic Telugu period drama."),
        ],
    ))
    wire["clients"] = FakeClients(
        search_results={
            "Some Kannada Action Movie": [wrong_lang],
            "Sita Ramam": [sita_ramam],
        }
    )
    body = client.post("/recommendations", json={"request": "telugu love stories"}).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "WRONG" not in ids
    assert ids == {"SITA"}


def test_explicit_language_unresolved_token_yields_empty_not_arbitrary(client, wire):
    """(C) An explicit language that fails to resolve to any known code must
    never silently permit arbitrary-language candidates through — an honest
    empty result, same philosophy as an unsatisfiable rating bound."""
    wire["clients"] = FakeClients(
        screen=[
            _media("A", genres=["Romance"], language="en", title="Some English Film"),
            _media("B", genres=["Romance"], language="te", title="Some Telugu Film"),
        ]
    )
    body = client.post(
        "/recommendations",
        json={
            "preferences": {
                "media_type": ["movie"],
                "genres": ["romance"],
                "language": ["Klingon"],
                "explicit_fields": ["genres", "language"],
            }
        },
    ).json()
    assert body["state"] == "results"
    assert body["results"] == []  # no wrong-language substitute is ever returned


def test_no_explicit_language_allows_multiple_languages(client, wire):
    """(D) Without an explicit language, results may legitimately span
    languages — the fix must not over-filter the unconstrained case."""
    wire["clients"] = FakeClients(
        screen=[
            _media("EN", genres=["Drama"], language="en", rating=7.5, title="English Drama"),
            _media("KO", genres=["Drama"], language="ko", rating=7.6, title="Korean Drama"),
        ]
    )
    body = client.post("/recommendations", json={"request": "a good drama"}).json()
    assert body["preferences"].get("language") in (None, [])
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert {"EN", "KO"} <= ids


def test_all_hard_constraints_compose_after_language_fix(client, wire):
    """(E) Rating threshold, explicit genre, avoid terms, and the new language
    filter must all still apply together correctly, not just individually."""
    wire["clients"] = FakeClients(
        screen=[
            _media("WINNER", genres=["Romance"], language="te", rating=8.1,
                   description="A tender romance.", title="Winner"),
            _media("WRONG_LANG", genres=["Romance"], language="hi", rating=8.5,
                   description="A tender romance.", title="Wrong Language"),
            _media("BELOW_RATING", genres=["Romance"], language="te", rating=6.0,
                   description="A tender romance.", title="Below Rating"),
            _media("WRONG_GENRE", genres=["Horror"], language="te", rating=9.0,
                   description="A tender romance.", title="Wrong Genre"),
            _media("AVOID_HIT", genres=["Romance"], language="te", rating=8.9,
                   description="A story built around violence and tragedy.", title="Avoid Hit"),
        ]
    )
    body = client.post(
        "/recommendations",
        json={
            "request": "a telugu romance movie rated above 7.5, no violence"
        },
    ).json()
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert ids == {"WINNER"}
