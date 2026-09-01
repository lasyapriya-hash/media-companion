"""Phase 6: Open Library -> Google Books fallback wiring (spec §15 D1, §5.4)."""
from __future__ import annotations

import pytest

from app.schemas.media import NormalizedMedia
from app.services import search as search_svc
from app.services.recommendations import _book_link
from app.services.recommendations.candidates import build_candidates
from app.models.taste import TasteProfile
from app.schemas.preference import PreferenceObject


def _book(sid, *, source="open_library", **raw):
    return NormalizedMedia(
        source=source, source_id=sid, type="book", title=f"Book {sid}",
        genres=["Fantasy"], raw_metadata=raw or {},
    )


class _Stub:
    def __init__(self, result=None, exc=None):
        self.result = result if result is not None else []
        self.exc = exc
        self.calls = 0

    def search(self, *a, **k):
        self.calls += 1
        if self.exc:
            raise self.exc
        return list(self.result)

    def discover(self, *a, **k):
        return self.search(*a, **k)


# --------------------------------------------------------------------------- #
# search_media
# --------------------------------------------------------------------------- #
def test_search_uses_google_books_when_open_library_empty(monkeypatch):
    ol, gb = _Stub(result=[]), _Stub(result=[_book("gb1", source="google_books")])
    monkeypatch.setattr(search_svc, "openlibrary_client", lambda: ol)
    monkeypatch.setattr(search_svc, "google_books_client", lambda: gb)
    monkeypatch.setattr(search_svc, "tmdb_client", lambda: _Stub(result=[]))

    out = search_svc.search_media("dune", media_type="book")
    assert [m.source for m in out] == ["google_books"]
    assert ol.calls == 1 and gb.calls == 1


def test_search_uses_google_books_when_open_library_errors(monkeypatch):
    ol = _Stub(exc=RuntimeError("OL down"))
    gb = _Stub(result=[_book("gb2", source="google_books")])
    monkeypatch.setattr(search_svc, "openlibrary_client", lambda: ol)
    monkeypatch.setattr(search_svc, "google_books_client", lambda: gb)
    monkeypatch.setattr(search_svc, "tmdb_client", lambda: _Stub(result=[]))

    out = search_svc.search_media("dune", media_type="book")
    assert [m.source for m in out] == ["google_books"]


def test_search_prefers_open_library_when_it_has_results(monkeypatch):
    ol = _Stub(result=[_book("ol1")])
    gb = _Stub(result=[_book("gb3", source="google_books")])
    monkeypatch.setattr(search_svc, "openlibrary_client", lambda: ol)
    monkeypatch.setattr(search_svc, "google_books_client", lambda: gb)
    monkeypatch.setattr(search_svc, "tmdb_client", lambda: _Stub(result=[]))

    out = search_svc.search_media("dune", media_type="book")
    assert [m.source for m in out] == ["open_library"]
    assert gb.calls == 0


# --------------------------------------------------------------------------- #
# recommendation candidates
# --------------------------------------------------------------------------- #
def test_candidate_books_fall_back_to_google_books(monkeypatch):
    import app.services.recommendations.candidates as cand

    monkeypatch.setattr(cand, "openlibrary_client", lambda: _Stub(exc=RuntimeError("down")))
    gb = _Stub(result=[_book("gbc", source="google_books")])
    monkeypatch.setattr(cand, "google_books_client", lambda: gb)

    prefs = PreferenceObject(media_type=["book"], genres=["Fantasy"])
    items, all_failed = build_candidates(prefs, TasteProfile(id=1))
    assert not all_failed
    assert [m.source for m in items] == ["google_books"]


def test_candidate_books_all_failed_when_both_sources_down(monkeypatch):
    import app.services.recommendations.candidates as cand

    monkeypatch.setattr(cand, "openlibrary_client", lambda: _Stub(exc=RuntimeError("down")))
    monkeypatch.setattr(cand, "google_books_client", lambda: _Stub(exc=RuntimeError("down")))

    prefs = PreferenceObject(media_type=["book"], genres=["Fantasy"])
    items, all_failed = build_candidates(prefs, TasteProfile(id=1))
    assert items == [] and all_failed is True


# --------------------------------------------------------------------------- #
# _book_link (spec §5.4 — only when the API returns one)
# --------------------------------------------------------------------------- #
def test_book_link_google_books_for_sale():
    item = _book("gb", source="google_books",
                 saleInfo={"saleability": "FOR_SALE", "buyLink": "https://play.google.com/b"})
    assert _book_link(item) == "https://play.google.com/b"


def test_book_link_google_books_omitted_when_none():
    assert _book_link(_book("gb", source="google_books")) is None


def test_book_link_open_library_only_when_readable():
    assert _book_link(_book("ol", ebook_access="public")).startswith("https://openlibrary.org/works/")
    assert _book_link(_book("ol", ebook_access="no_ebook")) is None
