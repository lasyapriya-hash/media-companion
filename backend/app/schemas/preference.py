"""The structured preference object (spec §7).

Produced by the LLM extractor **or** the deterministic fallback (spec §8.3);
also accepted directly on the request body so a client can bypass the LLM.
All fields optional; absent fields are ``null`` or ``[]``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MediaTypeLit = Literal["movie", "series", "book"]
LengthLit = Literal["short", "medium", "long"]
IntensityLit = Literal["low", "medium", "high"]
NamedPeriodLit = Literal["recent", "classic"]

# Fields that count toward the richness set for the sparsity rule (spec §8.3).
# `avoid` deliberately excluded.
RICHNESS_FIELDS = (
    "media_type",
    "mood",
    "tone",
    "genres",
    "length",
    "intensity",
    "language",
    "release_period",
)


class ReleaseWindow(BaseModel):
    from_year: int | None = None
    to_year: int | None = None


class PreferenceObject(BaseModel):
    media_type: list[MediaTypeLit] | None = None  # null = any
    mood: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    length: LengthLit | None = None
    intensity: IntensityLit | None = None
    language: list[str] = Field(default_factory=list)
    release_period: ReleaseWindow | NamedPeriodLit | None = None
    avoid: list[str] = Field(default_factory=list)  # always a HARD filter (spec §7)
    explicit_fields: list[str] = Field(default_factory=list)

    def populated_richness(self) -> set[str]:
        """Which richness-set fields carry a value (spec §8.3)."""
        out: set[str] = set()
        for name in RICHNESS_FIELDS:
            value = getattr(self, name)
            if value not in (None, [], ""):
                out.add(name)
        return out

    def is_sufficient(self) -> bool:
        """Sparsity rule (spec §8.3): sufficient if any of the three hold."""
        rich = self.populated_richness()
        if "genres" in rich:
            return True
        if "mood" in rich and rich & {"tone", "media_type", "length", "language"}:
            return True
        return len(rich) >= 3
