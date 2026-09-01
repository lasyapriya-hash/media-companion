"""Phase 6: external-call error/timeout handling (spec §3.4 / NFR2).

`request_json` retries once on a transient failure (network error / 429 / 5xx)
and raises a typed error otherwise — no retry storm on a 4xx.
"""
from __future__ import annotations

import httpx
import pytest

from app.clients.base import ExternalAPIError, TransientAPIError, request_json


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(handler)
    )


def test_success_returns_json_no_retry():
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    assert request_json(_client(handler), "/x") == {"ok": True}
    assert calls["n"] == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_status_retried_then_typed(status):
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        return httpx.Response(status, json={})

    with pytest.raises(TransientAPIError):
        request_json(_client(handler), "/x")
    assert calls["n"] == 2  # one retry


@pytest.mark.parametrize("status", [400, 401, 404])
def test_client_error_not_retried(status):
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        return httpx.Response(status, json={})

    with pytest.raises(ExternalAPIError) as ei:
        request_json(_client(handler), "/x")
    assert not isinstance(ei.value, TransientAPIError)
    assert calls["n"] == 1  # no retry on a 4xx


def test_network_error_retried_then_recovers():
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"recovered": True})

    assert request_json(_client(handler), "/x") == {"recovered": True}
    assert calls["n"] == 2


def test_bad_json_body_is_typed_error():
    def handler(_req):
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(ExternalAPIError):
        request_json(_client(handler), "/x")
