"""Templated one-sentence recommendation reasons (spec §9.4).

Assembled deterministically from the structured match explanation (which
sub-signals matched) plus one taste-profile fact. No LLM. Request-specific
because the sentence names the request's own matched fields; when the request
was too sparse to match anything, it names the taste-profile basis instead.
"""
from __future__ import annotations

from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject
from app.services.recommendations.scoring import MatchExplanation, satisfies_rating

_TYPE_NOUN = {"movie": "movie", "series": "series", "book": "book"}


def _fmt(v: float) -> str:
    return f"{v:g}"


def _rating_clause(item: NormalizedMedia, prefs: PreferenceObject) -> str:
    """A clause about the explicit rating bound — only when the item truly meets
    it (spec §9.4: never claim a constraint the candidate doesn't satisfy)."""
    rc = prefs.rating
    if rc is None or not rc.is_set() or item.external_rating is None:
        return ""
    if not satisfies_rating(item, rc):
        return ""
    got = f"{item.external_rating:.1f}"
    if (rc.gte is not None or rc.gt is not None) and (rc.lte is not None or rc.lt is not None):
        lo = _fmt(rc.gte if rc.gte is not None else rc.gt)
        hi = _fmt(rc.lte if rc.lte is not None else rc.lt)
        return f"a critics’ score of {got}/10, inside the {lo}–{hi} you asked for"
    if rc.gt is not None:
        return f"a critics’ score of {got}/10, above the {_fmt(rc.gt)} you asked for"
    if rc.gte is not None:
        return f"a critics’ score of {got}/10, at or above the {_fmt(rc.gte)} you asked for"
    if rc.lt is not None:
        return f"a critics’ score of {got}/10, below the {_fmt(rc.lt)} you asked for"
    return f"a critics’ score of {got}/10, at or below the {_fmt(rc.lte)} you asked for"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def build_reason(
    item: NormalizedMedia,
    prefs: PreferenceObject,
    exp: MatchExplanation,
    taste,
) -> str:
    noun = _TYPE_NOUN.get(getattr(item.type, "value", item.type), "pick")
    rating_clause = _rating_clause(item, prefs)

    if exp.any_preference_signal() or rating_clause:
        clauses: list[str] = []
        if exp.genres:
            clauses.append(f"the {_join(exp.genres)} angle you asked for")
        if exp.mood_tone:
            clauses.append(f"{_article(exp.mood_tone[0])} {_join(exp.mood_tone)} tone")
        if exp.length:
            clauses.append(f"its {exp.length} length")
        if exp.language:
            clauses.append(f"the {exp.language} language")
        if exp.period:
            clauses.append(exp.period)
        if rating_clause:
            clauses.append(rating_clause)
        head = f"Fits your request for {_join(clauses)}"
        tail = f", and {exp.taste_fact}" if exp.taste_fact else ""
        if not tail and exp.novelty_high:
            tail = ", and it's a lower-profile pick rather than an obvious blockbuster"
        return f"{head}{tail}."

    # Sparse request -> taste-profile basis (spec §8.3 fallback).
    favs = list(taste.favourite_genres or [])[:2]
    if exp.taste_fact:
        return (
            f"Your request was open-ended, so this leans on your taste profile: "
            f"{exp.taste_fact}."
        )
    if favs:
        return (
            f"Your request was open-ended, so this comes from your favourite "
            f"{_join(favs)} {'genre' if len(favs) == 1 else 'genres'}."
        )
    return (
        f"Your request was open-ended and your library is still small, so this "
        f"{noun} is a broadly popular starting point that is not just the "
        f"top-rated result."
    )
