"""Controlled vocabularies for the deterministic preference parser and for
scoring's mood/tone sub-signal (spec §7, §9.1).

Kept deliberately small and constant. The mood vocabulary itself lives in
`normalization.MOOD_TAG_VOCABULARY` (spec §6.4); this module adds the synonym
and genre-hint maps the fallback needs.
"""
from __future__ import annotations

from app.services.normalization import MOOD_TAG_VOCABULARY

# Normalised genre labels we recognise in free text. Superset of the common
# TMDb genres plus a few book-ish subjects. Matching is case-insensitive.
GENRE_VOCABULARY: tuple[str, ...] = (
    "action",
    "adventure",
    "animation",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "family",
    "fantasy",
    "history",
    "horror",
    "music",
    "mystery",
    "romance",
    "science fiction",
    "thriller",
    "war",
    "western",
    "fiction",
    "nonfiction",
    "biography",
    "memoir",
    "poetry",
    "self-help",
    "young adult",
)

# free-text token -> canonical genre label
GENRE_SYNONYMS: dict[str, str] = {
    "sci-fi": "science fiction",
    "scifi": "science fiction",
    "sf": "science fiction",
    "rom-com": "romance",
    "romcom": "romance",
    "romantic comedy": "romance",
    "documentaries": "documentary",
    "docs": "documentary",
    "thrillers": "thriller",
    "whodunit": "mystery",
    "noir": "crime",
    "historical": "history",
    "non-fiction": "nonfiction",
    "ya": "young adult",
    "kids": "family",
    "children": "family",
    "superhero": "action",
    "animated": "animation",
    "anime": "animation",
}

# tone words recognised in free text (spec §7 `tone` examples)
TONE_VOCABULARY: tuple[str, ...] = (
    "light",
    "dark",
    "bittersweet",
    "uplifting",
    "serious",
    "funny",
    "gritty",
    "hopeful",
    "melancholic",
)

TONE_SYNONYMS: dict[str, str] = {
    "lighthearted": "light",
    "light-hearted": "light",
    "heavy": "dark",
    "sad": "melancholic",
    "hopeful": "uplifting",
    "feelgood": "uplifting",
    "feel-good": "uplifting",
}

# mood synonyms -> a tag in MOOD_TAG_VOCABULARY
MOOD_SYNONYMS: dict[str, str] = {
    "cosy": "cozy",
    "comforting": "cozy",
    "comfort": "cozy",
    "scary": "tense",
    "suspenseful": "tense",
    "nail-biting": "tense",
    "feel good": "feel-good",
    "feelgood": "feel-good",
    "happy": "feel-good",
    "smart": "cerebral",
    "thought-provoking": "cerebral",
    "thoughtful": "cerebral",
    "thinky": "cerebral",
    "twisty": "cerebral",
    "fun": "escapist",
    "adventurous": "escapist",
    "sweet": "wholesome",
    "heartwarming": "wholesome",
    "depressing": "bleak",
    "grim": "bleak",
    "sombre": "bleak",
    "somber": "bleak",
    "gloomy": "dark",
    "moody": "dark",
    "energetic": "high-energy",
    "fast-paced": "high-energy",
    "slow": "slow-burn",
    "slow burn": "slow-burn",
    "sad": "bittersweet",
    "wistful": "bittersweet",
    "love story": "romantic",
    "romance": "romantic",
}

# mood/tone term -> genre labels that express it. Used by scoring when a fresh
# candidate has no `mood_tags` yet (spec §9.1: "mood_tags vs mood/tone").
MOOD_TONE_GENRE_HINTS: dict[str, set[str]] = {
    "cozy": {"comedy", "family", "romance"},
    "tense": {"thriller", "horror", "crime", "mystery", "war"},
    "feel-good": {"comedy", "family", "animation", "romance", "music"},
    "dark": {"thriller", "horror", "crime", "drama", "war", "mystery"},
    "bittersweet": {"drama", "romance"},
    "slow-burn": {"drama", "mystery"},
    "high-energy": {"action", "adventure"},
    "cerebral": {"science fiction", "mystery", "drama", "documentary", "history"},
    "escapist": {"fantasy", "adventure", "science fiction", "animation"},
    "romantic": {"romance"},
    "bleak": {"drama", "war", "history"},
    "wholesome": {"family", "animation", "comedy", "music"},
    "light": {"comedy", "family", "animation", "romance"},
    "uplifting": {"comedy", "family", "music", "drama"},
    "serious": {"drama", "history", "war", "documentary"},
    "funny": {"comedy"},
    "gritty": {"crime", "thriller", "war"},
    "melancholic": {"drama", "romance"},
    "hopeful": {"drama", "family"},
}

LENGTH_WORDS: dict[str, str] = {
    "short": "short",
    "quick": "short",
    "brief": "short",
    "bite-sized": "short",
    "bitesized": "short",
    "snackable": "short",
    "medium": "medium",
    "mid-length": "medium",
    "long": "long",
    "lengthy": "long",
    "epic": "long",
    "sprawling": "long",
    "doorstopper": "long",
}

INTENSITY_WORDS: dict[str, str] = {
    "intense": "high",
    "high-stakes": "high",
    "gripping": "high",
    "heart-pounding": "high",
    "adrenaline": "high",
    "moderate": "medium",
    "gentle": "low",
    "chill": "low",
    "relaxing": "low",
    "low-key": "low",
    "calm": "low",
    "easy": "low",
    "cozy": "low",
}

RECENT_WORDS = (
    "recent",
    "new",
    "latest",
    "modern",
    "current",
    "this year",
    "last few years",
    "past few years",
    "recently",
)
CLASSIC_WORDS = ("classic", "old", "older", "vintage", "retro", "golden age")

# language name -> ISO 639-1 (TMDb `with_original_language`)
LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "english": "en",
    "korean": "ko",
    "japanese": "ja",
    "mandarin": "zh",
    "chinese": "zh",
    "cantonese": "zh",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "hindi": "hi",
    "tamil": "ta",
    "telugu": "te",
    "malayalam": "ml",
    "kannada": "kn",
    "bengali": "bn",
    "marathi": "mr",
    "portuguese": "pt",
    "russian": "ru",
    "arabic": "ar",
    "turkish": "tr",
    "thai": "th",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "polish": "pl",
    "dutch": "nl",
}

# ISO 639-1 -> Open Library's 3-letter code (best effort; unknowns pass through)
_OL_LANG_3: dict[str, str] = {
    "en": "eng",
    "ko": "kor",
    "ja": "jpn",
    "zh": "chi",
    "fr": "fre",
    "es": "spa",
    "de": "ger",
    "it": "ita",
    "hi": "hin",
    "pt": "por",
    "ru": "rus",
    "ar": "ara",
    "nl": "dut",
    "sv": "swe",
    "pl": "pol",
    "tr": "tur",
}

MOOD_VOCABULARY: tuple[str, ...] = MOOD_TAG_VOCABULARY


def language_to_code(name_or_code: str) -> str | None:
    """Map a language name or code to ISO 639-1; None if unrecognised."""
    key = (name_or_code or "").strip().lower()
    if not key:
        return None
    if key in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[key]
    if len(key) == 2 and key.isalpha():
        return key
    return None


def language_to_ol_code(name_or_code: str) -> str | None:
    code = language_to_code(name_or_code)
    if code is None:
        return None
    return _OL_LANG_3.get(code, code)
