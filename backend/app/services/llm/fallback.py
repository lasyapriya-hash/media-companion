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

from app.schemas.preference import PreferenceObject, RatingRange, ReleaseWindow
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
# comparative stop-words that only ever belong to a rating clause
# ("no more than 6", "no less than 8") — never a thing to avoid.
_AVOID_STOPWORDS = {"more", "less", "fewer", "than"}

# --------------------------------------------------------------------------- #
# Explicit numeric rating bounds (spec §7). Extracted from the *pristine* text
# so a "no more than X" clause is read as a bound, not as an `avoid`.
# --------------------------------------------------------------------------- #
_RATING_NUM = r"(?:10(?:\.0)?|[0-9](?:\.[0-9])?)"  # 0.0 – 10.0
_RATING_CUE_RE = re.compile(
    r"\b(?:rated|rating|ratings|score|scored|scores|star|stars|imdb|"
    r"rotten\s+tomatoes|metacritic)\b|/\s?10|out of 10"
)
_RATING_OP_RE = re.compile(rf"(>=|<=|>|<)\s*(?P<num>{_RATING_NUM})\b")
# trailing token varies ("7.5+", "8 or higher") — no closing \b: "+" is
# non-word so \b after it would never hold.
_RATING_SUFFIX_UP_RE = re.compile(
    rf"\b(?P<num>{_RATING_NUM})\s*(?:\+|or (?:higher|above|better|more|over)|"
    r"and (?:up|above|higher|over))"
)
_RATING_SUFFIX_DOWN_RE = re.compile(
    rf"\b(?P<num>{_RATING_NUM})\s*(?:or (?:lower|below|less|worse)|"
    r"and (?:below|lower))"
)
_RATING_BETWEEN_RE = re.compile(
    rf"\bbetween\s+(?P<lo>{_RATING_NUM})\s+(?:and|to|-|–)\s+(?P<hi>{_RATING_NUM})\b"
)
_RATING_CMP_RE = re.compile(
    r"\b(?:"
    r"(?P<gt>above|over|more than|greater than|higher than|exceeding|north of)|"
    r"(?P<gte>at least|no less than|minimum(?: of)?|min(?: of)?)|"
    r"(?P<lt>below|under|less than|lower than|south of)|"
    r"(?P<lte>at most|no more than|maximum(?: of)?|max(?: of)?|up to)"
    rf")\s+(?:a\s+)?(?:rating\s+of\s+|score\s+of\s+)?(?P<num>{_RATING_NUM})\b"
)


def _extract_rating(text: str) -> RatingRange | None:
    """Parse "rated above 7.5", "at least 8", "below 6", "between 7 and 8", …

    Inclusive vs exclusive is preserved: "above"/"over"/">" -> `gt`;
    "at least"/"or higher"/">=" -> `gte`; "below"/"under"/"<" -> `lt`;
    "at most"/"no more than"/"<=" -> `lte`. Word forms need a rating cue word
    nearby so "under 90 minutes" / "over 2 hours" are never mistaken for a bound;
    the ``>=``/``7.5+`` forms are unambiguous and only require a 0–10 value.
    """
    has_cue = _RATING_CUE_RE.search(text) is not None
    rng = RatingRange()

    def up(v: float, inclusive: bool) -> None:
        if inclusive:
            rng.gte = v if rng.gte is None else max(rng.gte, v)
        else:
            rng.gt = v if rng.gt is None else max(rng.gt, v)

    def down(v: float, inclusive: bool) -> None:
        if inclusive:
            rng.lte = v if rng.lte is None else min(rng.lte, v)
        else:
            rng.lt = v if rng.lt is None else min(rng.lt, v)

    for m in _RATING_OP_RE.finditer(text):
        v = float(m.group("num"))
        {">": lambda: up(v, False), ">=": lambda: up(v, True),
         "<": lambda: down(v, False), "<=": lambda: down(v, True)}[m.group(1)]()

    for m in _RATING_SUFFIX_UP_RE.finditer(text):
        up(float(m.group("num")), True)
    for m in _RATING_SUFFIX_DOWN_RE.finditer(text):
        down(float(m.group("num")), True)

    if has_cue:
        bm = _RATING_BETWEEN_RE.search(text)
        if bm:
            lo, hi = sorted((float(bm.group("lo")), float(bm.group("hi"))))
            up(lo, True)
            down(hi, True)
        for m in _RATING_CMP_RE.finditer(text):
            v = float(m.group("num"))
            if m.group("gt") is not None:
                up(v, False)
            elif m.group("gte") is not None:
                up(v, True)
            elif m.group("lt") is not None:
                down(v, False)
            elif m.group("lte") is not None:
                down(v, True)

    return rng if rng.is_set() else None


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
        if word in _AVOID_STOPWORDS:  # part of "no more than X" — a rating bound
            continue
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

    rating = _extract_rating(base)  # pristine text: bounds are never `avoid`
    if rating is not None:
        explicit.append("rating")

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
        rating=rating,
        avoid=avoid,
        explicit_fields=_dedupe(explicit),
    )
