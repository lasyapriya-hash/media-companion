"""Shared HTTP plumbing for external API clients.

Timeout + one retry on transient network errors (spec §3.4 / NFR2). Richer
fallback handling (typed "unknown" states, primary/fallback book APIs) lands in
later phases; this is the transport floor.
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
    """Raised when an upstream API call ultimately fails."""


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(0.4),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
def request_json(
    http: httpx.Client,
    path: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> dict:
    """GET `path` on an existing client and return parsed JSON.

    Retries once on timeout/transport errors; raises ExternalAPIError on an
    HTTP error status or a non-JSON body.
    """
    try:
        resp = http.get(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise ExternalAPIError(
            f"{exc.request.url} -> HTTP {exc.response.status_code}"
        ) from exc
    except ValueError as exc:  # invalid JSON
        raise ExternalAPIError(f"{path} -> invalid JSON response") from exc
