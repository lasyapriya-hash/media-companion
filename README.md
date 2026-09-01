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
- Tests: `.venv/bin/pytest` (unit + API). Live external-API smoke: `.venv/bin/pytest -m integration`
  (TMDb tests skip unless `TMDB_API_KEY` is set in `backend/.env`).
- Needs local databases `media_companion` and `media_companion_test`
  (`createdb media_companion media_companion_test`).
- Backfill mood tags once an LLM provider is configured (`LLM_PROVIDER=gemini`
  + `GEMINI_API_KEY`):
  `.venv/bin/python -m app.scripts.backfill_mood_tags`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_BASE_URL defaults to localhost:8000
npm run dev
```

Open <http://localhost:3000>: **Library** (browse/filter), **Search & add**
(discover and add items), and an item page for status / rating / review /
favourite and, for series, season/episode progress.

## Deployment (split topology, spec §15 D2)

- **Backend + Postgres:** Render blueprint at `backend/render.yaml`
  (or Railway using `backend/Dockerfile`). The start hook
  (`backend/start.sh`, tracked executable) runs `alembic upgrade head`
  before serving.
- **Frontend:** Vercel, root directory `frontend/`. Set
  `NEXT_PUBLIC_API_BASE_URL` to the deployed backend URL.
- Set `FRONTEND_ORIGIN` on the backend to the deployed frontend URL for CORS.

The LLM provider is **Gemini**, and it is optional: with no `GEMINI_API_KEY`
the app still runs — preference extraction uses a deterministic parser and
`mood_tags` classification is skipped. There is no Anthropic dependency.

### Environment variables

| Where | Variable | Required? | Purpose |
|---|---|---|---|
| Backend | `DATABASE_URL` | required | Postgres connection string (Render/Railway supply this) |
| Backend | `ENV` | required | `production` in deploys |
| Backend | `FRONTEND_ORIGIN` | required | allowed CORS origin(s), comma-separated — the deployed frontend URL |
| Backend | `TMDB_API_KEY` | required | TMDb v3 API key — movie/series search, metadata, watch providers |
| Backend | `LLM_PROVIDER` | optional | `gemini` (default) or `none` to disable the LLM entirely |
| Backend | `GEMINI_API_KEY` | optional | Google AI Studio key. Enables LLM preference extraction and `mood_tags`; without it a deterministic parser runs and `mood_tags` are skipped |
| Backend | `GEMINI_MODEL` | optional | overrides the Gemini model (default `gemini-2.5-flash`) |
| Backend | `GOOGLE_BOOKS_API_KEY` | optional | book-search **fallback** (Open Library is primary); a key just raises the rate limit |
| Frontend | `NEXT_PUBLIC_API_BASE_URL` | required | backend base URL (the only frontend var; not a secret) |

No secret is ever committed or shipped to the browser (spec FR8).

## Phase status

- [x] Phase 0 — live skeleton (backend + frontend + Postgres + migrations + CORS)
- [x] Phase 1 — data model + external ingestion (schema migration; TMDb + Open Library clients; normalization)
- [x] Phase 2 — library CRUD + UI (search/library endpoints; add + status/rating/review/favourite + series progress; `mood_tags` feature-gated on the LLM provider, with backfill script)
- [x] Phase 3 — taste profile (derived record recomputed on every rating/status change)
- [x] Phase 4 — single-turn recommendations (Gemini/deterministic-fallback preference extraction; deterministic candidate retrieval, scoring, ranking, reasons)
- [x] Phase 5 — clarification turn (one templated question when the request is sparse; session state machine)
- [x] Phase 6 — robustness & completeness (`mood_tags` on Gemini — no Anthropic; Google Books fallback; external-call retry/typed fallbacks; availability/book-link polish; scoring-penalty refinement)
- [ ] Phase 7 — acceptance pass & deploy hardening
