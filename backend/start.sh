#!/usr/bin/env bash
# Deploy start hook: apply migrations, then launch the API.
# Used by Render (see render.yaml) and for local prod-like runs.
set -euo pipefail

echo "==> Running database migrations"
alembic upgrade head

echo "==> Starting API on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
