"""Phase 2: mood-tag classifier is feature-gated and never raises (spec §6.4;
ANTHROPIC_API_KEY must not be a hard dependency).
"""
from app.services import mood_tags
from app.services.normalization import MOOD_TAG_VOCABULARY


def test_disabled_without_api_key(monkeypatch):
    monkeypatch.setattr(mood_tags, "is_enabled", lambda: False)
    result = mood_tags.classify_mood_tags(
        title="Anything", description="x", genres=["Drama"], media_type="movie"
    )
    assert result == []


def test_enabled_but_provider_error_returns_empty(monkeypatch):
    monkeypatch.setattr(mood_tags, "is_enabled", lambda: True)

    def boom(_prompt):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(mood_tags, "_call_anthropic", boom)
    result = mood_tags.classify_mood_tags(
        title="Anything", description="x", genres=["Drama"], media_type="movie"
    )
    assert result == []


def test_enabled_parses_json_array_response(monkeypatch):
    monkeypatch.setattr(mood_tags, "is_enabled", lambda: True)
    monkeypatch.setattr(
        mood_tags,
        "_call_anthropic",
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
