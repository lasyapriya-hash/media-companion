"""Enumerations shared by models and schemas (spec §6.2)."""
import enum


class MediaType(str, enum.Enum):
    movie = "movie"
    series = "series"
    book = "book"


class MediaSource(str, enum.Enum):
    tmdb = "tmdb"
    open_library = "open_library"
    google_books = "google_books"


class LibraryStatus(str, enum.Enum):
    want = "want"
    in_progress = "in_progress"
    completed = "completed"
    dropped = "dropped"


class SessionState(str, enum.Enum):
    extracting = "extracting"
    needs_clarification = "needs_clarification"
    awaiting_answer = "awaiting_answer"
    ranking = "ranking"
    results = "results"
    error = "error"


def enum_values(e: type[enum.Enum]) -> list[str]:
    """For SQLAlchemy Enum(values_callable=...): persist member values."""
    return [m.value for m in e]
