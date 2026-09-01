"""Merge a re-extracted preference object into the existing one (spec §8.3).

Rule: new non-null / non-empty values win; `avoid` lists are unioned;
`explicit_fields` is unioned (informational only).
"""
from __future__ import annotations

from app.schemas.preference import PreferenceObject

_SCALAR_FIELDS = ("length", "intensity", "release_period")
_LIST_FIELDS = ("mood", "tone", "genres", "language")


def _union(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def merge_preferences(
    existing: PreferenceObject, new: PreferenceObject
) -> PreferenceObject:
    data = existing.model_dump()

    for field in _SCALAR_FIELDS:
        value = getattr(new, field)
        if value is not None:
            data[field] = value

    for field in _LIST_FIELDS:
        value = getattr(new, field)
        if value:  # a non-empty new list replaces the old one
            data[field] = list(value)

    if new.media_type:
        data["media_type"] = list(new.media_type)

    data["avoid"] = _union(existing.avoid, new.avoid)
    data["explicit_fields"] = _union(existing.explicit_fields, new.explicit_fields)

    return PreferenceObject(**data)
