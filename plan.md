# Personal Media Companion — Implementation Plan

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-08-31 |
| **Basis** | `spec.md` v1.0 (approved) — this plan adds **no** scope beyond it |
| **Priority** | Get a working MVP deployed to a public URL early, then layer the rest on a live app |
| **Status** | Awaiting approval — do not implement yet |

---

## 1. Guiding Principles

1. **Deploy before building features.** Stand up an empty-but-live frontend +
   backend + Postgres before writing features, so deployment risk is retired
   first.
2. **Vertical slices.** Each phase ends with something demonstrable and tested,
   not a half-built layer.
3. **MVP = the core loop deployed.** Search → add → track → single-turn
   recommendation with reasons and availability. Everything else is layered on
   top of a live app.
4. **Claude stays on a bounded path** (spec §8.2, §10): preference extraction,
   the one clarifying question, `mood_tags` classification, per-result reason
   text. Never candidate generation.
5. **Secrets server-side only** (spec FR8): the frontend talks only to the
   backend; all API keys are backend env vars.
6. **Follow the spec's open-decision defaults** (spec §15) unless a blocker
   forces otherwise: Open Library primary, split deploy, N = 8, weights
   0.50/0.35/0.15, slider rating input, `mood_tags` computed on add.

---

## 2. Architecture & Component Responsibilities

### 2.1 Frontend — Next.js / React (Vercel)

| Responsibility | Notes |
|---|---|
| Search UI | free-text query, type filter, results grid |
| Library UI | list + filter by status/type, item cards |
| Item detail & edit | status, rating (slider, 0.5 steps), review, favourite; series season/episode progress |
| Recommendation UI | request box; render the single optional clarifying question; ranked results with reason + availability |
| Responsive layout | desktop + mobile widths (spec NFR1) |

Holds **no** API keys. Only env var is the backend base URL.

### 2.2 Backend — FastAPI / Python (Render or Railway)

| Module | Responsibility |
|---|---|
| **API layer** | REST endpoints for search, library CRUD, series progress, recommendation session |
| **External clients** | TMDb client (search, details, watch providers region IN); Book client (Open Library primary, Google Books fallback) |
| **Normalization** | map provider payloads → common `media_item` shape (spec §6.1, §6.4 buckets) |
| **Library service** | upsert `media_item`, create/update `library_entry` + `series_progress` |
| **Taste-profile service** | recompute derived profile on every rating/status change (spec §6.3, FR9) |
| **Recommendation orchestrator** | the session state machine (spec §8.1); sparsity rule (§8.3); candidate build → exclude → score → top-N; fallbacks |
| **Scoring** | movie/series weighted score; book genre + mood-tag overlap (spec §9) |
| **Claude client** | extraction, clarifying question, `mood_tags`, reason text |
| **Availability service** | watch-provider lookup + "unknown" fallback; book link passthrough or clean omission (spec §5.4) |

Holds all secrets. Applies DB migrations on deploy.

### 2.3 Database — Postgres

Tables per spec §6.1: `media_item`, `library_entry`, `series_progress`,
`taste_profile` (derived record), optional non-durable `recommendation_session`.
Must survive redeploys (spec §13).

### 2.4 External services

- **TMDb** — movie/series search, metadata, watch providers (IN).
- **Open Library / Google Books** — book search and metadata.
- **Anthropic API (Claude)** — the four bounded call types above.

---

## 3. Data Flow

### 3.1 Search & add

```
FE  ──GET /search?q&type──▶  BE
                             BE ──▶ TMDb / Book API ──▶ raw payloads
                             BE: normalize → common media shape
FE  ◀── normalized results ── BE

FE  ──POST /library {source, source_id, type}──▶ BE
                             BE: upsert media_item (cache raw_metadata)
                             BE ──▶ Claude: classify mood_tags (bounded, one-shot)
                             BE: insert library_entry (status defaults to "want")
FE  ◀── created entry ────── BE
```

### 3.2 Library management

```
FE  ──PATCH /library/{id} {status|rating|review|favourite}──▶ BE
FE  ──PUT   /library/{id}/progress {season, episode}────────▶ BE   (series only)
                             BE: write library_entry / series_progress
                             BE: recompute taste_profile  (on status or rating change)
FE  ◀── updated entry ────── BE
```

### 3.3 Recommendation (full flow, spec §8.1)

```
FE  ──POST /recommendations {request}──▶ BE
     BE: create session (state = extracting)
     BE ──▶ Claude: extract preference object (spec §7)
     BE: sparsity check (spec §8.3)
        ├─ sufficient ────────────────────────────────┐
        └─ sparse:                                     │
             BE: state = needs_clarification           │
             FE ◀── { question } ── BE                 │
             FE ──POST /recommendations/{id}/answer──▶ BE
             BE ──▶ Claude: re-extract from answer
             BE: merge (new non-null wins; avoid = union)
             BE: clarification_used = true             │
                                                       ▼
     BE: state = ranking
     BE: build candidate queries from preference object
     BE ──▶ TMDb / Book API: fetch candidates
     BE: exclude library status completed/dropped; hard-filter `avoid`
     BE: read taste_profile from DB
     BE: score (spec §9.1 movies/series | §9.2 books); apply novelty term
     BE: take top N (default 8)
     BE ──▶ Claude: generate one-sentence reason per result
     BE ──▶ TMDb watch providers (IN) per movie/series result; book link passthrough
     BE: state = results
FE  ◀── ranked list [ item + score + reason + availability ] ── BE
```

**Invariants enforced in the orchestrator:** `awaiting_answer` entered at most
once per session; `ranking` always yields a non-empty list unless all data APIs
are down (→ `error`); candidate generation never routes through Claude.

### 3.4 Failure paths (spec NFR2)

- Any external call: timeout + retry-once + typed fallback. TMDb providers
  missing → "availability unknown". Book link missing → field omitted. Primary
  book API empty → Google Books fallback. Claude failure during ranking →
  return scored list with a generic-but-honest reason line rather than erroring.
- All data APIs unreachable → session `error` state with a user-visible,
  non-crashing message.

---

## 4. Implementation Phases & Feature Order

Each phase lists **deliverables** and **verification checkpoints** (mapped to
spec FR / NFR / §16 acceptance criteria, shown as `AC:`).

### Phase 0 — Live skeleton  *(MVP-critical)*

**Deliverables**
- Repo scaffold: FastAPI backend, Next.js frontend.
- Postgres provisioned (Render/Railway); `DATABASE_URL` wired.
- Migration tooling; run-on-deploy hook.
- Backend `/health`; frontend loads and calls `/health` through the backend
  base URL.
- Env var plumbing for `TMDB_API_KEY`, book API key (if needed),
  `ANTHROPIC_API_KEY` — set in the deploy platform, absent from the repo and
  the client bundle.
- Both halves deployed to public URLs; CORS configured.

**Verification**
- [ ] Backend public URL returns `/health` 200 and confirms a live DB
      connection.
- [ ] Frontend public URL renders and reaches the backend.
- [ ] `git grep` shows no keys committed; built client bundle contains no keys
      (`AC:` no hardcoded keys).

### Phase 1 — Data model + external ingestion  *(MVP-critical)*

**Deliverables**
- Migrations for `media_item`, `library_entry`, `series_progress`,
  `recommendation_session`; `taste_profile` record.
- TMDb client: search, details, watch providers (region IN).
- Book client: Open Library search + details; **Google Books fallback deferred
  to Phase 6** (D1 default allows single-API operation).
- Normalization layer → common media shape, including `length_bucket` mapping
  (spec §6.4).

**Verification**
- [ ] Unit tests: normalization for a movie, a series, a book (field coverage,
      bucket thresholds).
- [ ] Integration smoke: live search for each type returns normalized items.
- [ ] Watch-provider fetch returns providers for a known title and the
      "unknown" sentinel for one with no IN data.

### Phase 2 — Library CRUD + UI  *(MVP-critical)*

**Deliverables**
- Endpoints: `GET /search`, `POST /library`, `GET /library`,
  `PATCH /library/{id}`, `PUT /library/{id}/progress`.
- `mood_tags` classification call fires on `POST /library` (spec §6.4, D6).
- Frontend: search page + results, add-to-library, library list with
  status/type filters, item detail with status / rating slider / review /
  favourite, series progress control.

**Verification**
- [ ] Add a movie, a series, and a book to the library (`AC:` search & add).
- [ ] Set status, rating, review on each of the three types (`AC:`).
- [ ] Track season/episode progress on a series (`AC:`).
- [ ] `mood_tags` populated on newly added items.
- [ ] FR1, FR2 satisfied.

### Phase 3 — Taste profile  *(MVP-critical, minimal version)*

**Deliverables**
- Recompute function: favourite genres, favourite languages,
  `avg_rating_by_genre`, `avg_rating_by_language`, `completion_rate`.
- `drop_patterns` and per-genre completion rate — **minimal now, refine in
  Phase 6** if time allows.
- Hook recompute into every status change and every rating change.

**Verification**
- [ ] Unit tests: profile fields correct over a seeded library.
- [ ] Changing a rating or status triggers recompute (FR9).

### Phase 4 — Single-turn recommendations  *(MVP-critical — MVP DEPLOY GATE)*

**Deliverables**
- Preference object schema + Claude extraction call (spec §7).
- Candidate generation from the preference object via data APIs.
- Scoring: movie/series weighted (spec §9.1); book overlap (spec §9.2);
  novelty term; exclude completed/dropped; hard-filter `avoid`.
- Per-result reason text via Claude.
- Availability attached to each result.
- `POST /recommendations` returns a ranked list directly (no clarification
  path yet).
- Frontend: recommendation request box + ranked results with reason and
  availability.

**Verification**
- [ ] A free-text request returns a ranked list with request-specific reasons
      (`AC:`, FR3, FR4, FR6).
- [ ] "Not highest-rated" test (spec §9.3): a request whose mood/tone conflicts
      with the top-rated candidate does not rank that candidate #1 (`AC:`).
- [ ] Movie/series results use the taste profile; book results use
      genre/mood-tag matching (`AC:`).
- [ ] Availability shows for movies/series with provider data, "unknown"
      otherwise (`AC:`, FR7).
- [ ] Response time within the ~8 s demo target on a warm backend (NFR5).

> **▶ MVP DEPLOY CHECKPOINT** — after Phase 4, redeploy and confirm the full
> core loop works on the public URL. This is the earliest complete,
> demonstrable product.

### Phase 5 — Clarification turn  *(required for final acceptance; deferrable past the MVP deploy)*

**Deliverables**
- `recommendation_session` state machine (spec §8.1): `extracting →
  needs_clarification → awaiting_answer → ranking → results`, plus `error`.
- Sparsity rule (spec §8.3): the 3-condition sufficiency test.
- `POST /recommendations/{id}/answer`: re-extract, merge (new non-null wins;
  `avoid` union), set `clarification_used = true`.
- One-question invariant enforced by `clarification_used`.
- Fallback when still sparse at ranking time (taste-profile-only for
  movies/series; popularity-within-favourite-genres for books).
- Frontend: render the single question when present, then the list.

**Verification**
- [ ] Sparse request → exactly one question → ranked list (`AC:`, FR5).
- [ ] Rich request → ranked list with no question (`AC:`).
- [ ] No session ever emits a second question, including when the answer is
      empty/declined (`AC:`).
- [ ] Still-sparse-after-answer path returns a non-empty list via fallback.

### Phase 6 — Robustness & completeness  *(required for final acceptance)*

**Deliverables**
- Google Books fallback wired into the book client (D1).
- Error/timeout handling across all external calls; typed fallbacks per §3.4.
- Availability polish: consistent "unknown" state; clean book-link omission.
- `drop_patterns` / per-genre completion refinement in scoring penalty (spec
  §9.1) if not already complete.
- Remove any placeholder content; eliminate console/runtime errors.
- Mobile + desktop viewport pass.

**Verification**
- [ ] Induced API failure (bad key / forced timeout) surfaces no unhandled
      error (NFR2).
- [ ] No console or runtime errors during a full walkthrough (NFR4).
- [ ] No placeholder/lorem content anywhere (NFR3).
- [ ] Layout correct at mobile and desktop widths (NFR1).
- [ ] Book purchase/access link appears only when the API returns one (`AC:`).

### Phase 7 — Acceptance pass & deploy hardening  *(required)*

**Deliverables**
- Full §16 acceptance checklist run against the public URL.
- Secret audit: no keys in repo history or client bundle (FR8).
- Migration idempotency confirmed across a clean redeploy.
- Demo script / seed library for the review.

**Verification**
- [ ] Every box in spec §16 checked on the deployed app.
- [ ] Fresh redeploy preserves data and applies migrations cleanly.

---

## 5. MVP vs. Deferrable

### Must-have for the MVP deploy (Phases 0–4)

- Live frontend + backend + Postgres on public URLs, no secrets client-side.
- Search movies/series (TMDb) and books (Open Library).
- Add to library; set status / rating / review / favourite; series
  season/episode progress.
- Taste profile (minimal) recomputed on rating/status change.
- Single-turn natural-language recommendation: preference extraction →
  scored, ranked list → per-result reason → availability, demonstrably not
  "highest-rated first".

### Required for final acceptance, but deferrable past the first deploy (Phases 5–7)

- The one clarifying-question turn and the full session state machine
  (spec §8) — this is the flagged complexity risk, so it follows a working
  single-turn engine rather than blocking it.
- Google Books fallback (spec runs on the primary API alone until then).
- Error-handling hardening, "unknown"/omission polish, mobile pass,
  placeholder and console-error cleanup.
- Taste-profile refinement (`drop_patterns`, per-genre completion in the
  scoring penalty).

### Can be cut entirely only if scope must be reduced

- Google Books fallback (D1 default explicitly permits a single book API).
- Nothing else — every remaining item maps to a spec §16 acceptance
  criterion.

### Not in this plan (spec §17)

Book page/percentage progress, full taste-profile scoring for books,
multi-user/login, social features, streaming/hosting, unbounded clarification,
trained ML model, cross-session history.

---

## 6. Deployment Steps

Split topology (spec §15 D2 default): backend + Postgres on Render/Railway,
frontend on Vercel.

1. **Provision Postgres** on Render/Railway; capture `DATABASE_URL`.
2. **Backend service:**
   - Set env vars: `DATABASE_URL`, `TMDB_API_KEY`, book API key (if the chosen
     API needs one), `ANTHROPIC_API_KEY`, `FRONTEND_ORIGIN`.
   - Deploy hook runs DB migrations, then starts the app.
   - Expose `/health` (app + DB check).
3. **Frontend (Vercel):**
   - Set the single public env var to the backend base URL.
   - Confirm no secret env vars are exposed to the client.
4. **CORS:** backend allows the Vercel origin.
5. **Smoke test** both public URLs (Phase 0 verification).
6. **Redeploy at each phase boundary;** always re-run the current phase's
   verification against the live URL.
7. **MVP deploy checkpoint** after Phase 4.
8. **Final hardening** (Phase 7): secret audit on repo + built bundle,
   clean-redeploy migration check, seed a demo library.

---

## 7. Risk-Driven Sequencing Notes

- **Deployment risk** is retired in Phase 0, before any feature work.
- **Conversation-state complexity** (spec §18) is isolated to Phase 5 and sits
  behind a working single-turn engine, so a slip there still leaves a
  demonstrable product deployed.
- **Book API variance** (spec §18) is absorbed by shipping on Open Library
  alone first and adding the Google Books fallback only in Phase 6.
- **Claude latency** (spec §18, NFR5) is bounded by keeping Claude off the
  candidate path and precomputing `mood_tags` on add.
```
