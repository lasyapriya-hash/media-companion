"""Shared test fixtures.

Tests run against a dedicated local database (`media_companion_test`) so they
never touch dev data. External APIs and the mood-tag classifier are stubbed by
default; individual tests opt back in.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://localhost/media_companion_test"
)
os.environ["ANTHROPIC_API_KEY"] = ""  # mood-tag feature off unless a test enables it
os.environ["LLM_PROVIDER"] = "none"  # preference extraction uses the deterministic
os.environ["GEMINI_API_KEY"] = ""  # fallback unless a test enables the LLM

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402

_ENUM_TYPES = ("media_source", "media_type", "session_state", "library_status")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        for name in _ENUM_TYPES:
            conn.execute(text(f"DROP TYPE IF EXISTS {name}"))
    Base.metadata.create_all(engine)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        for name in _ENUM_TYPES:
            conn.execute(text(f"DROP TYPE IF EXISTS {name}"))


@pytest.fixture()
def db_session():
    """Function-scoped session wrapped in a rolled-back transaction."""
    connection = engine.connect()
    trans = connection.begin()
    from sqlalchemy.orm import Session

    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _stub_enrichment(monkeypatch):
    """By default, persist the posted item verbatim (no details fetch)."""
    monkeypatch.setattr(
        "app.services.library._enrich", lambda item: item, raising=True
    )
