"""The single clarifying question (spec §8.3).

Chosen deterministically from a fixed templated set, keyed on which
richness-set fields are still missing. **No LLM call.** The question is only
ever asked when preferences are sparse (all three sufficiency conditions fail),
so at most one or two richness fields are populated here.
"""
from __future__ import annotations

from app.schemas.preference import PreferenceObject

# Ordered (most useful first). Each entry: (does this gap apply?, question).
# `r` is the set of populated richness fields (PreferenceObject.populated_richness()).
_TEMPLATES: list[tuple] = [
    (
        lambda r: not (r & {"media_type", "genres", "mood", "tone"}),
        "To point this the right way — are you after a film, a series, or a book, "
        "and is there a genre or a mood in mind?",
    ),
    (
        lambda r: "media_type" not in r,
        "Are you in the mood for a film, a series, or a book?",
    ),
    (
        lambda r: not (r & {"genres", "mood", "tone"}),
        "What sort of thing are you after — a particular genre, or more of a mood?",
    ),
    (
        lambda r: not (r & {"mood", "tone"}),
        "What mood are you going for — something light and easy, or darker and heavier?",
    ),
    (
        lambda r: "length" not in r,
        "How much time do you have — something short, or happy to settle in for a while?",
    ),
]

_DEFAULT_QUESTION = (
    "Anything you're leaning toward right now — a genre, a mood, or a length?"
)

# Replies that mean "stop asking, just recommend" (spec §8.3: the user declines).
_DECLINE_PHRASES = (
    "just recommend",
    "just pick",
    "just choose",
    "surprise me",
    "you choose",
    "you pick",
    "you decide",
    "anything",
    "anything is fine",
    "whatever",
    "no preference",
    "no idea",
    "not sure",
    "dunno",
    "don't know",
    "dont know",
    "don't care",
    "dont care",
    "idk",
    "skip",
    "n/a",
)


def clarifying_question(prefs: PreferenceObject) -> str:
    rich = prefs.populated_richness()
    for applies, question in _TEMPLATES:
        if applies(rich):
            return question
    return _DEFAULT_QUESTION


def is_decline(answer: str) -> bool:
    """True when the reply carries no usable signal — proceed straight to ranking."""
    a = (answer or "").strip().lower()
    if not a:
        return True
    if len(a) <= 2:
        return True
    return any(p in a for p in _DECLINE_PHRASES)
