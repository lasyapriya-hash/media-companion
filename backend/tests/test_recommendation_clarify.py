"""Phase 5 verification: the clarification turn + session state machine
(spec §8.1-8.4; plan Phase 5).

Reuses the stubbed clients / extractor harness from the Phase 4 test module.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_recommendations import (  # noqa: F401  (wire is a fixture)
    FakeClients,
    SpyExtractor,
    _media,
    wire,
)
from app.schemas.preference import PreferenceObject

RICH = "a dark, tense crime thriller movie"
SPARSE = "something for tonight"


def _screen(**over):
    base = dict(rating=7.0)
    base.update(over)
    return base


@pytest.fixture()
def stocked(wire):
    """A pool broad enough that ranking always returns something."""
    wire["clients"] = FakeClients(
        screen=[
            _media("A", genres=["Crime", "Thriller"], title="Cold Ledger", rating=6.5),
            _media("B", genres=["Drama"], title="Quiet Room", rating=7.2),
            _media("C", genres=["Comedy"], title="Bright Side", rating=7.8),
        ],
        books=[
            _media("bk", source="open_library", type="book", genres=["Fantasy"],
                   title="Elderwood", page_count=300),
        ],
    )
    return wire


# --------------------------------------------------------------------------- #
# Rich request -> straight to a ranked list, no question (AC, spec §8.3)
# --------------------------------------------------------------------------- #
def test_rich_request_returns_list_without_a_question(client, stocked):
    resp = client.post("/recommendations", json={"request": RICH})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "results"
    assert body["clarification_question"] is None
    assert len(body["results"]) >= 1
    assert uuid.UUID(body["session_id"])  # a real session id is always returned


# --------------------------------------------------------------------------- #
# Sparse request -> exactly one question -> ranked list (AC, FR5)
# --------------------------------------------------------------------------- #
def test_sparse_request_asks_one_question_then_lists(client, stocked):
    q = client.post("/recommendations", json={"request": SPARSE})
    assert q.status_code == 200
    qb = q.json()
    assert qb["state"] == "needs_clarification"
    assert isinstance(qb["clarification_question"], str) and len(qb["clarification_question"]) > 10
    assert qb["results"] == []

    a = client.post(
        f"/recommendations/{qb['session_id']}/answer",
        json={"answer": "a crime thriller film"},
    )
    assert a.status_code == 200
    ab = a.json()
    assert ab["state"] == "results"
    assert ab["clarification_question"] is None
    assert len(ab["results"]) >= 1
    # the answer was merged into the preference object
    assert "crime" in ab["preferences"]["genres"]
    assert ab["preferences"]["media_type"] == ["movie"]


# --------------------------------------------------------------------------- #
# The question is asked at most once (AC, spec §8.2)
# --------------------------------------------------------------------------- #
def test_no_second_question_ever(client, stocked):
    sid = client.post("/recommendations", json={"request": SPARSE}).json()["session_id"]

    first = client.post(f"/recommendations/{sid}/answer", json={"answer": "sci-fi"})
    assert first.status_code == 200 and first.json()["state"] == "results"

    # any further answer attempt is rejected — the flow can only go to ranking
    second = client.post(f"/recommendations/{sid}/answer", json={"answer": "no, horror"})
    assert second.status_code == 409


def test_empty_and_declined_answers_still_produce_a_list(client, stocked):
    for reply in ({}, {"answer": ""}, {"answer": "just recommend something"}):
        sid = client.post(
            "/recommendations", json={"request": SPARSE}
        ).json()["session_id"]
        a = client.post(f"/recommendations/{sid}/answer", json=reply)
        assert a.status_code == 200, (reply, a.text)
        body = a.json()
        assert body["state"] == "results"
        assert len(body["results"]) >= 1  # via taste / broad fallback (spec §8.3)
        # and no second question is possible afterwards
        assert (
            client.post(f"/recommendations/{sid}/answer", json={"answer": "x"}).status_code
            == 409
        )


# --------------------------------------------------------------------------- #
# Still-sparse-after-answer -> non-empty list via fallback (plan Phase 5)
# --------------------------------------------------------------------------- #
def test_still_sparse_after_answer_uses_fallback(client, stocked):
    sid = client.post("/recommendations", json={"request": SPARSE}).json()["session_id"]
    # an answer that yields no usable structured signal
    a = client.post(
        f"/recommendations/{sid}/answer", json={"answer": "hmm, honestly not sure"}
    )
    assert a.status_code == 200
    body = a.json()
    assert body["state"] == "results"
    assert len(body["results"]) >= 1


# --------------------------------------------------------------------------- #
# Merge rule: new non-null wins, `avoid` unions (spec §8.3)
# --------------------------------------------------------------------------- #
def test_answer_merges_avoid_as_union(client, wire):
    wire["clients"] = FakeClients(
        screen=[
            _media("K", genres=["Comedy"], title="Keep Me", rating=7.0),
            _media("H", genres=["Horror"], title="The Cellar", rating=7.0),
        ]
    )
    # original request is sparse but carries an `avoid`
    sid = client.post(
        "/recommendations", json={"request": "something, but no horror"}
    ).json()["session_id"]
    body = client.post(
        f"/recommendations/{sid}/answer",
        json={"answer": "a light comedy, nothing gory"},
    ).json()
    assert body["state"] == "results"
    prefs = body["preferences"]
    assert "comedy" in prefs["genres"]  # new value present
    assert set(prefs["avoid"]) >= {"horror", "gory"}  # unioned across both turns
    ids = {r["media"]["source_id"] for r in body["results"]}
    assert "H" not in ids  # avoid stays a hard filter


# --------------------------------------------------------------------------- #
# Structured `preferences` (e.g. "Surprise me") skips the clarifying turn
# --------------------------------------------------------------------------- #
def test_structured_preferences_skip_clarification(client, stocked):
    resp = client.post("/recommendations", json={"preferences": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "results"  # no question even though it's "sparse"
    assert body["clarification_question"] is None
    # and it cannot be answered afterwards
    assert (
        client.post(
            f"/recommendations/{body['session_id']}/answer", json={"answer": "x"}
        ).status_code
        == 409
    )


# --------------------------------------------------------------------------- #
# Answering a rich (already-resolved) session is rejected
# --------------------------------------------------------------------------- #
def test_cannot_answer_a_session_that_went_straight_to_results(client, stocked):
    sid = client.post("/recommendations", json={"request": RICH}).json()["session_id"]
    assert (
        client.post(f"/recommendations/{sid}/answer", json={"answer": "x"}).status_code
        == 409
    )


# --------------------------------------------------------------------------- #
# Unknown / malformed session id
# --------------------------------------------------------------------------- #
def test_answer_unknown_session_is_404(client):
    r = client.post(
        f"/recommendations/{uuid.uuid4()}/answer", json={"answer": "anything"}
    )
    assert r.status_code == 404


def test_answer_bad_session_id_is_422(client):
    assert client.post(
        "/recommendations/not-a-uuid/answer", json={"answer": "x"}
    ).status_code == 422


# --------------------------------------------------------------------------- #
# The LLM is still only used for extraction (spec §8.2)
# --------------------------------------------------------------------------- #
def test_answer_reextraction_uses_the_llm_interface_once(client, stocked):
    # returns nothing usable, so the request stays sparse and a question is asked
    spy = SpyExtractor(PreferenceObject())
    stocked["extractor"] = spy

    q = client.post("/recommendations", json={"request": SPARSE}).json()
    assert q["state"] == "needs_clarification"
    assert spy.calls == [SPARSE]  # one extraction for the request

    a = client.post(
        f"/recommendations/{q['session_id']}/answer", json={"answer": "gritty crime"}
    ).json()
    assert a["state"] == "results"
    # exactly one more extraction call — for the answer, and nothing else
    assert spy.calls == [SPARSE, "gritty crime"]
