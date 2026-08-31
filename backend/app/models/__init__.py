"""SQLAlchemy models. Importing this package registers every table on
``Base.metadata`` so Alembic autogenerate and ``create_all`` see them all.
"""
from app.models.library import LibraryEntry, SeriesProgress
from app.models.media import MediaItem
from app.models.recommendation import RecommendationSession
from app.models.taste import TasteProfile

__all__ = [
    "MediaItem",
    "LibraryEntry",
    "SeriesProgress",
    "RecommendationSession",
    "TasteProfile",
]
