"""Deterministic recommendation scoring (spec §9).

Movies/series: weighted `preference_match`, `taste_profile_match`, `novelty`
minus a `penalty` (spec §9.1, weights 0.50 / 0.35 / 0.15 per §15 D4).
Books: `genre_overlap + mood_tag_overlap` with a taste tiebreaker (spec §9.2).

`external_rating` never enters a sort key — only a low quality floor (spec §9.3).
No LLM anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.taste import TasteProfile
from app.schemas.media import NormalizedMedia
from app.schemas.preference import PreferenceObject, ReleaseWindow
from app.services.recommendations.candidates import period_years
from app.services.vocab import (
    GENRE_SYNONYMS,
    MOOD_SYNONYMS,
    MOOD_TONE_GENRE_HINTS,
    TONE_SYNONYMS,
    language_to_code,
)

W_PREF, W_TASTE, W_NOVELTY = 0.50, 0.35, 0.15
# Drop obvious junk only (spec §9.3: a minimum-quality floor, nothing more).
QUALITY_FLOOR = 2.5
_INTENSITY_GENRE = {
    "high": {"action", "horror", "thriller", "war", "crime"},
    "low": {"family", "animation", "documentary", "romance", "music", "comedy"},
}


@dataclass
class MatchExplanation:
    genres: list[str] = field(default_factory=list)
    mood_tone: list[str] = field(default_factory=list)
    length: str | None = None
    language: str | None = None
    period: str | None = None
    taste_fact: str | None = None
    novelty_high: bool = False
    sparse: bool = False

    def any_preference_signal(self) -> bool:
        return bool(
            self.genres or self.mood_tone or self.length or self.language or self.period
        )


@dataclass
class ScoredCandidate:
    item: NormalizedMedia
    score: float
    tiebreak: float
    explanation: MatchExplanation


def _norm_genre(label: str) -> str:
    g = label.strip().lower()
    return GENRE_SYNONYMS.get(g, g)


def _cand_genres(item: NormalizedMedia) -> set[str]:
    return {_norm_genre(g) for g in (item.genres or [])}


def _mood_terms(prefs: PreferenceObject) -> list[str]:
    """Canonical mood/tone terms usable as `MOOD_TONE_GENRE_HINTS` keys.

    Preferences that came through the fallback or the LLM extractor are already
    canonical; the synonym remap only rescues a raw term (e.g. from a
    client-supplied `preferences` body).
    """
    terms: list[str] = []
    for raw in [*prefs.mood, *prefs.tone]:
        t = raw.strip().lower()
        if t not in MOOD_TONE_GENRE_HINTS:
            t = MOOD_SYNONYMS.get(t, TONE_SYNONYMS.get(t, t))
        if t and t not in terms:
            terms.append(t)
    return terms


def passes_quality_floor(item: NormalizedMedia) -> bool:
    return item.external_rating is None or item.external_rating >= QUALITY_FLOOR


def hits_avoid(item: NormalizedMedia, avoid: list[str]) -> bool:
    """`avoid` is always a hard filter (spec §7)."""
    if not avoid:
        return False
    hay = " ".join(
        [
            item.title or "",
            item.description or "",
            " ".join(item.genres or []),
            " ".join(item.mood_tags or []),
        ]
    ).lower()
    cand_genres = _cand_genres(item)
    for raw in avoid:
        term = raw.strip().lower()
        if not term:
            continue
        norm = GENRE_SYNONYMS.get(term, term)
        if norm in cand_genres or term in cand_genres:
            return True
        if term in hay:
            return True
        # mood/tone term -> its genre expression
        for hint_genre in MOOD_TONE_GENRE_HINTS.get(norm, set()):
            if hint_genre in cand_genres:
                return True
    return False


# --------------------------------------------------------------------------- #
# Sub-signals (each 0–1)
# --------------------------------------------------------------------------- #
def _genre_signal(prefs: PreferenceObject, cand: set[str], exp: MatchExplanation):
    if not prefs.genres:
        return None
    want = {_norm_genre(g) for g in prefs.genres}
    hit = want & cand
    exp.genres = sorted(hit)
    return len(hit) / len(want)


def _mood_tone_signal(prefs: PreferenceObject, item: NormalizedMedia, cand: set[str], exp):
    terms = _mood_terms(prefs)
    if not terms:
        return None
    tags = {t.lower() for t in (item.mood_tags or [])}
    desc = (item.description or "").lower()
    matched: list[str] = []
    for term in terms:
        if term in tags or term in desc:
            matched.append(term)
        elif cand & MOOD_TONE_GENRE_HINTS.get(term, set()):
            matched.append(term)
    exp.mood_tone = matched
    return len(matched) / len(terms)


def _length_signal(prefs: PreferenceObject, item: NormalizedMedia, exp: MatchExplanation):
    if not prefs.length:
        return None
    bucket = item.length_bucket
    if bucket is None:
        return None
    bucket = getattr(bucket, "value", bucket)
    order = {"short": 0, "medium": 1, "long": 2}
    if bucket == prefs.length:
        exp.length = prefs.length
        return 1.0
    return 0.5 if abs(order[bucket] - order[prefs.length]) == 1 else 0.0


def _language_signal(prefs: PreferenceObject, item: NormalizedMedia, exp: MatchExplanation):
    if not prefs.language:
        return None
    want = {c for c in (language_to_code(l) for l in prefs.language) if c}
    have = (item.language or "").lower()
    if have and (have in want or language_to_code(have) in want):
        exp.language = have
        return 1.0
    return 0.0


def _intensity_signal(prefs: PreferenceObject, cand: set[str]):
    if not prefs.intensity:
        return None
    genres = _INTENSITY_GENRE.get(prefs.intensity, set())
    if not genres:
        return None
    return 1.0 if cand & genres else 0.0


def _period_signal(prefs: PreferenceObject, item: NormalizedMedia, exp: MatchExplanation):
    if prefs.release_period is None:
        return None
    if item.year is None:
        return None
    year_from, year_to = period_years(prefs.release_period)
    ok = True
    if year_from is not None and item.year < year_from:
        ok = False
    if year_to is not None and item.year > year_to:
        ok = False
    if ok:
        if prefs.release_period == "recent":
            exp.period = "recent releases"
        elif prefs.release_period == "classic":
            exp.period = "classic titles"
        elif isinstance(prefs.release_period, (ReleaseWindow, dict)):
            exp.period = f"{year_from or '…'}–{year_to or '…'}"
        return 1.0
    return 0.0


def _novelty(item: NormalizedMedia) -> float:
    r = item.external_rating if item.external_rating is not None else 6.0
    nov_rating = 1.0 - _clamp((r - 6.0) / 4.0)
    pop = None
    if isinstance(item.raw_metadata, dict):
        pop = item.raw_metadata.get("popularity")
    if isinstance(pop, (int, float)):
        nov_pop = 1.0 - _clamp(float(pop) / 200.0)
        return (nov_rating + nov_pop) / 2
    return nov_rating


def _taste_profile_match(item: NormalizedMedia, taste: TasteProfile, exp: MatchExplanation):
    cand = _cand_genres(item)
    fav = [g.lower() for g in (taste.favourite_genres or [])]
    genre_affinity = 0.0
    if fav:
        best = 0.0
        for g in cand:
            if g in fav:
                best = max(best, 1.0 - fav.index(g) / max(len(fav), 1))
        genre_affinity = best

    fav_langs = {l.lower() for l in (taste.favourite_languages or [])}
    lang_affinity = 1.0 if (item.language or "").lower() in fav_langs else 0.0

    parts = [genre_affinity, lang_affinity]
    by_genre = {k.lower(): v for k, v in (taste.avg_rating_by_genre or {}).items()}
    ratings = [by_genre[g] for g in cand if g in by_genre]
    if ratings:
        predicted = sum(ratings) / len(ratings)
        parts.append(_clamp(predicted / 10.0))
        top_genre = max((g for g in cand if g in by_genre), key=lambda g: by_genre[g])
        exp.taste_fact = f"you rate {top_genre} {round(by_genre[top_genre], 1)}/10 on average"
    elif genre_affinity > 0:
        matched = next((g for g in cand if g in fav), None)
        if matched:
            exp.taste_fact = f"{matched} is among your favourite genres"

    return _clamp(sum(parts) / len(parts))


def _penalty(item: NormalizedMedia, taste: TasteProfile) -> float:
    """Deductions for `drop_patterns` and low per-genre completion (spec §9.1).

    A confirmed drop-pattern genre is penalised hardest, scaled by how far its
    completion rate sits below 1.0; a genre that merely completes poorly
    (< 50%) without being a full pattern gets a small nudge. Capped at 0.35.
    """
    cand = _cand_genres(item)
    if not cand:
        return 0.0
    drop = {d.lower() for d in (taste.drop_patterns or [])}
    by_genre = {
        k.lower(): float(v)
        for k, v in (taste.completion_rate_by_genre or {}).items()
    }

    pen = 0.0
    for g in cand:
        if g in drop:
            rate = _clamp(by_genre.get(g, 0.0))
            pen += 0.12 + 0.12 * (1.0 - rate)  # 0.12–0.24 per drop-pattern genre
        elif g in by_genre and by_genre[g] < 0.5:
            pen += 0.05 * (0.5 - by_genre[g]) / 0.5  # up to 0.05
    return min(0.35, pen)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #
def score_candidate(
    item: NormalizedMedia, prefs: PreferenceObject, taste: TasteProfile
) -> ScoredCandidate:
    exp = MatchExplanation(sparse=not prefs.is_sufficient())
    cand = _cand_genres(item)

    if item.type == "book":
        want = {_norm_genre(g) for g in prefs.genres} or {
            g.lower() for g in (taste.favourite_genres or [])
        }
        genre_overlap = (len(want & cand) / len(want)) if want else 0.0
        if want & cand:
            exp.genres = sorted(want & cand)
        mood_sig = _mood_tone_signal(prefs, item, cand, exp) or 0.0
        score = _clamp(genre_overlap) + _clamp(mood_sig)  # 0–2 (spec §9.2)
        by_genre = {k.lower(): v for k, v in (taste.avg_rating_by_genre or {}).items()}
        tie = max((by_genre[g] for g in cand if g in by_genre), default=0.0)
        if tie and not exp.taste_fact:
            best = max((g for g in cand if g in by_genre), key=lambda g: by_genre[g])
            exp.taste_fact = f"you rate {best} {round(by_genre[best], 1)}/10 on average"
        exp.novelty_high = _novelty(item) >= 0.6
        return ScoredCandidate(item, round(score, 4), round(tie, 4), exp)

    signals = [
        _genre_signal(prefs, cand, exp),
        _mood_tone_signal(prefs, item, cand, exp),
        _length_signal(prefs, item, exp),
        _language_signal(prefs, item, exp),
        _intensity_signal(prefs, cand),
        _period_signal(prefs, item, exp),
    ]
    present = [s for s in signals if s is not None]
    preference_match = sum(present) / len(present) if present else 0.0
    taste_match = _taste_profile_match(item, taste, exp)
    novelty = _novelty(item)
    penalty = _penalty(item, taste)

    # Novelty (spec §9.1) is a *small* diversity nudge — only meaningful when
    # there is a real preference or taste signal to diversify around. With
    # neither, novelty alone would rank obscure / low-rated titles first
    # (an inversion of quality). In that degenerate case, spend the same 0.15
    # weight on a mild quality prior instead (spec §9.3 allows `external_rating`
    # as a low-weight quality floor).
    has_signal = preference_match > 0.0 or taste_match > 0.0
    if has_signal:
        diversity = novelty
        exp.novelty_high = novelty >= 0.6
    else:
        diversity = _clamp((item.external_rating or 6.0) / 10.0)
        exp.novelty_high = False

    score = (
        W_PREF * preference_match
        + W_TASTE * taste_match
        + W_NOVELTY * diversity
        - penalty
    )
    return ScoredCandidate(item, round(score, 4), round(taste_match, 4), exp)


def rank(
    items: list[NormalizedMedia],
    prefs: PreferenceObject,
    taste: TasteProfile,
    limit: int,
) -> list[ScoredCandidate]:
    scored = [score_candidate(it, prefs, taste) for it in items]
    scored.sort(key=lambda s: (s.score, s.tiebreak), reverse=True)
    return scored[:limit]
