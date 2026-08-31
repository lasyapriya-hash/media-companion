"""Phase 1 unit verification: length-bucket thresholds and provider
normalization for a movie, a series, and a book. No network.
"""
from app.clients.openlibrary import normalize_ol_doc, normalize_ol_work
from app.clients.tmdb import (
    normalize_tmdb_details,
    normalize_tmdb_search,
    parse_watch_providers,
)
from app.schemas.media import LengthBucket
from app.services.normalization import MOOD_TAG_VOCABULARY, length_bucket


# --------------------------------------------------------------------------- #
# length_bucket thresholds (spec §6.4)
# --------------------------------------------------------------------------- #
def test_length_bucket_movie_thresholds():
    assert length_bucket("movie", runtime_minutes=89) == LengthBucket.short
    assert length_bucket("movie", runtime_minutes=90) == LengthBucket.medium
    assert length_bucket("movie", runtime_minutes=150) == LengthBucket.medium
    assert length_bucket("movie", runtime_minutes=151) == LengthBucket.long


def test_length_bucket_series_thresholds():
    assert length_bucket("series", episode_runtime_minutes=29) == LengthBucket.short
    assert length_bucket("series", episode_runtime_minutes=30) == LengthBucket.medium
    assert length_bucket("series", episode_runtime_minutes=50) == LengthBucket.medium
    assert length_bucket("series", episode_runtime_minutes=51) == LengthBucket.long


def test_length_bucket_book_thresholds():
    assert length_bucket("book", page_count=249) == LengthBucket.short
    assert length_bucket("book", page_count=250) == LengthBucket.medium
    assert length_bucket("book", page_count=500) == LengthBucket.medium
    assert length_bucket("book", page_count=501) == LengthBucket.long


def test_length_bucket_missing_measure_is_none():
    assert length_bucket("movie") is None
    assert length_bucket("series", episode_runtime_minutes=None) is None
    assert length_bucket("book", page_count=0) is None


def test_mood_vocabulary_is_fixed_and_nonempty():
    assert isinstance(MOOD_TAG_VOCABULARY, tuple)
    assert "cozy" in MOOD_TAG_VOCABULARY and "bleak" in MOOD_TAG_VOCABULARY


# --------------------------------------------------------------------------- #
# TMDb normalization
# --------------------------------------------------------------------------- #
def test_normalize_tmdb_movie_search_result():
    raw = {
        "id": 27205,
        "media_type": "movie",
        "title": "Inception",
        "overview": "A thief who steals corporate secrets...",
        "genre_ids": [28, 878, 12],
        "original_language": "en",
        "release_date": "2010-07-15",
        "vote_average": 8.4,
        "poster_path": "/inception.jpg",
    }
    genre_map = {28: "Action", 878: "Science Fiction", 12: "Adventure"}
    media = normalize_tmdb_search(raw, "movie", genre_map)

    assert media.source == "tmdb"
    assert media.source_id == "27205"
    assert media.type == "movie"
    assert media.title == "Inception"
    assert media.description.startswith("A thief")
    assert media.genres == ["Action", "Science Fiction", "Adventure"]
    assert media.language == "en"
    assert media.year == 2010
    assert media.external_rating == 8.4
    assert media.artwork_url == "https://image.tmdb.org/t/p/w500/inception.jpg"


def test_normalize_tmdb_movie_details_sets_runtime_and_bucket():
    raw = {
        "id": 27205,
        "title": "Inception",
        "overview": "...",
        "genres": [{"id": 878, "name": "Science Fiction"}],
        "original_language": "en",
        "release_date": "2010-07-15",
        "vote_average": 8.4,
        "poster_path": "/x.jpg",
        "runtime": 148,
    }
    media = normalize_tmdb_details(raw, "movie")
    assert media.runtime_minutes == 148
    assert media.length_bucket == LengthBucket.medium  # 90–150
    assert media.seasons is None


def test_normalize_tmdb_series_details_sets_seasons_episodes_bucket():
    raw = {
        "id": 1396,
        "name": "Breaking Bad",
        "overview": "...",
        "genres": [{"id": 18, "name": "Drama"}],
        "original_language": "en",
        "first_air_date": "2008-01-20",
        "vote_average": 8.9,
        "poster_path": "/bb.jpg",
        "number_of_seasons": 5,
        "number_of_episodes": 62,
        "episode_run_time": [47],
    }
    media = normalize_tmdb_details(raw, "series")
    assert media.type == "series"
    assert media.year == 2008
    assert media.seasons == 5
    assert media.episodes == 62
    assert media.episode_runtime_minutes == 47
    assert media.length_bucket == LengthBucket.medium  # 30–50
    assert media.runtime_minutes is None


def test_parse_watch_providers_available_for_region_in():
    results = {
        "IN": {
            "link": "https://www.themoviedb.org/movie/1396/watch?locale=IN",
            "flatrate": [{"provider_name": "Netflix"}],
            "rent": [{"provider_name": "Apple TV"}],
        },
        "US": {"flatrate": [{"provider_name": "AMC+"}]},
    }
    av = parse_watch_providers(results, "IN")
    assert av.region == "IN"
    assert av.status == "available"
    assert av.flatrate == ["Netflix"]
    assert av.rent == ["Apple TV"]
    assert av.link.endswith("locale=IN")


def test_parse_watch_providers_unknown_when_region_absent():
    results = {"US": {"flatrate": [{"provider_name": "Hulu"}]}}
    av = parse_watch_providers(results, "IN")
    assert av.status == "unknown"
    assert av.flatrate == [] and av.rent == [] and av.buy == []


def test_parse_watch_providers_unknown_when_region_has_no_offers():
    av = parse_watch_providers({"IN": {"link": "https://x"}}, "IN")
    assert av.status == "unknown"
    assert av.link == "https://x"


# --------------------------------------------------------------------------- #
# Open Library normalization
# --------------------------------------------------------------------------- #
def test_normalize_ol_search_doc():
    doc = {
        "key": "/works/OL27448W",
        "title": "The Lord of the Rings",
        "author_name": ["J. R. R. Tolkien"],
        "first_publish_year": 1954,
        "cover_i": 258027,
        "number_of_pages_median": 1178,
        "language": ["eng"],
        "subject": ["Fantasy fiction", "Adventure", "Middle Earth"],
        "ratings_average": 4.5,
    }
    media = normalize_ol_doc(doc)
    assert media.source == "open_library"
    assert media.source_id == "OL27448W"
    assert media.type == "book"
    assert media.title == "The Lord of the Rings"
    assert media.author == "J. R. R. Tolkien"
    assert media.page_count == 1178
    assert media.year == 1954
    assert media.language == "eng"
    assert media.external_rating == 9.0  # 4.5 * 2, normalized to 0–10
    assert media.artwork_url == "https://covers.openlibrary.org/b/id/258027-L.jpg"
    assert media.length_bucket == LengthBucket.long  # >500 pages
    assert "Fantasy fiction" in media.genres


def test_normalize_ol_work_details_extracts_description_and_subjects():
    payload = {
        "key": "/works/OL27448W",
        "title": "The Lord of the Rings",
        "description": {"type": "/type/text", "value": "An epic high-fantasy novel."},
        "subjects": ["Fantasy", "Quests"],
    }
    media = normalize_ol_work(payload)
    assert media.description == "An epic high-fantasy novel."
    assert media.genres == ["Fantasy", "Quests"]
    assert media.source_id == "OL27448W"


def test_normalize_ol_doc_missing_optionals_is_safe():
    media = normalize_ol_doc({"key": "/works/OL1W", "title": "Sparse Book"})
    assert media.title == "Sparse Book"
    assert media.author is None
    assert media.page_count is None
    assert media.length_bucket is None
    assert media.external_rating is None
    assert media.genres == []
