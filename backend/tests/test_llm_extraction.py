"""Phase 4: the LLM extraction layer (spec §7, §8.3, §10).

Covers the provider-agnostic selector, the Gemini adapter's parsing/bounding,
and the deterministic fallback parser. No network.
"""
from __future__ import annotations

import pytest

from app.services.llm import get_extractor, parse_preferences
from app.services.llm.gemini import GeminiExtractor


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def test_get_extractor_disabled_without_key(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert get_extractor() is None
    get_settings.cache_clear()


def test_get_extractor_none_provider(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("GEMINI_API_KEY", "irrelevant")
    assert get_extractor() is None
    get_settings.cache_clear()


def test_get_extractor_returns_gemini_when_configured(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    extractor = get_extractor()
    assert isinstance(extractor, GeminiExtractor)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# Gemini adapter: parsing + never-raises contract
# --------------------------------------------------------------------------- #
def test_gemini_parses_structured_json(monkeypatch):
    ex = GeminiExtractor(api_key="k")
    monkeypatch.setattr(
        ex,
        "_raw_call",
        lambda _t: (
            '{"genres":["Crime","Thriller"],"mood":["tense"],"tone":["dark"],'
            '"media_type":["series"],"language":["ko"],"length":"short",'
            '"intensity":null,"release_named":"recent","avoid":["romance"],'
            '"explicit_fields":["genres","language"]}'
        ),
    )
    prefs = ex.extract("a tense korean crime thriller, recent, no romance")
    assert prefs is not None
    assert prefs.genres == ["Crime", "Thriller"]
    assert prefs.media_type == ["series"]
    assert prefs.length == "short"
    assert prefs.release_period == "recent"
    assert prefs.avoid == ["romance"]
    assert prefs.explicit_fields == ["genres", "language"]


def test_gemini_reassembles_year_window(monkeypatch):
    ex = GeminiExtractor(api_key="k")
    monkeypatch.setattr(
        ex,
        "_raw_call",
        lambda _t: '{"release_from_year":1970,"release_to_year":1979,"genres":[]}',
    )
    prefs = ex.extract("70s movies")
    assert prefs is not None
    rp = prefs.release_period
    assert getattr(rp, "from_year", None) == 1970 and getattr(rp, "to_year", None) == 1979


def test_gemini_returns_none_on_bad_output(monkeypatch):
    ex = GeminiExtractor(api_key="k")
    monkeypatch.setattr(ex, "_raw_call", lambda _t: "not json at all")
    assert ex.extract("whatever") is None  # -> caller uses the deterministic fallback


def test_gemini_returns_none_when_sdk_raises(monkeypatch):
    ex = GeminiExtractor(api_key="k")

    def boom(_t):
        raise RuntimeError("network")

    monkeypatch.setattr(ex, "_raw_call", boom)
    assert ex.extract("whatever") is None


def test_gemini_empty_request_is_none():
    assert GeminiExtractor(api_key="k").extract("   ") is None


# --------------------------------------------------------------------------- #
# Deterministic fallback parser (spec §8.3)
# --------------------------------------------------------------------------- #
def test_fallback_extracts_rich_request():
    p = parse_preferences(
        "a dark, tense Korean crime thriller series with short episodes, avoid romance"
    )
    assert set(p.genres) == {"crime", "thriller"}
    assert "tense" in p.mood and "dark" in p.mood
    assert p.language == ["korean"]
    assert p.media_type == ["series"]
    assert p.length == "short"
    assert p.avoid == ["romance"]
    assert "romance" not in p.genres  # negation wins over the positive match
    assert p.is_sufficient()


def test_fallback_sparse_request_is_not_sufficient():
    p = parse_preferences("something to watch tonight")
    assert p.genres == [] and p.mood == [] and p.explicit_fields == []
    assert not p.is_sufficient()


def test_fallback_negation_pulls_avoid_and_blanks_it():
    p = parse_preferences("a fun movie, no horror")
    assert p.avoid == ["horror"]
    assert "horror" not in p.genres
    assert p.media_type == ["movie"]


def test_fallback_named_period_and_language():
    p = parse_preferences("classic French films")
    assert p.release_period == "classic"
    assert p.language == ["french"]
    assert "release_period" in p.explicit_fields


def test_fallback_decade_window():
    p = parse_preferences("sci-fi from the 1980s")
    rp = p.release_period
    assert getattr(rp, "from_year", None) == 1980 and getattr(rp, "to_year", None) == 1989
    assert "science fiction" in p.genres
