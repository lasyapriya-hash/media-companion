"""FastAPI application entrypoint.

Phase 0: app skeleton, CORS, and a /health endpoint that confirms a live
database connection. Feature routers are added in later phases.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import library as library_api
from app.api import search as search_api
from app.api import taste as taste_api
from app.config import get_settings
from app.db import engine

logger = logging.getLogger("uvicorn.error")
settings = get_settings()

app = FastAPI(title="Personal Media Companion API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(search_api.router)
app.include_router(library_api.router)
app.include_router(taste_api.router)


@app.get("/health")
def health() -> JSONResponse:
    """Liveness + database connectivity check.

    Returns 200 only when a `SELECT 1` against the configured database
    succeeds; 503 otherwise. The frontend uses this to confirm it can reach a
    healthy backend.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
        code = 200
    except Exception as exc:  # noqa: BLE001 - report any failure, don't crash
        logger.error("health check DB failure: %s", exc)
        db_status = "unavailable"
        code = 503

    return JSONResponse(
        status_code=code,
        content={
            "status": "ok" if code == 200 else "degraded",
            "service": "media-companion-api",
            "env": settings.env,
            "database": db_status,
        },
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "media-companion-api", "docs": "/docs", "health": "/health"}
