"""Deterministic free-text -> `PreferenceObject` parser (spec §8.3).

No network, no LLM. Keyword + controlled-vocabulary matching only. Always
available; used whenever the LLM provider is disabled, key-less, or fails, and
directly when a client posts raw text but the engine is running LLM-free.

It is intentionally conservative: it only populates a field when it matched a
term *literally*, and records every such field in `explicit_fields`. `avoid`
clauses are pulled out first and blanked from the text so a word that only
appears in "no …" / "avoid …" is never also read as something wanted.
"""
from __future__ import annotations

import re

from app.schemas.preference import PreferenceObject, ReleaseWindow
from app.services.vocab import (
    CLASSIC_WORDS,
    GENRE_SYNONYMS,
    GENRE_VOCABULARY,
    INTENSITY_WORDS,
    LANGUAGE_NAME_TO_CODE,
    LENGTH_WORDS,
    MOOD_SYNONYMS,
    MOOD_VOCABULARY,
    RECENT_WORDS,
    TONE_SYNONYMS,
    TONE_VOCABULARY,
)

_MEDIA_TYPE_WORDS: dict[str, str] = {
    "movie": "movie",
    "movies": "movie",
    "film": "movie",
    "films": "movie",
    "series": "series",
    "show": "series",
    "shows": "series",
    "tv": "series",
    "book": "book",
    "books": "book",
    "novel": "book",
    "novels": "book",
}

# single word after a negation cue: "no horror", "not scary", "without romance",
# "avoid gore", "nothing violent", "not too long"
_AVOID_RE = re.compile(
    r"\b(?:no|not|without|avoid|avoiding|nothing|none|skip|hate|dislike)\s+"
    r"(?:the\s+|any\s+|too\s+|really\s+)*([a-z][a-z\-]{2,20})"
)


def _phrase_hits(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _extract_avoid(text: str) -> tuple[list[str], str]:
    """Return (avoid terms, text with the matched avoid words blanked out)."""
    avoid: list[str] = []
    chars = list(text)
    for match in _AVOID_RE.finditer(text):
        word = match.group(1)
        term: str | None = None
        if word in GENRE_VOCABULARY or word in MOOD_VOCABULARY or word in TONE_VOCABULARY:
            term = word
        elif word in GENRE_SYNONYMS:
            term = GENRE_SYNONYMS[word]
        elif word in MOOD_SYNONYMS:
            term = MOOD_SYNONYMS[word]
        elif word in TONE_SYNONYMS:
            term = TONE_SYNONYMS[word]
        elif 3 <= len(word) <= 20:
            term = word
        if term:
            avoid.append(term)
            for i in range(*match.span(1)):
                chars[i] = " "
    return _dedupe(avoid), "".join(chars)


def parse_preferences(request_text: str) -> PreferenceObject:
    base = f" {(request_text or '').lower().strip()} "
    avoid, text = _extract_avoid(base)
    explicit: list[str] = []

    genres: list[str] = [g for g in GENRE_VOCABULARY if _phrase_hits(text, g)]
    genres += [c for token, c in GENRE_SYNONYMS.items() if _phrase_hits(text, token)]
    genres = _dedupe(genres)
    if genres:
        explicit.append("genres")

    mood: list[str] = [
        tag
        for tag in MOOD_VOCABULARY
        if _phrase_hits(text, tag) or _phrase_hits(text, tag.replace("-", " "))
    ]
    mood += [tag for token, tag in MOOD_SYNONYMS.items() if _phrase_hits(text, token)]
    mood = _dedupe(mood)
    if mood:
        explicit.append("mood")

    tone: list[str] = [w for w in TONE_VOCABULARY if _phrase_hits(text, w)]
    tone += [w for token, w in TONE_SYNONYMS.items() if _phrase_hits(text, token)]
    tone = _dedupe(tone)
    if tone:
        explicit.append("tone")

    length: str | None = None
    for word, bucket in LENGTH_WORDS.items():
        if _phrase_hits(text, word):
            length = bucket
            break
    if length:
        explicit.append("length")

    intensity: str | None = None
    for word, level in INTENSITY_WORDS.items():
        if _phrase_hits(text, word):
            intensity = level
            break
    if intensity:
        explicit.append("intensity")

    language: list[str] = _dedupe(
        [name for name in LANGUAGE_NAME_TO_CODE if _phrase_hits(text, name)]
    )
    if language:
        explicit.append("language")

    media_type: list[str] = _dedupe(
        [kind for token, kind in _MEDIA_TYPE_WORDS.items() if _phrase_hits(text, token)]
    )
    if media_type:
        explicit.append("media_type")

    release_period: object = None
    decade = re.search(r"\b(18|19|20)(\d0)s\b", text)
    year = re.search(r"\b(19|20)\d{2}\b", text)
    if any(_phrase_hits(text, w) for w in RECENT_WORDS):
        release_period = "recent"
    elif any(_phrase_hits(text, w) for w in CLASSIC_WORDS):
        release_period = "classic"
    elif decade:
        start = int(f"{decade.group(1)}{decade.group(2)}")
        release_period = ReleaseWindow(from_year=start, to_year=start + 9)
    elif year:
        y = int(year.group(0))
        release_period = ReleaseWindow(from_year=y, to_year=y)
    if release_period is not None:
        explicit.append("release_period")

    # a term can't be both wanted and avoided; the negation wins
    avoid_set = set(avoid)
    genres = [g for g in genres if g not in avoid_set]
    mood = [m for m in mood if m not in avoid_set]
    tone = [t for t in tone if t not in avoid_set]

    return PreferenceObject(
        media_type=media_type or None,
        mood=mood,
        tone=tone,
        genres=genres,
        length=length,
        intensity=intensity,
        language=language,
        release_period=release_period,
        avoid=avoid,
        explicit_fields=_dedupe(explicit),
    )
