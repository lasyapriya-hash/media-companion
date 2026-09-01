"""mood-tag classifier: feature-gated on an LLM provider, never raises
(spec §6.4; Phase 6 — Gemini via the shared LLM layer, no Anthropic).
"""
from app.services import mood_tags
from app.services.normalization import MOOD_TAG_VOCABULARY


def test_disabled_without_llm_provider(monkeypatch):
    # conftest sets LLM_PROVIDER=none -> gemini_target() is None -> disabled
    assert mood_tags.is_enabled() is False
    result = mood_tags.classify_mood_tags(
        title="Anything", description="x", genres=["Drama"], media_type="movie"
    )
    assert result == []


def test_enabled_when_gemini_configured(monkeypatch):
    monkeypatch.setattr(mood_tags, "gemini_target", lambda: ("test-key", "gemini-2.5-flash"))
    assert mood_tags.is_enabled() is True


def test_enabled_but_provider_error_returns_empty(monkeypatch):
    monkeypatch.setattr(mood_tags, "is_enabled", lambda: True)

    def boom(_prompt):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(mood_tags, "_call_llm", boom)
    result = mood_tags.classify_mood_tags(
        title="Anything", description="x", genres=["Drama"], media_type="movie"
    )
    assert result == []


def test_enabled_parses_json_array_response(monkeypatch):
    monkeypatch.setattr(mood_tags, "is_enabled", lambda: True)
    monkeypatch.setattr(
        mood_tags,
        "_call_llm",
        lambda _p: 'Here you go: ["cozy", "wholesome"]',
    )
    result = mood_tags.classify_mood_tags(
        title="A", description="b", genres=[], media_type="book"
    )
    assert result == ["cozy", "wholesome"]


def test_coerce_tags_filters_to_vocabulary():
    raw = ["Cozy", "cozy", "not-a-real-tag", "TENSE", 42, "bleak"]
    coerced = mood_tags._coerce_tags(raw)
    assert coerced == ["cozy", "tense", "bleak"]
    assert all(t in MOOD_TAG_VOCABULARY for t in coerced)


def test_coerce_tags_caps_length():
    coerced = mood_tags._coerce_tags(list(MOOD_TAG_VOCABULARY))
    assert len(coerced) == mood_tags.MAX_TAGS
