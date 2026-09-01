"""The extraction contract. One method, one bounded call."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.preference import PreferenceObject


@runtime_checkable
class PreferenceExtractor(Protocol):
    """Turns a free-text request into a `PreferenceObject` (spec §7).

    Implementations must be bounded: a single request, structured JSON out, a
    short timeout, at most one retry. They return ``None`` (never raise) when
    they cannot produce a usable object, so the caller can fall back.
    """

    def extract(self, request_text: str) -> PreferenceObject | None: ...
