"""Shared HTTP plumbing for external API clients (spec §3.4 / NFR2).

Every request: a bounded timeout, one retry on a transient failure (network
error, 429, or 5xx), then a typed `ExternalAPIError` the caller can catch and
turn into a graceful fallback. Non-transient 4xx errors are not retried.
"""
from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ExternalAPIError(RuntimeError):
    """An upstream API call ultimately failed (after any retry)."""


class TransientAPIError(ExternalAPIError):
    """A retryable upstream failure: 429 or 5xx."""


_RETRYABLE = (httpx.TimeoutException, httpx.TransportError, TransientAPIError)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(0.4),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def request_json(
    http: httpx.Client,
    path: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> dict:
    """GET `path` on an existing client and return parsed JSON.

    Retries once on a transient failure; raises `ExternalAPIError`
    (`TransientAPIError` for 429/5xx) on failure or a non-JSON body.
    """
    try:
        resp = http.get(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = f"{exc.request.url} -> HTTP {status}"
        if status == 429 or 500 <= status < 600:
            raise TransientAPIError(message) from exc
        raise ExternalAPIError(message) from exc
    except ValueError as exc:  # invalid JSON
        raise ExternalAPIError(f"{path} -> invalid JSON response") from exc
