# Personal Media Companion

One library for movies, TV series, and books, with natural-language
recommendations. Single-user, no login.

See [`spec.md`](./spec.md) for requirements and [`plan.md`](./plan.md) for the
implementation plan. This repo follows the plan phase by phase.

## Repository layout

```
backend/    FastAPI + SQLAlchemy + Alembic API (holds all secrets)
frontend/   Next.js (App Router) UI (no secrets; talks only to the backend)
```

## Local development

### Prerequisites

- Python 3.12+
- Node.js 18.18+
- PostgreSQL 16 running locally

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # then fill in values as phases require
createdb media_companion        # once
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health>
- API docs: <http://localhost:8000/docs>
- Tests: `.venv/bin/pytest`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_BASE_URL defaults to localhost:8000
npm run dev
```

Open <http://localhost:3000>. The home page shows the live backend health
status.

## Deployment (split topology, spec §15 D2)

- **Backend + Postgres:** Render blueprint at `backend/render.yaml`
  (or Railway using `backend/Dockerfile`). The start hook
  (`backend/start.sh`) runs `alembic upgrade head` before serving.
- **Frontend:** Vercel, root directory `frontend/`. Set
  `NEXT_PUBLIC_API_BASE_URL` to the deployed backend URL.
- Set `FRONTEND_ORIGIN` on the backend to the deployed Vercel URL for CORS.

### Required environment variables

| Where | Variable | Purpose |
|---|---|---|
| Backend | `DATABASE_URL` | Postgres connection string |
| Backend | `ENV` | `production` in deploys |
| Backend | `FRONTEND_ORIGIN` | allowed CORS origin(s), comma-separated |
| Backend | `TMDB_API_KEY` | TMDb v3 API key (Phase 1) |
| Backend | `GOOGLE_BOOKS_API_KEY` | optional; Google Books fallback (Phase 6) |
| Backend | `ANTHROPIC_API_KEY` | Claude API (Phase 4) |
| Frontend | `NEXT_PUBLIC_API_BASE_URL` | backend base URL |

No secret is ever committed or shipped to the browser (spec FR8).

## Phase status

- [x] Phase 0 — live skeleton (backend + frontend + Postgres + migrations + CORS)
- [ ] Phase 1 — data model + external ingestion
- [ ] Phase 2 — library CRUD + UI
- [ ] Phase 3 — taste profile
- [ ] Phase 4 — single-turn recommendations (MVP deploy checkpoint)
- [ ] Phase 5 — clarification turn
- [ ] Phase 6 — robustness & completeness
- [ ] Phase 7 — acceptance pass & deploy hardening
