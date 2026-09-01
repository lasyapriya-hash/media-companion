"""Phase 6: Google Books as the book fallback (spec §15 D1, §5.4)."""
from __future__ import annotations

from app.clients.google_books import book_access_link, normalize_gb_volume
from app.schemas.media import LengthBucket


def _vol(**over):
    base = {
        "id": "gb123",
        "volumeInfo": {
            "title": "The Fifth Season",
            "authors": ["N. K. Jemisin"],
            "description": "A world ending, again.",
            "categories": ["Fiction", "Fantasy"],
            "language": "en",
            "publishedDate": "2015-08-04",
            "pageCount": 512,
            "averageRating": 4.3,
            "imageLinks": {"thumbnail": "http://books.google.com/x.jpg"},
        },
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def test_normalize_gb_volume_maps_fields():
    m = normalize_gb_volume(_vol())
    assert m.source == "google_books"
    assert m.source_id == "gb123"
    assert m.type == "book"
    assert m.title == "The Fifth Season"
    assert m.author == "N. K. Jemisin"
    assert m.genres == ["Fiction", "Fantasy"]
    assert m.language == "en"
    assert m.year == 2015
    assert m.page_count == 512
    assert m.external_rating == 8.6  # 4.3 * 2
    assert m.artwork_url == "https://books.google.com/x.jpg"  # forced https
    assert m.length_bucket == LengthBucket.long  # > 500 pages


def test_normalize_gb_volume_tolerates_missing_fields():
    m = normalize_gb_volume({"id": "x", "volumeInfo": {"title": "Untitled"}})
    assert m.title == "Untitled"
    assert m.author is None
    assert m.page_count is None
    assert m.external_rating is None
    assert m.length_bucket is None
    assert m.genres == []


# --------------------------------------------------------------------------- #
# Access link (spec §5.4 — only when the API actually returns one)
# --------------------------------------------------------------------------- #
def test_access_link_for_sale():
    v = _vol(saleInfo={"saleability": "FOR_SALE", "buyLink": "https://play.google.com/buy"})
    assert book_access_link(v) == "https://play.google.com/buy"


def test_access_link_partial_preview():
    v = _vol(accessInfo={"viewability": "PARTIAL", "webReaderLink": "https://books.google.com/read"})
    assert book_access_link(v) == "https://books.google.com/read"


def test_access_link_absent_when_not_available():
    assert book_access_link(_vol()) is None
    assert book_access_link(_vol(saleInfo={"saleability": "NOT_FOR_SALE"})) is None
    assert book_access_link(_vol(accessInfo={"viewability": "NO_PAGES"})) is None
